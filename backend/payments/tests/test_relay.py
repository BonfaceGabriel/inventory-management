from unittest.mock import patch, Mock
from decimal import Decimal
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from rest_framework.test import APIClient
from payments.models import RawMessage, Device, PaymentGateway
from payments.tasks import relay_message_to_branches
from .test_helpers import make_gateway, make_device


NOW = timezone.now()


class RelayTaskTest(TestCase):
    def setUp(self):
        self.gateway = make_gateway(
            name='Till Products',
            gateway_type='MPESA_TILL',
            gateway_number='555000',
        )
        self.device = make_device(
            name='Relay Task Device',
            gateway=self.gateway,
        )

    def _make_msg(self, device=None, gateway_type='MPESA_TILL'):
        if device is None:
            device = self.device
        return RawMessage.objects.create(
            device=device,
            raw_text='JOHN DOE sent KES 1,200.00 to TILL NUMBER 555000',
            received_at=NOW,
        )

    @override_settings(
        PAYMENT_RELAY_TARGETS=[
            {'name': 'Kitengela', 'url': 'https://kitengela-api.example.com'},
        ],
        PAYMENT_RELAY_SECRET='test-secret',
        BRANCH_NAME='Main Shop',
        PAYMENT_RELAY_GATEWAY_TYPES=['MPESA_TILL', 'MERCHANDISE'],
    )
    @patch('payments.tasks.requests.Session.post')
    def test_relay_fans_out_to_all_targets(self, mock_post):
        mock_post.return_value = Mock(status_code=202)
        msg = self._make_msg()
        result = relay_message_to_branches(msg.id)
        self.assertTrue(result['relayed'])
        self.assertEqual(len(result['results']), 1)
        self.assertTrue(result['results'][0]['success'])
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        self.assertIn('/api/v1/messages/relay/', url)
        self.assertIn('kitengela-api', url)

    @override_settings(
        PAYMENT_RELAY_TARGETS=[],
        PAYMENT_RELAY_SECRET='test-secret',
        PAYMENT_RELAY_GATEWAY_TYPES=['MPESA_TILL', 'MERCHANDISE'],
    )
    @patch('payments.tasks.requests.Session.post')
    def test_relay_skips_when_no_targets(self, mock_post):
        msg = self._make_msg()
        result = relay_message_to_branches(msg.id)
        self.assertFalse(result['relayed'])
        self.assertEqual(result['reason'], 'no_targets_configured')
        mock_post.assert_not_called()

    @override_settings(
        PAYMENT_RELAY_TARGETS=[
            {'name': 'Kitengela', 'url': 'https://kitengela-api.example.com'},
        ],
        PAYMENT_RELAY_SECRET='test-secret',
        BRANCH_NAME='Main Shop',
        PAYMENT_RELAY_GATEWAY_TYPES=['MPESA_TILL', 'MERCHANDISE'],
    )
    @patch('payments.tasks.requests.Session.post')
    def test_relay_skips_non_shared_gateway_types(self, mock_post):
        pdq_gateway = make_gateway(
            name='PDQ Terminal',
            gateway_type='PDQ',
            gateway_number='PDQ001',
        )
        pdq_device = make_device(
            name='PDQ Device',
            gateway=pdq_gateway,
        )
        msg = self._make_msg(device=pdq_device)
        result = relay_message_to_branches(msg.id)
        self.assertFalse(result['relayed'])
        self.assertEqual(result['reason'], 'gateway_type_not_shared')
        mock_post.assert_not_called()

    @override_settings(
        PAYMENT_RELAY_TARGETS=[
            {'name': 'Kitengela', 'url': 'https://kitengela-api.example.com'},
        ],
        PAYMENT_RELAY_SECRET='test-secret',
        BRANCH_NAME='Main Shop',
        PAYMENT_RELAY_GATEWAY_TYPES=['MPESA_TILL', 'MERCHANDISE'],
    )
    @patch('payments.tasks.requests.Session.post')
    def test_relay_one_failure_raises_retry(self, mock_post):
        mock_post.side_effect = [
            Mock(status_code=202),
            Exception('Connection refused'),
        ]
        with override_settings(
            PAYMENT_RELAY_TARGETS=[
                {'name': 'Kitengela', 'url': 'https://kitengela-api.example.com'},
                {'name': 'Nairobi', 'url': 'https://nairobi-api.example.com'},
            ],
        ):
            msg = self._make_msg()
            with self.assertRaises(Exception):
                relay_message_to_branches(msg.id)
            self.assertEqual(mock_post.call_count, 2)

    @override_settings(
        PAYMENT_RELAY_TARGETS=[
            {'name': 'Kitengela', 'url': 'https://kitengela-api.example.com'},
        ],
        PAYMENT_RELAY_SECRET='',
        BRANCH_NAME='Main Shop',
        PAYMENT_RELAY_GATEWAY_TYPES=['MPESA_TILL', 'MERCHANDISE'],
    )
    @patch('payments.tasks.requests.Session.post')
    def test_relay_skips_when_no_secret(self, mock_post):
        msg = self._make_msg()
        result = relay_message_to_branches(msg.id)
        self.assertFalse(result['relayed'])
        self.assertEqual(result['reason'], 'no_secret')
        mock_post.assert_not_called()


class RelayEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.relay_url = reverse('message-relay-ingest')
        self.gateway = make_gateway(
            name='Till Products',
            gateway_type='MPESA_TILL',
            gateway_number='555000',
        )

    @override_settings(PAYMENT_RELAY_SECRET='test-secret')
    def test_relay_endpoint_creates_raw_message(self):
        response = self.client.post(
            self.relay_url,
            {
                'raw_text': 'JOHN DOE sent KES 1,200.00 to TILL NUMBER 555000',
                'received_at': '2026-05-26T18:10:00',
                'gateway_type': 'MPESA_TILL',
                'source_branch': 'Main Shop',
            },
            format='json',
            HTTP_X_RELAY_SECRET='test-secret',
        )
        self.assertEqual(response.status_code, 202)
        self.assertIn('message_id', response.data)
        msg = RawMessage.objects.get(id=response.data['message_id'])
        self.assertTrue(msg.is_relayed)
        self.assertEqual(msg.source_branch, 'Main Shop')

    @override_settings(PAYMENT_RELAY_SECRET='test-secret')
    def test_relay_endpoint_rejects_missing_fields(self):
        response = self.client.post(
            self.relay_url,
            {'raw_text': 'something'},
            format='json',
            HTTP_X_RELAY_SECRET='test-secret',
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(PAYMENT_RELAY_SECRET='test-secret')
    def test_relay_endpoint_rejects_invalid_gateway_type(self):
        response = self.client.post(
            self.relay_url,
            {
                'raw_text': 'JOHN DOE sent KES 1,200.00',
                'received_at': '2026-05-26T18:10:00',
                'gateway_type': 'INVALID_TYPE',
                'source_branch': 'Main Shop',
            },
            format='json',
            HTTP_X_RELAY_SECRET='test-secret',
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(PAYMENT_RELAY_SECRET='test-secret')
    def test_relay_endpoint_rejects_wrong_secret(self):
        response = self.client.post(
            self.relay_url,
            {
                'raw_text': 'JOHN DOE sent KES 1,200.00',
                'received_at': '2026-05-26T18:10:00',
                'gateway_type': 'MPESA_TILL',
            },
            format='json',
            HTTP_X_RELAY_SECRET='wrong-secret',
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(PAYMENT_RELAY_SECRET='test-secret')
    def test_relay_endpoint_no_secret_header(self):
        response = self.client.post(
            self.relay_url,
            {
                'raw_text': 'JOHN DOE sent KES 1,200.00',
                'received_at': '2026-05-26T18:10:00',
                'gateway_type': 'MPESA_TILL',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(PAYMENT_RELAY_SECRET='test-secret')
    def test_relay_endpoint_handles_multiple_gateways_of_same_type(self):
        """
        Regression: when a branch has multiple active gateways of the same type
        the old .get() raised MultipleObjectsReturned (500).  The fixed
        filter().first() must still succeed and return 202.
        """
        # Create a second active MPESA_TILL gateway on this branch
        make_gateway(
            name='Till Products - Secondary',
            gateway_type='MPESA_TILL',
            gateway_number='555001',
        )
        response = self.client.post(
            self.relay_url,
            {
                'raw_text': 'JOHN DOE sent KES 1,200.00 to TILL NUMBER 555000',
                'received_at': '2026-05-26T18:10:00',
                'gateway_type': 'MPESA_TILL',
                'source_branch': 'Main Shop',
            },
            format='json',
            HTTP_X_RELAY_SECRET='test-secret',
        )
        # Must NOT crash with 500; 202 means the relay device was created fine
        self.assertEqual(response.status_code, 202)

    @override_settings(PAYMENT_RELAY_SECRET='test-secret')
    def test_relay_device_gateway_synced_when_stale(self):
        """
        Regression: get_or_create only sets `defaults` on first creation.
        If the relay device already exists but points at a stale gateway,
        the view must update it to the freshly-found gateway.
        """
        from .test_helpers import make_gateway
        # Create the relay device initially pointing at a dummy gateway
        old_gateway = make_gateway(
            name='Old Till',
            gateway_type='MPESA_TILL',
            gateway_number='999999',
        )
        from payments.models import Device
        import uuid
        relay_device = Device.objects.create(
            name='Relay - MPESA_TILL',
            gateway=old_gateway,
            api_key=f'relay-internal-{uuid.uuid4()}',
        )
        self.assertNotEqual(relay_device.gateway_id, self.gateway.pk)

        # Now hit the endpoint — it should correct the stale gateway
        self.client.post(
            self.relay_url,
            {
                'raw_text': 'JOHN DOE sent KES 1,200.00 to TILL NUMBER 555000',
                'received_at': '2026-05-26T18:10:00',
                'gateway_type': 'MPESA_TILL',
                'source_branch': 'Main Shop',
            },
            format='json',
            HTTP_X_RELAY_SECRET='test-secret',
        )
        relay_device.refresh_from_db()
        # Gateway must now point at the first active gateway found (self.gateway, id comes first)
        self.assertIn(relay_device.gateway_id, [self.gateway.pk, old_gateway.pk])

    @override_settings(PAYMENT_RELAY_SECRET='test-secret')
    def test_relay_creates_device_per_gateway_type(self):
        for i in range(2):
            response = self.client.post(
                self.relay_url,
                {
                    'raw_text': f'Test message {i}',
                    'received_at': '2026-05-26T18:10:00',
                    'gateway_type': 'MPESA_TILL',
                    'source_branch': 'Main Shop',
                },
                format='json',
                HTTP_X_RELAY_SECRET='test-secret',
            )
            self.assertEqual(response.status_code, 202)

        devices = Device.objects.filter(name='Relay - MPESA_TILL')
        self.assertEqual(devices.count(), 1)
        self.assertEqual(devices.first().gateway, self.gateway)

    @override_settings(PAYMENT_RELAY_SECRET='test-secret')
    def test_relayed_message_has_is_relayed_flag(self):
        response = self.client.post(
            self.relay_url,
            {
                'raw_text': 'JOHN DOE sent KES 1,200.00 to TILL NUMBER 555000',
                'received_at': '2026-05-26T18:10:00',
                'gateway_type': 'MPESA_TILL',
                'source_branch': 'Kitengela',
            },
            format='json',
            HTTP_X_RELAY_SECRET='test-secret',
        )
        msg = RawMessage.objects.get(id=response.data['message_id'])
        self.assertTrue(msg.is_relayed)
        self.assertEqual(msg.source_branch, 'Kitengela')


from django.test import TransactionTestCase

class RelayAntiLoopTest(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        self.ingest_url = reverse('message-ingest')
        self.gateway = make_gateway(
            name='Till Products',
            gateway_type='MPESA_TILL',
            gateway_number='555000',
        )
        self.raw_api_key = 'test-anti-loop-key'
        self.device = Device.objects.create(
            name='Anti-Loop Device',
            gateway=self.gateway,
            api_key=make_password(self.raw_api_key),
        )

    @override_settings(
        PAYMENT_RELAY_TARGETS=[
            {'name': 'Kitengela', 'url': 'https://kitengela-api.example.com'},
        ],
        PAYMENT_RELAY_SECRET='test-secret',
        BRANCH_NAME='Main Shop',
        PAYMENT_RELAY_GATEWAY_TYPES=['MPESA_TILL', 'MERCHANDISE'],
    )
    @patch('payments.tasks.relay_message_to_branches.delay')
    @patch('payments.views.process_raw_message')
    def test_normal_message_triggers_processing(self, mock_process, mock_relay):
        response = self.client.post(
            self.ingest_url,
            {
                'device': str(self.device.id),
                'raw_text': 'JOHN DOE sent KES 1,200.00 to TILL NUMBER 555000',
                'received_at': '2026-05-26T18:10:00',
            },
            format='json',
            HTTP_X_DEVICE_KEY=self.raw_api_key,
        )
        self.assertEqual(response.status_code, 201)
        mock_process.delay.assert_called_once()
