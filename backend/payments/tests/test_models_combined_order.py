from decimal import Decimal
from django.test import TestCase
from payments.models import CombinedOrder, CombinedOrderTransaction, CombinedOrderLineItem
from .test_helpers import (
    make_gateway, make_transaction, make_product, make_admin,
    make_location, make_combined_order,
)


class CombinedOrderModelTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.location = make_location()
        self.gateway = make_gateway()
        self.tx1 = make_transaction(tx_id='CMB-M-TX1', amount=Decimal('1000.00'))
        self.tx2 = make_transaction(tx_id='CMB-M-TX2', amount=Decimal('500.00'), unique_hash='hash_cmb_m2')
        self.order = make_combined_order(
            transactions=[self.tx1, self.tx2],
            created_by=self.admin,
            location=self.location,
        )

    def test_initial_status_is_pending(self):
        self.assertEqual(self.order.status, 'PENDING')

    def test_total_amount_is_sum_of_child_transactions(self):
        self.assertEqual(self.order.total_amount, Decimal('1500.00'))

    def test_transaction_count_property(self):
        self.assertEqual(self.order.transaction_count, 2)

    def test_remaining_amount_equals_total_when_nothing_fulfilled(self):
        self.assertEqual(self.order.remaining_amount, Decimal('1500.00'))

    def test_fulfillment_percentage_zero_initially(self):
        self.assertEqual(self.order.fulfillment_percentage, Decimal('0'))

    def test_string_contains_order_id_and_total(self):
        self.assertIn(self.order.combined_order_id, str(self.order))
        self.assertIn('1500', str(self.order))

    def test_combined_order_id_format(self):
        self.assertTrue(self.order.combined_order_id.startswith('CMB-'))

    def test_parent_transaction_created(self):
        self.assertIsNotNone(self.order.parent_transaction)
        self.assertEqual(self.order.parent_transaction.amount, self.order.total_amount)
        self.assertEqual(self.order.parent_transaction.status, 'PROCESSING')


class CombinedOrderTransactionTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.location = make_location()
        self.gateway = make_gateway()
        self.tx1 = make_transaction(tx_id='CMB-LNK-TX1', amount=Decimal('1000.00'))
        self.tx2 = make_transaction(tx_id='CMB-LNK-TX2', amount=Decimal('500.00'), unique_hash='hash_cmb_lnk2')
        self.order = make_combined_order(
            transactions=[self.tx1, self.tx2],
            created_by=self.admin,
            location=self.location,
        )

    def test_child_transactions_are_combined_fulfilled(self):
        self.tx1.refresh_from_db()
        self.tx2.refresh_from_db()
        self.assertEqual(self.tx1.status, 'COMBINED_FULFILLED')
        self.assertEqual(self.tx2.status, 'COMBINED_FULFILLED')

    def test_link_records_exist(self):
        links = CombinedOrderTransaction.objects.filter(combined_order=self.order)
        self.assertEqual(links.count(), 2)

    def test_link_string_representation(self):
        link = CombinedOrderTransaction.objects.filter(combined_order=self.order).first()
        self.assertIn(self.order.combined_order_id, str(link))
        self.assertIn(self.tx1.tx_id, str(link))

    def test_unique_together_constraint(self):
        with self.assertRaises(Exception):
            CombinedOrderTransaction.objects.create(
                combined_order=self.order,
                transaction=self.tx1,
            )

    def test_sequence_is_set(self):
        links = CombinedOrderTransaction.objects.filter(combined_order=self.order).order_by('sequence')
        self.assertEqual(links[0].sequence, 0)
        self.assertEqual(links[1].sequence, 1)


class CombinedOrderLineItemTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.location = make_location()
        self.gateway = make_gateway()
        self.product = make_product(price=Decimal('500.00'), pv=Decimal('10.00'), cost_price=Decimal('300.00'))
        self.tx1 = make_transaction(tx_id='CMB-LI-TX1', amount=Decimal('1000.00'))
        self.tx2 = make_transaction(tx_id='CMB-LI-TX2', amount=Decimal('500.00'), unique_hash='hash_cmb_li2')
        self.order = make_combined_order(
            transactions=[self.tx1, self.tx2],
            created_by=self.admin,
            location=self.location,
        )

    def test_line_total_auto_calculated(self):
        item = CombinedOrderLineItem.objects.create(
            combined_order=self.order,
            product=self.product,
            scanned_prod_code=self.product.prod_code,
            scanned_prod_name=self.product.prod_name,
            scanned_sku=self.product.sku,
            scanned_price=self.product.current_price,
            scanned_pv=self.product.current_pv,
            quantity=3,
        )
        self.assertEqual(item.line_total, Decimal('1500.00'))

    def test_line_cost_auto_calculated(self):
        item = CombinedOrderLineItem.objects.create(
            combined_order=self.order,
            product=self.product,
            scanned_prod_code=self.product.prod_code,
            scanned_prod_name=self.product.prod_name,
            scanned_sku=self.product.sku,
            scanned_price=self.product.current_price,
            scanned_pv=self.product.current_pv,
            quantity=3,
        )
        self.assertEqual(item.line_cost, Decimal('900.00'))

    def test_line_pv_auto_calculated(self):
        item = CombinedOrderLineItem.objects.create(
            combined_order=self.order,
            product=self.product,
            scanned_prod_code=self.product.prod_code,
            scanned_prod_name=self.product.prod_name,
            scanned_sku=self.product.sku,
            scanned_price=self.product.current_price,
            scanned_pv=self.product.current_pv,
            quantity=3,
        )
        self.assertEqual(item.line_pv, Decimal('30.00'))

    def test_string_representation(self):
        item = CombinedOrderLineItem.objects.create(
            combined_order=self.order,
            product=self.product,
            scanned_prod_code=self.product.prod_code,
            scanned_prod_name=self.product.prod_name,
            scanned_sku=self.product.sku,
            scanned_price=self.product.current_price,
            scanned_pv=self.product.current_pv,
            quantity=2,
        )
        self.assertIn(self.product.prod_name, str(item))

    def test_is_inventory_deducted_defaults_false(self):
        item = CombinedOrderLineItem.objects.create(
            combined_order=self.order,
            product=self.product,
            scanned_prod_code=self.product.prod_code,
            scanned_prod_name=self.product.prod_name,
            scanned_sku=self.product.sku,
            scanned_price=self.product.current_price,
            scanned_pv=self.product.current_pv,
            quantity=1,
        )
        self.assertFalse(item.is_inventory_deducted)
