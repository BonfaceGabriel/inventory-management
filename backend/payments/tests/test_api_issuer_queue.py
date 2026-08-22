from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APITestCase
from .test_helpers import (
    make_admin, make_issuer, make_gateway, make_transaction,
    make_authenticated_client,
)


class IssuerQueueAPITest(APITestCase):
    def setUp(self):
        self.issuer = make_issuer(username='queue_issuer')
        self.admin = make_admin(username='queue_admin')
        self.gateway = make_gateway()
        self.tx = make_transaction(tx_id='QUEUE-TX', amount=Decimal('1000.00'), status='PROCESSING')
        self.client = make_authenticated_client(self.issuer)

    def test_issuer_queue(self):
        response = self.client.get(reverse('issuer-queue'))
        self.assertEqual(response.status_code, 200)

    def test_issuer_queue_pending(self):
        response = self.client.get(reverse('issuer-queue-pending'))
        self.assertEqual(response.status_code, 200)

    def test_issuer_stats(self):
        response = self.client.get(reverse('issuer-stats'))
        self.assertEqual(response.status_code, 200)
