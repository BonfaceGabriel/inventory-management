from decimal import Decimal
from io import BytesIO
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from payments.services.bi_reconciliation_deep_dive_service import BiReconciliationDeepDiveService


class TestSeverityClassification(TestCase):
    def test_balanced(self):
        self.assertEqual(BiReconciliationDeepDiveService._classify_severity(0.0), 'BALANCED')

    def test_minor(self):
        self.assertEqual(BiReconciliationDeepDiveService._classify_severity(50.0), 'MINOR')

    def test_major(self):
        self.assertEqual(BiReconciliationDeepDiveService._classify_severity(500.0), 'MAJOR')

    def test_critical(self):
        self.assertEqual(BiReconciliationDeepDiveService._classify_severity(5000.0), 'CRITICAL')

    def test_negative_values(self):
        self.assertEqual(BiReconciliationDeepDiveService._classify_severity(-50.0), 'MINOR')
        self.assertEqual(BiReconciliationDeepDiveService._classify_severity(-500.0), 'MAJOR')
        self.assertEqual(BiReconciliationDeepDiveService._classify_severity(-5000.0), 'CRITICAL')


class TestCleanForIssue(TestCase):
    def test_clean_with_all_fields(self):
        result = BiReconciliationDeepDiveService._clean_for_issue([
            {'tx_id': 'T001', 'amount': Decimal('100'), 'remaining': Decimal('50'),
             'status': 'PARTIALLY_FULFILLED', 'sender_name': 'John'},
        ])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['tx_id'], 'T001')
        self.assertEqual(result[0]['amount'], 100.0)
        self.assertEqual(result[0]['remaining'], 50.0)

    def test_clean_empty(self):
        self.assertEqual(BiReconciliationDeepDiveService._clean_for_issue([]), [])

    def test_clean_none(self):
        self.assertEqual(BiReconciliationDeepDiveService._clean_for_issue(None), [])


class TestBuildComponents(TestCase):
    def test_build_components_schema(self):
        calc = {
            'mpesa_paybill': {'amount': Decimal('1000'), 'count': 2, 'transactions': [{'tx_id': 'T1', 'amount': Decimal('500'), 'status': 'FULFILLED', 'sender_name': 'A'}]},
            'unused': {'amount': Decimal('0'), 'count': 0, 'transactions': []},
            'pdq': {'amount': Decimal('500'), 'count': 1, 'transactions': []},
            'previous': {'amount': Decimal('200'), 'count': 1, 'transactions': []},
            'till': {'amount': Decimal('300'), 'count': 2, 'transactions': []},
            'credit': {'amount': Decimal('0'), 'count': 0, 'transactions': [], 'combined_orders': []},
            'kits': {'amount': Decimal('400'), 'count': 2, 'transactions': []},
            'sales': {'amount': Decimal('1600'), 'count': 5, 'transactions': [], 'by_gateway': {'PAYBILL_PDQ': {'amount': Decimal('1000'), 'count': 3}}},
        }
        comp = BiReconciliationDeepDiveService._build_components(calc)
        self.assertEqual(comp['mpesa_paybill']['amount'], 1000.0)
        self.assertEqual(comp['mpesa_paybill']['count'], 2)
        self.assertEqual(comp['unused']['amount'], 0.0)
        self.assertEqual(comp['sales']['by_gateway']['PAYBILL_PDQ']['amount'], 1000.0)
        self.assertEqual(comp['credit']['combined_orders'], [])

    def test_build_components_sales_no_by_gateway(self):
        calc = {
            'mpesa_paybill': {'amount': Decimal('0'), 'count': 0, 'transactions': []},
            'unused': {'amount': Decimal('0'), 'count': 0, 'transactions': []},
            'pdq': {'amount': Decimal('0'), 'count': 0, 'transactions': []},
            'previous': {'amount': Decimal('0'), 'count': 0, 'transactions': []},
            'till': {'amount': Decimal('0'), 'count': 0, 'transactions': []},
            'credit': {'amount': Decimal('0'), 'count': 0, 'transactions': []},
            'kits': {'amount': Decimal('0'), 'count': 0, 'transactions': []},
            'sales': {'amount': Decimal('0'), 'count': 0, 'transactions': []},
        }
        comp = BiReconciliationDeepDiveService._build_components(calc)
        self.assertEqual(comp['sales']['by_gateway'], {})


