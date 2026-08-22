from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth import get_user_model

from payments.models import (
    Location, Device, ManualPayment, RawMessage,
    GeneratedReport,
)
from .test_helpers import (
    make_admin, make_processor, make_issuer, make_gateway,
    make_device, make_transaction, make_location, now,
)

User = get_user_model()


class LocationModelTest(TestCase):
    def setUp(self):
        self.location = make_location()

    def test_string_representation(self):
        self.assertIn('Main Shop', str(self.location))

    def test_main_location_type(self):
        self.assertEqual(self.location.location_type, 'MAIN')

    def test_active_status_default(self):
        self.assertEqual(self.location.status, 'ACTIVE')

    def test_is_main_property_true(self):
        self.assertTrue(self.location.is_main)

    def test_is_main_property_false(self):
        field = Location.objects.create(name='Field Office', location_type='FIELD')
        self.assertFalse(field.is_main)

    def test_unique_name_constraint(self):
        with self.assertRaises(Exception):
            Location.objects.create(name='Main Shop', location_type='FIELD')

    def test_get_main_location_returns_singleton(self):
        loc1 = Location.get_main_location()
        loc2 = Location.get_main_location()
        self.assertEqual(loc1.id, loc2.id)


class UserModelTest(TestCase):
    def test_admin_role_check(self):
        user = make_admin(username='test_admin')
        self.assertTrue(user.is_admin())
        self.assertTrue(user.has_processor_access())
        self.assertTrue(user.has_issuer_access())

    def test_processor_role_check(self):
        user = make_processor(username='test_processor')
        self.assertTrue(user.is_processor())
        self.assertFalse(user.is_admin())
        self.assertTrue(user.has_processor_access())
        self.assertFalse(user.has_issuer_access())

    def test_issuer_role_check(self):
        user = make_issuer(username='test_issuer')
        self.assertTrue(user.is_issuer())
        self.assertFalse(user.is_admin())
        self.assertFalse(user.has_processor_access())
        self.assertTrue(user.has_issuer_access())

    def test_string_representation_includes_role(self):
        user = make_admin(username='str_user')
        self.assertIn('str_user', str(user))
        self.assertIn('Administrator', str(user))

    def test_current_location_nullable(self):
        user = make_admin(username='no_loc_user')
        self.assertIsNone(user.current_location)

    def test_current_location_settable(self):
        loc = make_location()
        user = make_admin(username='with_loc_user')
        user.current_location = loc
        user.save()
        user.refresh_from_db()
        self.assertEqual(user.current_location, loc)


