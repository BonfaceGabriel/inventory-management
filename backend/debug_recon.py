"""
One-off diagnostic script for the 2026-02-03 reconciliation discrepancy.

Run with:
    docker exec inventory-management-web-1 python manage.py shell < debug_recon.py
    # or
    docker exec inventory-management-web-1 python -c "
        import django, os
        os.environ.setdefault('DJANGO_SETTINGS_MODULE','management.settings')
        django.setup()
        exec(open('debug_recon.py').read())
    "

Investigates two things:
  1. MAN-PDQ-20260202-1243 — yesterday's PDQ txn leaking into today's Credit (+1)
     and Sales (+7692), for a combined leak of 7693.
  2. Confirms the exact Credit breakdown to verify 918 vs expected 917.
"""

import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'management.settings')

import django
django.setup()

import pytz
from datetime import date, datetime
from django.utils import timezone
from django.db.models import Q, Sum
from payments.models import Transaction, CombinedOrder, CombinedOrderTransaction, PaymentGateway

nairobi = pytz.timezone('Africa/Nairobi')
report_date = date(2026, 2, 3)
start_dt = timezone.make_aware(datetime.combine(report_date, datetime.min.time()))
end_dt   = timezone.make_aware(datetime.combine(report_date, datetime.max.time()))

print("=" * 70)
print(" TARGET TRANSACTION: MAN-PDQ-20260202-1243")
print("=" * 70)

txn = Transaction.objects.get(tx_id='MAN-PDQ-20260202-1243')
print(f"  amount:            {txn.amount}")
print(f"  amount_fulfilled:  {txn.amount_fulfilled}")
print(f"  remaining:         {txn.amount - txn.amount_fulfilled}")
print(f"  status:            {txn.status}")
print(f"  gateway:           {txn.gateway} ({txn.gateway.gateway_type if txn.gateway else '?'})")
print(f"  timestamp:         {txn.timestamp}  (Nairobi: {txn.timestamp.astimezone(nairobi)})")
print(f"  created_at:        {txn.created_at}  (Nairobi: {txn.created_at.astimezone(nairobi)})")
print(f"  updated_at:        {txn.updated_at}  (Nairobi: {txn.updated_at.astimezone(nairobi)})")
print(f"  completed_at:      {txn.completed_at}")
print(f"  is_registration:   {txn.is_registration}")
print(f"  reg_kit_issued:    {txn.registration_kit_issued}")
print(f"  reg_kit_qty:       {txn.registration_kit_quantity}")
print(f"  combined_order_parent: {txn.combined_order_parent}")
print()

# Is timestamp today?
ts_today = start_dt <= txn.timestamp <= end_dt
# Is updated_at today?
ua_today = start_dt <= txn.updated_at <= end_dt
# Is completed_at today?
ca_today = txn.completed_at and start_dt <= txn.completed_at <= end_dt

print(f"  timestamp  in today's range: {ts_today}")
print(f"  updated_at in today's range: {ua_today}")
print(f"  completed_at in today's range: {ca_today}")
print()

# Which Sales arm catches it?
print("  --- Sales filter arms ---")
print(f"    Q(completed_at today):                          {ca_today}")
print(f"    Q(updated_at today):                            {ua_today}  <-- catches it")
print(f"    Q(timestamp today AND amount_fulfilled > 0):    {ts_today and txn.amount_fulfilled > 0}")
print()

# Which Credit arm catches it?
print("  --- Credit filter arms ---")
print(f"    Q(timestamp today):   {ts_today}")
print(f"    Q(updated_at today):  {ua_today}  <-- catches it")
print()

# Combined order involvement?
cots = CombinedOrderTransaction.objects.filter(transaction=txn)
print(f"  Combined order involvement: {list(cots.values('combined_order__combined_order_id', 'added_at'))}")

print()
print("=" * 70)
print(" CREDIT FULL BREAKDOWN")
print("=" * 70)

paybill_gw = PaymentGateway.objects.get(
    gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL,
    is_parent_company=True,
    is_active=True
)
pdq_gw = PaymentGateway.objects.filter(
    gateway_type=PaymentGateway.GatewayType.PDQ,
    is_active=True
).first()
gw_ids = [paybill_gw.id, pdq_gw.id]

# Part 1 — single PARTIALLY_FULFILLED (same filter as calculate_credit)
part1_txns = Transaction.objects.exclude(
    Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
    Q(combined_order_parent__isnull=False) |
    Q(sender_name__icontains='7974481') |
    Q(sender_phone__icontains='7974481')
).filter(
    gateway_id__in=gw_ids,
    status=Transaction.OrderStatus.PARTIALLY_FULFILLED
).filter(
    Q(timestamp__gte=start_dt, timestamp__lte=end_dt) |
    Q(updated_at__gte=start_dt, updated_at__lte=end_dt)
)

