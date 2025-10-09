import uuid
from django.db import models
from django.core.validators import MaxLengthValidator
from django.core.exceptions import ValidationError
import re
from django.utils import timezone
from decimal import Decimal

class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    default_gateway = models.CharField(max_length=50)
    gateway_number = models.CharField(max_length=50)
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
    gateway_type = models.CharField(max_length=50)
    destination_number = models.CharField(max_length=50, blank=True)
    confidence = models.FloatField(default=0)
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.NOT_PROCESSED,
        db_index=True
    )
    amount_expected = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    unique_hash = models.CharField(max_length=64, unique=True, db_index=True)
    duplicate_of = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Transaction {self.tx_id} of {self.amount}"

    @property
    def remaining_amount(self):
        """
        Calculate how much of the payment is still available.
        Returns the difference between expected and paid amounts.
        """
        return self.amount_expected - self.amount_paid

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

        # Validate amount_paid doesn't exceed amount_expected
        if self.amount_paid > self.amount_expected:
            raise ValidationError({
                'amount_paid': f'Amount paid ({self.amount_paid}) cannot exceed amount expected ({self.amount_expected})'
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

        # Auto-fulfill when amount is fully paid
        if self.amount_paid >= self.amount_expected:
            if self.status in [self.OrderStatus.PROCESSING, self.OrderStatus.PARTIALLY_FULFILLED]:
                self.status = self.OrderStatus.FULFILLED

        # Auto-mark as partially fulfilled if amount is partially used
        elif self.amount_paid > Decimal('0.00'):
            if self.status == self.OrderStatus.PROCESSING:
                self.status = self.OrderStatus.PARTIALLY_FULFILLED

        super().save(*args, **kwargs)