import asyncio
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch, MagicMock, AsyncMock
from django.test import TestCase, override_settings
from django.utils import timezone
from payments.bi_telegram_bot import (
    _fmt_kes, _fmt_pct, _arrow, _alert_bell, _is_authorized, _escape_markdown,
    format_briefing, format_revenue, format_sales, format_stock_alerts,
    format_reconciliation, format_compare, format_revenue_vs_sales,
    format_branch_summary, format_merch, format_trend, format_anomaly,
    format_product_sales, format_product_stock, format_top_products,
    format_top_products_by_revenue, format_category_sales, format_stock_by_category,
    format_inventory_value, format_stock_movements, format_search_transactions,
    format_transaction_detail, format_customer, format_pending_fulfillments,
    format_fulfillment_pipeline, format_user_performance, format_combined_orders,
    format_gateway_breakdown, format_period_revenue, format_period_sales,
    format_period_revenue_vs_sales, format_month_comparison, format_year_comparison,
    format_product_sales_trend, format_product_comparison,
    format_registration_kits_summary, format_pv_summary, format_total_cost,
    format_products, format_sales_summary,
    format_reconciliation_deep_dive,
    handle_message, send_telegram_message,
    handle_message_with_media,
)
from payments.services.bi_extended_service import BiExtendedService
from .test_helpers import make_gateway, make_product, make_transaction, make_line_item, today


class TestHelpers(TestCase):
    def test_fmt_kes_int(self):
        self.assertEqual(_fmt_kes(1500), "KES 1,500.00")

    def test_fmt_kes_decimal(self):
        self.assertEqual(_fmt_kes(Decimal('1234.5')), "KES 1,234.50")

    def test_fmt_kes_zero(self):
        self.assertEqual(_fmt_kes(0), "KES 0.00")

    def test_fmt_kes_large(self):
        self.assertEqual(_fmt_kes(1000000), "KES 1,000,000.00")

    def test_fmt_pct(self):
        self.assertEqual(_fmt_pct(75.5), "75.5%")

    def test_fmt_pct_zero(self):
        self.assertEqual(_fmt_pct(0), "0.0%")

    def test_arrow_up(self):
        self.assertEqual(_arrow('up'), '📈')

    def test_arrow_down(self):
        self.assertEqual(_arrow('down'), '📉')

    def test_arrow_flat(self):
        self.assertEqual(_arrow('flat'), '➡️')

    def test_arrow_unknown(self):
        self.assertEqual(_arrow('unknown'), '➡️')

    def test_alert_bell_positive(self):
        self.assertEqual(_alert_bell(100), '🔔')

    def test_alert_bell_zero(self):
        self.assertEqual(_alert_bell(0), '')

    def test_is_authorized_allowed(self):
        with override_settings(TELEGRAM_ALLOWED_USER_IDS=[123]):
            self.assertTrue(_is_authorized(123))

    def test_is_authorized_denied(self):
        with override_settings(TELEGRAM_ALLOWED_USER_IDS=[123]):
            self.assertFalse(_is_authorized(456))

    def test_is_authorized_empty_whitelist(self):
        with override_settings(TELEGRAM_ALLOWED_USER_IDS=[]):
            self.assertTrue(_is_authorized(999))

    def test_escape_markdown_no_underscore(self):
        self.assertEqual(_escape_markdown("hello world"), "hello world")

    def test_escape_markdown_with_underscore(self):
        self.assertEqual(_escape_markdown("PAYBILL_PDQ"), r"PAYBILL\_PDQ")

    def test_escape_markdown_multiple(self):
        self.assertEqual(_escape_markdown("A_B_C_D"), r"A\_B\_C\_D")


class TestFormatBriefing(TestCase):
    def test_briefing_with_all_sections(self):
        data = {
            'date': '2026-06-18',
            'summary': {
                'total_revenue': 50000.0, 'total_sales': 45000.0,
                'fulfillment_rate': 90.0, 'transaction_count': 25,
                'avg_transaction_value': 2000.0, 'gap': 5000.0,
            },
            'revenue_buckets': {
                'PAYBILL_PDQ': {'revenue': 30000.0, 'sales': 28000.0, 'gap': 2000.0, 'fulfillment_rate': 93.3, 'alert': None},
                'TILL': {'revenue': 10000.0, 'sales': 9000.0, 'gap': 1000.0, 'fulfillment_rate': 90.0, 'alert': None},
                'MERCH': {'revenue': 5000.0, 'sales': 5000.0, 'gap': 0.0, 'fulfillment_rate': 100.0, 'alert': None},
                'OTHER': {'revenue': 5000.0, 'sales': 3000.0, 'gap': 2000.0, 'fulfillment_rate': 60.0, 'alert': '🔔'},
            },
            'unused_paybill_pdq': {'amount': 0, 'count': 0},
            'credit_lost_paybill_pdq': {'amount': 500.0, 'count': 2},
            'stock_alerts': {
                'summary': '2 low stock, 1 out of stock',
                'total_stock_value': 500000.0,
                'out_of_stock_products': [{'name': 'Vitamin C', 'code': 'VITC001'}],
                'low_stock_products': [{'name': 'Zaminocal', 'code': 'ZAM001', 'quantity': 5, 'reorder_level': 10}],
            },
            'reconciliation': {'is_balanced': True, 'x_value': 30000.0, 'y_value': 30000.0, 'result': 0.0},
            'merchandise': {'fulfilled_revenue': 5000.0, 'fulfilled_items': 10, 'pending_orders': 2},
            'registration_kits': {'kits_issued': 0, 'total_value': 0},
            'vs_yesterday': {'revenue_direction': 'up', 'revenue_change_pct': 12.5},
            'trend_7d': {'total_revenue': 350000.0, 'daily_average': 50000.0, 'growth_rate_pct': 5.2},
            'anomalies': {'anomaly_count': 0, 'anomalies': []},
        }
        result = format_briefing(data)
        self.assertIn('Daily Briefing', result)
        self.assertIn('KES 50,000.00', result)
        self.assertIn('12.5%', result)
        self.assertNotIn('UNUSED PAYBILL', result)
        self.assertIn('CREDIT LOST', result)

    def test_briefing_with_unused_and_kits(self):
        data = {
            'date': '2026-06-18',
            'summary': {
                'total_revenue': 0, 'total_sales': 0, 'fulfillment_rate': 0,
                'transaction_count': 0, 'avg_transaction_value': 0, 'gap': 0,
            },
            'revenue_buckets': {
                'PAYBILL_PDQ': {'revenue': 0, 'sales': 0, 'gap': 0, 'fulfillment_rate': 0, 'alert': None},
                'TILL': {'revenue': 0, 'sales': 0, 'gap': 0, 'fulfillment_rate': 0, 'alert': None},
                'MERCH': {'revenue': 0, 'sales': 0, 'gap': 0, 'fulfillment_rate': 0, 'alert': None},
                'OTHER': {'revenue': 0, 'sales': 0, 'gap': 0, 'fulfillment_rate': 0, 'alert': None},
            },
            'unused_paybill_pdq': {'amount': 15000.0, 'count': 3},
            'credit_lost_paybill_pdq': {'amount': 0, 'count': 0},
            'stock_alerts': {'summary': 'All stocked', 'total_stock_value': 0, 'out_of_stock_products': [], 'low_stock_products': []},
            'reconciliation': {'is_balanced': False, 'x_value': 0, 'y_value': 0, 'result': 0},
            'merchandise': {'fulfilled_revenue': 0, 'fulfilled_items': 0, 'pending_orders': 0},
            'registration_kits': {'kits_issued': 5, 'total_value': 10000.0},
            'vs_yesterday': {'revenue_direction': 'down', 'revenue_change_pct': -5.0},
            'trend_7d': {'total_revenue': 0, 'daily_average': 0, 'growth_rate_pct': 0},
            'anomalies': {'anomaly_count': 2, 'anomalies': [
                {'date': '2026-05-21', 'revenue': 15400.0, 'z_score': 2.22},
            ]},
        }
        result = format_briefing(data)
        self.assertIn('UNUSED PAYBILL', result)
        self.assertIn('REGISTRATION KITS', result)
        self.assertIn('NOT Balanced', result)
        self.assertIn('ANOMALIES', result)