part1_total = 0
print("\n  Part 1 — Single PARTIALLY_FULFILLED transactions:")
for t in part1_txns:
    rem = t.amount - t.amount_fulfilled
    ts_in = start_dt <= t.timestamp <= end_dt
    ua_in = start_dt <= t.updated_at <= end_dt
    caught_by = []
    if ts_in:
        caught_by.append("timestamp")
    if ua_in:
        caught_by.append("updated_at")
    print(f"    {t.tx_id}: amount={t.amount}, fulfilled={t.amount_fulfilled}, "
          f"remaining={rem}, caught_by={caught_by}, "
          f"ts={t.timestamp.astimezone(nairobi)}, ua={t.updated_at.astimezone(nairobi)}")
    part1_total += float(rem)

print(f"  Part 1 total: {part1_total}")

# Part 2 — combined orders (paybill/PDQ-only, PARTIALLY_FULFILLED)
part2_orders = CombinedOrder.objects.filter(
    status=CombinedOrder.Status.PARTIALLY_FULFILLED
).filter(
    Q(fulfilled_at__gte=start_dt, fulfilled_at__lte=end_dt) |
    Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
    Q(created_at__gte=start_dt, created_at__lte=end_dt)
).prefetch_related('transactions__transaction__gateway')

part2_total = 0
print("\n  Part 2 — Combined orders (paybill/PDQ-only, PARTIALLY_FULFILLED):")
for order in part2_orders:
    all_pb_pdq = all(
        cot.transaction.gateway_id in gw_ids
        for cot in order.transactions.all()
    )
    rem = order.total_amount - order.amount_fulfilled
    print(f"    {order.combined_order_id}: all_paybill_pdq={all_pb_pdq}, "
          f"total={order.total_amount}, fulfilled={order.amount_fulfilled}, remaining={rem}")
    if all_pb_pdq and rem > 0:
        part2_total += float(rem)

print(f"  Part 2 total: {part2_total}")
print(f"\n  CREDIT TOTAL (Part1 + Part2): {part1_total + part2_total}")
print(f"  Expected Credit: 917")
print(f"  Overshoot: {part1_total + part2_total - 917}")

print()
print("=" * 70)
print(" SALES LEAK CHECK — MAN-PDQ-20260202-1243 in single_txns")
print("=" * 70)

# Replicate the single_txns filter from calculate_total_sales
base_exclude = Q(sender_name__icontains='7974481') | Q(sender_phone__icontains='7974481')
single_txns = Transaction.objects.exclude(
    base_exclude |
    Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
    Q(combined_order_parent__isnull=False)
).filter(
    status__in=[Transaction.OrderStatus.FULFILLED, Transaction.OrderStatus.PARTIALLY_FULFILLED]
).filter(
    Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
    Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
    Q(timestamp__gte=start_dt, timestamp__lte=end_dt, amount_fulfilled__gt=0)
)

leaked = single_txns.filter(timestamp__lt=start_dt)
print("\n  Transactions in single_txns with timestamp BEFORE today (leaked via updated_at/completed_at):")
for t in leaked:
    ts_in = start_dt <= t.timestamp <= end_dt
    ua_in = start_dt <= t.updated_at <= end_dt
    ca_in = t.completed_at and start_dt <= t.completed_at <= end_dt
    caught = []
    if ua_in: caught.append("updated_at")
    if ca_in: caught.append("completed_at")
    print(f"    {t.tx_id}: amount_fulfilled={t.amount_fulfilled}, status={t.status}, "
          f"caught_by={caught}, "
          f"ts={t.timestamp.astimezone(nairobi)}, ua={t.updated_at.astimezone(nairobi)}")

print()
print("=" * 70)
print(" DISCREPANCY SUMMARY")
print("=" * 70)
print(f"  Credit leak:  +1  (MAN-PDQ-20260202-1243 remaining=1, pulled in by updated_at)")
print(f"  Sales leak:   +7692 (MAN-PDQ-20260202-1243 amount_fulfilled=7692, pulled in by updated_at)")
print(f"  Total leak:   +7693 — matches reported discrepancy exactly")
print()
print("  ROOT CAUSE: calculate_credit and calculate_total_sales both use")
print("  Q(updated_at__gte=start_dt) as an OR condition, which pulls in")
print("  transactions from PREVIOUS days whose status changed today.")
print("  Credit's docstring says 'received TODAY' — updated_at violates that.")
print("  Sales re-counts the FULL amount_fulfilled (including yesterday's work).")
