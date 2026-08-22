from decimal import Decimal
from django.test import TransactionTestCase
from django.core.exceptions import ValidationError
from payments.services.admin_service import AdminService
from payments.models import Transaction, InventoryMovement
from .test_helpers import (
    make_admin, make_gateway, make_transaction, make_product,
    make_issuer, make_line_item,
)


class AdminServiceTest(TransactionTestCase):
    def setUp(self):
        self.admin = make_admin()
        self.issuer = make_issuer()
        self.gateway = make_gateway()
        self.product = make_product(prod_code='ADM-PROD', price=Decimal('500.00'), quantity=100)
        self.tx = make_transaction(tx_id='ADM-TX-001', amount=Decimal('1000.00'))

    def test_cancel_fulfilled_transaction_from_fulfilled(self):
        self.tx.status = 'FULFILLED'
        self.tx.amount_fulfilled = Decimal('1000.00')
        self.tx.save(skip_validation=True)
        li = make_line_item(self.tx, self.product, quantity=2, scanned_by_user=self.issuer)
        li.is_inventory_deducted = True
        li.save()
        self.product.quantity = 98
        self.product.save()
        result = AdminService.cancel_fulfilled_transaction(
            transaction_id=self.tx.id,
            cancelled_by_user=self.admin,
            reason='Customer return',
        )
        self.assertTrue(result['success'])
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'NOT_PROCESSED')
        self.assertEqual(self.tx.amount_fulfilled, Decimal('0.00'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 100)
        mov = InventoryMovement.objects.filter(
            product=self.product, movement_type='RETURN'
        ).first()
        self.assertIsNotNone(mov)
        self.assertEqual(mov.quantity_change, 2)

    def test_cancel_fulfilled_rejects_not_fulfilled(self):
        with self.assertRaises(ValidationError):
            AdminService.cancel_fulfilled_transaction(
                transaction_id=self.tx.id,
                cancelled_by_user=self.admin,
                reason='Should fail',
            )

    def test_cancel_fulfilled_requires_reason(self):
        self.tx.status = 'FULFILLED'
        self.tx.save(skip_validation=True)
        result = AdminService.cancel_fulfilled_transaction(
            transaction_id=self.tx.id,
            cancelled_by_user=self.admin,
            reason='',
        )
        self.assertTrue(result['success'])
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'NOT_PROCESSED')

    def test_cancel_fulfilled_from_partially_fulfilled(self):
        self.tx.status = 'PARTIALLY_FULFILLED'
        self.tx.amount_fulfilled = Decimal('500.00')
        self.tx.save(skip_validation=True)
        li = make_line_item(self.tx, self.product, quantity=1, scanned_by_user=self.issuer)
        li.is_inventory_deducted = True
        li.save()
        self.product.quantity = 99
        self.product.save()
        result = AdminService.cancel_fulfilled_transaction(
            transaction_id=self.tx.id,
            cancelled_by_user=self.admin,
            reason='Partial return',
        )
        self.assertTrue(result['success'])
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 100)

    def test_cancel_registration_order(self):
        self.tx.is_registration = True
        self.tx.registration_kit_issued = True
        self.tx.registration_kit_quantity = 1
        self.tx.registration_kit_amount_deducted = Decimal('2900.00')
        self.tx.amount_fulfilled = Decimal('2900.00')
        self.tx.status = 'PARTIALLY_FULFILLED'
        self.tx.save(skip_validation=True)
        result = AdminService.cancel_registration_order(
            transaction_id=self.tx.id,
            cancelled_by_user=self.admin,
            reason='Registration cancelled',
        )
        self.assertTrue(result['success'])
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'NOT_PROCESSED')

    def test_delete_transaction(self):
        result = AdminService.delete_transaction(
            transaction_id=self.tx.id,
            deleted_by_user=self.admin,
            reason='Test delete',
        )
        self.assertTrue(result['success'])
        with self.assertRaises(Transaction.DoesNotExist):
            Transaction.objects.get(id=self.tx.id)
