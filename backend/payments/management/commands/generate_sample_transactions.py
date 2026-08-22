"""
Generate raw sample payment receipts for manual fulfillment testing.

Creates exactly 20 NOT_PROCESSED transactions across TODAY and YESTERDAY,
split across Paybill, Till, and PDQ only.

Usage:
    python manage.py generate_sample_transactions
    python manage.py generate_sample_transactions --clear
"""

from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal
import hashlib
from typing import List

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.utils import timezone

from payments.models import (
    CombinedOrder,
    InventoryMovement,
    PaymentGateway,
    Transaction,
)

TX_PREFIX = "SAMPLE"

# 20 rows: (key_suffix, gateway_key, day_offset, hour, amount_kes)
# day_offset: 0 = yesterday, 1 = today
RAW_RECEIPTS = [
    # Yesterday (7)
    ("Y01", "paybill", 0, 9, "5000.00"),
    ("Y02", "paybill", 0, 10, "3000.00"),
    ("Y03", "paybill", 0, 11, "1800.00"),
    ("Y04", "till", 0, 12, "2000.00"),
    ("Y05", "till", 0, 13, "1200.00"),
    ("Y06", "pdq", 0, 14, "1500.00"),
    ("Y07", "pdq", 0, 15, "900.00"),
    # Today (13)
    ("T01", "paybill", 1, 9, "3000.00"),
    ("T02", "paybill", 1, 10, "2500.00"),
    ("T03", "paybill", 1, 11, "4000.00"),
    ("T04", "paybill", 1, 12, "2200.00"),
    ("T05", "paybill", 1, 13, "1800.00"),
    ("T06", "till", 1, 14, "2000.00"),
    ("T07", "till", 1, 15, "3500.00"),
    ("T08", "till", 1, 16, "1100.00"),
    ("T09", "till", 1, 17, "5265.00"),
    ("T10", "pdq", 1, 11, "1500.00"),
    ("T11", "pdq", 1, 13, "1200.00"),
    ("T12", "pdq", 1, 15, "900.00"),
    ("T13", "pdq", 1, 17, "2100.00"),
]


def make_hash(tx_id: str) -> str:
    return hashlib.sha256(tx_id.encode()).hexdigest()[:64]


def aware_dt(day: date, hour: int, minute: int = 0) -> datetime:
    return timezone.make_aware(datetime.combine(day, dt_time(hour, minute, 0)))


@dataclass
class ReceiptSpec:
    key: str
    gateway_key: str
    payment_day: date
    hour: int
    amount: Decimal


