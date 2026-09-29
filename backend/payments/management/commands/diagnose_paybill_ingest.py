"""
Paybill ingestion diagnostic — read-only, safe to run in production.

Answers one question: why are paybill transactions missing?

A transaction's gateway comes ONLY from the Device that forwarded the SMS.
`process_raw_message` assigns `gateway=message.device.gateway` and discards
the parser's `gateway_type` verdict entirely, so the fault always sits at one
of five points. This command discriminates between them:

  1. Paybill SMS never became a RawMessage
       -> forwarder isn't sending, or the paybill device never registered
  2. Paybill SMS arrived but failed to parse
       -> `re.match` anchoring in parsers.parse_mpesa_sms
  3. Paybill SMS parsed but was booked to the wrong gateway
       -> the paybill device is bound to a Till gateway
  4. Paybill SMS booked correctly but the report reads a different gateway
       -> duplicate paybill gateways; get_parent_paybill_gateway() fallback
         picks the alphabetically-first name, and the entrypoint seeds a
         placeholder "Paybill Parent Company" with gateway_number
         'PAYBILL_NUMBER' on every boot
  5. Everything is consistent — the Paybill figure is correct, and the
     problem is display-side (filters, wrong branch, date range)

Usage:
    python manage.py diagnose_paybill_ingest
    python manage.py diagnose_paybill_ingest --days 30
    python manage.py diagnose_paybill_ingest --show-text
    python manage.py diagnose_paybill_ingest --max-samples 20

Read-only: performs no writes of any kind. Safe on production.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from payments.models import Device, PaymentGateway, RawMessage, Transaction
from payments.parsers import parse_mpesa_sms
from payments.services.reconciliation_v2_service import ReconciliationV2Service
from payments.tasks import INTERNAL_SENDER_NUMBER, MIN_PARSE_CONFIDENCE

# gateway_number values seeded by create_default_gateways, never a real number.
KNOWN_PLACEHOLDER_NUMBERS = {
    "PAYBILL_NUMBER",
    "TILL_PRODUCTS",
    "TILL_MERCHANDISE",
    "PDQ_TERMINAL",
}

# Substring that identifies an M-Pesa Paybill confirmation as opposed to a
# Till receipt. Used to tell "did a paybill SMS ever arrive" from
# "did a paybill transaction ever get booked".
PAYBILL_MARKER = "Account Number"


def _is_placeholder(gateway: PaymentGateway) -> bool:
    if gateway.gateway_number in KNOWN_PLACEHOLDER_NUMBERS:
        return True
    # Catch other never-filled-in seeds: all-caps, underscored, no digits run.
    number = (gateway.gateway_number or "").strip()
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]{3,}", number))


def _looks_internal(parsed: dict) -> bool:
    sender_phone = str(parsed.get("sender_phone") or "")
    sender_name = str(parsed.get("sender_name") or "")
    if sender_phone == INTERNAL_SENDER_NUMBER or sender_name == INTERNAL_SENDER_NUMBER:
        return True
    # The org pattern prefixes the number onto the name: "7974481 - BF SUMA..."
    return sender_name.startswith(f"{INTERNAL_SENDER_NUMBER} -")


class Command(BaseCommand):
    help = "Diagnose why M-Pesa Paybill transactions are missing (read-only)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=14,
            help="Look back this many days (default: 14)",
        )
        parser.add_argument(
            "--show-text",
            action="store_true",
            help="Print the full raw text of sampled messages",
        )
        parser.add_argument(
            "--max-samples",
            type=int,
            default=10,
            help="How many example messages to print per section (default: 10)",
        )

    def handle(self, *args, **options):
        self.days = options["days"]
        self.show_text = options["show_text"]
        self.max_samples = options["max_samples"]
        self.since = timezone.now() - timedelta(days=self.days)
        self.findings: list[tuple[str, str]] = []

        self._rule("=" * 78)
        self._rule(f"PAYBILL INGEST DIAGNOSTIC — {self.days} day window")
        self._rule("=" * 78)
        self.stdout.write(
            f"  Branch name (settings.BRANCH_NAME): {getattr(settings, 'BRANCH_NAME', '(unset)')!r}\n"
        )

        self._section_config()
        self._section_gateways()
        self._section_devices()
        self._section_volume()
        self._section_timeline()
        self._section_replay()
        self._section_verdict()

    # ------------------------------------------------------------------
    # sections
    # ------------------------------------------------------------------

    def _section_config(self):
        self._rule("1. RELAY CONFIGURATION")
        relay_types = getattr(
            settings, "PAYMENT_RELAY_GATEWAY_TYPES", ["MPESA_TILL", "MERCHANDISE"]
        )
        targets = getattr(settings, "PAYMENT_RELAY_TARGETS", [])
        has_secret = bool(getattr(settings, "PAYMENT_RELAY_SECRET", ""))

        self.stdout.write(f"  PAYMENT_RELAY_GATEWAY_TYPES = {relay_types}")
        self.stdout.write(f"  PAYMENT_RELAY_TARGETS       = {len(targets)} target(s)")
        self.stdout.write(
            f"  PAYMENT_RELAY_SECRET        = {'set' if has_secret else 'NOT SET'}"
        )

        if PaymentGateway.GatewayType.MPESA_PAYBILL in relay_types:
            self._ok("Paybill is in the shared/relayed set.")
        else:
            self._warn(
                "Paybill is NOT relayed. Fine for per-branch paybill numbers, "
                "but if every branch must see all paybill payments this is the bug."
            )
        self.stdout.write("")

    def _section_gateways(self):
        self._rule("2. PAYBILL GATEWAYS")
        gateways = list(
            PaymentGateway.objects.filter(
                gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL
            ).order_by("name")
        )
        if not gateways:
            self._fail("No MPESA_PAYBILL gateway exists on this branch.")
            self._warn(
                "Run `manage.py create_default_gateways`, then set the real "
                "paybill number and is_parent_company=True on it."
            )
            self.stdout.write("")
            return

        for gw in gateways:
            flags = []
            if _is_placeholder(gw):
                flags.append("PLACEHOLDER NUMBER")
            if not gw.is_active:
                flags.append("INACTIVE")
            if not gw.is_parent_company:
                flags.append("is_parent_company=False")
            suffix = f"   <-- {', '.join(flags)}" if flags else ""
            self.stdout.write(
                f"  id={gw.id}  name={gw.name!r}  number={gw.gateway_number!r}"
                f"  active={gw.is_active}  parent={gw.is_parent_company}{suffix}"
            )

        placeholders = [g for g in gateways if _is_placeholder(g)]
        if placeholders:
            self._warn(
                f"{len(placeholders)} placeholder gateway(s) present. "
                "The entrypoint re-seeds these on every boot, and "
                "get_parent_paybill_gateway() falls back to the "
                "alphabetically-first name, so a placeholder can win."
            )

        resolved = ReconciliationV2Service.get_parent_paybill_gateway()
        if resolved is None:
            self._fail(
                "get_parent_paybill_gateway() resolved to None — every "
                "reconciliation reads 0.00 for Mpesa_Paybill."
            )
        else:
            self._ok(
                f"get_parent_paybill_gateway() resolves to {resolved.name!r} "
                f"(number={resolved.gateway_number!r})"
            )
            if _is_placeholder(resolved):
                self._fail(
                    "It resolved to a PLACEHOLDER gateway. No transactions are "
                    "ever booked here, so the Paybill figure is 0.00 even "
                    "though the money arrived on the real gateway. Set "
                    "is_parent_company=True on the real paybill gateway."
                )

        booked_ids = set(
            Transaction.objects.values_list("gateway_id", flat=True).distinct()
        )
        empty = [g for g in gateways if g.id not in booked_ids]
        if empty:
            self._warn(
                "Gateway(s) with ZERO transactions ever: "
                + ", ".join(f"{g.name!r}({g.gateway_number!r})" for g in empty)
            )
        self.stdout.write("")

    def _section_devices(self):
        self._rule("3. DEVICE -> GATEWAY BINDINGS")
        devices = list(Device.objects.select_related("gateway").order_by("name"))
        if not devices:
            self._fail("No devices registered.")
            self.stdout.write("")
            return

        for dev in devices:
            gw = dev.gateway
            recent = RawMessage.objects.filter(
                device=dev, created_at__gte=self.since
            ).count()
            paybill_seen = RawMessage.objects.filter(
                device=dev, raw_text__icontains=PAYBILL_MARKER, created_at__gte=self.since
            ).count()
            note = ""
            if paybill_seen and gw and gw.gateway_type != PaymentGateway.GatewayType.MPESA_PAYBILL:
                note = f"   <-- {paybill_seen} paybill SMS booked to a {gw.gateway_type} gateway!"
            self.stdout.write(
                f"  {dev.name!r:34} -> {(gw.gateway_type if gw else 'NONE'):14} "
                f"{(gw.gateway_number if gw else ''):20} "
                f"msgs/14d={recent:4}  paybill/14d={paybill_seen:4}{note}"
            )

        paybill_devices = [
            d
            for d in devices
            if d.gateway
            and d.gateway.gateway_type == PaymentGateway.GatewayType.MPESA_PAYBILL
            and not d.name.startswith("Relay - ")
        ]
        if not paybill_devices:
            self._fail(
                "No non-relay device is bound to an MPESA_PAYBILL gateway. "
                "Either the paybill device was never registered on this "
                "branch API (DeviceRegisterView does a branch-local "
                "gateway_id lookup and 400s on a foreign UUID), or it is "
                "bound to the wrong gateway."
            )
        self.stdout.write("")

    def _section_volume(self):
        self._rule("4. TRANSACTION VOLUME BY GATEWAY TYPE")
        rows = (
            Transaction.objects.filter(created_at__gte=self.since)
            .values("gateway_type", "gateway__name")
            .annotate(n=Count("id"))
            .order_by("-n")
        )
        if not rows:
            self._warn(f"No transactions created in the last {self.days} days at all.")
        for row in rows:
            self.stdout.write(
                f"  {row['gateway_type'] or '(none)':16} {row['gateway__name'] or '-':30} n={row['n']}"
            )

        paybill_n = sum(
            r["n"] for r in rows if r["gateway_type"] == PaymentGateway.GatewayType.MPESA_PAYBILL
        )
        self.stdout.write("")
        if paybill_n == 0:
            self._fail("Zero paybill-gateway transactions in the window.")
        else:
            self._ok(f"{paybill_n} paybill-gateway transaction(s) in the window.")
        self.stdout.write("")

    def _section_timeline(self):
        self._rule("5. TIMELINE GAP (the decisive check)")
        last_txn = (
            Transaction.objects.filter(
                gateway__gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL
            )
            .order_by("-created_at")
            .first()
        )
        last_paybill_msg = (
            RawMessage.objects.filter(raw_text__icontains=PAYBILL_MARKER)
            .order_by("-created_at")
            .first()
        )
        last_any_msg = RawMessage.objects.order_by("-created_at").first()

        self._line("last paybill-gateway Transaction", last_txn)
        self._line(f"last raw message containing {PAYBILL_MARKER!r}", last_paybill_msg)
        self._line("last raw message of any kind", last_any_msg)

        if last_txn is None:
            if last_paybill_msg is None:
                self._fail(
                    "No paybill SMS has EVER been received. The fault is "
                    "UPSTREAM of the backend: the forwarder is not sending, "
                    "or the paybill device never registered against this API. "
                    "Check section 3 and the Android app's send filters."
                )
            else:
                self._fail(
                    "Paybill SMS IS arriving but NO paybill transaction exists. "
                    "The fault is between ingestion and booking: parsing "
                    "(section 6), the internal-sender filter, or the paybill "
                    "device being bound to the wrong gateway (section 3)."
                )
        else:
            self._ok(f"Paybill transactions exist; newest at {last_txn.created_at}.")
            if last_paybill_msg and last_paybill_msg.created_at > last_txn.created_at:
                self._warn(
                    f"Paybill SMS kept arriving for "
                    f"{(last_paybill_msg.created_at - last_txn.created_at).days}d "
                    "after the last paybill transaction was booked. Something "
                    "stopped booking them partway through — compare the two "
                    "timestamps to find the change."
                )
        self.stdout.write("")

    def _section_replay(self):
        self._rule("6. PARSER REPLAY — parsed intent vs booked gateway")
        messages = list(
            RawMessage.objects.filter(created_at__gte=self.since)
            .select_related("device__gateway")
            .order_by("-created_at")[:500]
        )
        if not messages:
            self._warn("No raw messages in the window to replay.")
            self.stdout.write("")
            return

        counts: Counter = Counter()
        mismatch_samples = []
        unparsed_samples = []
        internal_samples = []

        for msg in messages:
            text = msg.raw_text or ""
            parsed = parse_mpesa_sms(text)
            confidence = parsed.get("confidence", 0) if parsed else 0
            intent = parsed.get("gateway_type") or "UNPARSED"
            booked = msg.device.gateway.gateway_type if msg.device and msg.device.gateway else None

            if confidence <= MIN_PARSE_CONFIDENCE:
                counts["unparsed"] += 1
                if len(unparsed_samples) < self.max_samples:
                    unparsed_samples.append((msg, text, confidence))
                continue
            if _looks_internal(parsed):
                counts["internal_filtered"] += 1
                if len(internal_samples) < self.max_samples:
                    internal_samples.append((msg, text))
                continue
            counts["parsed"] += 1
            if intent != booked:
                counts["mismatch"] += 1
                if len(mismatch_samples) < self.max_samples:
                    mismatch_samples.append((msg, text, intent, booked))

        self.stdout.write(f"  replayed {len(messages)} message(s) (newest 500 max)")
        self.stdout.write(f"    parsed OK              : {counts['parsed']}")
        self.stdout.write(f"    FAILED TO PARSE        : {counts['unparsed']}")
        self.stdout.write(f"    internal sender dropped: {counts['internal_filtered']}")
        self.stdout.write(f"    intent != booked gw    : {counts['mismatch']}")

        if counts["unparsed"]:
            self._fail(
                f"{counts['unparsed']} message(s) did not parse. parse_mpesa_sms "
                "uses re.match (anchored to position 0) with no strip and no "
                "re.search fallback, so leading whitespace or a prefix kills "
                "every pattern."
            )
            self._dump("   samples that failed to parse", unparsed_samples)
        if counts["mismatch"]:
            self._warn(
                f"{counts['mismatch']} message(s) parsed as one gateway type "
                "but were booked to another. The parser verdict is discarded "
                "by process_raw_message; the device binding decides."
            )
            for msg, text, intent, booked in mismatch_samples:
                self.stdout.write(
                    f"     id={str(msg.id)[:8]} parsed={intent:8} booked={booked} "
                    f"dev={msg.device.name!r}"
                )
                self._maybe_text(text)
        if counts["internal_filtered"]:
            self._warn(
                f"{counts['internal_filtered']} message(s) dropped by the "
                f"{INTERNAL_SENDER_NUMBER} internal-sender filter. Confirm these "
                "are genuinely internal before dismissing."
            )
            self._dump("   internal-filtered samples", internal_samples)
        if not (counts["unparsed"] or counts["mismatch"] or counts["internal_filtered"]):
            self._ok("Parser replay is clean: every message parsed and matched its device gateway.")
        self.stdout.write("")

    def _section_verdict(self):
        self._rule("7. VERDICT")
        if not self.findings:
            self._ok("No paybill-specific problems detected on this branch.")
        for level, message in self.findings:
            prefix = {"ok": "  [PASS] ", "warn": "  [WARN] ", "fail": "  [FAIL] "}[level]
            for i, line in enumerate(_wrap(message, 68)):
                self.stdout.write(f"{prefix if i == 0 else '        '}{line}")
        self._rule("=" * 78)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _rule(self, text=""):
        self.stdout.write(self.style.MIGRATE_HEADING(text))

    def _ok(self, msg):
        self.findings.append(("ok", msg))
        self.stdout.write(self.style.SUCCESS(f"  [PASS] {msg}"))

    def _warn(self, msg):
        self.findings.append(("warn", msg))
        self.stdout.write(self.style.WARNING(f"  [WARN] {msg}"))

    def _fail(self, msg):
        self.findings.append(("fail", msg))
        self.stdout.write(self.style.ERROR(f"  [FAIL] {msg}"))

    def _line(self, label, obj):
        if obj is None:
            self.stdout.write(f"  {label:52}: (none)")
        else:
            self.stdout.write(f"  {label:52}: {obj.created_at}")

    def _maybe_text(self, text):
        if self.show_text:
            self.stdout.write(f"             {text!r}")

    def _dump(self, header, samples):
        self.stdout.write(header)
        for entry in samples:
            msg, text = entry[0], entry[1]
            self.stdout.write(f"     id={str(msg.id)[:8]} dev={msg.device.name!r} {text!r}")


def _wrap(text, width):
    import textwrap

    return textwrap.wrap(text, width) or [""]
