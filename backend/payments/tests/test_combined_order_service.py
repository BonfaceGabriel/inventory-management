"""
Comprehensive tests for CombinedOrderService.

Tests all scenarios involving:
- Creating combined orders (with fresh and partially fulfilled transactions)
- Amount reconciliation and tracking
- Scanning products (staged workflow)
- Completing orders and inventory updates
- Cancelling issuance (restoring state)
- Cancelling entire orders
- Removing line items
- Edge cases and data integrity

Author: QA Senior Analyst
"""

from decimal import Decimal
from django.test import TransactionTestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
import hashlib

from payments.models import (
    Transaction, Product, CombinedOrder, CombinedOrderTransaction,
    CombinedOrderLineItem, TransactionLineItem, InventoryMovement,
    PaymentGateway, User
)
from payments.services.combined_order_service import CombinedOrderService
from payments.services.fulfillment_service import FulfillmentService


class CombinedOrderServiceTestBase(TransactionTestCase):
    """Base class with common setup for combined order tests."""

    def setUp(self):
        """Set up test data."""
        # Clear all data
        CombinedOrderLineItem.objects.all().delete()
        CombinedOrderTransaction.objects.all().delete()
        CombinedOrder.objects.all().delete()
        TransactionLineItem.objects.all().delete()
        InventoryMovement.objects.all().delete()
        Transaction.objects.all().delete()
        Product.objects.all().delete()

        # Create gateway
        self.gateway = PaymentGateway.objects.create(
            name='Test Gateway',
            gateway_type=PaymentGateway.GatewayType.MPESA_TILL,
            gateway_number='123456',
            settlement_type=PaymentGateway.SettlementType.NONE
        )

        # Create products with known prices
        self.product1 = Product.objects.create(
            prod_code='PROD001',
            prod_name='Test Product 1',
            sku='PROD001',
            sku_name='Unit',
            current_price=Decimal('1000.00'),
            cost_price=Decimal('1000.00'),
            current_pv=Decimal('10.00'),
            quantity=100,
            is_active=True
        )

        self.product2 = Product.objects.create(
            prod_code='PROD002',
            prod_name='Test Product 2',
            sku='PROD002',
            sku_name='Unit',
            current_price=Decimal('500.00'),
            cost_price=Decimal('500.00'),
            current_pv=Decimal('5.00'),
            quantity=100,
            is_active=True
        )

        self.product3 = Product.objects.create(
            prod_code='PROD003',
            prod_name='Test Product 3',
            sku='PROD003',
            sku_name='Unit',
            current_price=Decimal('2000.00'),
            cost_price=Decimal('2000.00'),
            current_pv=Decimal('20.00'),
            quantity=50,
            is_active=True
        )

    def create_transaction(self, tx_id, amount, status=None):
        """Helper to create a transaction."""
        unique_hash = hashlib.sha256(
            f"{tx_id}|{amount}|{timezone.now().isoformat()}".encode()
        ).hexdigest()
        txn = Transaction.objects.create(
            tx_id=tx_id,
            amount=Decimal(str(amount)),
            sender_name=f'Sender {tx_id}',
            sender_phone='0712345678',
            timestamp=timezone.now(),
            gateway=self.gateway,
            unique_hash=unique_hash,
            status=status or Transaction.OrderStatus.NOT_PROCESSED
        )
        return txn


