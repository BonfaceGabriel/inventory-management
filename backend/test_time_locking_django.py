"""
Django-based test for time-locking feature.
Run with: docker exec inventory-management-web-1 python test_time_locking_django.py
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'management.settings')
django.setup()

from decimal import Decimal
from django.utils import timezone
from datetime import datetime
from payments.models import Transaction, PaymentGateway, Device
from payments.services.time_locking_service import TimeLockingService

def print_section(title):
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)

def print_result(test_name, passed, details=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} - {test_name}")
    if details:
        print(f"     {details}")

def run_tests():
    print("\n" + "🧪" * 35)
    print("TIME-LOCKING FEATURE TEST SUITE (Django)")
    print("🧪" * 35)

    # Test 1: Create test gateway
    print_section("Test 1: Setup - Create Test Gateway")
    gateway, created = PaymentGateway.objects.get_or_create(
        name="Test Time Lock Gateway",
        defaults={
            'gateway_type': 'MPESA_TILL',
            'gateway_number': '555999',
            'settlement_type': 'NONE',
            'is_active': True
        }
    )
    print(f"Gateway: {gateway.name} (Created: {created})")

    # Test 2: Create partially fulfilled transaction
    print_section("Test 2: Create Partially Fulfilled Transaction")

    now = timezone.now()
    tx = Transaction.objects.create(
        tx_id=f"TEST{now.strftime('%H%M%S')}",
        amount=Decimal('1000.00'),
        sender_name="Test Customer",
        sender_phone="0712345678",
        timestamp=now,
        gateway=gateway,
        status=Transaction.OrderStatus.PARTIALLY_FULFILLED,
        amount_fulfilled=Decimal('500.00'),  # 500 out of 1000 fulfilled
        unique_hash=f"hash_test_{now.timestamp()}",
        confidence=0.9
    )

    print(f"Created transaction:")
    print(f"  TX ID: {tx.tx_id}")
    print(f"  Amount: {tx.amount}")
    print(f"  Amount Fulfilled: {tx.amount_fulfilled}")
    print(f"  Remaining: {tx.remaining_amount}")
    print(f"  Status: {tx.status}")
    print(f"  Is Locked: {tx.is_locked}")
    print(f"  Is Time Locked: {tx.is_time_locked}")

    print_result("Transaction created", tx.id is not None)
    print_result("Status is PARTIALLY_FULFILLED", tx.status == Transaction.OrderStatus.PARTIALLY_FULFILLED)
    print_result("Not locked initially", not tx.is_locked and not tx.is_time_locked)

    # Test 3: Get lockable transactions
    print_section("Test 3: Get Lockable Transactions")

    lockable = TimeLockingService.get_lockable_transactions()
    print(f"Found {lockable.count()} lockable transactions")

    for t in lockable[:3]:
        print(f"  - {t.tx_id}: {t.status}, Remaining: {t.remaining_amount}")

    print_result("Lockable transactions found", lockable.count() > 0)
    print_result("Test transaction is lockable", tx in lockable)

    # Test 4: Lock partially fulfilled transactions
    print_section("Test 4: Lock Partially Fulfilled Transactions")

    result = TimeLockingService.lock_partially_fulfilled_transactions(
        locked_by="Test Script"
    )

    print(f"Lock result:")
    print(f"  Success: {result['success']}")
    print(f"  Locked Count: {result['locked_count']}")
    print(f"  Total Remaining Amount: {result['total_remaining_amount']}")
    print(f"  Locked By: {result['locked_by']}")
    print(f"  Locked Transaction IDs: {result['locked_tx_ids'][:5]}")

    print_result("Locking successful", result['success'])
    print_result("At least one transaction locked", result['locked_count'] > 0)
    print_result("Our test transaction was locked", tx.tx_id in result['locked_tx_ids'])

    # Test 5: Verify transaction is now locked
    print_section("Test 5: Verify Transaction is Locked")

    # Refresh from database
    tx.refresh_from_db()

    print(f"Transaction after locking:")
    print(f"  TX ID: {tx.tx_id}")
    print(f"  Status: {tx.status}")
    print(f"  Is Locked: {tx.is_locked}")
    print(f"  Is Time Locked: {tx.is_time_locked}")
    print(f"  Locked At: {tx.locked_at}")
    print(f"  Locked By: {tx.locked_by}")

    print_result("Is locked", tx.is_locked)
    print_result("Is time locked", tx.is_time_locked)
    print_result("Status unchanged (still PARTIALLY_FULFILLED)",
                 tx.status == Transaction.OrderStatus.PARTIALLY_FULFILLED)
    print_result("Locked by is set", tx.locked_by == "Test Script")
    print_result("Locked at timestamp is set", tx.locked_at is not None)

    # Test 6: Try to modify locked transaction
    print_section("Test 6: Try to Modify Locked Transaction")

    try:
        tx.notes = "This should not be allowed"
        tx.save()
        print_result("Locked transaction modification prevented", False,
                    "❌ Modification was allowed (should be blocked)")
    except Exception as e:
        print_result("Locked transaction modification prevented", True,
                    f"✅ Correctly raised: {type(e).__name__}")

    # Test 7: Check that lockable transactions list is now empty (for our test transaction)
    print_section("Test 7: Verify No Longer Lockable")

    lockable_after = TimeLockingService.get_lockable_transactions()
    print(f"Lockable transactions after locking: {lockable_after.count()}")

    print_result("Test transaction no longer lockable", tx not in lockable_after)

    # Final Summary
    print_section("TEST SUMMARY")

    all_tests = [
        tx.id is not None,
        tx.status == Transaction.OrderStatus.PARTIALLY_FULFILLED,
        result['success'],
        result['locked_count'] > 0,
        tx.is_locked,
        tx.is_time_locked,
        tx.locked_by == "Test Script",
        tx not in lockable_after
    ]

    passed = sum(all_tests)
    total = len(all_tests)

    print(f"\nTests Passed: {passed}/{total}")

    if passed == total:
        print("\n🎉 All tests PASSED! Time-locking feature is working correctly.")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please review the output above.")

    print("\n" + "="*70)

    # Cleanup
    print("\nCleaning up test data...")
    tx.delete()
    if created:
        gateway.delete()
    print("✅ Cleanup complete")

if __name__ == "__main__":
    try:
        run_tests()
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
