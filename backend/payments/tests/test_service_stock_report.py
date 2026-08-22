from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from payments.services.stock_report_service import StockReportService
from payments.services.reconciliation_v2_service import ReconciliationV2Service
from .test_helpers import (
    make_admin, make_product, make_product_line, make_gateway,
    make_transaction, make_line_item, make_daily_stock_reconciliation,
    make_stock_adjustment_item, today,
)


class StockReportServiceTest(TestCase):
    def setUp(self):
        self.line = make_product_line('Test Line')
        self.product_a = make_product(
            prod_code='RPT-A', prod_name='Report Product A',
            price=Decimal('500.00'), quantity=100, product_line=self.line,
        )
        self.product_b = make_product(
            prod_code='RPT-B', prod_name='Report Product B',
            price=Decimal('300.00'), quantity=50, product_line=self.line,
        )
        self.product_c = make_product(
            prod_code='RPT-C', prod_name='Inactive Product',
            price=Decimal('100.00'), quantity=0, is_active=False,
        )

    def test_generate_stock_report_structure(self):
        report = StockReportService.generate_stock_report()
        self.assertIn('summary', report)
        self.assertIn('product_lines', report)
        self.assertIn('all_products', report)

    def test_generate_stock_report_totals(self):
        report = StockReportService.generate_stock_report()
        summary = report['summary']
        self.assertEqual(summary['total_products'], 3)
        self.assertEqual(summary['active_products'], 2)
        self.assertEqual(summary['total_quantity'], 150)
        expected_value = Decimal('500.00') * 100 + Decimal('300.00') * 50
        self.assertEqual(summary['total_value'], expected_value)

    def test_generate_stock_report_for_date(self):
        report = StockReportService.generate_stock_report_for_date(today())
        self.assertIn('summary', report)

    def test_generate_stock_report_with_adjustments(self):
        rec = make_daily_stock_reconciliation(created_by=make_admin())
        make_stock_adjustment_item(
            reconciliation=rec, product=self.product_a,
            opening_stock=100, closing_stock=100,
        )
        report = StockReportService.generate_stock_report_with_adjustments(today())
        self.assertIn('summary', report)
        self.assertIn('adjustments', report)

    def test_generate_stock_report_xlsx(self):
        buffer, filename = StockReportService.generate_stock_report_xlsx()
        self.assertTrue(len(buffer.getvalue()) > 0)
        self.assertTrue(filename.endswith('.xlsx'))

    def test_generate_stock_report_xlsx_with_adjustments(self):
        rec = make_daily_stock_reconciliation(created_by=make_admin())
        make_stock_adjustment_item(
            reconciliation=rec, product=self.product_a,
            opening_stock=100, closing_stock=100,
        )
        buffer, filename = StockReportService.generate_stock_report_xlsx_with_adjustments(today())
        self.assertTrue(len(buffer.getvalue()) > 0)
        self.assertTrue(filename.endswith('.xlsx'))

    def test_generate_stock_report_xlsx_for_date(self):
        buffer, filename = StockReportService.generate_stock_report_xlsx_for_date(today())
        self.assertTrue(len(buffer.getvalue()) > 0)

    def test_stock_status_calculation(self):
        self.assertEqual(self.product_c.stock_status, 'Out of Stock')
        self.product_b.quantity = 5
        self.product_b.reorder_level = 10
        self.assertEqual(self.product_b.stock_status, 'Low Stock')
        self.product_a.quantity = 50
        self.assertEqual(self.product_a.stock_status, 'In Stock')
