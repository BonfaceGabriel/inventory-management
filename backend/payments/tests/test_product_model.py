"""
Unit tests for Product, ProductCategory, TransactionLineItem, and InventoryMovement models.
"""

from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from payments.models import (
    Product, ProductCategory, TransactionLineItem, InventoryMovement,
    Transaction, PaymentGateway, Device
)


class ProductCategoryModelTest(TestCase):
    """Test cases for ProductCategory model."""

    def setUp(self):
        """Set up test data."""
        self.parent_category = ProductCategory.objects.create(
            name='Health Supplements',
            description='All health supplement products'
        )

    def test_create_category(self):
        """Test creating a product category."""
        category = ProductCategory.objects.create(
            name='Coffee Products',
            description='All coffee-based products'
        )
        self.assertEqual(category.name, 'Coffee Products')
        self.assertEqual(category.description, 'All coffee-based products')
        self.assertIsNone(category.parent_category)

    def test_create_subcategory(self):
        """Test creating a subcategory with parent."""
        subcategory = ProductCategory.objects.create(
            name='Capsules',
            description='Capsule supplements',
            parent_category=self.parent_category
        )
        self.assertEqual(subcategory.parent_category, self.parent_category)
        self.assertIn(subcategory, self.parent_category.subcategories.all())

    def test_category_name_unique(self):
        """Test that category names must be unique."""
        with self.assertRaises(IntegrityError):
            ProductCategory.objects.create(name='Health Supplements')

    def test_category_str(self):
        """Test string representation of category."""
        self.assertEqual(str(self.parent_category), 'Health Supplements')

    def test_timestamps(self):
        """Test that timestamps are auto-generated."""
        category = ProductCategory.objects.create(name='Test Category')
        self.assertIsNotNone(category.created_at)
        self.assertIsNotNone(category.updated_at)


class ProductModelTest(TestCase):
    """Test cases for Product model."""

    def setUp(self):
        """Set up test data."""
        self.category = ProductCategory.objects.create(
            name='Supplements',
            description='Health supplements'
        )

    def test_create_product(self):
        """Test creating a product with all required fields."""
        product = Product.objects.create(
            prod_code='AP004E',
            prod_name='MicroQ2 Cycle Tablets',
            sku='AP004E',
            sku_name='100 tablets',
            current_price=Decimal('2970.00'),
            cost_price=Decimal('2079.00'),
            current_pv=Decimal('11.00'),
            quantity=100,
            reorder_level=10,
            category=self.category,
            is_active=True
        )

        self.assertEqual(product.prod_code, 'AP004E')
        self.assertEqual(product.prod_name, 'MicroQ2 Cycle Tablets')
        self.assertEqual(product.current_price, Decimal('2970.00'))
        self.assertEqual(product.current_pv, Decimal('11.00'))
        self.assertEqual(product.quantity, 100)
        self.assertTrue(product.is_active)

    def test_product_prod_code_unique(self):
        """Test that prod_code must be unique."""
        Product.objects.create(
            prod_code='AP004E',
            prod_name='Test Product',
            sku='AP004E',
            sku_name='Test',
            current_price=Decimal('100.00'),
            cost_price=Decimal('70.00'),
            current_pv=Decimal('5.00')
        )

        with self.assertRaises(IntegrityError):
            Product.objects.create(
                prod_code='AP004E',  # Duplicate prod_code
                prod_name='Another Product',
                sku='AP004E2',
                sku_name='Test2',
                current_price=Decimal('200.00'),
                cost_price=Decimal('140.00'),
                current_pv=Decimal('10.00')
            )

    def test_product_sku_unique(self):
        """Test that SKU must be unique."""
        Product.objects.create(
            prod_code='AP004E',
            prod_name='Test Product',
            sku='TESTSKU001',
            sku_name='Test',
            current_price=Decimal('100.00'),
            cost_price=Decimal('70.00'),
            current_pv=Decimal('5.00')
        )

        with self.assertRaises(IntegrityError):
            Product.objects.create(
                prod_code='AP005E',
                prod_name='Another Product',
                sku='TESTSKU001',  # Duplicate SKU
                sku_name='Test2',
                current_price=Decimal('200.00'),
                cost_price=Decimal('140.00'),
                current_pv=Decimal('10.00')
            )

    def test_product_str(self):
        """Test string representation of product."""
        product = Product.objects.create(
            prod_code='AP004E',
            prod_name='MicroQ2 Cycle Tablets',
            sku='AP004E',
            sku_name='100 tablets',
            current_price=Decimal('2970.00'),
            cost_price=Decimal('2079.00'),
            current_pv=Decimal('11.00')
        )
        self.assertEqual(str(product), 'AP004E - MicroQ2 Cycle Tablets')

    def test_product_timestamps(self):
        """Test that timestamps are auto-generated."""
        product = Product.objects.create(
            prod_code='AP004E',
            prod_name='Test Product',
            sku='AP004E',
            sku_name='Test',
            current_price=Decimal('100.00'),
            cost_price=Decimal('70.00'),
            current_pv=Decimal('5.00')
        )
        self.assertIsNotNone(product.created_at)
        self.assertIsNotNone(product.updated_at)

    def test_product_defaults(self):
        """Test default values for product fields."""
        product = Product.objects.create(
            prod_code='AP004E',
            prod_name='Test Product',
            sku='AP004E',
            sku_name='Test',
            current_price=Decimal('100.00'),
            cost_price=Decimal('70.00'),
            current_pv=Decimal('5.00')
        )
        self.assertEqual(product.quantity, 0)  # Default quantity
        self.assertEqual(product.reorder_level, 10)  # Default reorder level
        self.assertTrue(product.is_active)  # Default is_active


