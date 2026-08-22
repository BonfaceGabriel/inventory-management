from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from payments.services.analytics_service import AnalyticsService
from .test_helpers import (
    make_admin, make_gateway, make_transaction, make_product,
    make_line_item, today, now,
)


class AnalyticsServiceTest(TestCase):
    def setUp(self):
        self.till_gw = make_gateway(
            name='Analytics Till', gateway_type='MPESA_TILL', gateway_number='ANAL-TILL',
        )
        self.tx = make_transaction(
            tx_id='ANAL-TX-1', amount=Decimal('5000.00'),
            gateway=self.till_gw, status='FULFILLED',
            amount_fulfilled=Decimal('5000.00'),
        )

    def test_parse_date_range_defaults(self):
        start, end = AnalyticsService.parse_date_range(None, None)
        self.assertIsNotNone(start)
        self.assertIsNotNone(end)

    def test_parse_date_range_with_values(self):
        start, end = AnalyticsService.parse_date_range('2026-01-01', '2026-01-31')
        self.assertEqual(start.date(), timezone.datetime(2026, 1, 1).date())
        self.assertEqual(end.date(), timezone.datetime(2026, 1, 31).date())

    def test_revenue_analytics_returns_structure(self):
        result = AnalyticsService.revenue_analytics(
            start_date=today() - timezone.timedelta(days=1),
            end_date=today() + timezone.timedelta(days=1),
        )
        self.assertIn('total_revenue', result)
        self.assertIn('transactions', result)
        self.assertIn('gateway_breakdown', result)

    def test_revenue_analytics_with_fulfilled_tx(self):
        result = AnalyticsService.revenue_analytics(
            start_date=today() - timezone.timedelta(days=1),
            end_date=today() + timezone.timedelta(days=1),
        )
        self.assertEqual(result['total_revenue'], 5000.0)
        self.assertEqual(result['transactions'], 1)

    def test_revenue_analytics_excludes_unfulfilled(self):
        tx2 = make_transaction(
            tx_id='ANAL-TX-2', amount=Decimal('3000.00'),
            gateway=self.till_gw, status='NOT_PROCESSED',
            unique_hash='hash_anal2',
        )
        result = AnalyticsService.revenue_analytics(
            start_date=today() - timezone.timedelta(days=1),
            end_date=today() + timezone.timedelta(days=1),
        )
        self.assertEqual(result['transactions'], 1)

    def test_product_analytics_returns_structure(self):
        product = make_product(prod_code='ANAL-PROD', price=Decimal('500.00'), quantity=100)
        make_line_item(self.tx, product, quantity=2)
        for li in self.tx.line_items.all():
            li.is_inventory_deducted = True
            li.save()
        result = AnalyticsService.product_analytics(
            start_date=today() - timezone.timedelta(days=1),
            end_date=today() + timezone.timedelta(days=1),
        )
        self.assertIsInstance(result, list)

    def test_merchandise_analytics_returns_structure(self):
        result = AnalyticsService.merchandise_analytics(
            start_date=today() - timezone.timedelta(days=1),
            end_date=today() + timezone.timedelta(days=1),
        )
        self.assertIsInstance(result, list)

    def test_revenue_analytics_with_granularity(self):
        result = AnalyticsService.revenue_analytics(
            start_date=today() - timezone.timedelta(days=1),
            end_date=today() + timezone.timedelta(days=1),
            granularity='day',
        )
        self.assertIn('total_revenue', result)

    def test_revenue_analytics_excludes_cancelled(self):
        make_transaction(
            tx_id='ANAL-TX-3', amount=Decimal('2000.00'),
            gateway=self.till_gw, status='CANCELLED',
            unique_hash='hash_anal3',
        )
        result = AnalyticsService.revenue_analytics(
            start_date=today() - timezone.timedelta(days=1),
            end_date=today() + timezone.timedelta(days=1),
        )
        self.assertEqual(result['transactions'], 1)
