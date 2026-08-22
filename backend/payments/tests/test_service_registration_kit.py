from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from payments.services.registration_kit_service import RegistrationKitService
from payments.models import InventoryMovement
from .test_helpers import (
    make_admin, make_gateway, make_transaction, make_product,
    make_registration_kit_product, make_line_item,
)


class RegistrationKitServiceTest(TestCase):
    def setUp(self):
        self.reg_kit = make_registration_kit_product()
        self.reg_kit.quantity = 50
        self.reg_kit.save()
        self.gateway = make_gateway()
        self.tx = make_transaction(
            tx_id='REG-TX-001', amount=Decimal('5000.00'),
            is_registration=True,
        )

    def test_calculate_transaction_pv_with_line_items(self):
        product = make_product(prod_code='PV-PROD', pv=Decimal('10.00'))
        make_line_item(self.tx, product, quantity=3)
        make_line_item(
            self.tx,
            make_product(prod_code='PV-PROD2', pv=Decimal('5.00'), sku='SKU-PV2'),
            quantity=2,
        )
        pv = RegistrationKitService.calculate_transaction_pv(self.tx)
        self.assertEqual(pv, Decimal('40.00'))

    def test_calculate_transaction_pv_without_line_items(self):
        pv = RegistrationKitService.calculate_transaction_pv(self.tx)
        self.assertEqual(pv, Decimal('0.00'))

    def test_can_issue_registration_kit_true(self):
        product = make_product(prod_code='PV-CAN', pv=Decimal('10.00'))
        make_line_item(self.tx, product, quantity=3)
        can, reason = RegistrationKitService.can_issue_registration_kit(self.tx)
        self.assertTrue(can)

    def test_can_issue_registration_kit_false_not_registration(self):
        self.tx.is_registration = False
        can, reason = RegistrationKitService.can_issue_registration_kit(self.tx)
        self.assertFalse(can)

    def test_can_issue_registration_kit_false_already_issued(self):
        self.tx.registration_kit_issued = True
        can, reason = RegistrationKitService.can_issue_registration_kit(self.tx)
        self.assertFalse(can)

    def test_can_issue_registration_kit_false_insufficient_balance(self):
        self.tx.amount = Decimal('2000.00')
        self.tx.save()
        can, reason = RegistrationKitService.can_issue_registration_kit(self.tx)
        self.assertFalse(can)

    def test_issue_registration_kit_deducts_inventory(self):
        tx = RegistrationKitService.issue_registration_kit(
            transaction_id=self.tx.id,
            quantity=1,
            issued_by='test',
        )
        self.reg_kit.refresh_from_db()
        self.assertEqual(self.reg_kit.quantity, 49)
        tx.refresh_from_db()
        self.assertTrue(tx.registration_kit_issued)
        self.assertEqual(tx.registration_kit_quantity, 1)
        mov = InventoryMovement.objects.filter(
            product=self.reg_kit, movement_type='SALE'
        ).first()
        self.assertIsNotNone(mov)

    def test_issue_registration_kit_multiple_quantity(self):
        tx = RegistrationKitService.issue_registration_kit(
            transaction_id=self.tx.id,
            quantity=1,
            issued_by='test',
        )
        tx.refresh_from_db()
        self.assertTrue(tx.registration_kit_issued)
        self.assertEqual(tx.registration_kit_quantity, 1)
        self.assertEqual(tx.registration_kit_amount_deducted, Decimal('2900.00'))

    def test_issue_registration_kit_raises_on_insufficient_stock(self):
        self.reg_kit.quantity = 0
        self.reg_kit.save()
        with self.assertRaises(ValidationError):
            RegistrationKitService.issue_registration_kit(
                transaction_id=self.tx.id,
                quantity=1,
                issued_by='test',
            )

    def test_issue_registration_kit_raises_on_product_not_found(self):
        self.reg_kit.delete()
        with self.assertRaises(ValidationError):
            RegistrationKitService.issue_registration_kit(
                transaction_id=self.tx.id,
                quantity=1,
                issued_by='test',
            )

    def test_validate_pv_before_activation_passes(self):
        product = make_product(prod_code='PV-ACT', pv=Decimal('10.00'))
        make_line_item(self.tx, product, quantity=3)
        RegistrationKitService.issue_registration_kit(
            transaction_id=self.tx.id, quantity=1, issued_by='test',
        )
        self.tx.refresh_from_db()
        RegistrationKitService.validate_pv_before_activation(self.tx)

    def test_validate_pv_before_completion_passes(self):
        product = make_product(prod_code='PV-COMP', pv=Decimal('10.00'))
        make_line_item(self.tx, product, quantity=3)
        RegistrationKitService.issue_registration_kit(
            transaction_id=self.tx.id, quantity=1, issued_by='test',
        )
        self.tx.refresh_from_db()
        RegistrationKitService.validate_pv_before_completion(self.tx)


class RegistrationKitTransaction(TestCase):
    def test_non_registration_transaction_rejects_kit(self):
        tx = make_transaction(tx_id='REG-NON', amount=Decimal('5000.00'), is_registration=False)
        can, reason = RegistrationKitService.can_issue_registration_kit(tx)
        self.assertFalse(can)
