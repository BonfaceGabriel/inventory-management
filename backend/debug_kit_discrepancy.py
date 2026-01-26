#!/usr/bin/env python
"""
Debug script to find the missing kit in reconciliation.

Run with: docker exec inventory-management-web-1 python debug_kit_discrepancy.py
"""

import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'management.settings')
django.setup()

from decimal import Decimal
from datetime import date, datetime, timedelta
from django.db.models import Sum, Q
from django.utils import timezone
from payments.models import Transaction, PaymentGateway, CombinedOrder, CombinedOrderTransaction
from payments.services.reconciliation_v2_service import ReconciliationV2Service


def debug_kits(report_date=None):
    if report_date is None:
        report_date = date.today()

    print(f"\n{'='*80}")
    print(f"KIT DISCREPANCY DEBUG FOR {report_date}")
    print(f"{'='*80}")

    start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)
    print(f"\nDate range: {start_dt} to {end_dt}")

    # Base exclusions
    base_exclude = Q(sender_name__icontains='7974481') | Q(sender_phone__icontains='7974481')

    # Find ALL transactions with kits issued today (any status)
    print(f"\n{'='*80}")
    print("ALL TRANSACTIONS WITH KITS ISSUED (any status)")
    print(f"{'='*80}")

    all_kit_txns = Transaction.objects.exclude(base_exclude).filter(
        is_registration=True,
        registration_kit_issued=True
    ).filter(
        Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
        Q(timestamp__gte=start_dt, timestamp__lte=end_dt)
    )

    total_kits_all = 0
    for txn in all_kit_txns:
        qty = txn.registration_kit_quantity or 1
        total_kits_all += qty

        # Check if this is a combined order parent
        is_parent = hasattr(txn, 'combined_order_parent') and txn.combined_order_parent is not None

        print(f"\n{txn.tx_id}:")
        print(f"  Status: {txn.status}")
        print(f"  Amount: {txn.amount}")
        print(f"  Gateway: {txn.gateway}")
        print(f"  Kit quantity: {qty}")
        print(f"  is_registration: {txn.is_registration}")
        print(f"  registration_kit_issued: {txn.registration_kit_issued}")
        print(f"  Is combined order parent: {is_parent}")
        print(f"  timestamp: {txn.timestamp}")
        print(f"  updated_at: {txn.updated_at}")
        print(f"  completed_at: {txn.completed_at}")

        # If COMBINED_FULFILLED, find the parent
        if txn.status == Transaction.OrderStatus.COMBINED_FULFILLED:
            cot = CombinedOrderTransaction.objects.filter(transaction=txn).first()
            if cot:
                print(f"  >> PART OF COMBINED ORDER: {cot.combined_order.combined_order_id}")
                parent = cot.combined_order.parent_transaction
                if parent:
                    print(f"     Parent TX: {parent.tx_id}")
                    print(f"     Parent is_registration: {parent.is_registration}")
                    print(f"     Parent registration_kit_issued: {parent.registration_kit_issued}")
                    print(f"     Parent kit_quantity: {parent.registration_kit_quantity}")

    print(f"\n{'='*80}")
    print(f"TOTAL KITS (all statuses): {total_kits_all}")
    print(f"{'='*80}")

    # Now check what the reconciliation service counts
    print(f"\n{'='*80}")
    print("WHAT RECONCILIATION SERVICE COUNTS")
    print(f"{'='*80}")

    # Part 1: Single transactions (non-combined)
    single_reg_txns = Transaction.objects.exclude(
        base_exclude |
        Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
        Q(combined_order_parent__isnull=False)
    ).filter(
        is_registration=True,
        registration_kit_issued=True
    ).filter(
        Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
        Q(timestamp__gte=start_dt, timestamp__lte=end_dt)
    )

    single_kits = sum(t.registration_kit_quantity or 1 for t in single_reg_txns)
    print(f"\nPart 1 - Single (non-combined) transactions: {single_kits} kits")
    for txn in single_reg_txns:
        print(f"  {txn.tx_id}: {txn.registration_kit_quantity or 1} kits, status={txn.status}")

    # Part 2: Combined order parents
    combined_parent_reg_txns = Transaction.objects.exclude(base_exclude).filter(
        combined_order_parent__isnull=False,
        is_registration=True,
        registration_kit_issued=True
    ).filter(
        Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
        Q(timestamp__gte=start_dt, timestamp__lte=end_dt)
    )

    combined_parent_kits = sum(t.registration_kit_quantity or 1 for t in combined_parent_reg_txns)
    print(f"\nPart 2 - Combined order PARENTS: {combined_parent_kits} kits")
    for txn in combined_parent_reg_txns:
        print(f"  {txn.tx_id}: {txn.registration_kit_quantity or 1} kits, status={txn.status}")

    # What's being excluded
    print(f"\n{'='*80}")
    print("TRANSACTIONS WITH KITS THAT ARE EXCLUDED")
    print(f"{'='*80}")

    # COMBINED_FULFILLED with kits (excluded from Part 1, not in Part 2)
    combined_fulfilled_with_kits = Transaction.objects.exclude(base_exclude).filter(
        status=Transaction.OrderStatus.COMBINED_FULFILLED,
        is_registration=True,
        registration_kit_issued=True
    ).filter(
        Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
        Q(timestamp__gte=start_dt, timestamp__lte=end_dt)
    )

    excluded_kits = sum(t.registration_kit_quantity or 1 for t in combined_fulfilled_with_kits)
    print(f"\nCOMBINED_FULFILLED transactions with kits: {excluded_kits} kits")
    for txn in combined_fulfilled_with_kits:
        print(f"  {txn.tx_id}: {txn.registration_kit_quantity or 1} kits")

        # Check if parent also has kit
        cot = CombinedOrderTransaction.objects.filter(transaction=txn).first()
        if cot and cot.combined_order.parent_transaction:
            parent = cot.combined_order.parent_transaction
            if parent.is_registration and parent.registration_kit_issued:
                print(f"    >> Parent {parent.tx_id} ALSO has kit - DOUBLE COUNTING risk!")
            else:
                print(f"    >> Parent {parent.tx_id} does NOT have kit - THIS KIT IS MISSING!")

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Total kits found (all statuses): {total_kits_all}")
    print(f"Kits counted by reconciliation: {single_kits + combined_parent_kits}")
    print(f"Kits excluded (COMBINED_FULFILLED children): {excluded_kits}")
    print(f"Discrepancy: {total_kits_all - (single_kits + combined_parent_kits)} kits = {(total_kits_all - (single_kits + combined_parent_kits)) * 200} KES")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        try:
            report_date = date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"Invalid date: {sys.argv[1]}")
            sys.exit(1)
    else:
        report_date = date.today()

    debug_kits(report_date)
