import uuid
from django.db import models
from django.core.validators import MaxLengthValidator
from django.core.exceptions import ValidationError
import re
from django.utils import timezone
from decimal import Decimal
from utils.constants import STATUS_COLORS, STATUS_ICONS

class PaymentGateway(models.Model):
    """
    Payment Gateway Configuration

    Represents different payment channels (Tills, Paybills, PDQ, Bank)
    and their associated settlement rules.

    Examples:
    - Till 1 - Supplements (M-PESA Till 555000)
    - Till 2 - Merchandise (M-PESA Till 555001)
    - Paybill - Parent Company (Paybill 654321)
    - PDQ/Bank - Manual Payments
    """

    class GatewayType(models.TextChoices):
        MPESA_TILL = 'MPESA_TILL', 'M-PESA Till Number'
        MPESA_PAYBILL = 'MPESA_PAYBILL', 'M-PESA Paybill'
        PDQ = 'PDQ', 'PDQ/Card Payment'
        BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'
        CASH = 'CASH', 'Cash Payment'
        OTHER = 'OTHER', 'Other'

    class SettlementType(models.TextChoices):
        NONE = 'NONE', 'No Settlement Required (100% to shop)'
        PARENT_TAKES_ALL = 'PARENT_TAKES_ALL', 'All to Parent Company'
        COST_MARKUP = 'COST_MARKUP', 'Parent gets cost, Shop gets markup'
        PERCENTAGE = 'PERCENTAGE', 'Percentage split'
        CUSTOM = 'CUSTOM', 'Custom calculation'

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Gateway name (e.g., 'Till 1 - Supplements')"
    )
    gateway_type = models.CharField(
        max_length=20,
        choices=GatewayType.choices,
        help_text="Type of payment gateway"
    )
    gateway_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Till number, Paybill number, or identifier"
    )
    settlement_type = models.CharField(
        max_length=20,
        choices=SettlementType.choices,
        default=SettlementType.NONE,
        help_text="How to split payments with parent company"
    )
    settlement_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="If percentage split, what % goes to parent (e.g., 70.00 = 70%)"
    )
    requires_parent_settlement = models.BooleanField(
        default=False,
        help_text="Does this gateway require settlement with parent company?"
    )
    description = models.TextField(
        blank=True,
        help_text="Additional notes about this gateway"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Is this gateway currently active?"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Payment Gateway'
        verbose_name_plural = 'Payment Gateways'

    def __str__(self):
        return f"{self.name} ({self.gateway_number})"

    def calculate_settlement(self, amount: Decimal) -> dict:
        """
        Calculate settlement split for this gateway.

        Implements settlement rules based on gateway type and configuration.

        Args:
            amount: Transaction amount

        Returns:
            dict: {
                'total': amount,
                'parent_amount': Decimal,
                'shop_amount': Decimal,
                'settlement_type': str,
                'calculation_note': str
            }
        """
        # All Paybill transactions go to Parent Company
        if self.gateway_type == self.GatewayType.MPESA_PAYBILL:
            return {
                'total': amount,
                'parent_amount': amount,
                'shop_amount': Decimal('0.00'),
                'settlement_type': 'PAYBILL_TO_PARENT',
                'calculation_note': 'Paybill - All to parent company'
            }

        if not self.requires_parent_settlement:
            return {
                'total': amount,
                'parent_amount': Decimal('0.00'),
                'shop_amount': amount,
                'settlement_type': self.settlement_type,
                'calculation_note': 'No parent settlement required - 100% to shop'
            }

        # Settlement calculations based on configured type
        if self.settlement_type == self.SettlementType.PARENT_TAKES_ALL:
            return {
                'total': amount,
                'parent_amount': amount,
                'shop_amount': Decimal('0.00'),
                'settlement_type': self.settlement_type,
                'calculation_note': 'All to parent company'
            }

        elif self.settlement_type == self.SettlementType.PERCENTAGE and self.settlement_percentage:
            parent_amount = (amount * self.settlement_percentage / Decimal('100')).quantize(Decimal('0.01'))
            shop_amount = amount - parent_amount
            return {
                'total': amount,
                'parent_amount': parent_amount,
                'shop_amount': shop_amount,
                'settlement_type': self.settlement_type,
                'calculation_note': f'Parent: {self.settlement_percentage}%, Shop: {100 - self.settlement_percentage}%'
            }

        elif self.settlement_type == self.SettlementType.COST_MARKUP:
            # PLACEHOLDER: Actual cost+markup calculation will be per-product
            return {
                'total': amount,
                'parent_amount': Decimal('0.00'),  # TODO: Calculate based on product cost
                'shop_amount': amount,  # TODO: Calculate based on markup
                'settlement_type': self.settlement_type,
                'calculation_note': 'TODO: Implement per-product cost+markup calculation'
            }

        else:
            # Custom or unknown settlement type
            return {
                'total': amount,
                'parent_amount': Decimal('0.00'),
                'shop_amount': amount,
                'settlement_type': self.settlement_type,
                'calculation_note': 'Settlement calculation pending - manual review required'
            }


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    gateway = models.ForeignKey(
        PaymentGateway,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='devices',
        help_text="Which payment gateway this device handles"
    )
    # Legacy fields - will be deprecated
    default_gateway = models.CharField(max_length=50, blank=True)
    gateway_number = models.CharField(max_length=50, blank=True)

    api_key = models.CharField(max_length=255, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class RawMessage(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='messages', db_index=True)
    raw_text = models.TextField(validators=[MaxLengthValidator(1024)])
    received_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    processed = models.BooleanField(default=False)
    transaction = models.ForeignKey('Transaction', on_delete=models.SET_NULL, null=True, blank=True, related_name='raw_messages')

    def __str__(self):
        return f"Message for {self.device.name} at {self.received_at}"

    def clean(self):
        super().clean()
        # Strip control characters from raw_text
        self.raw_text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', self.raw_text)

class Transaction(models.Model):
    class OrderStatus(models.TextChoices):
        NOT_PROCESSED = 'NOT_PROCESSED', 'Not Processed'
        PROCESSING = 'PROCESSING', 'Processing'
        PARTIALLY_FULFILLED = 'PARTIALLY_FULFILLED', 'Partially Fulfilled'
        FULFILLED = 'FULFILLED', 'Fulfilled'
        CANCELLED = 'CANCELLED', 'Cancelled'

    tx_id = models.CharField(max_length=50, unique=True, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    sender_name = models.CharField(max_length=255, blank=True)
    sender_phone = models.CharField(max_length=50, blank=True)
    timestamp = models.DateTimeField()
    gateway = models.ForeignKey(
        PaymentGateway,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='transactions',
        help_text="Payment gateway this transaction came through"
    )
    # Legacy field - will be deprecated after migration
    gateway_type = models.CharField(max_length=50, blank=True)
    destination_number = models.CharField(max_length=50, blank=True)
    confidence = models.FloatField(default=0)
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.NOT_PROCESSED,
        db_index=True
    )

    # Legacy fields (DEPRECATED - will be removed in future version)
    # Use amount_fulfilled instead
    amount_expected = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="DEPRECATED: Use transaction.amount instead"
    )
    amount_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        null=True,
        blank=True,
        help_text="DEPRECATED: Use amount_fulfilled instead"
    )

    # New fulfillment tracking fields
    amount_fulfilled = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Sum of scanned line items (replaces amount_paid)"
    )
    total_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Total cost of all line items (for settlement calculation)"
    )
    total_pv = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Total Point Value of all line items"
    )
    is_in_issuance = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Is this transaction currently being fulfilled? (Only one at a time)"
    )

    notes = models.TextField(blank=True)
    unique_hash = models.CharField(max_length=64, unique=True, db_index=True)
    duplicate_of = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount_fulfilled__lte=models.F('amount')),
                name='amount_fulfilled_cannot_exceed_payment',
                violation_error_message='Amount fulfilled cannot exceed payment amount'
            ),
        ]

    def __str__(self):
        return f"Transaction {self.tx_id} of {self.amount}"

    @property
    def remaining_amount(self):
        """
        Calculate how much of the payment is still available for fulfillment.
        Returns the difference between amount received and amount fulfilled.
        Will be 0 for fully fulfilled or cancelled transactions.

        Note: Supports both amount_fulfilled (new) and amount_paid (legacy) for backwards compatibility.
        """
        if self.status in [self.OrderStatus.FULFILLED, self.OrderStatus.CANCELLED]:
            return Decimal('0.00')

        # Use amount_fulfilled if set, otherwise fall back to amount_paid for legacy support
        paid = self.amount_fulfilled if self.amount_fulfilled > 0 else (self.amount_paid or Decimal('0.00'))
        return self.amount - paid

    @property
    def is_locked(self):
        """
        Check if transaction is locked (cannot be modified).
        Transactions are locked when FULFILLED or CANCELLED.
        """
        return self.status in [
            self.OrderStatus.FULFILLED,
            self.OrderStatus.CANCELLED
        ]

    def get_status_color(self):
        """
        Return hex color code for current status.
        Used by frontend for visual status indicators.

        Returns:
            str: Hex color code (e.g., '#EF4444')
        """
        return STATUS_COLORS.get(self.status, '#6B7280')  # Gray as fallback

    def get_status_icon(self):
        """
        Return emoji icon for current status.
        Used by frontend for visual status indicators.

        Returns:
            str: Emoji icon (e.g., '✅')
        """
        return STATUS_ICONS.get(self.status, '❓')  # Question mark as fallback

    @property
    def status_display(self):
        """
        Return comprehensive status information for frontend display.
        Includes status value, label, color, and icon.

        Returns:
            dict: {
                'status': 'FULFILLED',
                'label': 'Fulfilled',
                'color': '#10B981',
                'icon': '✅',
                'is_locked': True
            }
        """
        return {
            'status': self.status,
            'label': self.get_status_display(),
            'color': self.get_status_color(),
            'icon': self.get_status_icon(),
            'is_locked': self.is_locked,
        }

    def can_transition_to(self, new_status):
        """
        Check if the transaction can transition to the new status.
        Enforces valid state machine transitions.

        Valid transitions:
        - NOT_PROCESSED → PROCESSING, CANCELLED
        - PROCESSING → PARTIALLY_FULFILLED, FULFILLED, CANCELLED
        - PARTIALLY_FULFILLED → FULFILLED, CANCELLED
        - FULFILLED → (locked, no transitions)
        - CANCELLED → (locked, no transitions)
        """
        if self.is_locked:
            return False

        valid_transitions = {
            self.OrderStatus.NOT_PROCESSED: [
                self.OrderStatus.PROCESSING,
                self.OrderStatus.CANCELLED
            ],
            self.OrderStatus.PROCESSING: [
                self.OrderStatus.PARTIALLY_FULFILLED,
                self.OrderStatus.FULFILLED,
                self.OrderStatus.CANCELLED
            ],
            self.OrderStatus.PARTIALLY_FULFILLED: [
                self.OrderStatus.FULFILLED,
                self.OrderStatus.CANCELLED
            ],
        }

        return new_status in valid_transitions.get(self.status, [])

    def clean(self):
        """
        Validate the transaction data before saving.
        """
        super().clean()

        # Validate amount_paid doesn't exceed amount received
        if self.amount_paid > self.amount:
            raise ValidationError({
                'amount_paid': f'Amount fulfilled ({self.amount_paid}) cannot exceed amount received ({self.amount})'
            })

        # Prevent modification of locked transactions
        if self.pk:  # Only check if updating existing transaction
            try:
                old_instance = Transaction.objects.get(pk=self.pk)
                if old_instance.is_locked and old_instance.status != self.status:
                    raise ValidationError({
                        'status': f'Transaction is {old_instance.status} and cannot be modified'
                    })

                # Validate status transitions
                if old_instance.status != self.status:
                    if not old_instance.can_transition_to(self.status):
                        raise ValidationError({
                            'status': f'Cannot transition from {old_instance.get_status_display()} to {self.get_status_display()}'
                        })
            except Transaction.DoesNotExist:
                pass

    def save(self, *args, **kwargs):
        """
        Override save to implement auto-locking logic.
        Auto-lock when amount is fully used.
        """
        # Run validation unless explicitly skipped
        skip_validation = kwargs.pop('skip_validation', False)
        if not skip_validation:
            self.full_clean()

        # Auto-fulfill when payment is fully used
        if self.amount_paid >= self.amount:
            if self.status in [self.OrderStatus.PROCESSING, self.OrderStatus.PARTIALLY_FULFILLED]:
                self.status = self.OrderStatus.FULFILLED
                # Ensure amount_paid equals amount when fulfilled
                self.amount_paid = self.amount

        # Auto-mark as partially fulfilled if payment is partially used
        elif self.amount_paid > Decimal('0.00'):
            if self.status == self.OrderStatus.PROCESSING:
                self.status = self.OrderStatus.PARTIALLY_FULFILLED

        # When manually marking as FULFILLED, move remaining amount to amount_paid
        if self.status == self.OrderStatus.FULFILLED and self.amount_paid < self.amount:
            self.amount_paid = self.amount

        super().save(*args, **kwargs)


