"""
Admin-Only Operations Service

Handles privileged operations that only administrators can perform:
- Cancelling fulfilled transactions with inventory return
- Other admin-specific business logic
"""

from decimal import Decimal
from django.db import transaction as db_transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from typing import Dict
import logging

from payments.models import (
    Transaction, InventoryMovement, TransactionLineItem, Product
)

logger = logging.getLogger(__name__)


class AdminService:
    """Service for admin-only operations."""

    @staticmethod
    def cancel_fulfilled_transaction(
        transaction_id: int,
        cancelled_by_user,
        reason: str
    ) -> Dict:
        """
        Cancel a fulfilled transaction and return products to inventory.

        This is a privileged admin operation that reverses a completed fulfillment:
        - Changes status from FULFILLED to CANCELLED
        - Returns all line item products back to inventory
        - Creates reverse InventoryMovement records for audit trail
        - Records detailed cancellation notes

        Business Rules:
        - Only FULFILLED transactions can be cancelled
        - Requires admin role (enforced at view level)
        - Uses skip_validation to allow FULFILLED → CANCELLED transition
        - All inventory movements are reversible and auditable

        Args:
            transaction_id: ID of the fulfilled transaction to cancel
            cancelled_by_user: Admin user performing the cancellation
            reason: Required explanation for the cancellation

        Returns:
            Dict with cancellation status and inventory restoration details

        Raises:
            ValidationError: If business rules are violated
        """
        try:
            with db_transaction.atomic():
                # Get and lock transaction
                txn = Transaction.objects.select_for_update().get(id=transaction_id)

                # Validate transaction status
                if txn.status != Transaction.OrderStatus.FULFILLED:
                    raise ValidationError({
                        'status': f'Can only cancel FULFILLED transactions. '
                                 f'Current status: {txn.status}'
                    })

                # Get all line items
                line_items = TransactionLineItem.objects.filter(
                    transaction=txn
                ).select_related('product')

                if not line_items.exists():
                    raise ValidationError({
                        'line_items': 'No line items found to reverse'
                    })

                # Reverse inventory for each line item
                reversed_movements = []
                for item in line_items:
                    product = Product.objects.select_for_update().get(id=item.product.id)

                    # Return quantity to inventory
                    quantity_before = product.quantity
                    product.quantity += item.quantity
                    quantity_after = product.quantity
                    product.save()

                    # Create reverse inventory movement (RETURN type)
                    InventoryMovement.objects.create(
                        movement_type=InventoryMovement.MovementType.RETURN,
                        product=product,
                        quantity_before=quantity_before,
                        quantity_after=quantity_after,
                        quantity_change=item.quantity,  # Positive change (adding back)
                        reference=f'Cancelled {txn.tx_id} - {reason}',
                        performed_by=cancelled_by_user.username,
                        performed_by_user=cancelled_by_user
                    )

                    reversed_movements.append({
                        'product_code': product.prod_code,
                        'product_name': product.prod_name,
                        'quantity_returned': item.quantity,
                        'new_stock': quantity_after
                    })

                    logger.info(
                        f"Returned {item.quantity}x {product.prod_name} to inventory "
                        f"(new stock: {quantity_after}) for cancelled transaction {txn.tx_id}"
                    )

                # Reset transaction to NOT_PROCESSED so it reappears in transaction list
                txn.status = Transaction.OrderStatus.NOT_PROCESSED
                txn.amount_fulfilled = Decimal('0.00')
                txn.total_cost = Decimal('0.00')
                txn.total_pv = Decimal('0.00')
                txn.is_in_issuance = False
                txn.cancelled_by = cancelled_by_user
                txn.cancelled_at = timezone.now()

                # Clear completion tracking
                txn.completed_by = None
                txn.completed_at = None

                # Add detailed cancellation note
                cancel_note = (
                    f"\n[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"ADMIN REVERSAL by {cancelled_by_user.username}: {reason}\n"
                    f"Order reset to NOT_PROCESSED. Inventory returned: {len(reversed_movements)} products restored.\n"
                    f"Transaction can now be processed again."
                )
                txn.notes = f"{txn.notes}{cancel_note}" if txn.notes else cancel_note

                # Use skip_validation to bypass FULFILLED → NOT_PROCESSED restriction
                # This is safe because we're explicitly handling the reversal
                txn.save(skip_validation=True)

                # Delete the line items since we're resetting the transaction
                line_items.delete()

                logger.warning(
                    f"Admin {cancelled_by_user.username} cancelled FULFILLED transaction "
                    f"{txn.tx_id}. Reason: {reason}. "
                    f"Inventory restored: {len(reversed_movements)} products."
                )

                return {
                    'success': True,
                    'transaction_id': txn.id,
                    'tx_id': txn.tx_id,
                    'status': txn.status,
                    'cancelled_by': cancelled_by_user.username,
                    'cancelled_at': txn.cancelled_at.isoformat(),
                    'reason': reason,
                    'reversed_items_count': len(reversed_movements),
                    'inventory_updates': reversed_movements,
                    'message': (
                        f'Transaction {txn.tx_id} cancelled successfully. '
                        f'{len(reversed_movements)} products returned to inventory.'
                    )
                }

        except Transaction.DoesNotExist:
            raise ValidationError({'transaction_id': 'Transaction not found'})
        except Product.DoesNotExist as e:
            raise ValidationError({'product': f'Product not found: {str(e)}'})
        except Exception as e:
            logger.error(f"Error cancelling transaction {transaction_id}: {str(e)}")
            raise ValidationError({'error': f'Cancellation failed: {str(e)}'})
