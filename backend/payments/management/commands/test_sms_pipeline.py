"""
Test the full SMS pipeline end-to-end: create a RawMessage as if
a device forwarded it, then process synchronously and verify a
Transaction is created.

Usage:
    python manage.py test_sms_pipeline
    python manage.py test_sms_pipeline --sms "TX1ABC Confirmed. on 30/5/26 at 2:30 PM Ksh1,500.00 received from John Doe 254712345678"
"""

import time
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from payments.models import Device, RawMessage, Transaction
from payments.parsers import parse_mpesa_sms
from payments.tasks import process_raw_message


TEST_SMS = (
    "TX1ABC Confirmed. on 30/5/26 at 2:30 PM "
    "Ksh1,500.00 received from John Doe 254712345678"
)


class Command(BaseCommand):
    help = "Create a RawMessage and run it through the full SMS→Transaction pipeline."

    def add_arguments(self, parser):
        parser.add_argument("--sms", type=str, default=TEST_SMS, help="M-PESA SMS text")
        parser.add_argument(
            "--device", type=str, default=None,
            help="Device name to use (default: first device with a gateway)",
        )

    def handle(self, *args, **options):
        sms_text = options["sms"]
        device_name = options["device"]

        self.stdout.write("=" * 72)
        self.stdout.write("  SMS PIPELINE END-TO-END TEST")
        self.stdout.write("=" * 72)

        # 1. Parse test
        self.stdout.write("\n[1] Parse SMS...")
        parsed = parse_mpesa_sms(sms_text)
        if not parsed:
            self.stdout.write(self.style.ERROR("  PARSE FAILED — SMS format not recognized"))
            self.stdout.write(f"  SMS: {sms_text}")
            return
        self.stdout.write(self.style.SUCCESS(f"  tx_id={parsed['tx_id']} amount={parsed['amount']} confidence={parsed['confidence']}"))
        self.stdout.write(f"  sender={parsed.get('sender_name')} phone={parsed.get('sender_phone')}")

        # 2. Find device
        self.stdout.write("\n[2] Find device...")
        devices = Device.objects.select_related("gateway").all()
        if not devices:
            self.stdout.write(self.style.ERROR("  No devices registered. Register one first."))
            return

        device = None
        if device_name:
            device = devices.filter(name__iexact=device_name).first()
        if not device:
            device = devices.filter(gateway__isnull=False).first()
        if not device:
            device = devices.first()

        if not device.gateway:
            self.stdout.write(self.style.ERROR(f"  Device '{device.name}' has no gateway assigned"))
            return
        self.stdout.write(self.style.SUCCESS(f"  Using device: {device.name} → {device.gateway.name} ({device.gateway.gateway_type})"))

        # 3. Create RawMessage
        self.stdout.write("\n[3] Create RawMessage...")
        raw = RawMessage.objects.create(
            device=device,
            raw_text=sms_text,
            received_at=timezone.now(),
        )
        self.stdout.write(self.style.SUCCESS(f"  RawMessage id={raw.id} created, processed={raw.processed}"))

        # 4. Process through Celery (synchronous)
        self.stdout.write("\n[4] Process via Celery task...")
        result = process_raw_message(raw.id)
        raw.refresh_from_db()

        self.stdout.write(f"  Task result: {result}")

        if raw.processed and raw.transaction:
            txn = raw.transaction
            self.stdout.write(self.style.SUCCESS(f"\n  ✓ TRANSACTION CREATED:"))
            self.stdout.write(f"     tx_id:     {txn.tx_id}")
            self.stdout.write(f"     amount:    {txn.amount}")
            self.stdout.write(f"     status:    {txn.status}")
            self.stdout.write(f"     gateway:   {txn.gateway.name if txn.gateway else 'N/A'}")
            self.stdout.write(f"     sender:    {txn.sender_name} ({txn.sender_phone})")
            self.stdout.write(f"     timestamp: {txn.timestamp}")
            self.stdout.write(f"     matched via: {txn.gateway.gateway_type}")
        elif raw.processed and not raw.transaction:
            reason = result.get("reason", "unknown") if isinstance(result, dict) else "unknown"
            self.stdout.write(self.style.WARNING(f"\n  Message processed but NO transaction (reason: {reason})"))
        else:
            self.stdout.write(self.style.ERROR(f"\n  Message STILL UNPROCESSED — Celery worker didn't pick it up"))

        self.stdout.write("\n" + "=" * 72)
        return raw.id
