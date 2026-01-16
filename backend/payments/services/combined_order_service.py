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

logger = logging.getLogger(__name__)


class CombinedOrderService:
    """Service for managing combined orders (multiple transactions combined into one fulfillment)."""

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

        # Validate all transactions are eligible
        for txn in transactions:
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
                CombinedOrderLineItem.objects.create(
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
        parent_transaction.amount = combined_order.total_amount
        parent_transaction.amount_fulfilled = combined_order.amount_fulfilled
        parent_transaction.save(update_fields=['amount', 'amount_fulfilled', 'updated_at'])

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

        # Update combined order status
        combined_order.status = CombinedOrder.Status.CANCELLED
        combined_order.notes += f"\n\n[CANCELLED {timezone.now()}]\nBy: {cancelled_by}\nReason: {reason or 'N/A'}\n{reversed_count} line items reversed."
        combined_order.amount_fulfilled_before_activation = None
        combined_order.status_before_activation = None
        combined_order.save()

        # Update parent transaction status
        if combined_order.parent_transaction:
            parent = combined_order.parent_transaction
            parent.status = Transaction.OrderStatus.CANCELLED
            parent.save()

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
        try:
            combined_order = CombinedOrder.objects.select_for_update().get(
                combined_order_id=combined_order_id
            )
        except CombinedOrder.DoesNotExist:
            raise ValidationError(f"Combined order {combined_order_id} not found")

        # Must be IN_PROGRESS to cancel issuance
        if combined_order.status != CombinedOrder.Status.IN_PROGRESS:
            raise ValidationError(
                f"Combined order {combined_order_id} is not in progress. "
                f"Current status: {combined_order.get_status_display()}"
            )

        # Get the state BEFORE this issuance session started
        previous_amount_fulfilled = combined_order.amount_fulfilled_before_activation
        previous_status = combined_order.status_before_activation

        # Handle case where tracking fields weren't set (backwards compatibility)
        if previous_amount_fulfilled is None:
            previous_amount_fulfilled = combined_order.base_amount_fulfilled
        if previous_status is None:
            previous_status = CombinedOrder.Status.PENDING
            if previous_amount_fulfilled > 0:
                previous_status = CombinedOrder.Status.PARTIALLY_FULFILLED

        # Delete ONLY pending line items (not yet deducted from inventory)
        # Keep the completed items (from previous sessions or copied from child transactions)
        pending_items = combined_order.line_items.filter(is_inventory_deducted=False)
        pending_count = pending_items.count()
        pending_items.delete()

        # Restore state
        combined_order.amount_fulfilled = previous_amount_fulfilled
        combined_order.status = previous_status
        combined_order.amount_fulfilled_before_activation = None
        combined_order.status_before_activation = None

        if reason:
            combined_order.notes += f"\n\n[ISSUANCE CANCELLED {timezone.now()}]\nBy: {cancelled_by}\nReason: {reason or 'N/A'}\n{pending_count} pending items removed."

        combined_order.save()

        # Also update parent transaction
        if combined_order.parent_transaction:
            parent = combined_order.parent_transaction
            parent.amount_fulfilled = combined_order.amount_fulfilled
            if combined_order.status == CombinedOrder.Status.PARTIALLY_FULFILLED:
                parent.status = Transaction.OrderStatus.PARTIALLY_FULFILLED
            else:
                parent.status = Transaction.OrderStatus.PROCESSING
            parent.save()

        logger.info(
            f"Cancelled issuance session for combined order {combined_order_id}. "
            f"Removed {pending_count} pending items. Restored to {previous_status}."
        )

        return {
            'success': True,
            'combined_order_id': combined_order_id,
            'pending_items_removed': pending_count,
            'status': combined_order.status,
            'amount_fulfilled': float(combined_order.amount_fulfilled),
            'previous_status': previous_status,
            'message': f'Issuance cancelled. {pending_count} pending items removed. Restored to {previous_status}.'
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

        # Verify order can be activated (PENDING or PARTIALLY_FULFILLED)
        if order.status not in [CombinedOrder.Status.PENDING, CombinedOrder.Status.PARTIALLY_FULFILLED]:
            raise ValidationError(
                f"Cannot activate {order.get_status_display()} order. "
                f"Order must be PENDING or PARTIALLY_FULFILLED."
            )

        # Save state BEFORE activation for cancel restoration
        order.amount_fulfilled_before_activation = order.amount_fulfilled
        order.status_before_activation = order.status

        # Set to IN_PROGRESS
        order.status = CombinedOrder.Status.IN_PROGRESS
        order.save()

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

        # Verify order is IN_PROGRESS
        if order.status != CombinedOrder.Status.IN_PROGRESS:
            raise ValidationError(
                f"Cannot scan to {order.get_status_display()} order. "
                f"Order must be IN_PROGRESS."
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

        # Update amount_fulfilled
        # We calculate from line items directly since line items now include copied items
        # from partially fulfilled transactions (which have is_inventory_deducted=True)
        # So the total is simply the sum of all line item totals
        new_fulfilled = sum(item.line_total for item in order.line_items.all())
        order.amount_fulfilled = new_fulfilled
        order.save()

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

        # Verify order is IN_PROGRESS
        if order.status != CombinedOrder.Status.IN_PROGRESS:
            raise ValidationError(
                f"Cannot complete {order.get_status_display()} order. "
                f"Order must be IN_PROGRESS."
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
        if order.parent_transaction:
            parent = order.parent_transaction
            parent.status = parent_status
            parent.amount_fulfilled = order.amount_fulfilled
            parent.save(update_fields=['status', 'amount_fulfilled', 'updated_at'])

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

        # Verify order is IN_PROGRESS
        if order.status != CombinedOrder.Status.IN_PROGRESS:
            raise ValidationError(
                f"Cannot remove items from {order.get_status_display()} order. "
                f"Order must be IN_PROGRESS."
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

            # Recalculate amount_fulfilled from remaining items
            order.amount_fulfilled = sum(
                item.line_total for item in order.line_items.all()
            )
            order.save()

            # Also update parent transaction's amount_fulfilled to stay in sync
            if order.parent_transaction:
                order.parent_transaction.amount_fulfilled = order.amount_fulfilled
                order.parent_transaction.save(update_fields=['amount_fulfilled', 'updated_at'])

            logger.info(
                f"Line item {line_item_id} removed from combined order "
                f"{combined_order_id}"
            )
        except CombinedOrderLineItem.DoesNotExist:
            raise ValidationError(
                f"Line item {line_item_id} not found in order {combined_order_id}"
            )

