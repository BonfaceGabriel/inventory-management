"""
Test to reproduce the combined order partial fulfillment bug.

Bug scenario: When combining two or more partially fulfilled transactions,
scanning doesn't correctly use the remaining balance (total_paid - total_fulfilled)
nor properly inherit line items.
"""
from decimal import Decimal
from django.test import TransactionTestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
import hashlib

from payments.models import (
    Transaction, Product, CombinedOrder, CombinedOrderTransaction,
    CombinedOrderLineItem, TransactionLineItem, InventoryMovement,
    PaymentGateway
)
from payments.services.combined_order_service import CombinedOrderService
from payments.services.fulfillment_service import FulfillmentService


class TestPartialFulfillmentBugReproduction(TransactionTestCase):
    """Test to reproduce the partial fulfillment combination bug."""

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
            gateway_number='TEST123',
            settlement_type=PaymentGateway.SettlementType.NONE
        )

        # Create products
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
        return Transaction.objects.create(
            tx_id=tx_id,
            amount=Decimal(str(amount)),
            sender_name=f'Sender {tx_id}',
            sender_phone='0712345678',
            timestamp=timezone.now(),
            gateway=self.gateway,
            unique_hash=unique_hash,
            status=status or Transaction.OrderStatus.NOT_PROCESSED
        )

    def test_two_partially_fulfilled_combine_remaining_balance(self):
        """
        BUG REPRODUCTION TEST:
        
        Scenario:
        - TXN1: 3000 KES, partially fulfilled 1000 KES (product1 x1)
        - TXN2: 2000 KES, partially fulfilled 500 KES (product2 x1)
        - Total paid: 5000 KES
        - Total already fulfilled: 1500 KES
        - Expected remaining: 3500 KES
        
        Expected behavior:
        - Combined order should have remaining_amount = 3500 KES
        - Scanning should be able to use up to 3500 KES worth of products
        - Line items from both partial fulfillments should be visible
        """
        # Create two transactions
        txn1 = self.create_transaction('TXN001', 3000)
        txn2 = self.create_transaction('TXN002', 2000)

        # Partially fulfill txn1: 1000 KES (1x product1)
        FulfillmentService.activate_issuance(txn1.id)
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD001', 'quantity': 1})
        FulfillmentService.complete_issuance(txn1.id)

        txn1.refresh_from_db()
        print(f"TXN1 after partial fulfillment: amount={txn1.amount}, fulfilled={txn1.amount_fulfilled}")
        self.assertEqual(txn1.amount_fulfilled, Decimal('1000.00'))
        self.assertEqual(txn1.status, Transaction.OrderStatus.PARTIALLY_FULFILLED)

        # Partially fulfill txn2: 500 KES (1x product2)
        FulfillmentService.activate_issuance(txn2.id)
        FulfillmentService.scan_barcode(txn2.id, {'prod_code': 'PROD002', 'quantity': 1})
        FulfillmentService.complete_issuance(txn2.id)

        txn2.refresh_from_db()
        print(f"TXN2 after partial fulfillment: amount={txn2.amount}, fulfilled={txn2.amount_fulfilled}")
        self.assertEqual(txn2.amount_fulfilled, Decimal('500.00'))
        self.assertEqual(txn2.status, Transaction.OrderStatus.PARTIALLY_FULFILLED)

        # Combine both transactions
        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        print(f"Combined order result: {result}")
        
        # Verify totals
        self.assertEqual(result['total_amount'], 5000.0)
        self.assertEqual(result['amount_fulfilled'], 1500.0)  # 1000 + 500
        self.assertEqual(result['remaining_amount'], 3500.0)  # 5000 - 1500

        # Get the combined order
        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        
        print(f"CombinedOrder: total={order.total_amount}, fulfilled={order.amount_fulfilled}, remaining={order.remaining_amount}")
        print(f"CombinedOrder: base_amount_fulfilled={order.base_amount_fulfilled}")
        
        # Verify line items were copied (2 line items from 2 partial fulfillments)
        line_items = order.line_items.all()
        print(f"Line items count: {line_items.count()}")
        for item in line_items:
            print(f"  - {item.product.prod_code}: qty={item.quantity}, total={item.line_total}, deducted={item.is_inventory_deducted}")
        
        self.assertEqual(line_items.count(), 2)
        self.assertEqual(line_items.filter(is_inventory_deducted=True).count(), 2)

        # Activate and try to scan more products
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')
        
        order.refresh_from_db()
        print(f"After activation: remaining={order.remaining_amount}")
        
        # Should be able to scan 3500 KES worth
        # Try scanning product3 (2000 KES) - should succeed
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product3.id, 1, 'test_user'
        )  # 2000 KES
        
        order.refresh_from_db()
        print(f"After scanning product3: fulfilled={order.amount_fulfilled}, remaining={order.remaining_amount}")
        
        # fulfilled should now be 1500 + 2000 = 3500
        self.assertEqual(order.amount_fulfilled, Decimal('3500.00'))
        self.assertEqual(order.remaining_amount, Decimal('1500.00'))
        
        # Can still scan more - try 1000 KES (product1)
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product1.id, 1, 'test_user'
        )  # 1000 KES
        
        order.refresh_from_db()
        print(f"After scanning product1: fulfilled={order.amount_fulfilled}, remaining={order.remaining_amount}")
        
        # fulfilled should now be 3500 + 1000 = 4500
        self.assertEqual(order.amount_fulfilled, Decimal('4500.00'))
        self.assertEqual(order.remaining_amount, Decimal('500.00'))

        # Verify all line items (2 copied + 2 newly scanned)
        all_items = order.line_items.all()
        print(f"Final line items count: {all_items.count()}")
        for item in all_items:
            print(f"  - {item.product.prod_code}: qty={item.quantity}, total={item.line_total}, deducted={item.is_inventory_deducted}, copied_from={item.copied_from_transaction_id}")
        
        self.assertEqual(all_items.count(), 4)
        self.assertEqual(all_items.filter(is_inventory_deducted=True).count(), 2)  # copied items
        self.assertEqual(all_items.filter(is_inventory_deducted=False).count(), 2)  # newly scanned

    def test_budget_validation_uses_remaining_from_children(self):
        """
        Test that budget validation correctly uses remaining balance from child transactions.
        
        When scanning exceeds the actual remaining balance, it should fail.
        """
        # Create two transactions
        txn1 = self.create_transaction('TXN001', 2000)
        txn2 = self.create_transaction('TXN002', 1500)

        # Partially fulfill txn1: 1500 KES
        FulfillmentService.activate_issuance(txn1.id)
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD001', 'quantity': 1})  # 1000
        FulfillmentService.scan_barcode(txn1.id, {'prod_code': 'PROD002', 'quantity': 1})  # 500
        FulfillmentService.complete_issuance(txn1.id)

        # Combine
        result = CombinedOrderService.create_combined_order(
            transaction_ids=[txn1.id, txn2.id],
            created_by='test_user'
        )

        # Total: 3500, Fulfilled: 1500, Remaining: 2000
        self.assertEqual(result['remaining_amount'], 2000.0)

        # Activate
        CombinedOrderService.activate_combined_order(result['combined_order_id'], 'test_user')

        # Try to scan product3 (2000 KES) - should succeed (exactly remaining)
        CombinedOrderService.scan_product_to_combined_order_staged(
            result['combined_order_id'], self.product3.id, 1, 'test_user'
        )

        order = CombinedOrder.objects.get(combined_order_id=result['combined_order_id'])
        self.assertEqual(order.remaining_amount, Decimal('0.00'))

        # Try to scan more - should fail (exceeds budget)
        with self.assertRaises(ValidationError) as context:
            CombinedOrderService.scan_product_to_combined_order_staged(
                result['combined_order_id'], self.product2.id, 1, 'test_user'
            )
        
        self.assertIn('exceed budget', str(context.exception))


if __name__ == '__main__':
    import django
    django.setup()
    import unittest
    unittest.main()
