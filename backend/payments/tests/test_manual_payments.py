"""
Tests for Manual Payment Entry System

Tests manual payment model, service, and API endpoints.
"""

from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError

from payments.models import Transaction, ManualPayment, Device
from payments.services import ManualPaymentService


class ManualPaymentModelTestCase(TestCase):
    """Test ManualPayment model"""

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
            tx_id="MAN-PDQ-20251009-TEST",
            amount=Decimal('5000.00'),
            amount_expected=Decimal('5000.00'),
            amount_paid=Decimal('0.00'),
            sender_name="JOHN DOE",
            sender_phone="+254700000000",
            timestamp=timezone.now(),
            gateway_type="MANUAL_PDQ",
            destination_number="",
            status=Transaction.OrderStatus.NOT_PROCESSED,
            unique_hash="test-hash-manual-123"
        )

    def test_create_manual_payment(self):
        """Should create manual payment successfully"""
        manual_payment = ManualPayment.objects.create(
            transaction=self.transaction,
            payment_method=ManualPayment.PaymentMethod.PDQ,
            reference_number="PDQ123456",
            payer_name="John Doe",
            payer_phone="+254700000000",
            payer_email="john@example.com",
            amount=Decimal('5000.00'),
            payment_date=timezone.now(),
            notes="Test payment",
            created_by="staff_user_1"
        )

        self.assertEqual(manual_payment.payment_method, ManualPayment.PaymentMethod.PDQ)
        self.assertEqual(manual_payment.amount, Decimal('5000.00'))
        self.assertEqual(manual_payment.payer_name, "John Doe")
        self.assertEqual(manual_payment.created_by, "staff_user_1")

    def test_manual_payment_str(self):
        """Should have descriptive string representation"""
        manual_payment = ManualPayment.objects.create(
            transaction=self.transaction,
            payment_method=ManualPayment.PaymentMethod.PDQ,
            reference_number="PDQ123456",
            payer_name="John Doe",
            amount=Decimal('5000.00'),
            payment_date=timezone.now(),
            created_by="staff_user_1"
        )

        self.assertIn("PDQ", str(manual_payment))
        self.assertIn("5000", str(manual_payment))
        self.assertIn("John Doe", str(manual_payment))

    def test_manual_payment_negative_amount(self):
        """Should raise ValidationError for negative amount"""
        manual_payment = ManualPayment(
            transaction=self.transaction,
            payment_method=ManualPayment.PaymentMethod.CASH,
            payer_name="John Doe",
            amount=Decimal('-100.00'),
            payment_date=timezone.now(),
            created_by="staff_user_1"
        )

        with self.assertRaises(ValidationError):
            manual_payment.full_clean()

    def test_manual_payment_zero_amount(self):
        """Should raise ValidationError for zero amount"""
        manual_payment = ManualPayment(
            transaction=self.transaction,
            payment_method=ManualPayment.PaymentMethod.CASH,
            payer_name="John Doe",
            amount=Decimal('0.00'),
            payment_date=timezone.now(),
            created_by="staff_user_1"
        )

        with self.assertRaises(ValidationError):
            manual_payment.full_clean()

    def test_manual_payment_pdq_requires_reference(self):
        """Should require reference number for PDQ payments"""
        manual_payment = ManualPayment(
            transaction=self.transaction,
            payment_method=ManualPayment.PaymentMethod.PDQ,
            reference_number="",  # Empty reference
            payer_name="John Doe",
            amount=Decimal('1000.00'),
            payment_date=timezone.now(),
            created_by="staff_user_1"
        )

        with self.assertRaises(ValidationError) as cm:
            manual_payment.full_clean()

        self.assertIn('reference_number', str(cm.exception))

    def test_manual_payment_bank_transfer_requires_reference(self):
        """Should require reference number for bank transfers"""
        manual_payment = ManualPayment(
            transaction=self.transaction,
            payment_method=ManualPayment.PaymentMethod.BANK_TRANSFER,
            reference_number="",  # Empty reference
            payer_name="John Doe",
            amount=Decimal('1000.00'),
            payment_date=timezone.now(),
            created_by="staff_user_1"
        )

        with self.assertRaises(ValidationError) as cm:
            manual_payment.full_clean()

        self.assertIn('reference_number', str(cm.exception))

    def test_manual_payment_cash_no_reference_required(self):
        """Cash payments should not require reference number"""
        manual_payment = ManualPayment(
            transaction=self.transaction,
            payment_method=ManualPayment.PaymentMethod.CASH,
            reference_number="",  # No reference
            payer_name="John Doe",
            amount=Decimal('1000.00'),
            payment_date=timezone.now(),
            created_by="staff_user_1"
        )

        # Should not raise ValidationError
        manual_payment.full_clean()