class TestGenerateChart(TestCase):
    def test_chart_returns_bytesio(self):
        data = {
            'date': '2026-06-19',
            'is_balanced': True,
            'x_value': 0.0,
            'y_value': 0.0,
            'result': 0.0,
            'severity': 'BALANCED',
            'components': {
                'mpesa_paybill': {'amount': 1000.0, 'count': 2, 'transactions': []},
                'unused': {'amount': 0.0, 'count': 0, 'transactions': []},
                'pdq': {'amount': 500.0, 'count': 1, 'transactions': []},
                'previous': {'amount': 200.0, 'count': 1, 'transactions': []},
                'till': {'amount': 300.0, 'count': 2, 'transactions': []},
                'credit': {'amount': 0.0, 'count': 0, 'transactions': []},
                'kits': {'amount': 400.0, 'count': 2, 'transactions': []},
                'sales': {'amount': 1600.0, 'count': 5, 'transactions': []},
            },
        }
        buf = BiReconciliationDeepDiveService.generate_chart(data)
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_chart_with_unbalanced_data(self):
        data = {
            'date': '2026-06-19',
            'is_balanced': False,
            'x_value': 1000.0,
            'y_value': -950.0,
            'result': 50.0,
            'severity': 'MINOR',
            'components': {
                'mpesa_paybill': {'amount': 5000.0, 'count': 5, 'transactions': []},
                'unused': {'amount': 500.0, 'count': 2, 'transactions': []},
                'pdq': {'amount': 1000.0, 'count': 1, 'transactions': []},
                'previous': {'amount': 0.0, 'count': 0, 'transactions': []},
                'till': {'amount': 500.0, 'count': 1, 'transactions': []},
                'credit': {'amount': 200.0, 'count': 1, 'transactions': []},
                'kits': {'amount': 800.0, 'count': 4, 'transactions': []},
                'sales': {'amount': 5000.0, 'count': 3, 'transactions': []},
            },
        }
        buf = BiReconciliationDeepDiveService.generate_chart(data)
        self.assertIsInstance(buf, BytesIO)


class TestGenerateXlsx(TestCase):
    def test_xlsx_returns_tuple(self):
        data = {
            'date': '2026-06-19',
            'is_balanced': True,
            'x_value': 0.0,
            'y_value': 0.0,
            'result': 0.0,
            'severity': 'BALANCED',
            'components': {
                'mpesa_paybill': {'amount': 1000.0, 'count': 2, 'transactions': [{'tx_id': 'T1', 'amount': 500.0, 'status': 'FULFILLED', 'sender_name': 'John'}]},
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
        result = BiReconciliationDeepDiveService.generate_xlsx(data)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        buf, filename = result
        self.assertIsInstance(buf, BytesIO)
        self.assertIsInstance(filename, str)
        self.assertIn('2026-06-19', filename)
        self.assertIn('.xlsx', filename)

    def test_xlsx_with_issues(self):
        data = {
            'date': '2026-06-19',
            'is_balanced': False,
            'x_value': 500.0,
            'y_value': -400.0,
            'result': 100.0,
            'severity': 'MAJOR',
            'components': {
                'mpesa_paybill': {'amount': 1000.0, 'count': 2, 'transactions': []},
                'unused': {'amount': 0.0, 'count': 0, 'transactions': []},
                'pdq': {'amount': 0.0, 'count': 0, 'transactions': []},
                'previous': {'amount': 0.0, 'count': 0, 'transactions': []},
                'till': {'amount': 0.0, 'count': 0, 'transactions': []},
                'credit': {'amount': 0.0, 'count': 0, 'transactions': []},
                'kits': {'amount': 0.0, 'count': 0, 'transactions': []},
                'sales': {'amount': 0.0, 'count': 0, 'transactions': []},
            },
            'issues': [
                {'type': 'UNFULFILLED', 'severity': 'MAJOR', 'count': 3, 'total_amount': 4500.0,
                 'recommendation': 'Process these.', 'transactions': [], 'combined_orders': []},
            ],
        }
        result = BiReconciliationDeepDiveService.generate_xlsx(data)
        buf, filename = result
        self.assertGreater(len(buf.getvalue()), 200)
