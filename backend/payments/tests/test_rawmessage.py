from django.test import TestCase
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.auth.hashers import make_password
import secrets

from payments.models import RawMessage, Device

class RawMessageModelTests(TestCase):

    def setUp(self):
        self.device = Device.objects.create(name='Test Device', default_gateway='till', gateway_number='12345')

    def test_raw_text_sanitization(self):
        """
        Test that control characters are stripped from raw_text.
        """
        raw_text_with_control_chars = "Hello\x00\x1fWorld\x7f"
        message = RawMessage(
            device=self.device,
            raw_text=raw_text_with_control_chars,
            received_at=timezone.now()
        )
        message.full_clean()
        self.assertEqual(message.raw_text, "HelloWorld")

    def test_raw_text_max_length_validator(self):
        """
        Test that raw_text longer than the max length raises a ValidationError.
        """
        long_text = 'a' * 1025
        message = RawMessage(
            device=self.device,
            raw_text=long_text,
            received_at=timezone.now()
        )
        with self.assertRaises(ValidationError):
            message.full_clean()

class ArchiveRawMessagesCommandTests(TestCase):

    def setUp(self):
        self.device = Device.objects.create(name='Test Device', default_gateway='till', gateway_number='12345')
        now = timezone.now()
        # Create some old messages
        for i in range(5):
            RawMessage.objects.create(
                device=self.device,
                raw_text=f'Old message {i}',
                received_at=now,
                created_at=now - timedelta(days=200)
            )
        # Create some new messages
        for i in range(3):
            RawMessage.objects.create(
                device=self.device,
                raw_text=f'New message {i}',
                received_at=now,
                created_at=now - timedelta(days=10)
            )

    def test_archive_command_dry_run(self):
        """
        Test the archive_raw_messages command with --dry-run.
        """
        out = StringIO()
        call_command('archive_raw_messages', '--days=180', '--dry-run', stdout=out)
        self.assertIn('[Dry Run] Found 5 messages older than 180 days to be deleted.', out.getvalue())
        self.assertEqual(RawMessage.objects.count(), 8)

    def test_archive_command_delete(self):
        """
        Test the archive_raw_messages command actually deletes messages.
        """
        out = StringIO()
        call_command('archive_raw_messages', '--days=180', stdout=out)
        self.assertIn('Successfully deleted 5 messages older than 180 days.', out.getvalue())
        self.assertEqual(RawMessage.objects.count(), 3)

    def test_archive_command_no_old_messages(self):
        """
        Test the archive_raw_messages command when there are no old messages to delete.
        """
        RawMessage.objects.filter(created_at__lt=timezone.now() - timedelta(days=180)).delete()
        out = StringIO()
        call_command('archive_raw_messages', '--days=180', stdout=out)
        self.assertIn('No old messages to delete.', out.getvalue())
        self.assertEqual(RawMessage.objects.count(), 3)

class MessageIngestViewTests(APITestCase):
    def setUp(self):
        self.device_name = 'Test Ingest Device'
        self.plain_api_key = secrets.token_urlsafe(32)
        self.hashed_api_key = make_password(self.plain_api_key)
        self.device = Device.objects.create(
            name=self.device_name,
            api_key=self.hashed_api_key,
            default_gateway='till',
            gateway_number='54321'
        )
        self.url = reverse('message-ingest')

    @patch('payments.views.process_raw_message.delay')
    def test_ingest_message_queues_task(self, mock_delay):
        """
        Test that the ingest message view queues the processing task.
        """
        self.client.force_authenticate(user=self.device)
        data = {
            'raw_text': 'Test message',
            'received_at': timezone.now().isoformat()
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(RawMessage.objects.exists())
        message = RawMessage.objects.first()
        self.assertEqual(response.data['message_id'], message.id)
        mock_delay.assert_called_once_with(message.id)
