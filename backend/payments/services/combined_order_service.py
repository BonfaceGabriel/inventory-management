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

        # Create combined order
        combined_order = CombinedOrder.objects.create(
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

        logger.info(
            f"Created combined order {combined_order.combined_order_id} with "
            f"{len(transaction_ids)} transactions totaling {total_amount} KES"
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

        logger.info(
            f"Cancelled combined order {combined_order_id}. "
            f"Reversed {reversed_count} line items."
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
                    'product_code': item.scanned_prod_code,
                    'product_name': item.scanned_prod_name,
                    'sku': item.scanned_sku,
                    'quantity': item.quantity,
                    'unit_price': item.scanned_price,
                    'line_total': item.line_total,
                    'scanned_at': item.scanned_at,
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
