from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from payments.services import ManualPaymentService
from payments.models import Transaction, ManualPayment
from .test_helpers import make_admin, make_gateway, make_transaction


class ManualPaymentServiceTest(TestCase):
    def setUp(self):
        self.service = ManualPaymentService()
        self.gateway = make_gateway()
        self.admin = make_admin()
        self.tx = make_transaction(tx_id='MP-SRV-TX', amount=Decimal('5000.00'))

    def test_create_cash_payment(self):
        tx, mp = self.service.create_manual_payment(
            payment_method='CASH',
            payer_name='John Cash',
            amount=Decimal('1000.00'),
            payment_date=timezone.now(),
            created_by=self.admin,
        )
        self.assertIsNotNone(tx)
        self.assertIsNotNone(mp)
        self.assertEqual(mp.payment_method, 'CASH')
        self.assertEqual(mp.amount, Decimal('1000.00'))
        self.assertTrue(tx.tx_id.startswith('MAN-'))

    def test_create_pdq_payment_with_reference(self):
        tx, mp = self.service.create_manual_payment(
            payment_method='PDQ',
            payer_name='Jane PDQ',
            amount=Decimal('2500.00'),
            payment_date=timezone.now(),
            created_by=self.admin,
            reference_number='PDQ-12345',
        )
        self.assertEqual(mp.payment_method, 'PDQ')
        self.assertEqual(mp.reference_number, 'PDQ-12345')

    def test_create_bank_payment_with_reference(self):
        tx, mp = self.service.create_manual_payment(
            payment_method='BANK_TRANSFER',
            payer_name='Bob Bank',
            amount=Decimal('3000.00'),
            payment_date=timezone.now(),
            created_by=self.admin,
            reference_number='BNK-999',
        )
        self.assertEqual(mp.payment_method, 'BANK_TRANSFER')
        self.assertEqual(mp.reference_number, 'BNK-999')

    def test_create_payment_with_phone_and_email(self):
        tx, mp = self.service.create_manual_payment(
            payment_method='CASH',
            payer_name='Test User',
            amount=Decimal('1000.00'),
            payment_date=timezone.now(),
            created_by=self.admin,
            payer_phone='0712345678',
            payer_email='test@example.com',
        )
        self.assertEqual(mp.payer_phone, '0712345678')
        self.assertEqual(mp.payer_email, 'test@example.com')

    def test_create_payment_with_notes(self):
        tx, mp = self.service.create_manual_payment(
            payment_method='CASH',
            payer_name='Notes Test',
            amount=Decimal('500.00'),
            payment_date=timezone.now(),
            created_by=self.admin,
            notes='Test notes field',
        )
        self.assertIn('Test notes field', tx.notes)

    def test_generate_unique_hash_uniqueness(self):
        tx1, _ = self.service.create_manual_payment(
            payment_method='CASH', payer_name='Hash Test 1',
            amount=Decimal('1000.00'), payment_date=timezone.now(),
            created_by=self.admin,
        )
        tx2, _ = self.service.create_manual_payment(
            payment_method='CASH', payer_name='Hash Test 2',
            amount=Decimal('1000.00'), payment_date=timezone.now(),
            created_by=self.admin,
        )
        self.assertNotEqual(tx1.unique_hash, tx2.unique_hash)

    def test_get_manual_payments_summary(self):
        self.service.create_manual_payment(
            payment_method='CASH', payer_name='Summary 1',
            amount=Decimal('1000.00'), payment_date=timezone.now(),
            created_by=self.admin,
        )
        self.service.create_manual_payment(
            payment_method='PDQ', payer_name='Summary 2',
            amount=Decimal('2000.00'), payment_date=timezone.now(),
            created_by=self.admin, reference_number='PDQ-SUM',
        )
        summary = self.service.get_manual_payments_summary()
        self.assertEqual(summary['total_payments'], 2)
        self.assertEqual(summary['total_amount'], Decimal('3000.00'))

    def test_get_manual_payments_summary_by_method(self):
        self.service.create_manual_payment(
            payment_method='CASH', payer_name='Cash Only',
            amount=Decimal('1000.00'), payment_date=timezone.now(),
            created_by=self.admin,
        )
        self.service.create_manual_payment(
            payment_method='PDQ', payer_name='PDQ Only',
            amount=Decimal('2000.00'), payment_date=timezone.now(),
            created_by=self.admin, reference_number='PDQ-FILTER',
        )
        summary = self.service.get_manual_payments_summary(payment_method='CASH')
        self.assertEqual(summary['total_payments'], 1)
        self.assertEqual(summary['total_amount'], Decimal('1000.00'))

    def test_get_manual_payments_summary_empty(self):
        summary = self.service.get_manual_payments_summary()
        self.assertEqual(summary['total_payments'], 0)
        self.assertEqual(summary['total_amount'], Decimal('0.00'))
