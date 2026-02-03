"""
Diagnostic script — what touched MAN-PDQ-20260202-1243 today?

Run with:
    docker exec inventory-management-web-1 python manage.py shell < debug_recon.py
"""

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'management.settings')

import django
django.setup()

import pytz
from datetime import date, datetime
from django.utils import timezone
from django.db.models import Q
from payments.models import Transaction, PaymentGateway

nairobi = pytz.timezone('Africa/Nairobi')
report_date = date(2026, 2, 3)
start_dt = timezone.make_aware(datetime.combine(report_date, datetime.min.time()))
end_dt   = timezone.make_aware(datetime.combine(report_date, datetime.max.time()))

# --- Gateway lookup (mirrors the service fallback) ---
paybill_gw = PaymentGateway.objects.filter(
    gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL,
    is_parent_company=True,
    is_active=True
).first()
if not paybill_gw:
    paybill_gw = PaymentGateway.objects.filter(
        gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL,
        is_active=True
    ).first()

pdq_gw = PaymentGateway.objects.filter(
    gateway_type=PaymentGateway.GatewayType.PDQ,
    is_active=True
).first()

print(f"Paybill gateway: {paybill_gw} (id={paybill_gw.id if paybill_gw else None})")
print(f"PDQ gateway:     {pdq_gw} (id={pdq_gw.id if pdq_gw else None})")
gw_ids = [g.id for g in [paybill_gw, pdq_gw] if g]

# ---------------------------------------------------------------------------
print()
print("=" * 70)
print(" TARGET TRANSACTION: MAN-PDQ-20260202-1243")
print("=" * 70)

txn = Transaction.objects.get(tx_id='MAN-PDQ-20260202-1243')

# Dump every concrete field
for field in txn._meta.get_fields():
    if field.is_relation and field.auto_created:
        continue  # skip reverse FK / M2M
    try:
        val = getattr(txn, field.attname if hasattr(field, 'attname') else field.name)
        if hasattr(val, 'astimezone'):
            val = f"{val}  (Nairobi: {val.astimezone(nairobi)})"
        print(f"  {field.name:45s} {val}")
    except Exception as e:
        print(f"  {field.name:45s} <error: {e}>")

# ---------------------------------------------------------------------------
print()
print("=" * 70)
print(" NOTES (system writes appear here with timestamps)")
print("=" * 70)
print(txn.notes if txn.notes else "  <empty>")

# ---------------------------------------------------------------------------
print()
print("=" * 70)
print(" TIMESTAMP GAP ANALYSIS")
print("=" * 70)
print(f"  timestamp:   {txn.timestamp.astimezone(nairobi)}  (payment arrived)")
print(f"  created_at:  {txn.created_at.astimezone(nairobi)}  (record created)")
print(f"  completed_at:{txn.completed_at.astimezone(nairobi) if txn.completed_at else None}  (fulfillment completed)")
print(f"  updated_at:  {txn.updated_at.astimezone(nairobi)}  (last .save()  — auto_now)")
if txn.completed_at:
    print(f"  GAP completed_at->updated_at: {txn.updated_at - txn.completed_at}")
    print(f"  => Something .save()'d this record AFTER fulfillment completed, "
          f"on a different day.")

# ---------------------------------------------------------------------------
print()
print("=" * 70)
print(" OTHER prev-day PARTIALLY_FULFILLED paybill/PDQ with updated_at today")
print("         (same leak pattern — would also pollute Credit & Sales)")
print("=" * 70)

leakers = Transaction.objects.exclude(
    Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
    Q(combined_order_parent__isnull=False)
).filter(
    gateway_id__in=gw_ids,
    status=Transaction.OrderStatus.PARTIALLY_FULFILLED,
    timestamp__lt=start_dt,
    updated_at__gte=start_dt,
    updated_at__lte=end_dt
)

for t in leakers:
    print(f"  {t.tx_id}: amount={t.amount}, fulfilled={t.amount_fulfilled}, "
          f"remaining={t.amount - t.amount_fulfilled}, "
          f"ts={t.timestamp.astimezone(nairobi)}, "
          f"ua={t.updated_at.astimezone(nairobi)}, "
          f"time_locked={t.is_time_locked}, "
          f"reg={t.is_registration}")

if not leakers.exists():
    print("  None — MAN-PDQ-20260202-1243 is the only one.")
