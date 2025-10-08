import uuid
from django.db import models
from django.core.validators import MaxLengthValidator
import re
from django.utils import timezone

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