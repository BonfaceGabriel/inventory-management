from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Optional

from django.utils import timezone

from payments.services.bi_core_service import BiCoreService
from payments.services.bi_compare_service import BiCompareService
from payments.services.bi_anomaly_service import BiAnomalyService
from payments.services.bi_trend_service import BiTrendService


class BiBriefingService:
    @staticmethod
    def generate_daily_briefing(report_date: Optional[date] = None) -> Dict:
        if report_date is None:
            report_date = timezone.localdate()

        yesterday = report_date - timedelta(days=1)

        revenue = BiCoreService.get_revenue_by_bucket(report_date)
        sales = BiCoreService.get_fulfillment_by_gateway(report_date)
        rev_vs_sales = BiCoreService.get_revenue_vs_sales(report_date)
        unused = BiCoreService.get_unused_combined_pool(report_date)
        credit_lost = BiCoreService.get_credit_lost(report_date)
        stock = BiCoreService.get_stock_alerts()
        reconciliation = BiCoreService.get_reconciliation(report_date)
        merch = BiCoreService.get_merch_fulfillment(report_date)
        kits = BiCoreService.get_registration_kits(report_date)
        issuer = BiCoreService.get_issuer_stats()
        discrepancies = BiCoreService.get_discrepancies(report_date)

        vs_yesterday = BiCompareService.compare_dates('revenue_vs_sales', yesterday, report_date)

        trend_7d = BiTrendService.revenue_trend(days=7)

        anomalies = BiAnomalyService.check_revenue_anomaly(days=30, threshold=2.0)

        per_bucket_detail = {}
        for b in BiCoreService.REVENUE_BUCKETS:
            rev_amt = revenue['buckets'][b]['amount']
            sal_amt = sales['buckets'].get(b, {}).get('amount', 0.0)
            gap = rev_amt - sal_amt
            rate = (sal_amt / rev_amt * 100) if rev_amt > 0 else 0.0

            alert = None
            if b in ('PAYBILL', 'PDQ'):
                if unused['amount'] > 0:
                    alert = f"UNUSED: KES {unused['amount']:,.2f} untouched — carries over"
                if credit_lost['amount'] > 0:
                    alert = f"CREDIT LOST: KES {credit_lost['amount']:,.2f} on partially fulfilled — cannot recover"
            elif b == 'MERCH':
                if gap > 0:
                    alert = f"Unfulfilled merch: KES {gap:,.2f}"

            per_bucket_detail[b] = {
                'revenue': rev_amt,
                'sales': sal_amt,
                'gap': gap,
                'fulfillment_rate': round(rate, 1),
                'alert': alert,
            }

        stock_issues = []
        if stock['out_of_stock_count'] > 0:
            stock_issues.append(f"{stock['out_of_stock_count']} out of stock")
        if stock['low_stock_count'] > 0:
            stock_issues.append(f"{stock['low_stock_count']} low stock")

        briefing = {
            'date': report_date.isoformat(),
            'generated_at': timezone.now().isoformat(),

            'summary': {
                'total_revenue': revenue['total'],
                'total_sales': sales['total'],
                'gap': rev_vs_sales['gap'],
                'fulfillment_rate': rev_vs_sales['fulfillment_rate'],
                'transaction_count': sum(
                    revenue['buckets'][b]['count'] for b in BiCoreService.REVENUE_BUCKETS
                ),
                'avg_transaction_value': round(
                    revenue['total'] / sum(revenue['buckets'][b]['count'] for b in BiCoreService.REVENUE_BUCKETS), 2
                ) if sum(revenue['buckets'][b]['count'] for b in BiCoreService.REVENUE_BUCKETS) > 0 else 0,
            },

            'revenue_buckets': per_bucket_detail,

            'unused_pool': {
                'amount': unused['amount'],
                'count': unused['count'],
                'description': 'Paybill/PDQ payments never touched — available to fulfill tomorrow',
            },

            'credit_lost_pool': {
                'amount': credit_lost['amount'],
                'count': credit_lost['count'],
                'description': 'Partially fulfilled Paybill/PDQ remaining balance — CANNOT be recovered',
            },

            'stock_alerts': {
                'out_of_stock_count': stock['out_of_stock_count'],
                'low_stock_count': stock['low_stock_count'],
                'in_stock_count': stock['in_stock_count'],
                'total_stock_value': stock['total_stock_value'],
                'summary': ', '.join(stock_issues) if stock_issues else 'All stock levels healthy',
                'out_of_stock_products': stock['out_of_stock_products'][:5],
                'low_stock_products': stock['low_stock_products'][:5],
                'critical_alerts_count': stock['out_of_stock_count'] + stock['low_stock_count'],
            },

            'reconciliation': {
                'is_balanced': reconciliation.get('is_balanced', False),
                'x_value': reconciliation.get('x_value', 0),
                'y_value': reconciliation.get('y_value', 0),
                'result': reconciliation.get('result', 0),
                'x_components': reconciliation.get('x_formula', {}),
                'y_components': reconciliation.get('y_formula', {}),
            },

            'merchandise': {
                'fulfilled_revenue': merch['fulfilled_revenue'],
                'fulfilled_items': merch['fulfilled_items'],
                'fulfilled_orders': merch['fulfilled_orders'],
                'pending_orders': merch['pending_orders'],
            },

            'registration_kits': {
                'kits_issued': kits['kits_issued'],
                'total_value': kits['total_value'],
            },

            'issuer_queue': {
                'pending_transactions': issuer['pending_transactions'],
                'active_issuances': issuer['active_issuances'],
            },

            'discrepancies': discrepancies,

            'vs_yesterday': {
                'revenue_change_pct': vs_yesterday.get('percentage_change', 0),
                'revenue_change': vs_yesterday.get('absolute_change', 0),
                'revenue_direction': vs_yesterday.get('direction', 'flat'),
            },

            'trend_7d': {
                'total_revenue': trend_7d['total_revenue'],
                'daily_average': trend_7d['daily_average'],
                'growth_rate_pct': trend_7d['growth_rate_pct'],
            },

            'anomalies': {
                'anomaly_count': anomalies['anomaly_count'],
                'anomalies': anomalies['anomalies'][:5],
                'mean': anomalies['mean'],
                'std_dev': anomalies['std_dev'],
            },
        }

        return briefing
