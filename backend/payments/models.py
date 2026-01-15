import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxLengthValidator
from django.core.exceptions import ValidationError
from django.conf import settings
import re
from django.utils import timezone
from decimal import Decimal
from utils.constants import STATUS_COLORS, STATUS_ICONS


# ============================================================================
# User Model with Role-Based Access Control
# ============================================================================

class User(AbstractUser):
    """
    Custom User model with role-based access control.

    Roles:
    - ADMIN: Full access to all features
    - PROCESSOR: Transactions, Reports, Reconciliation (activate orders, combine)
    - ISSUER: Fulfillment, Stock Taking (scan products, issue items)
    """

    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrator'
        PROCESSOR = 'PROCESSOR', 'Processor'
        ISSUER = 'ISSUER', 'Issuer'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ADMIN,
        db_index=True,
        help_text="User role determines access permissions"
    )

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    def is_admin(self):
        """Check if user has admin role"""
        return self.role == self.Role.ADMIN

    def is_processor(self):
        """Check if user has processor role"""
        return self.role == self.Role.PROCESSOR

    def is_issuer(self):
        """Check if user has issuer role"""
        return self.role == self.Role.ISSUER

    def has_processor_access(self):
        """Check if user can access processor features (Admin or Processor)"""
        return self.role in [self.Role.ADMIN, self.Role.PROCESSOR]

    def has_issuer_access(self):
        """Check if user can access issuer features (Admin or Issuer)"""
        return self.role in [self.Role.ADMIN, self.Role.ISSUER]

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
        on_delete=models.PROTECT,
        related_name='devices',
        help_text="Which payment gateway this device handles (required)"
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
        COMBINED_FULFILLED = 'COMBINED_FULFILLED', 'Combined Order Fulfilled'
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

    # Time-locking fields (for end-of-day locking)
    is_time_locked = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Locked at end-of-day to prevent further modifications"
    )
    locked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when transaction was locked (manual or automatic)"
    )
    locked_by = models.CharField(
        max_length=255,
        blank=True,
        help_text="User or system process that locked the transaction"
    )

    # Audit trail fields (ForeignKey to User)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='activated_transactions',
        help_text="User who activated this transaction for issuance"
    )
    activated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the transaction was activated for issuance"
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='completed_transactions',
        help_text="User who completed the issuance"
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the issuance was completed"
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='cancelled_transactions',
        help_text="User who cancelled this transaction"
    )
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the transaction was cancelled"
    )

    # Processor tracking
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='processed_transactions',
        help_text="User who processed this transaction (changed to PROCESSING)"
    )
    processed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the transaction was processed"
    )

    # Registration transaction flag
    is_registration = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Is this a registration transaction (special handling)"
    )

    # Registration kit issuance tracking
    registration_kit_issued = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Has registration kit been issued for this transaction"
    )
    registration_kit_quantity = models.IntegerField(
        default=0,
        help_text="Number of registration kits issued"
    )
    registration_kit_amount_deducted = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Amount deducted for registration kit(s)"
    )

    # State tracking for issuance cancellation
    # These fields store the transaction state BEFORE activation
    # so we can restore it if the issuance is cancelled
    amount_fulfilled_before_activation = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Amount fulfilled before this issuance session started (for cancel restore)"
    )
    status_before_activation = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        null=True,
        blank=True,
        help_text="Status before this issuance session started (for cancel restore)"
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
        Transactions are locked when:
        1. Status is FULFILLED or CANCELLED, OR
        2. is_time_locked is True (end-of-day lock)
        """
        return (
            self.status in [self.OrderStatus.FULFILLED, self.OrderStatus.CANCELLED]
            or self.is_time_locked
        )

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
        Includes status value, label, color, icon, and locking info.

        Returns:
            dict: {
                'status': 'FULFILLED',
                'label': 'Fulfilled',
                'color': '#10B981',
                'icon': '✅',
                'is_locked': True,
                'is_time_locked': False,
                'locked_at': '2025-12-02T23:59:59Z',
                'locked_by': 'System: Daily Report'
            }
        """
        return {
            'status': self.status,
            'label': self.get_status_display(),
            'color': self.get_status_color(),
            'icon': self.get_status_icon(),
            'is_locked': self.is_locked,
            'is_time_locked': self.is_time_locked,
            'locked_at': self.locked_at.isoformat() if self.locked_at else None,
            'locked_by': self.locked_by,
        }

    def can_transition_to(self, new_status):
        """
        Check if the transaction can transition to the new status.
        Enforces valid state machine transitions.

        Valid transitions:
        - NOT_PROCESSED → PROCESSING, CANCELLED
        - PROCESSING → PARTIALLY_FULFILLED, FULFILLED, CANCELLED
        - PARTIALLY_FULFILLED → PROCESSING (revert), FULFILLED, CANCELLED
        - FULFILLED → (locked, no transitions)
        - CANCELLED → (locked, no transitions)

        Note: PARTIALLY_FULFILLED → PROCESSING revert is blocked if:
        - Transaction is time-locked (requires admin override)
        - Transaction is in a combined order
        """
        if self.is_locked:
            return False

        valid_transitions = {
            self.OrderStatus.NOT_PROCESSED: [
                self.OrderStatus.PROCESSING,
                self.OrderStatus.COMBINED_FULFILLED,
                self.OrderStatus.CANCELLED
            ],
            self.OrderStatus.PROCESSING: [
                self.OrderStatus.PARTIALLY_FULFILLED,
                self.OrderStatus.FULFILLED,
                self.OrderStatus.COMBINED_FULFILLED,
                self.OrderStatus.CANCELLED
            ],
            self.OrderStatus.PARTIALLY_FULFILLED: [
                self.OrderStatus.PROCESSING,  # Allow revert to PROCESSING
                self.OrderStatus.FULFILLED,
                self.OrderStatus.COMBINED_FULFILLED,
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
                if old_instance.is_locked:
                    raise ValidationError(
                        f'Transaction {old_instance.tx_id} is locked and cannot be modified. '
                        f'Locked by: {old_instance.locked_by or "status: " + old_instance.status}'
                    )

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

        # Sync amount_paid with amount_fulfilled for backwards compatibility
        # Use whichever is greater to ensure consistency
        if self.amount_fulfilled > self.amount_paid:
            self.amount_paid = self.amount_fulfilled
        elif self.amount_paid > self.amount_fulfilled:
            self.amount_fulfilled = self.amount_paid

        # Auto-fulfill when payment is fully used (use amount_fulfilled as source of truth)
        # BUT: Don't auto-fulfill if transaction is in issuance mode
        # The complete_issuance() service method will handle status updates
        if self.amount_fulfilled >= self.amount and not self.is_in_issuance:
            if self.status in [self.OrderStatus.PROCESSING, self.OrderStatus.PARTIALLY_FULFILLED]:
                self.status = self.OrderStatus.FULFILLED
                # Ensure amount_fulfilled equals amount when fulfilled
                self.amount_fulfilled = self.amount
                self.amount_paid = self.amount

        # Auto-mark as partially fulfilled if payment is partially used
        # BUT: Don't auto-update status if transaction is in issuance mode
        elif self.amount_fulfilled > Decimal('0.00') and not self.is_in_issuance:
            if self.status == self.OrderStatus.PROCESSING:
                self.status = self.OrderStatus.PARTIALLY_FULFILLED

        # When manually marking as FULFILLED, move remaining amount to amount_fulfilled
        if self.status == self.OrderStatus.FULFILLED and self.amount_fulfilled < self.amount:
            self.amount_fulfilled = self.amount
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
        help_text="DEPRECATED: Use created_by_user instead"
    )
    created_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_manual_payments',
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

class ProductLine(models.Model):
    """
    Product lines for organizing inventory (e.g., Immune Boosters, Cardiovascular Health).
    Supports hierarchical product lines (parent-child relationships).
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    parent_line = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sublines',
        help_text="Parent product line if this is a sub-line"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Product Line'
        verbose_name_plural = 'Product Lines'

    def __str__(self):
        if self.parent_line:
            return f"{self.parent_line.name} > {self.name}"
        return self.name


class Product(models.Model):
    """
    Product catalog for inventory management.

    Tracks product information and current stock levels.
    Barcode contains transaction-time data (price/PV),
    this model tracks current/default values and inventory.
    """
    # Product identification
    prod_code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Product Code/SKU (same value, e.g., AP004E)"
    )
    prod_name = models.CharField(
        max_length=200,
        help_text="Product name"
    )
    sku = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="SKU (same as prod_code, kept for backward compatibility)"
    )
    sku_name = models.CharField(
        max_length=200,
        help_text="Package description (e.g., '100 tablets', '60 capsules')"
    )
    barcode = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        db_index=True,
        help_text="Product barcode for scanning (can be same as SKU or different)"
    )

    # Pricing (current/default values in database)
    current_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Buying price (what resellers pay us)"
    )
    cost_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Cost price (same as buying price, kept for backward compatibility)"
    )
    current_pv = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Point Value (PV) for commissions"
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
    product_line = models.ForeignKey(
        ProductLine,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='products',
        help_text="Product line (e.g., Immune Boosters, Cardiovascular Health)"
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

    @property
    def stock_status(self):
        """
        Return human-readable stock status.

        Returns:
            str: 'Out of Stock', 'Low Stock', or 'In Stock'
        """
        if self.quantity <= 0:
            return 'Out of Stock'
        elif self.quantity <= self.reorder_level:
            return 'Low Stock'
        else:
            return 'In Stock'

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

    # Completion tracking
    is_inventory_deducted = models.BooleanField(
        default=False,
        help_text="True if inventory has been deducted for this item (on issuance completion)"
    )

    # Audit fields
    scanned_at = models.DateTimeField(auto_now_add=True)
    scanned_by = models.CharField(
        max_length=255,
        blank=True,
        help_text="DEPRECATED: Use scanned_by_user instead"
    )
    scanned_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='scanned_line_items',
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
        help_text="User who performed this movement (legacy string field)"
    )
    performed_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='inventory_movements_performed',
        help_text="User who performed this movement (ForeignKey)"
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


# ============================================================================
# Stock Taking Models
# ============================================================================

class StockTakeSession(models.Model):
    """
    Stock taking session for inventory audits and updates.
    Each session allows scanning multiple products with draft capability.
    """
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    session_id = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        help_text="Session identifier (STK-YYYYMMDD-HHMMSS)"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        help_text="Session status"
    )
    created_by = models.CharField(
        max_length=255,
        help_text="DEPRECATED: Use performed_by_user instead"
    )
    performed_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='stock_take_sessions',
        help_text="User who performed this stock take"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When session was completed"
    )
    completed_by = models.CharField(
        max_length=255,
        blank=True,
        help_text="DEPRECATED: Use completed_by_user instead"
    )
    completed_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='completed_stock_take_sessions',
        help_text="User who completed this session"
    )
    notes = models.TextField(
        blank=True,
        help_text="Session notes"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Stock Take Session'
        verbose_name_plural = 'Stock Take Sessions'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"Stock Take {self.session_id} ({self.get_status_display()})"


class StockTakeItem(models.Model):
    """
    Individual product scans within a stock take session.
    Tracks before/after quantities for audit trail.
    """
    session = models.ForeignKey(
        StockTakeSession,
        on_delete=models.CASCADE,
        related_name='items',
        help_text="Parent stock take session"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        help_text="Product being counted"
    )
    quantity_before = models.IntegerField(
        help_text="Stock quantity before this scan"
    )
    quantity_scanned = models.IntegerField(
        help_text="Quantity scanned (added to stock)"
    )
    quantity_after = models.IntegerField(
        help_text="Stock quantity after this scan"
    )
    scanned_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this item was scanned"
    )
    scanned_by = models.CharField(
        max_length=255,
        help_text="User who scanned this item"
    )

    class Meta:
        ordering = ['-scanned_at']
        verbose_name = 'Stock Take Item'
        verbose_name_plural = 'Stock Take Items'
        indexes = [
            models.Index(fields=['session', '-scanned_at']),
            models.Index(fields=['product']),
        ]

    def __str__(self):
        return f"{self.product.prod_name} (+{self.quantity_scanned})"

    def clean(self):
        """Validate stock take item calculations"""
        super().clean()

        # Verify calculation is correct
        expected_after = self.quantity_before + self.quantity_scanned
        if self.quantity_after != expected_after:
            raise ValidationError({
                'quantity_after': f'Calculation error: {self.quantity_before} + {self.quantity_scanned} should equal {expected_after}, not {self.quantity_after}'
            })


# ============================================================================
# Combined Order Models (Phase 2: Transaction Combination)
# ============================================================================

class CombinedOrder(models.Model):
    """
    Combined Order - links multiple transactions into one fulfillment order.

    Use case: Customer pays in installments (400+300+500=1200), but we fulfill
    against the combined total of 1200 KES.

    Individual transactions remain visible but are linked to this parent order.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Fulfillment'
        IN_PROGRESS = 'IN_PROGRESS', 'Fulfillment In Progress'
        PARTIALLY_FULFILLED = 'PARTIALLY_FULFILLED', 'Partially Fulfilled'
        FULFILLED = 'FULFILLED', 'Fully Fulfilled'
        CANCELLED = 'CANCELLED', 'Cancelled'

    # Identification
    combined_order_id = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        help_text="Auto-generated combined order ID (e.g., CMB-20251202-001)"
    )

    # Parent transaction - appears in transaction list as the combined order
    parent_transaction = models.OneToOneField(
        'Transaction',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='combined_order_parent',
        help_text="Transaction record representing this combined order in the transaction list"
    )

    # Linked transactions
    # (Use CombinedOrderTransaction linking table for many-to-many)

    # Amounts
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Sum of all linked transaction amounts"
    )
    amount_fulfilled = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total value of products issued against this combined order"
    )
    # Track the "base" fulfilled amount from child transactions
    # This is the sum of amount_fulfilled from all linked transactions at the time they were added
    # Used to preserve pre-existing fulfillment when scanning new products
    base_amount_fulfilled = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Sum of amount_fulfilled from child transactions (preserved from before combining)"
    )
    # Track state before activation for cancel restoration
    amount_fulfilled_before_activation = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Amount fulfilled before this issuance session started (for cancel restore)"
    )
    status_before_activation = models.CharField(
        max_length=20,
        choices=Status.choices,
        null=True,
        blank=True,
        help_text="Status before this issuance session started (for cancel restore)"
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Current fulfillment status"
    )

    # Customer info (optional)
    customer_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Customer name (if known)"
    )
    customer_phone = models.CharField(
        max_length=50,
        blank=True,
        help_text="Customer phone (if known)"
    )

    # Notes
    notes = models.TextField(
        blank=True,
        help_text="Additional notes about this combined order"
    )

    # Audit
    created_by = models.CharField(
        max_length=255,
        help_text="DEPRECATED: Use combined_by_user instead"
    )
    combined_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='combined_orders_created',
        help_text="User who created/combined this order"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    fulfilled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the order was fully fulfilled"
    )
    fulfilled_by = models.CharField(
        max_length=255,
        blank=True,
        help_text="DEPRECATED: Use fulfilled_by_user instead"
    )
    fulfilled_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='fulfilled_combined_orders',
        help_text="User who fulfilled this order"
    )

    # Time-locking (end-of-day)
    is_time_locked = models.BooleanField(
        default=False,
        help_text="True if locked at end-of-day (prevents further modifications)"
    )
    locked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this order was time-locked"
    )
    locked_by = models.CharField(
        max_length=255,
        blank=True,
        help_text="Reason or user who locked this order"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Combined Order'
        verbose_name_plural = 'Combined Orders'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['combined_order_id']),
        ]

    def __str__(self):
        return f"{self.combined_order_id} ({self.transaction_count} txns, {self.total_amount} KES)"

    @property
    def transaction_count(self):
        """Number of transactions in this combined order"""
        return self.transactions.count()

    @property
    def remaining_amount(self):
        """Amount remaining to be fulfilled"""
        return self.total_amount - self.amount_fulfilled

    @property
    def fulfillment_percentage(self):
        """Percentage of order fulfilled"""
        if self.total_amount <= 0:
            return Decimal('0.00')
        return (self.amount_fulfilled / self.total_amount) * 100

    def save(self, *args, **kwargs):
        """Auto-generate combined_order_id if not set"""
        if not self.combined_order_id:
            # Generate ID: CMB-YYYYMMDD-NNN
            today = timezone.now().date()
            date_str = today.strftime('%Y%m%d')

            # Find highest number for today
            prefix = f"CMB-{date_str}-"
            last_order = CombinedOrder.objects.filter(
                combined_order_id__startswith=prefix
            ).order_by('-combined_order_id').first()

            if last_order:
                # Extract number and increment
                last_num = int(last_order.combined_order_id.split('-')[-1])
                next_num = last_num + 1
            else:
                next_num = 1

            self.combined_order_id = f"{prefix}{next_num:03d}"

        # Auto-fulfill when fully paid
        if self.amount_fulfilled >= self.total_amount and self.status != self.Status.FULFILLED:
            self.status = self.Status.FULFILLED
            self.fulfilled_at = timezone.now()

        super().save(*args, **kwargs)


