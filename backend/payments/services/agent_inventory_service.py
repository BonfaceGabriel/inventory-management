from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from django.utils.text import slugify

from payments.models import MerchandiseOrder, MerchandiseOrderLine, MerchandiseStock, Product
from payments.services.stock_report_service import StockReportService


class AgentInventoryService:
    TIMEZONE = ZoneInfo("Africa/Nairobi")
    PAGE_SIZE = 8

    @classmethod
    def _report(cls, start_date, end_date, rows, page, now):
        offset = (page - 1) * cls.PAGE_SIZE
        return {
            "schema_version": 1,
            "branch": {"id": slugify(settings.BRANCH_NAME), "name": settings.BRANCH_NAME},
            "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
            "timezone": "Africa/Nairobi", "currency": "KES", "generated_at": now.isoformat(),
            "is_provisional": end_date == now.astimezone(cls.TIMEZONE).date(),
            "page": page, "page_count": max(1, (len(rows) + cls.PAGE_SIZE - 1) // cls.PAGE_SIZE),
            "items": rows[offset:offset + cls.PAGE_SIZE],
        }

    @classmethod
    def _merchandise_lines(cls, start_date, end_date):
        start = datetime.combine(start_date, time.min, tzinfo=cls.TIMEZONE)
        stop = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=cls.TIMEZONE)
        return MerchandiseOrderLine.objects.filter(
            order__status=MerchandiseOrder.Status.FULFILLED,
            order__fulfilled_at__gte=start, order__fulfilled_at__lt=stop,
        )

    @classmethod
    def get_merchandise(cls, start_date, end_date, *, page=1):
        now = timezone.now()
        sold = {
            row["item__code"]: row
            for row in cls._merchandise_lines(start_date, end_date).order_by()
            .values("item__code", "item__name").annotate(units=Sum("quantity"), value=Sum("line_total"))
        }
        stock = {
            row["item__code"]: row
            for row in MerchandiseStock.objects.order_by().values("item__code", "item__name", "item__unit_price")
            .annotate(units=Sum("quantity"))
        }
        rows = []
        for code in sold.keys() | stock.keys():
            sold_item, current = sold.get(code, {}), stock.get(code, {})
            units = current.get("units", 0)
            rows.append({
                "code": code, "name": (sold_item or current)["item__name"],
                "units_sold": sold_item.get("units", 0), "sales_value": format(sold_item.get("value", 0), ".2f"),
                "remaining_units": units, "remaining_catalog_value": format(units * current.get("item__unit_price", 0), ".2f"),
            })
        rows.sort(key=lambda item: (item["name"].casefold(), item["code"]))
        result = cls._report(start_date, end_date, rows, page, now)
        result["total_fulfilled"] = format(sum(row["value"] for row in sold.values()), ".2f")
        if start_date == end_date:
            previous = start_date - timedelta(days=1)
            previous_total = cls._merchandise_lines(previous, previous).aggregate(value=Sum("line_total"))["value"]
            result["previous_day_total"] = format(previous_total or Decimal(0), ".2f")
        return result

    @classmethod
    def get_stock(cls, *, page=1):
        now = timezone.now()
        day = now.astimezone(cls.TIMEZONE).date()
        rows = []
        total = Decimal("0.00")
        for product in Product.objects.filter(is_active=True).order_by("prod_name", "prod_code"):
            total += product.quantity * product.cost_price
            status = StockReportService._get_stock_status(product)
            if status in {"OUT_OF_STOCK", "LOW_STOCK"}:
                rows.append({
                    "code": product.prod_code, "name": product.prod_name,
                    "quantity": product.quantity, "reorder_level": product.reorder_level, "status": status,
                })
        return {
            **cls._report(day, day, rows, page, now),
            "total_stock_value_at_cost": format(total, ".2f"),
            "out_of_stock_count": sum(row["status"] == "OUT_OF_STOCK" for row in rows),
            "low_stock_count": sum(row["status"] == "LOW_STOCK" for row in rows),
        }
