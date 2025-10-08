from django.test import TestCase
from django.utils import timezone
from ..models import Device, RawMessage, Transaction
from ..tasks import process_raw_message
import hashlib

class TransactionLifecycleTest(TestCase):
    def setUp(self):
        self.device = Device.objects.create(
            name="Test Phone",
            default_gateway="Safaricom",
            gateway_number="223344"
        )
        self.valid_mpesa_sms = (
            "QWERTY12345 Confirmed. You have received Ksh1,234.56 from JOHN DOE 0712345678 "
            "on 1/1/2023 at 1:00 PM. New M-PESA balance is Ksh5,432.10."
        )

    def test_successful_message_processing_creates_transaction(self):
        # Create a raw message
        raw_message = RawMessage.objects.create(
            device=self.device,
            raw_text=self.valid_mpesa_sms,
            received_at=timezone.now()
        )

        # Process the message
        process_raw_message(raw_message.id)

        # Verify that a Transaction was created
        self.assertEqual(Transaction.objects.count(), 1)
        transaction = Transaction.objects.first()
        raw_message.refresh_from_db()
        self.assertEqual(raw_message.transaction, transaction)
        self.assertEqual(transaction.tx_id, "QWERTY12345")
        self.assertEqual(float(transaction.amount), 1234.56)
        self.assertEqual(transaction.status, Transaction.OrderStatus.NOT_PROCESSED)
        self.assertEqual(float(transaction.amount_expected), 1234.56)

        # Verify the raw message is marked as processed
        raw_message.refresh_from_db()
        self.assertTrue(raw_message.processed)

    def test_duplicate_message_handling(self):
        # Create and process the first message
        raw_message_1 = RawMessage.objects.create(
            device=self.device,
            raw_text=self.valid_mpesa_sms,
            received_at=timezone.now()
        )
        process_raw_message(raw_message_1.id)

        # Create and process a duplicate message
        raw_message_2 = RawMessage.objects.create(
            device=self.device,
            raw_text=self.valid_mpesa_sms,
            received_at=timezone.now()
        )
        process_raw_message(raw_message_2.id)

        # Verify that only one Transaction was created
        self.assertEqual(Transaction.objects.count(), 1)

        # Verify that the second raw message is linked to the first transaction
        raw_message_2.refresh_from_db()
        self.assertIsNotNone(raw_message_2.transaction)
        self.assertEqual(raw_message_2.transaction, Transaction.objects.first())