class TestFormatters(TestCase):
    def test_format_revenue(self):
        data = {
            'date': '2026-06-18',
            'buckets': {
                'PAYBILL_PDQ': {'amount': 30000.0, 'count': 10},
                'TILL': {'amount': 10000.0, 'count': 5},
                'MERCH': {'amount': 5000.0, 'count': 3},
                'OTHER': {'amount': 2000.0, 'count': 1},
            },
            'total': 47000.0,
        }
        result = format_revenue(data)
        self.assertIn('Revenue', result)
        self.assertIn('KES 47,000.00', result)

    def test_format_sales(self):
        data = {
            'date': '2026-06-18',
            'buckets': {
                'PAYBILL_PDQ': {'amount': 25000.0, 'count': 8},
                'TILL': {'amount': 8000.0, 'count': 4},
                'OTHER': {'amount': 1000.0, 'count': 1},
            },
            'total': 34000.0,
        }
        result = format_sales(data)
        self.assertIn('Fulfillment', result)
        self.assertIn('KES 34,000.00', result)

    def test_format_stock_alerts_with_products(self):
        data = {
            'in_stock_count': 45, 'low_stock_count': 3, 'out_of_stock_count': 2,
            'total_stock_value': 500000.0,
            'out_of_stock_products': [{'name': 'Vit C'}, {'name': 'Iron'}],
            'low_stock_products': [{'name': 'Zam', 'quantity': 3}, {'name': 'Cal', 'quantity': 5}, {'name': 'Mag', 'quantity': 2}],
        }
        result = format_stock_alerts(data)
        self.assertIn('Stock Alerts', result)
        self.assertIn('✅', result)
        self.assertIn('🚫', result)

    def test_format_stock_alerts_empty(self):
        data = {
            'in_stock_count': 47, 'low_stock_count': 0, 'out_of_stock_count': 0,
            'total_stock_value': 500000.0,
            'out_of_stock_products': [],
            'low_stock_products': [],
        }
        result = format_stock_alerts(data)
        self.assertIn('Stock Alerts', result)
        self.assertIn('In Stock:   47', result)
        self.assertNotIn('🚫 Vit', result)  # no individual product listed under out of stock

    def test_format_reconciliation_balanced(self):
        data = {
            'is_balanced': True, 'x_value': 50000.0, 'y_value': 50000.0, 'result': 0.0,
            'x_formula': {'mpesa_paybill': 40000.0, 'unused': 0, 'pdq': 10000.0, 'previous': 0, 'sales': 0},
            'y_formula': {'till': 40000.0, 'credit': 0, 'kits': 0},
        }
        result = format_reconciliation(data)
        self.assertIn('Balanced', result)

    def test_format_reconciliation_unbalanced(self):
        data = {
            'is_balanced': False, 'x_value': 50000.0, 'y_value': 48000.0, 'result': 2000.0,
            'x_formula': {}, 'y_formula': {},
        }
        result = format_reconciliation(data)
        self.assertIn('NOT Balanced', result)

    def test_format_compare(self):
        data = {
            'metric': 'revenue_vs_sales', 'period1': {'date': '2026-06-17', 'value': 40000.0},
            'period2': {'date': '2026-06-18', 'value': 50000.0},
            'absolute_change': 10000.0, 'percentage_change': 25.0,
        }
        result = format_compare(data)
        self.assertIn('Comparison', result)
        self.assertIn('+25.0%', result)

    def test_format_revenue_vs_sales(self):
        data = {
            'date': '2026-06-18', 'total_revenue': 50000.0, 'total_sales': 45000.0,
            'gap': 5000.0, 'fulfillment_rate': 90.0,
            'unused_paybill_pdq': {'amount': 2000.0},
            'credit_lost_paybill_pdq': {'amount': 500.0},
            'buckets': {'PAYBILL_PDQ': {'revenue': 30000.0, 'sales': 28000.0, 'fulfillment_rate': 93.3}},
        }
        result = format_revenue_vs_sales(data)
        self.assertIn('Revenue vs Sales', result)
        self.assertIn('90.0%', result)

    def test_format_branch_summary(self):
        data = {
            'date': '2026-06-18', 'total_revenue': 80000.0, 'total_sales': 75000.0,
            'branches': [
                {'name': 'Main Shop', 'status': 'ok', 'revenue': 50000.0, 'sales': 47000.0},
                {'name': 'Kitengela', 'status': 'error'},
            ],
        }
        result = format_branch_summary(data)
        self.assertIn('Branch Performance', result)
        self.assertIn('Main Shop', result)
        self.assertIn('Kitengela', result)
        self.assertIn('Unreachable', result)

    def test_format_merch(self):
        data = {'fulfilled_revenue': 15000.0, 'fulfilled_items': 30, 'fulfilled_orders': 10, 'pending_orders': 3, 'total_orders': 13}
        result = format_merch(data)
        self.assertIn('Merchandise', result)
        self.assertIn('KES 15,000.00', result)

    def test_format_trend(self):
        data = {
            'period_days': 30, 'total_revenue': 500000.0, 'daily_average': 16666.67,
            'min_daily': 5000.0, 'max_daily': 50000.0, 'growth_rate_pct': 3.5,
            'data_points': [{'date': '2026-06-18', 'revenue': 50000.0}],
        }
        result = format_trend(data)
        self.assertIn('Trend', result)
        self.assertIn('3.5%', result)

    def test_format_anomaly(self):
        data = {
            'period_days': 30, 'mean': 20000.0, 'std_dev': 5000.0, 'anomaly_count': 2,
            'anomalies': [
                {'date': '2026-05-21', 'revenue': 45000.0, 'z_score': 2.5},
                {'date': '2026-05-22', 'value': 3000.0, 'z_score': -3.0},
            ],
        }
        result = format_anomaly(data)
        self.assertIn('Anomaly', result)
        self.assertIn('z=2.5', result)
        self.assertIn('z=-3.0', result)

    def test_format_product_sales_found(self):
        data = {
            'found': True, 'date': '2026-06-18', 'total_quantity_sold': 10,
            'total_revenue': 5000.0, 'total_cost': 3000.0, 'total_pv': 200.0,
            'products': [{'name': 'Zaminocal', 'code': 'ZAM001', 'current_stock': 40, 'price': 500.0}],
        }
        result = format_product_sales(data)
        self.assertIn('Product Sales', result)
        self.assertIn('Zaminocal', result)

    def test_format_product_sales_not_found(self):
        result = format_product_sales({'found': False, 'message': 'Product not found'})
        self.assertIn('Product not found', result)

    def test_format_product_stock_found(self):
        data = {
            'found': True, 'total_stock_value': 20000.0,
            'products': [
                {'name': 'Zaminocal', 'code': 'ZAM001', 'quantity': 40, 'reorder_level': 10,
                 'stock_status': 'IN_STOCK', 'price': 500.0, 'stock_value': 20000.0, 'category': 'Bone Care'},
            ],
        }
        result = format_product_stock(data)
        self.assertIn('Product Stock', result)
        self.assertIn('✅', result)
        self.assertIn('Bone Care', result)

    def test_format_product_stock_not_found(self):
        result = format_product_stock({'found': False, 'message': 'Not found'})
        self.assertIn('Not found', result)

    def test_format_top_products(self):
        data = {
            'date': '2026-06-18', 'total_products_sold': 5,
            'products': [
                {'name': 'Zaminocal', 'quantity_sold': 20, 'revenue': 10000.0, 'category': 'Bone'},
                {'name': 'Vit C', 'quantity_sold': 15, 'revenue': 4500.0, 'category': 'Immune'},
                {'name': 'Iron', 'quantity_sold': 10, 'revenue': 3000.0},
                {'name': 'Mag', 'quantity_sold': 5, 'revenue': 1500.0},
                {'name': 'Cal', 'quantity_sold': 3, 'revenue': 900.0},
            ],
        }
        result = format_top_products(data)
        self.assertIn('🥇', result)
        self.assertIn('🥈', result)
        self.assertIn('🥉', result)

    def test_format_top_products_by_revenue(self):
        data = {
            'date': '2026-06-18', 'total_products_sold': 3,
            'products': [
                {'name': 'Zaminocal', 'revenue': 10000.0, 'quantity_sold': 20, 'category': 'Bone'},
                {'name': 'Vit C', 'revenue': 4500.0, 'quantity_sold': 15},
            ],
        }
        result = format_top_products_by_revenue(data)
        self.assertIn('Top Products by Revenue', result)

    def test_format_category_sales_found(self):
        data = {
            'found': True, 'date': '2026-06-18', 'total_quantity_sold': 30,
            'total_revenue': 15000.0, 'total_cost': 9000.0, 'total_pv': 600.0,
            'categories': [{'name': 'Bone Care'}, {'name': 'Immune'}],
        }
        result = format_category_sales(data)
        self.assertIn('Category Sales', result)

    def test_format_category_sales_not_found(self):
        result = format_category_sales({'found': False, 'message': 'Category not found'})
        self.assertIn('Category not found', result)

    def test_format_stock_by_category(self):
        data = {
            'total_categories': 2, 'total_products': 10, 'total_stock_value': 100000.0,
            'categories': [
                {'name': 'Bone Care', 'product_count': 5, 'total_stock_units': 100, 'total_value': 50000.0},
                {'name': 'Immune', 'product_count': 5, 'total_stock_units': 80, 'total_value': 50000.0},
            ],
        }
        result = format_stock_by_category(data)
        self.assertIn('Stock by Category', result)
        self.assertIn('Bone Care', result)

    def test_format_inventory_value(self):
        data = {'total_products': 47, 'total_stock_units': 5000, 'total_value_at_retail': 2000000.0, 'total_value_at_cost': 1500000.0, 'total_pv': 50000.0}
        result = format_inventory_value(data)
        self.assertIn('Inventory Value', result)
        self.assertIn('KES 2,000,000.00', result)

    def test_format_stock_movements(self):
        data = {
            'found': True, 'days': 7, 'product_query': 'Zaminocal', 'total_movements': 5,
            'by_type': {'SALE': {'count': 3, 'total_change': -6}, 'ADJUSTMENT': {'count': 2, 'total_change': 10}},
            'movements': [
                {'type': 'SALE', 'product': 'Zaminocal', 'quantity_change': -2, 'performed_by': 'admin'},
            ],
        }
        result = format_stock_movements(data)
        self.assertIn('Stock Movements', result)
        self.assertIn('Zaminocal', result)

    def test_format_stock_movements_not_found(self):
        result = format_stock_movements({'found': False, 'message': 'No product found', 'days': 7})
        self.assertIn('No product found', result)

    def test_format_search_transactions(self):
        data = {
            'query': 'Alice', 'total_found': 1,
            'transactions': [{
                'tx_id': 'TX001', 'amount': 1000.0, 'status': 'FULFILLED',
                'status_display': 'Fulfilled', 'sender_name': 'Alice',
                'sender_phone': '0712345678', 'timestamp': '2026-06-18T10:00:00',
                'gateway_type': 'MPESA_TILL',
            }],
        }
        result = format_search_transactions(data)
        self.assertIn('Transaction Search', result)
        self.assertIn('TX001', result)
        self.assertIn('Alice', result)

    def test_format_transaction_detail_found(self):
        data = {
            'found': True, 'tx_id': 'TX001', 'amount': 5000.0, 'amount_fulfilled': 5000.0,
            'remaining': 0.0, 'status': 'FULFILLED', 'status_display': 'Fulfilled',
            'gateway': 'Till 1', 'gateway_type': 'MPESA_TILL',
            'sender_name': 'Alice', 'sender_phone': '0712345678',
            'timestamp': '2026-06-18T10:00:00', 'completed_by': 'admin',
            'total_cost': 3000.0, 'total_pv': 200.0,
            'line_items': [{'product_name': 'Zaminocal', 'quantity': 2, 'unit_price': 2500.0, 'line_total': 5000.0}],
        }
        result = format_transaction_detail(data)
        self.assertIn('Transaction: TX001', result)
        self.assertIn('Zaminocal', result)

    def test_format_transaction_detail_not_found(self):
        result = format_transaction_detail({'found': False, 'message': 'Not found'})
        self.assertIn('Not found', result)

    def test_format_customer_found(self):
        data = {
            'found': True, 'query': 'Alice', 'customers_found': 1,
            'customers': [{
                'name': 'Alice Kamau', 'phone': '0712345678',
                'total_spent': 50000.0, 'total_fulfilled': 48000.0,
                'transaction_count': 10, 'fulfillment_rate': 96.0,
                'last_purchase': '2026-06-18',
            }],
        }
        result = format_customer(data)
        self.assertIn('Customer Search', result)
        self.assertIn('Alice Kamau', result)

    def test_format_customer_not_found(self):
        result = format_customer({'found': False, 'message': 'Not found'})
        self.assertIn('Not found', result)

    def test_format_pending_fulfillments(self):
        data = {
            'total_pending_transactions': 5, 'total_pending_combined_orders': 2,
            'pending_transactions': [
                {'tx_id': 'TX001', 'remaining': 2000.0, 'status_display': 'Processing', 'days_old': 3, 'sender_name': 'Alice'},
            ],
            'pending_combined_orders': [
                {'id': 'CO001', 'remaining': 5000.0, 'status': 'ACTIVE', 'days_old': 2},
            ],
        }
        result = format_pending_fulfillments(data)
        self.assertIn('Pending Fulfillments', result)
        self.assertIn('TX001', result)
        self.assertIn('CO001', result)

    def test_format_fulfillment_pipeline(self):
        data = {
            'transaction_pipeline': {'NOT_PROCESSED': 10, 'PROCESSING': 5, 'FULFILLED': 20},
            'combined_order_pipeline': {'ACTIVE': 3, 'COMPLETED': 7},
            'total_transactions': 35, 'total_combined_orders': 10,
        }
        result = format_fulfillment_pipeline(data)
        self.assertIn('Fulfillment Pipeline', result)
        self.assertIn('NOT_PROCESSED: 10', result)

    def test_format_user_performance(self):
        data = {
            'date': '2026-06-18',
            'users': [
                {'username': 'alice', 'role': 'PROCESSOR', 'total_actions': 15,
                 'transactions_processed': 10, 'transactions_activated': 5,
                 'transactions_completed': 3, 'items_scanned': 20,
                 'combined_orders_created': 2},
                {'username': 'bob', 'role': 'ISSUER', 'total_actions': 0,
                 'transactions_processed': 0, 'transactions_activated': 0,
                 'transactions_completed': 0, 'items_scanned': 0,
                 'combined_orders_created': 0},
            ],
        }
        result = format_user_performance(data)
        self.assertIn('User Performance', result)
        self.assertIn('alice', result)
        self.assertNotIn('bob', result)

    def test_format_user_performance_empty(self):
        result = format_user_performance({'date': '2026-06-18', 'users': []})
        self.assertIn('No users found', result)

    def test_format_combined_orders(self):
        data = {
            'date': '2026-06-18', 'total_orders_created': 5,
            'total_amount': 50000.0, 'total_amount_fulfilled': 45000.0,
            'status_breakdown': {'ACTIVE': 3, 'COMPLETED': 2},
            'orders': [{'id': 'CO001', 'total_amount': 10000.0, 'status': 'ACTIVE'}],
        }
        result = format_combined_orders(data)
        self.assertIn('Combined Orders', result)

    def test_format_gateway_breakdown(self):
        data = {
            'date': '2026-06-18',
            'gateways': [
                {'type': 'MPESA_TILL', 'name': 'Till 1', 'count': 10, 'revenue': 50000.0, 'sales': 45000.0},
            ],
        }
        result = format_gateway_breakdown(data)
        self.assertIn('Gateway Breakdown', result)
        self.assertIn('MPESA_TILL', result)

    def test_format_period_revenue(self):
        data = {
            'start_date': '2026-06-01', 'end_date': '2026-06-18',
            'total_revenue': 500000.0, 'total_transactions': 250,
            'daily_average': 27777.78, 'days_in_range': 18,
            'buckets': {'PAYBILL_PDQ': 300000.0, 'TILL': 200000.0},
        }
        result = format_period_revenue(data)
        self.assertIn('Revenue', result)
        self.assertIn('KES 27,777.78', result)

    def test_format_period_sales(self):
        data = {
            'start_date': '2026-06-01', 'end_date': '2026-06-18',
            'total_sales': 450000.0, 'total_transactions': 200,
            'daily_average': 25000.0,
        }
        result = format_period_sales(data)
        self.assertIn('Sales', result)

    def test_format_period_revenue_vs_sales(self):
        data = {
            'start_date': '2026-06-01', 'end_date': '2026-06-18',
            'total_revenue': 500000.0, 'total_sales': 450000.0,
            'gap': 50000.0, 'fulfillment_rate': 90.0, 'transaction_count': 250,
        }
        result = format_period_revenue_vs_sales(data)
        self.assertIn('Revenue vs Sales', result)
        self.assertIn('90.0%', result)

    def test_format_month_comparison(self):
        data = {
            'current_period': {'start': '2026-06-01', 'end': '2026-06-18', 'days': 18, 'revenue': 500000.0, 'sales': 450000.0, 'fulfillment_rate': 90.0},
            'previous_period': {'start': '2026-05-01', 'end': '2026-05-31', 'days': 31, 'revenue': 400000.0, 'sales': 350000.0, 'fulfillment_rate': 87.5},
            'change': {'revenue_pct': 25.0, 'sales_pct': 28.6, 'revenue': 100000.0, 'sales': 100000.0},
        }
        result = format_month_comparison(data)
        self.assertIn('Month-over-Month', result)
        self.assertIn('+25.0%', result)

    def test_format_year_comparison(self):
        data = {
            'current_year': 2026, 'previous_year': 2025,
            'current_period': {'start': '2026-01-01', 'end': '2026-06-18', 'days': 169, 'revenue': 3000000.0, 'sales': 2700000.0, 'fulfillment_rate': 90.0},
            'previous_period': {'start': '2025-01-01', 'end': '2025-12-31', 'days': 365, 'revenue': 5000000.0, 'sales': 4500000.0, 'fulfillment_rate': 90.0},
            'change': {'revenue_pct': -40.0, 'sales_pct': -40.0, 'revenue_change': -2000000.0, 'sales_change': -1800000.0},
        }
        result = format_year_comparison(data)
        self.assertIn('Year-over-Year', result)
        self.assertIn('-40.0%', result)

    def test_format_product_sales_trend(self):
        data = {
            'found': True, 'period_days': 30, 'total_quantity': 50, 'total_revenue': 25000.0,
            'daily_average_qty': 1.67, 'daily_average_revenue': 833.33,
            'days_with_sales': 15, 'product_info': [{'name': 'Zaminocal', 'code': 'ZAM001'}],
            'data_points': [{'date': '2026-06-18', 'quantity': 2, 'revenue': 1000.0}],
        }
        result = format_product_sales_trend(data)
        self.assertIn('Product Sales Trend', result)
        self.assertIn('Zaminocal', result)

    def test_format_product_comparison_found(self):
        data = {
            'found': True, 'product': [{'name': 'Zaminocal', 'code': 'ZAM001'}],
            'date1': {'date': '2026-06-17', 'quantity': 5, 'revenue': 2500.0},
            'date2': {'date': '2026-06-18', 'quantity': 10, 'revenue': 5000.0},
            'change': {'quantity_change': 5, 'revenue_change': 2500.0, 'quantity_pct': 100.0, 'revenue_pct': 100.0},
        }
        result = format_product_comparison(data)
        self.assertIn('Product Comparison', result)
        self.assertIn('+100.0%', result)

    def test_format_product_comparison_not_found(self):
        result = format_product_comparison({'found': False, 'message': 'Not found'})
        self.assertIn('Not found', result)

    def test_format_registration_kits_summary(self):
        data = {
            'start_date': '2026-05-18', 'end_date': '2026-06-18',
            'total_kits_issued': 10, 'total_value': 20000.0, 'total_transactions': 8,
            'daily_breakdown': {'2026-06-18': {'kits': 3, 'count': 2}},
        }
        result = format_registration_kits_summary(data)
        self.assertIn('Registration Kits', result)
        self.assertIn('10', result)

    def test_format_registration_kits_summary_no_daily(self):
        data = {
            'start_date': '2026-05-18', 'end_date': '2026-06-18',
            'total_kits_issued': 0, 'total_value': 0, 'total_transactions': 0,
            'daily_breakdown': {},
        }
        result = format_registration_kits_summary(data)
        self.assertIn('Registration Kits', result)

    def test_format_pv_summary(self):
        data = {
            'date': '2026-06-18', 'total_pv': 5000.0, 'total_items': 100,
            'per_bucket': {'PAYBILL_PDQ': 3000.0, 'TILL': 2000.0},
        }
        result = format_pv_summary(data)
        self.assertIn('PV Summary', result)
        self.assertIn('KES 5,000.00', result)

    def test_format_total_cost(self):
        data = {'date': '2026-06-18', 'total_cost_of_goods_sold': 25000.0, 'total_items_sold': 50}
        result = format_total_cost(data)
        self.assertIn('Cost of Goods Sold', result)
        self.assertIn('KES 25,000.00', result)

    def test_format_products_with_data(self):
        data = {
            'total_products': 2,
            'filters': {'stock_status': 'LOW_STOCK', 'category': None, 'search': None},
            'products': [
                {'name': 'Vit C', 'code': 'VITC', 'category': 'Supplements', 'quantity': 5,
                 'price': 500.0, 'stock_status': 'LOW_STOCK'},
                {'name': 'Iron', 'code': 'IRN', 'category': 'Supplements', 'quantity': 0,
                 'price': 400.0, 'stock_status': 'OUT_OF_STOCK'},
            ],
        }
        result = format_products(data)
        self.assertIn('Products', result)
        self.assertIn('Vit C', result)
        self.assertIn('🚫', result)
        self.assertIn('⚠️', result)
        self.assertIn('Supplements', result)

    def test_format_products_empty(self):
        data = {'total_products': 0, 'filters': {}, 'products': []}
        result = format_products(data)
        self.assertIn('Products', result)
        self.assertIn('No products match', result)

    def test_format_products_with_more_than_30(self):
        products = []
        for i in range(35):
            products.append({'name': f'Prod{i}', 'code': f'P{i}', 'category': 'Test',
                           'quantity': 10, 'price': 100.0, 'stock_status': 'IN_STOCK'})
        data = {'total_products': 35, 'filters': {}, 'products': products}
        result = format_products(data)
        self.assertIn('5 more products', result)

    def test_format_sales_summary_with_data(self):
        data = {
            'date': '2026-06-18',
            'unique_products': 3,
            'total_quantity_sold': 15,
            'total_revenue': 7500.0,
            'total_cost': 3000.0,
            'total_pv': 1200.0,
            'top_products': [
                {'name': 'Vit C', 'quantity_sold': 10, 'revenue': 5000.0},
                {'name': 'Zinc', 'quantity_sold': 5, 'revenue': 2500.0},
            ],
        }
        result = format_sales_summary(data)
        self.assertIn('Sales Summary', result)
        self.assertIn('KES 7,500.00', result)
        self.assertIn('Vit C', result)
        self.assertIn('10 x KES', result)

    def test_format_sales_summary_no_sales(self):
        data = {
            'date': '2026-06-18',
            'unique_products': 0,
            'total_quantity_sold': 0,
            'total_revenue': 0.0,
            'total_cost': 0.0,
            'total_pv': 0.0,
            'top_products': [],
        }
        result = format_sales_summary(data)
        self.assertIn('No sales data', result)


