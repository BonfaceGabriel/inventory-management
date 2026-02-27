"""
Service layer for Combined Order operations.

Handles business logic for combining multiple transactions into one fulfillment order.
"""

from decimal import Decimal
from typing import List, Dict, Optional
from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError
import logging

from payments.models import (
    Transaction, CombinedOrder, CombinedOrderTransaction,
    CombinedOrderLineItem, Product, InventoryMovement, TransactionLineItem
)
from payments.services.stock_take_service import StockTakeService
from payments.services.promotion_service import PromotionService

logger = logging.getLogger(__name__)


class CombinedOrderService:
    """Service for managing combined orders (multiple transactions combined into one fulfillment)."""

    @staticmethod
    def recalculate_amount_fulfilled(order: CombinedOrder) -> Decimal:
        """
        Recalculate total amount fulfilled for a combined order.
        
        Logic:
        1. Sum of all current line items (scanned + copied)
        2. PLUS any "orphan" fulfillment from original transactions that didn't have line items
           (derived from base_amount_fulfilled - sum(copied_line_items))
        """
        # Sum of all line items currently in the order
        all_items = order.line_items.all()
        line_items_total = sum(item.line_total for item in all_items)
        
        # Sum of line items that were copied from transactions
        # We filter the already fetched list to avoid extra DB query if possible
        copied_items_total = sum(
            item.line_total for item in all_items 
            if item.copied_from_transaction_id is not None
        )
        
        # Calculate orphan fulfillment (value in base_amount_fulfilled not accounted for by copied items)
        # This handles legacy transactions or manual fulfillments used to create the order
        orphan_fulfillment = order.base_amount_fulfilled - copied_items_total
        
        # Ensure non-negative (safety check)
        orphan_fulfillment = max(Decimal('0.00'), orphan_fulfillment)
        
        return line_items_total + orphan_fulfillment

    @staticmethod
    @transaction.atomic
    def create_combined_order(
        transaction_ids: List[int],
        created_by: str,
        customer_name: str = "",
        customer_phone: str = "",
        notes: str = ""
    ) -> Dict:
        """
        Create a combined order from multiple transactions.

        Args:
            transaction_ids: List of transaction IDs to combine
            created_by: Username/identifier of user creating the order
            customer_name: Optional customer name
            customer_phone: Optional customer phone
            notes: Optional notes

        Returns:
            Dict with combined order details and statistics

        Raises:
            ValidationError: If validation fails
        """
        # Check if stock-taking session is active
        active_stock_take = StockTakeService.get_active_session()
        if active_stock_take:
            raise ValidationError(
                f'Stock-taking session {active_stock_take.session_id} is in progress. '
                f'Complete or cancel the stock-take session before creating combined orders.'
            )

        # Validate input
        if not transaction_ids:
            raise ValidationError("At least one transaction ID must be provided")

        if len(transaction_ids) < 2:
            raise ValidationError("At least two transactions must be provided to create a combined order")

        # Fetch transactions
        transactions = Transaction.objects.filter(id__in=transaction_ids)

        if transactions.count() != len(transaction_ids):
            raise ValidationError(
                f"Found {transactions.count()} transactions, but {len(transaction_ids)} IDs were provided. "
                "Some transaction IDs may be invalid."
            )

        # Check upfront: none of the selected transactions can be a combined order parent
        parent_tx_ids = set(
            CombinedOrder.objects.filter(parent_transaction_id__in=transaction_ids)
            .values_list('parent_transaction_id', flat=True)
        )

        # Validate all transactions are eligible
        for txn in transactions:
            # Reject combined order parent transactions — they represent existing combined orders
            # and must not be re-combined. Use "Add Transactions" on the existing order instead.
            if txn.id in parent_tx_ids:
                raise ValidationError(
                    f"Transaction {txn.tx_id} is the parent of an existing combined order "
                    f"and cannot be re-combined. To add transactions to that order, "
                    f"use 'Add Transactions' from its order detail."
                )

            # Check if already in a combined order
            if txn.combined_orders.exists():
                raise ValidationError(
                    f"Transaction {txn.tx_id} is already part of a combined order "
                    f"({txn.combined_orders.first().combined_order.combined_order_id})"
                )

            # Allow NOT_PROCESSED and PARTIALLY_FULFILLED transactions to be combined
            allowed_statuses = [
                Transaction.OrderStatus.NOT_PROCESSED,
                Transaction.OrderStatus.PARTIALLY_FULFILLED
            ]
            if txn.status not in allowed_statuses:
                raise ValidationError(
                    f"Transaction {txn.tx_id} is {txn.get_status_display()} and cannot be combined. "
                    "Only NOT_PROCESSED or PARTIALLY_FULFILLED transactions can be combined."
                )

        # Calculate total amount and sum of already fulfilled amounts
        total_amount = sum(txn.amount for txn in transactions)
        total_already_fulfilled = sum(txn.amount_fulfilled for txn in transactions)

        # Check if any transaction is a registration transaction
        any_registration = any(txn.is_registration for txn in transactions)
        total_registration_kit_quantity = sum(
            txn.registration_kit_quantity for txn in transactions
            if txn.is_registration and txn.registration_kit_issued
        )
        total_registration_kit_amount = sum(
            txn.registration_kit_amount_deducted for txn in transactions
            if txn.is_registration and txn.registration_kit_issued
        )

        # Get gateway from first transaction (they should all be from same gateway ideally)
        first_gateway = transactions[0].gateway

        # Create parent transaction for the combined order
        # Use combined order ID as tx_id
        import hashlib
        now = timezone.now()
        parent_tx_id = now.strftime('CMB-%Y%m%d-%H%M%S')

        # Generate unique hash for parent transaction
        hash_input = f"{parent_tx_id}|{total_amount}|{now.isoformat()}"
        unique_hash = hashlib.sha256(hash_input.encode()).hexdigest()

        # Determine initial status based on whether any transactions were partially fulfilled
        initial_status = Transaction.OrderStatus.PROCESSING
        if total_already_fulfilled > 0:
            initial_status = Transaction.OrderStatus.PARTIALLY_FULFILLED

        parent_transaction = Transaction.objects.create(
            tx_id=parent_tx_id,
            amount=total_amount,
            sender_name=customer_name or f"{len(transaction_ids)} combined payments",
            sender_phone=customer_phone,
            timestamp=now,
            gateway=first_gateway,
            confidence=1.0,
            status=initial_status,
            amount_fulfilled=total_already_fulfilled,  # Carry over fulfilled amounts
            unique_hash=unique_hash,
            # Inherit registration status from child transactions
            is_registration=any_registration,
            registration_kit_issued=any(txn.registration_kit_issued for txn in transactions if txn.is_registration),
            registration_kit_amount_deducted=total_registration_kit_amount
        )

        # Determine combined order status
        combined_order_status = CombinedOrder.Status.PENDING
        if total_already_fulfilled > 0:
            combined_order_status = CombinedOrder.Status.PARTIALLY_FULFILLED

        # Create combined order
        combined_order = CombinedOrder.objects.create(
            combined_order_id=parent_tx_id,  # Use same ID as parent transaction
            parent_transaction=parent_transaction,
            total_amount=total_amount,
            amount_fulfilled=total_already_fulfilled,  # Carry over fulfilled amounts
            base_amount_fulfilled=total_already_fulfilled,  # Track the "base" from child transactions
            customer_name=customer_name,
            customer_phone=customer_phone,
            notes=notes,
            created_by=created_by,
            status=combined_order_status
        )

        # Link transactions to combined order AND copy their line items
        copied_items_count = 0
        for idx, txn in enumerate(transactions):
            CombinedOrderTransaction.objects.create(
                combined_order=combined_order,
                transaction=txn,
                sequence=idx,
                added_by=created_by
            )

            # Copy line items from partially fulfilled transactions
            # These items already had inventory deducted, so mark them as such
            for line_item in txn.line_items.filter(is_inventory_deducted=True):
                co_line_item = CombinedOrderLineItem.objects.create(
                    combined_order=combined_order,
                    product=line_item.product,
                    scanned_prod_code=line_item.scanned_prod_code,
                    scanned_prod_name=line_item.scanned_prod_name,
                    scanned_sku=line_item.scanned_sku,
                    scanned_sku_name=line_item.scanned_sku_name,
                    scanned_price=line_item.scanned_price,
                    scanned_pv=line_item.scanned_pv,
                    quantity=line_item.quantity,
                    line_total=line_item.line_total,
                    line_cost=line_item.line_cost,
                    line_pv=line_item.line_pv,
                    is_inventory_deducted=True,  # Already deducted from original transaction
                    copied_from_transaction=txn,
                    scanned_by=line_item.scanned_by or created_by
                )
                # Preserve original scan timestamp for accurate daily sales reporting.
                # auto_now_add=True prevents setting it at create time, so use update().
                CombinedOrderLineItem.objects.filter(pk=co_line_item.pk).update(
                    scanned_at=line_item.scanned_at
                )
                copied_items_count += 1

            # B4: If transaction has registration kit issued, create a line item for it
            # Registration kit amounts are tracked via registration_kit_* fields, not as line items
            # So we need to create a synthetic line item to display in the combined order UI
            if txn.is_registration and txn.registration_kit_issued:
                try:
                    reg_kit_product = Product.objects.get(prod_code='REG_KIT_001')
                    kit_quantity = txn.registration_kit_quantity or 1
                    kit_price = txn.registration_kit_amount_deducted / kit_quantity
                    CombinedOrderLineItem.objects.create(
                        combined_order=combined_order,
                        product=reg_kit_product,
                        scanned_prod_code='REG_KIT_001',
                        scanned_prod_name='Registration Kit',
                        scanned_sku=reg_kit_product.sku,
                        scanned_sku_name=reg_kit_product.sku_name or '',
                        scanned_price=kit_price,
                        scanned_pv=reg_kit_product.current_pv,
                        quantity=kit_quantity,
                        line_total=txn.registration_kit_amount_deducted,
                        line_cost=reg_kit_product.cost_price * kit_quantity,
                        line_pv=reg_kit_product.current_pv * kit_quantity,
                        is_inventory_deducted=True,  # Kit was already deducted
                        copied_from_transaction=txn,
                        scanned_by='System (Registration Kit)'
                    )
                    copied_items_count += 1
                    logger.info(
                        f"Created registration kit line item for transaction {txn.tx_id} "
                        f"in combined order {combined_order.combined_order_id}"
                    )
                except Product.DoesNotExist:
                    logger.warning(
                        f"Registration kit product (REG_KIT_001) not found when copying "
                        f"transaction {txn.tx_id} to combined order {combined_order.combined_order_id}"
                    )

        # Immediately mark all child transactions as COMBINED_FULFILLED
        # They become read-only and link to the combined order
        for txn in transactions:
            txn.status = Transaction.OrderStatus.COMBINED_FULFILLED
            txn.save()

        logger.info(
            f"Copied {copied_items_count} line items from partially fulfilled transactions "
            f"to combined order {combined_order.combined_order_id}"
        )

        # Update parent transaction's amount fields to match combined order totals
        # This ensures the parent transaction displays correct combined amounts
        # Note: remaining_amount is a computed property (amount - amount_fulfilled), so we don't set it
        # NOTE: Must also update amount_paid to keep in sync for legacy remaining_amount calculation
        parent_transaction.amount = combined_order.total_amount
        parent_transaction.amount_fulfilled = combined_order.amount_fulfilled
        parent_transaction.amount_paid = combined_order.amount_fulfilled  # Keep in sync for backwards compatibility
        parent_transaction.save(update_fields=['amount', 'amount_fulfilled', 'amount_paid', 'updated_at'])

        logger.info(
            f"Created combined order {combined_order.combined_order_id} with "
            f"{len(transaction_ids)} transactions totaling {total_amount} KES. "
            f"Marked {len(transaction_ids)} child transactions as COMBINED_FULFILLED. "
            f"Updated parent transaction {parent_transaction.tx_id} amount to {parent_transaction.amount}"
        )

        return {
            'success': True,
            'combined_order_id': combined_order.combined_order_id,
            'transaction_count': len(transaction_ids),
            'total_amount': float(total_amount),
            'amount_fulfilled': float(combined_order.amount_fulfilled),
            'remaining_amount': float(combined_order.remaining_amount),
            'status': combined_order.status,
            'customer_name': combined_order.customer_name,
            'customer_phone': combined_order.customer_phone,
            'notes': combined_order.notes,
            'created_by': combined_order.created_by,
            'created_at': combined_order.created_at.isoformat(),
            'transaction_ids': [txn.tx_id for txn in transactions]
        }

    @staticmethod
    @transaction.atomic
    def scan_product_to_combined_order(
        combined_order_id: str,
        product_id: int,
        quantity: int = 1,
        scanned_by: str = "System"
    ) -> Dict:
        """
        Scan a product into a combined order (for fulfillment).

        Args:
            combined_order_id: Combined order ID
            product_id: Product ID to scan
            quantity: Quantity to issue
            scanned_by: Username/identifier of user scanning

        Returns:
            Dict with scan result and updated combined order stats

        Raises:
            ValidationError: If validation fails
        """
        # Fetch combined order
        try:
            combined_order = CombinedOrder.objects.get(combined_order_id=combined_order_id)
        except CombinedOrder.DoesNotExist:
            raise ValidationError(f"Combined order {combined_order_id} not found")

        # Check if order is in valid state for scanning
        if combined_order.status == CombinedOrder.Status.FULFILLED:
            raise ValidationError(f"Combined order {combined_order_id} is already fulfilled")

        if combined_order.status == CombinedOrder.Status.CANCELLED:
            raise ValidationError(f"Combined order {combined_order_id} is cancelled")

        # Fetch product
        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            raise ValidationError(f"Product with ID {product_id} not found")

        # Check stock availability
        if product.quantity < quantity:
            raise ValidationError(
                f"Insufficient stock for {product.prod_name}. "
                f"Available: {product.quantity}, Requested: {quantity}"
            )

        # Calculate line total using cost_price (buying price)
        line_total = product.cost_price * quantity

        # Check if would exceed combined order total
        new_amount_fulfilled = combined_order.amount_fulfilled + line_total
        if new_amount_fulfilled > combined_order.total_amount:
            raise ValidationError(
                f"Cannot add item worth {line_total} KES. "
                f"Remaining budget: {combined_order.remaining_amount} KES"
            )

        # Create line item
        line_item = CombinedOrderLineItem.objects.create(
            combined_order=combined_order,
            product=product,
            scanned_prod_code=product.prod_code,
            scanned_prod_name=product.prod_name,
            scanned_sku=product.sku,
            scanned_sku_name=product.sku_name,
            scanned_price=product.cost_price,  # Use cost_price (buying price)
            scanned_pv=product.current_pv,
            quantity=quantity,
            scanned_by=scanned_by
        )

        # Update combined order amount_fulfilled
        combined_order.amount_fulfilled = new_amount_fulfilled

        # Update status to IN_PROGRESS if first item
        if combined_order.status == CombinedOrder.Status.PENDING:
            combined_order.status = CombinedOrder.Status.IN_PROGRESS

        # Auto-complete if fully fulfilled
        if combined_order.amount_fulfilled >= combined_order.total_amount:
            combined_order.status = CombinedOrder.Status.FULFILLED
            combined_order.fulfilled_at = timezone.now()
            combined_order.fulfilled_by = scanned_by

        combined_order.save()

        # Update product inventory
        old_quantity = product.quantity
        product.quantity -= quantity
        product.save()

        # Create inventory movement record
        InventoryMovement.objects.create(
            movement_type=InventoryMovement.MovementType.SALE,
            product=product,
            quantity_before=old_quantity,
            quantity_after=product.quantity,
            quantity_change=-quantity,
            reference=f"Combined Order: {combined_order.combined_order_id}",
            performed_by=scanned_by
        )

        logger.info(
            f"Scanned {quantity}x {product.prod_name} to combined order {combined_order_id}. "
            f"Line total: {line_total} KES, Remaining: {combined_order.remaining_amount} KES"
        )

        return {
            'success': True,
            'line_item': line_item,
            'combined_order': combined_order,
            'amount_fulfilled': combined_order.amount_fulfilled,
            'remaining_amount': combined_order.remaining_amount,
            'fulfillment_percentage': combined_order.fulfillment_percentage,
            'is_fulfilled': combined_order.status == CombinedOrder.Status.FULFILLED
        }

    @staticmethod
    @transaction.atomic
    def cancel_combined_order(
        combined_order_id: str,
        cancelled_by: str,
        reason: str = ""
    ) -> Dict:
        """
        Cancel a combined order and reverse any issued products.

        Args:
            combined_order_id: Combined order ID
            cancelled_by: Username/identifier
            reason: Cancellation reason

        Returns:
            Dict with cancellation result

        Raises:
            ValidationError: If validation fails
        """
        # Fetch combined order
        try:
            combined_order = CombinedOrder.objects.get(combined_order_id=combined_order_id)
        except CombinedOrder.DoesNotExist:
            raise ValidationError(f"Combined order {combined_order_id} not found")

        # Check if already cancelled or fulfilled
        if combined_order.status == CombinedOrder.Status.CANCELLED:
            raise ValidationError(f"Combined order {combined_order_id} is already cancelled")

        if combined_order.status == CombinedOrder.Status.FULFILLED:
            raise ValidationError(
                f"Combined order {combined_order_id} is fulfilled and cannot be cancelled. "
                "Please reverse via inventory management."
            )

        # Only reverse line items that were actually deducted from inventory
        # Items that were scanned but not yet completed (is_inventory_deducted=False) don't need reversal
        reversed_count = 0
        for line_item in combined_order.line_items.filter(is_inventory_deducted=True):
            # Only reverse if this is NOT a copied item from a child transaction
            # (copied items were already deducted in the original transaction)
            if line_item.copied_from_transaction is None:
                # Return stock to inventory
                product = line_item.product
                old_quantity = product.quantity
                product.quantity += line_item.quantity
                product.save()

                # Create inventory movement record
                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.MovementType.RETURN,
                    product=product,
                    quantity_before=old_quantity,
                    quantity_after=product.quantity,
                    quantity_change=line_item.quantity,
                    reference=f"Reversed: Combined Order {combined_order.combined_order_id}",
                    performed_by=cancelled_by
                )

                reversed_count += 1

        # Delete all line items (both deducted and pending)
        combined_order.line_items.all().delete()

        # Restore child transactions from COMBINED_FULFILLED to their actual status.
        # Without this, their TransactionLineItems are excluded from sales counts
        # (calculate_issued_from_orders excludes COMBINED_FULFILLED transactions)
        # even though their inventory deductions are still in effect.
        child_links = CombinedOrderTransaction.objects.filter(
            combined_order=combined_order
        ).select_related('transaction')

        for link in child_links:
            txn = link.transaction
            if txn.status == Transaction.OrderStatus.COMBINED_FULFILLED:
                if txn.amount_fulfilled >= txn.amount:
                    restored_status = Transaction.OrderStatus.FULFILLED
                elif txn.amount_fulfilled > 0:
                    restored_status = Transaction.OrderStatus.PARTIALLY_FULFILLED
                else:
                    restored_status = Transaction.OrderStatus.NOT_PROCESSED
                txn.status = restored_status
                txn.save(update_fields=['status', 'updated_at'], skip_validation=True)

        # Update combined order status
        combined_order.status = CombinedOrder.Status.CANCELLED
        combined_order.amount_fulfilled = Decimal('0.00')  # Reset amount since order is cancelled
        combined_order.notes += f"\n\n[CANCELLED {timezone.now()}]\nBy: {cancelled_by}\nReason: {reason or 'N/A'}\n{reversed_count} line items reversed."
        combined_order.amount_fulfilled_before_activation = None
        combined_order.status_before_activation = None
        combined_order.save()

        # Update parent transaction status
        if combined_order.parent_transaction:
            parent = combined_order.parent_transaction
            parent.status = Transaction.OrderStatus.CANCELLED
            parent.amount_fulfilled = Decimal('0.00')  # Reset amount since order is cancelled
            parent.amount_paid = Decimal('0.00')  # Keep in sync
            parent.save(update_fields=['status', 'amount_fulfilled', 'amount_paid', 'updated_at'])

        logger.info(
            f"Cancelled combined order {combined_order_id}. "
            f"Reversed {reversed_count} line items. "
            f"Parent transaction marked as CANCELLED."
        )

        return {
            'success': True,
            'combined_order_id': combined_order_id,
            'reversed_line_items': reversed_count,
            'status': combined_order.status
        }

    @staticmethod
    @transaction.atomic
    def cancel_combined_order_issuance(
        combined_order_id: str,
        cancelled_by: str,
        reason: str = ""
    ) -> Dict:
        """
        Cancel the current issuance session for a combined order.

        Unlike cancel_combined_order, this:
        - Only removes PENDING line items (not yet deducted from inventory)
        - Restores the order to its state BEFORE activation
        - Does NOT fully cancel the combined order

        Use this when the user wants to abandon current scanning and start over,
        without cancelling the entire combined order.

        Args:
            combined_order_id: Combined order ID
            cancelled_by: Username/identifier
            reason: Cancellation reason

        Returns:
            Dict with cancellation result

        Raises:
            ValidationError: If validation fails
        """
        logger.info(f"[CANCEL ISSUANCE] Starting issuance cancellation for combined order {combined_order_id}")
        logger.info(f"[CANCEL ISSUANCE] Cancelled by: {cancelled_by}, Reason: {reason or 'N/A'}")

        try:
            logger.info(f"[CANCEL ISSUANCE] Fetching combined order with ID: {combined_order_id}")
            combined_order = CombinedOrder.objects.select_for_update().get(
                combined_order_id=combined_order_id
            )
            logger.info(f"[CANCEL ISSUANCE] Found combined order. Current status: {combined_order.status}")
            logger.info(f"[CANCEL ISSUANCE] Total amount: {combined_order.total_amount}, Amount fulfilled: {combined_order.amount_fulfilled}")
            logger.info(f"[CANCEL ISSUANCE] is_in_issuance on parent: {combined_order.parent_transaction.is_in_issuance if combined_order.parent_transaction else 'No parent'}")
        except CombinedOrder.DoesNotExist:
            logger.error(f"[CANCEL ISSUANCE] Combined order {combined_order_id} not found in database")
            raise ValidationError(f"Combined order {combined_order_id} not found")

        # Allow IN_PROGRESS or PARTIALLY_FULFILLED
        # We allow PARTIALLY_FULFILLED because scanning (staged) is allowed in that state,
        # so we must allow cancelling the pending items even if not explicitly activated.
        allowed_statuses = [CombinedOrder.Status.IN_PROGRESS, CombinedOrder.Status.PARTIALLY_FULFILLED]
        logger.info(f"[CANCEL ISSUANCE] Validating order status. Current: {combined_order.status}, Allowed: {allowed_statuses}")
        if combined_order.status not in allowed_statuses:
            error_msg = (
                f"Cannot cancel issuance for {combined_order.get_status_display()} order. "
                f"Order must be IN_PROGRESS or PARTIALLY_FULFILLED."
            )
            logger.error(f"[CANCEL ISSUANCE] Status validation failed: {error_msg}")
            raise ValidationError(error_msg)

        # Get the state BEFORE this issuance session started (if available)
        logger.info(f"[CANCEL ISSUANCE] Retrieving pre-activation state")
        previous_amount_fulfilled = combined_order.amount_fulfilled_before_activation
        previous_status = combined_order.status_before_activation
        logger.info(f"[CANCEL ISSUANCE] Previous amount_fulfilled_before_activation: {previous_amount_fulfilled}")
        logger.info(f"[CANCEL ISSUANCE] Previous status_before_activation: {previous_status}")

        # Delete ONLY the pending line items (not yet deducted from inventory)
        # Keep the completed items (from previous sessions or copied from child transactions)
        logger.info(f"[CANCEL ISSUANCE] Finding pending line items (is_inventory_deducted=False)")
        pending_items = combined_order.line_items.filter(is_inventory_deducted=False)
        pending_count = pending_items.count()
        logger.info(f"[CANCEL ISSUANCE] Found {pending_count} pending line items to remove")

        # Log details of pending items before deletion
        if pending_count > 0:
            logger.info(f"[CANCEL ISSUANCE] Pending items to be removed:")
            for item in pending_items:
                logger.info(f"  - ID: {item.id}, Product: {item.scanned_prod_name}, Qty: {item.quantity}, Total: {item.line_total}, Copied: {item.copied_from_transaction}")

        logger.info(f"[CANCEL ISSUANCE] Deleting {pending_count} pending line items...")
        pending_items.delete()
        logger.info(f"[CANCEL ISSUANCE] Pending items deleted successfully")

        # Restore the state
        logger.info(f"[CANCEL ISSUANCE] Restoring combined order state")
        if previous_amount_fulfilled is not None:
            logger.info(f"[CANCEL ISSUANCE] Using previous_amount_fulfilled: {previous_amount_fulfilled}")
            combined_order.amount_fulfilled = previous_amount_fulfilled
        else:
            # If not tracked (e.g. not explicitly activated), recalculate
            logger.warning(f"[CANCEL ISSUANCE] previous_amount_fulfilled is None, recalculating from line items")
            recalculated = CombinedOrderService.recalculate_amount_fulfilled(combined_order)
            logger.info(f"[CANCEL ISSUANCE] Recalculated amount_fulfilled: {recalculated}")
            combined_order.amount_fulfilled = recalculated

        if previous_status:
            logger.info(f"[CANCEL ISSUANCE] Using previous_status: {previous_status}")
            combined_order.status = previous_status
        else:
            # Derive the status from the amount
            logger.warning(f"[CANCEL ISSUANCE] previous_status is None, deriving from amount")
            if combined_order.amount_fulfilled >= combined_order.total_amount:
                derived_status = CombinedOrder.Status.FULFILLED
            elif combined_order.amount_fulfilled > 0:
                derived_status = CombinedOrder.Status.PARTIALLY_FULFILLED
            else:
                derived_status = CombinedOrder.Status.PENDING
            logger.info(f"[CANCEL ISSUANCE] Derived status: {derived_status}")
            combined_order.status = derived_status

        logger.info(f"[CANCEL ISSUANCE] Final state: status={combined_order.status}, amount_fulfilled={combined_order.amount_fulfilled}")
        combined_order.amount_fulfilled_before_activation = None
        combined_order.status_before_activation = None

        if reason:
            cancel_note = f"\n\n[ISSUANCE CANCELLED {timezone.now()}]\nBy: {cancelled_by}\nReason: {reason or 'N/A'}\n{pending_count} pending items removed."
            combined_order.notes += cancel_note
            logger.info(f"[CANCEL ISSUANCE] Added cancellation note to order")

        combined_order.save()
        logger.info(f"[CANCEL ISSUANCE] Combined order saved successfully")

        # Also update the parent transaction
        if combined_order.parent_transaction:
            logger.info(f"[CANCEL ISSUANCE] Updating parent transaction: {combined_order.parent_transaction.tx_id}")
            parent = combined_order.parent_transaction
            logger.info(f"[CANCEL ISSUANCE] Parent transaction BEFORE update: status={parent.status}, amount_fulfilled={parent.amount_fulfilled}, is_in_issuance={parent.is_in_issuance}")

            parent.amount_fulfilled = combined_order.amount_fulfilled
            # CRITICAL: Must also update amount_paid to prevent save() from reverting
            # (Transaction.save() syncs these fields and takes the higher value)
            parent.amount_paid = combined_order.amount_fulfilled
            parent.is_in_issuance = False  # Clear the issuance flag

            # Map the combined status to the transaction status
            if combined_order.status == CombinedOrder.Status.PARTIALLY_FULFILLED:
                parent.status = Transaction.OrderStatus.PARTIALLY_FULFILLED
            elif combined_order.status == CombinedOrder.Status.PENDING:
                parent.status = Transaction.OrderStatus.PROCESSING # Map PENDING to PROCESSING
            else:
                parent.status = Transaction.OrderStatus.PROCESSING

            logger.info(f"[CANCEL ISSUANCE] Parent transaction AFTER update: status={parent.status}, amount_fulfilled={parent.amount_fulfilled}, is_in_issuance={parent.is_in_issuance}")

            # Use skip_validation=True because we're doing a coordinated update where the final state is valid
            parent.save(update_fields=['amount_fulfilled', 'amount_paid', 'status', 'is_in_issuance', 'updated_at'], skip_validation=True)
            logger.info(f"[CANCEL ISSUANCE] Parent transaction saved successfully")
        else:
            logger.warning(f"[CANCEL ISSUANCE] No parent transaction found for combined order {combined_order_id}")

        logger.info(
            f"[CANCEL ISSUANCE] Successfully cancelled issuance session for combined order {combined_order_id}. "
            f"Removed {pending_count} pending items. Restored to {combined_order.status}."
        )

        return {
            'success': True,
            'combined_order_id': combined_order_id,
            'pending_items_removed': pending_count,
            'status': combined_order.status,
            'amount_fulfilled': float(combined_order.amount_fulfilled),
            'previous_status': previous_status if previous_status else combined_order.status,
            'message': f'Issuance cancelled. {pending_count} pending items removed. Restored to {combined_order.status}.'
        }

    @staticmethod
    @transaction.atomic
    def revert_combined_order(
        combined_order_id: str,
        reverted_by: str,
        reason: str = ""
    ) -> Dict:
        """
        Completely revert a combined order to pre-combination state.

        This function:
        1. Reverses ALL inventory changes (returns products to stock)
        2. Restores child transactions to their original pre-combination status
        3. Deletes all line items
        4. Deletes the combined order entirely

        Use this when you want to completely undo a combination and start fresh.

        Args:
            combined_order_id: Combined order ID
            reverted_by: Username/identifier
            reason: Revert reason

        Returns:
            Dict with revert result

        Raises:
            ValidationError: If validation fails
        """
        logger.info(f"[REVERT] Starting full revert for combined order {combined_order_id}")
        logger.info(f"[REVERT] Reverted by: {reverted_by}, Reason: {reason or 'N/A'}")

        # Fetch combined order
        try:
            combined_order = CombinedOrder.objects.select_for_update().get(
                combined_order_id=combined_order_id
            )
        except CombinedOrder.DoesNotExist:
            raise ValidationError(f"Combined order {combined_order_id} not found")

        logger.info(f"[REVERT] Combined order status: {combined_order.status}")
        logger.info(f"[REVERT] Total amount: {combined_order.total_amount}")
        logger.info(f"[REVERT] Amount fulfilled: {combined_order.amount_fulfilled}")

        # Step 1: Reverse inventory for all deducted line items
        logger.info(f"[REVERT] Step 1: Reversing inventory for deducted line items")
        reversed_count = 0
        inventory_movements = []

        for line_item in combined_order.line_items.filter(is_inventory_deducted=True):
            # Skip items that were copied from child transactions
            # (they were already deducted in the original transaction)
            if line_item.copied_from_transaction is not None:
                logger.info(f"[REVERT]   Skipping copied item: {line_item.scanned_prod_name} (from {line_item.copied_from_transaction.tx_id})")
                continue

            # Return stock to inventory
            product = line_item.product
            old_quantity = product.quantity
            product.quantity += line_item.quantity
            product.save()

            logger.info(f"[REVERT]   Returned {line_item.quantity}x {product.prod_name}: {old_quantity} → {product.quantity}")

            # Create inventory movement record
            movement = InventoryMovement.objects.create(
                movement_type=InventoryMovement.MovementType.RETURN,
                product=product,
                quantity_before=old_quantity,
                quantity_after=product.quantity,
                quantity_change=line_item.quantity,
                reference=f"Reverted: {combined_order.combined_order_id} | Reason: {reason or 'N/A'}",
                performed_by=reverted_by,
            )
            inventory_movements.append(movement.id)
            reversed_count += 1

        logger.info(f"[REVERT] Reversed {reversed_count} line items")

        # Step 2: Get all child transactions and their original states
        logger.info(f"[REVERT] Step 2: Restoring child transactions")
        child_links = CombinedOrderTransaction.objects.filter(
            combined_order=combined_order
        ).select_related('transaction')

        restored_transactions = []
        for link in child_links:
            txn = link.transaction

            # Determine original status based on amount_fulfilled
            if txn.amount_fulfilled >= txn.amount:
                original_status = Transaction.OrderStatus.FULFILLED
            elif txn.amount_fulfilled > 0:
                original_status = Transaction.OrderStatus.PARTIALLY_FULFILLED
            else:
                original_status = Transaction.OrderStatus.NOT_PROCESSED

            logger.info(f"[REVERT]   Restoring {txn.tx_id} to {original_status} (fulfilled: {txn.amount_fulfilled}/{txn.amount})")

            txn.status = original_status
            txn.notes += f"\n\n[REVERTED FROM COMBINED ORDER {timezone.now()}]\nOrder: {combined_order_id}\nBy: {reverted_by}\nReason: {reason or 'N/A'}"
            # Use skip_validation to allow COMBINED_FULFILLED → PARTIALLY_FULFILLED/FULFILLED transitions
            # Note: is_in_combined_order is tracked through relationship, not a database field
            txn.save(update_fields=['status', 'notes', 'updated_at'], skip_validation=True)

            restored_transactions.append({
                'tx_id': txn.tx_id,
                'restored_status': original_status
            })

        logger.info(f"[REVERT] Restored {len(restored_transactions)} child transactions")

        # Step 3: Delete all line items
        logger.info(f"[REVERT] Step 3: Deleting all line items")
        line_items_count = combined_order.line_items.count()
        combined_order.line_items.all().delete()
        logger.info(f"[REVERT] Deleted {line_items_count} line items")

        # Step 4: Delete the combined order parent transaction (if exists)
        parent_tx_id = None
        if combined_order.parent_transaction:
            parent_tx_id = combined_order.parent_transaction.tx_id
            logger.info(f"[REVERT] Step 4: Deleting parent transaction {parent_tx_id}")
            combined_order.parent_transaction.delete()

        # Step 5: Delete the combined order itself
        logger.info(f"[REVERT] Step 5: Deleting combined order {combined_order_id}")
        combined_order.delete()

        logger.info(f"[REVERT] Successfully reverted and deleted combined order {combined_order_id}")

        return {
            'success': True,
            'combined_order_id': combined_order_id,
            'parent_transaction_id': parent_tx_id,
            'reversed_line_items': reversed_count,
            'restored_transactions': restored_transactions,
            'inventory_movements_created': len(inventory_movements),
            'message': f'Combined order reverted successfully. {len(restored_transactions)} transactions restored, {reversed_count} items returned to stock.'
        }

    @staticmethod
    def get_combined_order_details(combined_order_id: str) -> Dict:
        """
        Get detailed information about a combined order.

        Args:
            combined_order_id: Combined order ID

        Returns:
            Dict with full combined order details

        Raises:
            ValidationError: If not found
        """
        try:
            combined_order = CombinedOrder.objects.prefetch_related(
                'transactions__transaction',
                'line_items__product'
            ).get(combined_order_id=combined_order_id)
        except CombinedOrder.DoesNotExist:
            raise ValidationError(f"Combined order {combined_order_id} not found")

        # Get transactions
        transactions = combined_order.transactions.all().order_by('sequence')

        # Get line items
        line_items = combined_order.line_items.all()

        return {
            'combined_order_id': combined_order.combined_order_id,
            'status': combined_order.status,
            'total_amount': combined_order.total_amount,
            'amount_fulfilled': combined_order.amount_fulfilled,
            'remaining_amount': combined_order.remaining_amount,
            'fulfillment_percentage': combined_order.fulfillment_percentage,
            'transaction_count': transactions.count(),
            'customer_name': combined_order.customer_name,
            'customer_phone': combined_order.customer_phone,
            'notes': combined_order.notes,
            'created_by': combined_order.created_by,
            'created_at': combined_order.created_at,
            'fulfilled_at': combined_order.fulfilled_at,
            'fulfilled_by': combined_order.fulfilled_by,
            'transactions': [
                {
                    'tx_id': link.transaction.tx_id,
                    'amount': link.transaction.amount,
                    'sender_name': link.transaction.sender_name,
                    'sender_phone': link.transaction.sender_phone,
                    'timestamp': link.transaction.timestamp,
                    'sequence': link.sequence
                }
                for link in transactions
            ],
            'line_items': [
                {
                    'id': item.id,
                    'product_code': item.scanned_prod_code,
                    'product_name': item.scanned_prod_name,
                    'sku': item.scanned_sku,
                    'quantity': item.quantity,
                    'unit_price': float(item.scanned_price),
                    'line_total': float(item.line_total),
                    'scanned_at': item.scanned_at.isoformat() if item.scanned_at else None,
                    'scanned_by': item.scanned_by
                }
                for item in line_items
            ]
        }

    @staticmethod
    def list_combined_orders(
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict:
        """
        List combined orders with optional filtering.

        Args:
            status: Optional status filter
            limit: Max results to return
            offset: Pagination offset

        Returns:
            Dict with combined orders list and count
        """
        queryset = CombinedOrder.objects.all()

        if status:
            queryset = queryset.filter(status=status)

        total_count = queryset.count()
        orders = queryset.prefetch_related('transactions')[offset:offset+limit]

        return {
            'count': total_count,
            'limit': limit,
            'offset': offset,
            'combined_orders': [
                {
                    'combined_order_id': order.combined_order_id,
                    'status': order.status,
                    'total_amount': order.total_amount,
                    'amount_fulfilled': order.amount_fulfilled,
                    'remaining_amount': order.remaining_amount,
                    'transaction_count': order.transaction_count,
                    'customer_name': order.customer_name,
                    'customer_phone': order.customer_phone,
                    'created_at': order.created_at,
                    'created_by': order.created_by
                }
                for order in orders
            ]
        }

    @staticmethod
    @transaction.atomic
    def activate_combined_order(combined_order_id: str, activated_by: str):
        """
        Activate a combined order for fulfillment.
        Changes status from PENDING or PARTIALLY_FULFILLED to IN_PROGRESS.

        Args:
            combined_order_id: Combined order ID
            activated_by: User activating the order

        Returns:
            CombinedOrder instance

        Raises:
            ValidationError: If order not found, already fully fulfilled, or cancelled
        """
        # Check if stock-taking session is active
        active_stock_take = StockTakeService.get_active_session()
        if active_stock_take:
            raise ValidationError(
                f'Stock-taking session {active_stock_take.session_id} is in progress. '
                f'Complete or cancel the stock-take session before activating combined orders.'
            )

        try:
            order = CombinedOrder.objects.select_for_update().get(
                combined_order_id=combined_order_id
            )
        except CombinedOrder.DoesNotExist:
            raise ValidationError(f"Combined order {combined_order_id} not found")

        # Verify order can be activated (PENDING, PARTIALLY_FULFILLED, or already IN_PROGRESS)
        # If already IN_PROGRESS, this is a no-op (idempotent activation)
        if order.status == CombinedOrder.Status.IN_PROGRESS:
            logger.info(
                f"Combined order {combined_order_id} is already IN_PROGRESS. "
                f"Activation is idempotent - returning without changes."
            )
            return order

        if order.status not in [CombinedOrder.Status.PENDING, CombinedOrder.Status.PARTIALLY_FULFILLED]:
            raise ValidationError(
                f"Cannot activate {order.get_status_display()} order. "
                f"Order must be PENDING, PARTIALLY_FULFILLED, or IN_PROGRESS."
            )

        # Save state BEFORE activation for cancel restoration
        order.amount_fulfilled_before_activation = order.amount_fulfilled
        order.status_before_activation = order.status

        # Set to IN_PROGRESS
        order.status = CombinedOrder.Status.IN_PROGRESS
        order.save()

        # Set parent transaction to issuance mode
        if order.parent_transaction:
            order.parent_transaction.is_in_issuance = True
            order.parent_transaction.save(update_fields=['is_in_issuance', 'updated_at'])

        # Safety check: ensure all child transactions are marked COMBINED_FULFILLED
        # (They should already be marked during creation, but check anyway)
        linked_transactions = order.transactions.all()
        updated_count = 0
        for link in linked_transactions:
            txn = link.transaction
            if txn.status != Transaction.OrderStatus.COMBINED_FULFILLED:
                txn.status = Transaction.OrderStatus.COMBINED_FULFILLED
                txn.save()
                updated_count += 1

        if updated_count > 0:
            logger.warning(
                f"Combined order {combined_order_id} activation: marked {updated_count} child transactions "
                f"as COMBINED_FULFILLED (they should have been marked during creation)."
            )

        logger.info(
            f"Combined order {combined_order_id} activated by {activated_by}. "
            f"Status changed to IN_PROGRESS."
        )

        return order

    @staticmethod
    @transaction.atomic
    def scan_product_to_combined_order_staged(
        combined_order_id: str,
        product_id: int,
        quantity: int,
        scanned_by: str
    ):
        """
        Scan a product to combined order (STAGED - inventory NOT updated yet).
        Creates line item and updates amount_fulfilled but doesn't touch inventory.

        Args:
            combined_order_id: Combined order ID
            product_id: Product ID to scan
            quantity: Quantity scanned
            scanned_by: User scanning the product

        Returns:
            CombinedOrderLineItem instance

        Raises:
            ValidationError: If order not found, not in progress, product not found,
                           or budget exceeded
        """
        try:
            order = CombinedOrder.objects.select_for_update().get(
                combined_order_id=combined_order_id
            )
        except CombinedOrder.DoesNotExist:
            raise ValidationError(f"Combined order {combined_order_id} not found")

        # Verify order is IN_PROGRESS or PARTIALLY_FULFILLED
        if order.status not in [CombinedOrder.Status.IN_PROGRESS, CombinedOrder.Status.PARTIALLY_FULFILLED]:
            raise ValidationError(
                f"Cannot scan to {order.get_status_display()} order. "
                f"Order must be IN_PROGRESS or PARTIALLY_FULFILLED."
            )

        # Get product
        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            raise ValidationError(f"Product {product_id} not found")

        # Validate quantity
        if quantity <= 0:
            raise ValidationError("Quantity must be positive")

        # Calculate line total using cost_price (buying price)
        unit_price = product.cost_price
        line_total = unit_price * quantity

        # Check if product already exists in PENDING line items (not yet deducted)
        # Don't update items that were copied from child transactions (already deducted)
        # B3: Explicitly exclude copied items to handle any edge cases
        existing_pending_item = CombinedOrderLineItem.objects.filter(
            combined_order=order,
            product=product,
            is_inventory_deducted=False,
            copied_from_transaction__isnull=True  # Only match items scanned directly to this order
        ).first()

        if existing_pending_item:
            # Update existing PENDING line item quantity
            old_line_total = existing_pending_item.line_total
            new_quantity = existing_pending_item.quantity + quantity
            new_line_total = unit_price * new_quantity

            # Check if adding this would exceed budget
            new_fulfilled = order.amount_fulfilled - old_line_total + new_line_total
            if new_fulfilled > order.total_amount:
                raise ValidationError(
                    f"Adding {quantity}x {product.prod_name} (KES {line_total}) "
                    f"would exceed budget. Remaining: KES {order.remaining_amount}"
                )

            existing_pending_item.quantity = new_quantity
            existing_pending_item.line_total = new_line_total
            existing_pending_item.save()

            line_item = existing_pending_item
            logger.info(
                f"Product {product.prod_code} quantity updated in combined order "
                f"{combined_order_id} (STAGED, qty={existing_pending_item.quantity})"
            )
        else:
            # Check if adding this would exceed budget
            new_fulfilled = order.amount_fulfilled + line_total
            if new_fulfilled > order.total_amount:
                raise ValidationError(
                    f"Adding {quantity}x {product.prod_name} (KES {line_total}) "
                    f"would exceed budget. Remaining: KES {order.remaining_amount}"
                )

            # Create new line item (STAGED - no inventory update)
            line_item = CombinedOrderLineItem.objects.create(
                combined_order=order,
                product=product,
                scanned_prod_code=product.prod_code,
                scanned_prod_name=product.prod_name,
                scanned_sku=product.sku,
                scanned_sku_name=product.sku_name or '',
                scanned_price=unit_price,  # Use cost_price (buying price)
                scanned_pv=product.current_pv,
                quantity=quantity,
                line_total=line_total,
                line_cost=product.cost_price * quantity,
                line_pv=product.current_pv * quantity,
                scanned_by=scanned_by
            )

            logger.info(
                f"Product {product.prod_code} scanned to combined order "
                f"{combined_order_id} (STAGED, qty={quantity})"
            )

        # Apply promotions (may adjust scanned_price on qualifying items)
        PromotionService.apply_promotions(
            CombinedOrderLineItem.objects.filter(combined_order=order)
        )
        line_item.refresh_from_db()

        # Update amount_fulfilled
        # Use helper to ensure orphan amounts are preserved
        new_fulfilled = CombinedOrderService.recalculate_amount_fulfilled(order)
        order.amount_fulfilled = new_fulfilled
        order.save()

        # CRITICAL FIX: Also update parent transaction's amount_fulfilled to stay in sync
        # This ensures remaining_amount displays correctly on the frontend
        # NOTE: Must also update amount_paid to keep in sync for legacy remaining_amount calculation
        if order.parent_transaction:
            order.parent_transaction.amount_fulfilled = new_fulfilled
            order.parent_transaction.amount_paid = new_fulfilled  # Keep in sync for backwards compatibility
            order.parent_transaction.save(update_fields=['amount_fulfilled', 'amount_paid', 'updated_at'])

        return line_item

    @staticmethod
    @transaction.atomic
    def complete_combined_order(combined_order_id: str, completed_by: str):
        """
        Complete combined order and update inventory.
        Marks all linked transactions as COMBINED_FULFILLED.

        Args:
            combined_order_id: Combined order ID
            completed_by: User completing the order

        Returns:
            CombinedOrder instance

        Raises:
            ValidationError: If order not found or not in progress
        """
        try:
            order = CombinedOrder.objects.select_for_update().prefetch_related(
                'line_items__product',
                'transactions__transaction'
            ).get(combined_order_id=combined_order_id)
        except CombinedOrder.DoesNotExist:
            raise ValidationError(f"Combined order {combined_order_id} not found")

        # Verify order is IN_PROGRESS or PARTIALLY_FULFILLED
        if order.status not in [CombinedOrder.Status.IN_PROGRESS, CombinedOrder.Status.PARTIALLY_FULFILLED]:
            raise ValidationError(
                f"Cannot complete {order.get_status_display()} order. "
                f"Order must be IN_PROGRESS or PARTIALLY_FULFILLED."
            )

        # Get all line items
        line_items = order.line_items.all()

        if not line_items:
            raise ValidationError("Cannot complete order with no items")

        # Update inventory ONLY for items that haven't been deducted yet
        pending_items = line_items.filter(is_inventory_deducted=False)

        for item in pending_items:
            product = item.product

            # Check stock availability
            if product.quantity < item.quantity:
                raise ValidationError(
                    f"Insufficient stock for {product.prod_name}. "
                    f"Required: {item.quantity}, Available: {product.quantity}"
                )

            # Calculate quantities
            quantity_before = product.quantity
            quantity_after = quantity_before - item.quantity

            # Update product quantity
            product.quantity = quantity_after
            product.save()

            # Mark item as deducted
            item.is_inventory_deducted = True
            item.save(update_fields=['is_inventory_deducted'])

            # Create inventory movement for audit trail
            InventoryMovement.objects.create(
                movement_type=InventoryMovement.MovementType.SALE,
                product=product,
                quantity_before=quantity_before,
                quantity_after=quantity_after,
                quantity_change=-item.quantity,
                reference=f"Combined Order {combined_order_id}",
                performed_by=completed_by
            )

        # Determine if order is fully or partially fulfilled
        if order.amount_fulfilled >= order.total_amount:
            order.status = CombinedOrder.Status.FULFILLED
            parent_status = Transaction.OrderStatus.FULFILLED
            status_message = "FULFILLED"
        else:
            order.status = CombinedOrder.Status.PARTIALLY_FULFILLED
            parent_status = Transaction.OrderStatus.PARTIALLY_FULFILLED
            status_message = "PARTIALLY_FULFILLED"

        order.fulfilled_at = timezone.now()
        order.fulfilled_by = completed_by
        # Clear activation tracking since we're completing successfully
        order.amount_fulfilled_before_activation = None
        order.status_before_activation = None
        order.save()

        # Update parent transaction to match combined order totals
        # Note: remaining_amount is a computed property (amount - amount_fulfilled), so we don't set it
        # NOTE: Must also update amount_paid to keep in sync for legacy remaining_amount calculation
        if order.parent_transaction:
            parent = order.parent_transaction
            parent.status = parent_status
            parent.amount_fulfilled = order.amount_fulfilled
            parent.amount_paid = order.amount_fulfilled  # Keep in sync for backwards compatibility
            parent.is_in_issuance = False  # Clear issuance flag
            parent.save(update_fields=['status', 'amount_fulfilled', 'amount_paid', 'is_in_issuance', 'updated_at'])

        # Child transactions are already marked COMBINED_FULFILLED (from creation/activation)
        # No need to update them here - they remain COMBINED_FULFILLED regardless of partial/full fulfillment

        logger.info(
            f"Combined order {combined_order_id} completed by {completed_by}. "
            f"Status: {status_message}. "
            f"Parent transaction marked as {status_message}. "
            f"Child transactions remain COMBINED_FULFILLED (already marked)."
        )

        return order

    @staticmethod
    @transaction.atomic
    def remove_combined_order_line_item(combined_order_id: str, line_item_id: int):
        """
        Remove a line item from a combined order before completion.

        Args:
            combined_order_id: Combined order ID
            line_item_id: Line item ID to remove

        Raises:
            ValidationError: If order not in progress, item not found,
                           or item was copied from a child transaction
        """
        try:
            order = CombinedOrder.objects.select_for_update().get(
                combined_order_id=combined_order_id
            )
        except CombinedOrder.DoesNotExist:
            raise ValidationError(f"Combined order {combined_order_id} not found")

        # Verify order is IN_PROGRESS or PARTIALLY_FULFILLED
        if order.status not in [CombinedOrder.Status.IN_PROGRESS, CombinedOrder.Status.PARTIALLY_FULFILLED]:
            raise ValidationError(
                f"Cannot remove items from {order.get_status_display()} order. "
                f"Order must be IN_PROGRESS or PARTIALLY_FULFILLED."
            )

        try:
            line_item = CombinedOrderLineItem.objects.get(
                id=line_item_id,
                combined_order=order
            )

            # B5: Prevent deletion of items copied from child transactions
            # These items were already fulfilled in the original transaction
            # and their inventory was already deducted from that transaction
            if line_item.copied_from_transaction:
                raise ValidationError(
                    f"Cannot remove '{line_item.scanned_prod_name}' because it was already "
                    f"fulfilled in transaction {line_item.copied_from_transaction.tx_id}. "
                    f"This item was previously deducted from inventory."
                )

            line_total = line_item.line_total

            # B6: If this item was deducted from inventory (completed in THIS combined order),
            # return it to inventory before deleting
            if line_item.is_inventory_deducted:
                product = Product.objects.select_for_update().get(id=line_item.product.id)
                quantity_before = product.quantity
                product.quantity += line_item.quantity
                product.save()

                # Create inventory movement record for audit trail
                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.MovementType.RETURN,
                    product=product,
                    quantity_before=quantity_before,
                    quantity_after=product.quantity,
                    quantity_change=line_item.quantity,
                    reference=f"Removed from Combined Order {combined_order_id}",
                    performed_by='System'
                )

                logger.info(
                    f"Returned {line_item.quantity}x {product.prod_name} to inventory "
                    f"(was deducted for combined order {combined_order_id})"
                )

            line_item.delete()

            # Re-evaluate promotions after removal (may revert prices on remaining items)
            PromotionService.apply_promotions(
                CombinedOrderLineItem.objects.filter(combined_order=order)
            )

            # Recalculate amount_fulfilled from remaining items
            order.amount_fulfilled = CombinedOrderService.recalculate_amount_fulfilled(order)
            order.save()

            # Also update parent transaction's amount_fulfilled to stay in sync
            # NOTE: Must also update amount_paid to keep in sync for legacy remaining_amount calculation
            if order.parent_transaction:
                order.parent_transaction.amount_fulfilled = order.amount_fulfilled
                order.parent_transaction.amount_paid = order.amount_fulfilled
                order.parent_transaction.save(update_fields=['amount_fulfilled', 'amount_paid', 'updated_at'])

            logger.info(
                f"Line item {line_item_id} removed from combined order "
                f"{combined_order_id}"
            )
        except CombinedOrderLineItem.DoesNotExist:
            raise ValidationError(
                f"Line item {line_item_id} not found in order {combined_order_id}"
            )

