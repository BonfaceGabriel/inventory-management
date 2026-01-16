#!/usr/bin/env python
"""
Script to check and revert specific transactions to NOT_PROCESSED status.

Usage:
    docker exec -it inventory-management-web-1 python scripts/revert_transactions.py
"""

import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'management.settings')
django.setup()

from django.utils import timezone
from django.db import transaction as db_transaction
from payments.models import Transaction

# Transactions to revert
TX_IDS = [
    'UAG6Y3WVZJ',
    'UAGFZ3YO5O',
    'UAG7E3XAOW',
    'UAG7E3X5IR',
]

def check_and_revert():
    for tx_id in TX_IDS:
        try:
            txn = Transaction.objects.get(tx_id=tx_id)

            print(f"\n{'='*50}")
            print(f"TX: {tx_id}")
            print(f"Status: {txn.status} | Amount: {txn.amount} | Fulfilled: {txn.amount_fulfilled}")
            print(f"Line Items: {txn.line_items.count()} | In Combined: {txn.combined_orders.exists()}")

            # Check if can revert
            if txn.status == 'NOT_PROCESSED':
                print("SKIP: Already NOT_PROCESSED")
                continue
            if txn.is_in_issuance:
                print("SKIP: In issuance mode")
                continue
            if txn.combined_orders.exists():
                print("SKIP: In combined order")
                continue
            if txn.line_items.exists():
                print("SKIP: Has line items")
                continue

            # Revert using raw update to bypass model validation
            with db_transaction.atomic():
                old_status = txn.status
                timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
                new_notes = (txn.notes or '') + f"\n[{timestamp}] Reverted from {old_status} to NOT_PROCESSED by script"

                # Use update() to bypass model's clean/save validation
                Transaction.objects.filter(pk=txn.pk).update(
                    status=Transaction.OrderStatus.NOT_PROCESSED,
                    processed_by=None,
                    processed_at=None,
                    amount_fulfilled=0,
                    amount_paid=0,
                    notes=new_notes
                )

                print(f"REVERTED: {old_status} -> NOT_PROCESSED")

        except Transaction.DoesNotExist:
            print(f"\n{tx_id}: NOT FOUND")

if __name__ == '__main__':
    check_and_revert()
    print("\nDone!")
