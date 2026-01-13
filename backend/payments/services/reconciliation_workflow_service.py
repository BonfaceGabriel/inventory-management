"""
Stock Reconciliation Workflow Service

Handles end-of-day stock reconciliation workflow:
1. Create draft reconciliation
2. Add/update adjustments
3. Confirm and apply to inventory
4. Generate report with adjustments
"""
from datetime import date
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from typing import Dict, List, Optional
import logging

from payments.models import (
    DailyStockReconciliation, StockAdjustmentItem, Product,
    InventoryMovement, User
)

logger = logging.getLogger(__name__)


class ReconciliationWorkflowService:
    """Service for managing end-of-day stock reconciliation workflow"""

    @staticmethod
    def get_or_create_reconciliation(reconciliation_date: date, created_by: User) -> DailyStockReconciliation:
        """
        Get existing reconciliation for date or create a new draft one.

        Args:
            reconciliation_date: Date for the reconciliation
            created_by: User creating the reconciliation

        Returns:
            DailyStockReconciliation instance

        Raises:
            ValidationError: If reconciliation for date already confirmed
        """
        # Check if reconciliation exists
        reconciliation = DailyStockReconciliation.objects.filter(
            reconciliation_date=reconciliation_date
        ).first()

        if reconciliation:
            # If already confirmed, raise error
            if reconciliation.is_confirmed():
                raise ValidationError(
                    f"Reconciliation for {reconciliation_date} has already been confirmed "
                    f"and cannot be modified."
                )
            logger.info(f"Using existing draft reconciliation for {reconciliation_date}")
            return reconciliation

        # Create new reconciliation
        reconciliation = DailyStockReconciliation.objects.create(
            reconciliation_date=reconciliation_date,
            status=DailyStockReconciliation.Status.DRAFT,
            created_by=created_by
        )
        logger.info(f"Created new reconciliation for {reconciliation_date}")

        # Initialize adjustments for all active products
        products = Product.objects.filter(is_active=True)
        for product in products:
            StockAdjustmentItem.objects.create(
                reconciliation=reconciliation,
                product=product,
                opening_stock=product.quantity,
                quantity_added=0,
                quantity_deducted=0,
                closing_stock=product.quantity
            )
        logger.info(f"Initialized {products.count()} adjustment items")

        return reconciliation

    @staticmethod
    def update_adjustment(
        reconciliation_id: str,
        product_id: int,
        quantity_added: int,
        quantity_deducted: int,
        notes: str = ''
    ) -> StockAdjustmentItem:
        """
        Update adjustment for a specific product in the reconciliation.

        Args:
            reconciliation_id: UUID of reconciliation
            product_id: ID of product to adjust
            quantity_added: Quantity to add
            quantity_deducted: Quantity to deduct
            notes: Notes about the adjustment

        Returns:
            Updated StockAdjustmentItem

        Raises:
            ValidationError: If reconciliation confirmed or not found
        """
        try:
            reconciliation = DailyStockReconciliation.objects.get(id=reconciliation_id)
        except DailyStockReconciliation.DoesNotExist:
            raise ValidationError(f"Reconciliation {reconciliation_id} not found")

        # Check if confirmed
        if reconciliation.is_confirmed():
            raise ValidationError(
                f"Reconciliation for {reconciliation.reconciliation_date} has already been "
                f"confirmed and cannot be modified."
            )

        # Get or create adjustment item
        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            raise ValidationError(f"Product {product_id} not found")

        adjustment, created = StockAdjustmentItem.objects.get_or_create(
            reconciliation=reconciliation,
            product=product,
            defaults={
                'opening_stock': product.quantity,
                'quantity_added': quantity_added,
                'quantity_deducted': quantity_deducted,
                'notes': notes
            }
        )

        if not created:
            # Update existing adjustment
            adjustment.quantity_added = quantity_added
            adjustment.quantity_deducted = quantity_deducted
            adjustment.notes = notes
            # closing_stock is calculated automatically in save()
            adjustment.save()

        logger.info(
            f"Updated adjustment for product {product.prod_name}: "
            f"Added={quantity_added}, Deducted={quantity_deducted}"
        )

        return adjustment

    @staticmethod
    @transaction.atomic
    def confirm_reconciliation(reconciliation_id: str, confirmed_by: User) -> DailyStockReconciliation:
        """
        Confirm the reconciliation and apply all adjustments to inventory.

        This:
        1. Validates all adjustments
        2. Updates product quantities
        3. Creates InventoryMovement records
        4. Marks reconciliation as confirmed
        5. Locks reconciliation (no further edits)

        Args:
            reconciliation_id: UUID of reconciliation
            confirmed_by: User confirming the reconciliation

        Returns:
            Confirmed DailyStockReconciliation

        Raises:
            ValidationError: If reconciliation not found, already confirmed, or validation fails
        """
        try:
            reconciliation = DailyStockReconciliation.objects.select_for_update().get(
                id=reconciliation_id
            )
        except DailyStockReconciliation.DoesNotExist:
            raise ValidationError(f"Reconciliation {reconciliation_id} not found")

        # Check if already confirmed
        if reconciliation.is_confirmed():
            raise ValidationError(
                f"Reconciliation for {reconciliation.reconciliation_date} has already been confirmed"
            )

        # Get all adjustments
        adjustments = reconciliation.adjustments.select_related('product').all()

        if not adjustments:
            raise ValidationError("Cannot confirm reconciliation with no adjustments")

        # Apply each adjustment to inventory
        for adjustment in adjustments:
            # Skip if no changes
            if adjustment.quantity_added == 0 and adjustment.quantity_deducted == 0:
                continue

            product = adjustment.product

            # Create inventory movements for added quantities
            if adjustment.quantity_added > 0:
                product.quantity += adjustment.quantity_added
                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.MovementType.MANUAL_ADJUSTMENT,
                    product=product,
                    quantity_before=adjustment.opening_stock,
                    quantity_after=product.quantity,
                    quantity_change=adjustment.quantity_added,
                    reference=f"EOD Reconciliation {reconciliation.reconciliation_date} - Added",
                    notes=adjustment.notes,
                    performed_by=confirmed_by.username
                )
                logger.info(f"Added {adjustment.quantity_added} to {product.prod_name}")

            # Create inventory movements for deducted quantities
            if adjustment.quantity_deducted > 0:
                product.quantity -= adjustment.quantity_deducted
                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.MovementType.MANUAL_ADJUSTMENT,
                    product=product,
                    quantity_before=product.quantity + adjustment.quantity_deducted,  # Before deduction
                    quantity_after=product.quantity,
                    quantity_change=-adjustment.quantity_deducted,  # Negative for deduction
                    reference=f"EOD Reconciliation {reconciliation.reconciliation_date} - Deducted",
                    notes=adjustment.notes,
                    performed_by=confirmed_by.username
                )
                logger.info(f"Deducted {adjustment.quantity_deducted} from {product.prod_name}")

            # Save updated product quantity
            product.save()

            # Verify final quantity matches closing stock
            if product.quantity != adjustment.closing_stock:
                raise ValidationError(
                    f"Stock mismatch for {product.prod_name}: "
                    f"Expected {adjustment.closing_stock}, got {product.quantity}"
                )

        # Mark reconciliation as confirmed
        reconciliation.status = DailyStockReconciliation.Status.CONFIRMED
        reconciliation.confirmed_by = confirmed_by
        reconciliation.confirmed_at = timezone.now()
        reconciliation.save()

        logger.info(
            f"Confirmed reconciliation for {reconciliation.reconciliation_date}: "
            f"{adjustments.count()} items processed"
        )

        return reconciliation

    @staticmethod
    def get_reconciliation_by_date(reconciliation_date: date) -> Optional[DailyStockReconciliation]:
        """
        Get reconciliation for a specific date.

        Args:
            reconciliation_date: Date to look up

        Returns:
            DailyStockReconciliation instance or None
        """
        return DailyStockReconciliation.objects.filter(
            reconciliation_date=reconciliation_date
        ).prefetch_related('adjustments__product').first()

    @staticmethod
    def can_create_reconciliation(reconciliation_date: date) -> tuple[bool, str]:
        """
        Check if a reconciliation can be created/edited for a date.

        Args:
            reconciliation_date: Date to check

        Returns:
            Tuple of (can_create, reason)
        """
        existing = DailyStockReconciliation.objects.filter(
            reconciliation_date=reconciliation_date
        ).first()

        if existing and existing.is_confirmed():
            return False, f"Reconciliation for {reconciliation_date} already confirmed"

        return True, "OK"
