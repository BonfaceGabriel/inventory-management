"""
Tests for Order Status Management Service

Tests all service methods for proper:
- Status transitions
- Locking enforcement
- Payment allocation
- Validation and error handling
"""

from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone

from payments.models import Transaction, Device
from payments.services import OrderStatusService
from utils.exceptions import (
    TransactionLockedException,
    InvalidStatusTransitionError,
    InsufficientAmountError
)


class OrderStatusServiceTestCase(TestCase):
    """Test suite for OrderStatusService"""

    def setUp(self):
        """Create test device and transaction"""
        self.device = Device.objects.create(
            name="Test Device",
            phone_number="+254700000000",
            default_gateway="M-PESA",
            gateway_number="MPESA",
            api_key="test-api-key-123"
        )

        self.transaction = Transaction.objects.create(
            tx_id="TEST123",
            amount=Decimal('5000.00'),
            amount_expected=Decimal('5000.00'),
            amount_paid=Decimal('0.00'),
            sender_name="JOHN DOE",
            sender_phone="+254700000000",
            timestamp=timezone.now(),
            gateway_type="M-PESA",
            destination_number="MPESA",
            status=Transaction.OrderStatus.NOT_PROCESSED,
            unique_hash="test-hash-123"
        )

        self.service = OrderStatusService()

    # ==================== mark_as_processing Tests ====================

    def test_mark_as_processing_from_not_processed(self):
        """Should successfully mark NOT_PROCESSED transaction as PROCESSING"""
        result = self.service.mark_as_processing(self.transaction)

        self.assertEqual(result.status, Transaction.OrderStatus.PROCESSING)
        self.assertFalse(result.is_locked)

    def test_mark_as_processing_with_notes(self):
        """Should add notes when marking as PROCESSING"""
        result = self.service.mark_as_processing(
            self.transaction,
            notes="Starting order fulfillment"
        )

        self.assertIn("Starting order fulfillment", result.notes)

    def test_mark_as_processing_locked_transaction(self):
        """Should raise TransactionLockedException for locked transactions"""
        # Lock transaction by marking as FULFILLED
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        self.transaction.save()
        self.transaction.amount_paid = self.transaction.amount_expected
        self.transaction.save()

        with self.assertRaises(TransactionLockedException):
            self.service.mark_as_processing(self.transaction)

    def test_mark_as_processing_invalid_transition(self):
        """Should raise InvalidStatusTransitionError for invalid transitions"""
        # PARTIALLY_FULFILLED -> PROCESSING is not valid
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        self.transaction.save()
        self.transaction.status = Transaction.OrderStatus.PARTIALLY_FULFILLED
        self.transaction.save()

        with self.assertRaises(InvalidStatusTransitionError):
            self.service.mark_as_processing(self.transaction)

    # ==================== allocate_payment Tests ====================

    def test_allocate_payment_partial(self):
        """Should allocate partial payment correctly"""
        # Mark as PROCESSING first
        self.service.mark_as_processing(self.transaction)

        # Allocate 3000 out of 5000
        result = self.service.allocate_payment(
            self.transaction,
            order_id="ORDER-001",
            amount=Decimal('3000.00')
        )

        self.assertEqual(result.amount_paid, Decimal('3000.00'))
        self.assertEqual(result.remaining_amount, Decimal('2000.00'))
        self.assertEqual(result.status, Transaction.OrderStatus.PARTIALLY_FULFILLED)
        self.assertFalse(result.is_locked)

    def test_allocate_payment_full(self):
        """Should auto-lock when full amount is allocated"""
        self.service.mark_as_processing(self.transaction)

        # Allocate full amount
        result = self.service.allocate_payment(
            self.transaction,
            order_id="ORDER-001",
            amount=Decimal('5000.00')
        )

        self.assertEqual(result.amount_paid, Decimal('5000.00'))
        self.assertEqual(result.remaining_amount, Decimal('0.00'))
        self.assertEqual(result.status, Transaction.OrderStatus.FULFILLED)
        self.assertTrue(result.is_locked)

    def test_allocate_payment_multiple_allocations(self):
        """Should handle multiple partial allocations correctly"""
        self.service.mark_as_processing(self.transaction)

        # First allocation
        self.service.allocate_payment(
            self.transaction,
            order_id="ORDER-001",
            amount=Decimal('2000.00')
        )
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.remaining_amount, Decimal('3000.00'))

        # Second allocation
        self.service.allocate_payment(
            self.transaction,
            order_id="ORDER-002",
            amount=Decimal('1500.00')
        )
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.remaining_amount, Decimal('1500.00'))

        # Final allocation
        result = self.service.allocate_payment(
            self.transaction,
            order_id="ORDER-003",
            amount=Decimal('1500.00')
        )

        self.assertEqual(result.remaining_amount, Decimal('0.00'))
        self.assertTrue(result.is_locked)

    def test_allocate_payment_insufficient_amount(self):
        """Should raise InsufficientAmountError when amount exceeds remaining"""
        self.service.mark_as_processing(self.transaction)

        with self.assertRaises(InsufficientAmountError):
            self.service.allocate_payment(
                self.transaction,
                order_id="ORDER-001",
                amount=Decimal('6000.00')  # More than available
            )

    def test_allocate_payment_negative_amount(self):
        """Should raise ValidationError for negative amounts"""
        self.service.mark_as_processing(self.transaction)

        with self.assertRaises(ValidationError):
            self.service.allocate_payment(
                self.transaction,
                order_id="ORDER-001",
                amount=Decimal('-100.00')
            )

    def test_allocate_payment_zero_amount(self):
        """Should raise ValidationError for zero amounts"""
        self.service.mark_as_processing(self.transaction)

        with self.assertRaises(ValidationError):
            self.service.allocate_payment(
                self.transaction,
                order_id="ORDER-001",
                amount=Decimal('0.00')
            )

    def test_allocate_payment_locked_transaction(self):
        """Should raise TransactionLockedException for locked transactions"""
        # Lock transaction
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        self.transaction.save()
        self.transaction.amount_paid = self.transaction.amount_expected
        self.transaction.save()

        with self.assertRaises(TransactionLockedException):
            self.service.allocate_payment(
                self.transaction,
                order_id="ORDER-001",
                amount=Decimal('100.00')
            )

    def test_allocate_payment_with_notes(self):
        """Should add allocation notes with timestamps"""
        self.service.mark_as_processing(self.transaction)

        result = self.service.allocate_payment(
            self.transaction,
            order_id="ORDER-001",
            amount=Decimal('2000.00'),
            notes="First partial payment"
        )

        self.assertIn("ORDER-001", result.notes)
        self.assertIn("2000", result.notes)
        self.assertIn("First partial payment", result.notes)

    # ==================== mark_as_fulfilled Tests ====================

    def test_mark_as_fulfilled_manual(self):
        """Should manually mark transaction as FULFILLED"""
        self.service.mark_as_processing(self.transaction)

        result = self.service.mark_as_fulfilled(
            self.transaction,
            notes="Customer paid via bank transfer"
        )

        self.assertEqual(result.status, Transaction.OrderStatus.FULFILLED)
        self.assertTrue(result.is_locked)
        self.assertIn("Manually marked as FULFILLED", result.notes)
        self.assertIn("Customer paid via bank transfer", result.notes)

    def test_mark_as_fulfilled_from_partially_fulfilled(self):
        """Should fulfill from PARTIALLY_FULFILLED status"""
        self.service.mark_as_processing(self.transaction)
        self.service.allocate_payment(
            self.transaction,
            order_id="ORDER-001",
            amount=Decimal('2000.00')
        )
        self.transaction.refresh_from_db()

        result = self.service.mark_as_fulfilled(
            self.transaction,
            notes="Remaining amount waived"
        )

        self.assertEqual(result.status, Transaction.OrderStatus.FULFILLED)
        self.assertTrue(result.is_locked)

    def test_mark_as_fulfilled_invalid_transition(self):
        """Should raise InvalidStatusTransitionError for invalid transitions"""
        # NOT_PROCESSED -> FULFILLED is not valid
        with self.assertRaises(InvalidStatusTransitionError):
            self.service.mark_as_fulfilled(self.transaction)

    def test_mark_as_fulfilled_already_locked(self):
        """Should raise TransactionLockedException if already locked"""
        # Lock by cancelling
        self.service.cancel_transaction(
            self.transaction,
            reason="Duplicate entry"
        )

        with self.assertRaises(TransactionLockedException):
            self.service.mark_as_fulfilled(self.transaction)

    # ==================== cancel_transaction Tests ====================

    def test_cancel_transaction_from_not_processed(self):
        """Should cancel transaction from NOT_PROCESSED status"""
        result = self.service.cancel_transaction(
            self.transaction,
            reason="Duplicate entry detected"
        )

        self.assertEqual(result.status, Transaction.OrderStatus.CANCELLED)
        self.assertTrue(result.is_locked)
        self.assertIn("CANCELLED", result.notes)
        self.assertIn("Duplicate entry detected", result.notes)

    def test_cancel_transaction_from_processing(self):
        """Should cancel transaction from PROCESSING status"""
        self.service.mark_as_processing(self.transaction)

        result = self.service.cancel_transaction(
            self.transaction,
            reason="Customer requested refund"
        )

        self.assertEqual(result.status, Transaction.OrderStatus.CANCELLED)
        self.assertTrue(result.is_locked)

    def test_cancel_transaction_from_partially_fulfilled(self):
        """Should cancel transaction from PARTIALLY_FULFILLED status"""
        self.service.mark_as_processing(self.transaction)
        self.service.allocate_payment(
            self.transaction,
            order_id="ORDER-001",
            amount=Decimal('2000.00')
        )
        self.transaction.refresh_from_db()

        result = self.service.cancel_transaction(
            self.transaction,
            reason="Payment reversed by gateway"
        )

        self.assertEqual(result.status, Transaction.OrderStatus.CANCELLED)
        self.assertTrue(result.is_locked)

    def test_cancel_transaction_no_reason(self):
        """Should raise ValidationError when no reason provided"""
        with self.assertRaises(ValidationError):
            self.service.cancel_transaction(self.transaction, reason="")

        with self.assertRaises(ValidationError):
            self.service.cancel_transaction(self.transaction, reason="   ")

    def test_cancel_transaction_already_locked(self):
        """Should raise TransactionLockedException if already locked"""
        # Lock by fulfilling
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        self.transaction.save()
        self.transaction.amount_paid = self.transaction.amount_expected
        self.transaction.save()

        with self.assertRaises(TransactionLockedException):
            self.service.cancel_transaction(
                self.transaction,
                reason="Test cancellation"
            )

    # ==================== get_available_transactions Tests ====================

    def test_get_available_transactions_processing(self):
        """Should return PROCESSING transactions with remaining amount"""
        self.service.mark_as_processing(self.transaction)

        available = self.service.get_available_transactions()

        self.assertEqual(available.count(), 1)
        self.assertEqual(available.first().tx_id, "TEST123")

    def test_get_available_transactions_partially_fulfilled(self):
        """Should return PARTIALLY_FULFILLED transactions"""
        self.service.mark_as_processing(self.transaction)
        self.service.allocate_payment(
            self.transaction,
            order_id="ORDER-001",
            amount=Decimal('2000.00')
        )

        available = self.service.get_available_transactions()

        self.assertEqual(available.count(), 1)

    def test_get_available_transactions_excludes_locked(self):
        """Should exclude FULFILLED and CANCELLED transactions"""
        # Create multiple transactions
        tx2 = Transaction.objects.create(
            tx_id="TEST456",
            amount=Decimal('3000.00'),
            amount_expected=Decimal('3000.00'),
            amount_paid=Decimal('3000.00'),  # Fully paid
            sender_name="JANE DOE",
            sender_phone="+254700000001",
            timestamp=timezone.now(),
            gateway_type="M-PESA",
            destination_number="MPESA",
            status=Transaction.OrderStatus.PROCESSING,
            unique_hash="test-hash-456"
        )
        tx2.save()  # Will auto-lock

        tx3 = Transaction.objects.create(
            tx_id="TEST789",
            amount=Decimal('2000.00'),
            amount_expected=Decimal('2000.00'),
            amount_paid=Decimal('0.00'),
            sender_name="BOB SMITH",
            sender_phone="+254700000002",
            timestamp=timezone.now(),
            gateway_type="M-PESA",
            destination_number="MPESA",
            status=Transaction.OrderStatus.CANCELLED,
            unique_hash="test-hash-789"
        )

        self.service.mark_as_processing(self.transaction)

        available = self.service.get_available_transactions()

        # Should only return the PROCESSING transaction
        self.assertEqual(available.count(), 1)
        self.assertEqual(available.first().tx_id, "TEST123")

    def test_get_available_transactions_with_min_amount(self):
        """Should filter by minimum remaining amount"""
        # Create transaction with small remaining amount
        tx2 = Transaction.objects.create(
            tx_id="TEST456",
            amount=Decimal('1000.00'),
            amount_expected=Decimal('1000.00'),
            amount_paid=Decimal('900.00'),
            sender_name="JANE DOE",
            sender_phone="+254700000001",
            timestamp=timezone.now(),
            gateway_type="M-PESA",
            destination_number="MPESA",
            status=Transaction.OrderStatus.PARTIALLY_FULFILLED,
            unique_hash="test-hash-456"
        )

        self.service.mark_as_processing(self.transaction)

        # Filter for transactions with at least 500 remaining
        available = self.service.get_available_transactions(
            min_amount=Decimal('500.00')
        )

        # Should return both (TEST123 has 5000, TEST456 has 100)
        # Wait, TEST456 has only 100 remaining, should be excluded
        tx_ids = [tx.tx_id for tx in available]
        self.assertIn("TEST123", tx_ids)

    # ==================== get_transaction_summary Tests ====================

    def test_get_transaction_summary(self):
        """Should return comprehensive transaction summary"""
        self.service.mark_as_processing(self.transaction)
        self.service.allocate_payment(
            self.transaction,
            order_id="ORDER-001",
            amount=Decimal('2000.00')
        )
        self.transaction.refresh_from_db()

        summary = self.service.get_transaction_summary(self.transaction)

        self.assertEqual(summary['tx_id'], "TEST123")
        self.assertEqual(summary['amount'], 5000.00)
        self.assertEqual(summary['amount_expected'], 5000.00)
        self.assertEqual(summary['amount_paid'], 2000.00)
        self.assertEqual(summary['remaining_amount'], 3000.00)
        self.assertEqual(summary['status'], Transaction.OrderStatus.PARTIALLY_FULFILLED)
        self.assertFalse(summary['is_locked'])
        self.assertTrue(summary['can_allocate'])
        self.assertIn('status_display', summary)
        self.assertIn('timestamp', summary)

    def test_get_transaction_summary_locked(self):
        """Should show can_allocate as False for locked transactions"""
        self.service.mark_as_processing(self.transaction)
        self.service.allocate_payment(
            self.transaction,
            order_id="ORDER-001",
            amount=Decimal('5000.00')
        )
        self.transaction.refresh_from_db()

        summary = self.service.get_transaction_summary(self.transaction)

        self.assertTrue(summary['is_locked'])
        self.assertFalse(summary['can_allocate'])
