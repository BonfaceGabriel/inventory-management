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
    CombinedOrderLineItem, Product, InventoryMovement
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

            # Only NOT_PROCESSED transactions can be combined
            if txn.status != Transaction.OrderStatus.NOT_PROCESSED:
                raise ValidationError(
                    f"Transaction {txn.tx_id} is {txn.get_status_display()} and cannot be combined. "
                    "Only NOT_PROCESSED transactions can be combined into a combined order."
                )

        # Calculate total amount
        total_amount = sum(txn.amount for txn in transactions)

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

        parent_transaction = Transaction.objects.create(
            tx_id=parent_tx_id,
            amount=total_amount,
            sender_name=customer_name or f"{len(transaction_ids)} combined payments",
            sender_phone=customer_phone,
            timestamp=now,
            gateway=first_gateway,
            confidence=1.0,
            status=Transaction.OrderStatus.PROCESSING,  # Will be updated as order progresses
            amount_fulfilled=Decimal('0.00'),
            unique_hash=unique_hash
        )

        # Create combined order
        combined_order = CombinedOrder.objects.create(
            combined_order_id=parent_tx_id,  # Use same ID as parent transaction
            parent_transaction=parent_transaction,
            total_amount=total_amount,
            amount_fulfilled=Decimal('0.00'),
            customer_name=customer_name,
            customer_phone=customer_phone,
            notes=notes,
            created_by=created_by
        )

        # Link transactions to combined order
        for idx, txn in enumerate(transactions):
            CombinedOrderTransaction.objects.create(
                combined_order=combined_order,
                transaction=txn,
                sequence=idx,
                added_by=created_by
            )

        # Immediately mark all child transactions as COMBINED_FULFILLED
        # They become read-only and link to the combined order
        for txn in transactions:
            txn.status = Transaction.OrderStatus.COMBINED_FULFILLED
            txn.save()

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

        # Calculate line total
        line_total = product.current_price * quantity

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
            scanned_price=product.current_price,
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

        # Reverse any issued line items
        reversed_count = 0
        for line_item in combined_order.line_items.all():
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

        # Update combined order status
        combined_order.status = CombinedOrder.Status.CANCELLED
        combined_order.notes += f"\n\n[CANCELLED {timezone.now()}]\nBy: {cancelled_by}\nReason: {reason or 'N/A'}\n{reversed_count} line items reversed."
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

        # Calculate line total
        unit_price = product.current_price
        line_total = unit_price * quantity

        # Check if product already exists in line items
        existing_item = CombinedOrderLineItem.objects.filter(
            combined_order=order,
            product=product
        ).first()

        if existing_item:
            # Update existing line item quantity
            old_line_total = existing_item.line_total
            new_quantity = existing_item.quantity + quantity
            new_line_total = unit_price * new_quantity

            # Check if adding this would exceed budget
            new_fulfilled = order.amount_fulfilled - old_line_total + new_line_total
            if new_fulfilled > order.total_amount:
                raise ValidationError(
                    f"Adding {quantity}x {product.prod_name} (KES {line_total}) "
                    f"would exceed budget. Remaining: KES {order.remaining_amount}"
                )

            existing_item.quantity = new_quantity
            existing_item.line_total = new_line_total
            existing_item.save()

            line_item = existing_item
            logger.info(
                f"Product {product.prod_code} quantity updated in combined order "
                f"{combined_order_id} (STAGED, qty={existing_item.quantity})"
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
                scanned_price=unit_price,
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

        # Update amount_fulfilled (remaining_amount is calculated automatically as a property)
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

        # Update inventory for each line item
        for item in line_items:
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
            ValidationError: If order not in progress or item not found
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
            line_total = line_item.line_total
            line_item.delete()

            # Recalculate amount_fulfilled (remaining_amount is calculated automatically)
            order.amount_fulfilled -= line_total
            order.save()

            logger.info(
                f"Line item {line_item_id} removed from combined order "
                f"{combined_order_id}"
            )
        except CombinedOrderLineItem.DoesNotExist:
            raise ValidationError(
                f"Line item {line_item_id} not found in order {combined_order_id}"
            )
