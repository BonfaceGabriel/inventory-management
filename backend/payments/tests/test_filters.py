"""
Tests for Enhanced Transaction and Manual Payment Filters

Tests all filtering capabilities including:
- Date range filters
- Amount range filters
- Status filters
- Text search filters
- Combined filters
"""

from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from payments.models import Transaction, ManualPayment, Device
from payments.filters import TransactionFilter, ManualPaymentFilter


class TransactionFilterTestCase(TestCase):
    """Test TransactionFilter"""

    def setUp(self):
        """Create test transactions"""
        self.device = Device.objects.create(
            name="Test Device",
            phone_number="+254700000000",
            default_gateway="M-PESA",
            gateway_number="MPESA",
            api_key="test-api-key-123"
        )

        self.now = timezone.now()
        self.yesterday = self.now - timedelta(days=1)
        self.tomorrow = self.now + timedelta(days=1)

        # Transaction 1: NOT_PROCESSED, M-PESA, 5000
        self.tx1 = Transaction.objects.create(
            tx_id="TX001",
            amount=Decimal('5000.00'),
            amount_expected=Decimal('5000.00'),
            amount_paid=Decimal('0.00'),
            sender_name="JOHN DOE",
            sender_phone="+254700000001",
            timestamp=self.yesterday,
            gateway_type="M-PESA",
            status=Transaction.OrderStatus.NOT_PROCESSED,
            confidence=0.95,
            unique_hash="hash1"
        )

        # Transaction 2: PROCESSING, Manual PDQ, 3000
        self.tx2 = Transaction.objects.create(
            tx_id="MAN-PDQ-001",
            amount=Decimal('3000.00'),
            amount_expected=Decimal('3000.00'),
            amount_paid=Decimal('0.00'),
            sender_name="JANE SMITH",
            sender_phone="+254700000002",
            timestamp=self.now,
            gateway_type="MANUAL_PDQ",
            status=Transaction.OrderStatus.PROCESSING,
            confidence=1.0,
            unique_hash="hash2"
        )

        # Transaction 3: PARTIALLY_FULFILLED, M-PESA, 10000 (paid 6000)
        self.tx3 = Transaction.objects.create(
            tx_id="TX003",
            amount=Decimal('10000.00'),
            amount_expected=Decimal('10000.00'),
            amount_paid=Decimal('6000.00'),
            sender_name="BOB JOHNSON",
            sender_phone="+254700000003",
            timestamp=self.now,
            gateway_type="M-PESA",
            status=Transaction.OrderStatus.PARTIALLY_FULFILLED,
            confidence=0.85,
            notes="Partial payment received",
            unique_hash="hash3"
        )

        # Transaction 4: FULFILLED, M-PESA, 2000
        self.tx4 = Transaction.objects.create(
            tx_id="TX004",
            amount=Decimal('2000.00'),
            amount_expected=Decimal('2000.00'),
            amount_paid=Decimal('2000.00'),
            sender_name="ALICE BROWN",
            sender_phone="+254700000004",
            timestamp=self.tomorrow,
            gateway_type="M-PESA",
            status=Transaction.OrderStatus.FULFILLED,
            confidence=0.90,
            unique_hash="hash4"
        )

    # ==================== Date Range Filters ====================

    def test_filter_by_min_date(self):
        """Should filter transactions after minimum date"""
        filterset = TransactionFilter(
            data={'min_date': self.now.isoformat()},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should include tx2, tx3, tx4 (now and tomorrow)
        self.assertIn(self.tx2, results)
        self.assertIn(self.tx3, results)
        self.assertIn(self.tx4, results)
        self.assertNotIn(self.tx1, results)  # yesterday

    def test_filter_by_max_date(self):
        """Should filter transactions before maximum date"""
        filterset = TransactionFilter(
            data={'max_date': self.now.isoformat()},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should include tx1, tx2, tx3 (yesterday and now)
        self.assertIn(self.tx1, results)
        self.assertIn(self.tx2, results)
        self.assertIn(self.tx3, results)
        self.assertNotIn(self.tx4, results)  # tomorrow

    def test_filter_by_date_range(self):
        """Should filter transactions within date range"""
        filterset = TransactionFilter(
            data={
                'min_date': (self.now - timedelta(hours=1)).isoformat(),
                'max_date': (self.now + timedelta(hours=1)).isoformat()
            },
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should only include tx2 and tx3 (now)
        self.assertIn(self.tx2, results)
        self.assertIn(self.tx3, results)
        self.assertNotIn(self.tx1, results)  # yesterday
        self.assertNotIn(self.tx4, results)  # tomorrow

    # ==================== Amount Range Filters ====================

    def test_filter_by_min_amount(self):
        """Should filter transactions with minimum amount"""
        filterset = TransactionFilter(
            data={'min_amount': 5000},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should include tx1 (5000) and tx3 (10000)
        self.assertIn(self.tx1, results)
        self.assertIn(self.tx3, results)
        self.assertNotIn(self.tx2, results)  # 3000
        self.assertNotIn(self.tx4, results)  # 2000

    def test_filter_by_max_amount(self):
        """Should filter transactions with maximum amount"""
        filterset = TransactionFilter(
            data={'max_amount': 5000},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should include tx1 (5000), tx2 (3000), tx4 (2000)
        self.assertIn(self.tx1, results)
        self.assertIn(self.tx2, results)
        self.assertIn(self.tx4, results)
        self.assertNotIn(self.tx3, results)  # 10000

    def test_filter_by_amount_range(self):
        """Should filter transactions within amount range"""
        filterset = TransactionFilter(
            data={'min_amount': 3000, 'max_amount': 6000},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should include tx1 (5000) and tx2 (3000)
        self.assertIn(self.tx1, results)
        self.assertIn(self.tx2, results)
        self.assertNotIn(self.tx3, results)  # 10000
        self.assertNotIn(self.tx4, results)  # 2000

    # ==================== Confidence Filters ====================

    def test_filter_by_min_confidence(self):
        """Should filter transactions with minimum confidence"""
        filterset = TransactionFilter(
            data={'min_confidence': 0.90},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should include tx1 (0.95), tx2 (1.0), tx4 (0.90)
        self.assertIn(self.tx1, results)
        self.assertIn(self.tx2, results)
        self.assertIn(self.tx4, results)
        self.assertNotIn(self.tx3, results)  # 0.85

    # ==================== Text Search Filters ====================

    def test_filter_by_sender_name(self):
        """Should filter transactions by sender name"""
        filterset = TransactionFilter(
            data={'sender_name': 'john'},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should only include tx1 (JOHN DOE) and tx3 (BOB JOHNSON)
        self.assertIn(self.tx1, results)
        self.assertIn(self.tx3, results)
        self.assertEqual(len(results), 2)

    def test_filter_by_sender_phone(self):
        """Should filter transactions by sender phone"""
        filterset = TransactionFilter(
            data={'sender_phone': '00001'},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should only include tx1
        self.assertEqual(len(results), 1)
        self.assertIn(self.tx1, results)

    def test_filter_by_notes_contains(self):
        """Should filter transactions by notes content"""
        filterset = TransactionFilter(
            data={'notes_contains': 'partial'},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should only include tx3
        self.assertEqual(len(results), 1)
        self.assertIn(self.tx3, results)

    # ==================== Status Filters ====================

    def test_filter_by_status(self):
        """Should filter transactions by status"""
        filterset = TransactionFilter(
            data={'status': Transaction.OrderStatus.PROCESSING},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should only include tx2
        self.assertEqual(len(results), 1)
        self.assertIn(self.tx2, results)

    def test_filter_is_locked_true(self):
        """Should filter locked transactions"""
        filterset = TransactionFilter(
            data={'is_locked': 'true'},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should only include tx4 (FULFILLED)
        self.assertEqual(len(results), 1)
        self.assertIn(self.tx4, results)

    def test_filter_is_locked_false(self):
        """Should filter unlocked transactions"""
        filterset = TransactionFilter(
            data={'is_locked': 'false'},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should include tx1, tx2, tx3 (not locked)
        self.assertIn(self.tx1, results)
        self.assertIn(self.tx2, results)
        self.assertIn(self.tx3, results)
        self.assertNotIn(self.tx4, results)

    def test_filter_is_available_true(self):
        """Should filter available transactions"""
        filterset = TransactionFilter(
            data={'is_available': 'true'},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should include tx1, tx2, tx3 (not locked and have remaining amount)
        self.assertIn(self.tx1, results)
        self.assertIn(self.tx2, results)
        self.assertIn(self.tx3, results)
        self.assertNotIn(self.tx4, results)  # Fully paid

    def test_filter_is_available_false(self):
        """Should filter unavailable transactions"""
        filterset = TransactionFilter(
            data={'is_available': 'false'},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should only include tx4 (locked/fulfilled)
        self.assertEqual(len(results), 1)
        self.assertIn(self.tx4, results)

    # ==================== Gateway Filters ====================

    def test_filter_by_gateway_type(self):
        """Should filter transactions by gateway type"""
        filterset = TransactionFilter(
            data={'gateway_type': 'M-PESA'},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should include tx1, tx3, tx4 (M-PESA)
        self.assertIn(self.tx1, results)
        self.assertIn(self.tx3, results)
        self.assertIn(self.tx4, results)
        self.assertNotIn(self.tx2, results)  # MANUAL_PDQ

    def test_filter_is_manual_payment_true(self):
        """Should filter manual payment transactions"""
        filterset = TransactionFilter(
            data={'is_manual_payment': 'true'},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should only include tx2 (MANUAL_PDQ)
        self.assertEqual(len(results), 1)
        self.assertIn(self.tx2, results)

    def test_filter_is_manual_payment_false(self):
        """Should filter non-manual payment transactions"""
        filterset = TransactionFilter(
            data={'is_manual_payment': 'false'},
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should include tx1, tx3, tx4 (M-PESA)
        self.assertIn(self.tx1, results)
        self.assertIn(self.tx3, results)
        self.assertIn(self.tx4, results)
        self.assertNotIn(self.tx2, results)

    # ==================== Combined Filters ====================

    def test_combined_filters(self):
        """Should apply multiple filters together"""
        filterset = TransactionFilter(
            data={
                'min_amount': 3000,
                'max_amount': 10000,
                'is_locked': 'false',
                'gateway_type': 'M-PESA'
            },
            queryset=Transaction.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should only include tx1 (5000, M-PESA, unlocked) and tx3 (10000, M-PESA, unlocked)
        self.assertIn(self.tx1, results)
        self.assertIn(self.tx3, results)
        self.assertEqual(len(results), 2)


class ManualPaymentFilterTestCase(TestCase):
    """Test ManualPaymentFilter"""

    def setUp(self):
        """Create test manual payments"""
        self.now = timezone.now()
        self.yesterday = self.now - timedelta(days=1)

        # Create transactions first
        tx1 = Transaction.objects.create(
            tx_id="MAN-PDQ-001",
            amount=Decimal('5000.00'),
            amount_expected=Decimal('5000.00'),
            amount_paid=Decimal('0.00'),
            sender_name="JOHN DOE",
            timestamp=self.yesterday,
            gateway_type="MANUAL_PDQ",
            status=Transaction.OrderStatus.NOT_PROCESSED,
            unique_hash="hash1"
        )

        tx2 = Transaction.objects.create(
            tx_id="MAN-CASH-001",
            amount=Decimal('2000.00'),
            amount_expected=Decimal('2000.00'),
            amount_paid=Decimal('0.00'),
            sender_name="JANE SMITH",
            timestamp=self.now,
            gateway_type="MANUAL_CASH",
            status=Transaction.OrderStatus.NOT_PROCESSED,
            unique_hash="hash2"
        )

        # Create manual payments
        self.mp1 = ManualPayment.objects.create(
            transaction=tx1,
            payment_method=ManualPayment.PaymentMethod.PDQ,
            reference_number="PDQ123456",
            payer_name="John Doe",
            payer_phone="+254700000001",
            amount=Decimal('5000.00'),
            payment_date=self.yesterday,
            notes="Large payment",
            created_by="staff_user_1"
        )

        self.mp2 = ManualPayment.objects.create(
            transaction=tx2,
            payment_method=ManualPayment.PaymentMethod.CASH,
            payer_name="Jane Smith",
            amount=Decimal('2000.00'),
            payment_date=self.now,
            notes="Small cash payment",
            created_by="staff_user_2"
        )

    def test_filter_by_payment_method(self):
        """Should filter by payment method"""
        filterset = ManualPaymentFilter(
            data={'payment_method': ManualPayment.PaymentMethod.PDQ},
            queryset=ManualPayment.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        self.assertEqual(len(results), 1)
        self.assertIn(self.mp1, results)

    def test_filter_by_created_by(self):
        """Should filter by creator"""
        filterset = ManualPaymentFilter(
            data={'created_by': 'staff_user_1'},
            queryset=ManualPayment.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        self.assertEqual(len(results), 1)
        self.assertIn(self.mp1, results)

    def test_filter_by_amount_range(self):
        """Should filter by amount range"""
        filterset = ManualPaymentFilter(
            data={'min_amount': 3000, 'max_amount': 6000},
            queryset=ManualPayment.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        self.assertEqual(len(results), 1)
        self.assertIn(self.mp1, results)

    def test_filter_by_payer_name(self):
        """Should filter by payer name"""
        filterset = ManualPaymentFilter(
            data={'payer_name': 'john'},
            queryset=ManualPayment.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        self.assertEqual(len(results), 1)
        self.assertIn(self.mp1, results)

    def test_filter_by_reference_number(self):
        """Should filter by reference number"""
        filterset = ManualPaymentFilter(
            data={'reference_number': 'PDQ'},
            queryset=ManualPayment.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        self.assertEqual(len(results), 1)
        self.assertIn(self.mp1, results)

    def test_filter_by_notes(self):
        """Should filter by notes content"""
        filterset = ManualPaymentFilter(
            data={'notes_contains': 'large'},
            queryset=ManualPayment.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        self.assertEqual(len(results), 1)
        self.assertIn(self.mp1, results)

    def test_filter_by_payment_date_range(self):
        """Should filter by payment date range"""
        filterset = ManualPaymentFilter(
            data={
                'payment_date_after': (self.now - timedelta(hours=1)).isoformat(),
                'payment_date_before': (self.now + timedelta(hours=1)).isoformat()
            },
            queryset=ManualPayment.objects.all()
        )

        self.assertTrue(filterset.is_valid())
        results = list(filterset.qs)

        # Should only include mp2 (today)
        self.assertEqual(len(results), 1)
        self.assertIn(self.mp2, results)
