from decimal import Decimal
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService
from .test_helpers import (
    make_admin, make_product, make_gateway, make_transaction,
    make_daily_stock_reconciliation, make_stock_adjustment_item,
    make_authenticated_client, today,
)


class ReconciliationAPITest(APITestCase):
    def setUp(self):
        self.admin = make_admin(username='recon_api_admin')
        self.product = make_product(prod_code='API-RECON', quantity=100)
        self.gateway = make_gateway()
        self.client = make_authenticated_client(self.admin)

    def test_create_reconciliation(self):
        response = self.client.post(reverse('stock-reconciliation-create'), {}, format='json')
        self.assertEqual(response.status_code, 201)

    def test_get_reconciliation_by_date(self):
        rec = make_daily_stock_reconciliation(created_by=self.admin)
        response = self.client.get(reverse('stock-reconciliation-by-date'), {
            'date': rec.reconciliation_date.isoformat(),
        })
        self.assertEqual(response.status_code, 200)

    def test_get_reconciliation_detail(self):
        rec = make_daily_stock_reconciliation(created_by=self.admin)
        url = reverse('stock-reconciliation-detail', args=[rec.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_update_adjustment(self):
        rec = make_daily_stock_reconciliation(created_by=self.admin)
        url = reverse('stock-reconciliation-adjust', args=[rec.id])
        response = self.client.patch(url, {
            'product_id': self.product.id,
            'product_total': float(self.product.current_price),
        }, format='json')
        self.assertEqual(response.status_code, 200)

    def test_bulk_update_adjustments(self):
        rec = make_daily_stock_reconciliation(created_by=self.admin)
        url = reverse('stock-reconciliation-adjust-bulk', args=[rec.id])
        response = self.client.post(url, {
            'adjustments': [{
                'product_id': self.product.id,
                'product_total': float(self.product.current_price),
                'quantity_added': 10,
                'quantity_deducted': 5,
            }]
        }, format='json')
        self.assertEqual(response.status_code, 200)

    def test_confirm_reconciliation(self):
        rec = make_daily_stock_reconciliation(created_by=self.admin)
        adj = make_stock_adjustment_item(
            reconciliation=rec, product=self.product,
            opening_stock=100, closing_stock=100,
        )
        url = reverse('stock-reconciliation-confirm', args=[rec.id])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_cancel_reconciliation(self):
        rec = make_daily_stock_reconciliation(created_by=self.admin)
        url = reverse('stock-reconciliation-cancel', args=[rec.id])
        response = self.client.delete(url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_set_baseline(self):
        rec = make_daily_stock_reconciliation(created_by=self.admin)
        make_stock_adjustment_item(
            reconciliation=rec, product=self.product,
            opening_stock=100, closing_stock=100,
        )
        url = reverse('stock-reconciliation-set-baseline', args=[rec.id])
        response = self.client.post(url, {
            'product_id': self.product.id,
            'baseline_qty': 90,
        }, format='json')
        self.assertEqual(response.status_code, 200)

    def test_clear_baseline(self):
        rec = make_daily_stock_reconciliation(created_by=self.admin)
        make_stock_adjustment_item(
            reconciliation=rec, product=self.product,
            opening_stock=100, closing_stock=100,
        )
        url = reverse('stock-reconciliation-clear-baseline', args=[rec.id])
        response = self.client.delete(url, {}, format='json')
        self.assertEqual(response.status_code, 200)
