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
        Cancel a transaction and return products to inventory (if any).

        This is a privileged admin operation that handles various cancellation scenarios:
        - FULFILLED: Returns all scanned products to inventory
        - PARTIALLY_FULFILLED: Returns partially scanned products to inventory
        - PROCESSING: Handles edge case where amount_fulfilled > 0 but no completion

        Common Use Cases:
        - Reversing a completed order
        - Fixing an incomplete scan that failed mid-way
        - Resetting a transaction that has amount_fulfilled but no line items
          (e.g., when a product scan failed due to insufficient stock)

        Business Rules:
        - Can cancel FULFILLED, PARTIALLY_FULFILLED, or PROCESSING transactions
        - Returns line item products to inventory (if any exist)
        - Creates reverse InventoryMovement records for audit trail
        - Resets transaction to NOT_PROCESSED for re-processing
        - Requires admin role (enforced at view level)

        Args:
            transaction_id: ID of the transaction to cancel
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

                # Validate transaction status - allow FULFILLED and PARTIALLY_FULFILLED
                if txn.status not in [
                    Transaction.OrderStatus.FULFILLED,
                    Transaction.OrderStatus.PARTIALLY_FULFILLED,
                    Transaction.OrderStatus.PROCESSING  # Allow PROCESSING with amount_fulfilled > 0
                ]:
                    raise ValidationError({
                        'status': f'Can only cancel FULFILLED, PARTIALLY_FULFILLED, or PROCESSING transactions. '
                                 f'Current status: {txn.status}'
                    })

                # Get all line items (may be empty if scan failed before completion)
                line_items = TransactionLineItem.objects.filter(
                    transaction=txn
                ).select_related('product')

                # Reverse inventory for each line item (if any exist)
                reversed_movements = []
                if line_items.exists():
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
                else:
                    logger.info(
                        f"No line items found for transaction {txn.tx_id}. "
                        f"Resetting transaction without inventory reversal."
                    )

                # Reset transaction to NOT_PROCESSED so it reappears in transaction list
                txn.status = Transaction.OrderStatus.NOT_PROCESSED
                txn.amount_fulfilled = Decimal('0.00')
                txn.amount_paid = Decimal('0.00')  # Also reset legacy field for consistency
                txn.total_cost = Decimal('0.00')
                txn.total_pv = Decimal('0.00')
                txn.is_in_issuance = False
                txn.cancelled_by = cancelled_by_user
                txn.cancelled_at = timezone.now()

                # Clear completion tracking
                txn.completed_by = None
                txn.completed_at = None

                # Add detailed cancellation note
                inventory_msg = (
                    f"Inventory returned: {len(reversed_movements)} products restored."
                    if reversed_movements
                    else "No inventory reversal needed (no line items)."
                )
                cancel_note = (
                    f"\n[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"ADMIN REVERSAL by {cancelled_by_user.username}: {reason}\n"
                    f"Order reset to NOT_PROCESSED. {inventory_msg}\n"
                    f"Transaction can now be processed again."
                )
                txn.notes = f"{txn.notes}{cancel_note}" if txn.notes else cancel_note

                # Use skip_validation to bypass FULFILLED → NOT_PROCESSED restriction
                # This is safe because we're explicitly handling the reversal
                txn.save(skip_validation=True)

                # Refresh from database to ensure we have the saved values
                txn.refresh_from_db()

                # Delete the line items since we're resetting the transaction
                line_items.delete()

                inventory_log_msg = (
                    f"Inventory restored: {len(reversed_movements)} products."
                    if reversed_movements
                    else "No inventory reversal needed (no line items found)."
                )
                logger.warning(
                    f"Admin {cancelled_by_user.username} cancelled transaction "
                    f"{txn.tx_id} (was {txn.status}). Reason: {reason}. {inventory_log_msg}"
                )

                success_msg = (
                    f'Transaction {txn.tx_id} cancelled successfully. '
                    f'{len(reversed_movements)} products returned to inventory.'
                    if reversed_movements
                    else f'Transaction {txn.tx_id} cancelled successfully. No inventory to reverse.'
                )

                return {
                    'success': True,
                    'transaction_id': txn.id,
                    'tx_id': txn.tx_id,
                    'status': txn.status,
                    'amount': str(txn.amount),
                    'amount_fulfilled': str(txn.amount_fulfilled),
                    'remaining_amount': str(txn.remaining_amount),
                    'cancelled_by': cancelled_by_user.username,
                    'cancelled_at': txn.cancelled_at.isoformat(),
                    'reason': reason,
                    'reversed_items_count': len(reversed_movements),
                    'inventory_updates': reversed_movements,
                    'message': success_msg
                }

        except Transaction.DoesNotExist:
            raise ValidationError({'transaction_id': 'Transaction not found'})
        except Product.DoesNotExist as e:
            raise ValidationError({'product': f'Product not found: {str(e)}'})
        except Exception as e:
            logger.error(f"Error cancelling transaction {transaction_id}: {str(e)}")
            raise ValidationError({'error': f'Cancellation failed: {str(e)}'})

    @staticmethod
    def cancel_registration_order(
        transaction_id: int,
        cancelled_by_user,
        reason: str
    ) -> Dict:
        """
        Cancel a registration order and return both registration kit and fulfilled products to inventory.

        This handles cancellation of registration transactions by:
        - Returning all scanned products to inventory
        - Returning registration kit(s) to inventory
        - Resetting transaction to NOT_PROCESSED
        - Creating reverse InventoryMovement records for audit trail

        Business Rules:
        - Only registration transactions can be cancelled this way
        - Must have registration kit issued
        - Can be in any status (PROCESSING, PARTIALLY_FULFILLED, FULFILLED)
        - Requires admin role (enforced at view level)

        Args:
            transaction_id: ID of the registration transaction
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

                # Validate it's a registration transaction
                if not txn.is_registration:
                    raise ValidationError({
                        'is_registration': 'Transaction is not a registration order'
                    })

                if not txn.registration_kit_issued:
                    raise ValidationError({
                        'registration_kit_issued': 'No registration kit was issued for this transaction'
                    })

                reversed_movements = []

                # 1. Return scanned products to inventory (if any)
                line_items = TransactionLineItem.objects.filter(
                    transaction=txn
                ).select_related('product')

                for item in line_items:
                    product = Product.objects.select_for_update().get(id=item.product.id)

                    # Return quantity to inventory
                    quantity_before = product.quantity
                    product.quantity += item.quantity
                    quantity_after = product.quantity
                    product.save()

                    # Create reverse inventory movement
                    InventoryMovement.objects.create(
                        movement_type=InventoryMovement.MovementType.RETURN,
                        product=product,
                        quantity_before=quantity_before,
                        quantity_after=quantity_after,
                        quantity_change=item.quantity,
                        reference=f'Cancelled Registration {txn.tx_id} - {reason}',
                        performed_by=cancelled_by_user.username,
                        performed_by_user=cancelled_by_user
                    )

                    reversed_movements.append({
                        'product_code': product.prod_code,
                        'product_name': product.prod_name,
                        'quantity_returned': item.quantity,
                        'new_stock': quantity_after
                    })

                # 2. Return registration kit to inventory
                # Skip if kit was already returned via line items above (i.e. a REG_KIT_001
                # TransactionLineItem existed). This prevents double-returning the kit.
                kit_already_returned = any(
                    item.product.prod_code == 'REG_KIT_001'
                    for item in line_items
                    if item.product
                )

                if not kit_already_returned:
                    try:
                        reg_kit = Product.objects.select_for_update().get(prod_code='REG_KIT_001')
                        kit_quantity = txn.registration_kit_quantity or 1

                        quantity_before = reg_kit.quantity
                        reg_kit.quantity += kit_quantity
                        quantity_after = reg_kit.quantity
                        reg_kit.save()

                        # Create reverse inventory movement for kit
                        InventoryMovement.objects.create(
                            movement_type=InventoryMovement.MovementType.RETURN,
                            product=reg_kit,
                            quantity_before=quantity_before,
                            quantity_after=quantity_after,
                            quantity_change=kit_quantity,
                            reference=f'Cancelled Registration {txn.tx_id} - Kit Return - {reason}',
                            performed_by=cancelled_by_user.username,
                            performed_by_user=cancelled_by_user
                        )

                        reversed_movements.append({
                            'product_code': reg_kit.prod_code,
                            'product_name': f'{reg_kit.prod_name} (Registration Kit)',
                            'quantity_returned': kit_quantity,
                            'new_stock': quantity_after
                        })

                    except Product.DoesNotExist:
                        logger.warning(
                            f"Registration kit (REG_KIT_001) not found when cancelling "
                            f"registration transaction {txn.tx_id}. Kit inventory not restored."
                        )

                # 3. Reset transaction state
                txn.status = Transaction.OrderStatus.NOT_PROCESSED
                txn.amount_fulfilled = Decimal('0.00')
                txn.amount_paid = Decimal('0.00')  # Also reset legacy field for consistency
                txn.total_cost = Decimal('0.00')
                txn.total_pv = Decimal('0.00')
                txn.is_in_issuance = False
                txn.registration_kit_issued = False
                txn.registration_kit_quantity = 0
                txn.registration_kit_amount_deducted = Decimal('0.00')
                txn.cancelled_by = cancelled_by_user
                txn.cancelled_at = timezone.now()

                # Clear completion tracking
                txn.completed_by = None
                txn.completed_at = None
                txn.activated_by = None
                txn.activated_at = None

                # Add detailed cancellation note
                cancel_note = (
                    f"\n[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"ADMIN CANCELLATION by {cancelled_by_user.username}: {reason}\n"
                    f"Registration order cancelled. Inventory returned:\n"
                    f"- Registration kit(s): {kit_quantity if 'reg_kit' in locals() else 'N/A'}\n"
                    f"- Products: {len(line_items)} items\n"
                    f"Transaction reset to NOT_PROCESSED."
                )
                txn.notes = f"{txn.notes}{cancel_note}" if txn.notes else cancel_note

                # Use skip_validation to bypass status transition restrictions
                txn.save(skip_validation=True)

                # Delete line items
                line_items.delete()

                logger.warning(
                    f"Admin {cancelled_by_user.username} cancelled registration transaction "
                    f"{txn.tx_id}. Reason: {reason}. "
                    f"Inventory restored: {len(reversed_movements)} items (including kit)."
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
                        f'Registration order {txn.tx_id} cancelled successfully. '
                        f'{len(reversed_movements)} items returned to inventory (including kit).'
                    )
                }

        except Transaction.DoesNotExist:
            raise ValidationError({'transaction_id': 'Transaction not found'})
        except Exception as e:
            logger.error(f"Error cancelling registration order {transaction_id}: {str(e)}")
            raise ValidationError({'error': f'Cancellation failed: {str(e)}'})

    @staticmethod
    def delete_transaction(
        transaction_id: int,
        deleted_by_user,
        reason: str
    ) -> Dict:
        """
        Permanently delete a transaction (Admin only, use with caution).

        This is a destructive operation that completely removes a transaction from the system.
        Should only be used for duplicate, test, or erroneous transactions.

        Business Rules:
        - Only NOT_PROCESSED transactions can be deleted
        - Transaction must not have any line items (must be unfulfilled)
        - Transaction must not be part of a combined order
        - Requires admin role (enforced at view level)
        - Deletion is permanent and cannot be undone

        Args:
            transaction_id: ID of the transaction to delete
            deleted_by_user: Admin user performing the deletion
            reason: Required explanation for the deletion

        Returns:
            Dict with deletion confirmation

        Raises:
            ValidationError: If business rules are violated
        """
        try:
            with db_transaction.atomic():
                # Get and lock transaction
                txn = Transaction.objects.select_for_update().get(id=transaction_id)

                # Validate transaction can be deleted
                if txn.status != Transaction.OrderStatus.NOT_PROCESSED:
                    raise ValidationError({
                        'status': f'Can only delete NOT_PROCESSED transactions. '
                                 f'Current status: {txn.status}. '
                                 f'Use cancellation for fulfilled transactions.'
                    })

                # Check for line items
                line_items_count = TransactionLineItem.objects.filter(transaction=txn).count()
                if line_items_count > 0:
                    raise ValidationError({
                        'line_items': f'Transaction has {line_items_count} line items. '
                                     f'Cannot delete fulfilled transactions. Use cancellation instead.'
                    })

                # Check if part of combined order
                if txn.combined_orders.exists():
                    raise ValidationError({
                        'combined_order': 'Transaction is part of a combined order. '
                                        'Remove from combined order first.'
                    })

                # Check if registration kit issued
                if txn.is_registration and txn.registration_kit_issued:
                    raise ValidationError({
                        'registration_kit': 'Registration kit has been issued. '
                                          'Use cancel registration order instead.'
                    })

                # Store info for response
                tx_id = txn.tx_id
                amount = txn.amount
                sender_name = txn.sender_name

                # Log deletion
                logger.warning(
                    f"Admin {deleted_by_user.username} is DELETING transaction "
                    f"{tx_id} (ID: {transaction_id}). Reason: {reason}. "
                    f"Amount: {amount}, Sender: {sender_name}"
                )

                # Permanently delete transaction
                txn.delete()

                return {
                    'success': True,
                    'tx_id': tx_id,
                    'deleted_by': deleted_by_user.username,
                    'deleted_at': timezone.now().isoformat(),
                    'reason': reason,
                    'message': f'Transaction {tx_id} permanently deleted.'
                }

        except Transaction.DoesNotExist:
            raise ValidationError({'transaction_id': 'Transaction not found'})
        except Exception as e:
            logger.error(f"Error deleting transaction {transaction_id}: {str(e)}")
            raise ValidationError({'error': f'Deletion failed: {str(e)}'})
