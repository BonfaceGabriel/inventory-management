from django.test import TestCase
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone
from datetime import timedelta
from io import StringIO

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
