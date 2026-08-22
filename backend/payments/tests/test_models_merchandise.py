from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from payments.models import (
    MerchandiseCatalogItem, MerchandiseCatalogOption,
    MerchandiseOrder, MerchandiseOrderLine,
    MerchandiseStock, MerchandiseStockMovement,
    Promotion, PromotionProduct,
)
from .test_helpers import make_admin, make_product, make_gateway, make_device, make_transaction


class MerchandiseCatalogItemTest(TestCase):
    def setUp(self):
        self.item = MerchandiseCatalogItem.objects.create(
            code='TSHIRT-001',
            name='Classic T-Shirt',
            item_type='TSHIRT',
            unit_price=Decimal('1500.00'),
        )

    def test_string_representation(self):
        self.assertIn(self.item.name, str(self.item))
        self.assertIn(self.item.code, str(self.item))

    def test_is_active_default_true(self):
        self.assertTrue(self.item.is_active)

    def test_unique_code(self):
        with self.assertRaises(Exception):
            MerchandiseCatalogItem.objects.create(
                code='TSHIRT-001', name='Duplicate',
                item_type='HAT', unit_price=Decimal('500.00'),
            )

    def test_item_type_choices(self):
        types = dict(MerchandiseCatalogItem.ItemType.choices)
        self.assertIn('TSHIRT', types)
        self.assertIn('HAT', types)
        self.assertIn('COFFEE', types)


class MerchandiseCatalogOptionTest(TestCase):
    def setUp(self):
        self.item = MerchandiseCatalogItem.objects.create(
            code='TSHIRT-OPT', name='Option Test T-Shirt',
            item_type='TSHIRT', unit_price=Decimal('1500.00'),
        )

    def test_create_color_option(self):
        opt = MerchandiseCatalogOption.objects.create(
            item=self.item, option_type='COLOR', value='Red',
        )
        self.assertEqual(opt.option_type, 'COLOR')

    def test_create_size_option(self):
        opt = MerchandiseCatalogOption.objects.create(
            item=self.item, option_type='SIZE', value='Large',
        )
        self.assertEqual(opt.option_type, 'SIZE')

    def test_unique_together(self):
        MerchandiseCatalogOption.objects.create(
            item=self.item, option_type='COLOR', value='Red',
        )
        with self.assertRaises(Exception):
            MerchandiseCatalogOption.objects.create(
                item=self.item, option_type='COLOR', value='Red',
            )

    def test_string_representation(self):
        opt = MerchandiseCatalogOption.objects.create(
            item=self.item, option_type='COLOR', value='Blue',
        )
        self.assertIn(self.item.code, str(opt))
        self.assertIn('COLOR', str(opt))
        self.assertIn('Blue', str(opt))


class MerchandiseOrderTest(TestCase):
    def setUp(self):
        self.gateway = make_gateway(name='Merch GW', gateway_type='MERCHANDISE', gateway_number='MERCH-01')
        self.tx = make_transaction(tx_id='MERCH-ORD-TX', gateway=self.gateway, amount=Decimal('3000.00'))
        self.device = make_device(gateway=self.gateway)

    def test_create_pending_order(self):
        order = MerchandiseOrder.objects.create(
            transaction=self.tx,
            gateway=self.gateway,
            device=self.device,
        )
        self.assertEqual(order.status, 'PENDING')

    def test_string_representation(self):
        order = MerchandiseOrder.objects.create(
            transaction=self.tx,
            gateway=self.gateway,
        )
        self.assertIn(self.tx.tx_id, str(order))

    def test_fulfill_order(self):
        admin = make_admin(username='merch_admin')
        order = MerchandiseOrder.objects.create(
            transaction=self.tx,
            gateway=self.gateway,
        )
        order.status = 'FULFILLED'
        order.fulfilled_by = admin
        order.fulfilled_at = timezone.now()
        order.save()
        order.refresh_from_db()
        self.assertEqual(order.status, 'FULFILLED')
        self.assertIsNotNone(order.fulfilled_at)


