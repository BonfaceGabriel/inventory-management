#!/usr/bin/env python
"""
Debug script to find the credit discrepancy in reconciliation.

Credit = Remaining balance on partially fulfilled paybill transactions

Run with: docker exec inventory-management-web-1 python debug_credit_discrepancy.py
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


def debug_credits(report_date=None):
    if report_date is None:
        report_date = date.today()

    print(f"\n{'='*80}")
    print(f"CREDIT DISCREPANCY DEBUG FOR {report_date}")
    print(f"{'='*80}")

    start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)
    print(f"\nDate range: {start_dt} to {end_dt}")

    paybill_gateway = ReconciliationV2Service.get_parent_paybill_gateway()
    print(f"Paybill gateway: {paybill_gateway.name if paybill_gateway else 'NOT FOUND'}")

    # Base exclusions
    base_exclude = Q(sender_name__icontains='7974481') | Q(sender_phone__icontains='7974481')

    # Find ALL partially fulfilled paybill transactions
    print(f"\n{'='*80}")
    print("ALL PARTIALLY_FULFILLED PAYBILL TRANSACTIONS")
    print(f"{'='*80}")

    all_partial_paybill = Transaction.objects.exclude(base_exclude).filter(
        gateway=paybill_gateway,
        status=Transaction.OrderStatus.PARTIALLY_FULFILLED
    ).exclude(
        Q(combined_order_parent__isnull=False)  # Exclude parent transactions
    )

    print(f"\nTotal PARTIALLY_FULFILLED paybill transactions: {all_partial_paybill.count()}")

    total_credit_all = Decimal('0')
    for txn in all_partial_paybill:
        remaining = txn.amount - txn.amount_fulfilled

        # Check date ranges
        in_timestamp = start_dt <= txn.timestamp <= end_dt if txn.timestamp else False
        in_updated = start_dt <= txn.updated_at <= end_dt if txn.updated_at else False

        # What the service checks
        should_count = in_timestamp or in_updated

        print(f"\n{txn.tx_id}:")
        print(f"  Amount: {txn.amount}")
        print(f"  Fulfilled: {txn.amount_fulfilled}")
        print(f"  REMAINING (Credit): {remaining}")
        print(f"  timestamp: {txn.timestamp}")
        print(f"    In range [{start_dt} to {end_dt}]: {in_timestamp}")
        print(f"  updated_at: {txn.updated_at}")
        print(f"    In range: {in_updated}")
        print(f"  SHOULD COUNT IN CREDIT: {should_count}")

        if should_count:
            total_credit_all += remaining

    print(f"\n{'='*80}")
    print(f"CALCULATED CREDIT (based on date checks): {total_credit_all}")
    print(f"{'='*80}")

    # Now check what the service actually queries
    print(f"\n{'='*80}")
    print("WHAT RECONCILIATION SERVICE QUERIES")
    print(f"{'='*80}")

    # This is the actual query from calculate_credit
    service_query = Transaction.objects.exclude(
        base_exclude |
        Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
        Q(combined_order_parent__isnull=False)
    ).filter(
        gateway=paybill_gateway,
        status=Transaction.OrderStatus.PARTIALLY_FULFILLED
    ).filter(
        Q(timestamp__gte=start_dt, timestamp__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt)
    )

    service_credit = Decimal('0')
    print(f"\nTransactions matched by service query: {service_query.count()}")
    for txn in service_query:
        remaining = txn.amount - txn.amount_fulfilled
        service_credit += remaining
        print(f"  {txn.tx_id}: remaining={remaining}")

    print(f"\nService calculated credit: {service_credit}")

    # Check for combined orders with partial fulfillment (paybill-only)
    print(f"\n{'='*80}")
    print("COMBINED ORDERS - PAYBILL ONLY - PARTIALLY FULFILLED")
    print(f"{'='*80}")

    partial_combined = CombinedOrder.objects.filter(
        status=CombinedOrder.Status.PARTIALLY_FULFILLED
    ).filter(
        Q(fulfilled_at__gte=start_dt, fulfilled_at__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
        Q(created_at__gte=start_dt, created_at__lte=end_dt)
    ).prefetch_related('transactions__transaction__gateway')

    combined_credit = Decimal('0')
    for order in partial_combined:
        # Check if ALL children are paybill
        all_paybill = True
        for cot in order.transactions.all():
            if cot.transaction.gateway_id != paybill_gateway.id:
                all_paybill = False
                break

        remaining = order.total_amount - order.amount_fulfilled

        print(f"\n{order.combined_order_id}:")
        print(f"  Total: {order.total_amount}")
        print(f"  Fulfilled: {order.amount_fulfilled}")
        print(f"  Remaining: {remaining}")
        print(f"  All children paybill: {all_paybill}")
        print(f"  Child transactions:")
        for cot in order.transactions.all():
            print(f"    - {cot.transaction.tx_id}: gateway={cot.transaction.gateway.name if cot.transaction.gateway else 'None'}")

        if all_paybill and remaining > 0:
            combined_credit += remaining
            print(f"  >> SHOULD COUNT IN CREDIT")

    print(f"\nCombined order credit (paybill-only): {combined_credit}")

    # Get official report
    print(f"\n{'='*80}")
    print("OFFICIAL RECONCILIATION REPORT VALUES")
    print(f"{'='*80}")

    report = ReconciliationV2Service.generate_daily_report(report_date)
    credit_data = report['details'].get('credit', {})

    print(f"Credit amount: {credit_data.get('amount', 0)}")
    print(f"Transaction count: {len(credit_data.get('transactions', []))}")
    print(f"Combined order count: {len(credit_data.get('combined_orders', []))}")

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Manual calculation (all partial paybill in date range): {total_credit_all}")
    print(f"Service query result: {service_credit}")
    print(f"Combined orders (paybill-only): {combined_credit}")
    print(f"Official report credit: {credit_data.get('amount', 0)}")

    expected = service_credit + combined_credit
    print(f"\nExpected total (service + combined): {expected}")
    print(f"Discrepancy from report: {expected - Decimal(str(credit_data.get('amount', 0)))}")

    # Look for the 1 KES difference
    print(f"\n{'='*80}")
    print("LOOKING FOR 1 KES DIFFERENCE")
    print(f"{'='*80}")

    # Check all partial transactions for .50 remainders that might round
    for txn in all_partial_paybill:
        remaining = txn.amount - txn.amount_fulfilled
        # Check if remainder has decimals
        if remaining != remaining.quantize(Decimal('1')):
            print(f"\n{txn.tx_id} has decimal remainder: {remaining}")
            print(f"  amount={txn.amount}, fulfilled={txn.amount_fulfilled}")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        try:
            report_date = date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"Invalid date: {sys.argv[1]}")
            sys.exit(1)
    else:
        report_date = date.today()

    debug_credits(report_date)