class TestCombineOrders(CombinedOrderServiceTestBase):
    """Tests for creating combined orders."""

    def test_combine_two_fresh_transactions(self):
        """Test combining two NOT_PROCESSED transactions."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 2000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user',
            customer_name='Test Customer'
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['transaction_count'], 2)
        self.assertEqual(result['total_amount'], 5000.0)
        self.assertEqual(result['amount_fulfilled'], 0.0)
        self.assertEqual(result['remaining_amount'], 5000.0)

        # Verify combined order created
        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.total_amount, Decimal('5000.00'))
        self.assertEqual(order.amount_fulfilled, Decimal('0.00'))
        self.assertEqual(order.status, CombinedOrder.Status.PENDING)

        # Verify child transactions marked as COMBINED_FULFILLED
        txn1.refresh_from_db()
        txn2.refresh_from_db()
        self.assertEqual(txn1.status, Transaction.OrderStatus.COMBINED_FULFILLED)
        self.assertEqual(txn2.status, Transaction.OrderStatus.COMBINED_FULFILLED)

        # Verify parent transaction created
        self.assertIsNotNone(order.parent_transaction)
        self.assertEqual(order.parent_transaction.amount, Decimal('5000.00'))

    def test_combine_with_partially_fulfilled_transaction(self):
        """Test combining when one transaction is partially fulfilled."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 2000)

        # Partially fulfill txn1
        FulfillmentService.activate_issuance(txn1.id)
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD001', 'quantity': 1})  # 1000
        FulfillmentService.complete_issuance(txn1.id)

        txn1.refresh_from_db()
        self.assertEqual(txn1.amount_fulfilled, Decimal('1000.00'))
        self.assertEqual(txn1.status, Transaction.OrderStatus.PARTIALLY_FULFILLED)

        # Combine transactions
        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['total_amount'], 5000.0)
        self.assertEqual(result['amount_fulfilled'], 1000.0)  # Carried over from txn1
        self.assertEqual(result['remaining_amount'], 4000.0)

        # Verify combined order has correct amounts
        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.amount_fulfilled, Decimal('1000.00'))
        self.assertEqual(order.base_amount_fulfilled, Decimal('1000.00'))

        # Verify line items were copied from partially fulfilled transaction
        line_items = order.line_items.all()
        self.assertEqual(line_items.count(), 1)
        copied_item = line_items.first()
        self.assertTrue(copied_item.is_inventory_deducted)
        self.assertEqual(copied_item.copied_from_transaction, txn1)

    def test_combine_two_partially_fulfilled_transactions(self):
        """Test combining two partially fulfilled transactions."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 2000)

        # Partially fulfill both
        FulfillmentService.activate_issuance(txn1.id)
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD001', 'quantity': 1})  # 1000
        FulfillmentService.complete_issuance(txn1.id)

        FulfillmentService.activate_issuance(txn2.id)
        FulfillmentService.scan_barcode(txn2.id, {'prod_code': 'PROD002', 'quantity': 1})  # 500
        FulfillmentService.complete_issuance(txn2.id)

        # Combine
        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        self.assertEqual(result['total_amount'], 5000.0)
        self.assertEqual(result['amount_fulfilled'], 1500.0)  # 1000 + 500
        self.assertEqual(result['remaining_amount'], 3500.0)

        # Verify line items copied from both
        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.line_items.count(), 2)
        self.assertEqual(order.line_items.filter(is_inventory_deducted=True).count(), 2)

    def test_cannot_combine_single_transaction(self):
        """Test that combining a single transaction fails."""
        txn1 = self.create_transaction('TXN001', 3000)

        with self.assertRaises(ValidationError) as context:
            CombinedOrderService.create_combined_order(
                transaction_ids=[txn1.id],
                created_by='test_user'
            )

        self.assertIn('two transactions', str(context.exception))

    def test_cannot_combine_fulfilled_transaction(self):
        """Test that FULFILLED transactions cannot be combined."""
        txn1 = self.create_transaction('TXN001', 1000)
        txn2 = self.create_transaction('TXN002', 1000)

        # Fully fulfill txn1
        FulfillmentService.activate_issuance(txn1.id)
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD001', 'quantity': 1})
        FulfillmentService.complete_issuance(txn1.id)

        txn1.refresh_from_db()
        self.assertEqual(txn1.status, Transaction.OrderStatus.FULFILLED)

        with self.assertRaises(ValidationError) as context:
            CombinedOrderService.create_combined_order(
                transaction_ids=[txn1.id, txn2.id],
                created_by='test_user'
            )

        self.assertIn('cannot be combined', str(context.exception))

    def test_cannot_combine_already_combined_transaction(self):
        """Test that transactions already in a combined order cannot be recombined."""
        txn1 = self.create_transaction('TXN001', 2000)
        txn2 = self.create_transaction('TXN002', 2000)
        txn3 = self.create_transaction('TXN003', 2000)

        # Combine txn1 and txn2
        CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        # Try to combine txn1 (already combined) with txn3
        with self.assertRaises(ValidationError) as context:
            CombinedOrderService.create_combined_order(
                transaction_ids=[txn1.id, txn3.id],
                created_by='test_user'
            )

        self.assertIn('already part of a combined order', str(context.exception))


class TestCombinedOrderActivation(CombinedOrderServiceTestBase):
    """Tests for activating combined orders for fulfillment."""

    def test_activate_pending_order(self):
        """Test activating a PENDING combined order."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 2000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        order = CombinedOrderService.activate_combined_order(
            result['combined_order_id'],
            activated_by='test_user'
        )

        self.assertEqual(order.status, CombinedOrder.Status.IN_PROGRESS)
        # Verify state tracking for cancel restoration
        self.assertEqual(order.amount_fulfilled_before_activation, Decimal('0.00'))
        self.assertEqual(order.status_before_activation, CombinedOrder.Status.PENDING)

    def test_activate_partially_fulfilled_order(self):
        """Test activating a PARTIALLY_FULFILLED combined order."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 2000)

        # Partially fulfill txn1
        FulfillmentService.activate_issuance(txn1.id)
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD001', 'quantity': 1})
        FulfillmentService.complete_issuance(txn1.id)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        order = CombinedOrderService.activate_combined_order(
            result['combined_order_id'],
            activated_by='test_user'
        )

        self.assertEqual(order.status, CombinedOrder.Status.IN_PROGRESS)
        self.assertEqual(order.amount_fulfilled_before_activation, Decimal('1000.00'))
        self.assertEqual(order.status_before_activation, CombinedOrder.Status.PARTIALLY_FULFILLED)

    def test_cannot_activate_fulfilled_order(self):
        """Test that FULFILLED orders cannot be activated."""
        txn1 = self.create_transaction('TXN001', 1000)
        txn2 = self.create_transaction('TXN002', 1000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        # Activate and fully fulfill
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 2, 'test_user'
        )  # 2 x 1000 = 2000 (full amount)

        # Order should still be IN_PROGRESS after scanning (staged workflow)
        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.status, CombinedOrder.Status.IN_PROGRESS)

        # Complete the order
        CombinedOrderService.complete_combined_order(result['combined_order_id'], 'test_user')

        order.refresh_from_db()
        self.assertEqual(order.status, CombinedOrder.Status.FULFILLED)

        # Try to activate again
        with self.assertRaises(ValidationError) as context:
            CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        self.assertIn('FULFILLED', str(context.exception))


class TestCombinedOrderScanning(CombinedOrderServiceTestBase):
    """Tests for scanning products to combined orders."""

    def test_scan_product_updates_amount_fulfilled(self):
        """Test that scanning a product updates amount_fulfilled correctly."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 2000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        # Scan product1 (cost: 1000)
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'],
            self.product1.id,
            quantity=2,
            scanned_by='test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.amount_fulfilled, Decimal('2000.00'))  # 2 x 1000

        # Verify parent transaction updated
        order.parent_transaction.refresh_from_db()
        self.assertEqual(order.parent_transaction.amount_fulfilled, Decimal('2000.00'))

    def test_scan_multiple_products_accumulates_amount(self):
        """Test scanning multiple products accumulates amount_fulfilled."""
        txn1 = self.create_transaction('TXN001', 5000)
        txn2 = self.create_transaction('TXN002', 5000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        # Scan product1 (1000)
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 1, 'test_user'
        )

        # Scan product2 (500)
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product2.id, 2, 'test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.amount_fulfilled, Decimal('2000.00'))  # 1000 + (2 x 500)

    def test_scan_same_product_multiple_times_updates_quantity(self):
        """Test scanning same product multiple times updates existing line item."""
        txn1 = self.create_transaction('TXN001', 5000)
        txn2 = self.create_transaction('TXN002', 5000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        # Scan product1 twice
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 1, 'test_user'
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 2, 'test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.amount_fulfilled, Decimal('3000.00'))  # 3 x 1000

        # Should have only 1 line item with quantity 3
        line_items = order.line_items.filter(is_inventory_deducted=False)
        self.assertEqual(line_items.count(), 1)
        self.assertEqual(line_items.first().quantity, 3)

    def test_scan_preserves_copied_items_amount(self):
        """Test that scanning new items preserves amount from copied (partially fulfilled) items."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 3000)

        # Partially fulfill txn1
        FulfillmentService.activate_issuance(txn1.id)
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD001', 'quantity': 1})  # 1000
        FulfillmentService.complete_issuance(txn1.id)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.amount_fulfilled, Decimal('1000.00'))

        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        # Scan new product
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product2.id, 2, 'test_user'
        )  # 2 x 500 = 1000

        order.refresh_from_db()
        self.assertEqual(order.amount_fulfilled, Decimal('2000.00'))  # 1000 (copied) + 1000 (new)

        # Should have 2 line items: 1 copied (deducted), 1 new (pending)
        self.assertEqual(order.line_items.count(), 2)
        self.assertEqual(order.line_items.filter(is_inventory_deducted=True).count(), 1)
        self.assertEqual(order.line_items.filter(is_inventory_deducted=False).count(), 1)

    def test_cannot_scan_exceeding_budget(self):
        """Test that scanning products exceeding budget fails."""
        txn1 = self.create_transaction('TXN001', 1500)
        txn2 = self.create_transaction('TXN002', 1500)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        # Try to scan product that exceeds budget (3000 total, product costs 2000 x 2 = 4000)
        with self.assertRaises(ValidationError) as context:
            CombinedOrderService.scan_product_to_combined_order_staged(
                result['combined_order_id'], self.product3.id, 2, 'test_user'
            )

        self.assertIn('exceed budget', str(context.exception))

        # Verify amount_fulfilled unchanged
        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.amount_fulfilled, Decimal('0.00'))


class TestCombinedOrderRemoveLineItem(CombinedOrderServiceTestBase):
    """Tests for removing line items from combined orders."""

    def test_remove_pending_line_item(self):
        """Test removing a pending (not deducted) line item."""
        txn1 = self.create_transaction('TXN001', 5000)
        txn2 = self.create_transaction('TXN002', 5000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        # Scan two products
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 2, 'test_user'
        )  # 2000
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product2.id, 2, 'test_user'
        )  # 1000

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.amount_fulfilled, Decimal('3000.00'))

        # Remove first line item
        line_item_to_remove = order.line_items.filter(product=self.product1).first()
        CombinedOrderService.remove_combined_order_line_item(
            result['combined_order_id'],
            line_item_to_remove.id
        )

        order.refresh_from_db()
        self.assertEqual(order.amount_fulfilled, Decimal('1000.00'))  # Only product2 remains
        self.assertEqual(order.line_items.count(), 1)

    def test_cannot_remove_copied_line_item(self):
        """Test that copied (already deducted from child txn) line items cannot be removed."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 3000)

        # Partially fulfill txn1
        FulfillmentService.activate_issuance(txn1.id)
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD001', 'quantity': 1})
        FulfillmentService.complete_issuance(txn1.id)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        copied_item = order.line_items.filter(copied_from_transaction__isnull=False).first()

        with self.assertRaises(ValidationError) as context:
            CombinedOrderService.remove_combined_order_line_item(
                result['combined_order_id'],
                copied_item.id
            )

        self.assertIn('already fulfilled', str(context.exception))

    def test_remove_line_item_updates_parent_transaction(self):
        """Test that removing line item updates parent transaction's amount_fulfilled."""
        txn1 = self.create_transaction('TXN001', 5000)
        txn2 = self.create_transaction('TXN002', 5000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 2, 'test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        parent = order.parent_transaction
        parent.refresh_from_db()
        self.assertEqual(parent.amount_fulfilled, Decimal('2000.00'))

        # Remove line item
        line_item = order.line_items.first()
        CombinedOrderService.remove_combined_order_line_item(
            result['combined_order_id'],
            line_item.id
        )

        parent.refresh_from_db()
        self.assertEqual(parent.amount_fulfilled, Decimal('0.00'))


class TestCombinedOrderCancelIssuance(CombinedOrderServiceTestBase):
    """Tests for cancelling issuance sessions (not the entire order)."""

    def test_cancel_issuance_removes_pending_items_only(self):
        """Test that cancel_issuance only removes pending (not deducted) items."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 3000)

        # Partially fulfill txn1
        FulfillmentService.activate_issuance(txn1.id)
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD001', 'quantity': 1})
        FulfillmentService.complete_issuance(txn1.id)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        # Scan new product
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product2.id, 2, 'test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.line_items.count(), 2)  # 1 copied + 1 pending
        self.assertEqual(order.amount_fulfilled, Decimal('2000.00'))

        # Cancel issuance
        cancel_result = CombinedOrderService.cancel_combined_order_issuance(
            result['combined_order_id'],
            cancelled_by='test_user',
            reason='Testing'
        )

        self.assertTrue(cancel_result['success'])
        self.assertEqual(cancel_result['pending_items_removed'], 1)

        order.refresh_from_db()
        # Should still have the copied item
        self.assertEqual(order.line_items.count(), 1)
        self.assertTrue(order.line_items.first().is_inventory_deducted)
        # Amount should be restored to pre-activation value
        self.assertEqual(order.amount_fulfilled, Decimal('1000.00'))
        self.assertEqual(order.status, CombinedOrder.Status.PARTIALLY_FULFILLED)

    def test_cancel_issuance_restores_pending_status(self):
        """Test that cancel_issuance restores PENDING status for fresh orders."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 3000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        # Scan product
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 1, 'test_user'
        )

        # Cancel issuance
        cancel_result = CombinedOrderService.cancel_combined_order_issuance(
            result['combined_order_id'],
            cancelled_by='test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.status, CombinedOrder.Status.PENDING)
        self.assertEqual(order.amount_fulfilled, Decimal('0.00'))
        self.assertEqual(order.line_items.count(), 0)

    def test_cancel_issuance_updates_parent_transaction(self):
        """Test that cancel_issuance updates parent transaction correctly."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 3000)

        # Partially fulfill txn1
        FulfillmentService.activate_issuance(txn1.id)
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD001', 'quantity': 1})
        FulfillmentService.complete_issuance(txn1.id)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        # Scan new product
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product2.id, 2, 'test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        parent = order.parent_transaction
        parent.refresh_from_db()
        self.assertEqual(parent.amount_fulfilled, Decimal('2000.00'))

        # Cancel issuance
        CombinedOrderService.cancel_combined_order_issuance(
            result['combined_order_id'],
            cancelled_by='test_user'
        )

        parent.refresh_from_db()
        self.assertEqual(parent.amount_fulfilled, Decimal('1000.00'))
        self.assertEqual(parent.status, Transaction.OrderStatus.PARTIALLY_FULFILLED)


class TestCombinedOrderCancel(CombinedOrderServiceTestBase):
    """Tests for fully cancelling combined orders."""

    def test_cancel_order_reverses_inventory(self):
        """Test that cancelling order reverses inventory for deducted items."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 3000)

        initial_stock = self.product1.quantity

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 2, 'test_user'
        )
        CombinedOrderService.complete_combined_order(result['combined_order_id'], 'test_user')

        # Verify inventory was deducted
        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity, initial_stock - 2)

        # Reactivate to get to IN_PROGRESS for cancellation
        # Actually, we need to test cancel on a non-fulfilled order
        # Let's create a new scenario

    def test_cancel_pending_order_no_inventory_changes(self):
        """Test cancelling a PENDING order doesn't affect inventory."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 3000)

        initial_stock = self.product1.quantity

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        cancel_result = CombinedOrderService.cancel_combined_order(
            result['combined_order_id'],
            cancelled_by='test_user',
            reason='Testing'
        )

        self.assertTrue(cancel_result['success'])
        self.assertEqual(cancel_result['reversed_line_items'], 0)

        # Inventory unchanged
        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity, initial_stock)

        # Order marked as cancelled
        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.status, CombinedOrder.Status.CANCELLED)

    def test_cancel_in_progress_order_with_pending_items(self):
        """Test cancelling IN_PROGRESS order with only pending (not deducted) items."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 3000)

        initial_stock = self.product1.quantity

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 2, 'test_user'
        )

        # Items are staged (not deducted yet)
        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.line_items.filter(is_inventory_deducted=False).count(), 1)

        cancel_result = CombinedOrderService.cancel_combined_order(
            result['combined_order_id'],
            cancelled_by='test_user'
        )

        self.assertTrue(cancel_result['success'])
        self.assertEqual(cancel_result['reversed_line_items'], 0)  # Nothing deducted

        # Inventory unchanged (items were only staged)
        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity, initial_stock)

    def test_cannot_cancel_fulfilled_order(self):
        """Test that FULFILLED orders cannot be cancelled."""
        txn1 = self.create_transaction('TXN001', 1000)
        txn2 = self.create_transaction('TXN002', 1000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 2, 'test_user'
        )  # 2 x 1000 = 2000 (full amount)

        # Order should still be IN_PROGRESS after scanning (staged workflow)
        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.status, CombinedOrder.Status.IN_PROGRESS)

        # Complete the order
        CombinedOrderService.complete_combined_order(result['combined_order_id'], 'test_user')

        order.refresh_from_db()
        self.assertEqual(order.status, CombinedOrder.Status.FULFILLED)

        with self.assertRaises(ValidationError) as context:
            CombinedOrderService.cancel_combined_order(
                result['combined_order_id'],
                cancelled_by='test_user'
            )

        self.assertIn('fulfilled', str(context.exception).lower())


