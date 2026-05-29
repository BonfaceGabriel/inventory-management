from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from payments.models import (
    CombinedOrderLineItem,
    MerchandiseOrderLine,
    Product,
    Transaction,
    TransactionLineItem,
)
from payments.services.merchandise_service import MerchandiseService


class AnalyticsService:
    @staticmethod
    def _bucket_label(value_dt, granularity: str) -> str:
        if granularity == "month":
            return value_dt.strftime("%Y-%m")
        if granularity == "week":
            iso = value_dt.isocalendar()
            return f"{iso.year}-W{iso.week:02d}"
        return value_dt.isoformat()

    @staticmethod
    def parse_date_range(start_date_str: str | None, end_date_str: str | None):
        today = timezone.localdate()
        default_start = today - timedelta(days=29)

        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        else:
            start_date = default_start

        if end_date_str:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        else:
            end_date = today

        if end_date < start_date:
            start_date, end_date = end_date, start_date

        return start_date, end_date

    @staticmethod
    def _base_transactions_queryset(start_date, end_date):
        start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
        return Transaction.objects.exclude(
            Q(sender_name__icontains='7974481')
            | Q(sender_phone__icontains='7974481')
            | Q(combined_order_parent__isnull=False)
        ).filter(timestamp__gte=start_dt, timestamp__lte=end_dt)

    @staticmethod
    def _gateway_label(txn: Transaction):
        if txn.gateway and MerchandiseService.is_merchandise_gateway(txn.gateway):
            return "MERCH"
        if txn.gateway:
            return txn.gateway.gateway_type
        return "UNKNOWN"

    @classmethod
    def revenue_analytics(cls, start_date, end_date, granularity: str = "day"):
        queryset = cls._base_transactions_queryset(start_date, end_date).select_related("gateway")

        timeline_map = {}
        gateway_share = {}
        total_revenue = Decimal("0.00")
        total_transactions = 0

        for txn in queryset:
            bucket = cls._bucket_label(txn.timestamp.date(), granularity)
            label = cls._gateway_label(txn)
            amount = txn.amount or Decimal("0.00")

            total_revenue += amount
            total_transactions += 1

            if bucket not in timeline_map:
                timeline_map[bucket] = {
                    "date": bucket,
                    "total": 0.0,
                    "MPESA_TILL": 0.0,
                    "MPESA_PAYBILL": 0.0,
                    "PDQ": 0.0,
                    "MERCH": 0.0,
                    "OTHER": 0.0,
                    "UNKNOWN": 0.0,
                }

            timeline_map[bucket][label] = float(timeline_map[bucket].get(label, 0.0) + float(amount))
            timeline_map[bucket]["total"] += float(amount)
            gateway_share[label] = float(gateway_share.get(label, 0.0) + float(amount))

        timeline = [timeline_map[key] for key in sorted(timeline_map.keys())]
        gateway_share_chart = [
            {"gateway": key, "value": value}
            for key, value in sorted(gateway_share.items(), key=lambda item: item[1], reverse=True)
        ]

        return {
            "summary": {
                "total_revenue": float(total_revenue),
                "total_transactions": total_transactions,
                "average_transaction_value": float(total_revenue / total_transactions) if total_transactions else 0.0,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "granularity": granularity,
            },
            "timeline": timeline,
            "gateway_share": gateway_share_chart,
        }

    @classmethod
    def product_analytics(cls, start_date, end_date):
        start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))

        direct_items = TransactionLineItem.objects.filter(
            scanned_at__gte=start_dt,
            scanned_at__lte=end_dt,
            is_inventory_deducted=True,
        ).exclude(transaction__status=Transaction.OrderStatus.COMBINED_FULFILLED)

        combined_items = CombinedOrderLineItem.objects.filter(
            scanned_at__gte=start_dt,
            scanned_at__lte=end_dt,
            is_inventory_deducted=True,
        )

        product_sales = {}

        for item in direct_items.select_related("product"):
            pid = item.product_id
            if pid not in product_sales:
                product_sales[pid] = {
                    "product_id": pid,
                    "product_name": item.product.prod_name,
                    "product_code": item.product.prod_code,
                    "product_line": item.product.product_line.name if item.product.product_line else "Unassigned",
                    "quantity": 0,
                    "revenue": 0.0,
                }
            product_sales[pid]["quantity"] += int(item.quantity or 0)
            product_sales[pid]["revenue"] += float(item.line_total or 0)

        for item in combined_items.select_related("product"):
            pid = item.product_id
            if pid not in product_sales:
                product_sales[pid] = {
                    "product_id": pid,
                    "product_name": item.product.prod_name,
                    "product_code": item.product.prod_code,
                    "product_line": item.product.product_line.name if item.product.product_line else "Unassigned",
                    "quantity": 0,
                    "revenue": 0.0,
                }
            product_sales[pid]["quantity"] += int(item.quantity or 0)
            product_sales[pid]["revenue"] += float(item.line_total or 0)

        all_products = list(Product.objects.filter(is_active=True).select_related("product_line"))
        for product in all_products:
            if product.id not in product_sales:
                product_sales[product.id] = {
                    "product_id": product.id,
                    "product_name": product.prod_name,
                    "product_code": product.prod_code,
                    "product_line": product.product_line.name if product.product_line else "Unassigned",
                    "quantity": 0,
                    "revenue": 0.0,
                }

        ranked = sorted(product_sales.values(), key=lambda x: (x["quantity"], x["revenue"]), reverse=True)
        fast_moving = ranked[:10]
        slow_moving = sorted(product_sales.values(), key=lambda x: (x["quantity"], x["revenue"]))[:10]

        product_line_map = {}
        for item in product_sales.values():
            line = item["product_line"]
            if line not in product_line_map:
                product_line_map[line] = {"product_line": line, "quantity": 0, "revenue": 0.0}
            product_line_map[line]["quantity"] += item["quantity"]
            product_line_map[line]["revenue"] += item["revenue"]

        product_line_contribution = sorted(product_line_map.values(), key=lambda x: x["revenue"], reverse=True)

        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "fast_moving_products": fast_moving,
            "slow_moving_products": slow_moving,
            "product_line_contribution": product_line_contribution,
        }

    @classmethod
    def merchandise_analytics(cls, start_date, end_date):
        start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))

        fulfilled_lines = MerchandiseOrderLine.objects.filter(
            order__status='FULFILLED',
            order__fulfilled_at__gte=start_dt,
            order__fulfilled_at__lte=end_dt,
        ).select_related("item", "order")

        timeline = (
            fulfilled_lines
            .annotate(report_date=TruncDate("order__fulfilled_at"))
            .values("report_date")
            .annotate(
                quantity=Coalesce(Sum("quantity"), Value(0)),
                revenue=Coalesce(Sum("line_total"), Value(Decimal("0.00"))),
            )
            .order_by("report_date")
        )

        timeline_data = [
            {
                "date": row["report_date"].isoformat(),
                "quantity": int(row["quantity"] or 0),
                "revenue": float(row["revenue"] or 0),
            }
            for row in timeline
        ]

        item_map = {}
        size_color_map = {}
        for line in fulfilled_lines:
            code = line.item.code
            if code not in item_map:
                item_map[code] = {
                    "item_code": code,
                    "item_name": line.item.name,
                    "item_type": line.item.item_type,
                    "quantity": 0,
                    "revenue": 0.0,
                }
            item_map[code]["quantity"] += int(line.quantity or 0)
            item_map[code]["revenue"] += float(line.line_total or 0)

            key = f"{line.item.name}::{line.color or '-'}::{line.size or '-'}"
            if key not in size_color_map:
                size_color_map[key] = {
                    "item_name": line.item.name,
                    "color": line.color or "-",
                    "size": line.size or "-",
                    "quantity": 0,
                    "revenue": 0.0,
                }
            size_color_map[key]["quantity"] += int(line.quantity or 0)
            size_color_map[key]["revenue"] += float(line.line_total or 0)

        top_items = sorted(item_map.values(), key=lambda x: x["revenue"], reverse=True)[:10]
        size_color_mix = sorted(size_color_map.values(), key=lambda x: x["quantity"], reverse=True)[:20]

        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "timeline": timeline_data,
            "top_items": top_items,
            "size_color_mix": size_color_mix,
        }
