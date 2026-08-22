from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APITestCase
from payments.models import EndOfDayValueReconciliation
from .test_helpers import (
    make_admin, make_authenticated_client, today,
)


class EODValueAPITest(APITestCase):
    def setUp(self):
        self.admin = make_admin(username='eod_api_admin')
        self.client = make_authenticated_client(self.admin)

    def test_get_today_creates(self):
        response = self.client.get(reverse('eod-value-reconciliation-today'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['reconciliation_date'], today().isoformat())

    def test_get_today_returns_existing(self):
        self.client.get(reverse('eod-value-reconciliation-today'))
        response = self.client.get(reverse('eod-value-reconciliation-today'))
        self.assertEqual(response.status_code, 200)

    def test_update_today_inputs(self):
        self.client.get(reverse('eod-value-reconciliation-today'))
        response = self.client.patch(reverse('eod-value-reconciliation-update-today'), {
            'opening_stock_value': '1000.00',
            'replenished_value': '200.00',
            'sales_value': '300.00',
            'stock_value': '800.00',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['success'])

    def test_confirm_today(self):
        self.client.get(reverse('eod-value-reconciliation-today'))
        self.client.patch(reverse('eod-value-reconciliation-update-today'), {
            'opening_stock_value': '1000.00',
            'replenished_value': '200.00',
            'sales_value': '300.00',
            'stock_value': '800.00',
        }, format='json')
        response = self.client.post(reverse('eod-value-reconciliation-confirm-today'), {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_update_rejects_excessive_variance(self):
        self.client.get(reverse('eod-value-reconciliation-today'))
        self.client.patch(reverse('eod-value-reconciliation-update-today'), {
            'opening_stock_value': '100000.00',
            'sales_value': '0.00',
            'stock_value': '100.00',
            'hq_value': '50000.00',
        }, format='json')
        response = self.client.post(reverse('eod-value-reconciliation-confirm-today'), {}, format='json')
        self.assertTrue('warning' in response.data.get('warning', '') or not response.data.get('success'))
