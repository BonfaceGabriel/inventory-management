"""
Simulate a Till payment arriving and trace through the entire relay pipeline.

Usage:
    python manage.py simulate_till_pipeline
    python manage.py simulate_till_pipeline --live-relay  (actually POSTs to relay targets)
"""

import json
import os
import time
from datetime import datetime
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from payments.models import Device, PaymentGateway, RawMessage, Transaction
from payments.parsers import parse_mpesa_sms
from payments.tasks import process_raw_message, relay_message_to_branches


TEST_SMS = (
    "TX1ABC Confirmed. on 30/5/26 at 2:30 PM "
    "Ksh1,500.00 received from John Doe 254712345678"
)


def _status(ok, label, detail=""):
    icon = "PASS" if ok else "FAIL"
    line = f"  [{icon}] {label}"
    if detail:
        line += f" — {detail}"
    return line


def _mask_url(url):
    if not url:
        return "(not set)"
    parsed = urlparse(url)
    host = parsed.hostname or "?"
    return f"{parsed.scheme}://{host}{parsed.path or ''}"


class Command(BaseCommand):
    help = "Trace through the Till payment relay pipeline to find where it breaks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--live-relay",
            action="store_true",
            help="Actually POST relay data to configured targets (use with caution).",
        )
        parser.add_argument(
            "--sms", type=str, default=TEST_SMS,
            help="M-PESA SMS text to simulate (default: sample Till message).",
        )

    def handle(self, *args, **options):
        live_relay = options["live_relay"]
        sms_text = options["sms"]

        failures = []
        warnings = []

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("=" * 72))
        self.stdout.write(self.style.HTTP_INFO(
            " TILL PAYMENT RELAY PIPELINE SIMULATION"
        ))
        self.stdout.write(self.style.HTTP_INFO("=" * 72))
        self.stdout.write("")
        self.stdout.write(f"  Time    : {timezone.localtime(timezone.now())}")
        self.stdout.write(f"  SMS     : {sms_text[:80]}...")
        self.stdout.write("")

        # ── Step 1: Environment & Settings ──
        self.stdout.write(self.style.MIGRATE_HEADING("1. Relay Environment Variables"))
        relay_targets_raw = os.getenv("PAYMENT_RELAY_TARGETS", "NOT SET")
        relay_secret_raw = os.getenv("PAYMENT_RELAY_SECRET", "NOT SET")
        relay_types_raw = os.getenv("PAYMENT_RELAY_GATEWAY_TYPES", "NOT SET")
        branch_name_raw = os.getenv("BRANCH_NAME", "NOT SET")

        self.stdout.write(f"  PAYMENT_RELAY_TARGETS      = {relay_targets_raw}")
        self.stdout.write(f"  PAYMENT_RELAY_SECRET       = {'***SET***' if relay_secret_raw not in ('', 'NOT SET') else 'NOT SET'}")
        self.stdout.write(f"  PAYMENT_RELAY_GATEWAY_TYPES = {relay_types_raw}")
        self.stdout.write(f"  BRANCH_NAME                = {branch_name_raw}")
        self.stdout.write("")

        # ── Step 2: Django Settings ──
        self.stdout.write(self.style.MIGRATE_HEADING("2. Django Settings"))
        try:
            s_targets = settings.PAYMENT_RELAY_TARGETS
            s_secret = settings.PAYMENT_RELAY_SECRET
            s_types = settings.PAYMENT_RELAY_GATEWAY_TYPES
            s_branch = settings.BRANCH_NAME
        except AttributeError as e:
            self.stdout.write(self.style.ERROR(f"  [FAIL] Settings attribute missing: {e}"))
            failures.append("PAYMENT_RELAY_* settings not found in django.conf.settings")
            self._print_verdict(failures, warnings)
            return

        self.stdout.write(
            f"  PAYMENT_RELAY_TARGETS      = {repr(s_targets)}  "
            f"(type={type(s_targets).__name__}, truthy={bool(s_targets)})"
        )
        self.stdout.write(
            f"  PAYMENT_RELAY_SECRET       = {'***SET***' if s_secret else '(empty)'}  "
            f"(truthy={bool(s_secret)})"
        )
        self.stdout.write(
            f"  PAYMENT_RELAY_GATEWAY_TYPES = {s_types}  "
            f"(type={type(s_types).__name__})"
        )
        self.stdout.write(f"  BRANCH_NAME                = {s_branch}")

        if isinstance(s_targets, list):
            if len(s_targets) == 0:
                self.stdout.write(self.style.WARNING("  [WARN] PAYMENT_RELAY_TARGETS is an EMPTY list — relay will be SKIPPED"))
                warnings.append("PAYMENT_RELAY_TARGETS is an empty list")
            else:
                for t in s_targets:
                    self.stdout.write(f"    → {t.get('name', '?')}: {t.get('url', '?')}")
        else:
            self.stdout.write(self.style.ERROR(
                f"  [FAIL] PAYMENT_RELAY_TARGETS is not a list: {type(s_targets).__name__}"
            ))
            failures.append(f"PAYMENT_RELAY_TARGETS is type {type(s_targets).__name__}, expected list")

        if not s_secret:
            self.stdout.write(self.style.ERROR("  [FAIL] PAYMENT_RELAY_SECRET is empty — relay will be SKIPPED"))
            failures.append("PAYMENT_RELAY_SECRET is empty")

        # Check if settings match env
        try:
            env_targets_parsed = json.loads(os.getenv("PAYMENT_RELAY_TARGETS", "[]"))
            if s_targets != env_targets_parsed:
                self.stdout.write(self.style.WARNING(
                    f"  [WARN] settings.PAYMENT_RELAY_TARGETS differs from env var!"
                ))
                warnings.append("Settings vs env var mismatch for PAYMENT_RELAY_TARGETS")
        except json.JSONDecodeError as e:
            self.stdout.write(self.style.ERROR(
                f"  [FAIL] PAYMENT_RELAY_TARGETS env var is invalid JSON: {e}"
            ))
            failures.append(f"PAYMENT_RELAY_TARGETS env var is invalid JSON: {e}")

        self.stdout.write("")

        # ── Step 3: Database ──
        self.stdout.write(self.style.MIGRATE_HEADING("3. Database Connectivity"))
        try:
            with connection.cursor() as c:
                c.execute("SELECT 1")
                c.fetchone()
            self.stdout.write(_status(True, "PostgreSQL connected"))
        except Exception as e:
            self.stdout.write(_status(False, f"PostgreSQL: {e}"))
            failures.append("Database unreachable")
            self._print_verdict(failures, warnings)
            return
        self.stdout.write("")

        # ── Step 4: Gateways ──
        self.stdout.write(self.style.MIGRATE_HEADING("4. Payment Gateways (Till/Merchandise)"))
        till_gateways = PaymentGateway.objects.filter(
            gateway_type__in=["MPESA_TILL", "MERCHANDISE"],
            is_active=True,
        )
        self.stdout.write(f"  Active Till/Merchandise gateways: {till_gateways.count()}")
        for gw in till_gateways:
            self.stdout.write(f"    • {gw.id}: {gw.name} ({gw.gateway_type})")
        if not till_gateways.exists():
            self.stdout.write(self.style.ERROR("  [FAIL] No active Till or Merchandise gateways"))
            failures.append("No active MPESA_TILL or MERCHANDISE gateways")
        self.stdout.write("")

        # ── Step 5: Devices ──
        self.stdout.write(self.style.MIGRATE_HEADING("5. Devices with Till/Merchandise Gateways"))
        devices = Device.objects.filter(
            gateway__in=till_gateways,
        ).select_related("gateway")
        self.stdout.write(f"  Devices: {devices.count()}")
        for d in devices:
            self.stdout.write(f"    • {d.id}: {d.name} → {d.gateway.name} ({d.gateway.gateway_type})")
        if not devices.exists():
            self.stdout.write(self.style.WARNING("  [WARN] No devices linked to Till/Merchandise gateways"))
            warnings.append("No devices with Till/Merchandise gateways")
        self.stdout.write("")

        # ── Step 6: Parse SMS ──
        self.stdout.write(self.style.MIGRATE_HEADING("6. Parse Test SMS"))
        parsed = parse_mpesa_sms(sms_text)
        if parsed and parsed.get("confidence", 0) > 0.6:
            self.stdout.write(_status(True, f"Parsed (confidence={parsed['confidence']:.2f})"))
            self.stdout.write(f"    tx_id          = {parsed.get('tx_id')}")
            self.stdout.write(f"    amount         = {parsed.get('amount')}")
            self.stdout.write(f"    sender         = {parsed.get('sender_name')} ({parsed.get('sender_phone')})")
            self.stdout.write(f"    gateway_type   = {parsed.get('gateway_type', 'auto-detected')}")
        else:
            self.stdout.write(self.style.WARNING(f"  [WARN] SMS parse confidence low: {parsed.get('confidence', 0) if parsed else 'parse failed'}"))
            warnings.append("Test SMS not parseable — relay check may still pass for real messages")
        self.stdout.write("")

        # ── Step 7: Create Test RawMessage (optional, not persisted) ──
        self.stdout.write(self.style.MIGRATE_HEADING("7. Simulated MessageIngestView.post() Logic"))
        
        # Pick first device with a Till gateway
        test_device = devices.filter(gateway__gateway_type="MPESA_TILL").first()
        if not test_device:
            test_device = devices.filter(gateway__gateway_type="MERCHANDISE").first()
        if not test_device:
            test_device = devices.first()
        
        if test_device:
            self.stdout.write(f"  Using device: {test_device.name} (gateway: {test_device.gateway.name})")
            self.stdout.write(f"  Device gateway type: {test_device.gateway.gateway_type}")
        else:
            self.stdout.write(self.style.ERROR("  [FAIL] No device available for simulation"))
            failures.append("No test device found")
            self._print_verdict(failures, warnings)
            return

        self.stdout.write("")
        self.stdout.write(f"  --- Simulating views.py line 149 check ---")
        self.stdout.write(f"  Code: if getattr(settings, 'PAYMENT_RELAY_TARGETS', None):")

        check_result = getattr(settings, "PAYMENT_RELAY_TARGETS", None)
        self.stdout.write(f"  Result: {repr(check_result)}")
        self.stdout.write(f"  Type: {type(check_result).__name__}")
        self.stdout.write(f"  Truthy: {bool(check_result)}")

        if check_result is None:
            self.stdout.write(self.style.ERROR(
                "  >> BREAKS HERE: getattr returns None — PAYMENT_RELAY_TARGETS "
                "not found in settings!"
            ))
            failures.append("getattr(settings, 'PAYMENT_RELAY_TARGETS', None) returned None")
        elif not check_result:
            self.stdout.write(self.style.WARNING(
                "  >> BREAKS HERE: PAYMENT_RELAY_TARGETS is falsy (empty list or falsy value)"
            ))
            if isinstance(check_result, list) and len(check_result) == 0:
                self.stdout.write(self.style.WARNING(
                    "  >> Root cause: PAYMENT_RELAY_TARGETS is an empty list '[]'. "
                    "Check that the env var is properly set and json.loads() parses it correctly."
                ))
                failures.append("PAYMENT_RELAY_TARGETS is an empty list []")
            warnings.append("PAYMENT_RELAY_TARGETS is falsy — relay will not fire")
        else:
            self.stdout.write(self.style.SUCCESS("  >> PASS: relay check passes, relay task will be queued!"))
        self.stdout.write("")

        # ── Step 8: Simulate relay_message_to_branches ──
        self.stdout.write(self.style.MIGRATE_HEADING("8. Simulated relay_message_to_branches() Logic"))

        if test_device.gateway:
            is_till_type = test_device.gateway.gateway_type in (
                settings.PAYMENT_RELAY_GATEWAY_TYPES
                if hasattr(settings, "PAYMENT_RELAY_GATEWAY_TYPES")
                else ["MPESA_TILL", "MERCHANDISE"]
            )
            self.stdout.write(f"  Gateway type: {test_device.gateway.gateway_type}")
            self.stdout.write(f"  Should relay? {'YES' if is_till_type else 'NO (not in relay_types)'}")
            if not is_till_type:
                self.stdout.write(self.style.ERROR(
                    "  >> BREAKS HERE: gateway type not in PAYMENT_RELAY_GATEWAY_TYPES"
                ))
                failures.append(f"Gateway type {test_device.gateway.gateway_type} not in relay types")

        self.stdout.write("")
        self.stdout.write(f"  PAYMENT_RELAY_TARGETS: {repr(s_targets)}")
        self.stdout.write(f"  PAYMENT_RELAY_SECRET:  {'***SET***' if s_secret else '(empty)'}")

        if s_targets and s_secret and is_till_type:
            self.stdout.write(self.style.SUCCESS("  >> All preconditions met for relay!"))
        else:
            missing = []
            if not s_targets:
                missing.append("PAYMENT_RELAY_TARGETS")
            if not s_secret:
                missing.append("PAYMENT_RELAY_SECRET")
            if not is_till_type:
                missing.append("gateway type in relay list")
            self.stdout.write(self.style.WARNING(f"  >> Missing: {', '.join(missing)}"))
        self.stdout.write("")

        # ── Step 9: Live Relay Test ──
        if live_relay:
            self.stdout.write(self.style.MIGRATE_HEADING("9. Live Relay POST Test"))
            if s_targets and s_secret:
                import requests
                for target in s_targets:
                    url = target.get("url", "").rstrip("/") + "/api/v1/messages/relay/"
                    name = target.get("name", url)
                    self.stdout.write(f"  POST to {name}: {url}")
                    try:
                        resp = requests.post(
                            url,
                            json={
                                "raw_text": sms_text,
                                "received_at": timezone.now().isoformat(),
                                "gateway_type": "MPESA_TILL",
                                "source_branch": s_branch,
                            },
                            headers={"X-Relay-Secret": s_secret},
                            timeout=10,
                        )
                        self.stdout.write(f"    Status: {resp.status_code}")
                        self.stdout.write(f"    Body: {resp.text[:200]}")
                        if resp.status_code in (200, 201, 202):
                            self.stdout.write(self.style.SUCCESS("    OK"))
                        else:
                            self.stdout.write(self.style.ERROR(f"    FAILED (HTTP {resp.status_code})"))
                            failures.append(f"Live relay POST to {name} returned {resp.status_code}")
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"    EXCEPTION: {e}"))
                        failures.append(f"Live relay POST to {name} failed: {e}")
            else:
                self.stdout.write(self.style.WARNING("  Skipping: targets or secret not configured"))
            self.stdout.write("")
        else:
            self.stdout.write(self.style.MIGRATE_HEADING("9. Live Relay POST (skipped, use --live-relay)"))
            self.stdout.write("  Pass --live-relay to actually POST to target branches.")
            self.stdout.write("")

        # ── Verdict ──
        self._print_verdict(failures, warnings)

    def _print_verdict(self, failures, warnings):
        self.stdout.write(self.style.HTTP_INFO("=" * 72))
        self.stdout.write(self.style.HTTP_INFO(" VERDICT"))
        self.stdout.write(self.style.HTTP_INFO("=" * 72))

        if failures:
            self.stdout.write(self.style.ERROR("  Pipeline BROKEN at:"))
            for i, f in enumerate(failures, 1):
                self.stdout.write(self.style.ERROR(f"    {i}. {f}"))
        else:
            self.stdout.write(self.style.SUCCESS("  No failures detected."))

        if warnings:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("  Warnings:"))
            for w in warnings:
                self.stdout.write(self.style.WARNING(f"    • {w}"))

        if not failures:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(
                "  All checks passed! The pipeline should work.\n"
                "  If relay still doesn't fire, check the web container logs\n"
                "  for [TILL_PIPELINE_DEBUG] messages to trace the actual flow."
            ))
        self.stdout.write("")
