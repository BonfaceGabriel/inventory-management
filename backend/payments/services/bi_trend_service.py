from datetime import timedelta
from decimal import Decimal
from typing import Dict, List
from statistics import mean, stdev

from django.utils import timezone

from payments.services.bi_core_service import BiCoreService


class BiTrendService:
    @staticmethod
    def revenue_trend(days: int = 30) -> Dict:
        today = timezone.localdate()
        data_points = []

        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            rev = BiCoreService.get_revenue_by_bucket(d)
            sal = BiCoreService.get_fulfillment_by_gateway(d)
            unused = BiCoreService.get_unused_combined_pool(d)
            data_points.append({
                'date': d.isoformat(),
                'revenue': rev['total'],
                'sales': sal['total'],
                'unused_combined_pool': unused['amount'],
            })

        values = [d['revenue'] for d in data_points]
        avg = mean(values)
        total = sum(values)
        min_val = min(values)
        max_val = max(values)

        growth_rate = 0.0
        if len(values) >= 7:
            first_half = mean(values[:len(values)//2])
            second_half = mean(values[len(values)//2:])
            growth_rate = ((second_half - first_half) / first_half * 100) if first_half > 0 else 0.0

        moving_avg_7d = []
        for i in range(len(data_points)):
            segment = values[max(0, i-6):i+1]
            moving_avg_7d.append(round(mean(segment), 2))

        return {
            'period_days': days,
            'total_revenue': round(total, 2),
            'total_sales': round(sum(d['sales'] for d in data_points), 2),
            'daily_average': round(avg, 2),
            'min_daily': round(min_val, 2),
            'max_daily': round(max_val, 2),
            'growth_rate_pct': round(growth_rate, 2),
            'data_points': data_points,
            'moving_average_7d': moving_avg_7d,
        }

    @staticmethod
    def bucket_trend(bucket: str, days: int = 30) -> Dict:
        today = timezone.localdate()
        bucket = bucket.upper()
        data_points = []

        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            rev = BiCoreService.get_revenue_by_bucket(d)
            sal = BiCoreService.get_fulfillment_by_gateway(d)
            data_points.append({
                'date': d.isoformat(),
                'revenue': rev['buckets'].get(bucket, {}).get('amount', 0),
                'sales': sal['buckets'].get(bucket, {}).get('amount', 0),
            })

        values = [d['revenue'] for d in data_points]
        avg = mean(values) if values else 0

        return {
            'bucket': bucket,
            'period_days': days,
            'total_revenue': round(sum(values), 2),
            'daily_average': round(avg, 2),
            'data_points': data_points,
        }

    @staticmethod
    def stock_trend(days: int = 30) -> Dict:
        today = timezone.localdate()
        data_points = []

        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            from payments.services.stock_report_service import StockReportService
            report = StockReportService.generate_stock_report_for_date(d)
            data_points.append({
                'date': d.isoformat(),
                'total_products': report['summary']['total_products'],
                'total_stock_value': report['summary']['total_stock_value'],
                'out_of_stock': report['summary']['out_of_stock_count'],
                'low_stock': report['summary']['low_stock_count'],
                'in_stock': report['summary']['in_stock_count'],
            })

        return {
            'period_days': days,
            'data_points': data_points,
        }
