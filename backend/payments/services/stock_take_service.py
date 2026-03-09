"""
Stock Take Service
Handles stock taking session management and inventory updates.
"""
from datetime import datetime
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from ..models import (
    StockTakeSession, StockTakeItem, Product, InventoryMovement
)


class StockTakeService:
    """Service for managing stock take sessions"""

    @staticmethod
    def get_active_session():
        """
        Get currently active stock take session (if any).

        Returns:
            StockTakeSession instance if one is active (DRAFT status), None otherwise
        """
        return StockTakeSession.objects.filter(
            status=StockTakeSession.Status.DRAFT
        ).first()

    @staticmethod
    def has_active_session():
        """
        Check if there's currently an active stock take session.

        Returns:
            Boolean indicating if a session is active
        """
        return StockTakeSession.objects.filter(
            status=StockTakeSession.Status.DRAFT
        ).exists()

    @staticmethod
    def create_session(created_by, notes=''):
        """
        Create a new stock take session.

        Args:
            created_by: User creating the session
            notes: Optional session notes

        Returns:
            StockTakeSession instance
        """
        # Generate session ID: STK-YYYYMMDD-HHMMSS
        now = timezone.now()
        session_id = now.strftime('STK-%Y%m%d-%H%M%S')

        session = StockTakeSession.objects.create(
            session_id=session_id,
            status=StockTakeSession.Status.DRAFT,
            created_by=created_by,
            notes=notes
        )

        return session

    @staticmethod
    def scan_product(session_id, product_id, quantity, scanned_by):
        """
        Scan a product into the stock take session.
        Does NOT update product inventory yet - staged only.

        Args:
            session_id: Stock take session ID
            product_id: Product ID to scan
            quantity: Quantity scanned (positive integer)
            scanned_by: User scanning the product

        Returns:
            StockTakeItem instance

        Raises:
            ValidationError: If session not found, completed, or product not found
        """
        try:
            session = StockTakeSession.objects.get(session_id=session_id)
        except StockTakeSession.DoesNotExist:
            raise ValidationError(f"Stock take session {session_id} not found")

        # Verify session is in DRAFT status
        if session.status != StockTakeSession.Status.DRAFT:
            raise ValidationError(
                f"Cannot scan to {session.get_status_display()} session. "
                f"Session must be in DRAFT status."
            )

        # Get product
        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            raise ValidationError(f"Product {product_id} not found")

        # Validate quantity
        if quantity <= 0:
            raise ValidationError("Quantity must be positive")

        # Check if product already scanned in this session
        existing_item = StockTakeItem.objects.filter(
            session=session,
            product=product
        ).first()

        if existing_item:
            # Update existing item quantity
            new_quantity_scanned = existing_item.quantity_scanned + quantity
            new_quantity_after = existing_item.quantity_before + new_quantity_scanned

            existing_item.quantity_scanned = new_quantity_scanned
            existing_item.quantity_after = new_quantity_after
            existing_item.save()

            return existing_item
        else:
            # Record stock before/after (but don't update product yet)
            quantity_before = product.quantity
            quantity_after = quantity_before + quantity

            # Create stock take item
            item = StockTakeItem.objects.create(
                session=session,
                product=product,
                quantity_before=quantity_before,
                quantity_scanned=quantity,
                quantity_after=quantity_after,
                scanned_by=scanned_by
            )

            return item

    @staticmethod
    @transaction.atomic
    def complete_session(session_id, completed_by):
        """
        Complete the stock take session and update inventory.
        Creates InventoryMovement records for audit trail.

        Args:
            session_id: Stock take session ID
            completed_by: User completing the session

        Returns:
            StockTakeSession instance

        Raises:
            ValidationError: If session not found or already completed
        """
        try:
            session = StockTakeSession.objects.select_for_update().get(
                session_id=session_id
            )
        except StockTakeSession.DoesNotExist:
            raise ValidationError(f"Stock take session {session_id} not found")

        # Verify session is in DRAFT status
        if session.status != StockTakeSession.Status.DRAFT:
            raise ValidationError(
                f"Cannot complete {session.get_status_display()} session. "
                f"Session must be in DRAFT status."
            )

        # Get all items in session
        items = session.items.select_related('product').all()

        if not items and session.kit_quantity == 0:
            raise ValidationError("Cannot complete session with no items")

        # Update inventory for each scanned item
        for item in items:
            product = item.product

            # Update product quantity
            product.quantity = item.quantity_after
            product.save()

            # Create inventory movement for audit trail
            InventoryMovement.objects.create(
                movement_type=InventoryMovement.MovementType.STOCK_TAKE,
                product=product,
                quantity_before=item.quantity_before,
                quantity_after=item.quantity_after,
                quantity_change=item.quantity_scanned,
                reference=f"Stock Take {session_id}",
                performed_by=completed_by
            )

        # Process registration kits if any were counted
        if session.kit_quantity > 0:
            try:
                kit_product = Product.objects.select_for_update().get(prod_code='REG_KIT_001')
                qty_before = kit_product.quantity
                qty_after = qty_before + session.kit_quantity

                kit_product.quantity = qty_after
                kit_product.save()

                # Create StockTakeItem for audit trail
                StockTakeItem.objects.create(
                    session=session,
                    product=kit_product,
                    quantity_before=qty_before,
                    quantity_scanned=session.kit_quantity,
                    quantity_after=qty_after,
                    scanned_by=completed_by
                )

                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.MovementType.STOCK_TAKE,
                    product=kit_product,
                    quantity_before=qty_before,
                    quantity_after=qty_after,
                    quantity_change=session.kit_quantity,
                    reference=f"Stock Take {session_id} (Registration Kits)",
                    performed_by=completed_by
                )
            except Product.DoesNotExist:
                raise ValidationError(
                    "Registration kit product 'REG_KIT_001' not found. Cannot process kit quantity."
                )

        # Mark session as completed
        session.status = StockTakeSession.Status.COMPLETED
        session.completed_at = timezone.now()
        session.completed_by = completed_by
        session.save()

        return session

    @staticmethod
    def get_session_details(session_id):
        """
        Get stock take session with all items.

        Args:
            session_id: Stock take session ID

        Returns:
            StockTakeSession instance with prefetched items

        Raises:
            ValidationError: If session not found
        """
        try:
            session = StockTakeSession.objects.prefetch_related(
                'items__product'
            ).get(session_id=session_id)
        except StockTakeSession.DoesNotExist:
            raise ValidationError(f"Stock take session {session_id} not found")

        return session

    @staticmethod
    def remove_item(session_id, item_id):
        """
        Remove an item from a draft stock take session.

        Args:
            session_id: Stock take session ID
            item_id: Stock take item ID to remove

        Raises:
            ValidationError: If session not in draft or item not found
        """
        try:
            session = StockTakeSession.objects.get(session_id=session_id)
        except StockTakeSession.DoesNotExist:
            raise ValidationError(f"Stock take session {session_id} not found")

        # Verify session is in DRAFT status
        if session.status != StockTakeSession.Status.DRAFT:
            raise ValidationError(
                f"Cannot remove items from {session.get_status_display()} session. "
                f"Session must be in DRAFT status."
            )

        try:
            item = StockTakeItem.objects.get(id=item_id, session=session)
            item.delete()
        except StockTakeItem.DoesNotExist:
            raise ValidationError(
                f"Item {item_id} not found in session {session_id}"
            )

    @staticmethod
    def update_item_quantity(session_id, item_id, new_quantity):
        """
        Update the quantity of an item in a draft stock take session.

        Args:
            session_id: Stock take session ID
            item_id: Stock take item ID to update
            new_quantity: New quantity to set

        Returns:
            Updated StockTakeItem instance

        Raises:
            ValidationError: If session not in draft, item not found, or invalid quantity
        """
        if new_quantity < 0:
            raise ValidationError("Quantity cannot be negative")

        try:
            session = StockTakeSession.objects.get(session_id=session_id)
        except StockTakeSession.DoesNotExist:
            raise ValidationError(f"Stock take session {session_id} not found")

        # Verify session is in DRAFT status
        if session.status != StockTakeSession.Status.DRAFT:
            raise ValidationError(
                f"Cannot update items in {session.get_status_display()} session. "
                f"Session must be in DRAFT status."
            )

        try:
            item = StockTakeItem.objects.get(id=item_id, session=session)
            # Update the quantity
            item.quantity_scanned = new_quantity
            item.quantity_after = item.quantity_before + new_quantity
            item.save()
            return item
        except StockTakeItem.DoesNotExist:
            raise ValidationError(
                f"Item {item_id} not found in session {session_id}"
            )

    @staticmethod
    def update_kit_quantity(session_id, kit_quantity):
        """
        Update the registration kit quantity for a draft stock take session.

        Args:
            session_id: Stock take session ID
            kit_quantity: New kit quantity (0 or more)

        Returns:
            StockTakeSession instance

        Raises:
            ValidationError: If session not in draft or invalid quantity
        """
        if kit_quantity < 0:
            raise ValidationError("Kit quantity cannot be negative")

        try:
            session = StockTakeSession.objects.get(session_id=session_id)
        except StockTakeSession.DoesNotExist:
            raise ValidationError(f"Stock take session {session_id} not found")

        if session.status != StockTakeSession.Status.DRAFT:
            raise ValidationError(
                f"Cannot update kit quantity on {session.get_status_display()} session. "
                f"Session must be in DRAFT status."
            )

        session.kit_quantity = kit_quantity
        session.save()
        return session

    @staticmethod
    def cancel_session(session_id, cancelled_by):
        """
        Cancel a draft stock take session.

        Args:
            session_id: Stock take session ID
            cancelled_by: User cancelling the session

        Returns:
            StockTakeSession instance

        Raises:
            ValidationError: If session not in draft
        """
        try:
            session = StockTakeSession.objects.get(session_id=session_id)
        except StockTakeSession.DoesNotExist:
            raise ValidationError(f"Stock take session {session_id} not found")

        # Verify session is in DRAFT status
        if session.status != StockTakeSession.Status.DRAFT:
            raise ValidationError(
                f"Cannot cancel {session.get_status_display()} session. "
                f"Session must be in DRAFT status."
            )

        # Mark as cancelled
        session.status = StockTakeSession.Status.CANCELLED
        session.completed_at = timezone.now()
        session.completed_by = cancelled_by
        session.save()

        return session