class TransactionLineItemModelTest(TestCase):
    """Test cases for TransactionLineItem model."""

    def setUp(self):
        """Set up test data."""
        # Create gateway
        self.gateway = PaymentGateway.objects.create(
            name='Test Gateway',
            gateway_type=PaymentGateway.GatewayType.MPESA_TILL,
            gateway_number='123456',
            settlement_type=PaymentGateway.SettlementType.NONE
        )

        # Create device
        self.device = Device.objects.create(
            name='Test Device',
            phone_number='0712345678',
            gateway=self.gateway
        )

        # Create transaction
        from django.utils import timezone
        import hashlib
        # Generate unique_hash (same as what the system would generate)
        unique_hash = hashlib.sha256(f"TEST12345|5000.00|{timezone.now().isoformat()}".encode()).hexdigest()
        self.transaction = Transaction.objects.create(
            tx_id='TEST12345',
            amount=Decimal('5000.00'),
            sender_name='JOHN DOE',
            sender_phone='0712345678',
            timestamp=timezone.now(),
            gateway=self.gateway,
            unique_hash=unique_hash,
            status=Transaction.OrderStatus.NOT_PROCESSED
        )

        # Create product
        self.product = Product.objects.create(
            prod_code='AP004E',
            prod_name='MicroQ2 Cycle Tablets',
            sku='AP004E',
            sku_name='100 tablets',
            current_price=Decimal('2970.00'),
            cost_price=Decimal('2079.00'),
            current_pv=Decimal('11.00'),
            quantity=100
        )

    def test_create_line_item(self):
        """Test creating a transaction line item."""
        line_item = TransactionLineItem.objects.create(
            transaction=self.transaction,
            product=self.product,
            scanned_prod_code='AP004E',
            scanned_prod_name='MicroQ2 Cycle Tablets',
            scanned_sku='AP004E',
            scanned_sku_name='100 tablets',
            scanned_price=Decimal('2970.00'),
            scanned_pv=Decimal('11.00'),
            quantity=2,
            scanned_by='John Scanner'
        )

        self.assertEqual(line_item.transaction, self.transaction)
        self.assertEqual(line_item.product, self.product)
        self.assertEqual(line_item.quantity, 2)
        self.assertEqual(line_item.scanned_price, Decimal('2970.00'))

    def test_line_item_auto_calculate_totals(self):
        """Test that line totals are auto-calculated on save."""
        line_item = TransactionLineItem.objects.create(
            transaction=self.transaction,
            product=self.product,
            scanned_prod_code='AP004E',
            scanned_prod_name='MicroQ2 Cycle Tablets',
            scanned_sku='AP004E',
            scanned_sku_name='100 tablets',
            scanned_price=Decimal('2970.00'),
            scanned_pv=Decimal('11.00'),
            quantity=2
        )

        # Check auto-calculated totals
        self.assertEqual(line_item.line_total, Decimal('5940.00'))  # 2 * 2970
        self.assertEqual(line_item.line_cost, Decimal('4158.00'))   # 2 * 2079
        self.assertEqual(line_item.line_pv, Decimal('22.00'))       # 2 * 11

    def test_line_item_recalculates_on_quantity_change(self):
        """Test that totals recalculate when quantity changes."""
        line_item = TransactionLineItem.objects.create(
            transaction=self.transaction,
            product=self.product,
            scanned_prod_code='AP004E',
            scanned_prod_name='MicroQ2 Cycle Tablets',
            scanned_sku='AP004E',
            scanned_sku_name='100 tablets',
            scanned_price=Decimal('2970.00'),
            scanned_pv=Decimal('11.00'),
            quantity=2
        )

        # Change quantity
        line_item.quantity = 5
        line_item.save()

        # Check recalculated totals
        self.assertEqual(line_item.line_total, Decimal('14850.00'))  # 5 * 2970
        self.assertEqual(line_item.line_cost, Decimal('10395.00'))   # 5 * 2079
        self.assertEqual(line_item.line_pv, Decimal('55.00'))        # 5 * 11

    def test_line_item_str(self):
        """Test string representation of line item."""
        line_item = TransactionLineItem.objects.create(
            transaction=self.transaction,
            product=self.product,
            scanned_prod_code='AP004E',
            scanned_prod_name='MicroQ2 Cycle Tablets',
            scanned_sku='AP004E',
            scanned_sku_name='100 tablets',
            scanned_price=Decimal('2970.00'),
            scanned_pv=Decimal('11.00'),
            quantity=2
        )
        expected = f'2x MicroQ2 Cycle Tablets (TX: {self.transaction.tx_id})'
        self.assertEqual(str(line_item), expected)

    def test_frozen_barcode_data(self):
        """Test that scanned barcode data is frozen at scan time."""
        # Create line item with specific scanned data
        line_item = TransactionLineItem.objects.create(
            transaction=self.transaction,
            product=self.product,
            scanned_prod_code='AP004E',
            scanned_prod_name='MicroQ2 Cycle Tablets',
            scanned_sku='AP004E',
            scanned_sku_name='100 tablets',
            scanned_price=Decimal('2970.00'),
            scanned_pv=Decimal('11.00'),
            quantity=1
        )

        # Change product price
        self.product.current_price = Decimal('3500.00')
        self.product.save()

        # Reload line item
        line_item.refresh_from_db()

        # Scanned price should remain unchanged
        self.assertEqual(line_item.scanned_price, Decimal('2970.00'))
        self.assertNotEqual(line_item.scanned_price, self.product.current_price)


