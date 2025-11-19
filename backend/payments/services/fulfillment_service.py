"""
Transaction Fulfillment Service

Handles the scanner-based fulfillment workflow:
1. Activate issuance for a transaction
2. Scan products to add line items
3. Complete issuance to finalize and update inventory

Business Rules:
- Only ONE transaction can be in issuance at a time
- amount_fulfilled cannot exceed transaction.amount
- Stock must be available when scanning products
- Inventory is updated only on completion
"""

from decimal import Decimal
from django.db import transaction, models
from django.core.exceptions import ValidationError
from django.utils import timezone
from typing import Dict, Optional

from payments.models import (
    Transaction, Product, TransactionLineItem, InventoryMovement
)


class FulfillmentService:
    """Service for handling transaction fulfillment workflow."""

    @staticmethod
    def activate_issuance(transaction_id: int) -> Dict:
        """
        Activate issuance mode for a transaction.

        Business Rules:
        - Only one transaction can be in issuance at a time
        - Transaction must be NOT_PROCESSED or PROCESSING
        - Transaction cannot be locked (FULFILLED/CANCELLED)

        Args:
            transaction_id: ID of the transaction to activate

        Returns:
            Dict with success status and transaction data

        Raises:
            ValidationError: If business rules are violated
        """
        try:
            with transaction.atomic():
                # Check if another transaction is already in issuance
                existing_issuance = Transaction.objects.filter(
                    is_in_issuance=True
                ).exclude(id=transaction_id).first()

                if existing_issuance:
                    raise ValidationError({
                        'is_in_issuance': f'Transaction {existing_issuance.tx_id} is already in issuance. '
                                         f'Complete or cancel it first.'
                    })

                # Get the transaction
                txn = Transaction.objects.select_for_update().get(id=transaction_id)

                # Validate transaction state
                if txn.is_locked:
                    raise ValidationError({
                        'status': f'Transaction is {txn.status} and cannot be modified'
                    })

                if txn.status not in [
                    Transaction.OrderStatus.NOT_PROCESSED,
                    Transaction.OrderStatus.PROCESSING,
                    Transaction.OrderStatus.PARTIALLY_FULFILLED
                ]:
                    raise ValidationError({
                        'status': f'Transaction must be NOT_PROCESSED, PROCESSING, or PARTIALLY_FULFILLED. '
                                 f'Current status: {txn.status}'
                    })

                # Activate issuance
                txn.is_in_issuance = True
                if txn.status == Transaction.OrderStatus.NOT_PROCESSED:
                    txn.status = Transaction.OrderStatus.PROCESSING
                txn.save()

                return {
                    'success': True,
                    'transaction_id': txn.id,
                    'tx_id': txn.tx_id,
                    'amount': str(txn.amount),
                    'amount_fulfilled': str(txn.amount_fulfilled),
                    'remaining_amount': str(txn.remaining_amount),
                    'status': txn.status,
                    'message': f'Transaction {txn.tx_id} activated for issuance'
                }

        except Transaction.DoesNotExist:
            raise ValidationError({'transaction_id': 'Transaction not found'})

    @staticmethod
    def scan_barcode(transaction_id: int, barcode_data: Dict, scanned_by: str = 'System') -> Dict:
        """
        Scan a product barcode and add it to the transaction.

        Barcode data should contain product information from the barcode scan.
        Creates a TransactionLineItem and validates against transaction amount.

        Business Rules:
        - Transaction must be in issuance mode
        - Product must exist and be active
        - Stock must be available (quantity >= scan quantity)
        - Total line items cannot exceed transaction amount

        Args:
            transaction_id: ID of the transaction in issuance
            barcode_data: Dict containing scanned product info:
                - prod_code: Product code
                - sku: Product SKU
                - quantity: Quantity scanned (default: 1)
            scanned_by: User who performed the scan

        Returns:
            Dict with line item details and updated totals

        Raises:
            ValidationError: If business rules are violated
        """
        try:
            with transaction.atomic():
                # Get transaction and verify it's in issuance
                txn = Transaction.objects.select_for_update().get(id=transaction_id)

                if not txn.is_in_issuance:
                    raise ValidationError({
                        'is_in_issuance': 'Transaction is not in issuance mode. Activate it first.'
                    })

                # Get product by SKU or prod_code
                sku = barcode_data.get('sku')
                prod_code = barcode_data.get('prod_code')
                quantity = barcode_data.get('quantity', 1)

                if not sku and not prod_code:
                    raise ValidationError({
                        'barcode': 'Either sku or prod_code must be provided'
                    })

                # Find product
                if sku:
                    product = Product.objects.select_for_update().get(sku=sku, is_active=True)
                else:
                    product = Product.objects.select_for_update().get(prod_code=prod_code, is_active=True)

                # Validate quantity
                if quantity <= 0:
                    raise ValidationError({'quantity': 'Quantity must be greater than 0'})

                # Check stock availability
                if product.quantity < quantity:
                    raise ValidationError({
                        'quantity': f'Insufficient stock. Available: {product.quantity}, Requested: {quantity}'
                    })

                # Create line item with scanned data
                line_item = TransactionLineItem.objects.create(
                    transaction=txn,
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

                # Calculate new totals
                all_line_items = TransactionLineItem.objects.filter(transaction=txn)
                new_total = sum(item.line_total for item in all_line_items)
                new_cost = sum(item.line_cost for item in all_line_items)
                new_pv = sum(item.line_pv for item in all_line_items)

                # Validate against transaction amount
                if new_total > txn.amount:
                    # Delete the line item we just created
                    line_item.delete()
                    raise ValidationError({
                        'amount': f'Total line items (${new_total}) would exceed transaction amount (${txn.amount}). '
                                 f'Cannot add this item.'
                    })

                # Update transaction totals (but don't update inventory yet)
                txn.amount_fulfilled = new_total
                txn.total_cost = new_cost
                txn.total_pv = new_pv

                # Update status based on fulfillment
                if txn.amount_fulfilled >= txn.amount:
                    txn.status = Transaction.OrderStatus.FULFILLED
                elif txn.amount_fulfilled > 0:
                    txn.status = Transaction.OrderStatus.PARTIALLY_FULFILLED

                txn.save()

                return {
                    'success': True,
                    'line_item_id': line_item.id,
                    'product_code': product.prod_code,
                    'product_name': product.prod_name,
                    'quantity': quantity,
                    'unit_price': str(product.current_price),
                    'line_total': str(line_item.line_total),
                    'transaction_totals': {
                        'amount_fulfilled': str(txn.amount_fulfilled),
                        'total_cost': str(txn.total_cost),
                        'total_pv': str(txn.total_pv),
                        'remaining_amount': str(txn.remaining_amount),
                        'status': txn.status
                    },
                    'message': f'Added {quantity}x {product.prod_name} to transaction'
                }

        except Transaction.DoesNotExist:
            raise ValidationError({'transaction_id': 'Transaction not found'})
        except Product.DoesNotExist:
            raise ValidationError({
                'product': f'Product not found or inactive (SKU: {sku}, Code: {prod_code})'
            })

    @staticmethod
    def complete_issuance(transaction_id: int, performed_by: str = 'System') -> Dict:
        """
        Complete the issuance and update inventory.

        This finalizes the transaction and deducts scanned products from inventory.
        Creates InventoryMovement records for audit trail.

        Business Rules:
        - Transaction must be in issuance mode
        - At least one line item must exist
        - Stock is deducted from inventory
        - Transaction is marked as no longer in issuance

        Args:
            transaction_id: ID of the transaction to complete
            performed_by: User who completed the issuance

        Returns:
            Dict with completion status and inventory updates

        Raises:
            ValidationError: If business rules are violated
        """
        try:
            with transaction.atomic():
                # Get transaction
                txn = Transaction.objects.select_for_update().get(id=transaction_id)

                if not txn.is_in_issuance:
                    raise ValidationError({
                        'is_in_issuance': 'Transaction is not in issuance mode'
                    })

                # Get all line items
                line_items = TransactionLineItem.objects.filter(transaction=txn).select_related('product')

                if not line_items.exists():
                    raise ValidationError({
                        'line_items': 'No products have been scanned. Cannot complete empty issuance.'
                    })

                # Update inventory for each line item
                inventory_movements = []
                for item in line_items:
                    product = Product.objects.select_for_update().get(id=item.product.id)

                    # Check stock one more time (defensive programming)
                    if product.quantity < item.quantity:
                        raise ValidationError({
                            'inventory': f'Insufficient stock for {product.prod_name}. '
                                        f'Available: {product.quantity}, Required: {item.quantity}'
                        })

                    # Deduct from inventory
                    quantity_before = product.quantity
                    product.quantity -= item.quantity
                    quantity_after = product.quantity
                    product.save()

                    # Create inventory movement record
                    movement = InventoryMovement.objects.create(
                        movement_type=InventoryMovement.MovementType.SALE,
                        product=product,
                        quantity_before=quantity_before,
                        quantity_after=quantity_after,
                        quantity_change=-item.quantity,
                        reference=f'Transaction {txn.tx_id}',
                        performed_by=performed_by
                    )
                    inventory_movements.append({
                        'product_code': product.prod_code,
                        'product_name': product.prod_name,
                        'quantity_deducted': item.quantity,
                        'new_stock': quantity_after
                    })

                # Mark transaction as no longer in issuance
                txn.is_in_issuance = False

                # Ensure status reflects fulfillment level
                if txn.amount_fulfilled >= txn.amount:
                    txn.status = Transaction.OrderStatus.FULFILLED
                elif txn.amount_fulfilled > 0:
                    txn.status = Transaction.OrderStatus.PARTIALLY_FULFILLED

                txn.save()

                return {
                    'success': True,
                    'transaction_id': txn.id,
                    'tx_id': txn.tx_id,
                    'status': txn.status,
                    'amount_fulfilled': str(txn.amount_fulfilled),
                    'total_cost': str(txn.total_cost),
                    'total_pv': str(txn.total_pv),
                    'line_items_count': line_items.count(),
                    'inventory_updates': inventory_movements,
                    'message': f'Transaction {txn.tx_id} completed successfully. Inventory updated.'
                }

        except Transaction.DoesNotExist:
            raise ValidationError({'transaction_id': 'Transaction not found'})

    @staticmethod
    def cancel_issuance(transaction_id: int, reason: str = '') -> Dict:
        """
        Cancel the current issuance without updating inventory.

        Removes all line items and resets the transaction to its previous state.
        Does NOT update inventory (since complete_issuance wasn't called).

        Args:
            transaction_id: ID of the transaction to cancel
            reason: Optional reason for cancellation

        Returns:
            Dict with cancellation status

        Raises:
            ValidationError: If business rules are violated
        """
        try:
            with transaction.atomic():
                # Get transaction
                txn = Transaction.objects.select_for_update().get(id=transaction_id)

                if not txn.is_in_issuance:
                    raise ValidationError({
                        'is_in_issuance': 'Transaction is not in issuance mode'
                    })

                # Delete all line items (inventory not affected since we never completed)
                line_items_count = TransactionLineItem.objects.filter(transaction=txn).count()
                TransactionLineItem.objects.filter(transaction=txn).delete()

                # Reset transaction state
                txn.is_in_issuance = False
                txn.amount_fulfilled = Decimal('0.00')
                txn.total_cost = None
                txn.total_pv = None

                # Revert to NOT_PROCESSED when cancelling
                if txn.status in [
                    Transaction.OrderStatus.PROCESSING,
                    Transaction.OrderStatus.PARTIALLY_FULFILLED
                ]:
                    txn.status = Transaction.OrderStatus.NOT_PROCESSED

                if reason:
                    txn.notes = f"{txn.notes}\n[Issuance Cancelled: {reason}]".strip()

                # Skip validation since we're reverting status (special case for cancellation)
                txn.save(skip_validation=True)

                return {
                    'success': True,
                    'transaction_id': txn.id,
                    'tx_id': txn.tx_id,
                    'status': txn.status,
                    'line_items_removed': line_items_count,
                    'message': f'Issuance cancelled for transaction {txn.tx_id}. {line_items_count} items removed.'
                }

        except Transaction.DoesNotExist:
            raise ValidationError({'transaction_id': 'Transaction not found'})

    @staticmethod
    def get_current_issuance() -> Optional[Dict]:
        """
        Get the currently active issuance transaction, if any.

        Returns:
            Dict with transaction details if one is in issuance, None otherwise
        """
        try:
            txn = Transaction.objects.get(is_in_issuance=True)
            line_items = TransactionLineItem.objects.filter(transaction=txn).select_related('product')

            return {
                'transaction_id': txn.id,
                'tx_id': txn.tx_id,
                'amount': str(txn.amount),
                'amount_fulfilled': str(txn.amount_fulfilled),
                'remaining_amount': str(txn.remaining_amount),
                'total_cost': str(txn.total_cost) if txn.total_cost else '0.00',
                'total_pv': str(txn.total_pv) if txn.total_pv else '0.00',
                'status': txn.status,
                'line_items_count': line_items.count(),
                'line_items': [
                    {
                        'id': item.id,
                        'product_code': item.scanned_prod_code,
                        'product_name': item.scanned_prod_name,
                        'quantity': item.quantity,
                        'unit_price': str(item.scanned_price),
                        'line_total': str(item.line_total)
                    }
                    for item in line_items
                ]
            }
        except Transaction.DoesNotExist:
            return None
