from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APITestCase
from .test_helpers import (
    make_admin, make_processor, make_gateway, make_product,
    make_transaction, make_line_item, make_issuer,
    make_authenticated_client,
)


class AdminOperationsAPITest(APITestCase):
    def setUp(self):
        self.admin = make_admin(username='ops_admin')
        self.processor = make_processor(username='ops_processor')
        self.issuer = make_issuer(username='ops_issuer')
        self.gateway = make_gateway()
        self.product = make_product(prod_code='OPS-PROD', quantity=100, price=Decimal('500.00'))
        self.tx = make_transaction(tx_id='OPS-TX', amount=Decimal('1000.00'))
        self.client = make_authenticated_client(self.admin)

    def test_cancel_fulfilled_transaction(self):
        self.tx.status = 'FULFILLED'
        self.tx.amount_fulfilled = Decimal('1000.00')
        self.tx.save()
        li = make_line_item(self.tx, self.product, quantity=2, scanned_by_user=self.issuer)
        li.is_inventory_deducted = True
        li.save()
        self.product.quantity = 98
        self.product.save()
        url = reverse('cancel-fulfilled', args=[self.tx.id])
        response = self.client.post(url, {'reason': 'Customer return'}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_cancel_fulfilled_missing_reason(self):
        self.tx.status = 'FULFILLED'
        self.tx.save()
        url = reverse('cancel-fulfilled', args=[self.tx.id])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_cancel_fulfilled_not_fulfilled_fails(self):
        url = reverse('cancel-fulfilled', args=[self.tx.id])
        response = self.client.post(url, {'reason': 'Test'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_cancel_registration(self):
        self.tx.is_registration = True
        self.tx.save()
        url = reverse('cancel-registration', args=[self.tx.id])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_mark_registration(self):
        url = reverse('mark-registration', args=[self.tx.id])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.tx.refresh_from_db()
        self.assertTrue(self.tx.is_registration)

    def test_unmark_registration(self):
        self.tx.is_registration = True
        self.tx.save()
        url = reverse('unmark-registration', args=[self.tx.id])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.tx.refresh_from_db()
        self.assertFalse(self.tx.is_registration)

    def test_delete_transaction(self):
        url = reverse('delete-transaction', args=[self.tx.id])
        response = self.client.delete(url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    # Processor-level tests (should get 403)
    def test_processor_cannot_cancel_fulfilled(self):
        proc_client = make_authenticated_client(self.processor)
        url = reverse('cancel-fulfilled', args=[self.tx.id])
        response = proc_client.client.post(url, {'reason': 'Test'}, format='json')
        self.assertIn(response.status_code, [403, 400])

    def test_processor_cannot_delete(self):
        proc_client = make_authenticated_client(self.processor)
        url = reverse('delete-transaction', args=[self.tx.id])
        response = proc_client.client.delete(url, {}, format='json')
        self.assertIn(response.status_code, [403, 400])
