from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APITestCase
from .test_helpers import (
    make_admin, make_gateway, make_transaction, make_product,
    make_issuer, make_location, make_device_client, make_device,
)


class CombinedOrderAPITest(APITestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.product = make_product(prod_code='API-CO', price=Decimal('500.00'), quantity=100)
        self.tx1 = make_transaction(tx_id='API-CO-1', amount=Decimal('1000.00'))
        self.tx2 = make_transaction(tx_id='API-CO-2', amount=Decimal('500.00'), unique_hash='hash_api_co2')
        self.admin = make_admin()
        self.issuer = make_issuer()
        self.location = make_location()
        self.device = make_device(gateway=self.gateway)
        self.client = make_device_client(self.device)

    def test_create_combined_order(self):
        url = reverse('combined-order-list-create')
        response = self.client.post(url, {
            'transaction_ids': [self.tx1.id, self.tx2.id],
            'created_by': self.admin.username,
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_create_combined_order_with_single_tx_fails(self):
        url = reverse('combined-order-list-create')
        response = self.client.post(url, {
            'transaction_ids': [self.tx1.id],
            'created_by': self.admin.username,
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_create_combined_order_with_empty_list_fails(self):
        url = reverse('combined-order-list-create')
        response = self.client.post(url, {
            'transaction_ids': [],
            'created_by': self.admin.username,
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_list_combined_orders(self):
        url = reverse('combined-order-list-create')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_get_combined_order_detail(self):
        from payments.services.combined_order_service import CombinedOrderService
        result = CombinedOrderService.create_combined_order(
            transaction_ids=[self.tx1.id, self.tx2.id],
            created_by=self.admin.username,
            created_by_user=self.admin,
            location=self.location,
        )
        url = reverse('combined-order-detail', args=[result['combined_order_id']])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['combined_order_id'], result['combined_order_id'])

    def test_get_nonexistent_combined_order(self):
        url = reverse('combined-order-detail', args=['CMB-NONEXISTENT'])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_activate_combined_order(self):
        from payments.services.combined_order_service import CombinedOrderService
        result = CombinedOrderService.create_combined_order(
            transaction_ids=[self.tx1.id, self.tx2.id],
            created_by=self.admin.username,
            created_by_user=self.admin,
            location=self.location,
        )
        url = reverse('combined-order-activate', args=[result['combined_order_id']])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_scan_staged(self):
        from payments.services.combined_order_service import CombinedOrderService
        result = CombinedOrderService.create_combined_order(
            transaction_ids=[self.tx1.id, self.tx2.id],
            created_by=self.admin.username,
            created_by_user=self.admin,
            location=self.location,
        )
        co_id = result['combined_order_id']
        CombinedOrderService.activate_combined_order(
            combined_order_id=co_id,
            activated_by=str(self.admin.username),
        )
        url = reverse('combined-order-scan-staged', args=[co_id])
        response = self.client.post(url, {
            'sku': self.product.prod_code,
            'quantity': 2,
        }, format='json')
        self.assertEqual(response.status_code, 200)

    def test_complete_combined_order(self):
        from payments.services.combined_order_service import CombinedOrderService
        result = CombinedOrderService.create_combined_order(
            transaction_ids=[self.tx1.id, self.tx2.id],
            created_by=self.admin.username,
            created_by_user=self.admin,
            location=self.location,
        )
        co_id = result['combined_order_id']
        CombinedOrderService.activate_combined_order(
            combined_order_id=co_id,
            activated_by=str(self.admin.username),
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=co_id,
            barcode_data={'sku': self.product.prod_code, 'quantity': 2},
            scanned_by=self.issuer,
        )
        url = reverse('combined-order-complete', args=[co_id])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_cancel_combined_order(self):
        from payments.services.combined_order_service import CombinedOrderService
        result = CombinedOrderService.create_combined_order(
            transaction_ids=[self.tx1.id, self.tx2.id],
            created_by=self.admin.username,
            created_by_user=self.admin,
            location=self.location,
        )
        co_id = result['combined_order_id']
        url = reverse('combined-order-cancel', args=[co_id])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_cancel_issuance(self):
        from payments.services.combined_order_service import CombinedOrderService
        result = CombinedOrderService.create_combined_order(
            transaction_ids=[self.tx1.id, self.tx2.id],
            created_by=self.admin.username,
            created_by_user=self.admin,
            location=self.location,
        )
        co_id = result['combined_order_id']
        CombinedOrderService.activate_combined_order(
            combined_order_id=co_id,
            activated_by=str(self.admin.username),
        )
        url = reverse('combined-order-cancel-issuance', args=[co_id])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_revert_combined_order(self):
        from payments.services.combined_order_service import CombinedOrderService
        result = CombinedOrderService.create_combined_order(
            transaction_ids=[self.tx1.id, self.tx2.id],
            created_by=self.admin.username,
            created_by_user=self.admin,
            location=self.location,
        )
        co_id = result['combined_order_id']
        CombinedOrderService.activate_combined_order(
            combined_order_id=co_id,
            activated_by=str(self.admin.username),
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=co_id,
            barcode_data={'sku': self.product.prod_code, 'quantity': 2},
            scanned_by=self.issuer,
        )
        CombinedOrderService.complete_combined_order(
            combined_order_id=co_id,
            completed_by=str(self.admin.username),
        )
        url = reverse('combined-order-revert', args=[co_id])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200)
