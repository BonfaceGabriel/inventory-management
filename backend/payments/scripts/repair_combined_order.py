"""
Script to repair corrupted combined order CMB-20260121-134211

This script will:
1. Analyze the combined order to identify which transactions were added later
2. Remove the added transactions and their line items
3. Restore the combined order to its state before the transactions were added
4. Restore the removed transactions to their original status

Run with: docker compose exec web python manage.py shell < backend/payments/scripts/repair_combined_order.py
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'management.settings')
django.setup()

from decimal import Decimal
from django.utils import timezone
from django.db import transaction as db_transaction
from django.db.models import Sum
from payments.models import (
    Transaction, CombinedOrder, CombinedOrderTransaction, 
    CombinedOrderLineItem, InventoryMovement
)
import logging

logger = logging.getLogger(__name__)

# The combined order to repair
TARGET_ORDER_ID = 'CMB-20260121-134211'


def analyze_combined_order(order_id):
    """Analyze the combined order to understand its current state"""
    print(f"\n{'='*70}")
    print(f"ANALYZING COMBINED ORDER: {order_id}")
    print(f"{'='*70}\n")
    
    try:
        order = CombinedOrder.objects.get(combined_order_id=order_id)
    except CombinedOrder.DoesNotExist:
        print(f"❌ Combined Order {order_id} not found")
        return None
    
    print(f"📦 Combined Order Details:")
    print(f"   Status: {order.status}")
    print(f"   Total Amount: {order.total_amount}")
    print(f"   Amount Fulfilled: {order.amount_fulfilled}")
    print(f"   Base Amount Fulfilled: {order.base_amount_fulfilled}")
    print(f"   Created At: {order.created_at}")
    
    parent = order.parent_transaction
    if parent:
        print(f"\n🔗 Parent Transaction: {parent.tx_id}")
        print(f"   Status: {parent.status}")
        print(f"   Amount: {parent.amount}")
        print(f"   Amount Fulfilled: {parent.amount_fulfilled}")
        print(f"   Amount Paid: {parent.amount_paid}")
        
        # Check for constraint violation
        if parent.amount_fulfilled > parent.amount:
            print(f"   ⚠️  CONSTRAINT VIOLATION: amount_fulfilled ({parent.amount_fulfilled}) > amount ({parent.amount})")
    
    print(f"\n📋 Linked Transactions:")
    links = CombinedOrderTransaction.objects.filter(
        combined_order=order
    ).select_related('transaction').order_by('sequence', 'added_at')
    
    # Group by creation time to identify batches
    creation_time = order.created_at
    initial_transactions = []
    added_transactions = []
    
    for link in links:
        txn = link.transaction
        time_diff = (link.added_at - creation_time).total_seconds()
        
        # Transactions added within 5 seconds of order creation are "initial"
        # Anything later was added via add_transactions_to_combined_order
        is_initial = time_diff < 5
        
        print(f"   {'[INITIAL]' if is_initial else '[ADDED]  '} {txn.tx_id}:")
        print(f"      Amount: {txn.amount}, Fulfilled: {txn.amount_fulfilled}")
        print(f"      Status: {txn.status}")
        print(f"      Added At: {link.added_at} (Δ{time_diff:.1f}s from order creation)")
        print(f"      Sequence: {link.sequence}")
        
        if is_initial:
            initial_transactions.append(link)
        else:
            added_transactions.append(link)
    
    print(f"\n📊 Line Items Summary:")
    items = CombinedOrderLineItem.objects.filter(combined_order=order)
    total_items = items.count()
    total_value = items.aggregate(total=Sum('line_total'))['total'] or Decimal('0')
    
    copied_items = items.filter(copied_from_transaction__isnull=False)
    copied_value = copied_items.aggregate(total=Sum('line_total'))['total'] or Decimal('0')
    
    scanned_items = items.filter(copied_from_transaction__isnull=True)
    scanned_value = scanned_items.aggregate(total=Sum('line_total'))['total'] or Decimal('0')
    
    print(f"   Total Items: {total_items} (Value: {total_value})")
    print(f"   Copied from Transactions: {copied_items.count()} (Value: {copied_value})")
    print(f"   Scanned Directly: {scanned_items.count()} (Value: {scanned_value})")
    
    # Show which transactions contributed line items
    print(f"\n   Line Items by Source:")
    for link in links:
        txn = link.transaction
        txn_items = items.filter(copied_from_transaction=txn)
        if txn_items.exists():
            txn_value = txn_items.aggregate(total=Sum('line_total'))['total']
            print(f"      From {txn.tx_id}: {txn_items.count()} items (Value: {txn_value})")
    
    return {
        'order': order,
        'parent': parent,
        'initial_transactions': initial_transactions,
        'added_transactions': added_transactions,
        'all_links': links,
        'line_items': items,
        'copied_items': copied_items,
        'scanned_items': scanned_items
    }


def repair_combined_order(order_id, dry_run=True):
    """
    Repair the combined order by removing added transactions and restoring state
    
    Args:
        order_id: Combined order ID to repair
        dry_run: If True, only show what would be done without making changes
    """
    print(f"\n{'='*70}")
    print(f"{'DRY RUN: ' if dry_run else ''}REPAIRING COMBINED ORDER: {order_id}")
    print(f"{'='*70}\n")
    
    # Analyze first
    analysis = analyze_combined_order(order_id)
    if not analysis:
        return False
    
    order = analysis['order']
    parent = analysis['parent']
    initial_transactions = analysis['initial_transactions']
    added_transactions = analysis['added_transactions']
    
    if not added_transactions:
        print("\n✅ No transactions were added after creation. Order is in original state.")
        return True
    
    print(f"\n🔧 Repair Plan:")
    print(f"   1. Remove {len(added_transactions)} added transaction(s)")
    print(f"   2. Delete line items copied from added transactions")
    print(f"   3. Recalculate combined order amounts")
    print(f"   4. Restore added transactions to their original status")
    print(f"   5. Update parent transaction amounts")
    
    if dry_run:
        print(f"\n⚠️  DRY RUN MODE - No changes will be made")
        print(f"   Run with dry_run=False to apply changes")
        return True
    
    # Confirm before proceeding
    print(f"\n⚠️  About to modify database. Press Ctrl+C to cancel...")
    import time
    time.sleep(3)
    
    with db_transaction.atomic():
        # Step 1: Identify and remove line items from added transactions
        print(f"\n📝 Step 1: Removing line items from added transactions...")
        removed_items_count = 0
        removed_items_value = Decimal('0')
        
        for link in added_transactions:
            txn = link.transaction
            # Find line items copied from this transaction
            txn_items = CombinedOrderLineItem.objects.filter(
                combined_order=order,
                copied_from_transaction=txn
            )
            
            if txn_items.exists():
                items_count = txn_items.count()
                items_value = txn_items.aggregate(total=Sum('line_total'))['total']
                print(f"   Removing {items_count} items from {txn.tx_id} (Value: {items_value})")
                
                txn_items.delete()
                removed_items_count += items_count
                removed_items_value += items_value
        
        print(f"   ✓ Removed {removed_items_count} line items (Total value: {removed_items_value})")
        
        # Step 2: Remove the transaction links
        print(f"\n🔗 Step 2: Removing transaction links...")
        for link in added_transactions:
            txn = link.transaction
            print(f"   Unlinking {txn.tx_id}")
            link.delete()
        
        # Step 3: Restore the added transactions to their original status
        print(f"\n♻️  Step 3: Restoring added transactions to original status...")
        for link in added_transactions:
            txn = link.transaction
            
            # Determine original status based on amount_fulfilled
            if txn.amount_fulfilled >= txn.amount:
                original_status = Transaction.OrderStatus.FULFILLED
            elif txn.amount_fulfilled > 0:
                original_status = Transaction.OrderStatus.PARTIALLY_FULFILLED
            else:
                original_status = Transaction.OrderStatus.NOT_PROCESSED
            
            print(f"   Restoring {txn.tx_id} to {original_status}")
            txn.status = original_status
            txn.save(update_fields=['status', 'updated_at'])
        
        # Step 4: Recalculate combined order amounts
        print(f"\n🔢 Step 4: Recalculating combined order amounts...")
        
        # Recalculate total_amount from remaining linked transactions
        remaining_links = CombinedOrderTransaction.objects.filter(
            combined_order=order
        ).select_related('transaction')
        
        new_total_amount = sum(
            link.transaction.amount for link in remaining_links
        )
        
        # Recalculate amount_fulfilled from remaining line items
        remaining_items = CombinedOrderLineItem.objects.filter(combined_order=order)
        new_amount_fulfilled = remaining_items.aggregate(
            total=Sum('line_total')
        )['total'] or Decimal('0')
        
        # Recalculate base_amount_fulfilled
        new_base_amount_fulfilled = remaining_items.filter(
            is_inventory_deducted=True
        ).aggregate(total=Sum('line_total'))['total'] or Decimal('0')
        
        print(f"   Old Total Amount: {order.total_amount} → New: {new_total_amount}")
        print(f"   Old Amount Fulfilled: {order.amount_fulfilled} → New: {new_amount_fulfilled}")
        print(f"   Old Base Amount Fulfilled: {order.base_amount_fulfilled} → New: {new_base_amount_fulfilled}")
        
        order.total_amount = new_total_amount
        order.amount_fulfilled = new_amount_fulfilled
        order.base_amount_fulfilled = new_base_amount_fulfilled
        
        # Update status
        if new_amount_fulfilled >= new_total_amount:
            order.status = CombinedOrder.Status.FULFILLED
        elif new_amount_fulfilled > 0:
            order.status = CombinedOrder.Status.PARTIALLY_FULFILLED
        else:
            order.status = CombinedOrder.Status.PENDING
        
        print(f"   Status: {order.status}")
        
        order.save(update_fields=[
            'total_amount', 'amount_fulfilled', 'base_amount_fulfilled', 
            'status', 'updated_at'
        ])
        
        # Step 5: Update parent transaction
        print(f"\n🔗 Step 5: Updating parent transaction...")
        if parent:
            parent.amount = order.total_amount
            parent.amount_fulfilled = order.amount_fulfilled
            parent.amount_paid = order.amount_fulfilled
            
            # Update status
            if order.amount_fulfilled >= order.total_amount:
                parent.status = Transaction.OrderStatus.FULFILLED
            elif order.amount_fulfilled > 0:
                parent.status = Transaction.OrderStatus.PARTIALLY_FULFILLED
            else:
                parent.status = Transaction.OrderStatus.PROCESSING
            
            print(f"   Amount: {parent.amount}")
            print(f"   Amount Fulfilled: {parent.amount_fulfilled}")
            print(f"   Amount Paid: {parent.amount_paid}")
            print(f"   Status: {parent.status}")
            
            # Use skip_validation=True to avoid constraint issues during update
            parent.save(
                update_fields=['amount', 'amount_fulfilled', 'amount_paid', 'status', 'updated_at'],
                skip_validation=True
            )
            
            # Verify constraint is satisfied
            if parent.amount_fulfilled <= parent.amount:
                print(f"   ✓ Constraint satisfied: amount_fulfilled <= amount")
            else:
                print(f"   ⚠️  WARNING: Constraint still violated!")
    
    print(f"\n{'='*70}")
    print(f"✅ REPAIR COMPLETED SUCCESSFULLY")
    print(f"{'='*70}\n")
    
    # Show final state
    print(f"Final State:")
    print(f"   Combined Order: total={order.total_amount}, fulfilled={order.amount_fulfilled}")
    print(f"   Parent Transaction: amount={parent.amount}, fulfilled={parent.amount_fulfilled}")
    print(f"   Removed {len(added_transactions)} added transaction(s)")
    print(f"   Restored {len(added_transactions)} transaction(s) to original status")
    
    return True


if __name__ == '__main__':
    # First, analyze the order
    print("Analyzing combined order...")
    analysis = analyze_combined_order(TARGET_ORDER_ID)
    
    if analysis and analysis['added_transactions']:
        print(f"\n{'='*70}")
        print(f"Found {len(analysis['added_transactions'])} transaction(s) that were added after creation")
        print(f"{'='*70}\n")
        
        # Run dry run first
        print("Running DRY RUN to preview changes...")
        repair_combined_order(TARGET_ORDER_ID, dry_run=True)
        
        # Ask for confirmation
        print(f"\n{'='*70}")
        response = input("Apply these changes? (yes/no): ").strip().lower()
        
        if response == 'yes':
            repair_combined_order(TARGET_ORDER_ID, dry_run=False)
        else:
            print("Repair cancelled by user")
    elif analysis:
        print("\n✅ No repair needed - order is in original state")
else:
    # Running via manage.py shell
    print("Analyzing combined order...")
    analysis = analyze_combined_order(TARGET_ORDER_ID)
    
    if analysis and analysis['added_transactions']:
        # In shell mode, just run the repair directly (no interactive prompt)
        repair_combined_order(TARGET_ORDER_ID, dry_run=False)
