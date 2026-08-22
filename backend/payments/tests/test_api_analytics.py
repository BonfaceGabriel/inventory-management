from decimal import Decimal
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from .test_helpers import (
    make_admin, make_gateway, make_transaction,
    make_authenticated_client, today,
)


class AnalyticsAPITest(APITestCase):
    def setUp(self):
        self.admin = make_admin(username='analytics_admin')
        self.gateway = make_gateway()
        self.tx = make_transaction(
            tx_id='ANAL-API-TX', amount=Decimal('5000.00'),
            gateway=self.gateway, status='FULFILLED',
            amount_fulfilled=Decimal('5000.00'),
        )
        self.client = make_authenticated_client(self.admin)
        self.start = (today() - timezone.timedelta(days=1)).isoformat()
        self.end = (today() + timezone.timedelta(days=1)).isoformat()

    def test_analytics_overview(self):
        response = self.client.get(reverse('analytics-overview'), {
            'start_date': self.start, 'end_date': self.end,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('total_revenue', response.data)

    def test_analytics_revenue(self):
        response = self.client.get(reverse('analytics-revenue'), {
            'start_date': self.start, 'end_date': self.end,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('total_revenue', response.data)

    def test_analytics_revenue_with_granularity(self):
        response = self.client.get(reverse('analytics-revenue'), {
            'start_date': self.start, 'end_date': self.end,
            'granularity': 'day',
        })
        self.assertEqual(response.status_code, 200)

    def test_analytics_products(self):
        response = self.client.get(reverse('analytics-products'), {
            'start_date': self.start, 'end_date': self.end,
        })
        self.assertEqual(response.status_code, 200)

    def test_analytics_merchandise(self):
        response = self.client.get(reverse('analytics-merchandise'), {
            'start_date': self.start, 'end_date': self.end,
        })
        self.assertEqual(response.status_code, 200)

    def test_analytics_without_dates(self):
        response = self.client.get(reverse('analytics-overview'))
        self.assertEqual(response.status_code, 200)

    def test_analytics_unauthenticated(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        response = anon.get(reverse('analytics-overview'))
        self.assertEqual(response.status_code, 401)
