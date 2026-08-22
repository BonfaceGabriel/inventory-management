from decimal import Decimal
from django.test import TransactionTestCase
from django.core.exceptions import ValidationError
from payments.services.stock_take_service import StockTakeService
from payments.models import StockTakeSession, StockTakeItem, InventoryMovement
from .test_helpers import (
    make_admin, make_product, make_gateway, make_transaction,
)


class StockTakeServiceTest(TransactionTestCase):
    def setUp(self):
        self.admin = make_admin(username='stk_admin')
        self.product = make_product(prod_code='STK-PROD', quantity=100)
        self.product2 = make_product(prod_code='STK-PROD2', quantity=50)

    def test_create_session(self):
        session = StockTakeService.create_session(created_by=self.admin)
        self.assertIsNotNone(session)
        self.assertEqual(session.status, 'DRAFT')
        self.assertTrue(session.session_id.startswith('STK-'))

    def test_get_active_session_returns_active(self):
        StockTakeService.create_session(created_by=self.admin)
        active = StockTakeService.get_active_session()
        self.assertIsNotNone(active)

    def test_get_active_session_returns_none_when_none_active(self):
        active = StockTakeService.get_active_session()
        self.assertIsNone(active)

    def test_has_active_session_true(self):
        StockTakeService.create_session(created_by=self.admin)
        self.assertTrue(StockTakeService.has_active_session())

    def test_has_active_session_false(self):
        self.assertFalse(StockTakeService.has_active_session())

    def test_scan_product_adds_item(self):
        session = StockTakeService.create_session(created_by=self.admin)
        result = StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=10,
            scanned_by=self.admin,
        )
        self.assertIsNotNone(result)
        self.assertEqual(session.items.count(), 1)
        item = session.items.first()
        self.assertEqual(item.quantity_before, 100)
        self.assertEqual(item.quantity_scanned, 10)
        self.assertEqual(item.quantity_after, 110)

    def test_scan_product_update_existing(self):
        session = StockTakeService.create_session(created_by=self.admin)
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=10,
            scanned_by=self.admin,
        )
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=5,
            scanned_by=self.admin,
        )
        self.assertEqual(session.items.count(), 1)
        item = session.items.first()
        self.assertEqual(item.quantity_scanned, 15)

    def test_scan_multiple_products(self):
        session = StockTakeService.create_session(created_by=self.admin)
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=10,
            scanned_by=self.admin,
        )
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product2.id,
            quantity=5,
            scanned_by=self.admin,
        )
        self.assertEqual(session.items.count(), 2)

    def test_complete_session_updates_inventory(self):
        session = StockTakeService.create_session(created_by=self.admin)
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=10,
            scanned_by=self.admin,
        )
        StockTakeService.complete_session(
            session_id=session.session_id,
            completed_by=self.admin,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 110)
        mov = InventoryMovement.objects.filter(
            product=self.product, movement_type='STOCK_TAKE'
        ).first()
        self.assertIsNotNone(mov)
        self.assertEqual(mov.quantity_change, 10)

    def test_complete_session_without_items(self):
        session = StockTakeService.create_session(created_by=self.admin)
        with self.assertRaises(ValidationError):
            StockTakeService.complete_session(
                session_id=session.session_id,
                completed_by=self.admin,
            )

    def test_cancel_session(self):
        session = StockTakeService.create_session(created_by=self.admin)
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=10,
            scanned_by=self.admin,
        )
        StockTakeService.cancel_session(
            session_id=session.session_id,
            cancelled_by=self.admin,
        )
        session.refresh_from_db()
        self.assertEqual(session.status, 'CANCELLED')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 100)

    def test_remove_item(self):
        session = StockTakeService.create_session(created_by=self.admin)
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=10,
            scanned_by=self.admin,
        )
        item = session.items.first()
        StockTakeService.remove_item(
            session_id=session.session_id,
            item_id=item.id,
        )
        self.assertEqual(session.items.count(), 0)

    def test_update_item_quantity(self):
        session = StockTakeService.create_session(created_by=self.admin)
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=10,
            scanned_by=self.admin,
        )
        item = session.items.first()
        StockTakeService.update_item_quantity(
            session_id=session.session_id,
            item_id=item.id,
            new_quantity=25,
        )
        item.refresh_from_db()
        self.assertEqual(item.quantity_scanned, 25)
        self.assertEqual(item.quantity_after, 125)

    def test_get_session_details(self):
        session = StockTakeService.create_session(created_by=self.admin, notes='Test session')
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=10,
            scanned_by=self.admin,
        )
        details = StockTakeService.get_session_details(session.session_id)
        self.assertEqual(details.session_id, session.session_id)
        self.assertEqual(details.items.count(), 1)
