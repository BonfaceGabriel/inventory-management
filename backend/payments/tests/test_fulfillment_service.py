"""
Unit tests for FulfillmentService.

Tests all business logic for scanner-based transaction fulfillment:
- Activating issuance
- Scanning products
- Completing issuance with inventory updates
- Cancelling issuance
- Business rule validation
"""

from decimal import Decimal
from django.test import TransactionTestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
import hashlib

from payments.models import (
    Transaction, Product, ProductCategory, TransactionLineItem,
    InventoryMovement, PaymentGateway
)
from payments.services.fulfillment_service import FulfillmentService


class FulfillmentServiceTest(TransactionTestCase):
    """Test cases for FulfillmentService."""

    def setUp(self):
        """Set up test data."""
        # Clear data for test isolation
        Transaction.objects.all().delete()
        Product.objects.all().delete()
        ProductCategory.objects.all().delete()
        TransactionLineItem.objects.all().delete()
        InventoryMovement.objects.all().delete()

        # Create gateway
        self.gateway = PaymentGateway.objects.create(
            name='Test Gateway',
            gateway_type=PaymentGateway.GatewayType.MPESA_TILL,
            gateway_number='123456',
            settlement_type=PaymentGateway.SettlementType.NONE
        )

        # Create products
        self.product1 = Product.objects.create(
            prod_code='AP004E',
            prod_name='MicroQ2 Cycle Tablets',
            sku='AP004E',
            sku_name='100 tablets',
            current_price=Decimal('2970.00'),
            cost_price=Decimal('2079.00'),
            current_pv=Decimal('11.00'),
            quantity=100,
            is_active=True
        )

        self.product2 = Product.objects.create(
            prod_code='AP008E',
            prod_name='Consiclean Capsules',
            sku='AP008E',
            sku_name='30s/Box',
            current_price=Decimal('3915.00'),
            cost_price=Decimal('2740.50'),
            current_pv=Decimal('22.00'),
            quantity=50,
            is_active=True
        )

        # Create transaction
        unique_hash = hashlib.sha256(
            f"TEST001|5000.00|{timezone.now().isoformat()}".encode()
        ).hexdigest()
        self.transaction = Transaction.objects.create(
            tx_id='TEST001',
            amount=Decimal('5000.00'),
            sender_name='JOHN DOE',
            sender_phone='0712345678',
            timestamp=timezone.now(),
            gateway=self.gateway,
            unique_hash=unique_hash,
            status=Transaction.OrderStatus.NOT_PROCESSED
        )

    def test_activate_issuance(self):
        """Test activating issuance for a transaction."""
        result = FulfillmentService.activate_issuance(self.transaction.id)

        self.assertTrue(result['success'])
        self.assertEqual(result['tx_id'], 'TEST001')

        # Verify transaction state
        self.transaction.refresh_from_db()
        self.assertTrue(self.transaction.is_in_issuance)
        self.assertEqual(self.transaction.status, Transaction.OrderStatus.PROCESSING)

    def test_activate_issuance_only_one_at_a_time(self):
        """Test that only one transaction can be in issuance at a time."""
        # Activate first transaction
        FulfillmentService.activate_issuance(self.transaction.id)

        # Create second transaction
        unique_hash = hashlib.sha256(
            f"TEST002|3000.00|{timezone.now().isoformat()}".encode()
        ).hexdigest()
        transaction2 = Transaction.objects.create(
            tx_id='TEST002',
            amount=Decimal('3000.00'),
            sender_name='JANE DOE',
            sender_phone='0723456789',
            timestamp=timezone.now(),
            gateway=self.gateway,
            unique_hash=unique_hash,
            status=Transaction.OrderStatus.NOT_PROCESSED
        )

        # Try to activate second transaction
        with self.assertRaises(ValidationError) as context:
            FulfillmentService.activate_issuance(transaction2.id)

        self.assertIn('is_in_issuance', context.exception.message_dict)

    def test_activate_issuance_locked_transaction(self):
        """Test that locked transactions cannot be activated."""
        # Use update() to bypass validation for test setup
        Transaction.objects.filter(id=self.transaction.id).update(
            status=Transaction.OrderStatus.FULFILLED
        )

        with self.assertRaises(ValidationError) as context:
            FulfillmentService.activate_issuance(self.transaction.id)

        self.assertIn('status', context.exception.message_dict)

    def test_scan_barcode_adds_product(self):
        """Test scanning a product barcode."""
        # Activate issuance
        FulfillmentService.activate_issuance(self.transaction.id)

        # Scan product (1 unit fits within transaction amount)
        result = FulfillmentService.scan_barcode(
            self.transaction.id,
            {'sku': 'AP004E', 'quantity': 1},
            scanned_by='Test User'
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['product_code'], 'AP004E')
        self.assertEqual(result['quantity'], 1)
        self.assertEqual(Decimal(result['line_total']), Decimal('2970.00'))  # 1 * 2970

        # Verify line item created
        line_items = TransactionLineItem.objects.filter(transaction=self.transaction)
        self.assertEqual(line_items.count(), 1)
        self.assertEqual(line_items.first().quantity, 1)

        # Verify transaction totals updated
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.amount_fulfilled, Decimal('2970.00'))

    def test_scan_barcode_without_issuance_fails(self):
        """Test that scanning fails if transaction not in issuance."""
        with self.assertRaises(ValidationError) as context:
            FulfillmentService.scan_barcode(
                self.transaction.id,
                {'sku': 'AP004E', 'quantity': 1}
            )

        self.assertIn('is_in_issuance', context.exception.message_dict)

    def test_scan_barcode_insufficient_stock(self):
        """Test that scanning fails if insufficient stock."""
        FulfillmentService.activate_issuance(self.transaction.id)

        # Try to scan more than available
        with self.assertRaises(ValidationError) as context:
            FulfillmentService.scan_barcode(
                self.transaction.id,
                {'sku': 'AP004E', 'quantity': 150}  # Only 100 available
            )

        self.assertIn('quantity', context.exception.message_dict)

    def test_scan_barcode_exceeds_transaction_amount(self):
        """Test that scanning fails if total exceeds transaction amount."""
        FulfillmentService.activate_issuance(self.transaction.id)

        # Scan product that would exceed transaction amount
        # Product costs 2970, transaction amount is 5000
        # Can fit 1 item (2970), but not 2 (5940 > 5000)
        FulfillmentService.scan_barcode(
            self.transaction.id,
            {'sku': 'AP004E', 'quantity': 1}
        )

        # Try to scan another one (would exceed)
        with self.assertRaises(ValidationError) as context:
            FulfillmentService.scan_barcode(
                self.transaction.id,
                {'sku': 'AP004E', 'quantity': 1}
            )

        self.assertIn('amount', context.exception.message_dict)

        # Verify line item was not created
        line_items = TransactionLineItem.objects.filter(transaction=self.transaction)
        self.assertEqual(line_items.count(), 1)  # Still only 1

    def test_scan_barcode_nonexistent_product(self):
        """Test that scanning fails for non-existent product."""
        FulfillmentService.activate_issuance(self.transaction.id)

        with self.assertRaises(ValidationError) as context:
            FulfillmentService.scan_barcode(
                self.transaction.id,
                {'sku': 'NOTEXIST', 'quantity': 1}
            )

        self.assertIn('product', context.exception.message_dict)

    def test_scan_multiple_products(self):
        """Test that scanning a second product that would exceed the limit fails."""
        FulfillmentService.activate_issuance(self.transaction.id)

        # Scan first product (2970)
        result1 = FulfillmentService.scan_barcode(
            self.transaction.id,
            {'sku': 'AP004E', 'quantity': 1}  # 2970
        )
        self.assertTrue(result1['success'])
        self.assertEqual(Decimal(result1['line_total']), Decimal('2970.00'))

        # Try to scan second product (3915) - should fail because 2970 + 3915 = 6885 > 5000
        with self.assertRaises(ValidationError) as context:
            FulfillmentService.scan_barcode(
                self.transaction.id,
                {'sku': 'AP008E', 'quantity': 1}  # 3915 (would exceed 5000)
            )

        self.assertIn('amount', context.exception.message_dict)

        # Verify only first product was added
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.amount_fulfilled, Decimal('2970.00'))
        line_items = TransactionLineItem.objects.filter(transaction=self.transaction)
        self.assertEqual(line_items.count(), 1)

    def test_complete_issuance_updates_inventory(self):
        """Test that completing issuance updates inventory."""
        # Activate and scan products
        FulfillmentService.activate_issuance(self.transaction.id)
        FulfillmentService.scan_barcode(
            self.transaction.id,
            {'sku': 'AP004E', 'quantity': 1}
        )

        # Record initial stock
        initial_stock = self.product1.quantity

        # Complete issuance
        result = FulfillmentService.complete_issuance(
            self.transaction.id,
            performed_by='Test User'
        )

        self.assertTrue(result['success'])
        self.assertEqual(len(result['inventory_updates']), 1)

        # Verify inventory updated
        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity, initial_stock - 1)

        # Verify inventory movement created
        movements = InventoryMovement.objects.filter(product=self.product1)
        self.assertEqual(movements.count(), 1)
        movement = movements.first()
        self.assertEqual(movement.movement_type, InventoryMovement.MovementType.SALE)
        self.assertEqual(movement.quantity_change, -1)

        # Verify transaction no longer in issuance
        self.transaction.refresh_from_db()
        self.assertFalse(self.transaction.is_in_issuance)

    def test_complete_issuance_without_line_items_fails(self):
        """Test that completing issuance fails if no products scanned."""
        FulfillmentService.activate_issuance(self.transaction.id)

        with self.assertRaises(ValidationError) as context:
            FulfillmentService.complete_issuance(self.transaction.id)

        self.assertIn('line_items', context.exception.message_dict)

    def test_cancel_issuance_removes_line_items(self):
        """Test that cancelling issuance removes line items without updating inventory."""
        # Activate and scan products
        FulfillmentService.activate_issuance(self.transaction.id)
        FulfillmentService.scan_barcode(
            self.transaction.id,
            {'sku': 'AP004E', 'quantity': 1}
        )

        # Record initial stock
        initial_stock = self.product1.quantity

        # Cancel issuance
        result = FulfillmentService.cancel_issuance(
            self.transaction.id,
            reason='Testing cancellation'
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['line_items_removed'], 1)

        # Verify line items deleted
        line_items = TransactionLineItem.objects.filter(transaction=self.transaction)
        self.assertEqual(line_items.count(), 0)

        # Verify inventory NOT changed
        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity, initial_stock)

        # Verify transaction state reset
        self.transaction.refresh_from_db()
        self.assertFalse(self.transaction.is_in_issuance)
        self.assertEqual(self.transaction.amount_fulfilled, Decimal('0.00'))
        self.assertEqual(self.transaction.status, Transaction.OrderStatus.NOT_PROCESSED)

        # Verify reason in notes
        self.assertIn('Issuance Cancelled', self.transaction.notes)

    def test_get_current_issuance(self):
        """Test getting the currently active issuance."""
        # No issuance initially
        current = FulfillmentService.get_current_issuance()
        self.assertIsNone(current)

        # Activate issuance
        FulfillmentService.activate_issuance(self.transaction.id)

        # Should return current issuance
        current = FulfillmentService.get_current_issuance()
        self.assertIsNotNone(current)
        self.assertEqual(current['tx_id'], 'TEST001')
        self.assertEqual(current['line_items_count'], 0)

        # Scan a product
        FulfillmentService.scan_barcode(
            self.transaction.id,
            {'sku': 'AP004E', 'quantity': 1}
        )

        # Should include line items
        current = FulfillmentService.get_current_issuance()
        self.assertEqual(current['line_items_count'], 1)
        self.assertEqual(len(current['line_items']), 1)

    def test_amount_fulfilled_cannot_exceed_payment_amount(self):
        """Test business rule: amount_fulfilled <= transaction.amount."""
        FulfillmentService.activate_issuance(self.transaction.id)

        # Try to scan products that would exceed transaction amount
        # Transaction amount: 5000
        # Product1 price: 2970
        # Try scanning 2 items: 5940 > 5000 (should fail)

        with self.assertRaises(ValidationError) as context:
            FulfillmentService.scan_barcode(
                self.transaction.id,
                {'sku': 'AP004E', 'quantity': 2}
            )

        self.assertIn('amount', context.exception.message_dict)

        # Verify transaction amount_fulfilled is still 0
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.amount_fulfilled, Decimal('0.00'))

    def test_transaction_status_updates_on_fulfillment(self):
        """Test that transaction status updates based on fulfillment level."""
        # Create transaction with exact amount for 1 product
        unique_hash = hashlib.sha256(
            f"TEST003|2970.00|{timezone.now().isoformat()}".encode()
        ).hexdigest()
        txn = Transaction.objects.create(
            tx_id='TEST003',
            amount=Decimal('2970.00'),  # Exact price of product1
            sender_name='TEST USER',
            sender_phone='0712345678',
            timestamp=timezone.now(),
            gateway=self.gateway,
            unique_hash=unique_hash,
            status=Transaction.OrderStatus.NOT_PROCESSED
        )

        # Activate
        FulfillmentService.activate_issuance(txn.id)
        txn.refresh_from_db()
        self.assertEqual(txn.status, Transaction.OrderStatus.PROCESSING)

        # Scan product (exact amount)
        FulfillmentService.scan_barcode(
            txn.id,
            {'sku': 'AP004E', 'quantity': 1}
        )

        # Status should be FULFILLED
        txn.refresh_from_db()
        self.assertEqual(txn.status, Transaction.OrderStatus.FULFILLED)

        # Complete issuance
        FulfillmentService.complete_issuance(txn.id)

        # Status should remain FULFILLED
        txn.refresh_from_db()
        self.assertEqual(txn.status, Transaction.OrderStatus.FULFILLED)
        self.assertFalse(txn.is_in_issuance)
