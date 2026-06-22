import logging
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from django.utils import timezone

from payments.services.reconciliation_v2_service import ReconciliationV2Service
from payments.services.reconciliation_service import ReconciliationService
from payments.models import CombinedOrder
from utils.chart_generator import ChartGenerator
from utils.xlsx_generator import XlsxGenerator

logger = logging.getLogger(__name__)

RECOMMENDATIONS = {
    'UNFULFILLED': 'Process or cancel these transactions to free up the balance.',
    'PARTIALLY_FULFILLED': 'Remaining balance on these transactions is lost forever. Review fulfillment process to avoid partial fulfillments.',
    'COMBINED_ORDER_MISMATCH': 'Combined orders not fully completed. Check fulfillment status and complete or cancel them.',
    'LOW_CONFIDENCE': 'Low SMS parsing confidence — review and correct these transactions manually.',
    'POTENTIALLY_STUCK': 'Partially fulfilled for over 24 hours — manual intervention may be needed.',
}


class BiReconciliationDeepDiveService:

    @staticmethod
    def get_deep_dive(report_date: date = None) -> Dict:
        if report_date is None:
            report_date = timezone.localtime(timezone.now()).date()

        v2_report = ReconciliationV2Service.generate_daily_report(report_date)

        paybill_gateway = ReconciliationV2Service.get_parent_paybill_gateway()

        calc_results = {
            'mpesa_paybill': ReconciliationV2Service.calculate_mpesa_paybill(report_date, paybill_gateway),
            'unused': ReconciliationV2Service.calculate_unused_unfulfilled(report_date, paybill_gateway),
            'pdq': ReconciliationV2Service.calculate_pdq_total(report_date),
            'previous': ReconciliationV2Service.calculate_previous(report_date, paybill_gateway),
            'till': ReconciliationV2Service.calculate_till_sales(report_date),
            'credit': ReconciliationV2Service.calculate_credit(report_date, paybill_gateway),
            'kits': ReconciliationV2Service.calculate_kits(report_date),
            'sales': ReconciliationV2Service.calculate_total_sales(report_date),
        }

        components = BiReconciliationDeepDiveService._build_components(calc_results)

        issues = BiReconciliationDeepDiveService._identify_issues(report_date, calc_results)

        old_disc = ReconciliationService.identify_discrepancies(report_date)

        result = float(v2_report.get('result', 0))
        severity = BiReconciliationDeepDiveService._classify_severity(result)

        return {
            'date': report_date.isoformat(),
            'is_balanced': v2_report.get('is_balanced', False),
            'x_value': float(v2_report.get('x_value', 0)),
            'y_value': float(v2_report.get('y_value', 0)),
            'result': result,
            'severity': severity,
            'components': components,
            'issues': issues,
            'old_discrepancies': {
                'low_confidence': old_disc.get('discrepancies', {}).get('low_confidence', {}),
                'unprocessed': old_disc.get('discrepancies', {}).get('unprocessed', {}),
                'no_gateway': old_disc.get('discrepancies', {}).get('no_gateway', {}),
                'potentially_stuck': old_disc.get('discrepancies', {}).get('potentially_stuck', {}),
            },
        }

    @staticmethod
    def _build_components(calc_results: Dict) -> Dict:
        def _clean_tx_list(tx_list: List[Dict]) -> List[Dict]:
            cleaned = []
            for tx in (tx_list or []):
                cleaned.append({
                    'tx_id': str(tx.get('tx_id', '')),
                    'amount': float(tx.get('amount', 0)),
                    'status': tx.get('status', ''),
                    'sender_name': tx.get('sender_name', '') or '',
                })
            return cleaned

        def _fmt_comp(key: str) -> Dict:
            raw = calc_results.get(key, {})
            return {
                'amount': float(raw.get('amount', 0)),
                'count': raw.get('count', 0),
                'transactions': _clean_tx_list(raw.get('transactions', [])),
            }

        components = {}
        for key in ['mpesa_paybill', 'unused', 'pdq', 'previous', 'till', 'credit', 'kits', 'sales']:
            components[key] = _fmt_comp(key)

        sales_raw = calc_results.get('sales', {})
        components['sales']['by_gateway'] = {
            k: {'amount': float(v['amount']), 'count': v['count']}
            for k, v in sales_raw.get('by_gateway', {}).items()
        }

        credit_raw = calc_results.get('credit', {})
        components['credit']['combined_orders'] = [
            {
                'combined_order_id': co.get('combined_order_id', ''),
                'total_amount': float(co.get('total_amount', 0)),
                'amount_fulfilled': float(co.get('amount_fulfilled', 0)),
                'remaining': float(co.get('remaining', 0)),
            }
            for co in (credit_raw.get('combined_orders') or [])
        ]

        return components

    @staticmethod
    def _identify_issues(report_date: date, calc_results: Dict) -> List[Dict]:
        issues = []

        unused = calc_results.get('unused', {})
        if unused.get('count', 0) > 0:
            issues.append({
                'type': 'UNFULFILLED',
                'severity': BiReconciliationDeepDiveService._classify_severity(float(unused.get('amount', 0))),
                'count': unused['count'],
                'total_amount': float(unused['amount']),
                'transactions': BiReconciliationDeepDiveService._clean_for_issue(unused.get('transactions', [])),
                'recommendation': RECOMMENDATIONS['UNFULFILLED'],
            })

        credit = calc_results.get('credit', {})
        if credit.get('count', 0) > 0:
            issues.append({
                'type': 'PARTIALLY_FULFILLED',
                'severity': BiReconciliationDeepDiveService._classify_severity(float(credit.get('amount', 0))),
                'count': credit['count'],
                'total_amount': float(credit['amount']),
                'transactions': BiReconciliationDeepDiveService._clean_for_issue(credit.get('transactions', [])),
                'recommendation': RECOMMENDATIONS['PARTIALLY_FULFILLED'],
            })

        co_mismatches = BiReconciliationDeepDiveService._check_combined_orders(report_date)
        if co_mismatches:
            total_amount = sum(m.get('remaining', 0) for m in co_mismatches)
            issues.append({
                'type': 'COMBINED_ORDER_MISMATCH',
                'severity': BiReconciliationDeepDiveService._classify_severity(total_amount),
                'count': len(co_mismatches),
                'total_amount': total_amount,
                'combined_orders': co_mismatches,
                'recommendation': RECOMMENDATIONS['COMBINED_ORDER_MISMATCH'],
            })

        old_disc = ReconciliationService.identify_discrepancies(report_date)
        disc = old_disc.get('discrepancies', {})

        low_conf = disc.get('low_confidence', {})
        if low_conf.get('count', 0) > 0:
            issues.append({
                'type': 'LOW_CONFIDENCE',
                'severity': 'MINOR',
                'count': low_conf['count'],
                'total_amount': 0.0,
                'transactions': low_conf.get('transactions', []),
                'recommendation': RECOMMENDATIONS['LOW_CONFIDENCE'],
            })

        stuck = disc.get('potentially_stuck', {})
        if stuck.get('count', 0) > 0:
            issues.append({
                'type': 'POTENTIALLY_STUCK',
                'severity': 'MAJOR',
                'count': stuck['count'],
                'total_amount': 0.0,
                'transactions': stuck.get('transactions', []),
                'recommendation': RECOMMENDATIONS['POTENTIALLY_STUCK'],
            })

        return issues

    @staticmethod
    def _check_combined_orders(report_date: date) -> List[Dict]:
        mismatches = []
        orders = CombinedOrder.objects.filter(
            created_at__date=report_date,
        ).exclude(status=CombinedOrder.Status.FULFILLED).exclude(status=CombinedOrder.Status.CANCELLED)
        for co in orders:
            mismatches.append({
                'combined_order_id': co.combined_order_id,
                'total_amount': float(co.total_amount),
                'amount_fulfilled': float(co.amount_fulfilled),
                'remaining': float(co.total_amount - co.amount_fulfilled),
                'status': co.status,
            })
        return mismatches

    @staticmethod
    def _classify_severity(amount: float) -> str:
        if amount == 0.0:
            return 'BALANCED'
        if abs(amount) > 1000:
            return 'CRITICAL'
        if abs(amount) > 100:
            return 'MAJOR'
        return 'MINOR'

    @staticmethod
    def _clean_for_issue(tx_list: List[Dict]) -> List[Dict]:
        cleaned = []
        for tx in (tx_list or []):
            item = {
                'tx_id': str(tx.get('tx_id', '')),
                'amount': float(tx.get('amount', 0)),
            }
            if tx.get('remaining'):
                item['remaining'] = float(tx['remaining'])
            if tx.get('status'):
                item['status'] = tx['status']
            if tx.get('sender_name'):
                item['sender_name'] = str(tx['sender_name'])
            cleaned.append(item)
        return cleaned

    @staticmethod
    def generate_chart(deep_dive_data: Dict) -> BytesIO:
        components = deep_dive_data.get('components', {})

        severity = deep_dive_data.get('severity', 'BALANCED')
        title_suffix = {'BALANCED': '\u2705 Balanced', 'MINOR': '\u26a0\ufe0f Minor Gap', 'MAJOR': '\U0001f534 Major Gap', 'CRITICAL': '\U0001f6a8 Critical Gap'}
        base_title = f"Reconciliation Deep Dive — {deep_dive_data.get('date', '')} ({title_suffix.get(severity, '')})"

        x_labels = ['Paybill', 'Unused', 'PDQ', 'Previous', 'Sales', 'X']
        x_vals = [
            components.get('mpesa_paybill', {}).get('amount', 0),
            components.get('unused', {}).get('amount', 0),
            components.get('pdq', {}).get('amount', 0),
            components.get('previous', {}).get('amount', 0),
            components.get('sales', {}).get('amount', 0),
            abs(deep_dive_data.get('x_value', 0)),
        ]
        x_colors = ['#0891B2', '#EF4444', '#0891B2', '#0891B2', '#EF4444', '#10B981']

        y_labels = ['Till', 'Credit', 'KITS', 'Y']
        y_vals = [
            components.get('till', {}).get('amount', 0),
            components.get('credit', {}).get('amount', 0),
            components.get('kits', {}).get('amount', 0),
            abs(deep_dive_data.get('y_value', 0)),
        ]
        y_colors = ['#F59E0B', '#EF4444', '#EF4444', '#10B981']

        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor('white')

        bars1 = ax1.bar(x_labels, x_vals, color=x_colors, edgecolor='white', linewidth=0.5)
        ax1.set_title('X = Paybill - Unused + PDQ + Previous - Sales', fontsize=11, fontweight='bold', color='#1F2937')
        ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'KES {v:,.0f}'))
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        ax1.grid(axis='y', color='#E5E7EB', linewidth=0.5)
        for bar, val in zip(bars1, x_vals):
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(x_vals) * 0.01,
                     f'KES {val:,.0f}', ha='center', va='bottom', fontsize=8, fontweight='bold', color='#1F2937')

        bars2 = ax2.bar(y_labels, y_vals, color=y_colors, edgecolor='white', linewidth=0.5)
        ax2.set_title('Y = Till - Credit - KITS', fontsize=11, fontweight='bold', color='#1F2937')
        ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'KES {v:,.0f}'))
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.grid(axis='y', color='#E5E7EB', linewidth=0.5)
        for bar, val in zip(bars2, y_vals):
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(y_vals) * 0.01,
                     f'KES {val:,.0f}', ha='center', va='bottom', fontsize=8, fontweight='bold', color='#1F2937')

        fig.suptitle(base_title, fontsize=13, fontweight='bold', color='#1F2937', y=1.02)
        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def generate_xlsx(deep_dive_data: Dict) -> Tuple[BytesIO, str]:
        report_date = deep_dive_data.get('date', 'unknown')
        filename = f"recon_deep_dive_{report_date}.xlsx"

        comp = deep_dive_data.get('components', {})

        summary_data = [{
            'date': report_date,
            'x_value': deep_dive_data.get('x_value', 0),
            'y_value': deep_dive_data.get('y_value', 0),
            'result': deep_dive_data.get('result', 0),
            'is_balanced': 'Yes' if deep_dive_data.get('is_balanced') else 'No',
            'severity': deep_dive_data.get('severity', ''),
        }]
        summary_cols = [
            {'key': 'date', 'header': 'Date', 'width': 14},
            {'key': 'x_value', 'header': 'X Value (KES)', 'width': 16, 'align': 'right'},
            {'key': 'y_value', 'header': 'Y Value (KES)', 'width': 16, 'align': 'right'},
            {'key': 'result', 'header': 'Result (KES)', 'width': 16, 'align': 'right'},
            {'key': 'is_balanced', 'header': 'Balanced', 'width': 12, 'align': 'center'},
            {'key': 'severity', 'header': 'Severity', 'width': 12, 'align': 'center'},
        ]

        all_txns = []
        comp_cols = [
            {'key': 'component', 'header': 'Component', 'width': 18},
            {'key': 'amount', 'header': 'Amount (KES)', 'width': 16, 'align': 'right'},
            {'key': 'count', 'header': 'Count', 'width': 10, 'align': 'center'},
        ]
        for ckey in ['mpesa_paybill', 'unused', 'pdq', 'previous', 'till', 'credit', 'kits', 'sales']:
            c = comp.get(ckey, {})
            all_txns.append({
                'component': ckey.replace('_', ' ').title(),
                'amount': c.get('amount', 0),
                'count': c.get('count', 0),
            })

        txn_data = []
        txn_cols = [
            {'key': 'component', 'header': 'Component', 'width': 18},
            {'key': 'tx_id', 'header': 'Transaction ID', 'width': 22},
            {'key': 'amount', 'header': 'Amount (KES)', 'width': 16, 'align': 'right'},
            {'key': 'status', 'header': 'Status', 'width': 18},
            {'key': 'sender', 'header': 'Sender', 'width': 22},
        ]
        for ckey in ['mpesa_paybill', 'unused', 'pdq', 'previous', 'till', 'credit', 'kits']:
            c = comp.get(ckey, {})
            for tx in (c.get('transactions') or []):
                txn_data.append({
                    'component': ckey.replace('_', ' ').title(),
                    'tx_id': tx.get('tx_id', ''),
                    'amount': tx.get('amount', 0),
                    'status': tx.get('status', ''),
                    'sender': tx.get('sender_name', ''),
                })

        issues = deep_dive_data.get('issues', [])
        issue_data = []
        issue_cols = [
            {'key': 'type', 'header': 'Issue Type', 'width': 24},
            {'key': 'severity', 'header': 'Severity', 'width': 12, 'align': 'center'},
            {'key': 'count', 'header': 'Count', 'width': 10, 'align': 'center'},
            {'key': 'total_amount', 'header': 'Total Amount (KES)', 'width': 18, 'align': 'right'},
            {'key': 'recommendation', 'header': 'Recommendation', 'width': 50},
        ]
        for issue in issues:
            issue_data.append({
                'type': issue.get('type', ''),
                'severity': issue.get('severity', ''),
                'count': issue.get('count', 0),
                'total_amount': issue.get('total_amount', 0),
                'recommendation': issue.get('recommendation', ''),
            })

        sheets = [
            {'name': 'Summary', 'data': summary_data, 'columns': summary_cols, 'title': f'Reconciliation Deep Dive — {report_date}'},
            {'name': 'Components', 'data': all_txns, 'columns': comp_cols, 'title': 'Formula Components'},
            {'name': 'Transactions', 'data': txn_data, 'columns': txn_cols, 'title': 'All Transactions by Component'},
            {'name': 'Issues', 'data': issue_data, 'columns': issue_cols, 'title': 'Identified Issues'},
        ]

        buf = XlsxGenerator.multi_sheet(sheets)
        return buf, filename
