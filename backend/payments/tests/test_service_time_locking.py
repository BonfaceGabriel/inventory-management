from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from payments.services.time_locking_service import TimeLockingService
from payments.models import Transaction
from .test_helpers import make_gateway, make_transaction, today, now


class TimeLockingServiceTest(TestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.tx = make_transaction(tx_id='TL-TX-001', amount=Decimal('1000.00'))

    def test_lock_partially_fulfilled_locks_eligible(self):
        self.tx.status = 'PARTIALLY_FULFILLED'
        self.tx.amount_fulfilled = Decimal('500.00')
        self.tx.save()
        result = TimeLockingService.lock_partially_fulfilled_transactions()
        self.assertEqual(result['locked_count'], 1)
        self.tx.refresh_from_db()
        self.assertTrue(self.tx.is_time_locked)
        self.assertIsNotNone(self.tx.locked_at)

    def test_lock_does_not_affect_not_processed(self):
        result = TimeLockingService.lock_partially_fulfilled_transactions()
        self.assertEqual(result['locked_count'], 0)
        self.tx.refresh_from_db()
        self.assertFalse(self.tx.is_time_locked)

    def test_lock_does_not_affect_fulfilled(self):
        self.tx.status = 'FULFILLED'
        self.tx.save()
        result = TimeLockingService.lock_partially_fulfilled_transactions()
        self.assertEqual(result['locked_count'], 0)

    def test_lock_does_not_affect_cancelled(self):
        self.tx.status = 'CANCELLED'
        self.tx.save()
        result = TimeLockingService.lock_partially_fulfilled_transactions()
        self.assertEqual(result['locked_count'], 0)

    def test_lock_with_custom_date(self):
        yesterday = today() - timezone.timedelta(days=1)
        tx2 = make_transaction(
            tx_id='TL-TX-002', amount=Decimal('500.00'),
            unique_hash='hash_tl2', status='PARTIALLY_FULFILLED',
            amount_fulfilled=Decimal('200.00'),
        )
        result = TimeLockingService.lock_partially_fulfilled_transactions(
            target_date=yesterday,
        )
        tx2.refresh_from_db()
        self.assertTrue(tx2.is_time_locked)

    def test_lock_returns_summary(self):
        self.tx.status = 'PARTIALLY_FULFILLED'
        self.tx.amount_fulfilled = Decimal('500.00')
        self.tx.save()
        result = TimeLockingService.lock_partially_fulfilled_transactions()
        self.assertIn('locked_count', result)
        self.assertIn('skipped_count', result)
        self.assertIn('total_fulfilled_locked', result)
