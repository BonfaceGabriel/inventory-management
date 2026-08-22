from decimal import Decimal
from django.test import TestCase, TransactionTestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from payments.services.merchandise_service import MerchandiseService
from payments.models import (
    MerchandiseCatalogItem, MerchandiseCatalogOption,
    MerchandiseOrder, MerchandiseOrderLine,
    MerchandiseStock, MerchandiseStockMovement,
    PaymentGateway,
)
from .test_helpers import make_admin, make_gateway, make_device, make_transaction


class MerchandiseServiceTest(TransactionTestCase):
    def setUp(self):
        self.admin = make_admin(username='merch_admin')
        self.merch_gw = make_gateway(
            name='Merchandise GW', gateway_type='MERCHANDISE', gateway_number='MERCH-01',
        )
        self.till_gw = make_gateway(
            name='Regular Till', gateway_type='MPESA_TILL', gateway_number='TILL-MERCH',
        )
        self.item = MerchandiseCatalogItem.objects.create(
            code='TSHIRT-MSRV', name='Service T-Shirt',
            item_type='TSHIRT', unit_price=Decimal('1500.00'),
        )
        MerchandiseCatalogOption.objects.create(item=self.item, option_type='COLOR', value='Red')
        MerchandiseCatalogOption.objects.create(item=self.item, option_type='SIZE', value='Large')
        self.stock = MerchandiseStock.objects.create(
            item=self.item, color='Red', size='Large', quantity=20,
        )

    def test_is_merchandise_gateway_true(self):
        self.assertTrue(MerchandiseService.is_merchandise_gateway(self.merch_gw))

    def test_is_merchandise_gateway_false(self):
        self.assertFalse(MerchandiseService.is_merchandise_gateway(self.till_gw))

    def test_create_pending_order_for_transaction(self):
        tx = make_transaction(
            tx_id='MERCH-ORD', amount=Decimal('3000.00'), gateway=self.merch_gw,
        )
        order = MerchandiseService.create_pending_order_for_transaction(tx)
        self.assertIsNotNone(order)
        self.assertEqual(order.status, 'PENDING')
        self.assertEqual(order.transaction, tx)

    def test_create_pending_order_skips_non_merchandise(self):
        tx = make_transaction(
            tx_id='MERCH-NON', amount=Decimal('1000.00'), gateway=self.till_gw,
            unique_hash='hash_merch_non',
        )
        order = MerchandiseService.create_pending_order_for_transaction(tx)
        self.assertIsNone(order)

    def test_get_pending_orders(self):
        tx = make_transaction(
            tx_id='MERCH-PEND', amount=Decimal('3000.00'), gateway=self.merch_gw,
        )
        MerchandiseService.create_pending_order_for_transaction(tx)
        pending = MerchandiseService.get_pending_orders()
        self.assertEqual(pending.count(), 1)

    def test_get_stock_rows(self):
        rows = MerchandiseService.get_stock_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['code'], 'TSHIRT-MSRV')
        self.assertEqual(rows[0]['quantity'], 20)

    def test_adjust_stock_add(self):
        result = MerchandiseService.adjust_stock(
            adjustments=[{
                'stock_id': self.stock.id,
                'quantity_change': 10,
            }],
            user=self.admin,
            notes='Restock',
        )
        self.assertTrue(result['success'])
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 30)

    def test_adjust_stock_deduct(self):
        result = MerchandiseService.adjust_stock(
            adjustments=[{
                'stock_id': self.stock.id,
                'quantity_change': -5,
            }],
            user=self.admin,
            notes='Damaged',
        )
        self.assertTrue(result['success'])
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 15)

    def test_adjust_stock_creates_movement(self):
        MerchandiseService.adjust_stock(
            adjustments=[{
                'stock_id': self.stock.id,
                'quantity_change': 10,
            }],
            user=self.admin,
            notes='Restock',
        )
        mov = MerchandiseStockMovement.objects.filter(stock=self.stock).first()
        self.assertIsNotNone(mov)
        self.assertEqual(mov.movement_type, 'MANUAL_ADD')

    def test_fulfill_order(self):
        tx = make_transaction(
            tx_id='MERCH-FUL', amount=Decimal('3000.00'), gateway=self.merch_gw,
        )
        order = MerchandiseService.create_pending_order_for_transaction(tx)
        result = MerchandiseService.fulfill_order(
            order=order,
            lines_payload=[{
                'item_id': self.item.id,
                'quantity': 2,
                'color': 'Red',
                'size': 'Large',
            }],
            user=self.admin,
        )
        self.assertTrue(result['success'])
        order.refresh_from_db()
        self.assertEqual(order.status, 'FULFILLED')
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 18)

    def test_fulfill_order_insufficient_stock(self):
        self.stock.quantity = 1
        self.stock.save()
        tx = make_transaction(
            tx_id='MERCH-NSF', amount=Decimal('3000.00'), gateway=self.merch_gw,
            unique_hash='hash_merch_nsf',
        )
        order = MerchandiseService.create_pending_order_for_transaction(tx)
        with self.assertRaises(ValidationError):
            MerchandiseService.fulfill_order(
                order=order,
                lines_payload=[{
                    'item_id': self.item.id,
                    'quantity': 5,
                    'color': 'Red',
                    'size': 'Large',
                }],
                user=self.admin,
            )

    def test_get_daily_report_rows(self):
        tx = make_transaction(
            tx_id='MERCH-REP', amount=Decimal('3000.00'), gateway=self.merch_gw,
        )
        order = MerchandiseService.create_pending_order_for_transaction(tx)
        MerchandiseService.fulfill_order(
            order=order,
            lines_payload=[{
                'item_id': self.item.id,
                'quantity': 2,
                'color': 'Red',
                'size': 'Large',
            }],
            user=self.admin,
        )
        rows = MerchandiseService.get_daily_report_rows(today())
        self.assertEqual(len(rows), 1)