class CombinedOrderTransaction(models.Model):
    """
    Linking table between CombinedOrder and Transaction.
    Tracks which transactions are part of which combined order.
    """
    combined_order = models.ForeignKey(
        CombinedOrder,
        on_delete=models.CASCADE,
        related_name='transactions',
        help_text="The combined order"
    )
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.PROTECT,  # Don't allow deleting transactions in a combined order
        related_name='combined_orders',
        help_text="Individual transaction"
    )

    # Order within combined order (for display purposes)
    sequence = models.IntegerField(
        default=0,
        help_text="Display order (0=first, 1=second, etc.)"
    )

    # Track when this link was created
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.CharField(
        max_length=255,
        blank=True,
        help_text="User who added this transaction to the combined order"
    )

    class Meta:
        unique_together = [('combined_order', 'transaction')]
        ordering = ['sequence', 'added_at']
        verbose_name = 'Combined Order Transaction'
        verbose_name_plural = 'Combined Order Transactions'
        indexes = [
            models.Index(fields=['combined_order', 'sequence']),
            models.Index(fields=['transaction']),
        ]

    def __str__(self):
        return f"{self.combined_order.combined_order_id} → {self.transaction.tx_id}"


class CombinedOrderLineItem(models.Model):
    """
    Line items for combined orders.
    Products scanned during fulfillment are attached to the CombinedOrder,
    not to individual transactions.
    """
    combined_order = models.ForeignKey(
        CombinedOrder,
        on_delete=models.CASCADE,
        related_name='line_items',
        help_text="Combined order this line item belongs to"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        help_text="Product issued"
    )

    # Scanned product details (snapshot at time of scan)
    scanned_prod_code = models.CharField(max_length=50, help_text="Product code at time of scan")
    scanned_prod_name = models.CharField(max_length=255, help_text="Product name at time of scan")
    scanned_sku = models.CharField(max_length=50, help_text="SKU at time of scan")
    scanned_sku_name = models.CharField(max_length=255, blank=True, help_text="SKU name at time of scan")
    scanned_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price at time of scan")
    scanned_pv = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="PV at time of scan")

    # Quantity
    quantity = models.IntegerField(default=1, help_text="Number of items issued")

    # Calculated totals
    line_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total for this line (quantity × price)"
    )
    line_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total cost for this line (quantity × cost_price)"
    )
    line_pv = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total PV for this line (quantity × pv)"
    )

    # Completion tracking
    is_inventory_deducted = models.BooleanField(
        default=False,
        help_text="True if inventory has been deducted for this item (on completion)"
    )
    # Track if this line item was copied from a child transaction
    copied_from_transaction = models.ForeignKey(
        'Transaction',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='copied_to_combined_items',
        help_text="If this item was copied from a partially fulfilled transaction"
    )

    # Audit
    scanned_at = models.DateTimeField(auto_now_add=True)
    scanned_by = models.CharField(max_length=255, blank=True, help_text="User who scanned this item")

    class Meta:
        ordering = ['scanned_at']
        verbose_name = 'Combined Order Line Item'
        verbose_name_plural = 'Combined Order Line Items'
        indexes = [
            models.Index(fields=['combined_order', 'scanned_at']),
            models.Index(fields=['product']),
        ]

    def __str__(self):
        return f"{self.scanned_prod_name} × {self.quantity} = {self.line_total} KES"

    def save(self, *args, **kwargs):
        """Calculate line totals before saving"""
        self.line_total = self.scanned_price * self.quantity
        self.line_pv = self.scanned_pv * self.quantity

        # Calculate cost if product has cost_price
        if hasattr(self.product, 'cost_price') and self.product.cost_price:
            self.line_cost = self.product.cost_price * self.quantity

        super().save(*args, **kwargs)