class InventoryMovementModelTest(TestCase):
    """Test cases for InventoryMovement model."""

    def setUp(self):
        """Set up test data."""
        self.product = Product.objects.create(
            prod_code='AP004E',
            prod_name='MicroQ2 Cycle Tablets',
            sku='AP004E',
            sku_name='100 tablets',
            current_price=Decimal('2970.00'),
            cost_price=Decimal('2079.00'),
            current_pv=Decimal('11.00'),
            quantity=100
        )

    def test_create_inventory_movement(self):
        """Test creating an inventory movement record."""
        movement = InventoryMovement.objects.create(
            movement_type=InventoryMovement.MovementType.SALE,
            product=self.product,
            quantity_before=100,
            quantity_after=95,
            quantity_change=-5,
            reference='Transaction TEST12345',
            performed_by='System'
        )

        self.assertEqual(movement.movement_type, InventoryMovement.MovementType.SALE)
        self.assertEqual(movement.product, self.product)
        self.assertEqual(movement.quantity_change, -5)

    def test_inventory_movement_types(self):
        """Test all movement type choices."""
        movement_types = [
            InventoryMovement.MovementType.STOCK_TAKE,
            InventoryMovement.MovementType.SALE,
            InventoryMovement.MovementType.ADJUSTMENT,
            InventoryMovement.MovementType.RETURN,
            InventoryMovement.MovementType.PURCHASE,
        ]

        for idx, movement_type in enumerate(movement_types):
            movement = InventoryMovement.objects.create(
                movement_type=movement_type,
                product=self.product,
                quantity_before=100,
                quantity_after=100 - idx,
                quantity_change=-idx,
                reference=f'Test {movement_type}'
            )
            self.assertEqual(movement.movement_type, movement_type)

    def test_inventory_movement_str(self):
        """Test string representation of inventory movement."""
        movement = InventoryMovement.objects.create(
            movement_type=InventoryMovement.MovementType.SALE,
            product=self.product,
            quantity_before=100,
            quantity_after=95,
            quantity_change=-5,
            reference='TEST12345'
        )
        expected = 'Sale: -5 MicroQ2 Cycle Tablets'
        self.assertEqual(str(movement), expected)

    def test_inventory_movement_timestamp(self):
        """Test that timestamp is auto-generated."""
        movement = InventoryMovement.objects.create(
            movement_type=InventoryMovement.MovementType.PURCHASE,
            product=self.product,
            quantity_before=100,
            quantity_after=150,
            quantity_change=50
        )
        self.assertIsNotNone(movement.created_at)
