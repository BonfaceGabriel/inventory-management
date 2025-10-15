"""
Manual Payment Service

Handles creation and management of manual payment entries for payments
received outside the SMS parsing system (PDQ, Bank, Cash, etc.)
"""

from decimal import Decimal
from django.db import transaction as db_transaction
from django.utils import timezone
import hashlib
import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from payments.models import Transaction, ManualPayment
from payments.serializers import TransactionSerializer

logger = logging.getLogger(__name__)


class ManualPaymentService:
    """
    Service for creating and managing manual payment entries.

    Manual payments create both:
    1. A Transaction record (for consistency with SMS payments)
    2. A ManualPayment record (with payment method details)
    """

    @staticmethod
    def create_manual_payment(
        payment_method: str,
        payer_name: str,
        amount: Decimal,
        payment_date,
        created_by: str,
        reference_number: str = None,
        payer_phone: str = None,
        payer_email: str = None,
        notes: str = None
    ) -> tuple:
        """
        Create a manual payment entry.

        This method:
        1. Creates a Transaction record
        2. Creates a ManualPayment record
        3. Links them together
        4. Returns both records

        Args:
            payment_method: Payment method (PDQ, BANK_TRANSFER, CASH, CHEQUE, OTHER)
            payer_name: Name of the person who paid
            amount: Amount received
            payment_date: When payment was received
            created_by: Staff member creating this entry
            reference_number: Optional reference (required for PDQ/Bank)
            payer_phone: Optional phone number
            payer_email: Optional email
            notes: Optional notes

        Returns:
            tuple: (Transaction, ManualPayment)

        Raises:
            ValidationError: If validation fails
        """
        with db_transaction.atomic():
            # Generate unique transaction ID for manual payments
            tx_id = ManualPaymentService._generate_manual_tx_id(
                payment_method, payer_name, amount, payment_date
            )

            # Generate unique hash
            unique_hash = ManualPaymentService._generate_unique_hash(
                tx_id, payer_name, str(amount), str(payment_date)
            )

            # Create Transaction record
            transaction = Transaction.objects.create(
                tx_id=tx_id,
                amount=amount,
                amount_expected=amount,
                amount_paid=Decimal('0.00'),
                sender_name=payer_name,
                sender_phone=payer_phone or '',
                timestamp=payment_date,
                gateway_type=f"MANUAL_{payment_method}",
                destination_number='',
                confidence=1.0,  # Manual entries have 100% confidence
                status=Transaction.OrderStatus.NOT_PROCESSED,
                unique_hash=unique_hash,
                notes=f"Manual {payment_method} payment entry\nEntered by: {created_by}"
            )

            # Add user notes if provided
            if notes:
                transaction.notes += f"\nNotes: {notes}"
                transaction.save()

            # Create ManualPayment record
            manual_payment = ManualPayment.objects.create(
                transaction=transaction,
                payment_method=payment_method,
                reference_number=reference_number or '',
                payer_name=payer_name,
                payer_phone=payer_phone or '',
                payer_email=payer_email or '',
                amount=amount,
                payment_date=payment_date,
                notes=notes or '',
                created_by=created_by
            )

            logger.info(
                f"Created manual {payment_method} payment: {tx_id} "
                f"for {amount} from {payer_name} (entered by {created_by})"
            )

            # Broadcast new transaction to WebSocket clients
            ManualPaymentService._broadcast_transaction_created(transaction)

            return transaction, manual_payment

    @staticmethod
    def _generate_manual_tx_id(payment_method: str, payer_name: str, amount: Decimal, payment_date) -> str:
        """
        Generate a unique transaction ID for manual payments.

        Format: MAN-{METHOD}-{TIMESTAMP}-{HASH}
        Example: MAN-PDQ-20251009-A3F2

        Args:
            payment_method: Payment method
            payer_name: Payer name
            amount: Payment amount
            payment_date: Payment date

        Returns:
            Unique transaction ID
        """
        # Use first 3 letters of payment method
        method_code = payment_method[:3].upper()

        # Format date as YYYYMMDD
        date_str = payment_date.strftime('%Y%m%d')

        # Create a short hash from payer name and amount
        hash_input = f"{payer_name}{amount}{payment_date.isoformat()}"
        hash_obj = hashlib.md5(hash_input.encode())
        short_hash = hash_obj.hexdigest()[:4].upper()

        return f"MAN-{method_code}-{date_str}-{short_hash}"

    @staticmethod
    def _generate_unique_hash(tx_id: str, sender_name: str, amount: str, timestamp: str) -> str:
        """
        Generate unique hash for transaction deduplication.

        Args:
            tx_id: Transaction ID
            sender_name: Sender name
            amount: Amount as string
            timestamp: Timestamp as string

        Returns:
            SHA-256 hash
        """
        hash_input = f"{tx_id}{sender_name}{amount}{timestamp}"
        return hashlib.sha256(hash_input.encode()).hexdigest()

    @staticmethod
    def get_manual_payments_summary(start_date=None, end_date=None, payment_method=None):
        """
        Get summary of manual payments for reporting.

        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter
            payment_method: Optional payment method filter

        Returns:
            Dictionary with summary statistics
        """
        queryset = ManualPayment.objects.all()

        if start_date:
            queryset = queryset.filter(payment_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(payment_date__lte=end_date)
        if payment_method:
            queryset = queryset.filter(payment_method=payment_method)

        total_count = queryset.count()
        total_amount = sum(mp.amount for mp in queryset) if total_count > 0 else Decimal('0.00')

        # Group by payment method
        by_method = {}
        for method, label in ManualPayment.PaymentMethod.choices:
            method_payments = queryset.filter(payment_method=method)
            method_count = method_payments.count()
            method_amount = sum(mp.amount for mp in method_payments) if method_count > 0 else Decimal('0.00')

            by_method[method] = {
                'label': label,
                'count': method_count,
                'total_amount': float(method_amount)
            }

        return {
            'total_count': total_count,
            'total_amount': float(total_amount),
            'by_method': by_method,
            'date_range': {
                'start': start_date.isoformat() if start_date else None,
                'end': end_date.isoformat() if end_date else None
            }
        }

    @staticmethod
    def _broadcast_transaction_created(transaction):
        """
        Broadcast a newly created transaction to WebSocket clients.

        Args:
            transaction: Transaction instance
        """
        try:
            channel_layer = get_channel_layer()
            if channel_layer:
                serializer = TransactionSerializer(transaction)
                async_to_sync(channel_layer.group_send)(
                    'transactions',
                    {
                        'type': 'transaction.created',
                        'transaction': serializer.data
                    }
                )
                logger.info(f"Broadcasted manual transaction {transaction.tx_id} to WebSocket clients")
        except Exception as e:
            logger.error(f"Failed to broadcast manual transaction {transaction.tx_id}: {e}")
