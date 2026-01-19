#!/usr/bin/env python
"""
Script to reset and deconstruct combined order CMB-20260119-103204

This script will:
1. Find the combined order and all associated data
2. Reverse any inventory changes from line items that were deducted
3. Restore child transactions to NOT_PROCESSED status
4. Delete the combined order, its line items, and parent transaction

Run with:
    docker exec inventory-management-web-1 python manage.py shell < scripts/reset_combined_order_CMB_20260119_103204.py

Or in Django shell:
    exec(open('scripts/reset_combined_order_CMB_20260119_103204.py').read())
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

COMBINED_ORDER_ID = 'CMB-20260119-103204'
DRY_RUN = True  # Set to False to actually execute changes

print("=" * 80)
print(f"RESET COMBINED ORDER: {COMBINED_ORDER_ID}")
print(f"DRY RUN: {DRY_RUN}")
print("=" * 80)

try:
    # Step 1: Find the combined order
    print("\n[STEP 1] Finding combined order...")
    try:
        combined_order = CombinedOrder.objects.get(combined_order_id=COMBINED_ORDER_ID)
        print(f"  Found: {combined_order}")
        print(f"  Status: {combined_order.status}")
        print(f"  Total Amount: {combined_order.total_amount}")
        print(f"  Amount Fulfilled: {combined_order.amount_fulfilled}")
        print(f"  Base Amount Fulfilled: {combined_order.base_amount_fulfilled}")
        print(f"  Created By: {combined_order.created_by}")
        print(f"  Created At: {combined_order.created_at}")
    except CombinedOrder.DoesNotExist:
        print(f"  ERROR: Combined order {COMBINED_ORDER_ID} not found!")
        sys.exit(1)

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

    items_to_reverse = []  # Items that need inventory reversal
    items_copied = []      # Items copied from child transactions (already had inventory deducted)

    for item in co_line_items:
        copied_from = item.copied_from_transaction.tx_id if item.copied_from_transaction else None
        print(f"  - {item.quantity}x {item.scanned_prod_name}")
        print(f"      Price: {item.scanned_price}, Total: {item.line_total}")
        print(f"      Is Inventory Deducted: {item.is_inventory_deducted}")
        print(f"      Copied From Transaction: {copied_from}")

        if item.is_inventory_deducted and not item.copied_from_transaction:
            # This item was scanned directly to combined order and inventory was deducted
            items_to_reverse.append(item)
            print(f"      >>> NEEDS INVENTORY REVERSAL")
        elif item.copied_from_transaction:
            items_copied.append(item)
            print(f"      >>> Copied item (inventory already handled in original txn)")

    # Step 5: Check for inventory movements related to this order
    print("\n[STEP 5] Finding related inventory movements...")
    inv_movements = InventoryMovement.objects.filter(
        reference__icontains=COMBINED_ORDER_ID
    )
    print(f"  Found {inv_movements.count()} inventory movements")
    for mov in inv_movements:
        print(f"  - {mov.get_movement_type_display()}: {mov.product.prod_name}")
        print(f"      Change: {mov.quantity_change}, Before: {mov.quantity_before}, After: {mov.quantity_after}")
        print(f"      Reference: {mov.reference}")

    # Step 6: Summary of what will be done
    print("\n" + "=" * 80)
    print("SUMMARY OF CHANGES TO BE MADE:")
    print("=" * 80)
    print(f"\n1. INVENTORY REVERSALS ({len(items_to_reverse)} items):")
    for item in items_to_reverse:
        product = item.product
        print(f"   - {product.prod_name}: +{item.quantity} (current stock: {product.quantity})")

    print(f"\n2. CHILD TRANSACTIONS TO RESTORE ({len(child_txns)} transactions):")
    for txn in child_txns:
        print(f"   - {txn.tx_id}: {txn.status} -> NOT_PROCESSED")
        print(f"     Reset: amount_fulfilled=0, is_in_issuance=False")

    print(f"\n3. LINE ITEMS TO DELETE:")
    print(f"   - Combined Order Line Items: {co_line_items.count()}")
    # Also check child transaction line items
    for txn in child_txns:
        txn_items = TransactionLineItem.objects.filter(transaction=txn)
        if txn_items.exists():
            print(f"   - Transaction {txn.tx_id} Line Items: {txn_items.count()}")

    print(f"\n4. RECORDS TO DELETE:")
    print(f"   - CombinedOrderTransaction links: {linked_transactions.count()}")
    print(f"   - CombinedOrder: {combined_order.combined_order_id}")
    if parent_transaction:
        print(f"   - Parent Transaction: {parent_transaction.tx_id}")

    if DRY_RUN:
        print("\n" + "=" * 80)
        print("DRY RUN - NO CHANGES MADE")
        print("Set DRY_RUN = False to execute changes")
        print("=" * 80)
    else:
        print("\n" + "=" * 80)
        print("EXECUTING CHANGES...")
        print("=" * 80)

        with transaction.atomic():
            # Step A: Reverse inventory for items scanned directly to combined order
            print("\n[A] Reversing inventory...")
            for item in items_to_reverse:
                product = Product.objects.select_for_update().get(id=item.product.id)
                quantity_before = product.quantity
                product.quantity += item.quantity
                product.save()

                # Create inventory movement for audit trail
                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.MovementType.RETURN,
                    product=product,
                    quantity_before=quantity_before,
                    quantity_after=product.quantity,
                    quantity_change=item.quantity,
                    reference=f"Reset Combined Order {COMBINED_ORDER_ID}",
                    performed_by="System (Reset Script)"
                )
                print(f"  Reversed: {product.prod_name} +{item.quantity} (now: {product.quantity})")

            # Step B: Handle child transactions - restore them to pre-combine state
            print("\n[B] Restoring child transactions...")
            for txn in child_txns:
                # Delete any line items that belong to this transaction
                # (these were scanned to the transaction before combining)
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
                        reference=f"Reset Transaction {txn.tx_id} (from Combined Order {COMBINED_ORDER_ID})",
                        performed_by="System (Reset Script)"
                    )
                    print(f"  Reversed from {txn.tx_id}: {product.prod_name} +{li.quantity}")

                # Delete all line items for this transaction
                deleted_count = txn_line_items.delete()[0]
                if deleted_count:
                    print(f"  Deleted {deleted_count} line items from {txn.tx_id}")

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
                print(f"  Restored {txn.tx_id} to NOT_PROCESSED")

            # Step C: Delete combined order line items
            print("\n[C] Deleting combined order line items...")
            deleted_co_items = co_line_items.delete()[0]
            print(f"  Deleted {deleted_co_items} combined order line items")

            # Step D: Delete combined order transaction links
            print("\n[D] Deleting combined order transaction links...")
            deleted_links = linked_transactions.delete()[0]
            print(f"  Deleted {deleted_links} transaction links")

            # Step E: Delete parent transaction
            if parent_transaction:
                print("\n[E] Deleting parent transaction...")
                parent_tx_id = parent_transaction.tx_id
                parent_transaction.delete()
                print(f"  Deleted parent transaction: {parent_tx_id}")

            # Step F: Delete combined order
            print("\n[F] Deleting combined order...")
            combined_order.delete()
            print(f"  Deleted combined order: {COMBINED_ORDER_ID}")

            print("\n" + "=" * 80)
            print("RESET COMPLETE!")
            print("=" * 80)

            # Verify child transactions
            print("\nVerification - Child transactions now:")
            for txn in child_txns:
                txn.refresh_from_db()
                print(f"  - {txn.tx_id}: status={txn.status}, amount_fulfilled={txn.amount_fulfilled}")

except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