class DeviceModelTest(TestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.device = make_device(gateway=self.gateway)

    def test_string_representation(self):
        self.assertEqual(str(self.device), 'Test Device')

    def test_api_key_is_unique(self):
        device2 = Device.objects.create(
            name='Device 2', phone_number='0722222222', gateway=self.gateway,
            api_key='unique-key-2'
        )
        self.assertNotEqual(self.device.api_key, device2.api_key)

    def test_api_key_is_generated(self):
        self.assertTrue(len(self.device.api_key) > 0)

    def test_phone_number_optional(self):
        device = Device.objects.create(
            name='No Phone', gateway=self.gateway,
            api_key='no-phone-key'
        )
        self.assertIsNone(device.phone_number)

    def test_last_seen_at_updates_on_save(self):
        old = self.device.last_seen_at
        self.device.save()
        self.device.refresh_from_db()
        self.assertNotEqual(self.device.last_seen_at, old)


class ManualPaymentModelTest(TestCase):
    def setUp(self):
        self.tx = make_transaction(tx_id='MP-MODEL-TX')

    def test_string_representation(self):
        mp = make_manual_payment_bare(self.tx)
        self.assertIn(str(mp.amount), str(mp))
        self.assertIn(mp.payer_name, str(mp))

    def test_clean_validates_positive_amount(self):
        mp = ManualPayment(
            transaction=self.tx, payment_method='CASH',
            amount=Decimal('-100.00'), payer_name='Test',
            payment_date=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            mp.clean()

    def test_clean_requires_reference_for_pdq(self):
        mp = ManualPayment(
            transaction=self.tx, payment_method='PDQ',
            amount=Decimal('500.00'), payer_name='Test',
            payment_date=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            mp.clean()

    def test_clean_requires_reference_for_bank(self):
        mp = ManualPayment(
            transaction=self.tx, payment_method='BANK_TRANSFER',
            amount=Decimal('500.00'), payer_name='Test',
            payment_date=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            mp.clean()

    def test_clean_passes_with_reference_for_pdq(self):
        mp = ManualPayment(
            transaction=self.tx, payment_method='PDQ',
            amount=Decimal('500.00'), payer_name='Test',
            reference_number='PDQ-REF-001',
            payment_date=timezone.now(),
        )
        mp.clean()

    def test_clean_passes_without_reference_for_cash(self):
        mp = ManualPayment(
            transaction=self.tx, payment_method='CASH',
            amount=Decimal('500.00'), payer_name='Test',
            payment_date=timezone.now(),
        )
        mp.clean()

    def test_negative_amount_raises(self):
        with self.assertRaises(ValidationError):
            mp = ManualPayment(
                transaction=self.tx, payment_method='CASH',
                amount=Decimal('-50.00'), payer_name='Test',
                payment_date=timezone.now(),
            )
            mp.clean()

    def test_all_payment_methods_available(self):
        methods = dict(ManualPayment.PaymentMethod.choices)
        self.assertIn('PDQ', methods)
        self.assertIn('BANK_TRANSFER', methods)
        self.assertIn('CASH', methods)
        self.assertIn('CHEQUE', methods)
        self.assertIn('OTHER', methods)


class RawMessageModelTest(TestCase):
    def setUp(self):
        self.device = make_device()

    def test_string_representation(self):
        msg = RawMessage.objects.create(
            device=self.device,
            raw_text='Test SMS content',
            received_at=timezone.now(),
        )
        self.assertIn(self.device.name, str(msg))

    def test_clean_strips_control_characters(self):
        msg = RawMessage(
            device=self.device,
            raw_text='Hello\x00World\x1fTest',
            received_at=timezone.now(),
        )
        msg.clean()
        self.assertEqual(msg.raw_text, 'HelloWorldTest')

    def test_clean_does_not_affect_normal_text(self):
        msg = RawMessage(
            device=self.device,
            raw_text='Hello World! Normal text here.',
            received_at=timezone.now(),
        )
        msg.clean()
        self.assertEqual(msg.raw_text, 'Hello World! Normal text here.')

    def test_processed_defaults_false(self):
        msg = RawMessage.objects.create(
            device=self.device,
            raw_text='Fresh message',
            received_at=timezone.now(),
        )
        self.assertFalse(msg.processed)

    def test_transaction_nullable(self):
        msg = RawMessage.objects.create(
            device=self.device,
            raw_text='Orphan message',
            received_at=timezone.now(),
        )
        self.assertIsNone(msg.transaction)

    def test_max_length_validator(self):
        with self.assertRaises(ValidationError):
            msg = RawMessage(
                device=self.device,
                raw_text='X' * 1100,
                received_at=timezone.now(),
            )
            msg.full_clean()


class GeneratedReportModelTest(TestCase):
    def test_string_representation(self):
        report = GeneratedReport.objects.create(
            report_date=timezone.localdate(),
            report_file=b'binary data',
        )
        self.assertIn(str(report.report_date), str(report))

    def test_report_file_stores_binary(self):
        report = GeneratedReport.objects.create(
            report_date=timezone.localdate(),
            report_file=b'\x00\x01\x02\x03',
        )
        self.assertEqual(report.report_file, b'\x00\x01\x02\x03')

    def test_unique_report_date(self):
        GeneratedReport.objects.create(
            report_date=timezone.localdate(),
            report_file=b'first',
        )
        with self.assertRaises(Exception):
            GeneratedReport.objects.create(
                report_date=timezone.localdate(),
                report_file=b'second',
            )


def make_manual_payment_bare(transaction, payment_method='CASH', amount=Decimal('500.00'),
                             payer_name='Jane Doe'):
    return ManualPayment.objects.create(
        transaction=transaction,
        payment_method=payment_method,
        amount=amount,
        payer_name=payer_name,
        payer_phone='0722222222',
        payment_date=timezone.now(),
    )
