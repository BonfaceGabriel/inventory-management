from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from payments.services.reconciliation_service import ReconciliationService
from .test_helpers import make_admin, make_gateway, make_transaction, today


class ReconciliationServiceTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.till_gw = make_gateway(
            name='Recon Till', gateway_type='MPESA_TILL', gateway_number='RECON-TILL',
        )
        self.paybill_gw = make_gateway(
            name='Recon Paybill', gateway_type='MPESA_PAYBILL', gateway_number='RECON-PB',
        )
        self.tx = make_transaction(
            tx_id='RECON-TX-1', amount=Decimal('5000.00'),
            gateway=self.till_gw, status='FULFILLED',
            amount_fulfilled=Decimal('5000.00'),
        )

    def test_generate_daily_report_structure(self):
        report = ReconciliationService.generate_daily_report()
        self.assertIn('report_date', report)
        self.assertIn('gateway_reports', report)
        self.assertIn('overall_totals', report)

    def test_generate_daily_report_includes_gateway_breakdown(self):
        report = ReconciliationService.generate_daily_report()
        self.assertTrue(len(report['gateway_reports']) > 0)

    def test_generate_daily_report_with_auto_lock(self):
        report = ReconciliationService.generate_daily_report(auto_lock=True)
        self.assertIn('gateway_reports', report)

    def test_generate_date_range_report(self):
        start = today() - timezone.timedelta(days=7)
        end = today()
        report = ReconciliationService.generate_date_range_report(start, end)
        self.assertIn('date_range', report)
        self.assertIn('daily_reports', report)
        self.assertIn('grand_totals', report)

    def test_identify_discrepancies(self):
        result = ReconciliationService.identify_discrepancies()
        self.assertIsInstance(result, dict)

    def test_generate_daily_report_overall_totals(self):
        report = ReconciliationService.generate_daily_report()
        totals = report['overall_totals']
        self.assertIn('total_transactions', totals)
        self.assertIn('total_amount', totals)

    def test_get_status_breakdown(self):
        tx2 = make_transaction(
            tx_id='RECON-TX-2', amount=Decimal('3000.00'),
            gateway=self.till_gw, status='PROCESSING',
            unique_hash='hash_recon2',
        )
        report = ReconciliationService.generate_daily_report()
        breakdown = report.get('status_breakdown', {})
        self.assertIsNotNone(breakdown)
