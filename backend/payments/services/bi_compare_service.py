from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Optional

from django.utils import timezone

from payments.services.bi_core_service import BiCoreService


class BiCompareService:
    @staticmethod
    def compare_dates(metric: str, date1: date, date2: date) -> Dict:
        if metric == 'revenue':
            d1 = BiCoreService.get_revenue_by_bucket(date1)
            d2 = BiCoreService.get_revenue_by_bucket(date2)
        elif metric == 'sales':
            d1 = BiCoreService.get_fulfillment_by_gateway(date1)
            d2 = BiCoreService.get_fulfillment_by_gateway(date2)
        elif metric == 'revenue_vs_sales':
            d1 = BiCoreService.get_revenue_vs_sales(date1)
            d2 = BiCoreService.get_revenue_vs_sales(date2)
        else:
            return {'error': f'Unknown metric: {metric}'}

        v1 = Decimal(str(d1.get('total', d1.get('total_revenue', 0))))
        v2 = Decimal(str(d2.get('total', d2.get('total_revenue', 0))))
        diff = v2 - v1
        pct = float(diff / v1 * 100) if v1 > 0 else 0.0

        return {
            'metric': metric,
            'period1': {'date': date1.isoformat(), 'value': float(v1)},
            'period2': {'date': date2.isoformat(), 'value': float(v2)},
            'absolute_change': float(diff),
            'percentage_change': pct,
            'direction': 'up' if diff > 0 else ('down' if diff < 0 else 'flat'),
        }

    @staticmethod
    def compare_week_over_week(metric: str = 'revenue') -> Dict:
        today = timezone.localdate()
        this_week_start = today - timedelta(days=today.weekday())
        last_week_start = this_week_start - timedelta(days=7)
        last_week_end = this_week_start - timedelta(days=1)

        this_week_total = Decimal('0.00')
        last_week_total = Decimal('0.00')

        for i in range(7):
            d = this_week_start + timedelta(days=i)
            if d > today:
                break
            if metric == 'revenue':
                data = BiCoreService.get_revenue_by_bucket(d)
            else:
                data = BiCoreService.get_fulfillment_by_gateway(d)
            this_week_total += Decimal(str(data['total']))

            ld = last_week_start + timedelta(days=i)
            if metric == 'revenue':
                ldata = BiCoreService.get_revenue_by_bucket(ld)
            else:
                ldata = BiCoreService.get_fulfillment_by_gateway(ld)
            last_week_total += Decimal(str(ldata['total']))

        diff = this_week_total - last_week_total
        pct = float(diff / last_week_total * 100) if last_week_total > 0 else 0.0

        return {
            'metric': metric,
            'this_week': {'start': this_week_start.isoformat(), 'end': today.isoformat(), 'total': float(this_week_total)},
            'last_week': {'start': last_week_start.isoformat(), 'end': last_week_end.isoformat(), 'total': float(last_week_total)},
            'absolute_change': float(diff),
            'percentage_change': pct,
            'direction': 'up' if diff > 0 else ('down' if diff < 0 else 'flat'),
        }

    @staticmethod
    def compare_revenue_vs_sales(date1: date, date2: date) -> Dict:
        d1 = BiCoreService.get_revenue_vs_sales(date1)
        d2 = BiCoreService.get_revenue_vs_sales(date2)

        return {
            'period1': {
                'date': date1.isoformat(),
                'revenue': d1['total_revenue'],
                'sales': d1['total_sales'],
                'gap': d1['gap'],
                'fulfillment_rate': d1['fulfillment_rate'],
                'unused': d1['unused_pool']['amount'],
                'credit_lost': d1['credit_lost_pool']['amount'],
            },
            'period2': {
                'date': date2.isoformat(),
                'revenue': d2['total_revenue'],
                'sales': d2['total_sales'],
                'gap': d2['gap'],
                'fulfillment_rate': d2['fulfillment_rate'],
                'unused': d2['unused_pool']['amount'],
                'credit_lost': d2['credit_lost_pool']['amount'],
            },
            'revenue_change_pct': (
                ((d2['total_revenue'] - d1['total_revenue']) / d1['total_revenue'] * 100)
                if d1['total_revenue'] else 0
            ),
            'sales_change_pct': (
                ((d2['total_sales'] - d1['total_sales']) / d1['total_sales'] * 100)
                if d1['total_sales'] else 0
            ),
        }
