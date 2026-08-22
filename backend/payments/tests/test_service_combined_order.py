from decimal import Decimal
from django.test import TransactionTestCase
from django.core.exceptions import ValidationError
from payments.services.combined_order_service import CombinedOrderService
from payments.models import (
    CombinedOrder, CombinedOrderLineItem, Transaction, InventoryMovement,
)
from .test_helpers import (
    make_admin, make_gateway, make_transaction, make_product,
    make_issuer, make_location, make_combined_order, make_line_item,
)


class CombinedOrderServiceTest(TransactionTestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.product_a = make_product(
            prod_code='CO-A', prod_name='Product A',
            price=Decimal('500.00'), quantity=100, pv=Decimal('10.00'),
        )
        self.product_b = make_product(
            prod_code='CO-B', prod_name='Product B',
            price=Decimal('300.00'), quantity=50, pv=Decimal('5.00'),
        )
        self.product_c = make_product(
            prod_code='CO-C', prod_name='Product C',
            price=Decimal('200.00'), quantity=30, pv=Decimal('3.00'),
        )
        self.admin = make_admin()
        self.issuer = make_issuer()
        self.location = make_location()

    def _make_tx(self, tx_id='CO-TX', amount=Decimal('1000.00'), status='NOT_PROCESSED', **kw):
        return make_transaction(tx_id=tx_id, amount=amount, status=status, **kw)

    def _make_order(self, transactions=None):
        return make_combined_order(
            transactions=transactions or [
                self._make_tx(tx_id='CO-BASE1'),
                self._make_tx(tx_id='CO-BASE2', amount=Decimal('500.00'), unique_hash='hash_cob2'),
            ],
            created_by=self.admin,
            location=self.location,
        )

    # --- create_combined_order ---
    def test_create_combined_order_success(self):
        tx1 = self._make_tx(tx_id='CO-CR-1')
        tx2 = self._make_tx(tx_id='CO-CR-2', amount=Decimal('500.00'), unique_hash='hash_cocr2')
        order = self._make_order([tx1, tx2])
        self.assertEqual(order.status, 'PENDING')
        self.assertEqual(order.total_amount, Decimal('1500.00'))
        self.assertEqual(order.transaction_count, 2)

    def test_create_with_three_transactions(self):
        tx1 = self._make_tx(tx_id='CO-CR3-1')
        tx2 = self._make_tx(tx_id='CO-CR3-2', amount=Decimal('500.00'), unique_hash='hash_cocr3b')
        tx3 = self._make_tx(tx_id='CO-CR3-3', amount=Decimal('300.00'), unique_hash='hash_cocr3c')
        order = self._make_order([tx1, tx2, tx3])
        self.assertEqual(order.transaction_count, 3)
        self.assertEqual(order.total_amount, Decimal('1800.00'))

    def test_create_with_single_transaction_raises(self):
        tx = self._make_tx(tx_id='CO-SINGLE')
        with self.assertRaises(ValidationError):
            CombinedOrderService.create_combined_order(
                transaction_ids=[tx.id],
                created_by=self.admin.username,
                created_by_user=self.admin,
                location=self.location,
            )

    def test_create_rejects_empty_list(self):
        with self.assertRaises(ValidationError):
            CombinedOrderService.create_combined_order(
                transaction_ids=[],
                created_by=self.admin.username,
                created_by_user=self.admin,
                location=self.location,
            )

    def test_create_rejects_duplicate_transactions(self):
        tx = self._make_tx(tx_id='CO-DUP')
        with self.assertRaises(ValidationError):
            CombinedOrderService.create_combined_order(
                transaction_ids=[tx.id, tx.id],
                created_by=self.admin.username,
                created_by_user=self.admin,
                location=self.location,
            )

    def test_create_with_partially_fulfilled_children(self):
        tx1 = self._make_tx(tx_id='CO-PF1')
        tx2 = self._make_tx(tx_id='CO-PF2', amount=Decimal('800.00'), unique_hash='hash_copf2')
        tx2.status = 'PARTIALLY_FULFILLED'
        tx2.amount_fulfilled = Decimal('300.00')
        tx2.save(skip_validation=True)
        li = make_line_item(tx2, self.product_a, quantity=1, scanned_by_user=self.issuer)
        li.is_inventory_deducted = True
        li.save()
        order = self._make_order([tx1, tx2])
        self.assertEqual(order.status, 'PARTIALLY_FULFILLED')
        self.assertEqual(order.amount_fulfilled, Decimal('300.00'))
        self.assertEqual(order.line_items.count(), 1)

    # --- activate_combined_order ---
    def test_activate_combined_order(self):
        order = self._make_order()
        result = CombinedOrderService.activate_combined_order(
            combined_order_id=order.combined_order_id,
            activated_by=str(self.admin.username),
        )
        self.assertEqual(result.status, 'IN_PROGRESS')
        order.refresh_from_db()
        self.assertEqual(order.status, 'IN_PROGRESS')

    # --- scan_product_to_combined_order_staged ---
    def test_scan_staged_product(self):
        order = self._make_order()
        CombinedOrderService.activate_combined_order(
            combined_order_id=order.combined_order_id,
            activated_by=str(self.admin.username),
        )
        result = CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=order.combined_order_id,
            product_id=self.product_a.id,
            quantity=2,
            scanned_by=str(self.issuer),
        )
        self.assertIsNotNone(result)
        self.assertEqual(order.line_items.count(), 1)

    def test_scan_staged_rejects_exceeding_budget(self):
        order = self._make_order()
        CombinedOrderService.activate_combined_order(
            combined_order_id=order.combined_order_id,
            activated_by=str(self.admin.username),
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=order.combined_order_id,
            product_id=self.product_a.id, quantity=2,
            scanned_by=str(self.issuer),
        )
        with self.assertRaises(ValidationError):
            CombinedOrderService.scan_product_to_combined_order_staged(
                combined_order_id=order.combined_order_id,
                product_id=self.product_c.id, quantity=10,
                scanned_by=str(self.issuer),
            )

    def test_scan_staged_insufficient_stock(self):
        self.product_a.quantity = 1
        self.product_a.save()
        order = self._make_order()
        CombinedOrderService.activate_combined_order(
            combined_order_id=order.combined_order_id,
            activated_by=str(self.admin.username),
        )
        # Stock is not checked during scan, only during completion
        CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=order.combined_order_id,
            product_id=self.product_a.id, quantity=5,
            scanned_by=str(self.issuer),
        )
        self.assertEqual(order.line_items.count(), 1)

    # --- remove_combined_order_line_item ---
    def test_remove_line_item(self):
        order = self._make_order()
        CombinedOrderService.activate_combined_order(
            combined_order_id=order.combined_order_id,
            activated_by=str(self.admin.username),
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=order.combined_order_id,
            product_id=self.product_a.id, quantity=2,
            scanned_by=str(self.issuer),
        )
        li = order.line_items.filter(copied_from_transaction__isnull=True).first()
        CombinedOrderService.remove_combined_order_line_item(
            combined_order_id=order.combined_order_id,
            line_item_id=li.id,
        )
        self.assertEqual(order.line_items.filter(copied_from_transaction__isnull=True).count(), 0)

    # --- complete_combined_order ---
    def test_complete_combined_order_deducts_inventory(self):
        order = self._make_order()
        CombinedOrderService.activate_combined_order(
            combined_order_id=order.combined_order_id,
            activated_by=str(self.admin.username),
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=order.combined_order_id,
            product_id=self.product_a.id, quantity=2,
            scanned_by=str(self.issuer),
        )
        result = CombinedOrderService.complete_combined_order(
            combined_order_id=order.combined_order_id,
            completed_by=str(self.admin.username),
        )
        self.assertEqual(result.status, 'PARTIALLY_FULFILLED')
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.quantity, 98)
        order.refresh_from_db()
        self.assertEqual(order.status, 'PARTIALLY_FULFILLED')
        mov = InventoryMovement.objects.filter(product=self.product_a, movement_type='SALE').first()
        self.assertIsNotNone(mov)

    def test_complete_combined_order_updates_child_statuses(self):
        tx1 = self._make_tx(tx_id='CO-COMP1')
        tx2 = self._make_tx(tx_id='CO-COMP2', amount=Decimal('500.00'), unique_hash='hash_cocomp2')
        order = self._make_order([tx1, tx2])
        CombinedOrderService.activate_combined_order(
            combined_order_id=order.combined_order_id,
            activated_by=str(self.admin.username),
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=order.combined_order_id,
            product_id=self.product_a.id, quantity=2,
            scanned_by=str(self.issuer),
        )
        CombinedOrderService.complete_combined_order(
            combined_order_id=order.combined_order_id,
            completed_by=str(self.admin.username),
        )
        tx1.refresh_from_db()
        tx2.refresh_from_db()
        self.assertEqual(tx1.status, 'COMBINED_FULFILLED')
        self.assertEqual(tx2.status, 'COMBINED_FULFILLED')

    def test_complete_without_scanning_fails(self):
        order = self._make_order()
        CombinedOrderService.activate_combined_order(
            combined_order_id=order.combined_order_id,
            activated_by=str(self.admin.username),
        )
        with self.assertRaises(ValidationError):
            CombinedOrderService.complete_combined_order(
                combined_order_id=order.combined_order_id,
                completed_by=str(self.admin.username),
            )

    # --- cancel_combined_order ---
    def test_cancel_combined_order_restores_children(self):
        tx1 = self._make_tx(tx_id='CO-CAN1')
        tx2 = self._make_tx(tx_id='CO-CAN2', amount=Decimal('500.00'), unique_hash='hash_cocan2')
        order = self._make_order([tx1, tx2])
        CombinedOrderService.activate_combined_order(
            combined_order_id=order.combined_order_id,
            activated_by=str(self.admin.username),
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=order.combined_order_id,
            product_id=self.product_a.id, quantity=2,
            scanned_by=str(self.issuer),
        )
        CombinedOrderService.cancel_combined_order(
            combined_order_id=order.combined_order_id,
            cancelled_by=self.admin,
        )
        tx1.refresh_from_db()
        tx2.refresh_from_db()
        self.assertEqual(tx1.status, 'NOT_PROCESSED')
        self.assertEqual(tx2.status, 'NOT_PROCESSED')

    def test_cancel_combined_order_returns_inventory(self):
        order = self._make_order()
        CombinedOrderService.activate_combined_order(
            combined_order_id=order.combined_order_id,
            activated_by=str(self.admin.username),
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=order.combined_order_id,
            product_id=self.product_a.id, quantity=2,
            scanned_by=str(self.issuer),
        )
        CombinedOrderService.complete_combined_order(
            combined_order_id=order.combined_order_id,
            completed_by=str(self.admin.username),
        )
        orig_qty = self.product_a.quantity + 2
        self.product_a.quantity = orig_qty
        self.product_a.save()
        CombinedOrderService.cancel_combined_order(
            combined_order_id=order.combined_order_id,
            cancelled_by=self.admin,
        )
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.quantity, orig_qty + 2)

    # --- cancel_combined_order_issuance ---
    def test_cancel_issuance_removes_staged_items(self):
        order = self._make_order()
        CombinedOrderService.activate_combined_order(
            combined_order_id=order.combined_order_id,
            activated_by=str(self.admin.username),
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=order.combined_order_id,
            product_id=self.product_a.id, quantity=2,
            scanned_by=str(self.issuer),
        )
        result = CombinedOrderService.cancel_combined_order_issuance(
            combined_order_id=order.combined_order_id,
            cancelled_by=str(self.admin.username),
        )
        self.assertTrue(result['success'])
        order.refresh_from_db()
        self.assertEqual(order.status, 'PENDING')
        self.assertEqual(order.line_items.filter(copied_from_transaction__isnull=True).count(), 0)

    # --- revert_combined_order ---
    def test_revert_combined_order_full_undo(self):
        tx1 = self._make_tx(tx_id='CO-REV1')
        tx2 = self._make_tx(tx_id='CO-REV2', amount=Decimal('500.00'), unique_hash='hash_corev2')
        order = self._make_order([tx1, tx2])
        CombinedOrderService.activate_combined_order(
            combined_order_id=order.combined_order_id,
            activated_by=str(self.admin.username),
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=order.combined_order_id,
            product_id=self.product_a.id, quantity=2,
            scanned_by=str(self.issuer),
        )
        CombinedOrderService.complete_combined_order(
            combined_order_id=order.combined_order_id,
            completed_by=str(self.admin.username),
        )
        result = CombinedOrderService.revert_combined_order(
            combined_order_id=order.combined_order_id,
            reverted_by=self.admin,
        )
        self.assertTrue(result['success'])
        tx1.refresh_from_db()
        tx2.refresh_from_db()
        self.assertEqual(tx1.status, 'NOT_PROCESSED')
        self.assertEqual(tx2.status, 'NOT_PROCESSED')
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.quantity, 100)

    # --- get_combined_order_details ---
    def test_get_combined_order_details(self):
        order = self._make_order()
        details = CombinedOrderService.get_combined_order_details(order.combined_order_id)
        self.assertEqual(details['combined_order_id'], order.combined_order_id)
        self.assertIn('transactions', details)
        self.assertIn('line_items', details)

    # --- recalculate_amount_fulfilled ---
    def test_recalculate_amount_fulfilled(self):
        order = self._make_order()
        result = CombinedOrderService.recalculate_amount_fulfilled(order)
        self.assertEqual(result, Decimal('0.00'))