class Command(BaseCommand):
    help = (
        "Generate 20 NOT_PROCESSED sample receipts (Paybill, Till, PDQ) "
        "for today and yesterday."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete ALL existing transactions before generating.",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            self._clear_all_transactions()

        gateways = self._resolve_gateways()
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        specs = self._build_specs(today, yesterday)
        if len(specs) != 20:
            raise CommandError(f"Expected 20 receipts, got {len(specs)}.")

        stats = {
            "created": 0,
            "by_day": {str(yesterday): 0, str(today): 0},
            "by_gateway": {"paybill": 0, "till": 0, "pdq": 0},
        }

        with db_transaction.atomic():
            for spec in specs:
                gw = gateways[spec.gateway_key]
                tx_id = f"{TX_PREFIX}-{spec.key}"
                payment_ts = aware_dt(spec.payment_day, spec.hour)

                Transaction.objects.create(
                    tx_id=tx_id,
                    amount=spec.amount,
                    amount_fulfilled=Decimal("0.00"),
                    sender_name="Sample Customer",
                    sender_phone="0712000001",
                    timestamp=payment_ts,
                    gateway=gw,
                    gateway_type=gw.gateway_type,
                    destination_number=gw.gateway_number,
                    status=Transaction.OrderStatus.NOT_PROCESSED,
                    confidence=Decimal("0.99"),
                    unique_hash=make_hash(tx_id),
                    notes=f"[SAMPLE] Raw {spec.gateway_key} receipt — process manually.",
                )
                stats["created"] += 1
                stats["by_day"][str(spec.payment_day)] += 1
                stats["by_gateway"][spec.gateway_key] += 1

        self._print_summary(today, yesterday, stats)

    def _build_specs(self, today: date, yesterday: date) -> List[ReceiptSpec]:
        specs = []
        for key, gateway_key, day_offset, hour, amount in RAW_RECEIPTS:
            payment_day = yesterday if day_offset == 0 else today
            specs.append(
                ReceiptSpec(
                    key=f"{key}-{gateway_key.upper()}",
                    gateway_key=gateway_key,
                    payment_day=payment_day,
                    hour=hour,
                    amount=Decimal(amount),
                )
            )
        return specs

    def _resolve_gateways(self) -> dict:
        paybill = PaymentGateway.objects.filter(
            is_parent_company=True, is_active=True
        ).first()
        if not paybill:
            paybill = (
                PaymentGateway.objects.filter(
                    gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL,
                    is_active=True,
                )
                .order_by("id")
                .first()
            )

        till = (
            PaymentGateway.objects.filter(
                name__icontains="Till Products",
                gateway_type=PaymentGateway.GatewayType.MPESA_TILL,
                is_active=True,
            ).first()
            or PaymentGateway.objects.filter(
                gateway_type=PaymentGateway.GatewayType.MPESA_TILL,
                is_active=True,
            )
            .exclude(gateway_type=PaymentGateway.GatewayType.MERCHANDISE)
            .first()
        )

        pdq = PaymentGateway.objects.filter(
            gateway_type=PaymentGateway.GatewayType.PDQ, is_active=True
        ).first()

        missing = [
            name
            for name, gw in (("paybill", paybill), ("till", till), ("pdq", pdq))
            if gw is None
        ]
        if missing:
            raise CommandError(
                f"Missing gateways: {', '.join(missing)}. Run create_default_gateways first."
            )

        return {"paybill": paybill, "till": till, "pdq": pdq}

    def _clear_all_transactions(self) -> None:
        from payments.models import MerchandiseOrder

        self.stdout.write(self.style.WARNING("Deleting ALL transactions..."))
        tx_count = Transaction.objects.count()
        combined_count = CombinedOrder.objects.count()
        merch_count = MerchandiseOrder.objects.count()
        movement_count = InventoryMovement.objects.filter(
            movement_type=InventoryMovement.MovementType.SALE
        ).count()

        MerchandiseOrder.objects.all().delete()
        CombinedOrder.objects.all().delete()
        Transaction.objects.all().delete()
        InventoryMovement.objects.filter(
            movement_type=InventoryMovement.MovementType.SALE
        ).delete()

        self.stdout.write(
            self.style.WARNING(
                f"Deleted {tx_count} transactions, {combined_count} combined orders, "
                f"{merch_count} merchandise orders, {movement_count} sale movements."
            )
        )

    def _print_summary(self, today: date, yesterday: date, stats: dict) -> None:
        self.stdout.write(self.style.SUCCESS("\n" + "=" * 72))
        self.stdout.write(self.style.SUCCESS("RAW SAMPLE RECEIPTS (20, NOT_PROCESSED)"))
        self.stdout.write(self.style.SUCCESS("=" * 72))
        self.stdout.write(f"  Today:     {today}")
        self.stdout.write(f"  Yesterday: {yesterday}")
        self.stdout.write(f"  Created:   {stats['created']} (all NOT_PROCESSED)")
        self.stdout.write(f"  Yesterday: {stats['by_day'].get(str(yesterday), 0)}")
        self.stdout.write(f"  Today:     {stats['by_day'].get(str(today), 0)}")
        self.stdout.write("  By gateway:")
        self.stdout.write(f"    Paybill: {stats['by_gateway']['paybill']}")
        self.stdout.write(f"    Till:    {stats['by_gateway']['till']}")
        self.stdout.write(f"    PDQ:     {stats['by_gateway']['pdq']}")
        self.stdout.write(self.style.SUCCESS("=" * 72))
        self.stdout.write(
            self.style.SUCCESS(
                "\nActivate and fulfill these manually in the app to test reconciliation."
            )
        )