class MerchandiseOrderLineTest(TestCase):
    def setUp(self):
        self.gateway = make_gateway(name='Merch GW', gateway_type='MERCHANDISE', gateway_number='MERCH-02')
        self.tx = make_transaction(tx_id='MERCH-LINE-TX', gateway=self.gateway, amount=Decimal('3000.00'))
        self.order = MerchandiseOrder.objects.create(transaction=self.tx, gateway=self.gateway)
        self.item_item = MerchandiseCatalogItem.objects.create(
            code='TSHIRT-LN', name='Line Test T-Shirt',
            item_type='TSHIRT', unit_price=Decimal('1500.00'),
        )

    def test_clean_rejects_zero_quantity(self):
        with self.assertRaises(ValidationError):
            line = MerchandiseOrderLine(
                order=self.order, item=self.item_item,
                quantity=0, unit_price_snapshot=Decimal('1500.00'),
                line_total=Decimal('0.00'),
            )
            line.clean()

    def test_tshirt_requires_color_and_size(self):
        line = MerchandiseOrderLine(
            order=self.order, item=self.item_item,
            quantity=2, unit_price_snapshot=Decimal('1500.00'),
            line_total=Decimal('3000.00'),
            color='Red', size='Large',
        )
        line.clean()

    def test_tshirt_rejects_missing_color(self):
        with self.assertRaises(ValidationError):
            line = MerchandiseOrderLine(
                order=self.order, item=self.item_item,
                quantity=2, unit_price_snapshot=Decimal('1500.00'),
                line_total=Decimal('3000.00'),
                size='Large',
            )
            line.clean()

    def test_string_representation(self):
        line = MerchandiseOrderLine.objects.create(
            order=self.order, item=self.item_item,
            quantity=2, unit_price_snapshot=Decimal('1500.00'),
            line_total=Decimal('3000.00'),
            color='Blue', size='Medium',
        )
        self.assertIn(self.item_item.name, str(line))

    def test_hat_rejects_size(self):
        hat = MerchandiseCatalogItem.objects.create(
            code='HAT-LN', name='Line Test Hat',
            item_type='HAT', unit_price=Decimal('800.00'),
        )
        with self.assertRaises(ValidationError):
            line = MerchandiseOrderLine(
                order=self.order, item=hat,
                quantity=1, unit_price_snapshot=Decimal('800.00'),
                line_total=Decimal('800.00'),
                color='Black', size='Large',
            )
            line.clean()

    def test_coffee_rejects_color_and_size(self):
        coffee = MerchandiseCatalogItem.objects.create(
            code='COF-LN', name='Line Test Coffee',
            item_type='COFFEE', unit_price=Decimal('500.00'),
        )
        with self.assertRaises(ValidationError):
            line = MerchandiseOrderLine(
                order=self.order, item=coffee,
                quantity=1, unit_price_snapshot=Decimal('500.00'),
                line_total=Decimal('500.00'),
                color='Red',
            )
            line.clean()


class MerchandiseStockTest(TestCase):
    def setUp(self):
        self.item = MerchandiseCatalogItem.objects.create(
            code='TSHIRT-STK', name='Stock Test T-Shirt',
            item_type='TSHIRT', unit_price=Decimal('1500.00'),
        )

    def test_default_quantity_zero(self):
        stock = MerchandiseStock.objects.create(item=self.item, color='Red', size='Large')
        self.assertEqual(stock.quantity, 0)

    def test_unique_variant_constraint(self):
        MerchandiseStock.objects.create(item=self.item, color='Red', size='Large', quantity=10)
        with self.assertRaises(Exception):
            MerchandiseStock.objects.create(item=self.item, color='Red', size='Large', quantity=5)

    def test_string_representation(self):
        stock = MerchandiseStock.objects.create(item=self.item, color='Blue', size='Medium', quantity=15)
        self.assertIn(self.item.code, str(stock))
        self.assertIn('15', str(stock))