class ManualPayment(models.Model):
    """
    Manual payment entry for non-SMS payments (PDQ, Bank Transfer, Cash, etc.)

    This model allows staff to manually record payments that aren't automatically
    captured via SMS parsing. Common use cases:
    - PDQ/Card payments at physical store
    - Direct bank transfers
    - Cash payments
    - Cheque payments
    """

    class PaymentMethod(models.TextChoices):
        PDQ = 'PDQ', 'PDQ/Card'
        BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'
        CASH = 'CASH', 'Cash'
        CHEQUE = 'CHEQUE', 'Cheque'
        OTHER = 'OTHER', 'Other'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name='manual_payments',
        help_text="Transaction created from this manual entry"
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        help_text="How the payment was received"
    )
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Reference number (e.g., bank transaction ID, PDQ receipt number)"
    )
    payer_name = models.CharField(
        max_length=255,
        help_text="Name of person who made the payment"
    )
    payer_phone = models.CharField(
        max_length=50,
        blank=True,
        help_text="Phone number of payer (optional)"
    )
    payer_email = models.EmailField(
        blank=True,
        help_text="Email address of payer (optional)"
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Amount received"
    )
    payment_date = models.DateTimeField(
        help_text="When the payment was received"
    )
    notes = models.TextField(
        blank=True,
        help_text="Additional notes about this payment"
    )
    created_by = models.CharField(
        max_length=255,
        help_text="Staff member who entered this payment"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-payment_date']
        indexes = [
            models.Index(fields=['-payment_date']),
            models.Index(fields=['payment_method']),
            models.Index(fields=['reference_number']),
        ]

    def __str__(self):
        return f"Manual {self.payment_method} payment of {self.amount} from {self.payer_name}"

    def clean(self):
        """Validate manual payment data"""
        super().clean()

        if self.amount <= Decimal('0.00'):
            raise ValidationError({
                'amount': 'Amount must be greater than zero'
            })

        # Validate reference number required for certain payment methods
        if self.payment_method in [self.PaymentMethod.BANK_TRANSFER, self.PaymentMethod.PDQ]:
            if not self.reference_number or not self.reference_number.strip():
                raise ValidationError({
                    'reference_number': f'Reference number is required for {self.get_payment_method_display()} payments'
                })


# ============================================================
# INVENTORY MANAGEMENT MODELS
# ============================================================

class ProductCategory(models.Model):
    """
    Product categories for organizing inventory.
    Supports hierarchical categories (parent-child relationships).
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    parent_category = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='subcategories',
        help_text="Parent category if this is a subcategory"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Product Category'
        verbose_name_plural = 'Product Categories'

    def __str__(self):
        if self.parent_category:
            return f"{self.parent_category.name} > {self.name}"
        return self.name


class Product(models.Model):
    """
    Product catalog for inventory management.

    Tracks product information and current stock levels.
    Barcode contains transaction-time data (price/PV),
    this model tracks current/default values and inventory.
    """
    # Product identification (from products.jpeg)
    prod_code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Product code (e.g., AP004E)"
    )
    prod_name = models.CharField(
        max_length=200,
        help_text="Product name"
    )
    sku = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="SKU/Barcode identifier for scanner"
    )
    sku_name = models.CharField(
        max_length=200,
        help_text="Package description (e.g., '100 tablets')"
    )

    # Pricing (current/default values in database)
    current_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Current selling price"
    )
    cost_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Cost price from parent company"
    )
    current_pv = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Current Point Value for commissions"
    )

    # Inventory tracking
    quantity = models.IntegerField(
        default=0,
        help_text="Current stock level"
    )
    reorder_level = models.IntegerField(
        default=10,
        help_text="Minimum stock level before reorder alert"
    )

    # Classification
    category = models.ForeignKey(
        ProductCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='products'
    )

    # Status
    is_active = models.BooleanField(
        default=True,
        help_text="Is this product available for sale?"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['prod_name']
        verbose_name = 'Product'
        verbose_name_plural = 'Products'
        indexes = [
            models.Index(fields=['prod_code']),
            models.Index(fields=['sku']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.prod_code} - {self.prod_name}"

    @property
    def is_low_stock(self):
        """Check if product is below reorder level"""
        return self.quantity <= self.reorder_level

    @property
    def is_out_of_stock(self):
        """Check if product is completely out of stock"""
        return self.quantity <= 0

    def clean(self):
        """Validate product data"""
        super().clean()

        if self.current_price <= Decimal('0.00'):
            raise ValidationError({
                'current_price': 'Price must be greater than zero'
            })

        if self.cost_price < Decimal('0.00'):
            raise ValidationError({
                'cost_price': 'Cost price cannot be negative'
            })

        if self.quantity < 0:
            raise ValidationError({
                'quantity': 'Quantity cannot be negative'
            })


class TransactionLineItem(models.Model):
    """
    Line items linking transactions to products (scanned items).

    Stores barcode data captured at scan time (frozen price/PV),
    while also linking to Product for inventory tracking.
    """
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name='line_items',
        help_text="Transaction this item belongs to"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='transaction_items',
        help_text="Product reference for inventory tracking"
    )

    # Data from barcode at scan time (frozen values)
    scanned_prod_code = models.CharField(max_length=50)
    scanned_prod_name = models.CharField(max_length=200)
    scanned_sku = models.CharField(max_length=100)
    scanned_sku_name = models.CharField(max_length=200)
    scanned_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Price from barcode at scan time"
    )
    scanned_pv = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Point Value from barcode at scan time"
    )

    # Quantity scanned
    quantity = models.IntegerField(help_text="Quantity scanned")

    # Calculated fields
    line_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="quantity × scanned_price"
    )
    line_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="quantity × product.cost_price (for settlement)"
    )
    line_pv = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="quantity × scanned_pv"
    )

    # Audit fields
    scanned_at = models.DateTimeField(auto_now_add=True)
    scanned_by = models.CharField(
        max_length=255,
        blank=True,
        help_text="User who scanned this item"
    )

    class Meta:
        ordering = ['scanned_at']
        verbose_name = 'Transaction Line Item'
        verbose_name_plural = 'Transaction Line Items'

    def __str__(self):
        return f"{self.quantity}x {self.scanned_prod_name} (TX: {self.transaction.tx_id})"

    def save(self, *args, **kwargs):
        """Auto-calculate line totals on save"""
        self.line_total = self.quantity * self.scanned_price
        self.line_cost = self.quantity * self.product.cost_price
        self.line_pv = self.quantity * self.scanned_pv
        super().save(*args, **kwargs)

    def clean(self):
        """Validate line item data"""
        super().clean()

        if self.quantity <= 0:
            raise ValidationError({
                'quantity': 'Quantity must be greater than zero'
            })

        # Validate product has enough stock
        if self.product and self.product.quantity < self.quantity:
            raise ValidationError({
                'quantity': f'Insufficient stock. Available: {self.product.quantity}'
            })


class InventoryMovement(models.Model):
    """
    Audit trail for all inventory movements.
    Tracks stock changes for sales, stock takes, adjustments, etc.
    """
    class MovementType(models.TextChoices):
        STOCK_TAKE = 'STOCK_TAKE', 'Stock Take'
        SALE = 'SALE', 'Sale'
        ADJUSTMENT = 'ADJUSTMENT', 'Manual Adjustment'
        RETURN = 'RETURN', 'Return'
        PURCHASE = 'PURCHASE', 'Purchase/Replenishment'

    movement_type = models.CharField(
        max_length=20,
        choices=MovementType.choices,
        help_text="Type of inventory movement"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='movements',
        help_text="Product affected"
    )

    # Quantity tracking
    quantity_before = models.IntegerField(help_text="Stock quantity before movement")
    quantity_after = models.IntegerField(help_text="Stock quantity after movement")
    quantity_change = models.IntegerField(help_text="Change in quantity (can be negative)")

    # Reference
    reference = models.CharField(
        max_length=200,
        blank=True,
        help_text="Reference (transaction ID, note, etc.)"
    )

    # Audit
    performed_by = models.CharField(
        max_length=255,
        blank=True,
        help_text="User who performed this movement"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Inventory Movement'
        verbose_name_plural = 'Inventory Movements'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['product', '-created_at']),
            models.Index(fields=['movement_type']),
        ]

    def __str__(self):
        sign = '+' if self.quantity_change > 0 else ''
        return f"{self.get_movement_type_display()}: {sign}{self.quantity_change} {self.product.prod_name}"

    def clean(self):
        """Validate movement data"""
        super().clean()

        # Verify calculation is correct
        expected_after = self.quantity_before + self.quantity_change
        if self.quantity_after != expected_after:
            raise ValidationError({
                'quantity_after': f'Calculation error: {self.quantity_before} + {self.quantity_change} should equal {expected_after}, not {self.quantity_after}'
            })