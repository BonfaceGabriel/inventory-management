from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from ..models import Transaction, Product, InventoryMovement
from ..services.registration_kit_service import RegistrationKitService


class RegistrationKitServiceTest(TestCase):
    def setUp(self):
        # Create a test product for the registration kit
        self.reg_kit_product = Product.objects.create(
            prod_code='REG_KIT_001',
            prod_name='Registration Kit',
            description='M-Pesa Registration Kit',
            quantity=100,  # Initial stock
            buying_price=Decimal('2000.00'),
            current_price=Decimal('2900.00'),
            is_registration_kit=True
        )

        # Create a test transaction marked as a registration
        self.transaction = Transaction.objects.create(
            tx_id='TESTREG001',
            amount=Decimal('5000.00'),  # Sufficient amount
            is_registration=True,
            status=Transaction.OrderStatus.NOT_PROCESSED
        )

    def test_issue_registration_kit_deducts_inventory(self):
        initial_kit_quantity = self.reg_kit_product.quantity
        issued_quantity = 1
        expected_deduction_amount = RegistrationKitService.REGISTRATION_KIT_PRICE * issued_quantity

        # Issue the registration kit
        updated_transaction = RegistrationKitService.issue_registration_kit(
            self.transaction.id,
            quantity=issued_quantity,
            issued_by='test_user'
        )

        # Refresh objects from DB
        self.reg_kit_product.refresh_from_db()
        self.transaction.refresh_from_db()

        # Assert Transaction fields are updated
        self.assertTrue(updated_transaction.registration_kit_issued)
        self.assertEqual(updated_transaction.registration_kit_quantity, issued_quantity)
        self.assertEqual(updated_transaction.registration_kit_amount_deducted, expected_deduction_amount)
        self.assertEqual(updated_transaction.amount_fulfilled, expected_deduction_amount)
        self.assertEqual(updated_transaction.status, Transaction.OrderStatus.PROCESSING)

        # Assert Product quantity has decreased
        self.assertEqual(self.reg_kit_product.quantity, initial_kit_quantity - issued_quantity)

        # Assert InventoryMovement record is created
        movement = InventoryMovement.objects.get(
            product=self.reg_kit_product,
            movement_type=InventoryMovement.MovementType.DEDUCTION,
            reference=f'Registration Kit Issued for Transaction {self.transaction.tx_id}'
        )
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity_change, -issued_quantity)
        self.assertEqual(movement.performed_by, 'test_user')

    def test_issue_registration_kit_multiple_quantity_deducts_inventory(self):
        initial_kit_quantity = self.reg_kit_product.quantity
        issued_quantity = 2
        expected_deduction_amount = RegistrationKitService.REGISTRATION_KIT_PRICE * issued_quantity

        # Issue multiple registration kits
        updated_transaction = RegistrationKitService.issue_registration_kit(
            self.transaction.id,
            quantity=issued_quantity,
            issued_by='test_user'
        )

        self.reg_kit_product.refresh_from_db()
        self.transaction.refresh_from_db()

        self.assertTrue(updated_transaction.registration_kit_issued)
        self.assertEqual(updated_transaction.registration_kit_quantity, issued_quantity)
        self.assertEqual(updated_transaction.registration_kit_amount_deducted, expected_deduction_amount)
        self.assertEqual(updated_transaction.amount_fulfilled, expected_deduction_amount)
        self.assertEqual(updated_transaction.status, Transaction.OrderStatus.PROCESSING)
        self.assertEqual(self.reg_kit_product.quantity, initial_kit_quantity - issued_quantity)

        movement = InventoryMovement.objects.get(
            product=self.reg_kit_product,
            movement_type=InventoryMovement.MovementType.DEDUCTION,
            reference=f'Registration Kit Issued for Transaction {self.transaction.tx_id}'
        )
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity_change, -issued_quantity)

    def test_issue_registration_kit_product_not_found(self):
        # Delete the registration kit product to simulate it not existing
        self.reg_kit_product.delete()

        with self.assertRaisesMessage(ValidationError, "Registration kit product 'REG_KIT_001' not found in inventory. Cannot issue."):
            RegistrationKitService.issue_registration_kit(
                self.transaction.id,
                quantity=1,
                issued_by='test_user'
            )

    def test_issue_registration_kit_insufficient_stock(self):
        # Reduce stock to 0 to trigger insufficient stock error
        self.reg_kit_product.quantity = 0
        self.reg_kit_product.save()
        self.reg_kit_product.refresh_from_db() # Ensure the change is saved and reloaded

        expected_error_message = (
            f"Insufficient stock for Registration Kit ({self.reg_kit_product.prod_code}). "
            f"Available: {self.reg_kit_product.quantity}, Requested: 1."
        )

        with self.assertRaisesMessage(ValidationError, expected_error_message):
            RegistrationKitService.issue_registration_kit(
                self.transaction.id,
                quantity=1,
                issued_by='test_user'
            )
