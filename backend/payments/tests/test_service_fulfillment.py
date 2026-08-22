from decimal import Decimal
from django.test import TransactionTestCase
from django.core.exceptions import ValidationError
from payments.services.fulfillment_service import FulfillmentService
from payments.models import Transaction, InventoryMovement
from .test_helpers import (
    make_admin, make_processor, make_issuer, make_gateway,
    make_product, make_transaction, make_location, make_registration_kit_product,
)


class FulfillmentServiceTest(TransactionTestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.product_a = make_product(
            prod_code='FUL-A', prod_name='Product A',
            price=Decimal('500.00'), quantity=100, pv=Decimal('10.00'),
            cost_price=Decimal('500.00'),
        )
        self.product_b = make_product(
            prod_code='FUL-B', prod_name='Product B',
            price=Decimal('300.00'), quantity=50, pv=Decimal('5.00'),
            cost_price=Decimal('300.00'),
        )
        self.tx = make_transaction(tx_id='FUL-TX-001', amount=Decimal('2000.00'))
        self.issuer = make_issuer()
        self.processor = make_processor()
        self.location = make_location()

    def test_activate_issuance_success(self):
        result = FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.issuer,
            location=self.location,
        )
        self.assertTrue(result['success'])
        self.tx.refresh_from_db()
        self.assertTrue(self.tx.is_in_issuance)

    def test_activate_issuance_rejects_duplicate_at_same_location(self):
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.issuer,
            location=self.location,
        )
        tx2 = make_transaction(tx_id='FUL-TX-002', amount=Decimal('1500.00'), unique_hash='hash_ful2')
        with self.assertRaises(ValidationError):
            FulfillmentService.activate_issuance(
                transaction_id=tx2.id,
                activated_by_user=self.issuer,
                location=self.location,
            )

    def test_activate_issuance_rejects_locked_transaction(self):
        self.tx.status = 'FULFILLED'
        self.tx.save(skip_validation=True)
        with self.assertRaises(ValidationError):
            FulfillmentService.activate_issuance(
                transaction_id=self.tx.id,
                activated_by_user=self.issuer,
                location=self.location,
            )

    def test_scan_barcode_adds_line_item(self):
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.issuer,
            location=self.location,
        )
        result = FulfillmentService.scan_barcode(
            transaction_id=self.tx.id,
            barcode_data={'sku': self.product_a.prod_code, 'quantity': 2},
            scanned_by_user=self.issuer,
        )
        self.assertTrue(result['success'])
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.line_items.count(), 1)
        item = self.tx.line_items.first()
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.line_total, Decimal('1000.00'))

    def test_scan_barcode_rejects_without_issuance(self):
        with self.assertRaises(ValidationError):
            FulfillmentService.scan_barcode(
                transaction_id=self.tx.id,
                barcode_data={'sku': self.product_a.prod_code, 'quantity': 1},
                scanned_by_user=self.issuer,
            )

    def test_scan_barcode_rejects_insufficient_stock(self):
        self.product_a.quantity = 1
        self.product_a.save()
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.issuer,
            location=self.location,
        )
        with self.assertRaises(ValidationError):
            FulfillmentService.scan_barcode(
                transaction_id=self.tx.id,
                barcode_data={'sku': self.product_a.prod_code, 'quantity': 10},
                scanned_by_user=self.issuer,
            )

    def test_scan_barcode_rejects_exceeding_amount(self):
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.issuer,
            location=self.location,
        )
        with self.assertRaises(ValidationError):
            FulfillmentService.scan_barcode(
                transaction_id=self.tx.id,
                barcode_data={'sku': self.product_a.prod_code, 'quantity': 100},
                scanned_by_user=self.issuer,
            )

    def test_scan_barcode_rejects_nonexistent_product(self):
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.issuer,
            location=self.location,
        )
        with self.assertRaises(ValidationError):
            FulfillmentService.scan_barcode(
                transaction_id=self.tx.id,
                barcode_data={'sku': 'NONEXISTENT', 'quantity': 1},
                scanned_by_user=self.issuer,
            )

    def test_scan_multiple_products_tracks_budget(self):
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.issuer,
            location=self.location,
        )
        FulfillmentService.scan_barcode(
            transaction_id=self.tx.id,
            barcode_data={'sku': self.product_a.prod_code, 'quantity': 2},
            scanned_by_user=self.issuer,
        )
        FulfillmentService.scan_barcode(
            transaction_id=self.tx.id,
            barcode_data={'sku': self.product_b.prod_code, 'quantity': 2},
            scanned_by_user=self.issuer,
        )
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.line_items.count(), 2)
        self.assertEqual(self.tx.amount_fulfilled, Decimal('1600.00'))

    def test_complete_issuance_deducts_inventory(self):
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.issuer,
            location=self.location,
        )
        FulfillmentService.scan_barcode(
            transaction_id=self.tx.id,
            barcode_data={'sku': self.product_a.prod_code, 'quantity': 2},
            scanned_by_user=self.issuer,
        )
        result = FulfillmentService.complete_issuance(
            transaction_id=self.tx.id,
            completed_by_user=self.issuer,
        )
        self.assertTrue(result['success'])
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.quantity, 98)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'PARTIALLY_FULFILLED')
        self.assertFalse(self.tx.is_in_issuance)
        mov = InventoryMovement.objects.filter(product=self.product_a, movement_type='SALE').first()
        self.assertIsNotNone(mov)
        self.assertEqual(mov.quantity_change, -2)

    def test_complete_issuance_without_items_fails(self):
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.issuer,
            location=self.location,
        )
        with self.assertRaises(ValidationError):
            FulfillmentService.complete_issuance(
                transaction_id=self.tx.id,
                completed_by_user=self.issuer,
            )

    def test_complete_issuance_not_in_issuance_fails(self):
        with self.assertRaises(ValidationError):
            FulfillmentService.complete_issuance(
                transaction_id=self.tx.id,
                completed_by_user=self.issuer,
            )

    def test_cancel_issuance_removes_items_no_inventory_change(self):
        orig_qty = self.product_a.quantity
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.issuer,
            location=self.location,
        )
        FulfillmentService.scan_barcode(
            transaction_id=self.tx.id,
            barcode_data={'sku': self.product_a.prod_code, 'quantity': 2},
            scanned_by_user=self.issuer,
        )
        result = FulfillmentService.cancel_issuance(
            transaction_id=self.tx.id,
            reason='Test cancel',
        )
        self.assertTrue(result['success'])
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.line_items.count(), 0)
        self.assertEqual(self.tx.amount_fulfilled, Decimal('0.00'))
        self.assertFalse(self.tx.is_in_issuance)
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.quantity, orig_qty)

    def test_get_current_issuance_returns_active(self):
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.issuer,
            location=self.location,
        )
        current = FulfillmentService.get_current_issuance(location=self.location)
        self.assertIsNotNone(current)
        self.assertEqual(current['tx_id'], self.tx.tx_id)

    def test_get_current_issuance_returns_none_when_inactive(self):
        current = FulfillmentService.get_current_issuance(location=self.location)
        self.assertIsNone(current)

    def test_full_fulfillment_sets_status_to_fulfilled(self):
        self.tx.amount = Decimal('1000.00')
        self.tx.save()
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.issuer,
            location=self.location,
        )
        FulfillmentService.scan_barcode(
            transaction_id=self.tx.id,
            barcode_data={'sku': self.product_a.prod_code, 'quantity': 2},
            scanned_by_user=self.issuer,
        )
        FulfillmentService.complete_issuance(
            transaction_id=self.tx.id,
            completed_by_user=self.issuer,
        )
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'FULFILLED')

    def test_amount_fulfilled_does_not_exceed_amount(self):
        self.tx.amount = Decimal('1000.00')
        self.tx.save()
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.issuer,
            location=self.location,
        )
        with self.assertRaises(ValidationError):
            FulfillmentService.scan_barcode(
                transaction_id=self.tx.id,
                barcode_data={'sku': self.product_a.prod_code, 'quantity': 3},
                scanned_by_user=self.issuer,
            )


