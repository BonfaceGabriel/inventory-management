from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from .test_helpers import (
    make_admin, make_gateway, make_transaction, make_product,
    make_device, make_authenticated_client, make_device_client,
)


class TransactionAPITest(TestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.tx1 = make_transaction(tx_id='API-TX-1', amount=Decimal('1000.00'))
        self.tx2 = make_transaction(
            tx_id='API-TX-2', amount=Decimal('500.00'),
            status='PROCESSING', unique_hash='hash_api2',
        )
        self.device = make_device(gateway=self.gateway)
        self.client = make_device_client(self.device)

    def test_list_transactions(self):
        response = self.client.get(reverse('transaction-list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_filter_by_status(self):
        response = self.client.get(reverse('transaction-list'), {'status': 'NOT_PROCESSED'})
        self.assertEqual(response.status_code, 200)
        for tx in response.data['results']:
            self.assertEqual(tx['status'], 'NOT_PROCESSED')

    def test_search_by_tx_id(self):
        response = self.client.get(reverse('transaction-list'), {'search': 'API-TX-1'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)

    def test_ordering_by_amount(self):
        response = self.client.get(reverse('transaction-list'), {'ordering': 'amount'})
        self.assertEqual(response.status_code, 200)

    def test_get_by_tx_id(self):
        response = self.client.get(reverse('transaction-by-tx-id', args=['API-TX-1']))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['tx_id'], 'API-TX-1')

    def test_get_by_nonexistent_tx_id(self):
        response = self.client.get(reverse('transaction-by-tx-id', args=['NONEXISTENT']))
        self.assertEqual(response.status_code, 404)

    def test_detail_view(self):
        response = self.client.get(reverse('transaction-detail', args=[self.tx1.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['tx_id'], 'API-TX-1')

    def test_detail_view_not_found(self):
        response = self.client.get(reverse('transaction-detail', args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_access_fails(self):
        anon_client = APIClient()
        response = anon_client.get(reverse('transaction-list'))
        self.assertEqual(response.status_code, 401)

    def test_pagination_default(self):
        for i in range(25):
            make_transaction(
                tx_id=f'API-PAGE-{i:03d}', amount=Decimal('100.00'),
                unique_hash=f'hash_page_{i}',
            )
        response = self.client.get(reverse('transaction-list'))
        self.assertIn('next', response.data)
        self.assertIn('count', response.data)


class TransactionDetailAPITest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.gateway = make_gateway()
        self.tx = make_transaction(tx_id='API-DET', amount=Decimal('1000.00'))
        self.client = make_authenticated_client(self.admin)

    def test_update_transaction_notes(self):
        response = self.client.patch(
            reverse('transaction-detail', args=[self.tx.id]),
            {'notes': 'Updated notes via API'}, format='json',
        )
        self.assertEqual(response.status_code, 200)

    def test_update_locked_transaction_fails(self):
        self.tx.status = 'FULFILLED'
        self.tx.save()
        response = self.client.patch(
            reverse('transaction-detail', args=[self.tx.id]),
            {'notes': 'Should fail'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_gateway_list(self):
        response = self.client.get(reverse('gateway-list'))
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.data), 0)
