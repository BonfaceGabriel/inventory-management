"""Read-only receipt aggregates for a single deployed branch.

Revenue is money received on Paybill, PDQ and Till, dated by receipt time.
Real combined-order child receipts count; synthetic parents do not. Cancelling
an order does not imply a refund. Merchandise-gateway receipts are outside this
metric; merchandise paid on PDQ/Till remains money received on those gateways.
Amounts cross the API as decimal strings, never floats.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import ClassVar
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.text import slugify

from payments.models import PaymentGateway, Transaction


class AgentRevenueService:
    TIMEZONE = ZoneInfo("Africa/Nairobi")
    GATEWAYS: ClassVar[dict[str, str]] = {
        PaymentGateway.GatewayType.MPESA_PAYBILL: "paybill",
        PaymentGateway.GatewayType.PDQ: "pdq",
        PaymentGateway.GatewayType.MPESA_TILL: "till",
    }

    @staticmethod
    def _empty_totals():
        return {
            **{name: Decimal("0.00") for name in AgentRevenueService.GATEWAYS.values()},
            "transaction_count": 0,
        }

    @staticmethod
    def _serialize(totals):
        result = {
            name: format(totals[name].quantize(Decimal("0.01")), ".2f")
            for name in AgentRevenueService.GATEWAYS.values()
        }
        result["total_revenue"] = format(
            sum(totals[name] for name in AgentRevenueService.GATEWAYS.values()), ".2f"
        )
        result["transaction_count"] = totals["transaction_count"]
        return result

    @staticmethod
    def get_revenue(start_date, end_date):
        start = datetime.combine(
            start_date, time.min, tzinfo=AgentRevenueService.TIMEZONE
        )
        stop = datetime.combine(
            end_date + timedelta(days=1), time.min, tzinfo=AgentRevenueService.TIMEZONE
        )

        # Match ingest's exact internal identity; a substring can also occur
        # within a legitimate customer's phone number.
        internal = (
            Q(sender_phone="7974481")
            | Q(sender_name="7974481")
            | Q(sender_name__startswith="7974481 -")
        )
        receipts = Transaction.objects.filter(
            timestamp__gte=start,
            timestamp__lt=stop,
            gateway__gateway_type__in=AgentRevenueService.GATEWAYS,
            combined_order_parent__isnull=True,
        ).exclude(internal)

        rows = (
            receipts.annotate(
                day=TruncDate("timestamp", tzinfo=AgentRevenueService.TIMEZONE),
            )
            .values("day", "gateway__gateway_type")
            .annotate(
                amount=Sum("amount"),
                count=Count("id"),
            )
            .order_by("day", "gateway__gateway_type")
        )

        daily = {
            start_date + timedelta(days=offset): AgentRevenueService._empty_totals()
            for offset in range((end_date - start_date).days + 1)
        }
        totals = AgentRevenueService._empty_totals()
        for row in rows:
            gateway = AgentRevenueService.GATEWAYS[row["gateway__gateway_type"]]
            daily[row["day"]][gateway] += row["amount"]
            daily[row["day"]]["transaction_count"] += row["count"]
            totals[gateway] += row["amount"]
            totals["transaction_count"] += row["count"]

        now = timezone.now()
        return {
            "schema_version": 1,
            "branch": {
                "id": slugify(settings.BRANCH_NAME),
                "name": settings.BRANCH_NAME,
            },
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "timezone": "Africa/Nairobi",
            "currency": "KES",
            "generated_at": now.isoformat(),
            "is_provisional": end_date
            == now.astimezone(AgentRevenueService.TIMEZONE).date(),
            "totals": AgentRevenueService._serialize(totals),
            "daily": [
                {"date": day.isoformat(), **AgentRevenueService._serialize(amounts)}
                for day, amounts in daily.items()
            ],
        }
