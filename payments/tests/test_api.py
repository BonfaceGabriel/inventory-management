from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from ..models import Device, Transaction
from django.contrib.auth.hashers import make_password
from decimal import Decimal
import secrets

class TransactionAPITest(APITestCase):
    def setUp(self):
        self.device = Device.objects.create(
            name="Test Phone",
            default_gateway="Safaricom",
            gateway_number="223344",
            api_key=make_password("test_key")
        )
        self.transaction1 = Transaction.objects.create(
            tx_id="QWERTY12345",
            amount=Decimal('1234.56'),
            sender_name="JOHN DOE",
            sender_phone="0712345678",
            timestamp="2023-01-01T13:00:00Z",
            status=Transaction.OrderStatus.NOT_PROCESSED,
            gateway_type="till",
            amount_expected=Decimal('1234.56'),
            unique_hash="testhash1"
        )
        self.transaction2 = Transaction.objects.create(
            tx_id="ASDFG67890",
            amount=Decimal('6543.21'),
            sender_name="JANE DOE",
            sender_phone="0787654321",
            timestamp="2023-01-02T14:00:00Z",
            status=Transaction.OrderStatus.PROCESSING,
            gateway_type="paybill",
            amount_expected=Decimal('6543.21'),
            unique_hash="testhash2"
        )

    def test_list_transactions(self):
        url = reverse('transaction-list')
        self.client.credentials(HTTP_X_DEVICE_KEY='test_key')
        response = self.client.get(url, {'device': self.device.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)

    def test_filter_by_status(self):
        url = reverse('transaction-list')
        self.client.credentials(HTTP_X_DEVICE_KEY='test_key')
        response = self.client.get(url, {'status': Transaction.OrderStatus.NOT_PROCESSED, 'device': self.device.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['tx_id'], self.transaction1.tx_id)

    def test_search_by_tx_id(self):
        url = reverse('transaction-list')
        self.client.credentials(HTTP_X_DEVICE_KEY='test_key')
        response = self.client.get(url, {'search': self.transaction2.tx_id, 'device': self.device.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['tx_id'], self.transaction2.tx_id)

    def test_ordering_by_amount(self):
        url = reverse('transaction-list')
        self.client.credentials(HTTP_X_DEVICE_KEY='test_key')
        response = self.client.get(url, {'ordering': '-amount', 'device': self.device.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['results'][0]['tx_id'], self.transaction2.tx_id)

    def test_pagination(self):
        url = reverse('transaction-list')
        self.client.credentials(HTTP_X_DEVICE_KEY='test_key')
        response = self.client.get(url, {'limit': 1, 'device': self.device.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
