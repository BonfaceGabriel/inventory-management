from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from payments.services import OrderStatusService
from utils.exceptions import (
    TransactionLockedException, InvalidStatusTransitionError, InsufficientAmountError,
)
from .test_helpers import make_gateway, make_transaction, make_product


class OrderStatusServiceTest(TestCase):
    def setUp(self):
        self.service = OrderStatusService()
        self.gateway = make_gateway()
        self.tx = make_transaction(tx_id='OS-TX-001', amount=Decimal('5000.00'))

    # --- mark_as_processing ---
    def test_mark_as_processing_success(self):
        result = self.service.mark_as_processing(self.tx)
        self.assertEqual(result.status, 'PROCESSING')

    def test_mark_as_processing_with_notes(self):
        result = self.service.mark_as_processing(self.tx, notes='Customer requested')
        self.assertEqual(result.status, 'PROCESSING')
        self.assertIn('Customer requested', result.notes)

    def test_mark_as_processing_raises_on_locked(self):
        self.tx.status = 'FULFILLED'
        self.tx.save(skip_validation=True)
        with self.assertRaises(TransactionLockedException):
            self.service.mark_as_processing(self.tx)

    def test_mark_as_processing_raises_on_invalid_transition(self):
        self.tx.status = 'CANCELLED'
        self.tx.save(skip_validation=True)
        with self.assertRaises(TransactionLockedException):
            self.service.mark_as_processing(self.tx)

    # --- allocate_payment ---
    def test_allocate_payment_partial(self):
        self.service.mark_as_processing(self.tx)
        result = self.service.allocate_payment(self.tx, 'ORD-001', Decimal('2000.00'))
        self.assertEqual(result.amount_fulfilled, Decimal('2000.00'))
        self.assertEqual(result.status, 'PARTIALLY_FULFILLED')

    def test_allocate_payment_full(self):
        self.service.mark_as_processing(self.tx)
        result = self.service.allocate_payment(self.tx, 'ORD-002', Decimal('5000.00'))
        self.assertEqual(result.amount_fulfilled, Decimal('5000.00'))
        self.assertEqual(result.status, 'FULFILLED')

    def test_allocate_payment_multiple_calls(self):
        self.service.mark_as_processing(self.tx)
        self.service.allocate_payment(self.tx, 'ORD-003', Decimal('2000.00'))
        self.service.allocate_payment(self.tx, 'ORD-004', Decimal('1500.00'))
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.amount_fulfilled, Decimal('3500.00'))
        self.assertEqual(self.tx.status, 'PARTIALLY_FULFILLED')

    def test_allocate_payment_exceeds_amount(self):
        with self.assertRaises(InsufficientAmountError):
            self.service.allocate_payment(self.tx, 'ORD-005', Decimal('6000.00'))

    def test_allocate_payment_negative(self):
        with self.assertRaises(ValidationError):
            self.service.allocate_payment(self.tx, 'ORD-006', Decimal('-100.00'))

    def test_allocate_payment_zero(self):
        with self.assertRaises(ValidationError):
            self.service.allocate_payment(self.tx, 'ORD-007', Decimal('0.00'))

    def test_allocate_payment_on_locked(self):
        self.tx.status = 'FULFILLED'
        self.tx.save(skip_validation=True)
        with self.assertRaises(TransactionLockedException):
            self.service.allocate_payment(self.tx, 'ORD-008', Decimal('100.00'))

    def test_allocate_payment_with_notes(self):
        result = self.service.allocate_payment(self.tx, 'ORD-009', Decimal('1000.00'), notes='First installment')
        self.assertIn('First installment', result.notes)

    # --- mark_as_fulfilled ---
    def test_mark_as_fulfilled_from_processing(self):
        self.tx.amount = Decimal('10000.00')
        self.tx.status = 'PROCESSING'
        self.tx.amount_fulfilled = Decimal('5000.00')
        self.tx.save(skip_validation=True)
        result = self.service.mark_as_fulfilled(self.tx)
        self.assertEqual(result.status, 'FULFILLED')

    def test_mark_as_fulfilled_from_partial(self):
        self.tx.amount = Decimal('10000.00')
        self.tx.status = 'PARTIALLY_FULFILLED'
        self.tx.amount_fulfilled = Decimal('5000.00')
        self.tx.save(skip_validation=True)
        result = self.service.mark_as_fulfilled(self.tx)
        self.assertEqual(result.status, 'FULFILLED')

    def test_mark_as_fulfilled_raises_on_locked(self):
        self.tx.status = 'FULFILLED'
        self.tx.save(skip_validation=True)
        with self.assertRaises(TransactionLockedException):
            self.service.mark_as_fulfilled(self.tx)

    # --- cancel_transaction ---
    def test_cancel_from_not_processed(self):
        result = self.service.cancel_transaction(self.tx, 'No longer needed')
        self.assertEqual(result.status, 'CANCELLED')

    def test_cancel_from_processing(self):
        self.tx.status = 'PROCESSING'
        self.tx.save(skip_validation=True)
        result = self.service.cancel_transaction(self.tx, 'Customer request')
        self.assertEqual(result.status, 'CANCELLED')

    def test_cancel_from_partially_fulfilled(self):
        self.tx.status = 'PARTIALLY_FULFILLED'
        self.tx.amount_fulfilled = Decimal('2000.00')
        self.tx.save(skip_validation=True)
        result = self.service.cancel_transaction(self.tx, 'Partial cancellation')
        self.assertEqual(result.status, 'CANCELLED')

    def test_cancel_without_reason(self):
        with self.assertRaises(ValidationError):
            self.service.cancel_transaction(self.tx, '')

    def test_cancel_raises_on_fulfilled(self):
        self.tx.status = 'FULFILLED'
        self.tx.save(skip_validation=True)
        with self.assertRaises(TransactionLockedException):
            self.service.cancel_transaction(self.tx, 'Trying')

    # --- get_available_transactions ---
    def test_get_available_transactions_includes_processing(self):
        self.tx.status = 'PROCESSING'
        self.tx.save(skip_validation=True)
        available = self.service.get_available_transactions()
        self.assertIn(self.tx, available)

    def test_get_available_transactions_includes_partial(self):
        self.tx.status = 'PARTIALLY_FULFILLED'
        self.tx.save(skip_validation=True)
        available = self.service.get_available_transactions()
        self.assertIn(self.tx, available)

    def test_get_available_transactions_excludes_locked(self):
        self.tx.status = 'FULFILLED'
        self.tx.save(skip_validation=True)
        available = self.service.get_available_transactions()
        self.assertNotIn(self.tx, available)

    def test_get_available_transactions_min_amount_filter(self):
        self.tx.amount = Decimal('3000.00')
        self.tx.status = 'PROCESSING'
        self.tx.save(skip_validation=True)
        available = self.service.get_available_transactions(min_amount=Decimal('4000.00'))
        self.assertNotIn(self.tx, available)

    # --- get_transaction_summary ---
    def test_get_transaction_summary_contains_keys(self):
        summary = self.service.get_transaction_summary(self.tx)
        self.assertIn('tx_id', summary)
        self.assertIn('status', summary)
        self.assertIn('amount', summary)
        self.assertIn('is_locked', summary)

    def test_get_transaction_summary_unlocked(self):
        summary = self.service.get_transaction_summary(self.tx)
        self.assertFalse(summary['is_locked'])

    def test_get_transaction_summary_locked(self):
        self.tx.status = 'FULFILLED'
        self.tx.save(skip_validation=True)
        summary = self.service.get_transaction_summary(self.tx)
        self.assertTrue(summary['is_locked'])
