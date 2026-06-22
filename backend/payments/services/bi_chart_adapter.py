import logging
from io import BytesIO
from typing import Dict, Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from utils.chart_generator import ChartGenerator, COLORS

logger = logging.getLogger(__name__)

DARK_TEXT = '#1F2937'
GRID_COLOR = '#E5E7EB'
POS_COLOR = '#0891B2'
NEG_COLOR = '#EF4444'
ACCENT_GREEN = '#10B981'


class BiChartAdapter:

    @staticmethod
    def for_revenue(data: Dict) -> BytesIO:
        buckets = data.get('buckets', {})
        labels = []
        values = []
        colors = []
        bucket_colors = {
            'PAYBILL': '#0891B2',
            'PDQ': '#8B5CF6',
            'TILL': '#F59E0B',
            'MERCH': '#10B981',
        }
        for b in ['PAYBILL', 'PDQ', 'TILL', 'MERCH']:
            bk = buckets.get(b, {})
            labels.append(b)
            values.append(bk.get('amount', 0))
            colors.append(bucket_colors.get(b, '#6B7280'))

        return _bar_chart(labels, values, colors,
                          title=f"Revenue by Bucket \u2014 {data.get('date', '')}",
                          ylabel='Amount (KES)',
                          total_label=f"Total: KES {data.get('total', 0):,.2f}")

    @staticmethod
    def for_fulfillment(data: Dict) -> BytesIO:
        buckets = data.get('buckets', {})
        labels = []
        values = []
        colors_map = {'PAYBILL': '#0891B2', 'PDQ': '#8B5CF6', 'TILL': '#F59E0B'}
        for b in ['PAYBILL', 'PDQ', 'TILL']:
            bk = buckets.get(b, {})
            labels.append(b)
            values.append(bk.get('amount', 0))

        return _bar_chart(labels, values,
                          [colors_map.get(l, '#6B7280') for l in labels],
                          title=f"Fulfillment by Gateway \u2014 {data.get('date', '')}",
                          ylabel='Amount (KES)',
                          total_label=f"Total Fulfilled: KES {data.get('total', 0):,.2f}")

    @staticmethod
    def for_trend(data: Dict) -> BytesIO:
        data_points = data.get('data_points', [])
        dates = [dp.get('date', '')[-5:] for dp in data_points]
        revenues = [dp.get('revenue', 0) for dp in data_points]
        sales = [dp.get('sales', 0) for dp in data_points]

        chart_data = {
            'labels': dates,
            'datasets': [
                {'label': 'Revenue', 'values': revenues},
                {'label': 'Fulfillment', 'values': sales},
            ],
        }

        title = f"Revenue Trend \u2014 Last {data.get('period_days', 30)} Days"
        grow = data.get('growth_rate_pct', 0)
        if grow:
            title += f" ({grow:+.1f}% growth)"

        return ChartGenerator.line_chart(
            chart_data,
            title=title,
            ylabel='Amount (KES)',
            figsize=(12, 5),
        )

    @staticmethod
    def for_top_products(data: Dict) -> BytesIO:
        products = data.get('products', [])
        if not products:
            return _empty_chart("No products sold on this date")

        names = [p.get('name', '?')[:25] for p in reversed(products)]
        qtys = [p.get('quantity_sold', 0) for p in reversed(products)]
        revs = [p.get('revenue', 0) for p in reversed(products)]

        fig, ax = plt.subplots(figsize=(10, max(4, len(names) * 0.4)))
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        bars = ax.barh(names, qtys, color=POS_COLOR, edgecolor='white', linewidth=0.5)
        ax.set_title(f"Top Products by Quantity \u2014 {data.get('date', '')}",
                     fontsize=12, fontweight='bold', color=DARK_TEXT, pad=12)
        ax.set_xlabel('Quantity Sold', fontsize=10, color=DARK_TEXT)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='x', color=GRID_COLOR, linewidth=0.5)

        for bar, qty, rev in zip(bars, qtys, revs):
            label = f'{qty} (KES {rev:,.0f})'
            ax.text(bar.get_width() + max(qtys) * 0.01, bar.get_y() + bar.get_height() / 2,
                    label, va='center', fontsize=8, color=DARK_TEXT)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_revenue_vs_sales(data: Dict) -> BytesIO:
        buckets = data.get('buckets', {})
        all_buckets = ['PAYBILL', 'PDQ', 'TILL', 'MERCH']
        rev_vals = [buckets.get(b, {}).get('revenue', 0) for b in all_buckets]
        sal_vals = [buckets.get(b, {}).get('sales', 0) for b in all_buckets]

        fig, ax = plt.subplots(figsize=(10, 5))
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        x = range(len(all_buckets))
        w = 0.35
        ax.bar([xi - w / 2 for xi in x], rev_vals, width=w, label='Revenue',
               color=POS_COLOR, edgecolor='white', linewidth=0.5)
        ax.bar([xi + w / 2 for xi in x], sal_vals, width=w, label='Fulfillment',
               color=ACCENT_GREEN, edgecolor='white', linewidth=0.5)

        ax.set_xticks(x)
        ax.set_xticklabels(all_buckets, fontsize=9, color=DARK_TEXT)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'KES {v:,.0f}'))
        ax.set_title(f"Revenue vs Fulfillment \u2014 {data.get('date', '')}",
                     fontsize=12, fontweight='bold', color=DARK_TEXT, pad=12)
        ax.legend(fontsize=9)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='y', color=GRID_COLOR, linewidth=0.5)

        rate = data.get('fulfillment_rate', 0)
        ax.text(0.98, 0.95, f"Fulfillment Rate: {rate:.1f}%",
                transform=ax.transAxes, ha='right', va='top',
                fontsize=10, fontweight='bold', color=ACCENT_GREEN if rate > 80 else NEG_COLOR)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_period_revenue_vs_sales(data: Dict) -> BytesIO:
        fig, ax = plt.subplots(figsize=(8, 5))
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        labels = ['Revenue', 'Sales', 'Gap']
        values = [
            data.get('total_revenue', 0),
            data.get('total_sales', 0),
            data.get('gap', 0),
        ]
        colors = [POS_COLOR, ACCENT_GREEN, NEG_COLOR] if values[2] > 0 else [POS_COLOR, ACCENT_GREEN, '#94A3B8']

        bars = ax.bar(labels, values, color=colors, edgecolor='white', linewidth=0.5)
        for bar, val in zip(bars, values):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        f'KES {val:,.0f}', ha='center', va='bottom', fontsize=9, fontweight='bold', color=DARK_TEXT)

        rate = data.get('fulfillment_rate', 0)
        ax.text(0.98, 0.95, f"Fulfillment: {rate:.1f}%",
                transform=ax.transAxes, ha='right', va='top',
                fontsize=10, fontweight='bold', color=ACCENT_GREEN if rate > 80 else NEG_COLOR)

        ax.set_title(f"Revenue vs Sales — {data.get('start_date', '')} to {data.get('end_date', '')}",
                     fontsize=12, fontweight='bold', color=DARK_TEXT, pad=12)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'KES {v:,.0f}'))
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='y', color=GRID_COLOR, linewidth=0.5)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_month_comparison(data: Dict) -> BytesIO:
        cur = data.get('current_period', {})
        prev = data.get('previous_period', {})

        fig, ax = plt.subplots(figsize=(8, 5))
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        labels = ['Revenue', 'Sales']
        cur_vals = [cur.get('revenue', 0), cur.get('sales', 0)]
        prev_vals = [prev.get('revenue', 0), prev.get('sales', 0)]

        x = range(len(labels))
        w = 0.35
        ax.bar([xi - w / 2 for xi in x], prev_vals, width=w, label='Previous Month',
               color='#94A3B8', edgecolor='white', linewidth=0.5)
        ax.bar([xi + w / 2 for xi in x], cur_vals, width=w, label='Current Month',
               color=POS_COLOR, edgecolor='white', linewidth=0.5)

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=10, color=DARK_TEXT)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'KES {v:,.0f}'))
        ax.set_title(f"Month-over-Month Comparison", fontsize=12, fontweight='bold', color=DARK_TEXT, pad=12)
        ax.legend(fontsize=9)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='y', color=GRID_COLOR, linewidth=0.5)

        ch = data.get('change', {})
        rev_pct = ch.get('revenue_pct', 0)
        sales_pct = ch.get('sales_pct', 0)
        info = f"Revenue: {rev_pct:+.1f}%  |  Sales: {sales_pct:+.1f}%"
        ax.text(0.98, 0.95, info, transform=ax.transAxes, ha='right', va='top',
                fontsize=9, fontweight='bold', color=DARK_TEXT)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_year_comparison(data: Dict) -> BytesIO:
        cur = data.get('current_period', {})
        prev = data.get('previous_period', {})
        cur_year = data.get('current_year', '')
        prev_year = data.get('previous_year', '')

        fig, ax = plt.subplots(figsize=(8, 5))
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        labels = ['Revenue', 'Sales']
        cur_vals = [cur.get('revenue', 0), cur.get('sales', 0)]
        prev_vals = [prev.get('revenue', 0), prev.get('sales', 0)]

        x = range(len(labels))
        w = 0.35
        ax.bar([xi - w / 2 for xi in x], prev_vals, width=w, label=str(prev_year),
               color='#94A3B8', edgecolor='white', linewidth=0.5)
        ax.bar([xi + w / 2 for xi in x], cur_vals, width=w, label=str(cur_year),
               color=POS_COLOR, edgecolor='white', linewidth=0.5)

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=10, color=DARK_TEXT)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'KES {v:,.0f}'))
        ax.set_title(f"Year-over-Year Comparison (YTD)", fontsize=12, fontweight='bold', color=DARK_TEXT, pad=12)
        ax.legend(fontsize=9)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='y', color=GRID_COLOR, linewidth=0.5)

        ch = data.get('change', {})
        rev_pct = ch.get('revenue_pct', 0)
        sales_pct = ch.get('sales_pct', 0)
        info = f"Revenue: {rev_pct:+.1f}%  |  Sales: {sales_pct:+.1f}%"
        ax.text(0.98, 0.95, info, transform=ax.transAxes, ha='right', va='top',
                fontsize=9, fontweight='bold', color=DARK_TEXT)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_product_sales_trend(data: Dict) -> BytesIO:
        data_points = data.get('data_points', [])
        if not data_points:
            return _empty_chart("No trend data available")

        dates = [dp['date'][-5:] for dp in data_points]
        quantities = [dp['quantity'] for dp in data_points]
        revenues = [dp['revenue'] for dp in data_points]

        product_name = '—'
        if data.get('product_info'):
            product_name = data['product_info'][0].get('name', '—')

        chart_data = {
            'labels': dates,
            'datasets': [
                {'label': 'Quantity', 'values': quantities},
                {'label': 'Revenue (KES)', 'values': revenues},
            ],
        }

        return ChartGenerator.line_chart(
            chart_data,
            title=f"{product_name} — Last {data.get('period_days', 30)} Days",
            ylabel='Amount',
            figsize=(12, 5),
        )

    @staticmethod
    def for_reconciliation(data: Dict) -> BytesIO:
        x_val = float(data.get('x_value', 0))
        y_val = float(data.get('y_value', 0))
        result_val = float(data.get('result', 0))

        fig, ax = plt.subplots(figsize=(8, 5))
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        labels = ['X (Sales)', 'Y (Payment)', 'X + Y']
        values = [x_val, y_val, result_val]
        colors = ['#0891B2', '#10B981', '#8B5CF6']
        bars = ax.bar(labels, values, color=colors, edgecolor='white', linewidth=0.5)

        for bar, val in zip(bars, values):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        f'KES {val:,.0f}', ha='center', va='bottom', fontsize=9, fontweight='bold', color=DARK_TEXT)

        balanced = data.get('is_balanced', False)
        status = '✅ Balanced' if balanced else '❌ NOT Balanced'
        ax.text(0.98, 0.95, status, transform=ax.transAxes, ha='right', va='top',
                fontsize=10, fontweight='bold', color=ACCENT_GREEN if balanced else NEG_COLOR)

        ax.set_title(f"Reconciliation — {data.get('date', '')}",
                     fontsize=12, fontweight='bold', color=DARK_TEXT, pad=12)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'KES {v:,.0f}'))
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='y', color=GRID_COLOR, linewidth=0.5)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_user_performance(data: Dict) -> BytesIO:
        users = data.get('users', [])
        if not users:
            return _empty_chart("No user performance data")

        usernames = [u.get('username', '?') for u in users]
        processed = [u.get('transactions_processed', 0) for u in users]
        activated = [u.get('transactions_activated', 0) for u in users]
        completed = [u.get('transactions_completed', 0) for u in users]
        scanned = [u.get('items_scanned', 0) for u in users]

        fig, ax = plt.subplots(figsize=(10, max(4, len(users) * 0.5)))
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        x = range(len(usernames))
        w = 0.2
        ax.bar([xi - 1.5 * w for xi in x], processed, width=w, label='Processed', color='#0891B2', edgecolor='white', linewidth=0.5)
        ax.bar([xi - 0.5 * w for xi in x], activated, width=w, label='Activated', color='#F59E0B', edgecolor='white', linewidth=0.5)
        ax.bar([xi + 0.5 * w for xi in x], completed, width=w, label='Completed', color='#10B981', edgecolor='white', linewidth=0.5)
        ax.bar([xi + 1.5 * w for xi in x], scanned, width=w, label='Scanned', color='#8B5CF6', edgecolor='white', linewidth=0.5)

        ax.set_xticks(x)
        ax.set_xticklabels(usernames, fontsize=9, color=DARK_TEXT)
        ax.set_title(f"User Performance — {data.get('date', '')}",
                     fontsize=12, fontweight='bold', color=DARK_TEXT, pad=12)
        ax.legend(fontsize=8)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='y', color=GRID_COLOR, linewidth=0.5)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_fulfillment_pipeline(data: Dict) -> BytesIO:
        tx_pipeline = data.get('transaction_pipeline', {})
        co_pipeline = data.get('combined_order_pipeline', {})

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        fig.patch.set_facecolor('white')

        if tx_pipeline:
            labels = list(tx_pipeline.keys())
            values = list(tx_pipeline.values())
            colors_list = [POS_COLOR if v > 0 else '#CBD5E1' for v in values]
            ax1.bar(labels, values, color=colors_list, edgecolor='white', linewidth=0.5)
            ax1.set_title(f'Transaction Pipeline ({data.get("total_transactions", 0)} total)',
                          fontsize=11, fontweight='bold', color=DARK_TEXT)
            ax1.spines['top'].set_visible(False)
            ax1.spines['right'].set_visible(False)
            ax1.grid(axis='y', color=GRID_COLOR, linewidth=0.5)
            for i, v in enumerate(values):
                if v > 0:
                    ax1.text(i, v + max(values) * 0.01, str(v), ha='center', va='bottom', fontsize=8, fontweight='bold')
        else:
            ax1.axis('off')
            ax1.text(0.5, 0.5, 'No transaction data', ha='center', va='center', fontsize=10, color='#94A3B8', transform=ax1.transAxes)

        if co_pipeline:
            co_labels = list(co_pipeline.keys())
            co_values = list(co_pipeline.values())
            co_colors = [POS_COLOR if v > 0 else '#CBD5E1' for v in co_values]
            ax2.bar(co_labels, co_values, color=co_colors, edgecolor='white', linewidth=0.5)
            ax2.set_title(f'Combined Order Pipeline ({data.get("total_combined_orders", 0)} total)',
                          fontsize=11, fontweight='bold', color=DARK_TEXT)
            ax2.spines['top'].set_visible(False)
            ax2.spines['right'].set_visible(False)
            ax2.grid(axis='y', color=GRID_COLOR, linewidth=0.5)
            for i, v in enumerate(co_values):
                if v > 0:
                    ax2.text(i, v + max(co_values) * 0.01, str(v), ha='center', va='bottom', fontsize=8, fontweight='bold')
        else:
            ax2.axis('off')
            ax2.text(0.5, 0.5, 'No combined order data', ha='center', va='center', fontsize=10, color='#94A3B8', transform=ax2.transAxes)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_combined_orders_summary(data: Dict) -> BytesIO:
        status_breakdown = data.get('status_breakdown', {})
        if not status_breakdown:
            return _empty_chart("No combined order data for this date")

        labels = list(status_breakdown.keys())
        values = list(status_breakdown.values())
        colors_list = ['#0891B2', '#10B981', '#F59E0B', '#8B5CF6', '#EF4444', '#EC4899'][:len(labels)]

        fig, ax = plt.subplots(figsize=(8, 5))
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        wedges, texts, autotexts = ax.pie(
            values, labels=labels, autopct='%1.1f%%',
            startangle=90, colors=colors_list,
            textprops={'fontsize': 9, 'color': DARK_TEXT},
        )
        for at in autotexts:
            at.set_fontsize(8)
            at.set_color('white')
            at.set_fontweight('bold')

        total = data.get('total_orders_created', 0)
        ax.set_title(f"Combined Orders — {data.get('date', '')} ({total} total)",
                     fontsize=11, fontweight='bold', color=DARK_TEXT, pad=12)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_product_comparison(data: Dict) -> BytesIO:
        d1 = data.get('date1', {})
        d2 = data.get('date2', {})

        fig, ax = plt.subplots(figsize=(8, 5))
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        labels = ['Quantity', 'Revenue']
        x = range(len(labels))
        w = 0.35

        d1_vals = [d1.get('quantity', 0), d1.get('revenue', 0)]
        d2_vals = [d2.get('quantity', 0), d2.get('revenue', 0)]
        d1_label = d1.get('date', 'Date 1')[-10:]
        d2_label = d2.get('date', 'Date 2')[-10:]

        ax.bar([xi - w / 2 for xi in x], d1_vals, width=w, label=d1_label,
               color=POS_COLOR, edgecolor='white', linewidth=0.5)
        ax.bar([xi + w / 2 for xi in x], d2_vals, width=w, label=d2_label,
               color=ACCENT_GREEN, edgecolor='white', linewidth=0.5)

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=10, color=DARK_TEXT)

        if any(isinstance(v, float) or v > 100 for v in d1_vals + d2_vals):
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'KES {v:,.0f}'))

        product_name = '—'
        if data.get('product'):
            product_name = data['product'][0].get('name', '—')
        ax.set_title(f"Product Comparison — {product_name}",
                     fontsize=12, fontweight='bold', color=DARK_TEXT, pad=12)
        ax.legend(fontsize=9)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='y', color=GRID_COLOR, linewidth=0.5)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_registration_kits_summary(data: Dict) -> BytesIO:
        daily = data.get('daily_breakdown', {})
        if not daily:
            return _empty_chart("No registration kit data")

        sorted_days = sorted(daily.items())
        dates = [d for d, _ in sorted_days]
        kits = [info['kits'] for _, info in sorted_days]

        fig, ax = plt.subplots(figsize=(10, 5))
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        bars = ax.bar(dates, kits, color=POS_COLOR, edgecolor='white', linewidth=0.5)
        for bar, kit in zip(bars, kits):
            if kit > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        str(kit), ha='center', va='bottom', fontsize=8, fontweight='bold', color=DARK_TEXT)

        ax.set_title(f"Registration Kits — {data.get('start_date', '')} to {data.get('end_date', '')} "
                     f"({data.get('total_kits_issued', 0)} total)",
                     fontsize=12, fontweight='bold', color=DARK_TEXT, pad=12)
        ax.set_ylabel('Kits Issued', fontsize=10, color=DARK_TEXT)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='y', color=GRID_COLOR, linewidth=0.5)
        for label in ax.get_xticklabels():
            label.set_rotation(45)
            label.set_ha('right')
            label.set_fontsize(8)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_stock_by_category(data: Dict) -> BytesIO:
        categories = data.get('categories', [])
        if not categories:
            return _empty_chart("No category stock data")

        names = [c.get('name', '?')[:20] for c in categories]
        units = [c.get('total_stock_units', 0) for c in categories]
        values = [c.get('total_value', 0) for c in categories]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, max(5, len(names) * 0.35)))
        fig.patch.set_facecolor('white')

        bars1 = ax1.barh(names, units, color=POS_COLOR, edgecolor='white', linewidth=0.5)
        ax1.set_title('Stock Units by Category', fontsize=11, fontweight='bold', color=DARK_TEXT)
        ax1.set_xlabel('Units', fontsize=9, color=DARK_TEXT)
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        ax1.grid(axis='x', color=GRID_COLOR, linewidth=0.5)
        for bar, unit in zip(bars1, units):
            if unit > 0:
                ax1.text(bar.get_width() + max(units) * 0.01, bar.get_y() + bar.get_height() / 2,
                         str(unit), va='center', fontsize=8, color=DARK_TEXT)

        bars2 = ax2.barh(names, values, color=ACCENT_GREEN, edgecolor='white', linewidth=0.5)
        ax2.set_title('Stock Value by Category', fontsize=11, fontweight='bold', color=DARK_TEXT)
        ax2.set_xlabel('Value (KES)', fontsize=9, color=DARK_TEXT)
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.grid(axis='x', color=GRID_COLOR, linewidth=0.5)
        for bar, val in zip(bars2, values):
            if val > 0:
                ax2.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
                         f'KES {val:,.0f}', va='center', fontsize=7, color=DARK_TEXT)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_stock_alerts(data: Dict) -> BytesIO:
        in_stock = data.get('in_stock_count', 0)
        low_stock = data.get('low_stock_count', 0)
        out_stock = data.get('out_of_stock_count', 0)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5),
                                        gridspec_kw={'width_ratios': [1, 1.5]})
        fig.patch.set_facecolor('white')

        labels = ['In Stock', 'Low Stock', 'Out of Stock']
        values = [in_stock, low_stock, out_stock]
        colors = ['#10B981', '#F59E0B', '#EF4444']
        non_zero = [(l, v, c) for l, v, c in zip(labels, values, colors) if v > 0]
        if not non_zero:
            plt.close(fig)
            return _empty_chart("All stock levels are zero")

        nz_labels, nz_values, nz_colors = zip(*non_zero)
        wedges, texts, autotexts = ax1.pie(
            nz_values, labels=nz_labels,
            autopct='%1.1f%%', startangle=90,
            colors=nz_colors,
            textprops={'fontsize': 9, 'color': DARK_TEXT},
        )
        for at in autotexts:
            at.set_fontsize(8)
            at.set_color('white')
            at.set_fontweight('bold')
        ax1.set_title('Stock Status', fontsize=11, fontweight='bold', color=DARK_TEXT)

        ax2.axis('off')
        val_text = f"Total Value: KES {data.get('total_stock_value', 0):,.2f}"
        ax2.text(0.5, 0.7, val_text, ha='center', va='center',
                 fontsize=14, fontweight='bold', color=DARK_TEXT)

        oos = data.get('out_of_stock_products', [])[:5]
        ls = data.get('low_stock_products', [])[:5]
        y = 0.5
        if oos:
            ax2.text(0.5, y, f"Out of Stock ({len(oos)}):", ha='center', va='center',
                     fontsize=9, fontweight='bold', color=NEG_COLOR, transform=ax2.transAxes)
            y -= 0.08
            for p in oos:
                ax2.text(0.5, y, f"\u2022 {p.get('name', '?')}", ha='center', va='center',
                         fontsize=8, color=DARK_TEXT, transform=ax2.transAxes)
                y -= 0.06
        if ls:
            ax2.text(0.5, y, f"Low Stock ({len(ls)}):", ha='center', va='center',
                     fontsize=9, fontweight='bold', color='#F59E0B', transform=ax2.transAxes)
            y -= 0.08
            for p in ls:
                ax2.text(0.5, y, f"\u2022 {p.get('name', '?')} ({p.get('quantity', 0)} left)",
                         ha='center', va='center', fontsize=8, color=DARK_TEXT,
                         transform=ax2.transAxes)
                y -= 0.06

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_gateway_breakdown(data: Dict) -> BytesIO:
        gateways = data.get('gateways', [])
        labels = [g.get('type', '?') for g in gateways]
        revenues = [g.get('revenue', 0) for g in gateways]
        sales = [g.get('sales', 0) for g in gateways]

        chart_data = {
            'labels': labels,
            'datasets': [
                {'label': 'Revenue', 'values': revenues},
                {'label': 'Fulfillment', 'values': sales},
            ],
        }
        return ChartGenerator.bar_chart(
            chart_data,
            title=f"Gateway Breakdown \u2014 {data.get('date', '')}",
            ylabel='Amount (KES)',
            figsize=(10, 5),
        )

    @staticmethod
    def for_briefing(data: Dict) -> BytesIO:
        buckets = data.get('revenue_buckets', {})
        stock = data.get('stock_alerts', {})
        trend_7d = data.get('trend_7d', {})

        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(14, 10))
        fig.patch.set_facecolor('white')
        fig.suptitle(f"Daily Briefing \u2014 {data.get('date', '')}",
                     fontsize=14, fontweight='bold', color=DARK_TEXT, y=0.98)

        bucket_labels = ['PAYBILL', 'PDQ', 'TILL', 'MERCH']
        rev_vals = [buckets.get(b, {}).get('revenue', 0) for b in bucket_labels]
        sal_vals = [buckets.get(b, {}).get('sales', 0) for b in bucket_labels]
        bucket_colors = ['#0891B2', '#8B5CF6', '#F59E0B', '#10B981']

        ax1.bar(bucket_labels, rev_vals, color=bucket_colors, edgecolor='white', linewidth=0.5)
        ax1.set_title('Revenue by Bucket', fontsize=11, fontweight='bold', color=DARK_TEXT)
        ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'KES {v:,.0f}'))
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        ax1.grid(axis='y', color=GRID_COLOR, linewidth=0.5)
        for bar, val in zip(ax1.patches, rev_vals):
            if val > 0:
                ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                         f'KES {val:,.0f}', ha='center', va='bottom', fontsize=7, fontweight='bold')

        x2 = range(len(bucket_labels))
        w = 0.3
        ax2.bar([xi - w / 2 for xi in x2], rev_vals, width=w, label='Revenue',
                color='#0891B2', edgecolor='white', linewidth=0.5)
        ax2.bar([xi + w / 2 for xi in x2], sal_vals, width=w, label='Fulfilled',
                color='#10B981', edgecolor='white', linewidth=0.5)
        ax2.set_xticks(x2)
        ax2.set_xticklabels(bucket_labels, fontsize=8)
        ax2.set_title('Revenue vs Fulfillment', fontsize=11, fontweight='bold', color=DARK_TEXT)
        ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'KES {v:,.0f}'))
        ax2.legend(fontsize=8)
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.grid(axis='y', color=GRID_COLOR, linewidth=0.5)

        summary = data.get('summary', {})
        ax3.axis('off')
        lines = [
            f"Total Revenue: KES {summary.get('total_revenue', 0):,.2f}",
            f"Total Fulfilled: KES {summary.get('total_sales', 0):,.2f}",
            f"Fulfillment Rate: {summary.get('fulfillment_rate', 0):.1f}%",
            f"Transactions: {summary.get('transaction_count', 0)}",
            f"Avg Value: KES {summary.get('avg_transaction_value', 0):,.2f}",
            "",
            f"7-Day Revenue: KES {trend_7d.get('total_revenue', 0):,.2f}",
            f"Daily Avg: KES {trend_7d.get('daily_average', 0):,.2f}",
        ]
        grow = trend_7d.get('growth_rate_pct', 0)
        if grow:
            lines.append(f"Growth: {grow:+.1f}%")
        for i, line in enumerate(lines):
            ax3.text(0.1, 0.9 - i * 0.08, line, fontsize=9,
                     color=DARK_TEXT, transform=ax3.transAxes, verticalalignment='top')
        ax3.set_title('Summary', fontsize=11, fontweight='bold', color=DARK_TEXT)

        ax4.axis('off')
        stock_lines = [
            f"In Stock: {stock.get('in_stock_count', 0)}",
            f"Low Stock: {stock.get('low_stock_count', 0)}",
            f"Out of Stock: {stock.get('out_of_stock_count', 0)}",
            f"Total Value: KES {stock.get('total_stock_value', 0):,.2f}",
        ]
        for i, line in enumerate(stock_lines):
            ax4.text(0.1, 0.85 - i * 0.08, line, fontsize=9,
                     color=DARK_TEXT, transform=ax4.transAxes, verticalalignment='top')
        ax4.set_title('Stock Alerts', fontsize=11, fontweight='bold', color=DARK_TEXT)

        fig.tight_layout(rect=[0, 0, 1, 0.96])
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def for_any(tool_name: str, data: Dict) -> Optional[BytesIO]:
        router = {
            'get_revenue': BiChartAdapter.for_revenue,
            'get_revenue_by_bucket': BiChartAdapter.for_revenue,
            'get_fulfillment_by_gateway': BiChartAdapter.for_fulfillment,
            'get_trend': BiChartAdapter.for_trend,
            'get_top_products': BiChartAdapter.for_top_products,
            'get_top_products_by_revenue': BiChartAdapter.for_top_products,
            'get_revenue_vs_sales': BiChartAdapter.for_revenue_vs_sales,
            'get_month_comparison': BiChartAdapter.for_month_comparison,
            'get_year_comparison': BiChartAdapter.for_year_comparison,
            'get_stock_alerts': BiChartAdapter.for_stock_alerts,
            'get_gateway_breakdown': BiChartAdapter.for_gateway_breakdown,
            'get_briefing': BiChartAdapter.for_briefing,
            'get_merch': BiChartAdapter.for_fulfillment,
            'get_branches': BiChartAdapter.for_revenue,
            'get_product_sales_trend': BiChartAdapter.for_product_sales_trend,
            'get_product_sales': BiChartAdapter.for_top_products,
            'get_daily_sales_summary': BiChartAdapter.for_top_products,
            'get_reconciliation': BiChartAdapter.for_reconciliation,
            'get_period_revenue_vs_sales': BiChartAdapter.for_period_revenue_vs_sales,
            'get_category_sales': BiChartAdapter.for_top_products,
            'get_stock_by_category': BiChartAdapter.for_stock_by_category,
            'get_user_performance': BiChartAdapter.for_user_performance,
            'get_combined_orders_summary': BiChartAdapter.for_combined_orders_summary,
            'get_pv_summary': BiChartAdapter.for_revenue,
            'get_fulfillment_pipeline': BiChartAdapter.for_fulfillment_pipeline,
            'get_product_comparison': BiChartAdapter.for_product_comparison,
            'get_registration_kits_summary': BiChartAdapter.for_registration_kits_summary,
        }
        fn = router.get(tool_name)
        if fn is None:
            return None
        try:
            return fn(data)
        except Exception as e:
            logger.error(f"Chart generation failed for {tool_name}: {e}")
            return None


def _bar_chart(labels, values, colors, title='', ylabel='', total_label='') -> BytesIO:
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    bars = ax.bar(labels, values, color=colors, edgecolor='white', linewidth=0.5)
    ax.set_title(title, fontsize=12, fontweight='bold', color=DARK_TEXT, pad=12)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'KES {v:,.0f}'))
    ax.set_ylabel(ylabel, fontsize=10, color=DARK_TEXT)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(axis='y', color=GRID_COLOR, linewidth=0.5)

    for bar, val in zip(bars, values):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    f'KES {val:,.0f}', ha='center', va='bottom', fontsize=8, fontweight='bold', color=DARK_TEXT)

    if total_label:
        ax.text(0.98, 0.95, total_label, transform=ax.transAxes, ha='right', va='top',
                fontsize=10, fontweight='bold', color=DARK_TEXT)

    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def _empty_chart(message: str = "No data") -> BytesIO:
    fig, ax = plt.subplots(figsize=(6, 3))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')
    ax.text(0.5, 0.5, message, ha='center', va='center',
            fontsize=12, color='#94A3B8', transform=ax.transAxes)
    ax.axis('off')
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf
