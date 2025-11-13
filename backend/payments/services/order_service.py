"""
Order Status Management Service

Provides centralized business logic for managing transaction status transitions,
partial fulfillment, and transaction locking. This service ensures all status
changes respect the state machine rules and locking constraints.

Key Features:
- Safe status transitions with validation
- Partial fulfillment tracking
- Auto-locking when fully paid
- Transaction history logging
- Prevents duplicate order fulfillment

Usage:
    from payments.services import OrderStatusService

    service = OrderStatusService()
    service.mark_as_processing(transaction)
    service.allocate_payment(transaction, order_id, amount)
"""

from decimal import Decimal
from django.db import transaction as db_transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
import json
import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from payments.models import Transaction
from payments.serializers import TransactionSerializer
from utils.exceptions import (
    TransactionLockedException,
    InvalidStatusTransitionError,
    InsufficientAmountError
)

logger = logging.getLogger(__name__)


class OrderStatusService:
    """
    Service class for managing transaction status changes and order fulfillment.

    This service provides safe methods for transitioning transactions through
    their lifecycle while enforcing business rules and preventing data corruption.
    """

    @staticmethod
    def mark_as_processing(transaction: Transaction, notes: str = None) -> Transaction:
        """
        Mark a transaction as PROCESSING.

        This indicates that the transaction has been reviewed and work has begun
        on fulfilling the order.

        Args:
            transaction: The Transaction instance to update
            notes: Optional notes to append to transaction

        Returns:
            Updated Transaction instance

        Raises:
            TransactionLockedException: If transaction is locked
            InvalidStatusTransitionError: If transition is not valid
        """
        if transaction.is_locked:
            logger.warning(f"Attempted to modify locked transaction {transaction.tx_id}")
            raise TransactionLockedException(
                f"Transaction {transaction.tx_id} is {transaction.status} and cannot be modified"
            )

        new_status = Transaction.OrderStatus.PROCESSING

        if not transaction.can_transition_to(new_status):
            logger.warning(
                f"Invalid transition for {transaction.tx_id}: "
                f"{transaction.status} -> {new_status}"
            )
            raise InvalidStatusTransitionError(
                f"Cannot transition from {transaction.get_status_display()} to "
                f"{Transaction.OrderStatus.PROCESSING.label}"
            )

        with db_transaction.atomic():
            transaction.status = new_status
            if notes:
                transaction.notes = f"{transaction.notes}\n{notes}" if transaction.notes else notes
            transaction.save()

        logger.info(f"Transaction {transaction.tx_id} marked as PROCESSING")
        OrderStatusService._broadcast_transaction_updated(transaction)
        return transaction

    @staticmethod
    def allocate_payment(
        transaction: Transaction,
        order_id: str,
        amount: Decimal,
        notes: str = None
    ) -> Transaction:
        """
        Allocate a portion of the transaction payment to an order.

        This method:
        1. Validates sufficient funds are available
        2. Updates amount_paid
        3. Auto-marks as PARTIALLY_FULFILLED or FULFILLED
        4. Auto-locks when fully paid

        Args:
            transaction: The Transaction instance to allocate from
            order_id: ID of the order being fulfilled
            amount: Amount to allocate (must be <= remaining_amount)
            notes: Optional notes about this allocation

        Returns:
            Updated Transaction instance

        Raises:
            TransactionLockedException: If transaction is locked
            InsufficientAmountError: If amount exceeds remaining_amount
            ValidationError: If amount is negative
        """
        if transaction.is_locked:
            logger.warning(f"Attempted to allocate from locked transaction {transaction.tx_id}")
            raise TransactionLockedException(
                f"Transaction {transaction.tx_id} is {transaction.status} and cannot be modified"
            )

        if amount <= Decimal('0.00'):
            raise ValidationError({"amount": "Amount must be greater than zero"})

        if amount > transaction.remaining_amount:
            logger.warning(
                f"Insufficient amount in {transaction.tx_id}: "
                f"Requested {amount}, Available {transaction.remaining_amount}"
            )
            raise InsufficientAmountError(
                f"Insufficient amount. Requested: {amount}, "
                f"Available: {transaction.remaining_amount}"
            )

        with db_transaction.atomic():
            transaction.amount_paid += amount

            allocation_note = (
                f"[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"Allocated {amount} to order {order_id}"
            )

            if notes:
                allocation_note += f" - {notes}"

            transaction.notes = (
                f"{transaction.notes}\n{allocation_note}"
                if transaction.notes
                else allocation_note
            )

            # The save() method will auto-transition to PARTIALLY_FULFILLED or FULFILLED
            transaction.save()

        logger.info(
            f"Allocated {amount} from transaction {transaction.tx_id} to order {order_id}. "
            f"Remaining: {transaction.remaining_amount}"
        )

        OrderStatusService._broadcast_transaction_updated(transaction)
        return transaction

    @staticmethod
    def mark_as_fulfilled(transaction: Transaction, notes: str = None) -> Transaction:
        """
        Manually mark a transaction as FULFILLED.

        Note: Transactions are typically auto-fulfilled when amount_paid reaches
        amount_expected. This method is for manual fulfillment in special cases.

        Args:
            transaction: The Transaction instance to update
            notes: Optional notes about why this was manually fulfilled

        Returns:
            Updated Transaction instance

        Raises:
            TransactionLockedException: If transaction is already locked
            InvalidStatusTransitionError: If transition is not valid
        """
        if transaction.is_locked:
            logger.warning(f"Attempted to modify locked transaction {transaction.tx_id}")
            raise TransactionLockedException(
                f"Transaction {transaction.tx_id} is already {transaction.status}"
            )

        new_status = Transaction.OrderStatus.FULFILLED

        if not transaction.can_transition_to(new_status):
            logger.warning(
                f"Invalid transition for {transaction.tx_id}: "
                f"{transaction.status} -> {new_status}"
            )
            raise InvalidStatusTransitionError(
                f"Cannot transition from {transaction.get_status_display()} to Fulfilled"
            )

        with db_transaction.atomic():
            transaction.status = new_status

            fulfillment_note = (
                f"[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"Manually marked as FULFILLED"
            )

            if notes:
                fulfillment_note += f" - {notes}"

            transaction.notes = (
                f"{transaction.notes}\n{fulfillment_note}"
                if transaction.notes
                else fulfillment_note
            )

            transaction.save()

        logger.info(f"Transaction {transaction.tx_id} manually marked as FULFILLED")
        OrderStatusService._broadcast_transaction_updated(transaction)
        return transaction

    @staticmethod
    def cancel_transaction(transaction: Transaction, reason: str) -> Transaction:
        """
        Cancel a transaction.

        Cancellation locks the transaction permanently. Use this for:
        - Fraudulent transactions
        - Duplicate entries
        - Customer refund requests
        - Payment reversals

        Args:
            transaction: The Transaction instance to cancel
            reason: Required reason for cancellation (for audit trail)

        Returns:
            Updated Transaction instance

        Raises:
            TransactionLockedException: If transaction is already locked
            ValidationError: If reason is not provided
        """
        if transaction.is_locked:
            logger.warning(f"Attempted to modify locked transaction {transaction.tx_id}")
            raise TransactionLockedException(
                f"Transaction {transaction.tx_id} is already {transaction.status}"
            )

        if not reason or not reason.strip():
            raise ValidationError({"reason": "Cancellation reason is required"})

        new_status = Transaction.OrderStatus.CANCELLED

        if not transaction.can_transition_to(new_status):
            logger.warning(
                f"Invalid transition for {transaction.tx_id}: "
                f"{transaction.status} -> {new_status}"
            )
            raise InvalidStatusTransitionError(
                f"Cannot transition from {transaction.get_status_display()} to Cancelled"
            )

        with db_transaction.atomic():
            transaction.status = new_status

            cancellation_note = (
                f"[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"CANCELLED - {reason}"
            )

            transaction.notes = (
                f"{transaction.notes}\n{cancellation_note}"
                if transaction.notes
                else cancellation_note
            )

            transaction.save()

        logger.warning(f"Transaction {transaction.tx_id} CANCELLED - Reason: {reason}")
        OrderStatusService._broadcast_transaction_updated(transaction)
        return transaction

    @staticmethod
    def get_available_transactions(min_amount: Decimal = None):
        """
        Get all transactions that have remaining amount available for allocation.

        Returns transactions that are:
        - Status: PROCESSING or PARTIALLY_FULFILLED
        - Not locked
        - Have remaining_amount > 0

        Args:
            min_amount: Optional minimum remaining amount filter

        Returns:
            QuerySet of available transactions ordered by timestamp
        """
        queryset = Transaction.objects.filter(
            status__in=[
                Transaction.OrderStatus.PROCESSING,
                Transaction.OrderStatus.PARTIALLY_FULFILLED
            ]
        ).exclude(
            status__in=[
                Transaction.OrderStatus.FULFILLED,
                Transaction.OrderStatus.CANCELLED
            ]
        )

        # Filter by remaining amount if specified
        if min_amount:
            # We need to use annotation since remaining_amount is a property
            from django.db.models import F
            queryset = queryset.annotate(
                remaining=F('amount_expected') - F('amount_paid')
            ).filter(remaining__gte=min_amount)

        return queryset.order_by('timestamp')

    @staticmethod
    def get_transaction_summary(transaction: Transaction) -> dict:
        """
        Get a comprehensive summary of a transaction's current state.

        Useful for API responses and frontend display.

        Args:
            transaction: The Transaction instance

        Returns:
            Dictionary with transaction summary including:
            - Basic transaction info
            - Payment status
            - Locking status
            - Visual indicators (color, icon)
        """
        return {
            'tx_id': transaction.tx_id,
            'amount': float(transaction.amount),
            'amount_expected': float(transaction.amount_expected),
            'amount_paid': float(transaction.amount_paid),
            'remaining_amount': float(transaction.remaining_amount),
            'sender_name': transaction.sender_name,
            'sender_phone': transaction.sender_phone,
            'timestamp': transaction.timestamp.isoformat(),
            'status': transaction.status,
            'status_display': transaction.status_display,
            'is_locked': transaction.is_locked,
            'can_allocate': not transaction.is_locked and transaction.remaining_amount > 0,
            'notes': transaction.notes,
            'created_at': transaction.created_at.isoformat(),
            'updated_at': transaction.updated_at.isoformat(),
        }

    @staticmethod
    def _broadcast_transaction_updated(transaction: Transaction):
        """
        Broadcast transaction update to WebSocket clients.

        Args:
            transaction: Transaction instance
        """
        try:
            channel_layer = get_channel_layer()
            if channel_layer:
                serializer = TransactionSerializer(transaction)
                # Convert to JSON and back to ensure all UUIDs are serialized as strings
                transaction_data = json.loads(json.dumps(serializer.data, default=str))

                async_to_sync(channel_layer.group_send)(
                    'transactions',
                    {
                        'type': 'transaction.updated',
                        'transaction': transaction_data
                    }
                )
                logger.info(f"Broadcasted update for transaction {transaction.tx_id} to WebSocket clients")
        except Exception as e:
            logger.error(f"Failed to broadcast transaction update {transaction.tx_id}: {e}")