class MultiLocationIssuanceTest(TransactionTestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.product_a = make_product(prod_code='MLOC-A', price=Decimal('500.00'), quantity=100, cost_price=Decimal('500.00'))
        self.admin = make_admin()
        self.main_loc = make_location(name='Main Shop', location_type='MAIN')
        self.field_loc = make_location(name='Field Office', location_type='FIELD')
        self.tx1 = make_transaction(tx_id='MLOC-TX1', amount=Decimal('1000.00'), location=self.main_loc)
        self.tx2 = make_transaction(tx_id='MLOC-TX2', amount=Decimal('1000.00'), unique_hash='hash_mloc2', location=self.field_loc)
        self.issuer = make_issuer()

    def test_different_locations_dont_block_each_other(self):
        FulfillmentService.activate_issuance(
            transaction_id=self.tx1.id,
            activated_by_user=self.issuer,
            location=self.main_loc,
        )
        FulfillmentService.activate_issuance(
            transaction_id=self.tx2.id,
            activated_by_user=self.issuer,
            location=self.field_loc,
        )
        self.tx1.refresh_from_db()
        self.tx2.refresh_from_db()
        self.assertTrue(self.tx1.is_in_issuance)
        self.assertTrue(self.tx2.is_in_issuance)

    def test_same_location_blocks_second_issuance(self):
        FulfillmentService.activate_issuance(
            transaction_id=self.tx1.id,
            activated_by_user=self.issuer,
            location=self.main_loc,
        )
        tx3 = make_transaction(tx_id='MLOC-TX3', amount=Decimal('500.00'), unique_hash='hash_mloc3', location=self.main_loc)
        with self.assertRaises(ValidationError):
            FulfillmentService.activate_issuance(
                transaction_id=tx3.id,
                activated_by_user=self.issuer,
                location=self.main_loc,
            )