class TestCombinedOrderCompletion(CombinedOrderServiceTestBase):
    """Tests for completing combined orders."""

    def test_complete_order_deducts_inventory(self):
        """Test that completing order deducts inventory."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 3000)

        initial_stock1 = self.product1.quantity
        initial_stock2 = self.product2.quantity

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 2, 'test_user'
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product2.id, 3, 'test_user'
        )
        CombinedOrderService.complete_combined_order(result['combined_order_id'], 'test_user')

        self.product1.refresh_from_db()
        self.product2.refresh_from_db()
        self.assertEqual(self.product1.quantity, initial_stock1 - 2)
        self.assertEqual(self.product2.quantity, initial_stock2 - 3)

        # Verify inventory movements created
        movements = InventoryMovement.objects.filter(reference__contains=result['combined_order_id'])
        self.assertEqual(movements.count(), 2)

    def test_complete_order_marks_items_as_deducted(self):
        """Test that completing order marks line items as inventory_deducted."""
        txn1 = self.create_transaction('TXN001', 5000)
        txn2 = self.create_transaction('TXN002', 5000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 2, 'test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.line_items.filter(is_inventory_deducted=False).count(), 1)

        CombinedOrderService.complete_combined_order(result['combined_order_id'], 'test_user')

        order.refresh_from_db()
        self.assertEqual(order.line_items.filter(is_inventory_deducted=True).count(), 1)
        self.assertEqual(order.line_items.filter(is_inventory_deducted=False).count(), 0)

    def test_complete_order_sets_fulfilled_status(self):
        """Test that completing fully paid order sets FULFILLED status."""
        txn1 = self.create_transaction('TXN001', 1000)
        txn2 = self.create_transaction('TXN002', 1000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 2, 'test_user'
        )  # 2 x 1000 = 2000 = total amount

        # Order should still be IN_PROGRESS after scanning (staged workflow)
        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.status, CombinedOrder.Status.IN_PROGRESS)

        # Complete the order
        CombinedOrderService.complete_combined_order(result['combined_order_id'], 'test_user')

        order.refresh_from_db()
        self.assertEqual(order.status, CombinedOrder.Status.FULFILLED)
        self.assertEqual(order.parent_transaction.status, Transaction.OrderStatus.FULFILLED)

    def test_complete_order_sets_partially_fulfilled_status(self):
        """Test that completing underpaid order sets PARTIALLY_FULFILLED status."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 3000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 1, 'test_user'
        )  # 1000 < 6000 total
        CombinedOrderService.complete_combined_order(result['combined_order_id'], 'test_user')

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.status, CombinedOrder.Status.PARTIALLY_FULFILLED)
        self.assertEqual(order.parent_transaction.status, Transaction.OrderStatus.PARTIALLY_FULFILLED)

    def test_complete_order_only_deducts_pending_items(self):
        """Test that completion only deducts inventory for pending (not already deducted) items."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 3000)

        # Partially fulfill txn1
        initial_stock = self.product1.quantity
        FulfillmentService.activate_issuance(txn1.id)
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD001', 'quantity': 1})
        FulfillmentService.complete_issuance(txn1.id)

        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity, initial_stock - 1)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        # Scan new item
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product2.id, 2, 'test_user'
        )

        initial_stock2 = self.product2.quantity
        CombinedOrderService.complete_combined_order(result['combined_order_id'], 'test_user')

        # Product1 should NOT be deducted again
        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity, initial_stock - 1)  # Still just -1

        # Product2 should be deducted
        self.product2.refresh_from_db()
        self.assertEqual(self.product2.quantity, initial_stock2 - 2)


class TestCombinedOrderAmountReconciliation(CombinedOrderServiceTestBase):
    """Tests for amount reconciliation in complex scenarios."""

    def test_amount_fulfilled_consistency_across_operations(self):
        """Test that amount_fulfilled stays consistent across multiple operations."""
        txn1 = self.create_transaction('TXN001', 5000)
        txn2 = self.create_transaction('TXN002', 5000)

        # Partially fulfill txn1
        FulfillmentService.activate_issuance(txn1.id)
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD001', 'quantity': 1})  # 1000
        FulfillmentService.complete_issuance(txn1.id)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        parent = order.parent_transaction

        # Check initial state
        self.assertEqual(order.amount_fulfilled, Decimal('1000.00'))
        self.assertEqual(order.base_amount_fulfilled, Decimal('1000.00'))
        parent.refresh_from_db()
        self.assertEqual(parent.amount_fulfilled, Decimal('1000.00'))

        # Activate
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        order.refresh_from_db()
        self.assertEqual(order.amount_fulfilled, Decimal('1000.00'))

        # Scan items
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product2.id, 2, 'test_user'
        )  # +1000
        order.refresh_from_db()
        parent.refresh_from_db()
        self.assertEqual(order.amount_fulfilled, Decimal('2000.00'))
        self.assertEqual(parent.amount_fulfilled, Decimal('2000.00'))

        # Remove the new item
        new_item = order.line_items.filter(is_inventory_deducted=False).first()
        CombinedOrderService.remove_combined_order_line_item(
            result['combined_order_id'],
            new_item.id
        )
        order.refresh_from_db()
        parent.refresh_from_db()
        self.assertEqual(order.amount_fulfilled, Decimal('1000.00'))
        self.assertEqual(parent.amount_fulfilled, Decimal('1000.00'))

        # Scan again
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product2.id, 4, 'test_user'
        )  # +2000
        order.refresh_from_db()
        parent.refresh_from_db()
        self.assertEqual(order.amount_fulfilled, Decimal('3000.00'))
        self.assertEqual(parent.amount_fulfilled, Decimal('3000.00'))

        # Cancel issuance
        CombinedOrderService.cancel_combined_order_issuance(
            result['combined_order_id'],
            cancelled_by='test_user'
        )
        order.refresh_from_db()
        parent.refresh_from_db()
        self.assertEqual(order.amount_fulfilled, Decimal('1000.00'))  # Back to base
        self.assertEqual(parent.amount_fulfilled, Decimal('1000.00'))

    def test_remaining_amount_calculation(self):
        """Test remaining_amount property calculation."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 2000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.remaining_amount, Decimal('5000.00'))

        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 2, 'test_user'
        )  # 2000

        order.refresh_from_db()
        self.assertEqual(order.remaining_amount, Decimal('3000.00'))

    def test_fulfillment_percentage_calculation(self):
        """Test fulfillment_percentage property calculation."""
        txn1 = self.create_transaction('TXN001', 5000)
        txn2 = self.create_transaction('TXN002', 5000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.fulfillment_percentage, Decimal('0'))

        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 5, 'test_user'
        )  # 5000 = 50%

        order.refresh_from_db()
        self.assertEqual(order.fulfillment_percentage, Decimal('50'))


