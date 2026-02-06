"""
Registration Kit Service

Handles registration kit issuance for transactions.
Validates PV requirements and deducts registration kit fee.
"""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from ..models import Transaction, Product, InventoryMovement, CombinedOrder, CombinedOrderLineItem
import logging

logger = logging.getLogger(__name__)

# Constants
REGISTRATION_KIT_PRICE = Decimal('2900.00')
MINIMUM_PV_REQUIRED = Decimal('20.00')


class RegistrationKitService:
    """Service for managing registration kit issuance"""

    @staticmethod
    def calculate_transaction_pv(transaction_obj):
        """
        Calculate total PV from line items.
        If no line items yet, returns 0.

        Args:
            transaction_obj: Transaction instance

        Returns:
            Decimal: Total PV from all line items
        """
        if not transaction_obj.line_items.exists():
            return Decimal('0.00')

        total = sum(
            item.line_pv for item in transaction_obj.line_items.all()
        )
        return Decimal(str(total))

    @staticmethod
    def can_issue_registration_kit(transaction_obj):
        """
        Check if registration kit can be issued for this transaction.

        Requirements:
        1. Transaction must be marked as registration
        2. Registration kit not already issued
        3. Transaction must have NOT_PROCESSED, PROCESSING, or PARTIALLY_FULFILLED status
        4. Remaining balance must be >= REGISTRATION_KIT_PRICE

        Args:
            transaction_obj: Transaction instance

        Returns:
            tuple: (can_issue: bool, reason: str or None)
        """
        if not transaction_obj.is_registration:
            return False, "Transaction is not marked as registration"

        if transaction_obj.registration_kit_issued:
            return False, "Registration kit already issued for this transaction"

        # Allow issuing kits for NOT_PROCESSED, PROCESSING, or PARTIALLY_FULFILLED transactions
        if transaction_obj.status not in [
            Transaction.OrderStatus.NOT_PROCESSED,
            Transaction.OrderStatus.PROCESSING,
            Transaction.OrderStatus.PARTIALLY_FULFILLED
        ]:
            return False, f"Cannot issue registration kit for {transaction_obj.get_status_display()} transaction"

        # Check remaining balance (not total amount) for PARTIALLY_FULFILLED transactions
        remaining_balance = transaction_obj.amount - transaction_obj.amount_fulfilled
        if remaining_balance < REGISTRATION_KIT_PRICE:
            return False, f"Insufficient remaining balance (KES {remaining_balance}) for registration kit price (KES {REGISTRATION_KIT_PRICE})"

        return True, None

    @staticmethod
    @db_transaction.atomic
    def issue_registration_kit(transaction_id, quantity=1, issued_by='system'):
        """
        Issue registration kit(s) for a transaction.

        Workflow:
        1. Validate transaction is eligible
        2. Deduct registration kit fee from available amount
        3. Mark registration kit as issued
        4. Return updated transaction

        Args:
            transaction_id: Transaction ID
            quantity: Number of registration kits (default 1)
            issued_by: User issuing the kit

        Returns:
            Transaction instance with updated values

        Raises:
            ValidationError: If transaction not eligible or validation fails
        """
        try:
            trans = Transaction.objects.select_for_update().get(id=transaction_id)
        except Transaction.DoesNotExist:
            raise ValidationError(f"Transaction {transaction_id} not found")

        # Validate eligibility
        can_issue, reason = RegistrationKitService.can_issue_registration_kit(trans)
        if not can_issue:
            raise ValidationError(reason)

        # Validate quantity
        if quantity < 1:
            raise ValidationError("Quantity must be at least 1")

        # Calculate total cost
        total_cost = REGISTRATION_KIT_PRICE * quantity

        # Check if enough funds available
        available_amount = trans.amount - trans.amount_fulfilled
        if available_amount < total_cost:
            raise ValidationError(
                f"Insufficient funds. Available: KES {available_amount}, "
                f"Required: KES {total_cost}"
            )

        # Update transaction
        trans.registration_kit_issued = True
        trans.registration_kit_quantity = quantity
        trans.registration_kit_amount_deducted = total_cost

        # CRITICAL: Actually deduct the registration kit cost from available amount
        # by adding it to amount_fulfilled (this reserves the amount)
        trans.amount_fulfilled += total_cost

        # Deduct physical registration kit from inventory
        try:
            reg_kit_product = Product.objects.select_for_update().get(prod_code='REG_KIT_001')

            # Check for insufficient stock before deducting
            if reg_kit_product.quantity < quantity:
                raise ValidationError(
                    f"Insufficient stock for Registration Kit ({reg_kit_product.prod_code}). "
                    f"Available: {reg_kit_product.quantity}, Requested: {quantity}."
                )

            qty_before = reg_kit_product.quantity
            reg_kit_product.quantity -= quantity
            reg_kit_product.save()

            InventoryMovement.objects.create(
                movement_type=InventoryMovement.MovementType.SALE.value,
                product=reg_kit_product,
                quantity_before=qty_before,
                quantity_after=reg_kit_product.quantity,
                quantity_change=-quantity,  # Negative for deduction
                reference=f'Registration Kit Issued for Transaction {trans.tx_id}',
                performed_by=issued_by
            )
        except Product.DoesNotExist:
            raise ValidationError("Registration kit product 'REG_KIT_001' not found in inventory. Cannot issue.")
        except Exception as e:
            # Log the full exception details to help diagnose the issue
            logger.exception(f"Unexpected error during registration kit inventory deduction. Exception type: {type(e)}, Exception repr: {repr(e)}")
            raise ValidationError(f"Failed to deduct registration kit from inventory: {e} (Type: {type(e).__name__}, Repr: {repr(e)})")

        # Change status to PROCESSING if NOT_PROCESSED
        if trans.status == Transaction.OrderStatus.NOT_PROCESSED:
            trans.status = Transaction.OrderStatus.PROCESSING

        trans.save()

        # CRITICAL: If this is a combined order parent transaction, also update the CombinedOrder
        # The CombinedOrder has its own amount_fulfilled field that must be kept in sync
        if hasattr(trans, 'combined_order_parent'):
            try:
                combined_order = trans.combined_order_parent
                combined_order.amount_fulfilled += total_cost

                # Also create a line item for the registration kit in the combined order
                CombinedOrderLineItem.objects.create(
                    combined_order=combined_order,
                    product=reg_kit_product,
                    scanned_prod_code=reg_kit_product.prod_code,
                    scanned_prod_name=reg_kit_product.prod_name,
                    scanned_sku=reg_kit_product.sku,
                    scanned_sku_name=reg_kit_product.sku_name or '',
                    scanned_price=REGISTRATION_KIT_PRICE,
                    scanned_pv=reg_kit_product.current_pv,
                    quantity=quantity,
                    line_total=total_cost,
                    line_cost=reg_kit_product.cost_price * quantity,
                    line_pv=reg_kit_product.current_pv * quantity,
                    is_inventory_deducted=True,  # Kit already deducted from inventory above
                    scanned_by=issued_by
                )

                combined_order.save()
                logger.info(
                    f"Updated CombinedOrder {combined_order.combined_order_id} "
                    f"amount_fulfilled to {combined_order.amount_fulfilled} after registration kit issuance"
                )
            except Exception as e:
                logger.error(f"Failed to update CombinedOrder for transaction {trans.tx_id}: {e}")
                raise ValidationError(f"Failed to update combined order: {e}")

        return trans

    @staticmethod
    def validate_pv_before_activation(transaction_obj):
        """
        Validate that transaction has minimum PV before allowing fulfillment activation.

        For registration transactions:
        1. Registration kit must be issued first
        2. PV validation is deferred to completion time

        This allows users to:
        - Activate issuance to scan products
        - Complete with partial fulfillment (even if PV < 20)
        - Re-activate to scan more products
        - Complete again when PV >= 20 for full fulfillment

        Args:
            transaction_obj: Transaction instance

        Raises:
            ValidationError: If registration kit not issued
        """
        if not transaction_obj.is_registration:
            # Not a registration transaction, no PV validation needed
            return

        # Check if registration kit issued
        # This is the only requirement for activation - PV check is deferred to completion
        if not transaction_obj.registration_kit_issued:
            raise ValidationError(
                "Registration kit must be issued before fulfilling order. "
                "Please issue registration kit first."
            )

        # No PV validation at activation time
        # This allows incremental product scanning and partial fulfillment
        # PV will be validated only at completion time (and only for full fulfillment)

    @staticmethod
    def validate_pv_before_completion(transaction_obj):
        """
        Validate PV before completing a registration transaction.

        Business Rules:
        - Registration kit must be issued first
        - If transaction will be FULLY FULFILLED (amount_fulfilled >= amount),
          then PV must be >= 20
        - Partial fulfillment is allowed even if PV < 20
          (allows incremental product scanning)

        Args:
            transaction_obj: Transaction instance

        Raises:
            ValidationError: If PV requirements not met
        """
        if not transaction_obj.is_registration:
            return

        if not transaction_obj.registration_kit_issued:
            raise ValidationError(
                "Registration kit must be issued before completing order"
            )

        current_pv = RegistrationKitService.calculate_transaction_pv(transaction_obj)

        # Only enforce PV requirement if transaction will be FULLY fulfilled
        # Allow partial fulfillment even with low PV (user can scan more products later)
        will_be_fully_fulfilled = transaction_obj.amount_fulfilled >= transaction_obj.amount

        if will_be_fully_fulfilled and current_pv < MINIMUM_PV_REQUIRED:
            raise ValidationError(
                f"Registration orders must have at least {MINIMUM_PV_REQUIRED} PV to be fully fulfilled. "
                f"Current PV: {current_pv}. Please scan more products with higher PV, or complete as partial fulfillment."
            )
