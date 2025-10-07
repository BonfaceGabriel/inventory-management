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

    def __str__(self):
        return f"Message for {self.device.name} at {self.received_at}"

    def clean(self):
        super().clean()
        # Strip control characters from raw_text
        self.raw_text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', self.raw_text)