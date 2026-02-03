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
from payments.models import Transaction

nairobi = pytz.timezone('Africa/Nairobi')
report_date = date(2026, 2, 3)
start_dt = timezone.make_aware(datetime.combine(report_date, datetime.min.time()))
end_dt   = timezone.make_aware(datetime.combine(report_date, datetime.max.time()))

txn = Transaction.objects.get(tx_id='MAN-PDQ-20260202-1243')

print("=" * 70)
print(" FULL FIELD DUMP: MAN-PDQ-20260202-1243")
print("=" * 70)

# Dump every field on the model
for field in txn._meta.get_fields():
    if field.is_relation and field.auto_created:
        continue  # skip reverse relations
    try:
        val = getattr(txn, field.name)
        if hasattr(val, 'astimezone'):
            val = f"{val}  (Nairobi: {val.astimezone(nairobi)})"
        print(f"  {field.name}: {val}")
    except Exception as e:
        print(f"  {field.name}: <error: {e}>")

print()
print("=" * 70)
print(" NOTES CONTENT (may show system writes)")
print("=" * 70)
print(txn.notes if txn.notes else "  <empty>")

print()
print("=" * 70)
print(" TIME-LOCK STATE")
print("=" * 70)
print(f"  is_time_locked: {txn.is_time_locked}")
print(f"  locked_at:      {txn.locked_at}")
print(f"  locked_by:      {txn.locked_by}")

print()
print("=" * 70)
print(" ACTIVATION STATE")
print("=" * 70)
print(f"  is_locked:                        {txn.is_locked}")
print(f"  locked_at:                        {txn.locked_at}")
print(f"  locked_by:                        {txn.locked_by}")
print(f"  amount_fulfilled_before_activation: {txn.amount_fulfilled_before_activation}")
print(f"  status_before_activation:         {txn.status_before_activation}")

print()
print("=" * 70)
print(" KEY TIMESTAMPS COMPARISON")
print("=" * 70)
print(f"  timestamp:   {txn.timestamp.astimezone(nairobi)}  (when payment arrived)")
print(f"  created_at:  {txn.created_at.astimezone(nairobi)}  (when DB record created)")
print(f"  completed_at:{txn.completed_at.astimezone(nairobi) if txn.completed_at else None}  (when fulfillment completed)")
print(f"  updated_at:  {txn.updated_at.astimezone(nairobi)}  (last .save() — auto_now)")
print()

# The gap: completed_at is yesterday, updated_at is today.
# Something saved this record today WITHOUT completing new fulfillment.
if txn.completed_at:
    print(f"  GAP: completed_at -> updated_at = {txn.updated_at - txn.completed_at}")
    print(f"       completed_at is {txn.completed_at.astimezone(nairobi).date()}, "
          f"updated_at is {txn.updated_at.astimezone(nairobi).date()}")
    print(f"       A .save() happened today that did NOT set completed_at.")

print()
print("=" * 70)
print(" OTHER PARTIALLY_FULFILLED PDQ/PAYBILL TXNS WITH updated_at TODAY")
print("         but timestamp NOT today (same leak pattern)")
print("=" * 70)
from django.db.models import Q
from payments.models import PaymentGateway

paybill_gw = PaymentGateway.objects.get(
    gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL,
    is_parent_company=True, is_active=True
)
pdq_gw = PaymentGateway.objects.filter(
    gateway_type=PaymentGateway.GatewayType.PDQ, is_active=True
).first()
gw_ids = [paybill_gw.id, pdq_gw.id]

leakers = Transaction.objects.exclude(
    Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
    Q(combined_order_parent__isnull=False)
).filter(
    gateway_id__in=gw_ids,
    status=Transaction.OrderStatus.PARTIALLY_FULFILLED,
    timestamp__lt=start_dt,           # received BEFORE today
    updated_at__gte=start_dt,         # but saved today
    updated_at__lte=end_dt
)

for t in leakers:
    print(f"  {t.tx_id}: amount={t.amount}, fulfilled={t.amount_fulfilled}, "
          f"remaining={t.amount - t.amount_fulfilled}, "
          f"ts={t.timestamp.astimezone(nairobi)}, "
          f"ua={t.updated_at.astimezone(nairobi)}, "
          f"locked={t.is_time_locked}, "
          f"reg={t.is_registration}")
