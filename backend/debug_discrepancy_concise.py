#!/usr/bin/env python
"""
Concise Reconciliation Discrepancy Debugger
Shows only essential data needed to trace the discrepancy source.
"""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'management.settings')
django.setup()

from decimal import Decimal
from datetime import date, datetime
from django.db.models import Sum, Q
from django.utils import timezone
from payments.models import Transaction, PaymentGateway, CombinedOrder
from payments.services.reconciliation_v2_service import ReconciliationV2Service

def main(report_date=None):
    if report_date is None:
        report_date = date.today()
    
    print(f"\n{'='*60}")
    print(f"DISCREPANCY TRACE FOR {report_date}")
    print('='*60)
    
    # Get report
    report = ReconciliationV2Service.generate_daily_report(report_date)
    start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)
    paybill_gw = ReconciliationV2Service.get_parent_paybill_gateway()
    
    # 1. FORMULA VALUES
    print("\n[1] FORMULA VALUES")
    print("-"*40)
    x = report['x_formula']
    y = report['y_formula']
    
    print(f"X = Mpesa_Paybill - Unused + PDQ + Previous - Sales")
    print(f"  Mpesa_Paybill: {x['mpesa_paybill']:>12,.2f}")
    print(f"  Unused:        {x['unused']:>12,.2f}")
    print(f"  PDQ:           {x['pdq']:>12,.2f}")
    print(f"  Previous:      {x['previous']:>12,.2f}")
    print(f"  Sales:         {x['sales']:>12,.2f}")
    print(f"  X =            {report['x_value']:>12,.2f}")
    
    print(f"\nY = Till - Credit - KITS")
    print(f"  Till:          {y['till']:>12,.2f}")
    print(f"  Credit:        {y['credit']:>12,.2f}")
    print(f"  KITS:          {y['kits']:>12,.2f}")
    print(f"  Y =            {report['y_value']:>12,.2f}")
    
    print(f"\n>>> RESULT: X + Y = {report['result']:,.2f}")
    
    if report['result'] == 0:
        print("✓ Balanced - no discrepancy")
        return
    
    # 2. VERIFY EACH COMPONENT MANUALLY
    print("\n[2] COMPONENT VERIFICATION")
    print("-"*40)
    
    # Helper filters
    base_exclude = Q(sender_name__icontains='7974481') | Q(sender_phone__icontains='7974481')
    fulfilled_statuses = [Transaction.OrderStatus.FULFILLED, Transaction.OrderStatus.PARTIALLY_FULFILLED]
    
    # 2a. Credit verification
    print("\nCREDIT check (partially fulfilled paybill/PDQ today):")
    
    # What service counts
    credit_svc = Decimal(str(report['details']['credit']['amount']))
    
    # What should be counted: ONLY transactions received today
    pdq_gw = ReconciliationV2Service.get_pdq_gateway()
    gw_ids = [g.id for g in [paybill_gw, pdq_gw] if g]
    
    # Count only received today
    credit_received_today = Transaction.objects.exclude(
        Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
        Q(combined_order_parent__isnull=False) | base_exclude
    ).filter(
        gateway_id__in=gw_ids,
        status=Transaction.OrderStatus.PARTIALLY_FULFILLED,
        timestamp__gte=start_dt, timestamp__lte=end_dt
    )
    credit_strict = sum(t.amount - t.amount_fulfilled for t in credit_received_today)
    
    # Count with updated_at (what service does)
    credit_with_updated = Transaction.objects.exclude(
        Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
        Q(combined_order_parent__isnull=False) | base_exclude
    ).filter(
        gateway_id__in=gw_ids,
        status=Transaction.OrderStatus.PARTIALLY_FULFILLED
    ).filter(
        Q(timestamp__gte=start_dt, timestamp__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt)
    )
    credit_loose = sum(t.amount - t.amount_fulfilled for t in credit_with_updated)
    
    print(f"  Service reports:         {credit_svc:>10,.2f}")
    print(f"  Received today only:     {credit_strict:>10,.2f}")
    print(f"  With updated_at:         {credit_loose:>10,.2f}")
    if credit_loose != credit_strict:
        print(f"  >>> BUG: updated_at adds {credit_loose - credit_strict:,.2f}")
    
    # 2b. Sales verification - key area
    print("\nSALES check:")
    sales_svc = Decimal(str(report['details']['sales']['amount']))
    
    # Single transactions
    single_txns = Transaction.objects.exclude(
        base_exclude | Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
        Q(combined_order_parent__isnull=False)
    ).filter(status__in=fulfilled_statuses).filter(
        Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
        Q(timestamp__gte=start_dt, timestamp__lte=end_dt, amount_fulfilled__gt=0)
    )
    single_sum = single_txns.aggregate(t=Sum('amount_fulfilled'))['t'] or Decimal('0')
    
    # COMBINED_FULFILLED children (potential double-count)
    cmb_children = Transaction.objects.exclude(
        base_exclude | Q(combined_order_parent__isnull=False)
    ).filter(
        status=Transaction.OrderStatus.COMBINED_FULFILLED,
        amount_fulfilled__gt=0
    ).filter(
        Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt)
    )
    cmb_child_sum = cmb_children.aggregate(t=Sum('amount_fulfilled'))['t'] or Decimal('0')
    
    # Combined orders
    combined_orders = CombinedOrder.objects.filter(
        Q(status__in=[CombinedOrder.Status.IN_PROGRESS, CombinedOrder.Status.PARTIALLY_FULFILLED, CombinedOrder.Status.FULFILLED]),
        Q(fulfilled_at__gte=start_dt, fulfilled_at__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
        Q(created_at__gte=start_dt, created_at__lte=end_dt)
    )
    
    cmb_order_today = Decimal('0')
    cmb_order_all = Decimal('0')
    for order in combined_orders:
        cmb_order_all += order.amount_fulfilled
        today = order.amount_fulfilled - order.base_amount_fulfilled
        if today > 0:
            cmb_order_today += today
    
    # Kit adjustment
    kit_count = report['details']['kits']['count']
    kit_adj = Decimal('200') * kit_count
    
    print(f"  Service reports:            {sales_svc:>12,.2f}")
    print(f"  Single txn fulfilled:       {single_sum:>12,.2f}")
    print(f"  COMBINED_FULFILLED children:{cmb_child_sum:>12,.2f}")
    print(f"  Combined orders (today):    {cmb_order_today:>12,.2f}")
    print(f"  Combined orders (all):      {cmb_order_all:>12,.2f}")
    print(f"  Kit adjustment:             {kit_adj:>12,.2f}")
    
    # What service likely calculates
    svc_calc = single_sum + cmb_child_sum + cmb_order_today - kit_adj
    print(f"\n  Expected (single + child + cmb_today - kits): {svc_calc:>12,.2f}")
    print(f"  Difference from service:    {svc_calc - sales_svc:>12,.2f}")
    
    if cmb_child_sum > 0:
        print(f"\n  >>> POTENTIAL BUG: COMBINED_FULFILLED children add {cmb_child_sum:,.2f}")
        print(f"      These may be double-counted if also in combined order fulfillment")
    
    # 2c. Check if cmb_child fulfillment overlaps with combined order fulfillment
    print("\n[3] COMBINED_FULFILLED CHILDREN DETAIL")
    print("-"*40)
    for txn in cmb_children[:5]:
        print(f"  {txn.tx_id}: fulfilled={txn.amount_fulfilled}, timestamp={txn.timestamp.date() if txn.timestamp else 'N/A'}, updated={txn.updated_at.date() if txn.updated_at else 'N/A'}")
    if cmb_children.count() > 5:
        print(f"  ... and {cmb_children.count() - 5} more")
    
    # 3. SUMMARY
    print("\n[4] DISCREPANCY BREAKDOWN HYPOTHESIS")
    print("-"*40)
    
    credit_diff = float(credit_loose - credit_strict)
    cmb_child_double = float(cmb_child_sum)
    cmb_base_issue = float(cmb_order_all - cmb_order_today)
    
    print(f"  Credit over-count (updated_at bug):   {credit_diff:>+12,.2f}")
    print(f"  COMBINED_FULFILLED double-count:      {cmb_child_double:>+12,.2f}")
    print(f"  Combined order base_amount included:  {cmb_base_issue:>+12,.2f}")
    
    total_explained = credit_diff + cmb_child_double
    print(f"\n  Total explained so far: {total_explained:>+12,.2f}")
    print(f"  Actual discrepancy:     {report['result']:>+12,.2f}")
    print(f"  Unexplained:            {report['result'] - total_explained:>+12,.2f}")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        main(date.fromisoformat(sys.argv[1]))
    else:
        main()
