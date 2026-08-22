from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APITestCase
from .test_helpers import (
    make_admin, make_gateway, make_transaction, make_device,
    make_device_client, make_authenticated_client,
)


class ManualPaymentAPITest(APITestCase):
    def setUp(self):
        self.admin = make_admin()
        self.gateway = make_gateway()
        self.tx = make_transaction(tx_id='API-MP-TX', amount=Decimal('5000.00'))
        self.client = make_authenticated_client(self.admin)

    def test_create_manual_payment_cash(self):
        response = self.client.post(reverse('manual-payment-create'), {
            'payment_method': 'CASH',
            'payer_name': 'John Cash',
            'amount': '1000.00',
            'transaction_id': self.tx.id,
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_create_manual_payment_pdq_with_reference(self):
        response = self.client.post(reverse('manual-payment-create'), {
            'payment_method': 'PDQ',
            'payer_name': 'Jane PDQ',
            'amount': '2500.00',
            'reference_number': 'PDQ-REF-001',
            'transaction_id': self.tx.id,
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_create_manual_payment_pdq_missing_reference(self):
        response = self.client.post(reverse('manual-payment-create'), {
            'payment_method': 'PDQ',
            'payer_name': 'Jane PDQ',
            'amount': '2500.00',
            'transaction_id': self.tx.id,
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_create_manual_payment_negative_amount(self):
        response = self.client.post(reverse('manual-payment-create'), {
            'payment_method': 'CASH',
            'payer_name': 'Bad',
            'amount': '-100.00',
            'transaction_id': self.tx.id,
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_list_manual_payments(self):
        self.client.post(reverse('manual-payment-create'), {
            'payment_method': 'CASH',
            'payer_name': 'List Test',
            'amount': '500.00',
            'transaction_id': self.tx.id,
        }, format='json')
        response = self.client.get(reverse('manual-payment-list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_manual_payment_summary(self):
        response = self.client.get(reverse('manual-payment-summary'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('total_payments', response.data)

    def test_unauthenticated_access_fails(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        response = anon.get(reverse('manual-payment-list'))
        self.assertEqual(response.status_code, 401)
