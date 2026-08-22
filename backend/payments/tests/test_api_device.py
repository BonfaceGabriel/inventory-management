from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from payments.models import Device
from .test_helpers import make_gateway, make_device


class DeviceAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.gateway = make_gateway()
        self.register_url = reverse('device-register')
        self.register_data = {
            'name': 'Test Device API',
            'phone_number': '0711111111',
            'gateway_id': self.gateway.id,
        }

    def test_register_device_returns_api_key(self):
        response = self.client.post(self.register_url, self.register_data, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIn('api_key', response.data)
        self.assertIn('device_id', response.data)

    def test_register_device_without_phone(self):
        data = self.register_data.copy()
        del data['phone_number']
        response = self.client.post(self.register_url, data, format='json')
        self.assertEqual(response.status_code, 201)

    def test_message_ingest_with_valid_key(self):
        response = self.client.post(self.register_url, self.register_data, format='json')
        api_key = response.data['api_key']
        msg_url = reverse('message-ingest')
        response = self.client.post(msg_url, {
            'message': 'M-PESA message test',
            'received_at': '2026-05-26T12:00:00',
        }, format='json', HTTP_X_API_KEY=api_key)
        self.assertEqual(response.status_code, 200)

    def test_message_ingest_with_invalid_key(self):
        msg_url = reverse('message-ingest')
        response = self.client.post(msg_url, {
            'message': 'Test message',
        }, format='json', HTTP_X_API_KEY='invalid-key')
        self.assertEqual(response.status_code, 403)

    def test_rotate_api_key(self):
        response = self.client.post(self.register_url, self.register_data, format='json')
        device_id = response.data['device_id']
        old_key = response.data['api_key']
        rotate_url = reverse('device-rotate-key', args=[device_id])
        response = self.client.post(rotate_url, {}, format='json', HTTP_X_API_KEY=old_key)
        self.assertEqual(response.status_code, 200)
        self.assertIn('api_key', response.data)
        self.assertNotEqual(response.data['api_key'], old_key)

    def test_rotate_api_key_with_old_key_stops_working(self):
        response = self.client.post(self.register_url, self.register_data, format='json')
        device_id = response.data['device_id']
        old_key = response.data['api_key']
        rotate_url = reverse('device-rotate-key', args=[device_id])
        self.client.post(rotate_url, {}, format='json', HTTP_X_API_KEY=old_key)
        msg_url = reverse('message-ingest')
        response = self.client.post(msg_url, {
            'message': 'Should fail',
        }, format='json', HTTP_X_API_KEY=old_key)
        self.assertEqual(response.status_code, 403)

    def test_device_settings_update(self):
        device = make_device(gateway=self.gateway)
        settings_url = reverse('device-settings-update')
        response = self.client.post(settings_url, {
            'device_id': str(device.id),
        }, format='json', HTTP_X_API_KEY=device.api_key)
        self.assertEqual(response.status_code, 200)
