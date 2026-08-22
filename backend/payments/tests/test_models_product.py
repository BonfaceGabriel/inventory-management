from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from payments.models import Product, ProductLine, TransactionLineItem, InventoryMovement
from .test_helpers import make_product, make_product_line, make_gateway, make_transaction, make_device, make_issuer


class ProductLineModelTest(TestCase):
    def setUp(self):
        self.parent = make_product_line(name='Parent Line')
        self.child = ProductLine.objects.create(name='Child Line', parent_line=self.parent)

    def test_string_without_parent(self):
        self.assertEqual(str(self.parent), 'Parent Line')

    def test_string_with_parent(self):
        self.assertIn('Parent', str(self.child))
        self.assertIn('Child', str(self.child))

    def test_unique_name_constraint(self):
        with self.assertRaises(Exception):
            ProductLine.objects.create(name='Parent Line')


class ProductModelTest(TestCase):
    def setUp(self):
        self.product = make_product()

    def test_string_representation(self):
        self.assertIn('PROD001', str(self.product))

    def test_low_stock_when_quantity_below_reorder(self):
        self.product.quantity = 5
        self.product.reorder_level = 10
        self.assertTrue(self.product.is_low_stock)

    def test_not_low_stock_when_quantity_above_reorder(self):
        self.product.quantity = 20
        self.product.reorder_level = 10
        self.assertFalse(self.product.is_low_stock)

    def test_out_of_stock_when_quantity_zero(self):
        self.product.quantity = 0
        self.assertTrue(self.product.is_out_of_stock)

    def test_out_of_stock_when_quantity_negative(self):
        self.product.quantity = -1
        self.assertTrue(self.product.is_out_of_stock)

    def test_in_stock_when_quantity_positive(self):
        self.product.quantity = 50
        self.assertFalse(self.product.is_out_of_stock)

    def test_stock_status_out_of_stock(self):
        self.product.quantity = 0
        self.assertEqual(self.product.stock_status, 'Out of Stock')

    def test_stock_status_low_stock(self):
        self.product.quantity = 5
        self.product.reorder_level = 10
        self.assertEqual(self.product.stock_status, 'Low Stock')

    def test_stock_status_in_stock(self):
        self.product.quantity = 50
        self.assertEqual(self.product.stock_status, 'In Stock')

    def test_clean_validates_price_positive(self):
        self.product.current_price = Decimal('-10.00')
        with self.assertRaises(ValidationError):
            self.product.clean()

    def test_clean_validates_cost_price_non_negative(self):
        self.product.cost_price = Decimal('-1.00')
        with self.assertRaises(ValidationError):
            self.product.clean()

    def test_clean_validates_quantity_non_negative(self):
        self.product.quantity = -5
        with self.assertRaises(ValidationError):
            self.product.clean()

    def test_clean_passes_with_valid_data(self):
        self.product.clean()

    def test_unique_prod_code(self):
        with self.assertRaises(Exception):
            Product.objects.create(
                prod_code='PROD001', prod_name='Duplicate',
                sku='SKU-DUP', current_price=Decimal('100.00'),
                cost_price=Decimal('50.00'), quantity=10
            )

    def test_unique_sku(self):
        with self.assertRaises(Exception):
            Product.objects.create(
                prod_code='PROD-DUP', prod_name='Duplicate SKU',
                sku='PROD001', current_price=Decimal('100.00'),
                cost_price=Decimal('50.00'), quantity=10
            )

    def test_default_quantity_zero(self):
        p = Product.objects.create(
            prod_code='PROD-ZERO', prod_name='Zero Qty',
            sku='SKU-ZERO', current_price=Decimal('100.00'),
            cost_price=Decimal('50.00'), current_pv=Decimal('0.00'),
        )
        self.assertEqual(p.quantity, 0)


