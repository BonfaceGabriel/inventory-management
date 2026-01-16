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
from payments.services.stock_take_service import StockTakeService


class FulfillmentService:
    """Service for handling transaction fulfillment workflow."""

    @staticmethod
    def activate_issuance(transaction_id: int, activated_by_user=None) -> Dict:
        """
        Activate issuance mode for a transaction.

        Business Rules:
        - Only one transaction can be in issuance at a time
        - Transaction must be NOT_PROCESSED or PROCESSING
        - Transaction cannot be locked (FULFILLED/CANCELLED)

        Args:
            transaction_id: ID of the transaction to activate
            activated_by_user: User who is activating the transaction

        Returns:
            Dict with success status and transaction data

        Raises:
            ValidationError: If business rules are violated
        """
        # Check if stock-taking session is active
        active_stock_take = StockTakeService.get_active_session()
        if active_stock_take:
            raise ValidationError({
                'stock_take': f'Stock-taking session {active_stock_take.session_id} is in progress. '
                             f'Complete or cancel the stock-take session before fulfilling orders.'
            })

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

                # Registration kit validation
                from payments.services.registration_kit_service import RegistrationKitService
                RegistrationKitService.validate_pv_before_activation(txn)

                # IMPORTANT: Save state BEFORE activation for cancel restoration
                # This allows us to restore the transaction to its previous state
                # if the issuance is cancelled
                txn.amount_fulfilled_before_activation = txn.amount_fulfilled
                txn.status_before_activation = txn.status

                # Activate issuance
                txn.is_in_issuance = True
                if activated_by_user:
                    txn.activated_by = activated_by_user
                    txn.activated_at = timezone.now()
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
    def scan_barcode(transaction_id: int, barcode_data: Dict, scanned_by_user=None) -> Dict:
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
                - prod_code: Product code (optional)
                - sku: Product SKU (optional)
                - barcode: Product barcode (optional)
                - quantity: Quantity scanned (default: 1)
                Note: At least one of prod_code, sku, or barcode must be provided
            scanned_by_user: User who performed the scan

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

                # Get product by SKU, prod_code, or barcode
                sku = barcode_data.get('sku')
                prod_code = barcode_data.get('prod_code')
                barcode = barcode_data.get('barcode')
                quantity = barcode_data.get('quantity', 1)

                if not sku and not prod_code and not barcode:
                    raise ValidationError({
                        'barcode': 'Either sku, prod_code, or barcode must be provided'
                    })

                # Find product
                if sku:
                    product = Product.objects.select_for_update().get(sku=sku, is_active=True)
                elif prod_code:
                    product = Product.objects.select_for_update().get(prod_code=prod_code, is_active=True)
                else:
                    product = Product.objects.select_for_update().get(barcode=barcode, is_active=True)

                # Validate quantity
                if quantity <= 0:
                    raise ValidationError({'quantity': 'Quantity must be greater than 0'})

                # Check if product already exists in PENDING line items (not yet deducted from inventory)
                # Important: Only match items with is_inventory_deducted=False to avoid
                # updating completed items from previous sessions
                existing_item = TransactionLineItem.objects.filter(
                    transaction=txn,
                    product=product,
                    is_inventory_deducted=False
                ).first()

                # Check stock availability FIRST (before creating/updating line items)
                if existing_item:
                    # Check if we can add more quantity
                    additional_quantity = quantity
                    if product.quantity < additional_quantity:
                        raise ValidationError({
                            'quantity': f'Insufficient stock. Available: {product.quantity}, Requested: {quantity}, Already in order: {existing_item.quantity}'
                        })
                else:
                    # Check stock availability for new item
                    if product.quantity < quantity:
                        raise ValidationError({
                            'quantity': f'Insufficient stock. Available: {product.quantity}, Requested: {quantity}'
                        })

                # Stock is available, now create/update line item
                if existing_item:
                    # Update existing line item quantity
                    new_quantity = existing_item.quantity + quantity
                    existing_item.quantity = new_quantity
                    existing_item.save()
                    line_item = existing_item
                else:
                    # Create new line item with scanned data
                    line_item = TransactionLineItem.objects.create(
                        transaction=txn,
                        product=product,
                        scanned_prod_code=product.prod_code,
                        scanned_prod_name=product.prod_name,
                        scanned_sku=product.sku,
                        scanned_sku_name=product.sku_name,
                        scanned_price=product.cost_price,  # Use cost_price (buying price)
                        scanned_pv=product.current_pv,
                        quantity=quantity,
                        scanned_by=scanned_by_user.username if scanned_by_user else 'System',
                        scanned_by_user=scanned_by_user
                    )

                # Calculate new totals from scanned line items
                all_line_items = TransactionLineItem.objects.filter(transaction=txn)
                scanned_items_total = sum(item.line_total for item in all_line_items)
                new_cost = sum(item.line_cost for item in all_line_items)
                new_pv = sum(item.line_pv for item in all_line_items)

                # For registration transactions, preserve the registration kit amount
                # Amount fulfilled = registration kit amount + scanned items total
                registration_kit_amount = txn.registration_kit_amount_deducted if txn.is_registration else Decimal('0.00')
                total_amount_fulfilled = registration_kit_amount + scanned_items_total

                # Validate against transaction amount
                if total_amount_fulfilled > txn.amount:
                    # CRITICAL: Delete the line item we just created/updated BEFORE raising error
                    # This ensures transaction totals are not updated if validation fails
                    if existing_item:
                        # Revert the quantity increase
                        existing_item.quantity -= quantity
                        if existing_item.quantity == 0:
                            existing_item.delete()
                        else:
                            existing_item.save()
                    else:
                        # Delete the newly created line item
                        line_item.delete()

                    raise ValidationError({
                        'amount': f'Total amount (kit: ${registration_kit_amount} + items: ${scanned_items_total} = ${total_amount_fulfilled}) '
                                 f'would exceed transaction amount (${txn.amount}). Cannot add this item.'
                    })

                # Update transaction totals (but don't update inventory yet)
                # IMPORTANT: This only executes if all validations passed
                txn.amount_fulfilled = total_amount_fulfilled
                txn.total_cost = new_cost
                txn.total_pv = new_pv

                # Don't update status during scanning - only update amounts
                # Status will be set when complete_issuance() is called
                # This prevents premature locking of the transaction

                txn.save()

                return {
                    'success': True,
                    'line_item_id': line_item.id,
                    'product_code': product.prod_code,
                    'product_name': product.prod_name,
                    'quantity': quantity,
                    'unit_price': str(product.cost_price),  # Use cost_price (buying price)
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
    def complete_issuance(transaction_id: int, completed_by_user=None) -> Dict:
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
            completed_by_user: User who completed the issuance

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

                # Registration kit PV validation before completion
                from payments.services.registration_kit_service import RegistrationKitService
                RegistrationKitService.validate_pv_before_completion(txn)

                # Update inventory ONLY for line items that haven't been deducted yet
                # This handles the case where we're completing a partial issuance on top of previous ones
                inventory_movements = []
                new_items = line_items.filter(is_inventory_deducted=False)

                for item in new_items:
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

                    # Mark line item as deducted
                    item.is_inventory_deducted = True
                    item.save(update_fields=['is_inventory_deducted'])

                    # Create inventory movement record
                    movement = InventoryMovement.objects.create(
                        movement_type=InventoryMovement.MovementType.SALE,
                        product=product,
                        quantity_before=quantity_before,
                        quantity_after=quantity_after,
                        quantity_change=-item.quantity,
                        reference=f'Transaction {txn.tx_id}',
                        performed_by=completed_by_user.username if completed_by_user else 'System',
                        performed_by_user=completed_by_user
                    )
                    inventory_movements.append({
                        'product_code': product.prod_code,
                        'product_name': product.prod_name,
                        'quantity_deducted': item.quantity,
                        'new_stock': quantity_after
                    })

                # Mark transaction as no longer in issuance
                txn.is_in_issuance = False
                if completed_by_user:
                    txn.completed_by = completed_by_user
                    txn.completed_at = timezone.now()

                # Clear the "before activation" tracking fields since we're completing successfully
                txn.amount_fulfilled_before_activation = None
                txn.status_before_activation = None

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

        Removes line items added during THIS issuance session and restores the
        transaction to its state BEFORE activation.
        Does NOT update inventory (since complete_issuance wasn't called).

        Key behavior:
        - Deletes all current line items (they haven't been deducted from inventory yet)
        - Restores amount_fulfilled to the value BEFORE this session (amount_fulfilled_before_activation)
        - Restores status to what it was BEFORE this session (status_before_activation)

        For Registration Transactions:
        - If kit was issued BEFORE this session, keeps the kit amount in amount_fulfilled
        - The amount_fulfilled_before_activation already includes the kit amount
        - Status stays PARTIALLY_FULFILLED if kit was issued (since kit is already fulfilled)

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

                # Get the state BEFORE this issuance session started
                # This was saved when activate_issuance was called
                # IMPORTANT: For registration transactions, this already includes the kit amount
                # (since kit is issued BEFORE activation, and activation saves the current state)
                previous_amount_fulfilled = txn.amount_fulfilled_before_activation
                previous_status = txn.status_before_activation

                # Handle case where tracking fields weren't set (backwards compatibility)
                if previous_amount_fulfilled is None:
                    # Calculate from already-completed line items (they have is_inventory_deducted=True)
                    completed_items_total = sum(
                        item.line_total for item in TransactionLineItem.objects.filter(
                            transaction=txn,
                            is_inventory_deducted=True
                        )
                    )
                    # For registration with kit, add the kit amount
                    if txn.is_registration and txn.registration_kit_issued:
                        previous_amount_fulfilled = txn.registration_kit_amount_deducted + completed_items_total
                    else:
                        previous_amount_fulfilled = completed_items_total

                if previous_status is None:
                    # Fallback: Determine status based on whether there's any completed fulfillment
                    if previous_amount_fulfilled > Decimal('0.00'):
                        previous_status = Transaction.OrderStatus.PARTIALLY_FULFILLED
                    elif txn.is_registration and txn.registration_kit_issued:
                        previous_status = Transaction.OrderStatus.PARTIALLY_FULFILLED
                    else:
                        previous_status = Transaction.OrderStatus.NOT_PROCESSED

                # Get line items that haven't had inventory deducted (from THIS session only)
                # Line items where is_inventory_deducted=True are from completed previous sessions
                # and should NOT be deleted
                pending_line_items = TransactionLineItem.objects.filter(
                    transaction=txn,
                    is_inventory_deducted=False
                )
                pending_count = pending_line_items.count()

                # Delete only the pending (current session) line items
                pending_line_items.delete()

                # Get completed line items (from previous sessions)
                completed_line_items = TransactionLineItem.objects.filter(
                    transaction=txn,
                    is_inventory_deducted=True
                )

                # Reset transaction state
                txn.is_in_issuance = False

                # Restore amount_fulfilled to what it was BEFORE this session
                # IMPORTANT: Also reset amount_paid to match, otherwise the Transaction.save()
                # sync logic will overwrite amount_fulfilled with the old amount_paid value
                txn.amount_fulfilled = previous_amount_fulfilled
                txn.amount_paid = previous_amount_fulfilled  # Keep in sync to avoid save() override

                # Recalculate total_cost and total_pv from remaining completed line items
                if completed_line_items.exists():
                    txn.total_cost = sum(item.line_cost for item in completed_line_items)
                    txn.total_pv = sum(item.line_pv for item in completed_line_items)
                else:
                    txn.total_cost = Decimal('0.00')
                    txn.total_pv = Decimal('0.00')

                # Restore the previous status
                txn.status = previous_status

                # Clear the "before activation" tracking fields
                txn.amount_fulfilled_before_activation = None
                txn.status_before_activation = None

                # Clear activation tracking
                txn.activated_by = None
                txn.activated_at = None

                if reason:
                    note_text = f"\n[Issuance Cancelled: {reason}]"
                    txn.notes = f"{txn.notes}{note_text}" if txn.notes else note_text.strip()

                # Skip validation since we're reverting status (special case for cancellation)
                txn.save(skip_validation=True)

                return {
                    'success': True,
                    'transaction_id': txn.id,
                    'tx_id': txn.tx_id,
                    'status': txn.status,
                    'amount_fulfilled': str(txn.amount_fulfilled),
                    'previous_amount_fulfilled': str(previous_amount_fulfilled),
                    'previous_status': previous_status,
                    'line_items_removed': pending_count,
                    'line_items_preserved': completed_line_items.count(),
                    'message': f'Issuance cancelled for transaction {txn.tx_id}. {pending_count} pending items removed, {completed_line_items.count()} completed items preserved. Restored to previous state (amount_fulfilled={previous_amount_fulfilled}, status={previous_status}).'
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

    @staticmethod
    def complete_registration_issuance(transaction_id: int, quantity: int = 1, completed_by_user=None) -> Dict:
        """
        Complete registration transaction by issuing Registration Kits.

        This is a special fulfillment workflow for registration transactions:
        - Does not require product scanning
        - Issues specified quantity of "Registration Kit" products
        - Updates inventory and completes transaction

        Business Rules:
        - Transaction must be marked as registration (is_registration=True)
        - Transaction does NOT need to be in issuance mode (direct issuance)
        - Registration Kit must exist (prod_code='REG_KIT_001')
        - Stock must be available (quantity >= requested quantity)

        Args:
            transaction_id: ID of the registration transaction
            quantity: Number of registration kits to issue (default: 1)
            completed_by_user: User who completed the registration

        Returns:
            Dict with completion status and kit issuance details

        Raises:
            ValidationError: If business rules are violated
        """
        try:
            with transaction.atomic():
                # Get transaction and verify it's a registration
                txn = Transaction.objects.select_for_update().get(id=transaction_id)

                if not txn.is_registration:
                    raise ValidationError({
                        'is_registration': 'Transaction must be marked as registration first'
                    })

                # Validate quantity
                if quantity < 1:
                    raise ValidationError({
                        'quantity': 'Quantity must be at least 1'
                    })

                # Get Registration Kit product
                try:
                    reg_kit = Product.objects.select_for_update().get(prod_code='REG_KIT_001')
                except Product.DoesNotExist:
                    raise ValidationError({
                        'product': 'Registration Kit not found (REG_KIT_001). Create it first.'
                    })

                # Check stock availability
                if reg_kit.quantity < quantity:
                    raise ValidationError({
                        'inventory': f'Insufficient registration kits. Available: {reg_kit.quantity}, Requested: {quantity}'
                    })

                # Activate issuance if not already active (to maintain consistency)
                if not txn.is_in_issuance:
                    txn.is_in_issuance = True
                    if completed_by_user:
                        txn.activated_by = completed_by_user
                        txn.activated_at = timezone.now()
                    if txn.status == Transaction.OrderStatus.NOT_PROCESSED:
                        txn.status = Transaction.OrderStatus.PROCESSING
                    txn.save()

                # Create line item for registration kits
                line_item = TransactionLineItem.objects.create(
                    transaction=txn,
                    product=reg_kit,
                    scanned_prod_code=reg_kit.prod_code,
                    scanned_prod_name=reg_kit.prod_name,
                    scanned_sku=reg_kit.sku,
                    scanned_sku_name=reg_kit.sku_name,
                    scanned_price=reg_kit.cost_price,  # Use cost_price (buying price)
                    scanned_pv=reg_kit.current_pv,
                    quantity=quantity,
                    scanned_by=completed_by_user.username if completed_by_user else 'System',
                    scanned_by_user=completed_by_user
                )

                # Update inventory
                quantity_before = reg_kit.quantity
                reg_kit.quantity -= quantity
                quantity_after = reg_kit.quantity
                reg_kit.save()

                # Create inventory movement record
                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.MovementType.SALE,
                    product=reg_kit,
                    quantity_before=quantity_before,
                    quantity_after=quantity_after,
                    quantity_change=-quantity,
                    reference=f'Registration {txn.tx_id}',
                    performed_by=completed_by_user.username if completed_by_user else 'System',
                    performed_by_user=completed_by_user
                )

                # Complete transaction
                txn.is_in_issuance = False
                txn.amount_fulfilled = line_item.line_total
                txn.total_cost = line_item.line_cost
                txn.total_pv = line_item.line_pv

                # Ensure status reflects fulfillment level (same logic as complete_issuance)
                if txn.amount_fulfilled >= txn.amount:
                    txn.status = Transaction.OrderStatus.FULFILLED
                elif txn.amount_fulfilled > 0:
                    txn.status = Transaction.OrderStatus.PARTIALLY_FULFILLED

                if completed_by_user:
                    txn.completed_by = completed_by_user
                    txn.completed_at = timezone.now()
                txn.save()

                return {
                    'success': True,
                    'transaction_id': txn.id,
                    'tx_id': txn.tx_id,
                    'status': txn.status,
                    'amount_fulfilled': str(txn.amount_fulfilled),
                    'kit_issued': {
                        'product_code': reg_kit.prod_code,
                        'product_name': reg_kit.prod_name,
                        'quantity': quantity,
                        'new_stock': quantity_after
                    },
                    'message': f'Registration {txn.tx_id} completed. {quantity}x Registration Kit issued.'
                }

        except Transaction.DoesNotExist:
            raise ValidationError({'transaction_id': 'Transaction not found'})
