#!/usr/bin/env python
"""
Script to reset and deconstruct multiple combined orders

This script will:
1. Find each combined order and all associated data
2. Reverse any inventory changes from line items that were deducted
3. Restore child transactions to NOT_PROCESSED status
4. Delete the combined order, its line items, and parent transaction

Run with:
    docker exec -it inventory-management-web-1 python manage.py shell < scripts/reset_combined_orders.py

Or in Django shell:
    exec(open('scripts/reset_combined_orders.py').read())
"""

import sys
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

# Import models
from payments.models import (
    CombinedOrder, CombinedOrderTransaction, CombinedOrderLineItem,
    Transaction, TransactionLineItem, Product, InventoryMovement
)

# ============================================================================
# CONFIGURATION
# ============================================================================

COMBINED_ORDER_IDS = [
    'CMB-20260119-103204',
    'CMB-20260119-094648',
    'CMB-20260119-154037',
]

DRY_RUN = True  # Set to False to actually execute changes

# ============================================================================
# SCRIPT
# ============================================================================

print("=" * 80)
print("RESET MULTIPLE COMBINED ORDERS")
print(f"Orders to reset: {len(COMBINED_ORDER_IDS)}")
print(f"DRY RUN: {DRY_RUN}")
print("=" * 80)

def reset_combined_order(combined_order_id, dry_run=True):
    """Reset a single combined order and return summary."""

    print(f"\n{'=' * 80}")
    print(f"PROCESSING: {combined_order_id}")
    print("=" * 80)

    summary = {
        'combined_order_id': combined_order_id,
        'found': False,
        'child_transactions': [],
        'items_reversed': 0,
        'items_deleted': 0,
        'success': False,
        'error': None
    }

    try:
        # Step 1: Find the combined order
        print("\n[STEP 1] Finding combined order...")
        try:
            combined_order = CombinedOrder.objects.get(combined_order_id=combined_order_id)
            summary['found'] = True
            print(f"  Found: {combined_order}")
            print(f"  Status: {combined_order.status}")
            print(f"  Total Amount: {combined_order.total_amount}")
            print(f"  Amount Fulfilled: {combined_order.amount_fulfilled}")
            print(f"  Base Amount Fulfilled: {combined_order.base_amount_fulfilled}")
            print(f"  Created By: {combined_order.created_by}")
            print(f"  Created At: {combined_order.created_at}")
        except CombinedOrder.DoesNotExist:
            print(f"  ERROR: Combined order {combined_order_id} not found!")
            summary['error'] = 'Not found'
            return summary

        # Step 2: Find parent transaction
        print("\n[STEP 2] Finding parent transaction...")
        parent_transaction = combined_order.parent_transaction
        if parent_transaction:
            print(f"  Parent TX ID: {parent_transaction.tx_id}")
            print(f"  Parent Status: {parent_transaction.status}")
            print(f"  Parent Amount: {parent_transaction.amount}")
            print(f"  Parent Amount Fulfilled: {parent_transaction.amount_fulfilled}")
        else:
            print("  No parent transaction found")

        # Step 3: Find linked child transactions
        print("\n[STEP 3] Finding linked child transactions...")
        linked_transactions = CombinedOrderTransaction.objects.filter(
            combined_order=combined_order
        ).select_related('transaction')

        child_txns = []
        for link in linked_transactions:
            txn = link.transaction
            child_txns.append(txn)
            summary['child_transactions'].append(txn.tx_id)
            print(f"  - {txn.tx_id}")
            print(f"      Status: {txn.status}")
            print(f"      Amount: {txn.amount}")
            print(f"      Amount Fulfilled: {txn.amount_fulfilled}")
            print(f"      Is In Issuance: {txn.is_in_issuance}")

            # Check if this transaction had line items before combining
            txn_line_items = TransactionLineItem.objects.filter(transaction=txn)
            if txn_line_items.exists():
                print(f"      Line Items: {txn_line_items.count()}")
                for li in txn_line_items:
                    print(f"        - {li.quantity}x {li.scanned_prod_name} (deducted: {li.is_inventory_deducted})")

        # Step 4: Find combined order line items
        print("\n[STEP 4] Finding combined order line items...")
        co_line_items = CombinedOrderLineItem.objects.filter(
            combined_order=combined_order
        ).select_related('product', 'copied_from_transaction')

        print(f"  Total line items: {co_line_items.count()}")
        summary['items_deleted'] = co_line_items.count()

        items_to_reverse = []  # Items that need inventory reversal
        items_copied = []      # Items copied from child transactions

        for item in co_line_items:
            copied_from = item.copied_from_transaction.tx_id if item.copied_from_transaction else None
            print(f"  - {item.quantity}x {item.scanned_prod_name}")
            print(f"      Price: {item.scanned_price}, Total: {item.line_total}")
            print(f"      Is Inventory Deducted: {item.is_inventory_deducted}")
            print(f"      Copied From Transaction: {copied_from}")

            if item.is_inventory_deducted and not item.copied_from_transaction:
                items_to_reverse.append(item)
                print(f"      >>> NEEDS INVENTORY REVERSAL")
            elif item.copied_from_transaction:
                items_copied.append(item)
                print(f"      >>> Copied item (inventory already handled in original txn)")

        summary['items_reversed'] = len(items_to_reverse)

        # Step 5: Check for inventory movements
        print("\n[STEP 5] Finding related inventory movements...")
        inv_movements = InventoryMovement.objects.filter(
            reference__icontains=combined_order_id
        )
        print(f"  Found {inv_movements.count()} inventory movements")
        for mov in inv_movements:
            print(f"  - {mov.get_movement_type_display()}: {mov.product.prod_name}")
            print(f"      Change: {mov.quantity_change}, Before: {mov.quantity_before}, After: {mov.quantity_after}")

        # Step 6: Summary
        print("\n" + "-" * 40)
        print("CHANGES TO BE MADE:")
        print("-" * 40)
        print(f"  Inventory reversals: {len(items_to_reverse)} items")
        print(f"  Child transactions to restore: {len(child_txns)}")
        print(f"  Combined order line items to delete: {co_line_items.count()}")
        print(f"  Transaction links to delete: {linked_transactions.count()}")

        if dry_run:
            print("\n  [DRY RUN - NO CHANGES MADE]")
            summary['success'] = True
            return summary

        # EXECUTE CHANGES
        print("\n  EXECUTING CHANGES...")

        with transaction.atomic():
            # Step A: Reverse inventory for items scanned directly to combined order
            print("\n  [A] Reversing inventory...")
            for item in items_to_reverse:
                product = Product.objects.select_for_update().get(id=item.product.id)
                quantity_before = product.quantity
                product.quantity += item.quantity
                product.save()

                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.MovementType.RETURN,
                    product=product,
                    quantity_before=quantity_before,
                    quantity_after=product.quantity,
                    quantity_change=item.quantity,
                    reference=f"Reset Combined Order {combined_order_id}",
                    performed_by="System (Reset Script)"
                )
                print(f"    Reversed: {product.prod_name} +{item.quantity} (now: {product.quantity})")

            # Step B: Handle child transactions
            print("\n  [B] Restoring child transactions...")
            for txn in child_txns:
                # Delete any line items that belong to this transaction
                txn_line_items = TransactionLineItem.objects.filter(transaction=txn)

                # For items that were deducted, reverse inventory
                for li in txn_line_items.filter(is_inventory_deducted=True):
                    product = Product.objects.select_for_update().get(id=li.product.id)
                    quantity_before = product.quantity
                    product.quantity += li.quantity
                    product.save()

                    InventoryMovement.objects.create(
                        movement_type=InventoryMovement.MovementType.RETURN,
                        product=product,
                        quantity_before=quantity_before,
                        quantity_after=product.quantity,
                        quantity_change=li.quantity,
                        reference=f"Reset Transaction {txn.tx_id} (from {combined_order_id})",
                        performed_by="System (Reset Script)"
                    )
                    print(f"    Reversed from {txn.tx_id}: {product.prod_name} +{li.quantity}")

                # Delete all line items for this transaction
                deleted_count = txn_line_items.delete()[0]
                if deleted_count:
                    print(f"    Deleted {deleted_count} line items from {txn.tx_id}")

                # Reset transaction to NOT_PROCESSED
                txn.status = Transaction.OrderStatus.NOT_PROCESSED
                txn.amount_fulfilled = Decimal('0.00')
                txn.amount_paid = Decimal('0.00')
                txn.total_cost = Decimal('0.00')
                txn.total_pv = Decimal('0.00')
                txn.is_in_issuance = False
                txn.amount_fulfilled_before_activation = None
                txn.status_before_activation = None
                txn.activated_by = None
                txn.activated_at = None
                txn.completed_by = None
                txn.completed_at = None
                txn.save(skip_validation=True)
                print(f"    Restored {txn.tx_id} to NOT_PROCESSED")

            # Step C: Delete combined order line items
            print("\n  [C] Deleting combined order line items...")
            deleted_co_items = co_line_items.delete()[0]
            print(f"    Deleted {deleted_co_items} combined order line items")

            # Step D: Delete combined order transaction links
            print("\n  [D] Deleting transaction links...")
            deleted_links = linked_transactions.delete()[0]
            print(f"    Deleted {deleted_links} transaction links")

            # Step E: Delete parent transaction
            if parent_transaction:
                print("\n  [E] Deleting parent transaction...")
                parent_tx_id = parent_transaction.tx_id
                parent_transaction.delete()
                print(f"    Deleted parent transaction: {parent_tx_id}")

            # Step F: Delete combined order
            print("\n  [F] Deleting combined order...")
            combined_order.delete()
            print(f"    Deleted combined order: {combined_order_id}")

            summary['success'] = True

            # Verify child transactions
            print("\n  Verification - Child transactions now:")
            for txn in child_txns:
                txn.refresh_from_db()
                print(f"    - {txn.tx_id}: status={txn.status}, amount_fulfilled={txn.amount_fulfilled}")

    except Exception as e:
        summary['error'] = str(e)
        print(f"\n  ERROR: {e}")
        import traceback
        traceback.print_exc()

    return summary


# ============================================================================
# MAIN EXECUTION
# ============================================================================

all_summaries = []

for order_id in COMBINED_ORDER_IDS:
    summary = reset_combined_order(order_id, dry_run=DRY_RUN)
    all_summaries.append(summary)

# Final summary
print("\n" + "=" * 80)
print("FINAL SUMMARY")
print("=" * 80)

for s in all_summaries:
    status = "✓ SUCCESS" if s['success'] else f"✗ FAILED: {s['error']}"
    found = "Found" if s['found'] else "Not Found"
    print(f"\n{s['combined_order_id']}:")
    print(f"  Status: {status}")
    print(f"  Found: {found}")
    if s['found']:
        print(f"  Child Transactions: {', '.join(s['child_transactions']) or 'None'}")
        print(f"  Items Reversed: {s['items_reversed']}")
        print(f"  Items Deleted: {s['items_deleted']}")

if DRY_RUN:
    print("\n" + "=" * 80)
    print("DRY RUN COMPLETE - NO CHANGES WERE MADE")
    print("To execute changes, edit the script and set: DRY_RUN = False")
    print("=" * 80)
else:
    print("\n" + "=" * 80)
    print("RESET COMPLETE!")
    print("=" * 80)