class TransactionLineItemModelTest(TestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.tx = make_transaction(tx_id='LI-TX-001')
        self.product = make_product(price=Decimal('500.00'), pv=Decimal('10.00'), cost_price=Decimal('300.00'))
        self.issuer = make_issuer()

    def test_line_total_auto_calculated(self):
        item = make_line_item_bare(self.tx, self.product, quantity=3, scanned_by_user=self.issuer)
        self.assertEqual(item.line_total, Decimal('1500.00'))

    def test_line_cost_auto_calculated(self):
        item = make_line_item_bare(self.tx, self.product, quantity=3, scanned_by_user=self.issuer)
        self.assertEqual(item.line_cost, Decimal('900.00'))

    def test_line_pv_auto_calculated(self):
        item = make_line_item_bare(self.tx, self.product, quantity=3, scanned_by_user=self.issuer)
        self.assertEqual(item.line_pv, Decimal('30.00'))

    def test_string_representation(self):
        item = make_line_item_bare(self.tx, self.product, quantity=2, scanned_by_user=self.issuer)
        self.assertIn(self.product.prod_name, str(item))
        self.assertIn(self.tx.tx_id, str(item))

    def test_clean_validates_quantity_positive(self):
        item = TransactionLineItem(
            transaction=self.tx, product=self.product,
            scanned_prod_code=self.product.prod_code,
            scanned_prod_name=self.product.prod_name,
            scanned_sku=self.product.sku,
            scanned_price=self.product.current_price,
            scanned_pv=self.product.current_pv,
            quantity=0,
        )
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_clean_validates_sufficient_stock(self):
        self.product.quantity = 2
        self.product.save()
        item = TransactionLineItem(
            transaction=self.tx, product=self.product,
            scanned_prod_code=self.product.prod_code,
            scanned_prod_name=self.product.prod_name,
            scanned_sku=self.product.sku,
            scanned_price=self.product.current_price,
            scanned_pv=self.product.current_pv,
            quantity=5,
        )
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_clean_passes_with_valid_quantity_and_stock(self):
        self.product.quantity = 100
        self.product.save()
        item = TransactionLineItem.objects.create(
            transaction=self.tx, product=self.product,
            scanned_prod_code=self.product.prod_code,
            scanned_prod_name=self.product.prod_name,
            scanned_sku=self.product.sku,
            scanned_price=self.product.current_price,
            scanned_pv=self.product.current_pv,
            quantity=2,
        )
        self.assertEqual(item.quantity, 2)

    def test_is_inventory_deducted_defaults_false(self):
        item = make_line_item_bare(self.tx, self.product, quantity=1, scanned_by_user=self.issuer)
        self.assertFalse(item.is_inventory_deducted)

    def test_scanned_at_is_set(self):
        item = make_line_item_bare(self.tx, self.product, quantity=1, scanned_by_user=self.issuer)
        self.assertIsNotNone(item.scanned_at)

    def test_scanned_by_user_nullable(self):
        item = TransactionLineItem.objects.create(
            transaction=self.tx, product=self.product,
            scanned_prod_code=self.product.prod_code,
            scanned_prod_name=self.product.prod_name,
            scanned_sku=self.product.sku,
            scanned_price=self.product.current_price,
            scanned_pv=self.product.current_pv,
            quantity=1,
        )
        self.assertIsNone(item.scanned_by_user)


class InventoryMovementModelTest(TestCase):
    def setUp(self):
        self.product = make_product(quantity=100)
        self.admin = make_issuer(username='movement_issuer')

    def test_movement_type_choices(self):
        for mt in ['STOCK_TAKE', 'SALE', 'ADJUSTMENT', 'RETURN', 'PURCHASE']:
            m = InventoryMovement.objects.create(
                movement_type=mt,
                product=self.product,
                quantity_before=100,
                quantity_after=mt == 'SALE' and 90 or 110,
                quantity_change=mt == 'SALE' and -10 or 10,
            )
            self.assertEqual(m.movement_type, mt)

    def test_quantity_change_calculation(self):
        m = InventoryMovement.objects.create(
            movement_type='SALE',
            product=self.product,
            quantity_before=100,
            quantity_after=90,
            quantity_change=-10,
        )
        self.assertEqual(m.quantity_change, -10)

    def test_string_includes_movement_type(self):
        m = InventoryMovement.objects.create(
            movement_type='SALE',
            product=self.product,
            quantity_before=100,
            quantity_after=90,
            quantity_change=-10,
        )
        self.assertIn('SALE', str(m))
        self.assertIn(self.product.prod_name, str(m))
        self.assertIn('-10', str(m))

    def test_clean_validates_arithmetic(self):
        mov = InventoryMovement(
            movement_type='ADJUSTMENT',
            product=self.product,
            quantity_before=100,
            quantity_after=200,
            quantity_change=50,
        )
        with self.assertRaises(ValidationError):
            mov.full_clean()

    def test_clean_passes_with_valid_arithmetic(self):
        m = InventoryMovement.objects.create(
            movement_type='RETURN',
            product=self.product,
            quantity_before=90,
            quantity_after=100,
            quantity_change=10,
        )
        self.assertEqual(m.quantity_after, m.quantity_before + m.quantity_change)


def make_line_item_bare(transaction, product, quantity=1, scanned_by_user=None):
    return TransactionLineItem.objects.create(
        transaction=transaction,
        product=product,
        scanned_prod_code=product.prod_code,
        scanned_prod_name=product.prod_name,
        scanned_sku=product.sku,
        scanned_sku_name=product.sku_name or '',
        scanned_price=product.current_price,
        scanned_pv=product.current_pv,
        quantity=quantity,
        scanned_by_user=scanned_by_user,
    )
