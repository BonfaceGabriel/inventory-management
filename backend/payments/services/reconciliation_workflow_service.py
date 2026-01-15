"""
Stock Reconciliation Workflow Service

Handles end-of-day stock reconciliation workflow:
1. Create draft reconciliation
2. Add/update adjustments (Added/Deducted only - Replenished is auto-calculated)
3. Confirm and apply to inventory
4. Generate report with adjustments

Flow:
- Opening Stock: Previous day's closing stock (product.quantity at reconciliation creation)
- Replenished: AUTO-CALCULATED from completed stock take sessions for the day (read-only)
- Added: Manual additions (corrections, found items)
- Deducted: Manual deductions (damaged, stolen, shrinkage)
- Closing Stock: Current product.quantity (auto-refreshed)
- Totals: Opening + Replenished + Added - Deducted
- Sales: Totals - Closing Stock
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
from datetime import timedelta

logger = logging.getLogger(__name__)


class ReconciliationWorkflowService:

    @staticmethod
    def _calculate_opening_stock(product: Product, reconciliation_date: date) -> int:
        """
        Calculate the opening stock for a product on a given date.

        Opening stock represents the stock at the BEGINNING of the day (before any
        stock takes or sales). This is determined by:
        1. If previous day's reconciliation exists and is confirmed, use its closing stock
        2. Otherwise, calculate by reversing today's inventory movements from current quantity

        Args:
            product: Product to calculate opening stock for
            reconciliation_date: Date of the reconciliation

        Returns:
            Opening stock quantity for beginning of day
        """
        from datetime import datetime, time
        from django.utils import timezone
        from django.db.models import Sum

        # Try to get yesterday's confirmed reconciliation
        yesterday = reconciliation_date - timedelta(days=1)
        yesterday_reconciliation = DailyStockReconciliation.objects.filter(
            reconciliation_date=yesterday,
            status=DailyStockReconciliation.Status.CONFIRMED
        ).first()

        if yesterday_reconciliation:
            # Get yesterday's closing stock for this product
            yesterday_adjustment = StockAdjustmentItem.objects.filter(
                reconciliation=yesterday_reconciliation,
                product=product
            ).first()
            if yesterday_adjustment:
                logger.debug(f"Using yesterday's closing stock for {product.prod_name}: {yesterday_adjustment.closing_stock}")
                return yesterday_adjustment.closing_stock

        # No confirmed reconciliation for yesterday, calculate from inventory movements
        # Start with current quantity and reverse all movements from today
        start_of_day = timezone.make_aware(datetime.combine(reconciliation_date, time.min))
        end_of_day = timezone.make_aware(datetime.combine(reconciliation_date, time.max))

        # Sum all inventory changes for today
        movements_today = InventoryMovement.objects.filter(
            product=product,
            created_at__gte=start_of_day,
            created_at__lte=end_of_day
        ).aggregate(total_change=Sum('quantity_change'))

        total_change = movements_today['total_change'] or 0

        # Opening stock = current quantity - today's changes
        opening_stock = product.quantity - total_change

        logger.debug(f"Calculated opening stock for {product.prod_name}: current={product.quantity}, today_changes={total_change}, opening={opening_stock}")
        return opening_stock
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
            # Calculate replenished from completed stock take sessions for this date
            quantity_replenished = StockAdjustmentItem.calculate_replenished_from_stock_takes(
                product.id,
                reconciliation_date
            )

            # Calculate opening stock (beginning of day, before any movements)
            # Uses yesterday's confirmed reconciliation if available, otherwise calculates from movements
            opening_stock = ReconciliationWorkflowService._calculate_opening_stock(
                product,
                reconciliation_date
            )

            StockAdjustmentItem.objects.create(
                reconciliation=reconciliation,
                product=product,
                opening_stock=opening_stock,  # Beginning of day (before replenishment/sales)
                quantity_replenished=quantity_replenished,  # Auto-populated from stock takes
                quantity_added=0,
                quantity_deducted=0,
                closing_stock=product.quantity  # Current stock (end of day)
            )
        logger.info(f"Initialized {products.count()} adjustment items with auto-calculated replenished")

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

        NOTE: quantity_replenished is READ-ONLY and auto-calculated from stock take sessions.
        Only quantity_added and quantity_deducted can be manually updated.

        Flow:
        - opening_stock: Set from product.quantity at creation (yesterday's closing)
        - quantity_replenished: AUTO-CALCULATED from completed stock take sessions (read-only)
        - System sales: Automatically deduct from product.quantity throughout the day
        - quantity_added/deducted: Manual adjustments during reconciliation
        - closing_stock: Auto-populated from current product.quantity
        - totals: opening + replenished + added - deducted (what should be there)
        - sales: totals - closing_stock (what was sold)

        Args:
            reconciliation_id: UUID of reconciliation
            product_id: ID of product to adjust
            quantity_added: Quantity added (manual corrections, found items)
            quantity_deducted: Quantity deducted (damaged, stolen, shrinkage)
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

        # Calculate replenished from stock takes (read-only, auto-calculated)
        quantity_replenished = StockAdjustmentItem.calculate_replenished_from_stock_takes(
            product_id,
            reconciliation.reconciliation_date
        )

        # Calculate opening stock (beginning of day, before any movements)
        opening_stock = ReconciliationWorkflowService._calculate_opening_stock(
            product,
            reconciliation.reconciliation_date
        )

        adjustment, created = StockAdjustmentItem.objects.get_or_create(
            reconciliation=reconciliation,
            product=product,
            defaults={
                'opening_stock': opening_stock,  # Beginning of day (before replenishment/sales)
                'quantity_replenished': quantity_replenished,  # Auto-calculated
                'quantity_added': quantity_added,
                'quantity_deducted': quantity_deducted,
                'closing_stock': product.quantity,  # Current stock (end of day)
                'notes': notes
            }
        )

        if not created:
            # Update existing adjustment - only manual fields
            # Refresh replenished from stock takes (in case new sessions completed)
            adjustment.quantity_replenished = quantity_replenished
            adjustment.quantity_added = quantity_added
            adjustment.quantity_deducted = quantity_deducted
            adjustment.closing_stock = product.quantity  # Always refresh from current stock
            adjustment.notes = notes
            adjustment.save()

        logger.info(
            f"Updated adjustment for product {product.prod_name}: "
            f"Replenished={quantity_replenished} (auto), Added={quantity_added}, Deducted={quantity_deducted}"
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
                    movement_type=InventoryMovement.MovementType.ADJUSTMENT,
                    product=product,
                    quantity_before=adjustment.opening_stock,
                    quantity_after=product.quantity,
                    quantity_change=adjustment.quantity_added,
                    reference=f"EOD Reconciliation {reconciliation.reconciliation_date} - Added",
                    performed_by=confirmed_by.username
                )
                logger.info(f"Added {adjustment.quantity_added} to {product.prod_name}")

            # Create inventory movements for deducted quantities
            if adjustment.quantity_deducted > 0:
                product.quantity -= adjustment.quantity_deducted
                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.MovementType.ADJUSTMENT,
                    product=product,
                    quantity_before=product.quantity + adjustment.quantity_deducted,  # Before deduction
                    quantity_after=product.quantity,
                    quantity_change=-adjustment.quantity_deducted,  # Negative for deduction
                    reference=f"EOD Reconciliation {reconciliation.reconciliation_date} - Deducted",
                    performed_by=confirmed_by.username
                )
                logger.info(f"Deducted {adjustment.quantity_deducted} from {product.prod_name}")

            # Save updated product quantity
            product.save()

            # Update the closing stock to reflect the final quantity after adjustments
            adjustment.closing_stock = product.quantity
            adjustment.save()

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

    @staticmethod
    def set_opening_stock_baseline(
        reconciliation_id: str,
        product_id: int,
        baseline_value: int
    ) -> StockAdjustmentItem:
        """
        Set a manual baseline for opening stock.

        Use this for initial setup when previous reconciliation data is invalid
        (e.g., placeholder data). The baseline overrides the calculated opening stock.

        Args:
            reconciliation_id: UUID of reconciliation
            product_id: ID of product
            baseline_value: The actual opening stock value to use

        Returns:
            Updated StockAdjustmentItem

        Raises:
            ValidationError: If reconciliation confirmed or not found
        """
        try:
            reconciliation = DailyStockReconciliation.objects.get(id=reconciliation_id)
        except DailyStockReconciliation.DoesNotExist:
            raise ValidationError(f"Reconciliation {reconciliation_id} not found")

        if reconciliation.is_confirmed():
            raise ValidationError(
                f"Reconciliation for {reconciliation.reconciliation_date} has already been "
                f"confirmed and cannot be modified."
            )

        try:
            adjustment = StockAdjustmentItem.objects.get(
                reconciliation=reconciliation,
                product_id=product_id
            )
        except StockAdjustmentItem.DoesNotExist:
            raise ValidationError(f"No adjustment found for product {product_id} in this reconciliation")

        adjustment.opening_stock_baseline = baseline_value
        adjustment.save()

        logger.info(
            f"Set baseline opening stock for {adjustment.product.prod_name}: {baseline_value}"
        )

        return adjustment

    @staticmethod
    @transaction.atomic
    def set_bulk_opening_stock_baseline(
        reconciliation_id: str,
        use_current_inventory: bool = False,
        baselines: list = None
    ) -> int:
        """
        Set baseline opening stock for multiple products at once.

        Use this for initial system setup to set real opening stock values,
        ignoring previous placeholder reconciliation data.

        Args:
            reconciliation_id: UUID of reconciliation
            use_current_inventory: If True, sets baseline to current product.quantity for ALL products
            baselines: List of {'product_id': int, 'opening_stock_baseline': int} dicts

        Returns:
            Number of adjustments updated

        Raises:
            ValidationError: If reconciliation confirmed or not found
        """
        try:
            reconciliation = DailyStockReconciliation.objects.get(id=reconciliation_id)
        except DailyStockReconciliation.DoesNotExist:
            raise ValidationError(f"Reconciliation {reconciliation_id} not found")

        if reconciliation.is_confirmed():
            raise ValidationError(
                f"Reconciliation for {reconciliation.reconciliation_date} has already been "
                f"confirmed and cannot be modified."
            )

        count = 0

        if use_current_inventory:
            # Set baseline to current inventory for ALL products
            adjustments = reconciliation.adjustments.select_related('product').all()
            for adjustment in adjustments:
                # Get current inventory minus today's replenished to get "true" opening
                # (because replenished has already been added to product.quantity)
                quantity_replenished = StockAdjustmentItem.calculate_replenished_from_stock_takes(
                    adjustment.product_id,
                    reconciliation.reconciliation_date
                )
                baseline = adjustment.product.quantity - quantity_replenished
                adjustment.opening_stock_baseline = baseline
                adjustment.save()
                count += 1
            logger.info(f"Set baseline from current inventory for {count} products")
        elif baselines:
            # Set specific baselines
            for item in baselines:
                try:
                    adjustment = StockAdjustmentItem.objects.get(
                        reconciliation=reconciliation,
                        product_id=item['product_id']
                    )
                    adjustment.opening_stock_baseline = item['opening_stock_baseline']
                    adjustment.save()
                    count += 1
                except StockAdjustmentItem.DoesNotExist:
                    logger.warning(f"No adjustment found for product {item['product_id']}")
            logger.info(f"Set baseline for {count} products from provided list")

        return count

    @staticmethod
    def clear_opening_stock_baseline(
        reconciliation_id: str,
        product_id: int = None
    ) -> int:
        """
        Clear baseline opening stock, reverting to calculated value.

        Args:
            reconciliation_id: UUID of reconciliation
            product_id: Optional specific product ID, or None for all products

        Returns:
            Number of adjustments cleared

        Raises:
            ValidationError: If reconciliation confirmed or not found
        """
        try:
            reconciliation = DailyStockReconciliation.objects.get(id=reconciliation_id)
        except DailyStockReconciliation.DoesNotExist:
            raise ValidationError(f"Reconciliation {reconciliation_id} not found")

        if reconciliation.is_confirmed():
            raise ValidationError(
                f"Reconciliation for {reconciliation.reconciliation_date} has already been "
                f"confirmed and cannot be modified."
            )

        if product_id:
            count = StockAdjustmentItem.objects.filter(
                reconciliation=reconciliation,
                product_id=product_id
            ).update(opening_stock_baseline=None)
        else:
            count = reconciliation.adjustments.update(opening_stock_baseline=None)

        logger.info(f"Cleared baseline for {count} products")
        return count
