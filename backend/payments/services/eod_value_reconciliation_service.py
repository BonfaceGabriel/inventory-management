from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from payments.models import EndOfDayValueReconciliation, StockAdjustmentItem
from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService


class EndOfDayValueReconciliationService:
    @staticmethod
    def _today():
        return timezone.localdate()

    @staticmethod
    def _decimal(value) -> Decimal:
        if value is None:
            return Decimal("0.00")
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @classmethod
    def _refresh_x_values(cls, reconciliation: EndOfDayValueReconciliation):
        stock_reconciliation = ReconciliationWorkflowService.get_reconciliation_by_date(
            reconciliation.reconciliation_date
        )

        # Ensure today's stock reconciliation context exists so X can always be derived.
        if stock_reconciliation is None and reconciliation.reconciliation_date == cls._today():
            stock_reconciliation = ReconciliationWorkflowService.get_or_create_reconciliation(
                reconciliation_date=reconciliation.reconciliation_date,
                created_by=reconciliation.created_by,
            )

        if stock_reconciliation is None:
            reconciliation.opening_stock_value = Decimal("0.00")
            reconciliation.replenished_value = Decimal("0.00")
            reconciliation.sales_value = Decimal("0.00")
            reconciliation.recalculate()
            return reconciliation

        adjustments = stock_reconciliation.adjustments.select_related("product")

        opening_expr = ExpressionWrapper(
            F("opening_stock") * F("product__cost_price"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
        replenished_expr = ExpressionWrapper(
            F("quantity_replenished") * F("product__cost_price"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )

        totals = adjustments.aggregate(
            opening_total=Coalesce(Sum(opening_expr), Decimal("0.00")),
            replenished_total=Coalesce(Sum(replenished_expr), Decimal("0.00")),
        )

        sales_total = Decimal("0.00")
        for adjustment in adjustments:
            sales_total += adjustment.product.cost_price * Decimal(adjustment.sales or 0)

        reconciliation.opening_stock_value = cls._decimal(totals["opening_total"])
        reconciliation.replenished_value = cls._decimal(totals["replenished_total"])
        reconciliation.sales_value = sales_total
        reconciliation.recalculate()
        return reconciliation

    @classmethod
    def get_or_create_today(cls, user):
        today = cls._today()
        reconciliation, created = EndOfDayValueReconciliation.objects.get_or_create(
            reconciliation_date=today,
            defaults={"created_by": user, "updated_by": user},
        )
        if created and reconciliation.created_by is None:
            reconciliation.created_by = user

        cls._refresh_x_values(reconciliation)
        reconciliation.updated_by = user
        reconciliation.save()
        return reconciliation

    @classmethod
    def update_today_inputs(cls, user, payload):
        reconciliation = cls.get_or_create_today(user)
        if reconciliation.status == EndOfDayValueReconciliation.Status.CONFIRMED:
            raise ValidationError("End-of-day value reconciliation is already confirmed.")
        if reconciliation.reconciliation_date != cls._today():
            raise ValidationError("Only today's value reconciliation can be edited.")

        for field in [
            "stock_value",
            "bk_stock",
            "duplicated",
            "hq_value",
            "kitengela_value",
            "kitui_value",
            "nakuru_value",
        ]:
            if field in payload:
                setattr(reconciliation, field, cls._decimal(payload[field]))

        cls._refresh_x_values(reconciliation)
        reconciliation.updated_by = user
        reconciliation.save()
        return reconciliation

    @classmethod
    def confirm_today(cls, user):
        reconciliation = cls.get_or_create_today(user)
        if reconciliation.status == EndOfDayValueReconciliation.Status.CONFIRMED:
            return reconciliation

        if reconciliation.reconciliation_date != cls._today():
            raise ValidationError("Only today's value reconciliation can be confirmed.")

        if reconciliation.v_value > Decimal("100.00"):
            raise ValidationError("Cannot confirm: V must be less than or equal to 100.")

        reconciliation.status = EndOfDayValueReconciliation.Status.CONFIRMED
        reconciliation.confirmed_by = user
        reconciliation.confirmed_at = timezone.now()
        reconciliation.updated_by = user
        reconciliation.save()
        return reconciliation
