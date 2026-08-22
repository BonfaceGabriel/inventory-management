from io import BytesIO
from django.test import TestCase
from utils.chart_generator import ChartGenerator


class TestChartGenerator(TestCase):
    def test_bar_chart_returns_bytesio(self):
        data = {
            'labels': ['A', 'B', 'C'],
            'datasets': [{'label': 'Series 1', 'values': [10, 20, 30]}],
        }
        buf = ChartGenerator.bar_chart(data, title='Test', ylabel='KES')
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_bar_chart_empty_data(self):
        buf = ChartGenerator.bar_chart({'labels': [], 'datasets': []})
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 50)

    def test_bar_chart_multiple_datasets(self):
        data = {
            'labels': ['X', 'Y', 'Z'],
            'datasets': [
                {'label': 'A', 'values': [1, 2, 3]},
                {'label': 'B', 'values': [4, 5, 6]},
            ],
        }
        buf = ChartGenerator.bar_chart(data)
        self.assertIsInstance(buf, BytesIO)

    def test_line_chart_returns_bytesio(self):
        data = {
            'labels': ['Mon', 'Tue', 'Wed'],
            'datasets': [{'label': 'Revenue', 'values': [100, 200, 150]}],
        }
        buf = ChartGenerator.line_chart(data, title='Trend', ylabel='KES')
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_line_chart_empty_data(self):
        buf = ChartGenerator.line_chart({'labels': [], 'datasets': []})
        self.assertIsInstance(buf, BytesIO)

    def test_pie_chart_returns_bytesio(self):
        data = {
            'labels': ['Paybill', 'Till', 'PDQ'],
            'values': [5000, 3000, 2000],
        }
        buf = ChartGenerator.pie_chart(data, title='Gateway Split')
        self.assertIsInstance(buf, BytesIO)
        self.assertGreater(len(buf.getvalue()), 100)

    def test_pie_chart_empty_data(self):
        buf = ChartGenerator.pie_chart({'labels': [], 'values': []})
        self.assertIsInstance(buf, BytesIO)

    def test_bar_chart_custom_colors(self):
        data = {
            'labels': ['A', 'B'],
            'datasets': [{'label': 'S', 'values': [1, 2]}],
        }
        buf = ChartGenerator.bar_chart(data, colors=['#FF0000', '#00FF00'])
        self.assertIsInstance(buf, BytesIO)
