import logging
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from django.conf import settings
from django.utils import timezone
import requests

from payments.services.bi_core_service import BiCoreService


logger = logging.getLogger(__name__)

SHARED_GATEWAY_BUCKETS = {'TILL', 'MERCH'}
BRANCH_SPECIFIC_BUCKETS = {'PAYBILL', 'PDQ'}


def _get_target_branches() -> List[Dict]:
    return getattr(settings, 'PAYMENT_RELAY_TARGETS', [])


def _get_local_branch_name() -> str:
    return getattr(settings, 'BRANCH_NAME', 'Main Shop')


def _slugify(name: str) -> str:
    return name.lower().replace(' ', '-')


class BiBranchAggregator:
    @staticmethod
    def get_local_branch_info() -> Dict:
        name = _get_local_branch_name()
        return {
            'id': _slugify(name),
            'name': name,
        }

    @staticmethod
    def fetch_branch_briefing(branch_url: str, report_date: date) -> Optional[Dict]:
        api_key = getattr(settings, 'VITE_INVENTORY_API_KEY', '')
        if not api_key:
            logger.warning("VITE_INVENTORY_API_KEY not set — skipping branch fetch")
            return None

        try:
            url = branch_url.rstrip('/') + f'/api/v1/bi/briefing/?date={report_date.isoformat()}'
            resp = requests.get(
                url,
                headers={'Authorization': f'Bearer {api_key}'},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.warning(
                    f"Branch {branch_url} returned {resp.status_code} for briefing"
                )
                return None
        except requests.RequestException as e:
            logger.error(f"Failed to fetch briefing from {branch_url}: {e}")
            return None

    @staticmethod
    def aggregate_branch_revenue(report_date: Optional[date] = None) -> Dict:
        from payments.services.bi_briefing_service import BiBriefingService
        if report_date is None:
            report_date = timezone.localdate()

        local_briefing = BiBriefingService.generate_daily_briefing(report_date)

        aggregated = {
            'total_revenue': Decimal('0.00'),
            'total_sales': Decimal('0.00'),
            'branches': [],
        }

        branches_data = {
            'primary': {
                'name': _get_local_branch_name(),
                'id': _slugify(_get_local_branch_name()),
                'status': 'ok',
            }
        }

        primary_revenue = Decimal('0.00')
        primary_sales = Decimal('0.00')

        for bucket, detail in local_briefing['revenue_buckets'].items():
            if bucket in SHARED_GATEWAY_BUCKETS:
                aggregated['total_revenue'] += Decimal(str(detail['revenue']))
                aggregated['total_sales'] += Decimal(str(detail['sales']))
            else:
                primary_revenue += Decimal(str(detail['revenue']))
                primary_sales += Decimal(str(detail['sales']))

        aggregated['total_revenue'] += primary_revenue
        aggregated['total_sales'] += primary_sales

        branches_data['primary']['revenue'] = float(primary_revenue)
        branches_data['primary']['sales'] = float(primary_sales)
        branches_data['primary']['unused'] = local_briefing['unused_pool']['amount']
        branches_data['primary']['credit_lost'] = local_briefing['credit_lost_pool']['amount']
        branches_data['primary']['stock_alerts'] = local_briefing['stock_alerts']['critical_alerts_count']
        branches_data['primary']['shared_buckets'] = {
            'till': local_briefing['revenue_buckets'].get('TILL', {}).get('revenue', 0),
            'merch': local_briefing['revenue_buckets'].get('MERCH', {}).get('revenue', 0),
        }

        for target in _get_target_branches():
            branch_name = target.get('name', 'Unknown')
            branch_url = target.get('url', '')

            briefing_data = BiBranchAggregator.fetch_branch_briefing(branch_url, report_date)

            if briefing_data:
                branch_revenue = Decimal('0.00')
                branch_sales = Decimal('0.00')

                for bucket, detail in briefing_data.get('revenue_buckets', {}).items():
                    if bucket in BRANCH_SPECIFIC_BUCKETS:
                        branch_revenue += Decimal(str(detail['revenue']))
                        branch_sales += Decimal(str(detail['sales']))

                aggregated['total_revenue'] += branch_revenue
                aggregated['total_sales'] += branch_sales

                branches_data[_slugify(branch_name)] = {
                    'name': branch_name,
                    'id': _slugify(branch_name),
                    'status': 'ok',
                    'revenue': float(branch_revenue),
                    'sales': float(branch_sales),
                    'unused': briefing_data.get('unused_pool', {}).get('amount', 0),
                    'credit_lost': briefing_data.get('credit_lost_pool', {}).get('amount', 0),
                    'stock_alerts': briefing_data.get('stock_alerts', {}).get('critical_alerts_count', 0),
                }
            else:
                branches_data[_slugify(branch_name)] = {
                    'name': branch_name,
                    'id': _slugify(branch_name),
                    'status': 'unreachable',
                    'revenue': 0,
                    'sales': 0,
                    'unused': 0,
                    'credit_lost': 0,
                    'stock_alerts': 0,
                }

        return {
            'date': report_date.isoformat(),
            'total_revenue': round(float(aggregated['total_revenue']), 2),
            'total_sales': round(float(aggregated['total_sales']), 2),
            'branches': list(branches_data.values()),
            'shared_gateway_revenue': {
                'note': 'Till and Merch revenue only counted from primary instance (shared gateways)',
            },
        }

    @staticmethod
    def best_performing_branch(metric: str = 'revenue', report_date: Optional[date] = None) -> Dict:
        agg = BiBranchAggregator.aggregate_branch_revenue(report_date)
        ranked = sorted(
            [b for b in agg['branches'] if b['status'] == 'ok'],
            key=lambda b: b.get(metric, 0),
            reverse=True,
        )

        return {
            'date': agg['date'],
            'metric': metric,
            'rankings': ranked if ranked else [{'name': 'No data', 'status': 'unreachable'}],
            'best': ranked[0] if ranked else None,
            'worst': ranked[-1] if len(ranked) > 1 else None,
        }
