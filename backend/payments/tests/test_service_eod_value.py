from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from payments.services.eod_value_reconciliation_service import EndOfDayValueReconciliationService
from payments.models import EndOfDayValueReconciliation
from .test_helpers import make_admin, today


class EodValueReconciliationServiceTest(TestCase):
    def setUp(self):
        self.admin = make_admin(username='eod_admin')

    def test_get_or_create_today_creates(self):
        rec = EndOfDayValueReconciliationService.get_or_create_today(self.admin)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.reconciliation_date, today())
        self.assertEqual(rec.status, 'DRAFT')

    def test_get_or_create_today_returns_existing(self):
        first = EndOfDayValueReconciliationService.get_or_create_today(self.admin)
        second = EndOfDayValueReconciliationService.get_or_create_today(self.admin)
        self.assertEqual(first.id, second.id)

    def test_update_today_inputs_sets_values(self):
        rec = EndOfDayValueReconciliationService.get_or_create_today(self.admin)
        result = EndOfDayValueReconciliationService.update_today_inputs(self.admin, {
            'opening_stock_value': '1000.00',
            'replenished_value': '200.00',
            'sales_value': '300.00',
            'stock_value': '800.00',
            'bk_stock': '50.00',
            'duplicated': '20.00',
            'hq_value': '500.00',
            'kitengela_value': '200.00',
            'kitui_value': '100.00',
            'nakuru_value': '50.00',
        })
        self.assertTrue(result['success'])
        rec.refresh_from_db()
        self.assertEqual(rec.opening_stock_value, Decimal('1000.00'))
        self.assertEqual(rec.replenished_value, Decimal('200.00'))
        self.assertEqual(rec.sales_value, Decimal('300.00'))
        self.assertEqual(rec.x_value, Decimal('900.00'))
        self.assertEqual(rec.y_value, Decimal('870.00'))
        self.assertEqual(rec.z_value, Decimal('850.00'))

    def test_update_partial_inputs(self):
        rec = EndOfDayValueReconciliationService.get_or_create_today(self.admin)
        EndOfDayValueReconciliationService.update_today_inputs(self.admin, {
            'opening_stock_value': '5000.00',
            'sales_value': '2000.00',
        })
        rec.refresh_from_db()
        self.assertEqual(rec.opening_stock_value, Decimal('5000.00'))
        self.assertEqual(rec.sales_value, Decimal('2000.00'))

    def test_confirm_today(self):
        rec = EndOfDayValueReconciliationService.get_or_create_today(self.admin)
        EndOfDayValueReconciliationService.update_today_inputs(self.admin, {
            'opening_stock_value': '1000.00',
            'replenished_value': '200.00',
            'sales_value': '300.00',
            'stock_value': '800.00',
        })
        result = EndOfDayValueReconciliationService.confirm_today(self.admin)
        self.assertTrue(result['success'])
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'CONFIRMED')

    def test_confirm_rejects_excessive_variance(self):
        rec = EndOfDayValueReconciliationService.get_or_create_today(self.admin)
        EndOfDayValueReconciliationService.update_today_inputs(self.admin, {
            'opening_stock_value': '100000.00',
            'sales_value': '0.00',
            'stock_value': '100.00',
            'hq_value': '50000.00',
        })
        result = EndOfDayValueReconciliationService.confirm_today(self.admin)
        self.assertFalse(result['success'])
        self.assertIn('threshold', result.get('warning', '').lower())
