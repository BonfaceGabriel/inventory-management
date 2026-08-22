from django.test import TestCase
from rest_framework.test import APIClient
from django.urls import reverse
from decimal import Decimal
from .test_helpers import (
    make_admin, make_processor, make_issuer,
    make_gateway, make_transaction, make_product,
)


class PermissionTest(TestCase):
    def setUp(self):
        self.admin = make_admin(username='perm_admin')
        self.processor = make_processor(username='perm_processor')
        self.issuer = make_issuer(username='perm_issuer')
        self.gateway = make_gateway()
        self.tx = make_transaction(tx_id='PERM-TX', amount=Decimal('1000.00'))

    def _auth_client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_admin_can_access_user_list(self):
        client = self._auth_client(self.admin)
        response = client.get(reverse('user-list-create'))
        self.assertEqual(response.status_code, 200)

    def test_processor_cannot_access_user_list(self):
        client = self._auth_client(self.processor)
        response = client.get(reverse('user-list-create'))
        self.assertEqual(response.status_code, 403)

    def test_issuer_cannot_access_user_list(self):
        client = self._auth_client(self.issuer)
        response = client.get(reverse('user-list-create'))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_admin_panel(self):
        client = self._auth_client(self.admin)
        response = client.get(reverse('stock-report'))
        self.assertEqual(response.status_code, 200)

    def test_processor_can_fulfill(self):
        client = self._auth_client(self.processor)
        response = client.get(reverse('transaction-list'))
        self.assertEqual(response.status_code, 200)

    def test_issuer_can_access_queue(self):
        client = self._auth_client(self.issuer)
        response = client.get(reverse('issuer-queue'))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_cancel_fulfilled(self):
        self.tx.status = 'FULFILLED'
        self.tx.save()
        client = self._auth_client(self.admin)
        url = reverse('cancel-fulfilled', args=[self.tx.id])
        body = {'reason': 'Test cancellation'}
        response = client.post(url, body, format='json')
        self.assertEqual(response.status_code, 200)

    def test_processor_cannot_cancel_fulfilled(self):
        self.tx.status = 'FULFILLED'
        self.tx.save()
        client = self._auth_client(self.processor)
        url = reverse('cancel-fulfilled', args=[self.tx.id])
        response = client.post(url, {'reason': 'Test'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_issuer_cannot_cancel_fulfilled(self):
        self.tx.status = 'FULFILLED'
        self.tx.save()
        client = self._auth_client(self.issuer)
        url = reverse('cancel-fulfilled', args=[self.tx.id])
        response = client.post(url, {'reason': 'Test'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_admin_can_delete_transaction(self):
        client = self._auth_client(self.admin)
        url = reverse('delete-transaction', args=[self.tx.id])
        response = client.delete(url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_processor_cannot_delete_transaction(self):
        client = self._auth_client(self.processor)
        url = reverse('delete-transaction', args=[self.tx.id])
        response = client.delete(url, {}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_issuer_cannot_delete_transaction(self):
        client = self._auth_client(self.issuer)
        url = reverse('delete-transaction', args=[self.tx.id])
        response = client.delete(url, {}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_processor_can_activate_issuance(self):
        client = self._auth_client(self.processor)
        url = reverse('transaction-activate-issuance', args=[self.tx.id])
        response = client.post(url, {'user_id': self.issuer.id}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_issuer_can_scan_barcode(self):
        from payments.services.fulfillment_service import FulfillmentService
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.processor,
            location=None,
        )
        product = make_product(prod_code='PERM-SCAN', quantity=100)
        client = self._auth_client(self.issuer)
        url = reverse('transaction-scan-barcode', args=[self.tx.id])
        response = client.post(url, {
            'sku': product.prod_code,
            'quantity': 1,
        }, format='json')
        self.assertEqual(response.status_code, 200)