class MerchandiseStockMovementTest(TestCase):
    def setUp(self):
        self.item = MerchandiseCatalogItem.objects.create(
            code='TSHIRT-MOV', name='Movement Test T-Shirt',
            item_type='TSHIRT', unit_price=Decimal('1500.00'),
        )
        self.stock = MerchandiseStock.objects.create(item=self.item, color='Red', size='Large', quantity=10)

    def test_movement_types(self):
        types = dict(MerchandiseStockMovement.MovementType.choices)
        self.assertIn('MANUAL_ADD', types)
        self.assertIn('MANUAL_DEDUCT', types)
        self.assertIn('FULFILLMENT', types)

    def test_create_fulfillment_movement(self):
        admin = make_admin(username='movement_admin')
        mov = MerchandiseStockMovement.objects.create(
            stock=self.stock,
            movement_type='FULFILLMENT',
            quantity_change=-2,
            quantity_before=10,
            quantity_after=8,
            performed_by=admin,
        )
        self.assertEqual(mov.quantity_after, 8)


class PromotionModelTest(TestCase):
    def setUp(self):
        self.admin = make_admin(username='promo_admin')

    def test_create_fixed_promotion(self):
        promo = Promotion.objects.create(
            name='KES 500 Off',
            discount_type='FIXED',
            discount_value=Decimal('500.00'),
            start_date=timezone.now() - timezone.timedelta(days=1),
            end_date=timezone.now() + timezone.timedelta(days=30),
            is_active=True,
            created_by=self.admin,
        )
        self.assertTrue(promo.is_currently_active)

    def test_create_percentage_promotion(self):
        promo = Promotion.objects.create(
            name='10% Off',
            discount_type='PERCENTAGE',
            discount_value=Decimal('10.00'),
            start_date=timezone.now() - timezone.timedelta(days=1),
            end_date=timezone.now() + timezone.timedelta(days=30),
            is_active=True,
            created_by=self.admin,
        )
        self.assertEqual(promo.discount_type, 'PERCENTAGE')

    def test_expired_promotion_not_currently_active(self):
        promo = Promotion.objects.create(
            name='Expired',
            discount_type='FIXED',
            discount_value=Decimal('100.00'),
            start_date=timezone.now() - timezone.timedelta(days=10),
            end_date=timezone.now() - timezone.timedelta(days=1),
            is_active=True,
            created_by=self.admin,
        )
        self.assertFalse(promo.is_currently_active)

    def test_inactive_promotion_not_currently_active(self):
        promo = Promotion.objects.create(
            name='Inactive',
            discount_type='FIXED',
            discount_value=Decimal('200.00'),
            start_date=timezone.now() - timezone.timedelta(days=1),
            end_date=timezone.now() + timezone.timedelta(days=30),
            is_active=False,
            created_by=self.admin,
        )
        self.assertFalse(promo.is_currently_active)

    def test_string_representation(self):
        promo = Promotion.objects.create(
            name='Test Promo',
            discount_type='FIXED',
            discount_value=Decimal('100.00'),
            start_date=timezone.now(),
            end_date=timezone.now() + timezone.timedelta(days=30),
            created_by=self.admin,
        )
        self.assertIn('Test Promo', str(promo))


class PromotionProductTest(TestCase):
    def setUp(self):
        self.admin = make_admin(username='pp_admin')
        self.product = make_product(prod_code='PROMO-PROD')
        self.promo = Promotion.objects.create(
            name='Bundle Deal',
            discount_type='FIXED',
            discount_value=Decimal('200.00'),
            start_date=timezone.now() - timezone.timedelta(days=1),
            end_date=timezone.now() + timezone.timedelta(days=30),
            created_by=self.admin,
        )

    def test_create_promotion_product(self):
        pp = PromotionProduct.objects.create(
            promotion=self.promo,
            product=self.product,
            min_quantity=3,
        )
        self.assertEqual(pp.min_quantity, 3)

    def test_unique_together(self):
        PromotionProduct.objects.create(
            promotion=self.promo, product=self.product, min_quantity=2,
        )
        with self.assertRaises(Exception):
            PromotionProduct.objects.create(
                promotion=self.promo, product=self.product, min_quantity=5,
            )

    def test_min_quantity_defaults_one(self):
        pp = PromotionProduct.objects.create(
            promotion=self.promo, product=self.product,
        )
        self.assertEqual(pp.min_quantity, 1)

    def test_string_representation(self):
        pp = PromotionProduct.objects.create(
            promotion=self.promo, product=self.product, min_quantity=2,
        )
        self.assertIn(self.promo.name, str(pp))
        self.assertIn(self.product.prod_name, str(pp))