class TestHandleMessage(TestCase):
    def _run(self, text, user_id=None):
        return asyncio.run(handle_message(text, user_id=user_id))

    def test_unauthorized_user(self):
        with override_settings(TELEGRAM_ALLOWED_USER_IDS=[999]):
            result = self._run('/revenue', user_id=123)
        self.assertIn('Unauthorized', result)

    def test_help_command(self):
        result = self._run('/help')
        self.assertIn('BI Copilot', result)

    def test_start_command(self):
        result = self._run('/start')
        self.assertIn('BI Copilot', result)

    def test_unknown_command(self):
        result = self._run('/nonexistent')
        self.assertIn('Unknown command', result)

    def test_empty_text(self):
        result = self._run('')
        self.assertIsNotNone(result)

    def test_free_form_text_with_llm_failure(self):
        result = self._run('some random text')
        self.assertIsNotNone(result)

    def test_blank_text(self):
        result = self._run('   ')
        self.assertIsNotNone(result)

    def test_stock_command(self):
        with patch('payments.bi_telegram_bot.BiCoreService.get_stock_alerts') as mock:
            mock.return_value = {
                'in_stock_count': 45, 'low_stock_count': 2, 'out_of_stock_count': 0,
                'total_stock_value': 500000.0, 'out_of_stock_products': [],
                'low_stock_products': [{'name': 'Zam', 'quantity': 3}],
            }
            result = self._run('/stock')
        self.assertIn('Stock Alerts', result)

    def test_inventory_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_inventory_value') as mock:
            mock.return_value = {
                'total_products': 47, 'total_stock_units': 5000,
                'total_value_at_retail': 2000000.0, 'total_value_at_cost': 1500000.0,
                'total_pv': 50000.0,
            }
            result = self._run('/inventory')
        self.assertIn('Inventory Value', result)

    def test_pending_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_pending_fulfillments') as mock:
            mock.return_value = {
                'total_pending_transactions': 3, 'total_pending_combined_orders': 1,
                'pending_transactions': [], 'pending_combined_orders': [],
            }
            result = self._run('/pending')
        self.assertIn('Pending Fulfillments', result)

    def test_pipeline_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_fulfillment_pipeline') as mock:
            mock.return_value = {
                'transaction_pipeline': {'NP': 5}, 'combined_order_pipeline': {},
                'total_transactions': 5, 'total_combined_orders': 0,
            }
            result = self._run('/pipeline')
        self.assertIn('Fulfillment Pipeline', result)

    def test_month_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_month_comparison') as mock:
            mock.return_value = {
                'current_period': {'start': '2026-06-01', 'end': '2026-06-18', 'days': 18, 'revenue': 500000.0, 'sales': 450000.0, 'fulfillment_rate': 90.0},
                'previous_period': {'start': '2026-05-01', 'end': '2026-05-31', 'days': 31, 'revenue': 400000.0, 'sales': 350000.0, 'fulfillment_rate': 87.5},
                'change': {'revenue_pct': 25.0, 'sales_pct': 28.6, 'revenue': 100000.0, 'sales': 100000.0},
            }
            result = self._run('/month')
        self.assertIn('Month-over-Month', result)

    def test_year_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_year_comparison') as mock:
            mock.return_value = {
                'current_year': 2026, 'previous_year': 2025,
                'current_period': {'start': '2026-01-01', 'end': '2026-06-18', 'days': 169, 'revenue': 3000000.0, 'sales': 2700000.0, 'fulfillment_rate': 90.0},
                'previous_period': {'start': '2025-01-01', 'end': '2025-12-31', 'days': 365, 'revenue': 5000000.0, 'sales': 4500000.0, 'fulfillment_rate': 90.0},
                'change': {'revenue_pct': -40.0, 'sales_pct': -40.0, 'revenue_change': -2000000.0, 'sales_change': -1800000.0},
            }
            result = self._run('/year')
        self.assertIn('Year-over-Year', result)

    def test_stock_by_category_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_stock_by_category') as mock:
            mock.return_value = {
                'total_categories': 2, 'total_products': 10, 'total_stock_value': 100000.0,
                'categories': [],
            }
            result = self._run('/stock_by_category')
        self.assertIn('Stock by Category', result)

    def test_gateways_command_no_date(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_gateway_breakdown') as mock:
            mock.return_value = {'date': '2026-06-18', 'gateways': []}
            result = self._run('/gateways')
        self.assertIn('Gateway Breakdown', result)

    def test_product_stock_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_product_stock') as mock:
            mock.return_value = {
                'found': True, 'total_stock_value': 20000.0,
                'products': [{'name': 'Zam', 'code': 'ZAM001', 'quantity': 40, 'reorder_level': 10, 'stock_status': 'IN_STOCK', 'price': 500.0, 'stock_value': 20000.0}],
            }
            result = self._run('/product_stock Zam')
        self.assertIn('Product Stock', result)

    def test_product_stock_command_no_query(self):
        result = self._run('/product_stock')
        self.assertIn('Unknown command', result)  # stripped input, no space → falls through

    def test_combined_command_no_date(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_combined_orders_summary') as mock:
            mock.return_value = {'date': '2026-06-18', 'total_orders_created': 0, 'total_amount': 0, 'total_amount_fulfilled': 0, 'status_breakdown': {}, 'orders': []}
            result = self._run('/combined')
        self.assertIn('Combined Orders', result)

    def test_compare_command_invalid_date(self):
        result = self._run('/compare notadate 2026-06-18')
        self.assertIn('Invalid date', result)

    def test_txn_detail_command_no_query(self):
        result = self._run('/txn_detail')
        self.assertIn('Unknown command', result)  # stripped input, no space → falls through

    def test_txn_detail_command_with_id(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_transaction_detail') as mock:
            mock.return_value = {
                'found': True, 'tx_id': 'TX001', 'amount': 5000.0, 'amount_fulfilled': 5000.0,
                'remaining': 0.0, 'status': 'FULFILLED', 'status_display': 'Fulfilled',
                'gateway': 'Till 1', 'gateway_type': 'MPESA_TILL',
                'sender_name': 'Alice', 'sender_phone': '0712345678',
                'timestamp': '2026-06-18T10:00:00', 'completed_by': 'admin',
                'total_cost': 3000.0, 'total_pv': 200.0,
                'line_items': [{'product_name': 'Zaminocal', 'quantity': 2, 'unit_price': 2500.0, 'line_total': 5000.0}],
            }
            result = self._run('/txn_detail TX001')
        self.assertIn('Transaction: TX001', result)

    def test_customer_command_no_query(self):
        result = self._run('/customer')
        self.assertIn('Unknown command', result)  # stripped input, no space → falls through

    def test_movements_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_stock_movements') as mock:
            mock.return_value = {'found': True, 'days': 7, 'product_query': 'Zam', 'total_movements': 0, 'by_type': {}, 'movements': []}
            result = self._run('/movements Zam')
        self.assertIn('Stock Movements', result)

    def test_product_sales_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_product_sales') as mock:
            mock.return_value = {'found': True, 'date': '2026-06-18', 'total_quantity_sold': 0, 'total_revenue': 0, 'total_cost': 0, 'total_pv': 0, 'products': []}
            result = self._run('/product_sales Zam')
        self.assertIn('Product Sales', result)

    def test_product_sales_command_invalid_date(self):
        result = self._run('/product_sales Zam notadate')
        self.assertIn('Invalid date', result)

    def test_vs_command(self):
        with patch('payments.bi_telegram_bot.BiCoreService.get_revenue_vs_sales') as mock:
            mock.return_value = {'date': '2026-06-18', 'total_revenue': 0, 'total_sales': 0, 'gap': 0, 'fulfillment_rate': 0, 'unused_paybill_pdq': {'amount': 0}, 'credit_lost_paybill_pdq': {'amount': 0}, 'buckets': {}}
            result = self._run('/vs 2026-06-18')
        self.assertIn('Revenue vs Sales', result)

    def test_vs_command_invalid_date(self):
        result = self._run('/vs notadate')
        self.assertIn('Invalid date', result)

    def test_briefing_command(self):
        with patch('payments.bi_telegram_bot.BiBriefingService.generate_daily_briefing') as mock:
            mock.return_value = {
                'date': '2026-06-18',
                'summary': {'total_revenue': 50000.0, 'total_sales': 45000.0, 'fulfillment_rate': 90.0, 'transaction_count': 25, 'avg_transaction_value': 2000.0, 'gap': 5000.0},
                'revenue_buckets': {
                    'PAYBILL_PDQ': {'revenue': 30000.0, 'sales': 28000.0, 'gap': 2000.0, 'fulfillment_rate': 93.3, 'alert': None},
                    'TILL': {'revenue': 10000.0, 'sales': 9000.0, 'gap': 1000.0, 'fulfillment_rate': 90.0, 'alert': None},
                    'MERCH': {'revenue': 5000.0, 'sales': 5000.0, 'gap': 0, 'fulfillment_rate': 100.0, 'alert': None},
                    'OTHER': {'revenue': 5000.0, 'sales': 3000.0, 'gap': 2000.0, 'fulfillment_rate': 60.0, 'alert': None},
                },
                'unused_paybill_pdq': {'amount': 0, 'count': 0},
                'credit_lost_paybill_pdq': {'amount': 0, 'count': 0},
                'stock_alerts': {'summary': 'All stocked', 'total_stock_value': 500000.0, 'out_of_stock_products': [], 'low_stock_products': []},
                'reconciliation': {'is_balanced': True, 'x_value': 30000.0, 'y_value': 30000.0, 'result': 0.0},
                'merchandise': {'fulfilled_revenue': 5000.0, 'fulfilled_items': 10, 'pending_orders': 2},
                'registration_kits': {'kits_issued': 0, 'total_value': 0},
                'vs_yesterday': {'revenue_direction': 'up', 'revenue_change_pct': 12.5},
                'trend_7d': {'total_revenue': 350000.0, 'daily_average': 50000.0, 'growth_rate_pct': 5.2},
                'anomalies': {'anomaly_count': 0, 'anomalies': []},
            }
            result = self._run('/briefing')
        self.assertIn('Daily Briefing', result)

    def test_briefing_command_invalid_date(self):
        result = self._run('/briefing notadate')
        self.assertIn('Invalid date', result)

    def test_user_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_user_performance') as mock:
            mock.return_value = {'date': '2026-06-18', 'users': []}
            result = self._run('/user')
        self.assertIn('No users found', result)

    def test_kits_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_registration_kits_summary') as mock:
            mock.return_value = {'start_date': '2026-05-18', 'end_date': '2026-06-18', 'total_kits_issued': 0, 'total_value': 0, 'total_transactions': 0, 'daily_breakdown': {}}
            result = self._run('/kits')
        self.assertIn('Registration Kits', result)

    def test_txn_search_with_item(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.search_transactions') as mock:
            mock.return_value = {
                'query': 'TX001', 'total_found': 1,
                'transactions': [{'tx_id': 'TX001', 'amount': 1000.0, 'status': 'FULFILLED', 'status_display': 'Fulfilled', 'sender_name': 'Alice', 'sender_phone': '0712345678', 'timestamp': '2026-06-18T10:00:00', 'gateway_type': 'MPESA_TILL'}],
            }
            result = self._run('/txn TX001')
        self.assertIn('Transaction Search', result)
        self.assertIn('TX001', result)

    def test_gateway_breakdown_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_gateway_breakdown') as mock:
            mock.return_value = {
                'date': '2026-06-18', 'gateways': [{'type': 'MPESA_TILL', 'name': 'Till 1', 'count': 5, 'revenue': 25000.0, 'sales': 23000.0}],
            }
            result = self._run('/gateways 2026-06-18')
        self.assertIn('Gateway Breakdown', result)
        self.assertIn('MPESA_TILL', result)

    def test_category_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_category_sales') as mock:
            mock.return_value = {'found': True, 'date': '2026-06-18', 'total_quantity_sold': 0, 'total_revenue': 0, 'total_cost': 0, 'total_pv': 0, 'categories': []}
            result = self._run('/category Bone')
        self.assertIn('Category Sales', result)

    def test_category_command_invalid_date(self):
        result = self._run('/category Bone notadate')
        self.assertIn('Invalid date', result)

    def test_top_command_with_arg(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_top_products') as mock:
            mock.return_value = {'date': '2026-06-18', 'total_products_sold': 0, 'products': []}
            result = self._run('/top 5')
        self.assertIn('Top Products', result)

    def test_top_revenue_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_top_products_by_revenue') as mock:
            mock.return_value = {'date': '2026-06-18', 'total_products_sold': 0, 'products': []}
            result = self._run('/top_revenue 5')
        self.assertIn('Top Products by Revenue', result)

    def test_pv_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_pv_summary') as mock:
            mock.return_value = {'date': '2026-06-18', 'total_pv': 0, 'total_items': 0, 'per_bucket': {}}
            result = self._run('/pv')
        self.assertIn('PV Summary', result)

    def test_cost_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_total_cost') as mock:
            mock.return_value = {'date': '2026-06-18', 'total_cost_of_goods_sold': 0, 'total_items_sold': 0}
            result = self._run('/cost')
        self.assertIn('Cost of Goods Sold', result)

    def test_merch_command(self):
        with patch('payments.bi_telegram_bot.BiCoreService.get_merch_fulfillment') as mock:
            mock.return_value = {'fulfilled_revenue': 0, 'fulfilled_items': 0, 'fulfilled_orders': 0, 'pending_orders': 0, 'total_orders': 0}
            result = self._run('/merch')
        self.assertIn('Merchandise', result)

    def test_recon_command(self):
        with patch('payments.bi_telegram_bot.BiCoreService.get_reconciliation') as mock:
            mock.return_value = {'is_balanced': True, 'x_value': 0, 'y_value': 0, 'result': 0, 'x_formula': {}, 'y_formula': {}}
            result = self._run('/recon')
        self.assertIn('Reconciliation', result)

    def test_branches_command(self):
        with patch('payments.bi_telegram_bot.BiBranchAggregator.aggregate_branch_revenue') as mock:
            mock.return_value = {'date': '2026-06-18', 'total_revenue': 0, 'total_sales': 0, 'branches': []}
            result = self._run('/branches')
        self.assertIn('Branch Performance', result)

    def test_anomalies_command(self):
        with patch('payments.bi_telegram_bot.BiAnomalyService.check_revenue_anomaly') as mock:
            mock.return_value = {'period_days': 30, 'mean': 0, 'std_dev': 0, 'anomaly_count': 0, 'anomalies': []}
            result = self._run('/anomalies')
        self.assertIn('Anomaly Detection', result)

    def test_trend_command(self):
        with patch('payments.bi_telegram_bot.BiTrendService.revenue_trend') as mock:
            mock.return_value = {
                'period_days': 30, 'total_revenue': 0, 'daily_average': 0,
                'min_daily': 0, 'max_daily': 0, 'data_points': [],
            }
            result = self._run('/trend')
        self.assertIn('Trend', result)

    def test_revenue_command(self):
        with patch('payments.bi_telegram_bot.BiCoreService.get_revenue_by_bucket') as mock:
            mock.return_value = {
                'date': '2026-06-18',
                'buckets': {'PAYBILL_PDQ': {'amount': 0, 'count': 0}, 'TILL': {'amount': 0, 'count': 0}, 'MERCH': {'amount': 0, 'count': 0}, 'OTHER': {'amount': 0, 'count': 0}},
                'total': 0,
            }
            result = self._run('/revenue')
        self.assertIn('Revenue', result)

    def test_sales_command(self):
        with patch('payments.bi_telegram_bot.BiCoreService.get_fulfillment_by_gateway') as mock:
            mock.return_value = {
                'date': '2026-06-18',
                'buckets': {'PAYBILL_PDQ': {'amount': 0, 'count': 0}, 'TILL': {'amount': 0, 'count': 0}, 'OTHER': {'amount': 0, 'count': 0}},
                'total': 0,
            }
            result = self._run('/sales')
        self.assertIn('Fulfillment', result)

    def test_products_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_all_products') as mock:
            mock.return_value = {
                'total_products': 1,
                'filters': {},
                'products': [{'name': 'Vit C', 'code': 'VITC', 'stock_status': 'IN_STOCK',
                            'quantity': 20, 'price': 500.0, 'category': 'Supplements'}],
            }
            result = self._run('/products')
        self.assertIn('Products', result)
        self.assertIn('Vit C', result)

    def test_products_command_with_filters(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_all_products') as mock:
            mock.return_value = {
                'total_products': 0,
                'filters': {'stock_status': 'OUT_OF_STOCK', 'category': None, 'search': None},
                'products': [],
            }
            result = self._run('/products out_of_stock')
        self.assertIn('No products match', result)

    def test_summary_command(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_daily_sales_summary') as mock:
            mock.return_value = {
                'date': '2026-06-18',
                'unique_products': 2,
                'total_quantity_sold': 10,
                'total_revenue': 5000.0,
                'total_cost': 2000.0,
                'total_pv': 800.0,
                'top_products': [{'name': 'Vit C', 'quantity_sold': 6, 'revenue': 3000.0}],
            }
            result = self._run('/summary')
        self.assertIn('Sales Summary', result)
        self.assertIn('KES 5,000.00', result)

    def test_summary_command_no_sales(self):
        with patch('payments.bi_telegram_bot.BiExtendedService.get_daily_sales_summary') as mock:
            mock.return_value = {
                'date': '2026-06-18',
                'unique_products': 0,
                'total_quantity_sold': 0,
                'total_revenue': 0.0,
                'total_cost': 0.0,
                'total_pv': 0.0,
                'top_products': [],
            }
            result = self._run('/summary')
        self.assertIn('No sales data', result)


class TestFormatReconciliationDeepDive(TestCase):
    def test_deep_dive_balanced(self):
        data = {
            'date': '2026-06-19',
            'is_balanced': True,
            'severity': 'BALANCED',
            'x_value': 0.0,
            'y_value': 0.0,
            'result': 0.0,
            'components': {
                'mpesa_paybill': {'amount': 1000.0, 'count': 1, 'transactions': []},
                'unused': {'amount': 0.0, 'count': 0, 'transactions': []},
                'pdq': {'amount': 0.0, 'count': 0, 'transactions': []},
                'previous': {'amount': 0.0, 'count': 0, 'transactions': []},
                'till': {'amount': 0.0, 'count': 0, 'transactions': []},
                'credit': {'amount': 0.0, 'count': 0, 'transactions': []},
                'kits': {'amount': 0.0, 'count': 0, 'transactions': []},
                'sales': {'amount': 0.0, 'count': 0, 'transactions': []},
            },
            'issues': [],
        }
        result = format_reconciliation_deep_dive(data)
        self.assertIn('Deep Dive', result)
        self.assertIn('Balanced', result)
        self.assertIn('No issues found', result)

    def test_deep_dive_with_issues(self):
        data = {
            'date': '2026-06-19',
            'is_balanced': False,
            'severity': 'MAJOR',
            'x_value': 1000.0,
            'y_value': -800.0,
            'result': 200.0,
            'components': {
                'mpesa_paybill': {'amount': 1000.0, 'count': 1, 'transactions': []},
                'unused': {'amount': 300.0, 'count': 2, 'transactions': [{'tx_id': 'T001', 'amount': 150.0}, {'tx_id': 'T002', 'amount': 150.0}]},
                'pdq': {'amount': 0.0, 'count': 0, 'transactions': []},
                'previous': {'amount': 0.0, 'count': 0, 'transactions': []},
                'till': {'amount': 200.0, 'count': 1, 'transactions': []},
                'credit': {'amount': 100.0, 'count': 1, 'transactions': [{'tx_id': 'T003', 'amount': 500.0, 'remaining': 100.0}]},
                'kits': {'amount': 0.0, 'count': 0, 'transactions': []},
                'sales': {'amount': 1000.0, 'count': 3, 'transactions': []},
            },
            'issues': [
                {'type': 'UNFULFILLED', 'severity': 'MAJOR', 'count': 2, 'total_amount': 300.0,
                 'transactions': [{'tx_id': 'T001', 'amount': 150.0}, {'tx_id': 'T002', 'amount': 150.0}],
                 'recommendation': 'Process or cancel.', 'combined_orders': []},
                {'type': 'PARTIALLY_FULFILLED', 'severity': 'MINOR', 'count': 1, 'total_amount': 100.0,
                 'transactions': [{'tx_id': 'T003', 'amount': 500.0, 'remaining': 100.0}],
                 'recommendation': 'Lost forever.', 'combined_orders': []},
            ],
        }
        result = format_reconciliation_deep_dive(data)
        self.assertIn('NOT Balanced', result)
        self.assertIn('Unfulfilled', result)
        self.assertIn('Partially Fulfilled', result)
        self.assertIn('T001', result)
        self.assertIn('T003', result)
        self.assertIn('MAJOR', result)

    def test_deep_dive_empty_data(self):
        result = format_reconciliation_deep_dive({})
        self.assertIn('Deep Dive', result)

    def test_deep_dive_with_combined_orders(self):
        data = {
            'date': '2026-06-19',
            'is_balanced': False,
            'severity': 'MINOR',
            'x_value': 0.0,
            'y_value': 0.0,
            'result': 0.0,
            'components': {
                'mpesa_paybill': {'amount': 0.0, 'count': 0, 'transactions': []},
                'unused': {'amount': 0.0, 'count': 0, 'transactions': []},
                'pdq': {'amount': 0.0, 'count': 0, 'transactions': []},
                'previous': {'amount': 0.0, 'count': 0, 'transactions': []},
                'till': {'amount': 0.0, 'count': 0, 'transactions': []},
                'credit': {'amount': 0.0, 'count': 0, 'transactions': []},
                'kits': {'amount': 0.0, 'count': 0, 'transactions': []},
                'sales': {'amount': 0.0, 'count': 0, 'transactions': []},
            },
            'issues': [
                {'type': 'COMBINED_ORDER_MISMATCH', 'severity': 'MINOR', 'count': 1, 'total_amount': 500.0,
                 'combined_orders': [{'combined_order_id': 'CMB-001', 'remaining': 500.0, 'status': 'PARTIALLY_FULFILLED'}],
                 'recommendation': 'Check fulfillment.', 'transactions': []},
            ],
        }
        result = format_reconciliation_deep_dive(data)
        self.assertIn('Combined Order Mismatch', result)
        self.assertIn('CMB-001', result)


class TestSendTelegramMessage(TestCase):
    @override_settings(TELEGRAM_BOT_TOKEN='')
    def test_no_token(self):
        result = asyncio.run(send_telegram_message('123', 'test'))
        self.assertFalse(result)

    @override_settings(TELEGRAM_BOT_TOKEN='test:token')
    def test_escape_markdown_in_message(self):
        result = asyncio.run(send_telegram_message('123', 'PAYBILL_PDQ text'))
        self.assertFalse(result)  # no network, but underscores should be escaped


class TestHandleMessageWithMedia(TestCase):
    def test_no_flags_routes_to_handle_message(self):
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/revenue 2026-01-01')
        )
        self.assertIn('PAYBILL_PDQ', result)
        self.assertIsNone(chart)
        self.assertIsNone(xlsx)

    def test_chart_flag_revenue_returns_chart(self):
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/revenue 2026-01-01 --chart')
        )
        self.assertIn('PAYBILL_PDQ', result)
        self.assertIsNotNone(chart)
        self.assertGreater(len(chart.getvalue()), 100)

    def test_chart_flag_stock_returns_chart(self):
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/stock --chart')
        )
        self.assertIsNotNone(chart)
        self.assertGreater(len(chart.getvalue()), 100)

    def test_chart_flag_trend_returns_chart(self):
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/trend 7 --chart')
        )
        self.assertIsNotNone(chart)
        self.assertGreater(len(chart.getvalue()), 100)

    def test_chart_flag_top_returns_chart(self):
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/top 5 2026-01-01 --chart')
        )
        self.assertIsNotNone(chart)
        self.assertGreater(len(chart.getvalue()), 100)

    def test_chart_flag_vs_returns_chart(self):
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/vs 2026-01-01 --chart')
        )
        self.assertIsNotNone(chart)
        self.assertGreater(len(chart.getvalue()), 100)

    def test_chart_flag_month_returns_chart(self):
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/month --chart')
        )
        self.assertIsNotNone(chart)
        self.assertGreater(len(chart.getvalue()), 100)

    def test_chart_flag_year_returns_chart(self):
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/year --chart')
        )
        self.assertIsNotNone(chart)
        self.assertGreater(len(chart.getvalue()), 100)

    def test_chart_flag_gateways_returns_chart(self):
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/gateways 2026-01-01 --chart')
        )
        self.assertIsNotNone(chart)
        self.assertGreater(len(chart.getvalue()), 100)

    def test_chart_flag_briefing_returns_chart(self):
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/briefing 2026-01-01 --chart')
        )
        self.assertIsNotNone(chart)
        self.assertGreater(len(chart.getvalue()), 100)

    def test_all_flag_returns_chart(self):
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/revenue 2026-01-01 --all')
        )
        self.assertIn('PAYBILL_PDQ', result)
        self.assertIsNotNone(chart)
        self.assertIsNone(xlsx)

    @patch('payments.services.bi_reconciliation_deep_dive_service.BiReconciliationDeepDiveService.get_deep_dive')
    @patch('payments.services.bi_reconciliation_deep_dive_service.BiReconciliationDeepDiveService.generate_chart')
    @patch('payments.services.bi_reconciliation_deep_dive_service.BiReconciliationDeepDiveService.generate_xlsx')
    def test_recon_deep_chart_and_xlsx(self, mock_xlsx, mock_chart, mock_deep):
        from io import BytesIO
        mock_deep.return_value = {'status': 'BALANCED', 'date': '2026-01-01', 'issues': []}
        mock_chart.return_value = BytesIO(b'fake_chart_data')
        mock_xlsx.return_value = (BytesIO(b'fake_xlsx_data'), 'recon_deep_2026-01-01.xlsx')
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/recon_deep 2026-01-01 --all')
        )
        self.assertIsNotNone(chart)
        self.assertIsNotNone(xlsx)
        self.assertIn('xlsx', name)

    @patch('payments.services.bi_reconciliation_deep_dive_service.BiReconciliationDeepDiveService.get_deep_dive')
    @patch('payments.services.bi_reconciliation_deep_dive_service.BiReconciliationDeepDiveService.generate_chart')
    def test_recon_deep_chart_only(self, mock_chart, mock_deep):
        from io import BytesIO
        mock_deep.return_value = {'status': 'BALANCED', 'date': '2026-01-01', 'issues': []}
        mock_chart.return_value = BytesIO(b'fake_chart_data')
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/recon_deep 2026-01-01 --chart')
        )
        self.assertIsNotNone(chart)
        self.assertIsNone(xlsx)

    @patch('payments.services.bi_reconciliation_deep_dive_service.BiReconciliationDeepDiveService.get_deep_dive')
    @patch('payments.services.bi_reconciliation_deep_dive_service.BiReconciliationDeepDiveService.generate_xlsx')
    def test_recon_deep_xlsx_only(self, mock_xlsx, mock_deep):
        from io import BytesIO
        mock_deep.return_value = {'status': 'BALANCED', 'date': '2026-01-01', 'issues': []}
        mock_xlsx.return_value = (BytesIO(b'fake_xlsx_data'), 'recon_deep_2026-01-01.xlsx')
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/recon_deep 2026-01-01 --xlsx')
        )
        self.assertIsNone(chart)
        self.assertIsNotNone(xlsx)
        self.assertIn('xlsx', name)

    def test_unknown_command_with_chart_still_returns_text(self):
        result, chart, xlsx, name = asyncio.run(
            handle_message_with_media('/unknown_cmd --chart')
        )
        self.assertIn('Unknown command', result)
        self.assertIsNone(chart)
