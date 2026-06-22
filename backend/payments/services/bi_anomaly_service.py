from datetime import timedelta
from decimal import Decimal
from typing import Dict, List
from statistics import mean, stdev

from django.utils import timezone

from payments.services.bi_core_service import BiCoreService


class BiAnomalyService:
    @staticmethod
    def _z_score(value, values: List[float]) -> float:
        if len(values) < 3:
            return 0.0
        avg = mean(values)
        sd = stdev(values)
        if sd == 0:
            return 0.0
        return (value - avg) / sd

    @staticmethod
    def check_revenue_anomaly(days: int = 30, threshold: float = 2.0) -> Dict:
        today = timezone.localdate()
        daily_values = []
        data_points = []

        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            rev = BiCoreService.get_revenue_by_bucket(d)
            daily_values.append(rev['total'])
            data_points.append({
                'date': d.isoformat(),
                'revenue': rev['total'],
            })

        avg = mean(daily_values)
        sd = stdev(daily_values) if len(daily_values) > 2 else 0

        anomalies = []
        for dp in data_points:
            z = BiAnomalyService._z_score(dp['revenue'], daily_values)
            dp['z_score'] = round(z, 2)
            dp['is_anomaly'] = abs(z) > threshold
            if dp['is_anomaly']:
                anomalies.append(dp)

        return {
            'metric': 'revenue',
            'period_days': days,
            'mean': round(avg, 2),
            'std_dev': round(sd, 2),
            'threshold': threshold,
            'anomaly_count': len(anomalies),
            'anomalies': anomalies,
            'all_points': data_points,
        }

    @staticmethod
    def check_all_anomalies(days: int = 30, threshold: float = 2.0) -> Dict:
        revenue_anomaly = BiAnomalyService.check_revenue_anomaly(days, threshold)

        today = timezone.localdate()
        bucket_anomalies = {}
        for bucket in BiCoreService.REVENUE_BUCKETS:
            b_values = []
            for i in range(days - 1, -1, -1):
                d = today - timedelta(days=i)
                rev = BiCoreService.get_revenue_by_bucket(d)
                b_values.append(rev['buckets'].get(bucket, {}).get('amount', 0))

            b_anomalies = []
            for i, val in enumerate(b_values):
                z = BiAnomalyService._z_score(val, b_values)
                if abs(z) > threshold:
                    date_str = (today - timedelta(days=days-1-i)).isoformat()
                    b_anomalies.append({
                        'date': date_str,
                        'value': val,
                        'z_score': round(z, 2),
                    })

            bucket_anomalies[bucket] = {
                'anomaly_count': len(b_anomalies),
                'anomalies': b_anomalies,
            }

        return {
            'period_days': days,
            'threshold': threshold,
            'revenue': {
                'anomaly_count': revenue_anomaly['anomaly_count'],
                'anomalies': revenue_anomaly['anomalies'],
                'mean': revenue_anomaly['mean'],
                'std_dev': revenue_anomaly['std_dev'],
            },
            'by_bucket': bucket_anomalies,
        }

    @staticmethod
    def check_stock_anomalies() -> Dict:
        alerts = BiCoreService.get_stock_alerts()
        return {
            'out_of_stock_count': alerts['out_of_stock_count'],
            'low_stock_count': alerts['low_stock_count'],
            'critical_alerts': [
                p for p in alerts['out_of_stock_products']
            ][:10],
        }
