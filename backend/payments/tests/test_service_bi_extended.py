from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from payments.models import Transaction
from payments.services.bi_extended_service import BiExtendedService
from .test_helpers import (
    make_admin, make_gateway, make_product, make_transaction,
    make_line_item, make_product_line, make_combined_order,
    make_processor, make_issuer, today, now,
)


class BiExtendedServiceProductTest(TestCase):
    def setUp(self):
        self.gw = make_gateway(name='Test Till', gateway_type='MPESA_TILL', gateway_number='BI-TILL')
        self.product = make_product(
            prod_code='ZAM001', prod_name='Zaminocal',
            price=Decimal('500.00'), quantity=50, pv=Decimal('10.00'),
            cost_price=Decimal('300.00'),
        )
        self.tx = make_transaction(
            tx_id='BI-PROD-TX', amount=Decimal('1000.00'),
            gateway=self.gw, status='FULFILLED',
            amount_fulfilled=Decimal('1000.00'),
        )
        make_line_item(self.tx, self.product, quantity=2)

    def test_get_product_stock_found(self):
        result = BiExtendedService.get_product_stock('Zaminocal')
        self.assertTrue(result['found'])
        self.assertEqual(len(result['products']), 1)
        self.assertEqual(result['products'][0]['name'], 'Zaminocal')
        self.assertEqual(result['products'][0]['quantity'], 50)

    def test_get_product_stock_not_found(self):
        result = BiExtendedService.get_product_stock('NonExistent')
        self.assertFalse(result['found'])

    def test_get_product_sales_found(self):
        result = BiExtendedService.get_product_sales('Zaminocal', today())
        self.assertTrue(result['found'])
        self.assertEqual(result['total_quantity_sold'], 2)
        self.assertEqual(result['total_revenue'], 1000.0)

    def test_get_product_sales_not_found(self):
        result = BiExtendedService.get_product_sales('NonExistent', today())
        self.assertFalse(result['found'])

    def test_get_top_products(self):
        result = BiExtendedService.get_top_products(today(), limit=5)
        self.assertIn('products', result)
        self.assertGreaterEqual(len(result['products']), 1)
        self.assertEqual(result['products'][0]['name'], 'Zaminocal')

    def test_get_top_products_by_revenue(self):
        result = BiExtendedService.get_top_products_by_revenue(today(), limit=5)
        self.assertIn('products', result)
        self.assertGreaterEqual(len(result['products']), 1)
        self.assertEqual(result['products'][0]['revenue'], 1000.0)

    def test_get_inventory_value(self):
        result = BiExtendedService.get_inventory_value()
        self.assertIn('total_stock_units', result)
        self.assertIn('total_value_at_retail', result)
        self.assertGreaterEqual(result['total_stock_units'], 50)

    def test_get_stock_movements(self):
        result = BiExtendedService.get_stock_movements('Zaminocal', days=7)
        self.assertEqual(result['product_query'], 'Zaminocal')
        self.assertIn('movements', result)

    def test_get_product_sales_trend(self):
        result = BiExtendedService.get_product_sales_trend('Zaminocal', days=7)
        self.assertEqual(result['query'], 'Zaminocal')
        self.assertGreaterEqual(result['total_quantity'], 0)
        self.assertIn('data_points', result)

    def test_get_pv_summary(self):
        result = BiExtendedService.get_pv_summary(today())
        self.assertEqual(result['date'], today().isoformat())
        self.assertGreaterEqual(result['total_pv'], 0)

    def test_get_total_cost(self):
        result = BiExtendedService.get_total_cost(today())
        self.assertEqual(result['date'], today().isoformat())
        self.assertGreaterEqual(result['total_cost_of_goods_sold'], 0)


class BiExtendedServiceCategoryTest(TestCase):
    def setUp(self):
        self.gw = make_gateway(name='Test Till', gateway_type='MPESA_TILL', gateway_number='BI-CAT')
        self.line = make_product_line(name='Immune Boosters')
        self.product = make_product(
            prod_code='IMM001', prod_name='Immune Booster',
            product_line=self.line, quantity=30,
        )
        self.tx = make_transaction(
            tx_id='BI-CAT-TX', amount=Decimal('500.00'),
            gateway=self.gw, status='FULFILLED',
            amount_fulfilled=Decimal('500.00'),
        )
        make_line_item(self.tx, self.product, quantity=3)

    def test_get_category_sales_found(self):
        result = BiExtendedService.get_category_sales('Immune', today())
        self.assertTrue(result['found'])
        self.assertGreaterEqual(result['total_quantity_sold'], 3)

    def test_get_category_sales_not_found(self):
        result = BiExtendedService.get_category_sales('NonExistent', today())
        self.assertFalse(result['found'])

    def test_get_stock_by_category(self):
        result = BiExtendedService.get_stock_by_category()
        self.assertGreaterEqual(result['total_categories'], 1)
        cat_names = [c['name'] for c in result['categories']]
        self.assertIn('Immune Boosters', cat_names)


