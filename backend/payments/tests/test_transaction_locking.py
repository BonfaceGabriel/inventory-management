from django.test import TestCase
from django.core.exceptions import ValidationError
from decimal import Decimal
from ..models import Transaction
from datetime import datetime
from django.utils import timezone


class TransactionLockingTest(TestCase):
    """
    Tests for transaction locking functionality to prevent duplicate fulfillment.
    """

    def setUp(self):
        """Set up test data."""
        self.transaction = Transaction.objects.create(
            tx_id="TEST123",
            amount=Decimal('5000.00'),
            sender_name="JOHN DOE",
            sender_phone="0712345678",
            timestamp=timezone.now(),
            gateway_type='till',
            amount_expected=Decimal('5000.00'),
            amount_paid=Decimal('0.00'),
            unique_hash="testhash123",
            status=Transaction.OrderStatus.NOT_PROCESSED
        )

    def test_remaining_amount_calculation(self):
        """Test that remaining_amount is calculated correctly."""
        self.assertEqual(self.transaction.remaining_amount, Decimal('5000.00'))

        # Update amount_paid
        self.transaction.amount_paid = Decimal('3000.00')
        self.transaction.save()

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.remaining_amount, Decimal('2000.00'))

    def test_is_locked_property_fulfilled(self):
        """Test that FULFILLED transactions are locked."""
        # Must transition through valid states
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        self.transaction.save()

        self.transaction.status = Transaction.OrderStatus.FULFILLED
        self.transaction.save()

        self.transaction.refresh_from_db()
        self.assertTrue(self.transaction.is_locked)

    def test_is_locked_property_cancelled(self):
        """Test that CANCELLED transactions are locked."""
        self.transaction.status = Transaction.OrderStatus.CANCELLED
        self.transaction.save()

        self.transaction.refresh_from_db()
        self.assertTrue(self.transaction.is_locked)

    def test_is_locked_property_not_fulfilled(self):
        """Test that non-FULFILLED/CANCELLED transactions are not locked."""
        for status in [Transaction.OrderStatus.NOT_PROCESSED,
                      Transaction.OrderStatus.PROCESSING,
                      Transaction.OrderStatus.PARTIALLY_FULFILLED]:
            self.transaction.status = status
            self.transaction.save()

            self.transaction.refresh_from_db()
            self.assertFalse(self.transaction.is_locked, f"Status {status} should not be locked")

    def test_cannot_modify_fulfilled_transaction(self):
        """Test that FULFILLED transactions cannot be modified."""
        # Mark as fulfilled
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        self.transaction.save()

        self.transaction.status = Transaction.OrderStatus.FULFILLED
        self.transaction.save()

        self.transaction.refresh_from_db()

        # Try to change status - should raise ValidationError
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        with self.assertRaises(ValidationError) as context:
            self.transaction.save()

        self.assertIn('status', context.exception.message_dict)
        self.assertIn('cannot be modified', str(context.exception))

    def test_cannot_modify_cancelled_transaction(self):
        """Test that CANCELLED transactions cannot be modified."""
        self.transaction.status = Transaction.OrderStatus.CANCELLED
        self.transaction.save()

        self.transaction.refresh_from_db()

        # Try to change status - should raise ValidationError
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        with self.assertRaises(ValidationError) as context:
            self.transaction.save()

        self.assertIn('status', context.exception.message_dict)

    def test_auto_fulfill_when_fully_paid(self):
        """Test that transaction auto-fulfills when amount_paid >= amount_expected."""
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        self.transaction.amount_paid = Decimal('5000.00')
        self.transaction.save()

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, Transaction.OrderStatus.FULFILLED)
        self.assertTrue(self.transaction.is_locked)

    def test_auto_partially_fulfilled_when_partially_paid(self):
        """Test that transaction auto-marks as PARTIALLY_FULFILLED when partially paid."""
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        self.transaction.amount_paid = Decimal('3000.00')
        self.transaction.save()

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, Transaction.OrderStatus.PARTIALLY_FULFILLED)
        self.assertFalse(self.transaction.is_locked)
        self.assertEqual(self.transaction.remaining_amount, Decimal('2000.00'))

    def test_partially_fulfilled_can_be_updated(self):
        """Test that PARTIALLY_FULFILLED transactions can still be updated."""
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        self.transaction.amount_paid = Decimal('3000.00')
        self.transaction.save()

        self.transaction.refresh_from_db()

        # Should be able to add more payment
        self.transaction.amount_paid = Decimal('4000.00')
        self.transaction.save()

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.amount_paid, Decimal('4000.00'))
        self.assertEqual(self.transaction.remaining_amount, Decimal('1000.00'))

    def test_partially_fulfilled_locks_when_fully_paid(self):
        """Test that PARTIALLY_FULFILLED auto-locks when remaining amount reaches zero."""
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        self.transaction.amount_paid = Decimal('3000.00')
        self.transaction.save()

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, Transaction.OrderStatus.PARTIALLY_FULFILLED)

        # Complete the payment
        self.transaction.amount_paid = Decimal('5000.00')
        self.transaction.save()

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, Transaction.OrderStatus.FULFILLED)
        self.assertTrue(self.transaction.is_locked)

    def test_amount_paid_cannot_exceed_amount_expected(self):
        """Test that amount_paid cannot exceed amount_expected."""
        self.transaction.amount_paid = Decimal('6000.00')  # More than expected

        with self.assertRaises(ValidationError) as context:
            self.transaction.save()

        self.assertIn('amount_paid', context.exception.message_dict)

    def test_valid_status_transitions(self):
        """Test valid status transitions."""
        # NOT_PROCESSED → PROCESSING
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        self.transaction.save()
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, Transaction.OrderStatus.PROCESSING)

        # PROCESSING → PARTIALLY_FULFILLED
        self.transaction.amount_paid = Decimal('1000.00')
        self.transaction.save()
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, Transaction.OrderStatus.PARTIALLY_FULFILLED)

        # PARTIALLY_FULFILLED → FULFILLED
        self.transaction.amount_paid = Decimal('5000.00')
        self.transaction.save()
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, Transaction.OrderStatus.FULFILLED)

    def test_invalid_status_transitions(self):
        """Test that invalid status transitions are blocked."""
        # Try NOT_PROCESSED → FULFILLED (invalid, should go through PROCESSING)
        self.transaction.status = Transaction.OrderStatus.FULFILLED

        with self.assertRaises(ValidationError) as context:
            self.transaction.save()

        self.assertIn('status', context.exception.message_dict)

    def test_can_transition_to_method(self):
        """Test the can_transition_to method."""
        # NOT_PROCESSED can go to PROCESSING or CANCELLED
        self.assertTrue(self.transaction.can_transition_to(Transaction.OrderStatus.PROCESSING))
        self.assertTrue(self.transaction.can_transition_to(Transaction.OrderStatus.CANCELLED))
        self.assertFalse(self.transaction.can_transition_to(Transaction.OrderStatus.FULFILLED))

        # Move to PROCESSING
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        self.transaction.save()

        # PROCESSING can go to PARTIALLY_FULFILLED, FULFILLED, or CANCELLED
        self.assertTrue(self.transaction.can_transition_to(Transaction.OrderStatus.PARTIALLY_FULFILLED))
        self.assertTrue(self.transaction.can_transition_to(Transaction.OrderStatus.FULFILLED))
        self.assertTrue(self.transaction.can_transition_to(Transaction.OrderStatus.CANCELLED))

    def test_locked_transactions_cannot_transition(self):
        """Test that locked transactions cannot transition to any status."""
        # First transition through valid states
        self.transaction.status = Transaction.OrderStatus.PROCESSING
        self.transaction.save()

        self.transaction.status = Transaction.OrderStatus.FULFILLED
        self.transaction.amount_paid = self.transaction.amount_expected
        self.transaction.save()

        self.transaction.refresh_from_db()

        # Locked transactions cannot transition
        self.assertFalse(self.transaction.can_transition_to(Transaction.OrderStatus.PROCESSING))
        self.assertFalse(self.transaction.can_transition_to(Transaction.OrderStatus.CANCELLED))

    def test_cancellation_at_any_unlocked_stage(self):
        """Test that transactions can be cancelled at any unlocked stage."""
        # Cancel from NOT_PROCESSED
        self.transaction.status = Transaction.OrderStatus.CANCELLED
        self.transaction.save()
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, Transaction.OrderStatus.CANCELLED)
        self.assertTrue(self.transaction.is_locked)

        # Create new transaction and cancel from PROCESSING
        transaction2 = Transaction.objects.create(
            tx_id="TEST456",
            amount=Decimal('3000.00'),
            sender_name="JANE DOE",
            sender_phone="0787654321",
            timestamp=timezone.now(),
            gateway_type='paybill',
            amount_expected=Decimal('3000.00'),
            amount_paid=Decimal('0.00'),
            unique_hash="testhash456",
            status=Transaction.OrderStatus.PROCESSING
        )
        transaction2.status = Transaction.OrderStatus.CANCELLED
        transaction2.save()
        transaction2.refresh_from_db()
        self.assertEqual(transaction2.status, Transaction.OrderStatus.CANCELLED)
        self.assertTrue(transaction2.is_locked)
