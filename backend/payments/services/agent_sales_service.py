"""Read-only fulfilled sales, grouped by period rather than payment gateway."""

from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Max, Min, Q
from django.utils import timezone
from django.utils.text import slugify

from payments.models import (
    CombinedOrder, CombinedOrderLineItem, InventoryMovement, PaymentGateway, Transaction, TransactionLineItem,
)


class IncompleteFulfillmentHistory(Exception):
    """A cumulative amount cannot be assigned to just the requested dates."""


class AgentSalesService:
    TIMEZONE = ZoneInfo("Africa/Nairobi")

    @staticmethod
    def _transactions(start, stop, sale_references):
        transaction_ids = {
            reference.split(" ", 1)[1]
            for reference in sale_references
            if reference.startswith(("Transaction ", "Registration "))
        }
        return Transaction.objects.filter(
            Q(completed_at__gte=start, completed_at__lt=stop) | Q(tx_id__in=transaction_ids),
            status__in=(
                Transaction.OrderStatus.FULFILLED,
                Transaction.OrderStatus.PARTIALLY_FULFILLED,
                Transaction.OrderStatus.COMBINED_FULFILLED,
            ),
            combined_order_parent__isnull=True,
            merchandise_order__isnull=True,
        ).exclude(gateway__gateway_type=PaymentGateway.GatewayType.MERCHANDISE)

    @staticmethod
    def _combined_orders(start, stop, sale_references):
        prefix = "Combined Order "
        order_ids = {reference[len(prefix):] for reference in sale_references if reference.startswith(prefix)}
        return CombinedOrder.objects.filter(
            Q(fulfilled_at__gte=start, fulfilled_at__lt=stop) | Q(combined_order_id__in=order_ids),
            status__in=(
                CombinedOrder.Status.IN_PROGRESS,
                CombinedOrder.Status.PARTIALLY_FULFILLED,
                CombinedOrder.Status.FULFILLED,
            ),
        )

    @staticmethod
    def _completed_fulfillment(start_date, end_date):
        zone = AgentSalesService.TIMEZONE
        start = datetime.combine(start_date, time.min, tzinfo=zone)
        stop = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone)

        movements = InventoryMovement.objects.filter(movement_type=InventoryMovement.MovementType.SALE)
        sale_references = set(
            movements.filter(created_at__gte=start, created_at__lt=stop)
            .order_by().values_list("reference", flat=True).distinct()
        )

        completed = []
        for transaction in AgentSalesService._transactions(start, stop, sale_references):
            amount = transaction.amount_fulfilled
            if transaction.is_in_issuance:
                amount = transaction.amount_fulfilled_before_activation
            if amount is None:
                raise IncompleteFulfillmentHistory
            if amount > 0:
                completed.append((
                    transaction, amount, transaction.completed_at,
                    (f"Transaction {transaction.tx_id}", f"Registration {transaction.tx_id}"),
                ))

        for order in AgentSalesService._combined_orders(start, stop, sale_references):
            amount = order.amount_fulfilled
            if order.status == CombinedOrder.Status.IN_PROGRESS:
                amount = order.amount_fulfilled_before_activation
            if amount is None:
                raise IncompleteFulfillmentHistory
            # The children retain the value they fulfilled before combining.
            added = amount - order.base_amount_fulfilled
            if added > 0:
                completed.append((order, added, order.fulfilled_at, (f"Combined Order {order.combined_order_id}",)))

        references = {reference for _, _, _, group in completed for reference in group}
        bounds = {
            row["reference"]: (row["first"], row["last"])
            for row in movements.filter(reference__in=references).order_by().values("reference").annotate(
                first=Min("created_at"), last=Max("created_at")
            )
        }

        for source, amount, completed_at, group in completed:
            dates = [stamp for reference in group for stamp in bounds.get(reference, ())]
            if completed_at is not None:
                dates.append(completed_at)
            # A current balance can be assigned only when all known completions
            # for that source lie within the requested period.
            if not dates or min(dates) < start or max(dates) >= stop:
                raise IncompleteFulfillmentHistory
            yield source, amount, min(dates).astimezone(zone).date(), max(dates).astimezone(zone).date()

    @staticmethod
    def _report(start_date, end_date):
        now = timezone.now()
        return {
            "schema_version": 1,
            "branch": {"id": slugify(settings.BRANCH_NAME), "name": settings.BRANCH_NAME},
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "timezone": "Africa/Nairobi",
            "currency": "KES",
            "generated_at": now.isoformat(),
            "is_provisional": end_date == now.astimezone(AgentSalesService.TIMEZONE).date(),
        }

    @staticmethod
    def get_sales(start_date, end_date, *, daily=False):
        rows = AgentSalesService._completed_fulfillment(start_date, end_date)
        total = Decimal("0.00")
        days = defaultdict(Decimal)
        for _, amount, first, last in rows:
            total += amount
            if daily:
                if first != last:
                    raise IncompleteFulfillmentHistory
                days[first] += amount
        report = {**AgentSalesService._report(start_date, end_date), "total_sales": format(total, ".2f")}
        if daily:
            requested_days = (start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1))
            report["daily"] = [
                {"date": day.isoformat(), "total_sales": format(days[day], ".2f")}
                for day in requested_days
            ]
        return report

    @staticmethod
    def get_products(start_date, end_date):
        direct, combined = {}, {}
        for source, amount, _, _ in AgentSalesService._completed_fulfillment(start_date, end_date):
            (direct if isinstance(source, Transaction) else combined)[source.pk] = amount

        products = {}
        for items, expected in (
            (TransactionLineItem.objects.filter(transaction_id__in=direct), direct),
            (CombinedOrderLineItem.objects.filter(combined_order_id__in=combined, copied_from_transaction__isnull=True), combined),
        ):
            sums = defaultdict(Decimal)
            for item in items.filter(is_inventory_deducted=True).select_related("product"):
                key = item.transaction_id if isinstance(item, TransactionLineItem) else item.combined_order_id
                sums[key] += item.line_total
                product = products.setdefault(item.product_id, {
                    "name": item.product.prod_name, "code": item.product.prod_code,
                    "units_sold": 0, "sales_value": Decimal("0.00"),
                })
                product["units_sold"] += item.quantity
                product["sales_value"] += item.line_total
            if any(sums[key] != amount for key, amount in expected.items()):
                raise IncompleteFulfillmentHistory

        ranked = sorted(products.values(), key=lambda item: (-item["units_sold"], -item["sales_value"], item["code"]))
        return {
            **AgentSalesService._report(start_date, end_date),
            "products": [{**item, "sales_value": format(item["sales_value"], ".2f")} for item in ranked[:10]],
        }
