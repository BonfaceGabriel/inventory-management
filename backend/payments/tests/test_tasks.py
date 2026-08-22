from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from payments.models import RawMessage, GeneratedReport
from payments.tasks import process_raw_message
from .test_helpers import (
    make_gateway, make_device, make_transaction,
)


class CeleryTasksTest(TestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.device = make_device(gateway=self.gateway)

    def test_process_raw_message_creates_transaction(self):
        msg = RawMessage.objects.create(
            device=self.device,
            raw_text="JOHN DOE sent KES 1,200.00 to TILL NUMBER 555000. New balance: KES 50,000.00. Transaction ID: CELERYTX01 on 20/05/2026 at 18:10",
        )
        result = process_raw_message(msg.id)
        self.assertIsNotNone(result)
        self.assertTrue(result['success'])
        msg.refresh_from_db()
        self.assertTrue(msg.processed)

    def test_process_raw_message_handles_unparseable(self):
        msg = RawMessage.objects.create(
            device=self.device,
            raw_text="This is not an M-PESA message",
        )
        result = process_raw_message(msg.id)
        self.assertIsNotNone(result)
        self.assertFalse(result['success'])
        msg.refresh_from_db()
        self.assertFalse(msg.processed)

    def test_process_raw_message_deduplication(self):
        msg1 = RawMessage.objects.create(
            device=self.device,
            raw_text="JOHN DOE sent KES 1,200.00 to TILL NUMBER 555000. New balance: KES 50,000.00. Transaction ID: DEDUP01 on 20/05/2026 at 18:10",
        )
        msg2 = RawMessage.objects.create(
            device=self.device,
            raw_text="JOHN DOE sent KES 1,200.00 to TILL NUMBER 555000. New balance: KES 50,000.00. Transaction ID: DEDUP01 on 20/05/2026 at 18:10",
        )
        result1 = process_raw_message(msg1.id)
        result2 = process_raw_message(msg2.id)
        self.assertTrue(result1['success'])
        self.assertFalse(result2['success'])

    def test_process_raw_message_nonexistent(self):
        result = process_raw_message(99999)
        self.assertEqual(result, {'success': False, 'reason': 'not_found'})

    def test_generate_daily_report_celery_task(self):
        from payments.tasks import generate_daily_report
        result = generate_daily_report()
        self.assertIsNone(result)