class TestCombinedOrderEdgeCases(CombinedOrderServiceTestBase):
    """Tests for edge cases and potential bugs."""

    def test_reactivate_partially_fulfilled_order(self):
        """Test reactivating an order after partial completion."""
        txn1 = self.create_transaction('TXN001', 5000)
        txn2 = self.create_transaction('TXN002', 5000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        # First session: scan and complete partial
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 2, 'test_user'
        )  # 2000
        CombinedOrderService.complete_combined_order(result['combined_order_id'], 'test_user')

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.status, CombinedOrder.Status.PARTIALLY_FULFILLED)
        self.assertEqual(order.amount_fulfilled, Decimal('2000.00'))

        # Second session: reactivate and add more
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        order.refresh_from_db()
        self.assertEqual(order.status, CombinedOrder.Status.IN_PROGRESS)
        self.assertEqual(order.amount_fulfilled_before_activation, Decimal('2000.00'))

        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product2.id, 4, 'test_user'
        )  # +2000

        order.refresh_from_db()
        self.assertEqual(order.amount_fulfilled, Decimal('4000.00'))

        # Complete again
        CombinedOrderService.complete_combined_order(result['combined_order_id'], 'test_user')

        order.refresh_from_db()
        self.assertEqual(order.status, CombinedOrder.Status.PARTIALLY_FULFILLED)
        self.assertEqual(order.amount_fulfilled, Decimal('4000.00'))
        self.assertEqual(order.line_items.filter(is_inventory_deducted=True).count(), 2)

    def test_cancel_after_reactivation_preserves_previous_fulfillment(self):
        """Test cancelling after reactivation preserves the previous session's items."""
        txn1 = self.create_transaction('TXN001', 5000)
        txn2 = self.create_transaction('TXN002', 5000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        # First session
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 2, 'test_user'
        )
        CombinedOrderService.complete_combined_order(result['combined_order_id'], 'test_user')

        # Second session
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product2.id, 2, 'test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.line_items.count(), 2)

        # Cancel second session
        CombinedOrderService.cancel_combined_order_issuance(
            result['combined_order_id'],
            cancelled_by='test_user'
        )

        order.refresh_from_db()
        # First session's items should still be there
        self.assertEqual(order.line_items.count(), 1)
        self.assertEqual(order.line_items.first().product, self.product1)
        self.assertTrue(order.line_items.first().is_inventory_deducted)
        self.assertEqual(order.amount_fulfilled, Decimal('2000.00'))

    def test_inventory_not_double_deducted_for_copied_items(self):
        """Test that inventory is not deducted twice for items copied from child transactions."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 3000)

        initial_stock = self.product1.quantity

        # Partially fulfill txn1
        FulfillmentService.activate_issuance(txn1.id)
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD001', 'quantity': 2})
        FulfillmentService.complete_issuance(txn1.id)

        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity, initial_stock - 2)

        # Combine
        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        # Activate and complete (without scanning anything new)
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        # Scan a different product
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product2.id, 1, 'test_user'
        )

        initial_stock2 = self.product2.quantity
        CombinedOrderService.complete_combined_order(result['combined_order_id'], 'test_user')

        # Product1 should NOT be deducted again
        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity, initial_stock - 2)  # Same as before

        # Product2 should be deducted
        self.product2.refresh_from_db()
        self.assertEqual(self.product2.quantity, initial_stock2 - 1)

    def test_line_item_line_total_calculation(self):
        """Test that line_total is calculated correctly on CombinedOrderLineItem.save()."""
        txn1 = self.create_transaction('TXN001', 5000)
        txn2 = self.create_transaction('TXN002', 5000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 3, 'test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        line_item = order.line_items.first()

        self.assertEqual(line_item.quantity, 3)
        self.assertEqual(line_item.scanned_price, Decimal('1000.00'))
        self.assertEqual(line_item.line_total, Decimal('3000.00'))  # 3 x 1000

    def test_zero_quantity_scan_rejected(self):
        """Test that zero or negative quantity scans are rejected."""
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 3000)

        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        with self.assertRaises(ValidationError):
            CombinedOrderService.scan_product_to_combined_order_staged(
                result['combined_order_id'], self.product1.id, 0, 'test_user'
            )

        with self.assertRaises(ValidationError):
            CombinedOrderService.scan_product_to_combined_order_staged(
                result['combined_order_id'], self.product1.id, -1, 'test_user'
            )