# ============================================================================
# End-of-Day Stock Reconciliation
# ============================================================================

class DailyStockReconciliation(models.Model):
    """
    End-of-day stock reconciliation record.

    This is SEPARATE from StockTakeSession which is for physical inventory audits.
    This reconciliation is for end-of-day reporting where admin/issuer manually
    enters added/deducted quantities that affect the stock report and inventory.

    Only one reconciliation per date is allowed.

    Flow:
    1. Generate report (status=DRAFT) - creates reconciliation with adjustments
    2. User enters added/deducted quantities for products
    3. User confirms (status=CONFIRMED) - applies to actual inventory
    4. Export button appears and report can be downloaded
    """

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        CONFIRMED = 'CONFIRMED', 'Confirmed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reconciliation_date = models.DateField(
        unique=True,
        db_index=True,
        help_text="Date of reconciliation (typically end of day)"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        help_text="DRAFT = editable, CONFIRMED = applied to inventory"
    )
    notes = models.TextField(
        blank=True,
        help_text="Overall notes for the day's reconciliation"
    )

    # Audit trail
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='reconciliations_created',
        help_text="User who created this reconciliation"
    )
    confirmed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reconciliations_confirmed',
        help_text="User who confirmed and applied this reconciliation"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when reconciliation was confirmed and applied"
    )

    class Meta:
        ordering = ['-reconciliation_date']
        verbose_name = 'Daily Stock Reconciliation'
        verbose_name_plural = 'Daily Stock Reconciliations'
        indexes = [
            models.Index(fields=['-reconciliation_date']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Reconciliation {self.reconciliation_date} [{self.status}]"

    def is_confirmed(self):
        """Check if reconciliation is confirmed and locked"""
        return self.status == self.Status.CONFIRMED


class StockAdjustmentItem(models.Model):
    """
    Individual product adjustment within a daily reconciliation.

    Records opening stock, replenished (from stock takes), manual added/deducted
    quantities, and closing stock.

    Flow:
    - opening_stock: Previous day's closing stock (product.quantity at reconciliation creation)
    - quantity_replenished: AUTO-CALCULATED from completed stock take sessions for the day (read-only)
    - quantity_added: Manual additions (corrections, found items)
    - quantity_deducted: Manual deductions (damaged, stolen, shrinkage)
    - closing_stock: Current product.quantity (auto-refreshed)
    - sales: calculated_totals - closing_stock

    When reconciliation is confirmed, only Added/Deducted adjustments update inventory
    (replenished already updated inventory when stock take was completed).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reconciliation = models.ForeignKey(
        DailyStockReconciliation,
        on_delete=models.CASCADE,
        related_name='adjustments',
        help_text="Parent reconciliation record"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='stock_adjustments',
        help_text="Product being adjusted"
    )

    # Stock tracking
    opening_stock = models.IntegerField(
        help_text="Stock quantity at start of day (from previous day's closing or baseline)"
    )
    opening_stock_baseline = models.IntegerField(
        null=True,
        blank=True,
        help_text="Manual baseline override for opening stock (used for initial setup, ignores previous reconciliation)"
    )
    quantity_replenished = models.IntegerField(
        default=0,
        help_text="Quantity replenished from stock take sessions (auto-calculated, read-only)"
    )
    quantity_added = models.IntegerField(
        default=0,
        help_text="Quantity added (manual adjustments, corrections)"
    )
    quantity_deducted = models.IntegerField(
        default=0,
        help_text="Quantity deducted (e.g., damaged, stolen, shrinkage)"
    )
    closing_stock = models.IntegerField(
        help_text="Actual closing stock counted during stock take"
    )

    # Notes for this specific product
    notes = models.TextField(
        blank=True,
        help_text="Notes about this specific adjustment"
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['product__prod_name']
        verbose_name = 'Stock Adjustment Item'
        verbose_name_plural = 'Stock Adjustment Items'
        indexes = [
            models.Index(fields=['reconciliation', 'product']),
            models.Index(fields=['product']),
        ]
        # Only one adjustment per product per reconciliation
        constraints = [
            models.UniqueConstraint(
                fields=['reconciliation', 'product'],
                name='unique_reconciliation_product'
            )
        ]

    def __str__(self):
        return f"{self.product.prod_name}: {self.opening_stock} → {self.closing_stock}"

    @property
    def effective_opening_stock(self):
        """
        Get the effective opening stock, using baseline if set.
        Baseline is used for initial setup when previous reconciliation data is invalid.
        """
        if self.opening_stock_baseline is not None:
            return self.opening_stock_baseline
        return self.opening_stock

    @property
    def net_adjustment(self):
        """Calculate net adjustment (added - deducted)"""
        return self.quantity_added - self.quantity_deducted

    @property
    def calculated_totals(self):
        """
        Calculate totals: Opening Stock + Replenished + Added - Deducted
        This represents expected stock if no sales occurred.
        Uses effective_opening_stock (baseline if set, otherwise opening_stock).
        """
        return self.effective_opening_stock + self.quantity_replenished + self.quantity_added - self.quantity_deducted

    @property
    def sales(self):
        """
        Calculate sales: Totals - Closing Stock
        This represents stock movement due to sales/usage.
        """
        return self.calculated_totals - self.closing_stock

    @staticmethod
    def calculate_replenished_from_stock_takes(product_id: int, target_date) -> int:
        """
        Calculate quantity replenished from completed stock take sessions for a given date.

        Args:
            product_id: ID of the product
            target_date: Date to calculate replenished for

        Returns:
            Total quantity replenished from stock takes on that date
        """
        from django.db.models import Sum
        from datetime import datetime, time
        from django.utils import timezone

        # Get start and end of the target date
        if hasattr(target_date, 'date'):
            target_date = target_date.date()

        start_of_day = timezone.make_aware(datetime.combine(target_date, time.min))
        end_of_day = timezone.make_aware(datetime.combine(target_date, time.max))

        # Sum quantity_scanned from completed stock take sessions for this product on this date
        result = StockTakeItem.objects.filter(
            session__status=StockTakeSession.Status.COMPLETED,
            session__completed_at__gte=start_of_day,
            session__completed_at__lte=end_of_day,
            product_id=product_id
        ).aggregate(total=Sum('quantity_scanned'))

        return result['total'] or 0

    def refresh_replenished_from_stock_takes(self):
        """
        Refresh quantity_replenished from completed stock take sessions for the reconciliation date.
        This is called when creating or viewing the reconciliation.
        """
        self.quantity_replenished = self.calculate_replenished_from_stock_takes(
            self.product_id,
            self.reconciliation.reconciliation_date
        )

    def clean(self):
        """Validate adjustment values"""
        if self.quantity_added < 0:
            raise ValidationError({'quantity_added': 'Quantity added cannot be negative'})
        if self.quantity_deducted < 0:
            raise ValidationError({'quantity_deducted': 'Quantity deducted cannot be negative'})

    def save(self, *args, **kwargs):
        """Save the adjustment item. Closing stock should be set externally."""
        # Don't auto-calculate closing_stock - it should be set from current product.quantity
        super().save(*args, **kwargs)