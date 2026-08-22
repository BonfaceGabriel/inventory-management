from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APITestCase
from utils.constants import STATUS_COLORS, STATUS_ICONS
from .test_helpers import (
    make_admin, make_gateway, make_product, make_product_line,
    make_device, make_device_client, make_authenticated_client,
)


class ProductAPITest(APITestCase):
    def setUp(self):
        self.admin = make_admin()
        self.line = make_product_line('API Test Line')
        self.product = make_product(
            prod_code='API-PROD', prod_name='API Product',
            price=Decimal('500.00'), quantity=100, product_line=self.line,
        )
        self.product2 = make_product(
            prod_code='API-PROD2', prod_name='API Product 2',
            price=Decimal('300.00'), quantity=50, sku='SKU-API2',
        )
        self.client = make_authenticated_client(self.admin)

    def test_list_products(self):
        response = self.client.get(reverse('product-list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_create_product(self):
        response = self.client.post(reverse('product-list'), {
            'prod_code': 'API-NEW',
            'prod_name': 'New API Product',
            'sku': 'SKU-APINEW',
            'current_price': '1000.00',
            'cost_price': '500.00',
            'current_pv': '0.00',
            'quantity': 50,
            'product_line': self.line.id,
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_create_product_missing_required_field(self):
        response = self.client.post(reverse('product-list'), {
            'prod_code': 'API-BAD',
            'current_price': '100.00',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_get_product_detail(self):
        response = self.client.get(reverse('product-detail', args=[self.product.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['prod_code'], 'API-PROD')

    def test_update_product(self):
        response = self.client.patch(
            reverse('product-detail', args=[self.product.id]),
            {'current_price': '600.00'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_price, Decimal('600.00'))

    def test_delete_product(self):
        response = self.client.delete(reverse('product-detail', args=[self.product.id]))
        self.assertEqual(response.status_code, 204)

    def test_search_product_by_sku(self):
        response = self.client.get(reverse('product-search'), {'sku': 'API-PROD'})
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.data), 0)

    def test_search_product_nonexistent(self):
        response = self.client.get(reverse('product-search'), {'sku': 'NONEXISTENT'})
        self.assertEqual(response.status_code, 404)

    def test_product_summary(self):
        response = self.client.get(reverse('product-summary'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('total_products', response.data)

    def test_list_product_lines(self):
        response = self.client.get(reverse('product-line-list'))
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.data), 0)

    def test_create_product_line(self):
        response = self.client.post(reverse('product-line-list'), {
            'name': 'New Line',
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_inventory_movement_list(self):
        response = self.client.get(reverse('inventory-movement-list'))
        self.assertEqual(response.status_code, 200)


class ProductAPIWithDeviceAuthTest(APITestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.device = make_device(gateway=self.gateway)
        self.client = make_device_client(self.device)
        self.product = make_product(prod_code='DEV-PROD')

    def test_list_products_with_device_auth(self):
        response = self.client.get(reverse('product-list'))
        self.assertEqual(response.status_code, 200)
