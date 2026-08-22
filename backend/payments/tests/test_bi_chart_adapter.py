from io import BytesIO
from django.test import TestCase
from payments.services.bi_chart_adapter import BiChartAdapter


class TestBiChartAdapter(TestCase):

    def test_for_revenue_returns_bytesio(self):
        data = {
            'buckets': {
                'PAYBILL_PDQ': {'total_revenue': 5000, 'transaction_count': 10},
                'TILL': {'total_revenue': 3000, 'transaction_count': 5},
                'MERCH': {'total_revenue': 1000, 'transaction_count': 2},
                'OTHER': {'total_revenue': 500, 'transaction_count': 1},
            }
        }
        buf = BiChartAdapter.for_revenue(data)
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_for_revenue_empty_buckets(self):
        buf = BiChartAdapter.for_revenue({'buckets': {}})
        self.assertIsInstance(buf, BytesIO)

    def test_for_fulfillment_returns_bytesio(self):
        data = {
            'buckets': {
                'PAYBILL_PDQ': {'total_fulfilled': 4000, 'fulfillment_count': 8},
                'TILL': {'total_fulfilled': 2000, 'fulfillment_count': 4},
                'OTHER': {'total_fulfilled': 500, 'fulfillment_count': 1},
            }
        }
        buf = BiChartAdapter.for_fulfillment(data)
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_for_fulfillment_empty(self):
        buf = BiChartAdapter.for_fulfillment({'buckets': {}})
        self.assertIsInstance(buf, BytesIO)

    def test_for_trend_returns_bytesio(self):
        data = {
            'trend': [
                {'date': '2026-01-01', 'revenue': 1000, 'sales': 5},
                {'date': '2026-01-02', 'revenue': 1500, 'sales': 8},
                {'date': '2026-01-03', 'revenue': 1200, 'sales': 6},
            ]
        }
        buf = BiChartAdapter.for_trend(data)
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_for_trend_empty(self):
        buf = BiChartAdapter.for_trend({'trend': []})
        self.assertIsInstance(buf, BytesIO)

    def test_for_top_products_returns_bytesio(self):
        data = {
            'products': [
                {'name': 'Product A', 'quantity_sold': 10, 'total_revenue': 5000},
                {'name': 'Product B', 'quantity_sold': 8, 'total_revenue': 4000},
                {'name': 'Product C', 'quantity_sold': 5, 'total_revenue': 2500},
            ]
        }
        buf = BiChartAdapter.for_top_products(data)
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_for_top_products_empty(self):
        buf = BiChartAdapter.for_top_products({'products': []})
        self.assertIsInstance(buf, BytesIO)

    def test_for_revenue_vs_sales_returns_bytesio(self):
        data = {
            'buckets': {
                'PAYBILL_PDQ': {'total_revenue': 5000, 'total_fulfilled': 4000},
                'TILL': {'total_revenue': 3000, 'total_fulfilled': 2500},
                'OTHER': {'total_revenue': 1000, 'total_fulfilled': 900},
            }
        }
        buf = BiChartAdapter.for_revenue_vs_sales(data)
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_for_revenue_vs_sales_empty(self):
        buf = BiChartAdapter.for_revenue_vs_sales({'buckets': {}})
        self.assertIsInstance(buf, BytesIO)

    def test_for_month_comparison_returns_bytesio(self):
        data = {
            'current_month': {
                'total_revenue': 50000,
                'total_sales': 200,
            },
            'previous_month': {
                'total_revenue': 45000,
                'total_sales': 180,
            },
            'current_label': 'Jun 2026',
            'previous_label': 'May 2026',
        }
        buf = BiChartAdapter.for_month_comparison(data)
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_for_month_comparison_empty(self):
        buf = BiChartAdapter.for_month_comparison({})
        self.assertIsInstance(buf, BytesIO)

    def test_for_year_comparison_returns_bytesio(self):
        data = {
            'current_year': {
                'total_revenue': 500000,
                'total_sales': 2000,
            },
            'previous_year': {
                'total_revenue': 450000,
                'total_sales': 1800,
            },
            'current_label': '2026',
            'previous_label': '2025',
        }
        buf = BiChartAdapter.for_year_comparison(data)
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_for_year_comparison_empty(self):
        buf = BiChartAdapter.for_year_comparison({})
        self.assertIsInstance(buf, BytesIO)

    def test_for_stock_alerts_returns_bytesio(self):
        data = {
            'in_stock_count': 45,
            'low_stock_count': 12,
            'out_of_stock_count': 5,
            'total_stock_value': 50000,
            'out_of_stock_products': [{'name': 'Product X', 'quantity': 0}],
            'low_stock_products': [{'name': 'Product Y', 'quantity': 3}],
        }
        buf = BiChartAdapter.for_stock_alerts(data)
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_for_stock_alerts_zero_values(self):
        data = {
            'in_stock_count': 0,
            'low_stock_count': 0,
            'out_of_stock_count': 0,
            'total_stock_value': 0,
            'out_of_stock_products': [],
            'low_stock_products': [],
        }
        buf = BiChartAdapter.for_stock_alerts(data)
        self.assertIsInstance(buf, BytesIO)

    def test_for_gateway_breakdown_returns_bytesio(self):
        data = {
            'breakdown': [
                {'gateway': 'MPESA Till', 'revenue': 30000, 'fulfillment': 25000},
                {'gateway': 'MPESA Paybill', 'revenue': 20000, 'fulfillment': 18000},
                {'gateway': 'PDQ', 'revenue': 10000, 'fulfillment': 9000},
            ]
        }
        buf = BiChartAdapter.for_gateway_breakdown(data)
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_for_gateway_breakdown_empty(self):
        buf = BiChartAdapter.for_gateway_breakdown({'breakdown': []})
        self.assertIsInstance(buf, BytesIO)

    def test_for_briefing_returns_bytesio(self):
        data = {
            'revenue_by_bucket': {
                'buckets': {
                    'PAYBILL_PDQ': {'total_revenue': 8000, 'transaction_count': 15},
                    'TILL': {'total_revenue': 4000, 'transaction_count': 8},
                    'MERCH': {'total_revenue': 2000, 'transaction_count': 3},
                    'OTHER': {'total_revenue': 500, 'transaction_count': 1},
                }
            },
            'fulfillment_by_gateway': {
                'buckets': {
                    'PAYBILL_PDQ': {'total_fulfilled': 7000, 'fulfillment_count': 12},
                    'TILL': {'total_fulfilled': 3000, 'fulfillment_count': 6},
                    'OTHER': {'total_fulfilled': 1000, 'fulfillment_count': 2},
                }
            },
            'revenue_vs_sales': {
                'buckets': {
                    'PAYBILL_PDQ': {'total_revenue': 8000, 'total_fulfilled': 7000},
                    'TILL': {'total_revenue': 4000, 'total_fulfilled': 3000},
                    'OTHER': {'total_revenue': 2500, 'total_fulfilled': 1000},
                }
            },
            'stock_alerts': {
                'in_stock': 45,
                'low_stock': 12,
                'out_of_stock': 5,
            },
        }
        buf = BiChartAdapter.for_briefing(data)
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_for_briefing_minimal(self):
        buf = BiChartAdapter.for_briefing({})
        self.assertIsInstance(buf, BytesIO)

    def test_for_any_routes_correctly(self):
        data = {'buckets': {'PAYBILL_PDQ': {'total_revenue': 100, 'transaction_count': 1}}}
        buf = BiChartAdapter.for_any('get_revenue_by_bucket', data)
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_for_any_unknown_tool(self):
        buf = BiChartAdapter.for_any('unknown_tool', {})
        self.assertIsNone(buf)

    def test_for_any_recon_deep_returns_none(self):
        buf = BiChartAdapter.for_any('get_reconciliation_deep_dive', {})
        self.assertIsNone(buf)