class ManualPaymentServiceTestCase(TestCase):
    """Test ManualPaymentService"""

    def setUp(self):
        """Set up test data"""
        self.service = ManualPaymentService()
        self.payment_date = timezone.now()

    def test_create_manual_payment_pdq(self):
        """Should create manual PDQ payment successfully"""
        transaction, manual_payment = self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.PDQ,
            payer_name="John Doe",
            amount=Decimal('5000.00'),
            payment_date=self.payment_date,
            created_by="staff_user_1",
            reference_number="PDQ123456",
            payer_phone="+254700000000"
        )

        self.assertIsNotNone(transaction)
        self.assertIsNotNone(manual_payment)
        self.assertEqual(transaction.amount, Decimal('5000.00'))
        self.assertEqual(transaction.sender_name, "John Doe")
        self.assertEqual(transaction.gateway_type, "MANUAL_PDQ")
        self.assertEqual(transaction.confidence, 1.0)
        self.assertEqual(manual_payment.payment_method, ManualPayment.PaymentMethod.PDQ)
        self.assertEqual(manual_payment.reference_number, "PDQ123456")

    def test_create_manual_payment_bank_transfer(self):
        """Should create manual bank transfer payment"""
        transaction, manual_payment = self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.BANK_TRANSFER,
            payer_name="Jane Smith",
            amount=Decimal('10000.00'),
            payment_date=self.payment_date,
            created_by="staff_user_2",
            reference_number="BANK789012",
            payer_email="jane@example.com"
        )

        self.assertEqual(transaction.amount, Decimal('10000.00'))
        self.assertEqual(transaction.gateway_type, "MANUAL_BANK_TRANSFER")
        self.assertEqual(manual_payment.payment_method, ManualPayment.PaymentMethod.BANK_TRANSFER)
        self.assertEqual(manual_payment.payer_email, "jane@example.com")

    def test_create_manual_payment_cash(self):
        """Should create manual cash payment"""
        transaction, manual_payment = self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.CASH,
            payer_name="Bob Johnson",
            amount=Decimal('2000.00'),
            payment_date=self.payment_date,
            created_by="staff_user_3",
            notes="Cash payment for walk-in customer"
        )

        self.assertEqual(transaction.amount, Decimal('2000.00'))
        self.assertEqual(transaction.gateway_type, "MANUAL_CASH")
        self.assertEqual(manual_payment.payment_method, ManualPayment.PaymentMethod.CASH)
        self.assertIn("Cash payment for walk-in customer", manual_payment.notes)

    def test_manual_tx_id_format(self):
        """Should generate proper transaction ID format"""
        transaction, _ = self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.PDQ,
            payer_name="Test User",
            amount=Decimal('1000.00'),
            payment_date=self.payment_date,
            created_by="staff_user_1",
            reference_number="TEST123"
        )

        # Should start with MAN-
        self.assertTrue(transaction.tx_id.startswith("MAN-"))
        # Should contain payment method code
        self.assertIn("PDQ", transaction.tx_id)

    def test_manual_payment_unique_hash(self):
        """Should generate unique hash for each payment"""
        transaction1, _ = self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.CASH,
            payer_name="User One",
            amount=Decimal('1000.00'),
            payment_date=self.payment_date,
            created_by="staff_user_1"
        )

        # Different payment should have different hash
        transaction2, _ = self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.CASH,
            payer_name="User Two",
            amount=Decimal('1000.00'),
            payment_date=self.payment_date,
            created_by="staff_user_1"
        )

        self.assertNotEqual(transaction1.unique_hash, transaction2.unique_hash)

    def test_manual_payment_with_notes(self):
        """Should store notes correctly"""
        notes = "Special instruction: Process urgently"
        transaction, manual_payment = self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.PDQ,
            payer_name="Test User",
            amount=Decimal('1000.00'),
            payment_date=self.payment_date,
            created_by="staff_user_1",
            reference_number="PDQ999",
            notes=notes
        )

        self.assertIn(notes, transaction.notes)
        self.assertEqual(manual_payment.notes, notes)

    def test_get_manual_payments_summary_all(self):
        """Should get summary of all manual payments"""
        # Create multiple manual payments
        self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.PDQ,
            payer_name="User 1",
            amount=Decimal('1000.00'),
            payment_date=self.payment_date,
            created_by="staff_user_1",
            reference_number="PDQ001"
        )

        self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.CASH,
            payer_name="User 2",
            amount=Decimal('2000.00'),
            payment_date=self.payment_date,
            created_by="staff_user_1"
        )

        self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.PDQ,
            payer_name="User 3",
            amount=Decimal('1500.00'),
            payment_date=self.payment_date,
            created_by="staff_user_2",
            reference_number="PDQ002"
        )

        summary = self.service.get_manual_payments_summary()

        self.assertEqual(summary['total_count'], 3)
        self.assertEqual(summary['total_amount'], 4500.00)
        self.assertEqual(summary['by_method']['PDQ']['count'], 2)
        self.assertEqual(summary['by_method']['PDQ']['total_amount'], 2500.00)
        self.assertEqual(summary['by_method']['CASH']['count'], 1)
        self.assertEqual(summary['by_method']['CASH']['total_amount'], 2000.00)

    def test_get_manual_payments_summary_filtered_by_method(self):
        """Should filter summary by payment method"""
        # Create payments
        self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.PDQ,
            payer_name="User 1",
            amount=Decimal('1000.00'),
            payment_date=self.payment_date,
            created_by="staff_user_1",
            reference_number="PDQ001"
        )

        self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.CASH,
            payer_name="User 2",
            amount=Decimal('2000.00'),
            payment_date=self.payment_date,
            created_by="staff_user_1"
        )

        # Filter by PDQ only
        summary = self.service.get_manual_payments_summary(
            payment_method=ManualPayment.PaymentMethod.PDQ
        )

        self.assertEqual(summary['total_count'], 1)
        self.assertEqual(summary['total_amount'], 1000.00)

    def test_get_manual_payments_summary_date_range(self):
        """Should filter summary by date range"""
        from datetime import timedelta

        yesterday = timezone.now() - timedelta(days=1)
        today = timezone.now()

        # Create payment from yesterday
        self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.CASH,
            payer_name="User 1",
            amount=Decimal('1000.00'),
            payment_date=yesterday,
            created_by="staff_user_1"
        )

        # Create payment from today
        self.service.create_manual_payment(
            payment_method=ManualPayment.PaymentMethod.CASH,
            payer_name="User 2",
            amount=Decimal('2000.00'),
            payment_date=today,
            created_by="staff_user_1"
        )

        # Filter for today only
        summary = self.service.get_manual_payments_summary(
            start_date=today - timedelta(hours=1)
        )

        # Should only include today's payment
        self.assertEqual(summary['total_count'], 1)
        self.assertEqual(summary['total_amount'], 2000.00)
