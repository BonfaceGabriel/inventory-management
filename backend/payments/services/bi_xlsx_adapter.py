import logging
from datetime import date
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from django.utils import timezone

from payments.services.bi_remote_service import BiRemoteService
from utils.xlsx_generator import XlsxGenerator

logger = logging.getLogger(__name__)

MONETARY_KEYS = {
    'amount', 'revenue', 'sales', 'cost', 'price', 'gap', 'value',
    'total', 'total_revenue', 'total_sales', 'total_amount', 'total_cost',
    'total_value', 'amount_fulfilled', 'balance', 'unused', 'credit_lost',
    'revenue_change', 'pv', 'total_pv', 'amount_min', 'amount_max',
}

COUNT_KEYS = {
    'count', 'quantity', 'quantity_sold', 'items', 'product_count',
    'total_stock_units', 'unique_products', 'fulfillment_count',
    'fulfilled_items', 'fulfilled_orders', 'pending_orders',
    'total_products', 'total_categories', 'total_users',
    'total_orders_created', 'total_products_sold', 'total_quantity',
    'total_count', 'days_with_sales', 'period_days', 'transaction_count',
    'transactions_processed', 'transactions_activated',
    'transactions_completed', 'items_scanned', 'combined_orders_created',
    'total_actions', 'reorder_level', 'out_of_stock_count',
    'low_stock_count', 'in_stock_count', 'daily_average_qty',
}

SKIP_KEYS = {
    'generated_at', 'filters', 'query', 'limit', 'found', 'message',
    'by_status', 'by_gateway', 'shared', 'product_info', 'change',
    'date1', 'date2', 'unused_pool', 'credit_lost_pool',
    'moving_average_7d', 'stock_alerts',
}

LIST_FIELDS = [
    'products', 'orders', 'transactions', 'gateways', 'branches',
    'categories', 'users', 'data_points', 'sample_transactions',
    'out_of_stock_products', 'low_stock_products', 'top_products',
]


def _derive_columns(row: dict) -> list:
    columns = []
    for key in row:
        if key in SKIP_KEYS:
            continue
        header = key.replace('_', ' ').title()
        w = min(max(len(header), 12), 30)
        align = 'right' if key in MONETARY_KEYS or key in COUNT_KEYS else 'left'
        columns.append({'key': key, 'header': header, 'width': w, 'align': align})
    return columns


def _buckets_to_rows(buckets: dict) -> list:
    rows = []
    for gateway, data in buckets.items():
        if isinstance(data, dict):
            rows.append({'gateway': gateway, **data})
        else:
            rows.append({'gateway': gateway, 'value': data})
    return rows


def _extract_rows(data: dict) -> Tuple[List[Dict], Dict]:
    for field in LIST_FIELDS:
        items = data.get(field)
        if isinstance(items, list) and items and isinstance(items[0], dict):
            meta = {k: v for k, v in data.items() if k != field and k not in SKIP_KEYS and not isinstance(v, (dict, list))}
            return items, meta

    buckets = data.get('buckets')
    if isinstance(buckets, dict):
        meta = {k: v for k, v in data.items() if k != 'buckets' and k not in SKIP_KEYS and not isinstance(v, (dict, list))}
        return _buckets_to_rows(buckets), meta

    flat = {}
    for k, v in data.items():
        if k in SKIP_KEYS or isinstance(v, (dict, list)):
            continue
        flat[k] = v
    return [flat] if flat else [], {}


class BiXlsxAdapter:
    CHART_CACHE_TTL = 300

    @staticmethod
    def for_any(tool_name: str, data: Dict) -> Optional[Tuple[BytesIO, str]]:
        if not data or not isinstance(data, dict):
            return None
        if data.get('found') is False:
            return None

        branch_data = data.get('_branch_data')
        if isinstance(branch_data, dict) and len(branch_data) > 1:
            return BiXlsxAdapter.for_branch_breakdown(tool_name, branch_data)

        rows, meta = _extract_rows(data)
        if not rows:
            return None

        cols = _derive_columns(rows[0])
        today = timezone.localdate().isoformat()
        title = f"{tool_name.replace('_', ' ').title()} - {today}"
        buf = XlsxGenerator.from_data(rows, cols, sheet_name=tool_name[:31], title=title)
        filename = f"{tool_name}_{today}.xlsx"
        return buf, filename

    @staticmethod
    def for_branch_breakdown(tool_name: str, branch_data: Dict) -> Optional[Tuple[BytesIO, str]]:
        today = timezone.localdate().isoformat()
        branches = BiRemoteService.list_branches()
        slug_to_display = {b['slug']: b['name'] for b in branches}
        sheets = []
        for slug, data in branch_data.items():
            display = slug_to_display.get(slug, slug.replace('-', ' ').title())
            rows, meta = _extract_rows(data)
            if rows:
                cols = _derive_columns(rows[0])
                sheets.append({
                    'name': display[:31],
                    'data': rows,
                    'columns': cols,
                    'title': f"{display} - {today}",
                })

        if not sheets:
            return None

        buf = XlsxGenerator.multi_sheet(sheets)
        filename = f"{tool_name}_{today}.xlsx"
        return buf, filename
