from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from ..models import Device
from django.contrib.auth.hashers import check_password
import secrets

from rest_framework.test import APIClient

class DeviceAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.device_name = "Test Device"
        self.register_url = reverse('device-register')
        self.register_data = {
            "name": self.device_name,
            "default_gateway": "Safaricom",
            "gateway_number": "123456"
        }
    def test_device_registration(self):
        """
        Ensure we can register a new device and get an API key.
        """
        url = reverse('device-register')
        data = {'name': 'Test Device', 'default_gateway': 'till', 'gateway_number': '12345'}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('api_key', response.data)
        self.assertIsNotNone(response.data['api_key'])
        
        # Check that the key in the database is hashed
        device = Device.objects.get(id=response.data['id'])
        self.assertTrue(check_password(response.data['api_key'], device.api_key))

    def test_message_ingestion_successful(self):
        """
        Ensure we can ingest a message with a valid API key.
        """
        # First, register a device
        register_url = reverse('device-register')
        register_data = {'name': 'Test Device', 'default_gateway': 'till', 'gateway_number': '12345'}
        register_response = self.client.post(register_url, register_data, format='json')
        api_key = register_response.data['api_key']
        device_id = register_response.data['id']

        # Now, ingest a message
        ingest_url = reverse('message-ingest')
        ingest_data = {'device': device_id, 'raw_text': 'test message', 'received_at': '2025-10-07T10:30:00+03:00'}
        self.client.credentials(HTTP_X_DEVICE_KEY=api_key)
        ingest_response = self.client.post(ingest_url, ingest_data, format='json')
        
        self.assertEqual(ingest_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ingest_response.data['status'], 'queued')

    def test_message_ingestion_invalid_key(self):
        """
        Ensure we get an error when ingesting a message with an invalid API key.
        """
        # Register a device to get a valid device_id
        register_url = reverse('device-register')
        register_data = {'name': 'Test Device', 'default_gateway': 'till', 'gateway_number': '12345'}
        register_response = self.client.post(register_url, register_data, format='json')
        device_id = register_response.data['id']

        ingest_url = reverse('message-ingest')
        ingest_data = {'device': device_id, 'raw_text': 'test message', 'received_at': '2025-10-07T10:30:00+03:00'}
        self.client.credentials(HTTP_X_DEVICE_KEY='invalid_key')
        ingest_response = self.client.post(ingest_url, ingest_data, format='json')
        
        self.assertEqual(ingest_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_rotate_api_key(self):
        """
        Ensure we can rotate an API key and the old key becomes invalid.
        """
        # Register a device
        register_url = reverse('device-register')
        register_data = {'name': 'Test Device', 'default_gateway': 'till', 'gateway_number': '12345'}
        register_response = self.client.post(register_url, register_data, format='json')
        old_api_key = register_response.data['api_key']
        device_id = register_response.data['id']

        # Rotate the key
        rotate_url = reverse('device-rotate-key', kwargs={'id': device_id})
        self.client.credentials(HTTP_X_DEVICE_KEY=old_api_key)
        rotate_response = self.client.patch(rotate_url, {'device': device_id}, format='json')
        
        self.assertEqual(rotate_response.status_code, status.HTTP_200_OK)
        new_api_key = rotate_response.data['api_key']
        self.assertNotEqual(old_api_key, new_api_key)

        # Verify the new key is stored hashed
        device = Device.objects.get(id=device_id)
        self.assertTrue(check_password(new_api_key, device.api_key))

        # Try to use the old key for message ingestion (should fail)
        ingest_url = reverse('message-ingest')
        ingest_data = {'device': device_id, 'raw_text': 'test message', 'received_at': '2025-10-07T10:30:00+03:00'}
        self.client.credentials(HTTP_X_DEVICE_KEY=old_api_key)
        ingest_response_fail = self.client.post(ingest_url, ingest_data, format='json')
        self.assertEqual(ingest_response_fail.status_code, status.HTTP_403_FORBIDDEN)

        # Try to use the new key for message ingestion (should succeed)
        self.client.credentials(HTTP_X_DEVICE_KEY=new_api_key)
        ingest_response_success = self.client.post(ingest_url, ingest_data, format='json')
        self.assertEqual(ingest_response_success.status_code, status.HTTP_201_CREATED)