class BiExtendedServiceTransactionTest(TestCase):
    def setUp(self):
        self.gw = make_gateway(name='Search Till', gateway_type='MPESA_TILL', gateway_number='BI-SRC')
        self.tx = make_transaction(
            tx_id='BI-SRC-001', amount=Decimal('1500.00'),
            sender_name='Alice Kamau', sender_phone='0711000000',
            gateway=self.gw,
        )

    def test_search_transactions_by_tx_id(self):
        result = BiExtendedService.search_transactions('BI-SRC-001')
        self.assertGreaterEqual(result['total_found'], 1)
        self.assertEqual(result['transactions'][0]['tx_id'], 'BI-SRC-001')

    def test_search_transactions_by_name(self):
        result = BiExtendedService.search_transactions('Alice')
        self.assertGreaterEqual(result['total_found'], 1)

    def test_search_transactions_by_phone(self):
        result = BiExtendedService.search_transactions('0711000000')
        self.assertGreaterEqual(result['total_found'], 1)

    def test_get_transaction_detail_found(self):
        result = BiExtendedService.get_transaction_detail('BI-SRC-001')
        self.assertTrue(result['found'])
        self.assertEqual(result['amount'], 1500.0)
        self.assertEqual(result['sender_name'], 'Alice Kamau')

    def test_get_transaction_detail_not_found(self):
        result = BiExtendedService.get_transaction_detail('NONEXISTENT')
        self.assertFalse(result['found'])

    def test_search_customer_by_name(self):
        result = BiExtendedService.search_customer('Alice')
        self.assertTrue(result['found'])
        self.assertGreaterEqual(result['customers_found'], 1)
        self.assertEqual(result['customers'][0]['name'], 'Alice Kamau')

    def test_search_customer_by_phone(self):
        result = BiExtendedService.search_customer('0711000000')
        self.assertTrue(result['found'])

    def test_search_customer_not_found(self):
        result = BiExtendedService.search_customer('NonExistent')
        self.assertFalse(result['found'])

    def test_get_gateway_breakdown(self):
        result = BiExtendedService.get_gateway_breakdown(today())
        self.assertEqual(result['date'], today().isoformat())
        self.assertGreaterEqual(len(result['gateways']), 1)


class BiExtendedServiceOperationalTest(TestCase):
    def setUp(self):
        self.gw = make_gateway(name='Ops Till', gateway_type='MPESA_TILL', gateway_number='BI-OPS')
        self.tx_pending = make_transaction(
            tx_id='BI-OPS-PEND', amount=Decimal('2000.00'),
            status='PROCESSING', gateway=self.gw,
        )
        self.tx_done = make_transaction(
            tx_id='BI-OPS-DONE', amount=Decimal('3000.00'),
            status='FULFILLED', gateway=self.gw,
            amount_fulfilled=Decimal('3000.00'),
            unique_hash='hash_ops_done',
        )
        self.admin = make_admin(username='biadmin')
        self.processor = make_processor(username='biprocessor')

    def test_get_fulfillment_pipeline(self):
        result = BiExtendedService.get_fulfillment_pipeline()
        self.assertIn('transaction_pipeline', result)
        self.assertIn('combined_order_pipeline', result)
        self.assertGreater(result['total_transactions'], 0)

    def test_get_pending_fulfillments(self):
        result = BiExtendedService.get_pending_fulfillments()
        self.assertGreaterEqual(result['total_pending_transactions'], 1)
        tx_ids = [t['tx_id'] for t in result['pending_transactions']]
        self.assertIn('BI-OPS-PEND', tx_ids)

    def test_get_user_performance_all(self):
        result = BiExtendedService.get_user_performance(None, today())
        self.assertGreaterEqual(result['total_users'], 2)

    def test_get_user_performance_filtered(self):
        result = BiExtendedService.get_user_performance('biprocessor', today())
        self.assertEqual(len(result['users']), 1)
        self.assertEqual(result['users'][0]['username'], 'biprocessor')

    def test_get_combined_orders_summary(self):
        result = BiExtendedService.get_combined_orders_summary(today())
        self.assertEqual(result['date'], today().isoformat())
        self.assertIn('total_orders_created', result)


