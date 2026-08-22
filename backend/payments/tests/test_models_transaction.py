from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from payments.models import Transaction, PaymentGateway
from .test_helpers import make_admin, make_gateway, make_transaction, make_product, make_line_item


class TransactionStateMachineTest(TestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.tx = make_transaction(tx_id='STM-TX-001', gateway=self.gateway)

    def test_initial_status_is_not_processed(self):
        self.assertEqual(self.tx.status, 'NOT_PROCESSED')

    def test_not_processed_can_transition_to_processing(self):
        self.assertTrue(self.tx.can_transition_to('PROCESSING'))

    def test_not_processed_can_transition_to_cancelled(self):
        self.assertTrue(self.tx.can_transition_to('CANCELLED'))

    def test_not_processed_can_transition_to_combined_fulfilled(self):
        self.assertTrue(self.tx.can_transition_to('COMBINED_FULFILLED'))

    def test_not_processed_cannot_transition_to_fulfilled(self):
        self.assertFalse(self.tx.can_transition_to('FULFILLED'))

    def test_not_processed_cannot_transition_to_partially_fulfilled(self):
        self.assertFalse(self.tx.can_transition_to('PARTIALLY_FULFILLED'))

    def test_processing_can_transition_to_partially_fulfilled(self):
        self.tx.status = 'PROCESSING'
        self.assertTrue(self.tx.can_transition_to('PARTIALLY_FULFILLED'))

    def test_processing_can_transition_to_fulfilled(self):
        self.tx.status = 'PROCESSING'
        self.assertTrue(self.tx.can_transition_to('FULFILLED'))

    def test_processing_can_transition_to_cancelled(self):
        self.tx.status = 'PROCESSING'
        self.assertTrue(self.tx.can_transition_to('CANCELLED'))

    def test_processing_can_transition_to_combined_fulfilled(self):
        self.tx.status = 'PROCESSING'
        self.assertTrue(self.tx.can_transition_to('COMBINED_FULFILLED'))

    def test_partially_fulfilled_can_revert_to_processing(self):
        self.tx.status = 'PARTIALLY_FULFILLED'
        self.assertTrue(self.tx.can_transition_to('PROCESSING'))

    def test_partially_fulfilled_can_transition_to_fulfilled(self):
        self.tx.status = 'PARTIALLY_FULFILLED'
        self.assertTrue(self.tx.can_transition_to('FULFILLED'))

    def test_partially_fulfilled_can_transition_to_cancelled(self):
        self.tx.status = 'PARTIALLY_FULFILLED'
        self.assertTrue(self.tx.can_transition_to('CANCELLED'))

    def test_partially_fulfilled_can_transition_to_combined_fulfilled(self):
        self.tx.status = 'PARTIALLY_FULFILLED'
        self.assertTrue(self.tx.can_transition_to('COMBINED_FULFILLED'))

    def test_fulfilled_is_terminal(self):
        self.tx.status = 'FULFILLED'
        for s in ['NOT_PROCESSED', 'PROCESSING', 'PARTIALLY_FULFILLED', 'CANCELLED', 'COMBINED_FULFILLED']:
            self.assertFalse(self.tx.can_transition_to(s), f'Should not transition from FULFILLED to {s}')

    def test_cancelled_is_terminal(self):
        self.tx.status = 'CANCELLED'
        for s in ['NOT_PROCESSED', 'PROCESSING', 'PARTIALLY_FULFILLED', 'FULFILLED', 'COMBINED_FULFILLED']:
            self.assertFalse(self.tx.can_transition_to(s), f'Should not transition from CANCELLED to {s}')

    def test_combined_fulfilled_is_terminal(self):
        self.tx.status = 'COMBINED_FULFILLED'
        for s in ['NOT_PROCESSED', 'PROCESSING', 'PARTIALLY_FULFILLED', 'FULFILLED', 'CANCELLED']:
            self.assertFalse(self.tx.can_transition_to(s), f'Should not transition from COMBINED_FULFILLED to {s}')

    def test_locked_transaction_rejects_all_transitions(self):
        self.tx.is_time_locked = True
        for s in ['PROCESSING', 'CANCELLED', 'COMBINED_FULFILLED']:
            self.assertFalse(self.tx.can_transition_to(s), f'Locked should reject transition to {s}')


class TransactionPropertiesTest(TestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.tx = make_transaction(tx_id='PROP-TX-001', amount=Decimal('1000.00'), gateway=self.gateway)

    def test_remaining_amount_equals_amount_when_nothing_fulfilled(self):
        self.assertEqual(self.tx.remaining_amount, Decimal('1000.00'))

    def test_remaining_amount_decreases_with_fulfillment(self):
        self.tx.amount_fulfilled = Decimal('400.00')
        self.assertEqual(self.tx.remaining_amount, Decimal('600.00'))

    def test_remaining_amount_zero_when_fulfilled(self):
        self.tx.status = 'FULFILLED'
        self.tx.amount_fulfilled = Decimal('1000.00')
        self.assertEqual(self.tx.remaining_amount, Decimal('0.00'))

    def test_remaining_amount_zero_when_cancelled(self):
        self.tx.status = 'CANCELLED'
        self.assertEqual(self.tx.remaining_amount, Decimal('0.00'))

    def test_is_locked_true_for_fulfilled(self):
        self.tx.status = 'FULFILLED'
        self.assertTrue(self.tx.is_locked)

    def test_is_locked_true_for_cancelled(self):
        self.tx.status = 'CANCELLED'
        self.assertTrue(self.tx.is_locked)

    def test_is_locked_true_when_time_locked(self):
        self.tx.is_time_locked = True
        self.assertTrue(self.tx.is_locked)

    def test_is_locked_false_for_active_statuses(self):
        for s in ['NOT_PROCESSED', 'PROCESSING', 'PARTIALLY_FULFILLED', 'COMBINED_FULFILLED']:
            self.tx.status = s
            self.tx.is_time_locked = False
            self.assertFalse(self.tx.is_locked, f'{s} should not be locked')

    def test_status_display_returns_dict(self):
        display = self.tx.status_display
        self.assertIn('status', display)
        self.assertIn('label', display)
        self.assertIn('color', display)
        self.assertIn('icon', display)
        self.assertEqual(display['status'], 'NOT_PROCESSED')

    def test_string_representation(self):
        self.assertIn('PROP-TX-001', str(self.tx))


class TransactionValidationTest(TestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.tx = make_transaction(tx_id='VAL-TX-001', amount=Decimal('1000.00'), gateway=self.gateway)

    def test_clean_raises_on_invalid_transition(self):
        self.tx.status = 'FULFILLED'
        with self.assertRaises(ValidationError):
            self.tx.clean()

    def test_clean_raises_when_amount_paid_exceeds_amount(self):
        self.tx.amount_paid = Decimal('2000.00')
        with self.assertRaises(ValidationError):
            self.tx.clean()

    def test_fulfilled_transition_enforces_amount_check_on_save(self):
        self.tx.status = 'PROCESSING'
        self.tx.save()
        self.tx.status = 'FULFILLED'
        self.tx.amount_fulfilled = Decimal('1000.00')
        self.tx.amount = Decimal('500.00')
        with self.assertRaises(ValidationError):
            self.tx.save()

    def test_save_with_skip_validation_bypasses_checks(self):
        self.tx.status = 'FULFILLED'
        self.tx.save(skip_validation=True)
        self.assertEqual(self.tx.status, 'FULFILLED')

    def test_unique_tx_id_constraint(self):
        with self.assertRaises(Exception):
            Transaction.objects.create(
                tx_id='VAL-TX-001', amount=Decimal('500.00'),
                gateway=self.gateway, timestamp=timezone.now(),
                unique_hash='hash_conflict'
            )

    def test_unique_hash_constraint(self):
        make_transaction(tx_id='VAL-TX-002', unique_hash='dup_hash')
        with self.assertRaises(Exception):
            Transaction.objects.create(
                tx_id='VAL-TX-003', amount=Decimal('500.00'),
                gateway=self.gateway, timestamp=timezone.now(),
                unique_hash='dup_hash'
            )

    def test_amount_fulfilled_cannot_exceed_amount(self):
        self.tx.amount_paid = Decimal('1500.00')
        self.tx.amount_fulfilled = Decimal('1500.00')
        with self.assertRaises(ValidationError):
            self.tx.clean()


class TransactionAutoFulfillTest(TestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.tx = make_transaction(tx_id='AUTO-TX-001', amount=Decimal('1000.00'))

    def test_auto_fulfills_when_amount_fulfilled_equals_amount(self):
        self.tx.status = 'PROCESSING'
        self.tx.amount_fulfilled = Decimal('1000.00')
        self.tx.save()
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'FULFILLED')

    def test_auto_marks_partially_fulfilled_when_partially_used(self):
        self.tx.status = 'PROCESSING'
        self.tx.amount_fulfilled = Decimal('400.00')
        self.tx.save()
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'PARTIALLY_FULFILLED')


class TransactionStatusColorsTest(TestCase):
    def test_get_status_color_returns_hex(self):
        tx = make_transaction(tx_id='CLR-TX-001')
        color = tx.get_status_color()
        self.assertTrue(color.startswith('#'))

    def test_get_status_icon_returns_string(self):
        tx = make_transaction(tx_id='ICN-TX-001')
        icon = tx.get_status_icon()
        self.assertIsInstance(icon, str)


class PaymentGatewayModelTest(TestCase):
    def setUp(self):
        self.gateway = make_gateway()

    def test_string_representation(self):
        self.assertIn('555000', str(self.gateway))

    def test_gateway_type_choices(self):
        self.assertIn(self.gateway.gateway_type, dict(PaymentGateway.GatewayType.choices))

    def test_settlement_none_returns_zero_parent(self):
        result = self.gateway.calculate_settlement(Decimal('1000.00'))
        self.assertEqual(result['total'], Decimal('1000.00'))
        self.assertEqual(result['parent_amount'], Decimal('0'))
        self.assertEqual(result['shop_amount'], Decimal('1000.00'))

    def test_settlement_parent_takes_all(self):
        gw = make_gateway(name='Parent Company GW', gateway_type='MPESA_TILL', gateway_number='PARENT-01')
        gw.settlement_type = 'PARENT_TAKES_ALL'
        gw.requires_parent_settlement = True
        gw.is_parent_company = True
        gw.save()
        result = gw.calculate_settlement(Decimal('1000.00'))
        self.assertEqual(result['parent_amount'], Decimal('1000.00'))
        self.assertEqual(result['shop_amount'], Decimal('0'))

    def test_settlement_percentage_split(self):
        gw = make_gateway(name='Commission Gateway', gateway_type='MPESA_TILL', gateway_number='COMM-01')
        gw.settlement_type = 'PERCENTAGE'
        gw.settlement_percentage = Decimal('20.00')
        gw.requires_parent_settlement = True
        gw.save()
        result = gw.calculate_settlement(Decimal('1000.00'))
        self.assertEqual(result['parent_amount'], Decimal('200.00'))
        self.assertEqual(result['shop_amount'], Decimal('800.00'))

    def test_settlement_cost_markup(self):
        gw = make_gateway(name='Cost Plus', gateway_type='MPESA_TILL', gateway_number='COST-01')
        gw.settlement_type = 'COST_MARKUP'
        gw.requires_parent_settlement = True
        gw.save()
        result = gw.calculate_settlement(Decimal('1000.00'))
        self.assertIn('cost_markup', result.get('calculation_note', ''))

    def test_settlement_custom_returns_placeholder(self):
        gw = make_gateway(name='Custom GW', gateway_type='MPESA_TILL', gateway_number='CUST-01')
        gw.settlement_type = 'CUSTOM'
        gw.requires_parent_settlement = True
        gw.save()
        result = gw.calculate_settlement(Decimal('1000.00'))
        self.assertIn('manual review', result.get('calculation_note', ''))

    def test_is_active_default_true(self):
        self.assertTrue(self.gateway.is_active)
