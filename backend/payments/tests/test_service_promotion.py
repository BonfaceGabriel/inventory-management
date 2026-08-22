from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from payments.services.promotion_service import PromotionService
from payments.models import Promotion, PromotionProduct, TransactionLineItem
from .test_helpers import (
    make_admin, make_gateway, make_transaction, make_product, make_line_item,
)


class PromotionServiceTest(TestCase):
    def setUp(self):
        self.admin = make_admin(username='promo_admin')
        self.gateway = make_gateway()
        self.product_a = make_product(
            prod_code='PROMO-A', prod_name='Promo Product A',
            price=Decimal('500.00'), quantity=100, pv=Decimal('10.00'),
            cost_price=Decimal('300.00'),
        )
        self.product_b = make_product(
            prod_code='PROMO-B', prod_name='Promo Product B',
            price=Decimal('300.00'), quantity=100, pv=Decimal('5.00'),
            cost_price=Decimal('200.00'),
        )
        self.tx = make_transaction(tx_id='PROMO-TX', amount=Decimal('10000.00'))

    def _make_active_promotion(self, name='Test Promo', discount_type='FIXED',
                                discount_value=Decimal('200.00')):
        promo = Promotion.objects.create(
            name=name,
            discount_type=discount_type,
            discount_value=discount_value,
            start_date=timezone.now() - timezone.timedelta(days=1),
            end_date=timezone.now() + timezone.timedelta(days=30),
            is_active=True,
            created_by=self.admin,
        )
        return promo

    def test_get_active_promotions_returns_active_only(self):
        self._make_active_promotion('Active Promo')
        expired = Promotion.objects.create(
            name='Expired Promo',
            discount_type='FIXED',
            discount_value=Decimal('100.00'),
            start_date=timezone.now() - timezone.timedelta(days=10),
            end_date=timezone.now() - timezone.timedelta(days=1),
            is_active=True,
            created_by=self.admin,
        )
        active = PromotionService.get_active_promotions()
        names = [p.name for p in active]
        self.assertIn('Active Promo', names)
        self.assertNotIn('Expired Promo', names)

    def test_apply_promotions_fixed_discount(self):
        promo = self._make_active_promotion(
            name='Buy 3 Get 200 Off',
            discount_type='FIXED',
            discount_value=Decimal('200.00'),
        )
        PromotionProduct.objects.create(
            promotion=promo, product=self.product_a, min_quantity=3,
        )
        make_line_item(self.tx, self.product_a, quantity=5)
        make_line_item(self.tx, self.product_b, quantity=2)
        qs = TransactionLineItem.objects.filter(transaction=self.tx)
        PromotionService.apply_promotions(qs)
        items = list(qs)
        expected_discount_per_item = Decimal('200.00') / 5
        self.assertAlmostEqual(
            float(items[0].scanned_price),
            float(self.product_a.cost_price - expected_discount_per_item),
            places=2,
        )

    def test_apply_promotions_percentage_discount(self):
        promo = self._make_active_promotion(
            name='10% Bundle Off',
            discount_type='PERCENTAGE',
            discount_value=Decimal('10.00'),
        )
        PromotionProduct.objects.create(
            promotion=promo, product=self.product_a, min_quantity=2,
        )
        make_line_item(self.tx, self.product_a, quantity=4)
        qs = TransactionLineItem.objects.filter(transaction=self.tx)
        PromotionService.apply_promotions(qs)
        li = qs.first()
        expected_price = self.product_a.cost_price * Decimal('0.90')
        self.assertAlmostEqual(float(li.scanned_price), float(expected_price), places=2)

    def test_apply_promotions_no_discount_when_below_min_quantity(self):
        promo = self._make_active_promotion(
            name='Min 5 Required',
            discount_type='FIXED',
            discount_value=Decimal('500.00'),
        )
        PromotionProduct.objects.create(
            promotion=promo, product=self.product_a, min_quantity=5,
        )
        make_line_item(self.tx, self.product_a, quantity=2)
        qs = TransactionLineItem.objects.filter(transaction=self.tx)
        PromotionService.apply_promotions(qs)
        li = qs.first()
        self.assertEqual(li.scanned_price, self.product_a.cost_price)

    def test_apply_promotions_empty_line_items(self):
        promo = self._make_active_promotion()
        PromotionProduct.objects.create(
            promotion=promo, product=self.product_a, min_quantity=1,
        )
        empty_qs = TransactionLineItem.objects.filter(transaction=self.tx)
        PromotionService.apply_promotions(empty_qs)

    def test_apply_promotions_no_active_promotions(self):
        make_line_item(self.tx, self.product_a, quantity=2)
        qs = TransactionLineItem.objects.filter(transaction=self.tx)
        PromotionService.apply_promotions(qs)
        li = qs.first()
        self.assertEqual(li.scanned_price, self.product_a.cost_price)
