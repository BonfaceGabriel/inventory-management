from decimal import Decimal
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from .test_helpers import (
    make_admin, make_gateway, make_transaction, make_product,
    make_authenticated_client, today,
)


class ReportAPITest(APITestCase):
    def setUp(self):
        self.admin = make_admin(username='report_admin')
        self.gateway = make_gateway()
        self.tx = make_transaction(tx_id='RPT-TX', amount=Decimal('1000.00'), gateway=self.gateway)
        self.client = make_authenticated_client(self.admin)

    def test_daily_reconciliation(self):
        response = self.client.get(reverse('daily-reconciliation'), {
            'date': today().isoformat(),
        })
        self.assertEqual(response.status_code, 200)

    def test_daily_reconciliation_v2(self):
        response = self.client.get(reverse('daily-reconciliation-v2'), {
            'date': today().isoformat(),
        })
        self.assertEqual(response.status_code, 200)

    def test_date_range_reconciliation(self):
        start = (today() - timezone.timedelta(days=7)).isoformat()
        end = today().isoformat()
        response = self.client.get(reverse('date-range-reconciliation'), {
            'start_date': start,
            'end_date': end,
        })
        self.assertEqual(response.status_code, 200)

    def test_discrepancies_report(self):
        response = self.client.get(reverse('discrepancies-report'))
        self.assertEqual(response.status_code, 200)

    def test_daily_reconciliation_xlsx(self):
        response = self.client.get(reverse('daily-reconciliation-xlsx'), {
            'date': today().isoformat(),
        })
        self.assertEqual(response.status_code, 200)

    def test_date_range_reconciliation_xlsx(self):
        start = (today() - timezone.timedelta(days=7)).isoformat()
        end = today().isoformat()
        response = self.client.get(reverse('date-range-reconciliation-xlsx'), {
            'start_date': start,
            'end_date': end,
        })
        self.assertEqual(response.status_code, 200)

    def test_stock_report(self):
        response = self.client.get(reverse('stock-report'))
        self.assertEqual(response.status_code, 200)

    def test_stock_report_xlsx(self):
        response = self.client.get(reverse('stock-report-xlsx'))
        self.assertEqual(response.status_code, 200)

    def test_stock_report_historical(self):
        response = self.client.get(reverse('stock-report-historical'), {
            'date': today().isoformat(),
        })
        self.assertEqual(response.status_code, 200)

    def test_stock_report_historical_xlsx(self):
        response = self.client.get(reverse('stock-report-historical-xlsx'), {
            'date': today().isoformat(),
        })
        self.assertEqual(response.status_code, 200)

    def test_stock_report_with_adjustments_xlsx(self):
        response = self.client.get(reverse('stock-report-with-adjustments-xlsx'), {
            'date': today().isoformat(),
        })
        self.assertEqual(response.status_code, 200)

    def test_unified_report_export(self):
        response = self.client.get(reverse('unified-report-export'), {
            'date': today().isoformat(),
        })
        self.assertEqual(response.status_code, 200)
