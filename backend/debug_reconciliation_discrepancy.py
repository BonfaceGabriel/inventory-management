#!/usr/bin/env python
"""
Reconciliation Discrepancy Debugger

This script analyzes the reconciliation formula to identify where a discrepancy of 1 (or any amount) is coming from.

Formula:
X = Mpesa_Paybill - Unused + PDQ + Previous - Sales
Y = Till - Credit - KITS

X + Y should = 0

Run with: docker exec inventory-management-web-1 python debug_reconciliation_discrepancy.py
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'management.settings')
django.setup()

from decimal import Decimal
from datetime import date, datetime, timedelta
from django.db.models import Sum, Q
from django.utils import timezone
from payments.models import Transaction, PaymentGateway, CombinedOrder, CombinedOrderTransaction
from payments.services.reconciliation_v2_service import ReconciliationV2Service

# Constants
REGISTRATION_KIT_VALUE = Decimal('200.00')


def print_header(title):
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def print_section(title):
    print(f"\n--- {title} ---")


def analyze_reconciliation(report_date=None):
    """Analyze reconciliation for a given date and identify discrepancies."""

    if report_date is None:
        report_date = date.today()

    print_header(f"RECONCILIATION DISCREPANCY ANALYSIS FOR {report_date}")

    # Get gateways
    paybill_gateway = ReconciliationV2Service.get_parent_paybill_gateway()
    till_gateways = ReconciliationV2Service.get_till_gateways()
    pdq_gateway = ReconciliationV2Service.get_pdq_gateway()

    print_section("GATEWAYS")
    print(f"Paybill Gateway: {paybill_gateway.name if paybill_gateway else 'NOT FOUND'} (ID: {paybill_gateway.id if paybill_gateway else 'N/A'})")
    print(f"Till Gateways: {[g.name for g in till_gateways]}")
    print(f"PDQ Gateway: {pdq_gateway.name if pdq_gateway else 'NOT FOUND'}")

    # Get date range
    start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)
    print(f"\nDate Range: {start_dt} to {end_dt}")

    # Generate official report
    print_section("OFFICIAL RECONCILIATION REPORT")
    report = ReconciliationV2Service.generate_daily_report(report_date)

    x_value = report['x_value']
    y_value = report['y_value']
    result = report['result']

    print(f"X = {x_value}")
    print(f"  Mpesa_Paybill: {report['x_formula']['mpesa_paybill']}")
    print(f"  Unused: {report['x_formula']['unused']}")
    print(f"  PDQ: {report['x_formula']['pdq']}")
    print(f"  Previous: {report['x_formula']['previous']}")
    print(f"  Sales: {report['x_formula']['sales']}")
    print(f"Y = {y_value}")
    print(f"  Till: {report['y_formula']['till']}")
    print(f"  Credit: {report['y_formula']['credit']}")
    print(f"  KITS: {report['y_formula']['kits']}")
    print(f"RESULT (X + Y) = {result}")
    print(f"DISCREPANCY: {abs(result)}" if result != 0 else "BALANCED!")

    if result == 0:
        print("\n✓ Reconciliation is balanced. No discrepancy to investigate.")
        return

    # Now let's dig deeper into each component
    print_header("DETAILED ANALYSIS OF EACH COMPONENT")

    # ========== MPESA PAYBILL ANALYSIS ==========
    print_section("1. MPESA PAYBILL TRANSACTIONS (received today)")
    mpesa_data = report['details'].get('mpesa_paybill', {})
    mpesa_txns = mpesa_data.get('transactions', [])

    print(f"Count: {len(mpesa_txns)}")
    print(f"Total: {mpesa_data.get('amount', 0)}")

    # Get raw transactions for verification
    if paybill_gateway:
        raw_paybill = Transaction.objects.exclude(
            Q(status=Transaction.OrderStatus.CANCELLED) |
            Q(combined_order_parent__isnull=False) |
            Q(sender_name__icontains='7974481') |
            Q(sender_phone__icontains='7974481')
        ).filter(
            gateway=paybill_gateway,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt
        )

        print(f"\nRaw query count: {raw_paybill.count()}")
        raw_sum = raw_paybill.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        print(f"Raw query sum: {raw_sum}")

        if len(mpesa_txns) <= 20:
            print("\nTransactions:")
            for txn in mpesa_txns:
                print(f"  {txn.get('tx_id', 'N/A')}: {txn.get('amount', 0)} - {txn.get('status', 'N/A')} - {txn.get('sender_name', 'N/A')}")

        # Check for edge cases
        print("\nEdge case analysis:")

        # Check for COMBINED_FULFILLED that might be incorrectly included
        combined_fulfilled = Transaction.objects.filter(
            gateway=paybill_gateway,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt,
            status=Transaction.OrderStatus.COMBINED_FULFILLED
        )
        if combined_fulfilled.exists():
            print(f"  COMBINED_FULFILLED transactions (should be excluded): {combined_fulfilled.count()}")
            for txn in combined_fulfilled[:5]:
                print(f"    {txn.tx_id}: {txn.amount}")

        # Check for parent transactions that might be incorrectly included
        parent_txns = Transaction.objects.filter(
            gateway=paybill_gateway,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt,
            combined_order_parent__isnull=False
        )
        if parent_txns.exists():
            print(f"  Parent transactions (should be excluded): {parent_txns.count()}")
            for txn in parent_txns[:5]:
                print(f"    {txn.tx_id}: {txn.amount}")

    # ========== UNUSED ANALYSIS ==========
    print_section("2. UNUSED PAYBILL TRANSACTIONS")
    unused_data = report['details'].get('unused', {})
    print(f"Total: {unused_data.get('amount', 0)}")
    print(f"Count: {unused_data.get('count', 0)}")

    # ========== PDQ ANALYSIS ==========
    print_section("3. PDQ TRANSACTIONS")
    pdq_data = report['details'].get('pdq', {})
    print(f"Total: {pdq_data.get('amount', 0)}")
    print(f"Count: {pdq_data.get('count', 0)}")

    # ========== PREVIOUS ANALYSIS ==========
    print_section("4. PREVIOUS (Paybill from previous days, active today)")
    previous_data = report['details'].get('previous', {})
    print(f"Total: {previous_data.get('amount', 0)}")

    standalone = previous_data.get('standalone_transactions', [])
    combined = previous_data.get('combined_transactions', [])

    print(f"Standalone count: {len(standalone)}")
    print(f"Combined count: {len(combined)}")

    if standalone:
        print("\nStandalone transactions:")
        for txn in standalone[:10]:
            print(f"  {txn.get('tx_id', 'N/A')}: {txn.get('amount', 0)} (fulfilled: {txn.get('amount_fulfilled', 0)})")

    if combined:
        print("\nCombined order transactions:")
        for txn in combined[:10]:
            print(f"  {txn.get('tx_id', 'N/A')}: {txn.get('amount', 0)}")

    # ========== SALES ANALYSIS ==========
    print_section("5. SALES (Total fulfilled today)")
    sales_data = report['details'].get('sales', {})
    print(f"Total (at distributor price): {sales_data.get('amount', 0)}")
    print(f"Total fulfilled (raw): {sales_data.get('total_fulfilled', 0)}")
    print(f"Kit adjustment: {sales_data.get('kit_adjustment', 0)}")
    print(f"Kits issued: {sales_data.get('kits_issued', 0)}")

    by_gateway = sales_data.get('by_gateway', {})
    if by_gateway:
        print("\nBy gateway:")
        for gw_name, gw_data in by_gateway.items():
            print(f"  {gw_name}: {gw_data.get('amount', 0)} ({gw_data.get('count', 0)} txns)")

    # Verify sales calculation
    print("\nVerifying sales calculation:")

    fulfilled_statuses = [
        Transaction.OrderStatus.FULFILLED,
        Transaction.OrderStatus.PARTIALLY_FULFILLED
    ]

    # Single transactions
    single_txns = Transaction.objects.exclude(
        Q(sender_name__icontains='7974481') |
        Q(sender_phone__icontains='7974481') |
        Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
        Q(combined_order_parent__isnull=False)
    ).filter(
        status__in=fulfilled_statuses
    ).filter(
        Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
        Q(timestamp__gte=start_dt, timestamp__lte=end_dt, amount_fulfilled__gt=0)
    )

    single_sum = single_txns.aggregate(total=Sum('amount_fulfilled'))['total'] or Decimal('0')
    print(f"  Single transactions fulfilled: {single_sum} ({single_txns.count()} txns)")

    # Combined order parents
    combined_parents = Transaction.objects.exclude(
        Q(sender_name__icontains='7974481') |
        Q(sender_phone__icontains='7974481')
    ).filter(
        combined_order_parent__isnull=False,
        status__in=fulfilled_statuses
    ).filter(
        Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
        Q(timestamp__gte=start_dt, timestamp__lte=end_dt, amount_fulfilled__gt=0)
    )

    combined_sum = combined_parents.aggregate(total=Sum('amount_fulfilled'))['total'] or Decimal('0')
    print(f"  Combined order parents fulfilled: {combined_sum} ({combined_parents.count()} txns)")

    print(f"  Raw total: {single_sum + combined_sum}")

    # ========== TILL ANALYSIS ==========
    print_section("6. TILL (Amount fulfilled from Till today)")
    till_data = report['details'].get('till', {})
    print(f"Total: {till_data.get('amount', 0)}")

    single_till = till_data.get('single_transactions', {})
    combined_till = till_data.get('combined_orders', {})

    print(f"From single transactions: {single_till.get('amount', 0)} ({single_till.get('count', 0)} txns)")
    print(f"From combined orders: {combined_till.get('amount', 0)} ({combined_till.get('count', 0)} orders)")

    # ========== CREDIT ANALYSIS ==========
    print_section("7. CREDIT (Remaining balance on partial paybill)")
    credit_data = report['details'].get('credit', {})
    print(f"Total: {credit_data.get('amount', 0)}")
    print(f"Transaction count: {len(credit_data.get('transactions', []))}")
    print(f"Combined order count: {len(credit_data.get('combined_orders', []))}")

    credit_txns = credit_data.get('transactions', [])
    if credit_txns:
        print("\nTransactions with remaining balance:")
        for txn in credit_txns[:10]:
            print(f"  {txn.get('tx_id', 'N/A')}: amount={txn.get('amount', 0)}, fulfilled={txn.get('amount_fulfilled', 0)}, remaining={txn.get('remaining', 0)}")

    # ========== KITS ANALYSIS ==========
    print_section("8. KITS (Registration kits issued today * 200)")
    kits_data = report['details'].get('kits', {})
    print(f"Total value: {kits_data.get('amount', 0)}")
    print(f"Kit count: {kits_data.get('count', 0)}")
    print(f"Unit value: {kits_data.get('unit_value', 200)}")

    kits_txns = kits_data.get('transactions', [])
    if kits_txns:
        print("\nRegistration transactions:")
        for txn in kits_txns[:10]:
            print(f"  {txn.get('tx_id', 'N/A')}: {txn.get('registration_kit_quantity', 0)} kits")

    # ========== LOOK FOR THE DISCREPANCY ==========
    print_header("DISCREPANCY HUNTING")

    discrepancy = result
    print(f"Looking for discrepancy of: {discrepancy}")

    # Check for transactions with amount differences
    print_section("Transactions where amount != amount_fulfilled (potential rounding)")

    all_fulfilled = Transaction.objects.filter(
        status__in=fulfilled_statuses
    ).filter(
        Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
        Q(timestamp__gte=start_dt, timestamp__lte=end_dt, amount_fulfilled__gt=0)
    )

    for txn in all_fulfilled:
        diff = txn.amount - txn.amount_fulfilled
        if diff != Decimal('0') and diff != Decimal('0.00'):
            print(f"  {txn.tx_id}: amount={txn.amount}, fulfilled={txn.amount_fulfilled}, diff={diff}, status={txn.status}")

    # Check for decimal precision issues
    print_section("Checking for decimal precision issues")

    # Look for amounts that end in unusual decimal places
    suspicious_amounts = Transaction.objects.filter(
        timestamp__gte=start_dt,
        timestamp__lte=end_dt
    ).exclude(
        Q(amount__endswith='.00') |
        Q(amount__endswith='.0')
    )

    # Since we can't filter by decimal ending in Django, let's iterate
    print("Checking amounts for non-.00 endings...")
    for txn in all_fulfilled[:50]:
        amount_str = str(txn.amount)
        fulfilled_str = str(txn.amount_fulfilled)
        if not amount_str.endswith('.00') and not amount_str.endswith('0'):
            print(f"  Unusual amount: {txn.tx_id} = {txn.amount}")
        if not fulfilled_str.endswith('.00') and not fulfilled_str.endswith('0'):
            print(f"  Unusual fulfilled: {txn.tx_id} = {txn.amount_fulfilled}")

    # Check if any transaction amount matches the discrepancy
    print_section(f"Transactions with amount = {abs(discrepancy)}")

    matching_amount = Transaction.objects.filter(
        amount=abs(Decimal(str(discrepancy))),
        timestamp__gte=start_dt,
        timestamp__lte=end_dt
    )

    for txn in matching_amount:
        print(f"  {txn.tx_id}: {txn.amount} - status: {txn.status} - gateway: {txn.gateway}")

    # Check amount_fulfilled matching discrepancy
    print_section(f"Transactions with amount_fulfilled = {abs(discrepancy)}")

    matching_fulfilled = Transaction.objects.filter(
        amount_fulfilled=abs(Decimal(str(discrepancy)))
    ).filter(
        Q(timestamp__gte=start_dt, timestamp__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt)
    )

    for txn in matching_fulfilled:
        print(f"  {txn.tx_id}: fulfilled={txn.amount_fulfilled} - status: {txn.status} - gateway: {txn.gateway}")

    # Check for registration kit count issues
    print_section("Registration kit verification")

    reg_txns = Transaction.objects.filter(
        is_registration=True,
        registration_kit_issued=True
    ).filter(
        Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
        Q(timestamp__gte=start_dt, timestamp__lte=end_dt)
    )

    total_kits = 0
    for txn in reg_txns:
        qty = txn.registration_kit_quantity or 1
        total_kits += qty
        print(f"  {txn.tx_id}: {qty} kits, gateway: {txn.gateway}, status: {txn.status}")

    print(f"\nTotal kits calculated: {total_kits}")
    print(f"Total kit value: {total_kits * 200}")
    print(f"Report kit value: {kits_data.get('amount', 0)}")

    # Final summary
    print_header("SUMMARY")
    print(f"Discrepancy: {discrepancy}")
    print("\nPossible causes:")
    print("1. A transaction counted in one component but not another")
    print("2. Decimal rounding issues")
    print("3. A transaction that changed status during the day")
    print("4. Combined order allocation issues")
    print("5. Registration kit count mismatch")
    print("\nReview the detailed output above to identify the source.")


if __name__ == '__main__':
    # Parse command line arguments for date
    if len(sys.argv) > 1:
        try:
            report_date = date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"Invalid date format: {sys.argv[1]}. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        report_date = date.today()

    analyze_reconciliation(report_date)
