from datetime import datetime, time, timedelta

from payments.models import InventoryMovement, Transaction
from payments.services.agent_sales_service import AgentSalesService
from payments.services.reconciliation_v2_service import REGISTRATION_KIT_VALUE


# Each issuance path writes one stock movement. Combined-order copies do not
# write a second issuance movement, so the original date and quantity survive.
ISSUANCE_REFERENCES = (
    "Registration Kit Issued for Transaction ",
    "Registration from partial ",
    "Registration ",
)


def get_registrations(start_date, end_date):
    zone = AgentSalesService.TIMEZONE
    start = datetime.combine(start_date, time.min, tzinfo=zone)
    stop = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone)
    movements = InventoryMovement.objects.filter(
        reference__startswith="Registration ", product__prod_code="REG_KIT_001",
        movement_type=InventoryMovement.MovementType.SALE, quantity_change__lt=0,
        created_at__gte=start, created_at__lt=stop,
    ).values_list("reference", "quantity_change")
    quantities = {}
    for reference, change in movements:
        prefix = next(prefix for prefix in ISSUANCE_REFERENCES if reference.startswith(prefix))
        tx_id = reference[len(prefix):]
        quantities[tx_id] = quantities.get(tx_id, 0) - change
    registered = Transaction.objects.filter(
        tx_id__in=quantities, is_registration=True,
    ).values_list("tx_id", flat=True)
    issued = [quantities[tx_id] for tx_id in registered]
    count = sum(issued)
    return {
        **AgentSalesService._report(start_date, end_date),
        "registration_transactions": len(issued),
        "kits_issued": count,
        "margin_per_kit": format(REGISTRATION_KIT_VALUE, ".2f"),
        "registration_margin": format(count * REGISTRATION_KIT_VALUE, ".2f"),
    }