class BiExtendedServicePeriodTest(TestCase):
    def setUp(self):
        self.gw = make_gateway(name='Period Till', gateway_type='MPESA_TILL', gateway_number='BI-PER')
        self.tx = make_transaction(
            tx_id='BI-PER-TX', amount=Decimal('4000.00'),
            gateway=self.gw, status='FULFILLED',
            amount_fulfilled=Decimal('4000.00'),
            unique_hash='hash_per',
        )

    def test_get_period_revenue(self):
        start = today() - timezone.timedelta(days=1)
        end = today() + timezone.timedelta(days=1)
        result = BiExtendedService.get_period_revenue(start, end)
        self.assertGreaterEqual(result['total_revenue'], 4000.0)
        self.assertGreaterEqual(result['total_transactions'], 1)

    def test_get_period_sales(self):
        start = today() - timezone.timedelta(days=1)
        end = today() + timezone.timedelta(days=1)
        result = BiExtendedService.get_period_sales(start, end)
        self.assertGreaterEqual(result['total_sales'], 0)

    def test_get_period_revenue_vs_sales(self):
        start = today() - timezone.timedelta(days=1)
        end = today() + timezone.timedelta(days=1)
        result = BiExtendedService.get_period_revenue_vs_sales(start, end)
        self.assertIn('total_revenue', result)
        self.assertIn('total_sales', result)
        self.assertIn('fulfillment_rate', result)

    def test_get_month_comparison(self):
        result = BiExtendedService.get_month_comparison()
        self.assertIn('current_period', result)
        self.assertIn('previous_period', result)
        self.assertIn('change', result)

    def test_get_year_comparison(self):
        result = BiExtendedService.get_year_comparison()
        self.assertIn('current_year', result)
        self.assertIn('previous_year', result)
        self.assertIn('change', result)


class BiExtendedServiceProductCompareTest(TestCase):
    def setUp(self):
        self.gw = make_gateway(name='Comp Till', gateway_type='MPESA_TILL', gateway_number='BI-COMP')
        self.product = make_product(
            prod_code='COMP001', prod_name='Compare Product',
            price=Decimal('100.00'), quantity=100,
        )
        self.tx1 = make_transaction(
            tx_id='BI-COMP-1', amount=Decimal('200.00'),
            gateway=self.gw, status='FULFILLED',
            amount_fulfilled=Decimal('200.00'),
            unique_hash='hash_comp1',
        )
        make_line_item(self.tx1, self.product, quantity=2)

    def test_get_product_comparison(self):
        tomorrow = today() + timezone.timedelta(days=1)
        result = BiExtendedService.get_product_comparison('Compare Product', today(), tomorrow)
        self.assertIn('product', result)
        self.assertIn('change', result)
        self.assertIn('quantity_change', result['change'])

    def test_get_product_comparison_not_found(self):
        result = BiExtendedService.get_product_comparison('NonExistent', today(), today())
        self.assertFalse(result['found'])


class BiExtendedServiceRegistrationKitTest(TestCase):
    def setUp(self):
        self.gw = make_gateway(name='Reg Till', gateway_type='MPESA_TILL', gateway_number='BI-REG')
        self.tx = make_transaction(
            tx_id='BI-REG-TX', amount=Decimal('5000.00'),
            gateway=self.gw, status='FULFILLED',
            amount_fulfilled=Decimal('5000.00'),
            is_registration=True,
            unique_hash='hash_reg',
        )
        Transaction.objects.filter(pk=self.tx.pk).update(
            registration_kit_issued=True,
            registration_kit_quantity=3,
            completed_at=timezone.now(),
        )
        self.tx.refresh_from_db()

    def test_get_registration_kits_summary(self):
        start = today() - timezone.timedelta(days=1)
        end = today() + timezone.timedelta(days=1)
        result = BiExtendedService.get_registration_kits_summary(start, end)
        self.assertGreaterEqual(result['total_kits_issued'], 3)
        self.assertGreaterEqual(result['total_value'], 600.0)  # 3 × 200
