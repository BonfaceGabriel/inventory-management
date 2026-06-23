import asyncio
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from django.conf import settings
from django.utils import timezone
from telegram._files.inputfile import InputFile

from payments.services.bi_core_service import BiCoreService
from payments.services.bi_compare_service import BiCompareService
from payments.services.bi_trend_service import BiTrendService
from payments.services.bi_anomaly_service import BiAnomalyService
from payments.services.bi_briefing_service import BiBriefingService
from payments.services.bi_branch_aggregator import BiBranchAggregator
from payments.services.bi_extended_service import BiExtendedService
from payments.services.bi_reconciliation_deep_dive_service import BiReconciliationDeepDiveService
from payments.services.bi_chart_adapter import BiChartAdapter

logger = logging.getLogger(__name__)


def _is_authorized(user_id: int) -> bool:
    allowed = getattr(settings, 'TELEGRAM_ALLOWED_USER_IDS', [])
    if not allowed:
        return True
    return user_id in allowed


def _fmt_kes(amount) -> str:
    return f"KES {float(amount):,.2f}"


def _fmt_pct(value) -> str:
    return f"{float(value):.1f}%"


def _arrow(direction: str) -> str:
    if direction == 'up':
        return '📈'
    if direction == 'down':
        return '📉'
    return '➡️'


def _alert_bell(amount) -> str:
    return '🔔' if float(amount) > 0 else ''


def format_briefing(data: Dict) -> str:
    d = data['date']
    s = data['summary']
    buckets = data['revenue_buckets']
    unused = data['unused_pool']
    credit = data['credit_lost_pool']
    stock = data['stock_alerts']
    recon = data['reconciliation']
    merch = data['merchandise']
    kits = data['registration_kits']
    vs_yd = data['vs_yesterday']
    trend = data['trend_7d']

    arrow = _arrow(vs_yd['revenue_direction'])

    lines = [f"📊 *Daily Briefing — {d}*", ""]

    lines.append("💰 *REVENUE*")
    lines.append(f"  Paybill:        {_fmt_kes(buckets['PAYBILL']['revenue'])}")
    lines.append(f"  PDQ:            {_fmt_kes(buckets['PDQ']['revenue'])}")
    lines.append(f"  Till:           {_fmt_kes(buckets['TILL']['revenue'])}")
    lines.append(f"  Merch:          {_fmt_kes(buckets['MERCH']['revenue'])}")
    lines.append(f"  ─────────────────────")
    lines.append(f"  *Total:*        {_fmt_kes(s['total_revenue'])}")
    lines.append(f"  Transactions:   {s['transaction_count']}")
    lines.append(f"  Avg Value:      {_fmt_kes(s['avg_transaction_value'])}")
    lines.append(f"  vs Yesterday:   {arrow} {vs_yd['revenue_change_pct']:+.1f}%")
    lines.append("")

    lines.append("📦 *FULFILLMENT (SALES)*")
    for b in ['PAYBILL', 'PDQ', 'TILL', 'MERCH']:
        bk = buckets[b]
        rate_str = _fmt_pct(bk['fulfillment_rate'])
        gap_str = _fmt_kes(bk['gap']) if bk['gap'] > 0 else '✅ Complete'
        alert = f" {bk['alert']}" if bk.get('alert') else ''
        lines.append(f"  {b}: {_fmt_kes(bk['sales'])} ({rate_str}) — Gap: {gap_str}{alert}")
    lines.append(f"  ─────────────────────")
    lines.append(f"  *Total Sales:*  {_fmt_kes(s['total_sales'])}")
    lines.append(f"  *Fulfillment:*  {_fmt_pct(s['fulfillment_rate'])}")
    lines.append("")

    if unused['amount'] > 0:
        lines.append(f"⚠️ *UNUSED PAYBILL/PDQ*")
        lines.append(f"  {_fmt_kes(unused['amount'])} in {unused['count']} txns never touched")
        lines.append(f"  → Available to fulfill tomorrow (monthly reset applies)")
        lines.append("")

    if credit['amount'] > 0:
        lines.append(f"🚫 *CREDIT LOST — PAYBILL/PDQ*")
        lines.append(f"  {_fmt_kes(credit['amount'])} in {credit['count']} txns partially fulfilled")
        lines.append(f"  → Remaining balance CANNOT be recovered")
        lines.append("")

    lines.append(f"📦 *STOCK ALERTS*")
    lines.append(f"  {stock['summary']}")
    lines.append(f"  Total Value: {_fmt_kes(stock['total_stock_value'])}")
    if stock['out_of_stock_products']:
        lines.append(f"  🚫 Out of Stock:")
        for p in stock['out_of_stock_products'][:3]:
            lines.append(f"    • {p['name']} ({p['code']})")
    if stock['low_stock_products']:
        lines.append(f"  ⚠️ Low Stock:")
        for p in stock['low_stock_products'][:3]:
            lines.append(f"    • {p['name']} — {p['quantity']} left (reorder at {p['reorder_level']})")
    lines.append("")

    bal = '✅ Balanced' if recon.get('is_balanced') else '❌ *NOT Balanced*'
    lines.append(f"🧮 *RECONCILIATION*")
    lines.append(f"  Status: {bal}")
    lines.append(f"  X = {_fmt_kes(recon.get('x_value', 0))}")
    lines.append(f"  Y = {_fmt_kes(recon.get('y_value', 0))}")
    lines.append(f"  Result: {_fmt_kes(recon.get('result', 0))}")
    lines.append("")

    lines.append(f"👕 *MERCHANDISE*")
    lines.append(f"  Fulfilled: {_fmt_kes(merch['fulfilled_revenue'])} ({merch['fulfilled_items']} items)")
    lines.append(f"  Pending: {merch['pending_orders']} orders")
    lines.append("")

    if kits['kits_issued'] > 0:
        lines.append(f"🎟 *REGISTRATION KITS*")
        lines.append(f"  Issued: {kits['kits_issued']} ({_fmt_kes(kits['total_value'])})")
        lines.append("")

    lines.append(f"📈 *7-DAY TREND*")
    lines.append(f"  Total: {_fmt_kes(trend['total_revenue'])} | Daily Avg: {_fmt_kes(trend['daily_average'])}")
    if trend['growth_rate_pct'] != 0:
        lines.append(f"  Growth: {trend['growth_rate_pct']:+.1f}%")
    lines.append("")

    if data['anomalies']['anomaly_count'] > 0:
        lines.append(f"🔍 *ANOMALIES DETECTED*")
        lines.append(f"  {data['anomalies']['anomaly_count']} unusual day(s) in last 30 days")
        for a in data['anomalies']['anomalies'][:3]:
            lines.append(f"  • {a['date']}: {_fmt_kes(a['revenue'])} (z-score: {a['z_score']})")
        lines.append("")

    return '\n'.join(lines)


def format_revenue(data: Dict) -> str:
    d = data['date']
    lines = [f"💰 *Revenue — {d}*", ""]
    for b in BiCoreService.REVENUE_BUCKETS:
        bk = data['buckets'][b]
        lines.append(f"  {b}: {_fmt_kes(bk['amount'])} ({bk['count']} txns)")
    lines.append(f"  ─────────────────")
    lines.append(f"  *Total:* {_fmt_kes(data['total'])}")
    return '\n'.join(lines)


def format_sales(data: Dict) -> str:
    d = data['date']
    lines = [f"📦 *Fulfillment (by Gateway) — {d}*", ""]
    for b in BiCoreService.SALES_BUCKETS:
        bk = data['buckets'][b]
        lines.append(f"  {b}: {_fmt_kes(bk['amount'])} ({bk['count']} txns)")
    lines.append(f"  ─────────────────")
    lines.append(f"  *Total Fulfilled:* {_fmt_kes(data['total'])}")
    return '\n'.join(lines)


def format_stock_alerts(data: Dict) -> str:
    lines = ["📦 *Stock Alerts*", ""]
    lines.append(f"  ✅ In Stock:   {data['in_stock_count']}")
    lines.append(f"  ⚠️ Low Stock:  {data['low_stock_count']}")
    lines.append(f"  🚫 Out of Stock: {data['out_of_stock_count']}")
    lines.append(f"  Total Value: {_fmt_kes(data['total_stock_value'])}")
    lines.append("")
    if data['out_of_stock_products']:
        lines.append("*Out of Stock:*")
        for p in data['out_of_stock_products'][:10]:
            lines.append(f"  🚫 {p['name']}")
    if data['low_stock_products']:
        lines.append("")
        lines.append("*Low Stock:*")
        for p in data['low_stock_products'][:10]:
            lines.append(f"  ⚠️ {p['name']} — {p['quantity']} left")
    return '\n'.join(lines)


def format_reconciliation(data: Dict) -> str:
    lines = ["🧮 *Reconciliation*", ""]
    bal = '✅ Balanced' if data.get('is_balanced') else '❌ *NOT Balanced*'
    lines.append(f"  Result: {bal}")
    lines.append(f"  X = {_fmt_kes(data.get('x_value', 0))}")
    lines.append(f"  Y = {_fmt_kes(data.get('y_value', 0))}")
    lines.append(f"  X + Y = {_fmt_kes(data.get('result', 0))}")
    lines.append("")
    xf = data.get('x_formula', {})
    lines.append("*X = Paybill - Unused + PDQ + Previous - Sales*")
    lines.append(f"  Paybill:  {_fmt_kes(xf.get('mpesa_paybill', 0))}")
    lines.append(f"  Unused:   -{_fmt_kes(xf.get('unused', 0))}")
    lines.append(f"  PDQ:      +{_fmt_kes(xf.get('pdq', 0))}")
    lines.append(f"  Previous: +{_fmt_kes(xf.get('previous', 0))}")
    lines.append(f"  Sales:    -{_fmt_kes(xf.get('sales', 0))}")
    lines.append("")
    yf = data.get('y_formula', {})
    lines.append("*Y = Till - Credit - KITS*")
    lines.append(f"  Till:   {_fmt_kes(yf.get('till', 0))}")
    lines.append(f"  Credit: -{_fmt_kes(yf.get('credit', 0))}")
    lines.append(f"  KITS:   -{_fmt_kes(yf.get('kits', 0))}")
    return '\n'.join(lines)


def format_reconciliation_deep_dive(data: Dict) -> str:
    date_str = data.get('date', '?')
    severity = data.get('severity', 'BALANCED')
    balanced = data.get('is_balanced', False)

    sev_icons = {'BALANCED': '\u2705', 'MINOR': '\u26a0\ufe0f', 'MAJOR': '\U0001f534', 'CRITICAL': '\U0001f6a8'}
    sev_icon = sev_icons.get(severity, '\u2753')

    lines = [f"{sev_icon} *Reconciliation Deep Dive — {date_str}*", ""]

    bal_text = '\u2705 Balanced' if balanced else '\u274c *NOT Balanced*'
    lines.append(f"  {bal_text}")
    lines.append(f"  X = {_fmt_kes(data.get('x_value', 0))}")
    lines.append(f"  Y = {_fmt_kes(data.get('y_value', 0))}")
    lines.append(f"  X + Y = {_fmt_kes(data.get('result', 0))}")
    lines.append(f"  Severity: {severity}")
    lines.append("")

    comp = data.get('components', {})
    lines.append("*Formula Components:*")
    for key, label in [
        ('mpesa_paybill', 'Paybill'),
        ('unused', 'Unused'),
        ('pdq', 'PDQ'),
        ('previous', 'Previous'),
        ('till', 'Till'),
        ('credit', 'Credit'),
        ('kits', 'KITS'),
        ('sales', 'Sales'),
    ]:
        c = comp.get(key, {})
        lines.append(f"  {label}: {_fmt_kes(c.get('amount', 0))} ({c.get('count', 0)} txns)")
    lines.append("")

    issues = data.get('issues', [])
    if issues:
        lines.append(f"*Issues Found: {len(issues)}*")
        lines.append("")
        for issue in issues:
            itype = issue.get('type', '')
            isev = issue.get('severity', '')
            icount = issue.get('count', 0)
            iamt = issue.get('total_amount', 0)
            irec = issue.get('recommendation', '')

            isev_icon = sev_icons.get(isev, '\u2753')
            lines.append(f"{isev_icon} *{itype.replace('_', ' ').title()}*")
            lines.append(f"  Count: {icount} | Amount: {_fmt_kes(iamt)}")
            if irec:
                lines.append(f"  \U0001f4a1 {irec}")

            txs = issue.get('transactions', [])
            if txs:
                for tx in txs[:5]:
                    tid = tx.get('tx_id', '')
                    tamt = _fmt_kes(tx.get('amount', 0))
                    lines.append(f"  \u2022 `{tid}` \u2014 {tamt}")
                if len(txs) > 5:
                    lines.append(f"  \u2026 and {len(txs) - 5} more")

            cos = issue.get('combined_orders', [])
            if cos:
                for co in cos[:5]:
                    cid = co.get('combined_order_id', '')
                    crem = _fmt_kes(co.get('remaining', 0))
                    cstat = co.get('status', '')
                    lines.append(f"  \u2022 `{cid}` \u2014 {crem} remaining ({cstat})")
                if len(cos) > 5:
                    lines.append(f"  \u2026 and {len(cos) - 5} more")

            lines.append("")
    else:
        lines.append("\u2705 No issues found \u2014 everything is balanced!")
        lines.append("")

    return '\n'.join(lines)


def format_compare(data: Dict) -> str:
    lines = [f"📊 *Comparison: {data.get('metric', '').replace('_', ' ').title()}*", ""]
    p1 = data.get('period1', {})
    p2 = data.get('period2', {})
    lines.append(f"  {p1.get('date', '')}: {_fmt_kes(p1.get('value', 0))}")
    lines.append(f"  {p2.get('date', '')}: {_fmt_kes(p2.get('value', 0))}")
    lines.append(f"  Change: {_fmt_kes(data.get('absolute_change', 0))}")
    lines.append(f"  %: {data.get('percentage_change', 0):+.1f}%")
    return '\n'.join(lines)


def format_revenue_vs_sales(data: Dict) -> str:
    lines = ["📊 *Revenue vs Sales*", ""]
    lines.append(f"  📅 {data.get('date', '')}")
    lines.append(f"  💰 Revenue:       {_fmt_kes(data.get('total_revenue', 0))}")
    lines.append(f"  📦 Sales:         {_fmt_kes(data.get('total_sales', 0))}")
    lines.append(f"  📉 Gap:           {_fmt_kes(data.get('gap', 0))}")
    lines.append(f"  ✅ Fulfillment:   {_fmt_pct(data.get('fulfillment_rate', 0))}")
    lines.append("")
    lines.append("*Paybill/PDQ Status:*")
    lines.append(f"  Unused (carries over):  {_fmt_kes(data.get('unused_pool', {}).get('amount', 0))}")
    lines.append(f"  Credit Lost (gone):    {_fmt_kes(data.get('credit_lost_pool', {}).get('amount', 0))}")
    lines.append("")
    lines.append("*Per Bucket:*")
    for b, bk in data.get('buckets', {}).items():
        lines.append(f"  {b}: {_fmt_kes(bk['revenue'])} → {_fmt_kes(bk['sales'])} ({_fmt_pct(bk['fulfillment_rate'])})")
    return '\n'.join(lines)


def format_branch_summary(data: Dict) -> str:
    lines = ["🏢 *Branch Performance Summary*", ""]
    lines.append(f"  Date: {data.get('date', '')}")
    lines.append(f"  *Total Revenue:* {_fmt_kes(data.get('total_revenue', 0))}")
    lines.append(f"  *Total Sales:*   {_fmt_kes(data.get('total_sales', 0))}")
    lines.append("")
    for branch in data.get('branches', []):
        status_icon = '🟢' if branch.get('status') == 'ok' else '🔴'
        lines.append(f"{status_icon} *{branch.get('name', 'Unknown')}*")
        if branch.get('status') == 'ok':
            lines.append(f"     Revenue: {_fmt_kes(branch.get('revenue', 0))}")
            lines.append(f"     Sales:   {_fmt_kes(branch.get('sales', 0))}")
            if branch.get('unused', 0) > 0:
                lines.append(f"     Unused:  {_fmt_kes(branch.get('unused', 0))}")
            if branch.get('stock_alerts', 0) > 0:
                lines.append(f"     Alerts:  {branch.get('stock_alerts')} issues")
        else:
            lines.append(f"     ⚠️ Unreachable")
        lines.append("")
    return '\n'.join(lines)


def format_merch(data: Dict) -> str:
    lines = ["👕 *Merchandise*", ""]
    lines.append(f"  Fulfilled Revenue: {_fmt_kes(data.get('fulfilled_revenue', 0))}")
    lines.append(f"  Items Fulfilled:   {data.get('fulfilled_items', 0)}")
    lines.append(f"  Orders Fulfilled:  {data.get('fulfilled_orders', 0)}")
    lines.append(f"  Pending Orders:    {data.get('pending_orders', 0)}")
    return '\n'.join(lines)


def format_trend(data: Dict) -> str:
    lines = [f"📈 *Trend — Last {data.get('period_days', 30)} Days*", ""]
    lines.append(f"  Total Revenue: {_fmt_kes(data.get('total_revenue', 0))}")
    lines.append(f"  Daily Avg:     {_fmt_kes(data.get('daily_average', 0))}")
    lines.append(f"  Min Day:       {_fmt_kes(data.get('min_daily', 0))}")
    lines.append(f"  Max Day:       {_fmt_kes(data.get('max_daily', 0))}")
    if data.get('growth_rate_pct', 0) != 0:
        growth = data['growth_rate_pct']
        arrow = _arrow('up' if growth > 0 else 'down')
        lines.append(f"  Growth Rate:   {arrow} {growth:+.1f}%")
    lines.append("")
    lines.append("*Last 7 days:*")
    for dp in data.get('data_points', [])[-7:]:
        lines.append(f"  {dp['date']}: {_fmt_kes(dp['revenue'])}")
    return '\n'.join(lines)


def format_anomaly(data: Dict) -> str:
    lines = ["🔍 *Anomaly Detection*", ""]
    lines.append(f"  Period: Last {data.get('period_days', 30)} days")
    lines.append(f"  Mean:   {_fmt_kes(data.get('mean', 0))}")
    lines.append(f"  StdDev: {_fmt_kes(data.get('std_dev', 0))}")
    lines.append(f"  Anomalies Found: {data.get('anomaly_count', 0)}")
    lines.append("")
    if data.get('anomalies'):
        lines.append("*Unusual days:*")
        for a in data['anomalies']:
            lines.append(f"  {a['date']}: {_fmt_kes(a.get('revenue', a.get('value', 0)))} (z={a.get('z_score', 0)})")
    return '\n'.join(lines)


def format_product_sales(data: Dict) -> str:
    if not data.get('found'):
        return f"❌ {data.get('message', 'Product not found')}"
    lines = [f"📦 *Product Sales — {data['date']}*", ""]
    for p in data['products']:
        lines.append(f"  *{p['name']}* ({p['code']})")
        lines.append(f"  Stock: {p['current_stock']} | Price: {_fmt_kes(p['price'])}")
    lines.append("")
    lines.append(f"  Quantity Sold: {data['total_quantity_sold']}")
    lines.append(f"  Revenue:       {_fmt_kes(data['total_revenue'])}")
    lines.append(f"  Cost:          {_fmt_kes(data['total_cost'])}")
    lines.append(f"  PV:            {_fmt_kes(data['total_pv'])}")
    return '\n'.join(lines)


def format_product_stock(data: Dict) -> str:
    if not data.get('found'):
        return f"❌ {data.get('message', 'Product not found')}"
    lines = ["📦 *Product Stock*", ""]
    for p in data['products']:
        icons = {'OUT_OF_STOCK': '🚫', 'LOW_STOCK': '⚠️', 'IN_STOCK': '✅'}
        icon = icons.get(p['stock_status'], '❓')
        lines.append(f"{icon} *{p['name']}* ({p['code']})")
        if p.get('category'):
            lines.append(f"   Category: {p['category']}")
        lines.append(f"   Qty: {p['quantity']} / Reorder: {p['reorder_level']}")
        lines.append(f"   Price: {_fmt_kes(p['price'])} | Value: {_fmt_kes(p['stock_value'])}")
        lines.append("")
    lines.append(f"Total Stock Value: {_fmt_kes(data['total_stock_value'])}")
    return '\n'.join(lines)


def format_top_products(data: Dict) -> str:
    lines = [f"🏆 *Top Products — {data['date']}*", ""]
    for i, p in enumerate(data['products'], 1):
        medal = {1: '🥇', 2: '🥈', 3: '🥉'}.get(i, f'{i}.')
        lines.append(f"{medal} *{p['name']}*")
        lines.append(f"   Qty: {p['quantity_sold']} | Rev: {_fmt_kes(p['revenue'])}")
        if p.get('category'):
            lines.append(f"   Category: {p['category']}")
        lines.append("")
    lines.append(f"Total products sold: {data['total_products_sold']}")
    return '\n'.join(lines)


def format_top_products_by_revenue(data: Dict) -> str:
    lines = [f"🏆 *Top Products by Revenue — {data['date']}*", ""]
    for i, p in enumerate(data['products'], 1):
        medal = {1: '🥇', 2: '🥈', 3: '🥉'}.get(i, f'{i}.')
        lines.append(f"{medal} *{p['name']}*")
        lines.append(f"   Rev: {_fmt_kes(p['revenue'])} | Qty: {p['quantity_sold']}")
        if p.get('category'):
            lines.append(f"   Category: {p['category']}")
        lines.append("")
    lines.append(f"Total products sold: {data['total_products_sold']}")
    return '\n'.join(lines)


def format_category_sales(data: Dict) -> str:
    if not data.get('found'):
        return f"❌ {data.get('message', 'Category not found')}"
    lines = [f"📂 *Category Sales — {data['date']}*", ""]
    for c in data['categories']:
        lines.append(f"  📁 {c['name']}")
    lines.append("")
    lines.append(f"  Quantity Sold: {data['total_quantity_sold']}")
    lines.append(f"  Revenue:       {_fmt_kes(data['total_revenue'])}")
    lines.append(f"  Cost:          {_fmt_kes(data['total_cost'])}")
    lines.append(f"  PV:            {_fmt_kes(data['total_pv'])}")
    return '\n'.join(lines)


def format_stock_by_category(data: Dict) -> str:
    lines = ["📂 *Stock by Category*", ""]
    for c in data['categories']:
        lines.append(f"  📁 *{c['name']}*")
        lines.append(f"     Products: {c['product_count']} | Units: {c['total_stock_units']}")
        lines.append(f"     Value: {_fmt_kes(c['total_value'])}")
        lines.append("")
    lines.append(f"Total: {data['total_categories']} categories, {data['total_products']} products")
    lines.append(f"Total Stock Value: {_fmt_kes(data['total_stock_value'])}")
    return '\n'.join(lines)


def format_inventory_value(data: Dict) -> str:
    lines = ["💰 *Inventory Value*", ""]
    lines.append(f"  Products:       {data['total_products']}")
    lines.append(f"  Total Units:    {data['total_stock_units']}")
    lines.append(f"  At Retail:      {_fmt_kes(data['total_value_at_retail'])}")
    lines.append(f"  At Cost:        {_fmt_kes(data['total_value_at_cost'])}")
    lines.append(f"  Total PV:       {_fmt_kes(data['total_pv'])}")
    return '\n'.join(lines)


def format_stock_movements(data: Dict) -> str:
    if not data.get('found', True) is True and data.get('message'):
        return f"❌ {data.get('message', 'No data')}"
    lines = [f"📋 *Stock Movements — Last {data['days']} Days*", ""]
    if data.get('product_query'):
        lines.append(f"  Product: {data['product_query']}")
    lines.append(f"  Total Movements: {data['total_movements']}")
    lines.append("")
    for mtype, info in data.get('by_type', {}).items():
        lines.append(f"  {mtype}: {info['count']} ({info['total_change']:+d} units)")
    if data['movements']:
        lines.append("")
        lines.append("*Recent:*")
        for m in data['movements'][:10]:
            lines.append(f"  {m['type']}: {m['product']} ({m['quantity_change']:+d}) — {m['performed_by']}")
    return '\n'.join(lines)


def format_search_transactions(data: Dict) -> str:
    lines = [f"🔍 *Transaction Search: \"{data['query']}\"*", ""]
    lines.append(f"Found: {data['total_found']}")
    lines.append("")
    for t in data['transactions'][:10]:
        status_icon = {
            'FULFILLED': '✅', 'CANCELLED': '❌', 'PARTIALLY_FULFILLED': '🔄',
            'PROCESSING': '⏳', 'NOT_PROCESSED': '🆕', 'COMBINED_FULFILLED': '✅',
        }.get(t['status'], '❓')
        lines.append(f"{status_icon} `{t['tx_id']}` — {_fmt_kes(t['amount'])} — {t['status_display']}")
        if t['sender_name']:
            lines.append(f"   👤 {t['sender_name']} ({t['sender_phone'] or '—'})")
        lines.append(f"   🕐 {t['timestamp'][:10] if t['timestamp'] else '—'} | {t['gateway_type'] or '—'}")
        lines.append("")
    return '\n'.join(lines)


def format_transaction_detail(data: Dict) -> str:
    if not data.get('found'):
        return f"❌ {data.get('message', 'Transaction not found')}"
    t = data
    status_icon = {
        'FULFILLED': '✅', 'CANCELLED': '❌', 'PARTIALLY_FULFILLED': '🔄',
        'PROCESSING': '⏳', 'NOT_PROCESSED': '🆕', 'COMBINED_FULFILLED': '✅',
    }.get(t['status'], '❓')
    lines = [f"{status_icon} *Transaction: {t['tx_id']}*", ""]
    lines.append(f"  Amount:         {_fmt_kes(t['amount'])}")
    lines.append(f"  Fulfilled:      {_fmt_kes(t['amount_fulfilled'])}")
    lines.append(f"  Remaining:      {_fmt_kes(t['remaining'])}")
    lines.append(f"  Status:         {t['status_display']}")
    lines.append(f"  Gateway:        {t['gateway']} ({t['gateway_type']})")
    if t['sender_name']:
        lines.append(f"  Customer:       {t['sender_name']} ({t['sender_phone'] or '—'})")
    lines.append(f"  Date:           {t['timestamp'][:10] if t['timestamp'] else '—'}")
    if t.get('completed_by'):
        lines.append(f"  Completed by:   {t['completed_by']}")
    if t.get('processed_by'):
        lines.append(f"  Processed by:   {t['processed_by']}")
    if t.get('total_cost', 0):
        lines.append(f"  Cost:           {_fmt_kes(t['total_cost'])}")
    if t.get('total_pv', 0):
        lines.append(f"  PV:             {_fmt_kes(t['total_pv'])}")
    if t.get('line_items'):
        lines.append("")
        lines.append(f"*Items ({len(t['line_items'])}):*")
        for li in t['line_items']:
            lines.append(f"  • {li['product_name']} x{li['quantity']} @ {_fmt_kes(li['unit_price'])} = {_fmt_kes(li['line_total'])}")
    if t.get('combined_order'):
        co = t['combined_order']
        lines.append("")
        lines.append(f"*Combined Order:* {co['combined_order_id']} ({co['status']})")
    return '\n'.join(lines)


def format_customer(data: Dict) -> str:
    if not data.get('found'):
        return f"❌ {data.get('message', 'Customer not found')}"
    lines = [f"👤 *Customer Search: \"{data['query']}\"*", ""]
    lines.append(f"Customers found: {data['customers_found']}")
    lines.append("")
    for c in data['customers']:
        lines.append(f"*{c['name']}* ({c['phone'] or '—'})")
        lines.append(f"  Spent: {_fmt_kes(c['total_spent'])} | Fulfilled: {_fmt_kes(c['total_fulfilled'])}")
        lines.append(f"  Txns: {c['transaction_count']} | Rate: {c['fulfillment_rate']}%")
        lines.append(f"  Last: {c['last_purchase'][:10] if c['last_purchase'] else '—'}")
        lines.append("")
    return '\n'.join(lines)


def format_pending_fulfillments(data: Dict) -> str:
    lines = ["⏳ *Pending Fulfillments*", ""]
    lines.append(f"*Transactions:* {data['total_pending_transactions']}")
    for t in data['pending_transactions'][:10]:
        lines.append(f"  `{t['tx_id']}` — {_fmt_kes(t['remaining'])} left — {t['status_display']} ({t['days_old']}d old)")
        if t['sender_name']:
            lines.append(f"    👤 {t['sender_name']}")
    lines.append("")
    lines.append(f"*Combined Orders:* {data['total_pending_combined_orders']}")
    for c in data['pending_combined_orders'][:10]:
        lines.append(f"  `{c['id']}` — {_fmt_kes(c['remaining'])} left — {c['status']} ({c['days_old']}d old)")
    return '\n'.join(lines)


def format_fulfillment_pipeline(data: Dict) -> str:
    lines = ["🏗️ *Fulfillment Pipeline*", ""]
    lines.append("*Transactions:*")
    for status_name, count in data['transaction_pipeline'].items():
        lines.append(f"  {status_name}: {count}")
    lines.append("")
    lines.append("*Combined Orders:*")
    for status_name, count in data['combined_order_pipeline'].items():
        lines.append(f"  {status_name}: {count}")
    lines.append("")
    lines.append(f"Total: {data['total_transactions']} txns, {data['total_combined_orders']} combined")
    return '\n'.join(lines)


def format_user_performance(data: Dict) -> str:
    if not data.get('users'):
        return "❌ No users found"
    lines = [f"👥 *User Performance — {data['date']}*", ""]
    for u in data['users']:
        if u['total_actions'] == 0:
            continue
        lines.append(f"*{u['username']}* ({u['role']})")
        if u['transactions_processed']:
            lines.append(f"  Processed: {u['transactions_processed']}")
        if u['transactions_activated']:
            lines.append(f"  Activated: {u['transactions_activated']}")
        if u['transactions_completed']:
            lines.append(f"  Completed: {u['transactions_completed']}")
        if u['items_scanned']:
            lines.append(f"  Scanned:   {u['items_scanned']} items")
        if u['combined_orders_created']:
            lines.append(f"  Combined:  {u['combined_orders_created']}")
        lines.append("")
    return '\n'.join(lines)


def format_combined_orders(data: Dict) -> str:
    lines = [f"🔗 *Combined Orders — {data['date']}*", ""]
    lines.append(f"Created: {data['total_orders_created']}")
    lines.append(f"Total Amount: {_fmt_kes(data['total_amount'])}")
    lines.append(f"Fulfilled:    {_fmt_kes(data['total_amount_fulfilled'])}")
    lines.append("")
    for status, count in data.get('status_breakdown', {}).items():
        lines.append(f"  {status}: {count}")
    if data['orders']:
        lines.append("")
        for c in data['orders'][:10]:
            lines.append(f"  `{c['id']}` — {_fmt_kes(c['total_amount'])} — {c['status']}")
    return '\n'.join(lines)


def format_gateway_breakdown(data: Dict) -> str:
    lines = [f"🏦 *Payment Gateway Breakdown — {data['date']}*", ""]
    for g in data['gateways']:
        lines.append(f"*{g['type']}* ({g['name']})")
        lines.append(f"  Count:   {g['count']}")
        lines.append(f"  Revenue: {_fmt_kes(g['revenue'])}")
        lines.append(f"  Sales:   {_fmt_kes(g['sales'])}")
        lines.append("")
    return '\n'.join(lines)


def format_period_revenue(data: Dict) -> str:
    lines = [f"💰 *Revenue — {data['start_date']} to {data['end_date']}*", ""]
    lines.append(f"  Total:       {_fmt_kes(data['total_revenue'])}")
    lines.append(f"  Txns:        {data['total_transactions']}")
    lines.append(f"  Daily Avg:   {_fmt_kes(data['daily_average'])}")
    lines.append(f"  Days:        {data['days_in_range']}")
    lines.append("")
    lines.append("*By Bucket:*")
    for b, v in data.get('buckets', {}).items():
        if v > 0:
            lines.append(f"  {b}: {_fmt_kes(v)}")
    return '\n'.join(lines)


def format_period_sales(data: Dict) -> str:
    lines = [f"📦 *Sales — {data['start_date']} to {data['end_date']}*", ""]
    lines.append(f"  Total:       {_fmt_kes(data['total_sales'])}")
    lines.append(f"  Txns:        {data['total_transactions']}")
    lines.append(f"  Daily Avg:   {_fmt_kes(data['daily_average'])}")
    return '\n'.join(lines)


def format_period_revenue_vs_sales(data: Dict) -> str:
    lines = [f"📊 *Revenue vs Sales — {data['start_date']} to {data['end_date']}*", ""]
    lines.append(f"  Revenue:       {_fmt_kes(data['total_revenue'])}")
    lines.append(f"  Sales:         {_fmt_kes(data['total_sales'])}")
    lines.append(f"  Gap:           {_fmt_kes(data['gap'])}")
    lines.append(f"  Fulfillment:   {_fmt_pct(data['fulfillment_rate'])}")
    lines.append(f"  Transactions:  {data['transaction_count']}")
    return '\n'.join(lines)


def format_month_comparison(data: Dict) -> str:
    c = data['current_period']
    p = data['previous_period']
    ch = data['change']
    lines = ["📊 *Month-over-Month Comparison*", ""]
    lines.append(f"*This Month ({c['start']} — {c['end']}, {c['days']}d)*")
    lines.append(f"  Revenue: {_fmt_kes(c['revenue'])}")
    lines.append(f"  Sales:   {_fmt_kes(c['sales'])}")
    lines.append(f"  Rate:    {c['fulfillment_rate']}%")
    lines.append("")
    lines.append(f"*Last Month ({p['start']} — {p['end']}, {p['days']}d)*")
    lines.append(f"  Revenue: {_fmt_kes(p['revenue'])}")
    lines.append(f"  Sales:   {_fmt_kes(p['sales'])}")
    lines.append(f"  Rate:    {p['fulfillment_rate']}%")
    lines.append("")
    arrow_rev = _arrow('up' if ch['revenue_pct'] > 0 else 'down')
    arrow_sales = _arrow('up' if ch['sales_pct'] > 0 else 'down')
    lines.append(f"*Change:*")
    lines.append(f"  Revenue: {arrow_rev} {ch['revenue_pct']:+.1f}% ({_fmt_kes(ch['revenue'])})")
    lines.append(f"  Sales:   {arrow_sales} {ch['sales_pct']:+.1f}% ({_fmt_kes(ch['sales'])})")
    return '\n'.join(lines)


def format_year_comparison(data: Dict) -> str:
    c = data['current_period']
    p = data['previous_period']
    ch = data['change']
    lines = ["📊 *Year-over-Year Comparison*", ""]
    lines.append(f"*{data['current_year']} YTD ({c['start']} — {c['end']})*")
    lines.append(f"  Revenue: {_fmt_kes(c['revenue'])}")
    lines.append(f"  Sales:   {_fmt_kes(c['sales'])}")
    lines.append(f"  Rate:    {c['fulfillment_rate']}%")
    lines.append("")
    lines.append(f"*{data['previous_year']} ({p['start']} — {p['end']})*")
    lines.append(f"  Revenue: {_fmt_kes(p['revenue'])}")
    lines.append(f"  Sales:   {_fmt_kes(p['sales'])}")
    lines.append(f"  Rate:    {p['fulfillment_rate']}%")
    lines.append("")
    arrow_rev = _arrow('up' if ch['revenue_pct'] > 0 else 'down')
    arrow_sales = _arrow('up' if ch['sales_pct'] > 0 else 'down')
    lines.append(f"*Change:*")
    lines.append(f"  Revenue: {arrow_rev} {ch['revenue_pct']:+.1f}% ({_fmt_kes(ch['revenue_change'])})")
    lines.append(f"  Sales:   {arrow_sales} {ch['sales_pct']:+.1f}% ({_fmt_kes(ch['sales_change'])})")
    return '\n'.join(lines)


def format_product_sales_trend(data: Dict) -> str:
    if not data.get('found', True):
        return f"❌ {data.get('message', 'Product not found')}"
    lines = [f"📈 *Product Sales Trend — Last {data['period_days']} Days*", ""]
    for p in data['product_info']:
        lines.append(f"  {p['name']} ({p['code']})")
    lines.append("")
    lines.append(f"  Total Qty:  {data['total_quantity']}")
    lines.append(f"  Total Rev:  {_fmt_kes(data['total_revenue'])}")
    lines.append(f"  Daily Avg:  {data['daily_average_qty']} units / {_fmt_kes(data['daily_average_revenue'])}")
    lines.append(f"  Days Sold:  {data['days_with_sales']}/{data['period_days']}")
    lines.append("")
    lines.append("*Last 7 days:*")
    for dp in data['data_points'][-7:]:
        icon = '📦' if dp['quantity'] > 0 else '—'
        lines.append(f"  {dp['date']}: {icon} {dp['quantity']} ({_fmt_kes(dp['revenue'])})")
    return '\n'.join(lines)


def format_product_comparison(data: Dict) -> str:
    if not data.get('found', True):
        return f"❌ {data.get('message', 'Product not found')}"
    lines = ["📊 *Product Comparison*", ""]
    for p in data['product']:
        lines.append(f"  {p['name']} ({p['code']})")
    lines.append("")
    d1 = data['date1']
    d2 = data['date2']
    ch = data['change']
    lines.append(f"*{d1['date']}:*  Qty {d1['quantity']} | Rev {_fmt_kes(d1['revenue'])}")
    lines.append(f"*{d2['date']}:*  Qty {d2['quantity']} | Rev {_fmt_kes(d2['revenue'])}")
    lines.append("")
    arrow_qty = _arrow('up' if ch['quantity_change'] > 0 else 'down') if ch['quantity_change'] != 0 else '➡️'
    arrow_rev = _arrow('up' if ch['revenue_change'] > 0 else 'down') if ch['revenue_change'] != 0 else '➡️'
    lines.append(f"Qty:  {arrow_qty} {ch['quantity_change']:+d} ({ch['quantity_pct']:+.1f}%)")
    lines.append(f"Rev:  {arrow_rev} {_fmt_kes(ch['revenue_change'])} ({ch['revenue_pct']:+.1f}%)")
    return '\n'.join(lines)


def format_registration_kits_summary(data: Dict) -> str:
    lines = [f"🎟 *Registration Kits — {data['start_date']} to {data['end_date']}*", ""]
    lines.append(f"  Total Issued: {data['total_kits_issued']}")
    lines.append(f"  Total Value:  {_fmt_kes(data['total_value'])}")
    lines.append(f"  Transactions: {data['total_transactions']}")
    if data['daily_breakdown']:
        lines.append("")
        lines.append("*Daily:*")
        for day, info in sorted(data['daily_breakdown'].items()):
            lines.append(f"  {day}: {info['kits']} kits ({info['count']} txns)")
    return '\n'.join(lines)


def format_pv_summary(data: Dict) -> str:
    lines = [f"⭐ *PV Summary — {data['date']}*", ""]
    lines.append(f"  Total PV:  {_fmt_kes(data['total_pv'])}")
    lines.append(f"  Items:     {data['total_items']}")
    lines.append("")
    for b, v in data.get('per_bucket', {}).items():
        if v > 0:
            lines.append(f"  {b}: {_fmt_kes(v)}")
    return '\n'.join(lines)


def format_total_cost(data: Dict) -> str:
    lines = [f"📋 *Cost of Goods Sold — {data['date']}*", ""]
    lines.append(f"  Total COGS: {_fmt_kes(data['total_cost_of_goods_sold'])}")
    lines.append(f"  Items Sold: {data['total_items_sold']}")
    return '\n'.join(lines)


def format_products(data: Dict) -> str:
    total = data.get('total_products', 0)
    lines = [f"📦 *Products — {total} found*", ""]
    filters = data.get('filters', {})
    active_filters = {k: v for k, v in filters.items() if v}
    if active_filters:
        lines.append(f"  Filters: {', '.join(f'{k}={v}' for k, v in active_filters.items())}")
        lines.append("")
    if total == 0:
        lines.append("No products match the given filters.")
        return '\n'.join(lines)
    for p in (data.get('products') or [])[:30]:
        icons = {'OUT_OF_STOCK': '🚫', 'LOW_STOCK': '⚠️', 'IN_STOCK': '✅'}
        icon = icons.get(p.get('stock_status'), '❓')
        lines.append(f"{icon} *{p.get('name', '?')}* ({p.get('code', '?')})")
        if p.get('category'):
            lines.append(f"   Cat: {p['category']}")
        lines.append(f"   Qty: {p.get('quantity', 0)} | Price: {_fmt_kes(p.get('price', 0))}")
        lines.append("")
    if total > 30:
        lines.append(f"... and {total - 30} more products")
    return '\n'.join(lines)


def format_sales_summary(data: Dict) -> str:
    date_str = data.get('date', '?')
    lines = [f"📊 *Daily Sales Summary — {date_str}*", ""]
    if data.get('total_quantity_sold', 0) == 0:
        lines.append("No sales data for this date.")
        return '\n'.join(lines)
    lines.append(f"  Unique Products: {data.get('unique_products', 0)}")
    lines.append(f"  Total Qty Sold:  {data.get('total_quantity_sold', 0)}")
    lines.append(f"  Total Revenue:   {_fmt_kes(data.get('total_revenue', 0))}")
    lines.append(f"  Total Cost:      {_fmt_kes(data.get('total_cost', 0))}")
    lines.append(f"  Total PV:        {_fmt_kes(data.get('total_pv', 0))}")
    lines.append("")
    if data.get('top_products'):
        lines.append("*Top Products:*")
        for p in data['top_products'][:10]:
            lines.append(f"  📦 {p.get('name', '?')} — {p.get('quantity_sold', 0)} x {_fmt_kes(p.get('revenue', 0))}")
    return '\n'.join(lines)


def _run_sync(func, *args, **kwargs):
    return asyncio.get_event_loop().run_in_executor(None, func, *args, **kwargs)


async def handle_message(text: str, user_id: int = None) -> str:
    text = text.strip().lower()

    if user_id and not _is_authorized(user_id):
        return "⛔ Unauthorized. Please contact admin to add your Telegram ID."

    today = timezone.localdate()

    if text in ['/start', '/help']:
        return (
            "🤖 *BI Copilot — BF SUMA Eagle Shop*\n\n"
            "*Commands:*\n"
            "`/briefing [date]` — EOD briefing\n"
            "`/revenue [date]` — Revenue by bucket\n"
            "`/sales [date]` — Fulfillment by gateway\n"
            "`/stock` — Stock alerts\n"
            "`/inventory` — Total inventory value\n"
             "`/recon [date]` — Reconciliation status\n"
             "`/recon_deep [date] [--chart] [--xlsx]` — Deep reconciliation dive\n"
            "`/compare D1 D2` — Compare two days\n"
            "`/trend [N]` — Revenue trend\n"
            "`/anomalies [N]` — Anomaly detection\n"
            "`/branches` — Branch performance\n"
            "`/merch [date]` — Merchandise\n"
            "`/vs [date]` — Revenue vs Fulfillment\n"
            "`/product_stock <name>` — Product stock\n"
            "`/product_sales <name> [date]` — Product sales\n"
            "`/product_trend <name> [N]` — Product sales trend\n"
            "`/product_compare <name> D1 D2` — Product compare\n"
            "`/top [N] [date]` — Top selling products\n"
            "`/top_revenue [N] [date]` — Top by revenue\n"
            "`/category <name> [date]` — Category sales\n"
            "`/stock_by_category` — Stock by category\n"
            "`/txn <id/name/phone>` — Search transactions\n"
            "`/txn_detail <tx_id>` — Full transaction detail\n"
            "`/customer <name/phone>` — Customer lookup\n"
            "`/pending` — Pending fulfillments\n"
            "`/pipeline` — Fulfillment pipeline\n"
            "`/user [name] [date]` — User performance\n"
            "`/gateways [date]` — Gateway breakdown\n"
            "`/combined [date]` — Combined order stats\n"
            "`/movements [product] [N]` — Stock movements\n"
            "`/month` — Month-over-month\n"
            "`/year` — Year-over-year\n"
            "`/pv [date]` — Point Value summary\n"
            "`/cost [date]` — Cost of goods sold\n"
            "`/kits [start] [end]` — Registration kits\n"
            "`/products [status] [category] [search]` — List all products\n"
            "   e.g. `/products low_stock` or `/products in_stock Coffee`\n"
            "`/summary [date]` — Product-level daily sales summary\n"
            "\nOr just ask anything in plain English!"
        )

    if text.startswith('/briefing'):
        parts = text.split()
        if len(parts) > 1:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        else:
            d = today
        data = await _run_sync(BiBriefingService.generate_daily_briefing, d)
        return format_briefing(data)

    if text == '/revenue' or text.startswith('/revenue '):
        parts = text.split()
        if len(parts) > 1:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        else:
            d = today
        data = await _run_sync(BiCoreService.get_revenue_by_bucket, d)
        return format_revenue(data)

    if text == '/sales' or text.startswith('/sales '):
        parts = text.split()
        if len(parts) > 1:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        else:
            d = today
        data = await _run_sync(BiCoreService.get_fulfillment_by_gateway, d)
        return format_sales(data)

    if text == '/stock':
        data = await _run_sync(BiCoreService.get_stock_alerts)
        return format_stock_alerts(data)

    if text == '/recon' or text.startswith('/recon '):
        parts = text.split()
        if len(parts) > 1:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        else:
            d = today
        data = await _run_sync(BiCoreService.get_reconciliation, d)
        return format_reconciliation(data)

    if text.startswith('/recon_deep'):
        parts = text[len('/recon_deep'):].strip().split()
        flags = [p for p in parts if p.startswith('--')]
        date_parts = [p for p in parts if not p.startswith('--')]
        d = today
        if date_parts:
            try:
                d = datetime.strptime(date_parts[0], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        data = await _run_sync(BiReconciliationDeepDiveService.get_deep_dive, d)
        result = format_reconciliation_deep_dive(data)

        wants_chart = '--chart' in flags or '--all' in flags
        wants_xlsx = '--xlsx' in flags or '--all' in flags

        # Can only return media from async context if we have the update object
        # For the `handle_message` entry point (text-only), just return text
        # Media sending is handled in the polling/webhook runner
        if wants_chart or wants_xlsx:
            result += "\n\n_Use /recon_deep through the Telegram bot interface for chart/XLSX attachments._"

        return result

    if text == '/merch' or text.startswith('/merch '):
        parts = text.split()
        if len(parts) > 1:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        else:
            d = today
        data = await _run_sync(BiCoreService.get_merch_fulfillment, d)
        return format_merch(data)

    if text.startswith('/compare '):
        parts = text.split()
        if len(parts) >= 3:
            try:
                d1 = datetime.strptime(parts[1], '%Y-%m-%d').date()
                d2 = datetime.strptime(parts[2], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
            data = await _run_sync(BiCompareService.compare_dates, 'revenue_vs_sales', d1, d2)
            return format_compare(data)
        return "❌ Usage: /compare YYYY-MM-DD YYYY-MM-DD"

    if text.startswith('/trend'):
        parts = text.split()
        days = 30
        if len(parts) > 1:
            try:
                days = int(parts[1])
            except ValueError:
                pass
        data = await _run_sync(BiTrendService.revenue_trend, days)
        return format_trend(data)

    if text == '/anomalies' or text.startswith('/anomalies '):
        parts = text.split()
        days = 30
        if len(parts) > 1:
            try:
                days = int(parts[1])
            except ValueError:
                pass
        data = await _run_sync(BiAnomalyService.check_revenue_anomaly, days, 2.0)
        return format_anomaly(data)

    if text == '/branches':
        data = await _run_sync(BiBranchAggregator.aggregate_branch_revenue, today)
        return format_branch_summary(data)

    if text.startswith('/vs') or text == '/revvssales':
        parts = text.split()
        if len(parts) > 1 and parts[1] not in ['today']:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        else:
            d = today
        data = await _run_sync(BiCoreService.get_revenue_vs_sales, d)
        return format_revenue_vs_sales(data)

    if text == '/inventory':
        data = await _run_sync(BiExtendedService.get_inventory_value)
        return format_inventory_value(data)

    if text == '/stock_by_category':
        data = await _run_sync(BiExtendedService.get_stock_by_category)
        return format_stock_by_category(data)

    if text == '/pending':
        data = await _run_sync(BiExtendedService.get_pending_fulfillments)
        return format_pending_fulfillments(data)

    if text == '/pipeline':
        data = await _run_sync(BiExtendedService.get_fulfillment_pipeline)
        return format_fulfillment_pipeline(data)

    if text == '/month':
        data = await _run_sync(BiExtendedService.get_month_comparison)
        return format_month_comparison(data)

    if text == '/year':
        data = await _run_sync(BiExtendedService.get_year_comparison)
        return format_year_comparison(data)

    if text.startswith('/product_stock '):
        q = text[len('/product_stock '):].strip()
        if not q:
            return "❌ Usage: /product_stock <product name/code>"
        data = await _run_sync(BiExtendedService.get_product_stock, q)
        return format_product_stock(data)

    if text.startswith('/product_sales '):
        parts = text[len('/product_sales '):].strip().split()
        if not parts:
            return "❌ Usage: /product_sales <name> [YYYY-MM-DD]"
        q = parts[0]
        d = today
        if len(parts) > 1:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        data = await _run_sync(BiExtendedService.get_product_sales, q, d)
        return format_product_sales(data)

    if text.startswith('/product_trend '):
        parts = text[len('/product_trend '):].strip().split()
        if not parts:
            return "❌ Usage: /product_trend <name> [days]"
        q = parts[0]
        days = 30
        if len(parts) > 1:
            try:
                days = int(parts[1])
            except ValueError:
                pass
        data = await _run_sync(BiExtendedService.get_product_sales_trend, q, days)
        return format_product_sales_trend(data)

    if text.startswith('/product_compare '):
        parts = text[len('/product_compare '):].strip().split()
        if len(parts) < 3:
            return "❌ Usage: /product_compare <name> YYYY-MM-DD YYYY-MM-DD"
        q = parts[0]
        try:
            d1 = datetime.strptime(parts[1], '%Y-%m-%d').date()
            d2 = datetime.strptime(parts[2], '%Y-%m-%d').date()
        except ValueError:
            return "❌ Invalid date format. Use YYYY-MM-DD"
        data = await _run_sync(BiExtendedService.get_product_comparison, q, d1, d2)
        return format_product_comparison(data)

    if text.startswith('/top '):
        parts = text[len('/top '):].strip().split()
        limit = 10
        d = today
        if parts:
            try:
                limit = int(parts[0])
                if len(parts) > 1:
                    d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                try:
                    d = datetime.strptime(parts[0], '%Y-%m-%d').date()
                except ValueError:
                    pass
        data = await _run_sync(BiExtendedService.get_top_products, d, limit)
        return format_top_products(data)

    if text.startswith('/top_revenue '):
        parts = text[len('/top_revenue '):].strip().split()
        limit = 10
        d = today
        if parts:
            try:
                limit = int(parts[0])
                if len(parts) > 1:
                    d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                try:
                    d = datetime.strptime(parts[0], '%Y-%m-%d').date()
                except ValueError:
                    pass
        data = await _run_sync(BiExtendedService.get_top_products_by_revenue, d, limit)
        return format_top_products_by_revenue(data)

    if text.startswith('/category '):
        parts = text[len('/category '):].strip().split()
        if not parts:
            return "❌ Usage: /category <name> [YYYY-MM-DD]"
        q = parts[0]
        d = today
        if len(parts) > 1:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        data = await _run_sync(BiExtendedService.get_category_sales, q, d)
        return format_category_sales(data)

    if text.startswith('/txn_detail '):
        q = text[len('/txn_detail '):].strip()
        if not q:
            return "❌ Usage: /txn_detail <tx_id>"
        data = await _run_sync(BiExtendedService.get_transaction_detail, q)
        return format_transaction_detail(data)

    if text.startswith('/txn ') or text.startswith('/search '):
        prefix = '/txn ' if text.startswith('/txn ') else '/search '
        q = text[len(prefix):].strip()
        if not q:
            return "❌ Usage: /txn <search query>"
        data = await _run_sync(BiExtendedService.search_transactions, q)
        return format_search_transactions(data)

    if text.startswith('/customer '):
        q = text[len('/customer '):].strip()
        if not q:
            return "❌ Usage: /customer <name or phone>"
        data = await _run_sync(BiExtendedService.search_customer, q)
        return format_customer(data)

    if text.startswith('/user '):
        parts = text[len('/user '):].strip().split()
        username = None
        d = today
        if parts:
            username = parts[0]
            if len(parts) > 1:
                try:
                    d = datetime.strptime(parts[1], '%Y-%m-%d').date()
                except ValueError:
                    pass
        data = await _run_sync(BiExtendedService.get_user_performance, username, d)
        return format_user_performance(data)

    if text == '/user':
        data = await _run_sync(BiExtendedService.get_user_performance, None, today)
        return format_user_performance(data)

    if text.startswith('/gateways '):
        parts = text.split()
        d = today
        if len(parts) > 1:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        data = await _run_sync(BiExtendedService.get_gateway_breakdown, d)
        return format_gateway_breakdown(data)

    if text == '/gateways':
        data = await _run_sync(BiExtendedService.get_gateway_breakdown, today)
        return format_gateway_breakdown(data)

    if text.startswith('/combined '):
        parts = text.split()
        d = today
        if len(parts) > 1:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        data = await _run_sync(BiExtendedService.get_combined_orders_summary, d)
        return format_combined_orders(data)

    if text == '/combined':
        data = await _run_sync(BiExtendedService.get_combined_orders_summary, today)
        return format_combined_orders(data)

    if text.startswith('/movements'):
        parts = text[len('/movements'):].strip().split()
        product_query = None
        days = 7
        if parts:
            try:
                days = int(parts[-1])
                parts = parts[:-1]
            except ValueError:
                pass
            if parts:
                product_query = ' '.join(parts)
        data = await _run_sync(BiExtendedService.get_stock_movements, product_query, days)
        return format_stock_movements(data)

    if text == '/pv' or text.startswith('/pv '):
        parts = text.split()
        d = today
        if len(parts) > 1:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        data = await _run_sync(BiExtendedService.get_pv_summary, d)
        return format_pv_summary(data)

    if text == '/cost' or text.startswith('/cost '):
        parts = text.split()
        d = today
        if len(parts) > 1:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        data = await _run_sync(BiExtendedService.get_total_cost, d)
        return format_total_cost(data)

    if text.startswith('/kits'):
        parts = text[len('/kits'):].strip().split()
        if len(parts) >= 2:
            try:
                s = datetime.strptime(parts[0], '%Y-%m-%d').date()
                e = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD YYYY-MM-DD"
        elif len(parts) == 1:
            try:
                s = datetime.strptime(parts[0], '%Y-%m-%d').date()
                e = today
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        else:
            s = today - timedelta(days=30)
            e = today
        data = await _run_sync(BiExtendedService.get_registration_kits_summary, s, e)
        return format_registration_kits_summary(data)

    if text.startswith('/products'):
        parts = text[len('/products'):].strip().split(maxsplit=2)
        status = None
        cat = None
        search = None
        if parts:
            p0 = parts[0].upper()
            if p0 in ('IN_STOCK', 'LOW_STOCK', 'OUT_OF_STOCK'):
                status = p0
                if len(parts) > 1:
                    cat = parts[1]
                    if len(parts) > 2:
                        search = parts[2]
            else:
                cat = parts[0]
                if len(parts) > 1:
                    search = parts[1]
        data = await _run_sync(BiExtendedService.get_all_products, status, cat, search)
        return format_products(data)

    if text == '/summary' or text.startswith('/summary '):
        parts = text.split()
        d = today
        if len(parts) > 1:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD"
        data = await _run_sync(BiExtendedService.get_daily_sales_summary, d)
        return format_sales_summary(data)

    is_free_form = not text.startswith('/')
    if is_free_form:
        from .services.bi_agent_service import BIAgent
        return await BIAgent.process_message(str(user_id or '0'), text)

    return "❌ Unknown command. Type /help for available commands."


_CHART_DISPATCH: Dict[str, Tuple] = {
    'revenue': (BiCoreService.get_revenue_by_bucket, BiChartAdapter.for_revenue),
    'sales': (BiCoreService.get_fulfillment_by_gateway, BiChartAdapter.for_fulfillment),
    'stock': (BiCoreService.get_stock_alerts, BiChartAdapter.for_stock_alerts),
    'vs': (BiCoreService.get_revenue_vs_sales, BiChartAdapter.for_revenue_vs_sales),
    'trend': (BiTrendService.revenue_trend, BiChartAdapter.for_trend),
    'briefing': (BiBriefingService.generate_daily_briefing, BiChartAdapter.for_briefing),
    'top': (BiExtendedService.get_top_products, BiChartAdapter.for_top_products),
    'month': (BiExtendedService.get_month_comparison, BiChartAdapter.for_month_comparison),
    'year': (BiExtendedService.get_year_comparison, BiChartAdapter.for_year_comparison),
    'gateways': (BiExtendedService.get_gateway_breakdown, BiChartAdapter.for_gateway_breakdown),
}


async def _get_chart_for_command(text: str) -> Optional[BytesIO]:
    """Parse a command text and return a chart buf if a chart adapter exists."""
    parts = text.strip().lower().split()
    if not parts:
        return None

    cmd = parts[0].lstrip('/')
    today = timezone.localdate()

    entry = _CHART_DISPATCH.get(cmd)
    if entry is None:
        return None

    service_fn, adapter_fn = entry

    no_date_cmds = {'stock', 'month', 'year'}

    if cmd == 'trend':
        days = 30
        if len(parts) > 1:
            try:
                days = int(parts[1])
            except ValueError:
                pass
        data = await _run_sync(service_fn, days)
    elif cmd == 'top':
        limit = 10
        d = today
        args = parts[1:]
        if args:
            try:
                limit = int(args[0])
                if len(args) > 1:
                    d = datetime.strptime(args[1], '%Y-%m-%d').date()
            except ValueError:
                try:
                    d = datetime.strptime(args[0], '%Y-%m-%d').date()
                except ValueError:
                    pass
        data = await _run_sync(service_fn, d, limit)
    elif cmd in no_date_cmds:
        data = await _run_sync(service_fn)
    else:
        d = today
        if len(parts) > 1:
            try:
                d = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                pass
        data = await _run_sync(service_fn, d)

    return await _run_sync(adapter_fn, data)


async def handle_message_with_media(text: str, user_id: int = None) -> Tuple[str, Optional[BytesIO], Optional[BytesIO], Optional[str]]:
    text_lower = text.strip().lower()
    parts = text_lower.split()

    flags = [p for p in parts if p.startswith('--')]
    non_flag_parts = [p for p in parts if not p.startswith('--')]
    clean_text = ' '.join(non_flag_parts)

    wants_chart = '--chart' in flags or '--all' in flags
    wants_xlsx = '--xlsx' in flags or '--all' in flags

    force_chart = '--chart' in flags or '--all' in flags
    is_free_form = not clean_text.startswith('/')

    if is_free_form:
        from .services.bi_agent_service import BIAgent
        result, chart_buf, xlsx_buf, xlsx_name = await BIAgent.process_message_with_chart(
            str(user_id or '0'), clean_text, force_chart=force_chart, force_xlsx=wants_xlsx,
        )
        return result, chart_buf, xlsx_buf, xlsx_name

    if clean_text.startswith('/recon_deep '):
        date_parts = non_flag_parts[1:]
        d = timezone.localdate()
        if date_parts:
            try:
                d = datetime.strptime(date_parts[0], '%Y-%m-%d').date()
            except ValueError:
                return "❌ Invalid date format. Use YYYY-MM-DD", None, None, None

        data = await _run_sync(BiReconciliationDeepDiveService.get_deep_dive, d)
        result = format_reconciliation_deep_dive(data)

        chart_buf = None
        xlsx_buf = None
        xlsx_name = None

        if wants_chart:
            chart_buf = await _run_sync(BiReconciliationDeepDiveService.generate_chart, data)

        if wants_xlsx:
            xlsx_result = await _run_sync(BiReconciliationDeepDiveService.generate_xlsx, data)
            xlsx_buf, xlsx_name = xlsx_result

        return result, chart_buf, xlsx_buf, xlsx_name

    result = await handle_message(clean_text, user_id)

    chart_buf = None
    if wants_chart:
        chart_buf = await _get_chart_for_command(clean_text)

    return result, chart_buf, None, None


def _escape_markdown(text: str) -> str:
    """Escape special characters for Telegram Markdown mode.
    Only _ needs escaping since * is used for bold formatting."""
    return text.replace('_', '\\_')


async def send_telegram_message(chat_id: str, text: str):
    import httpx
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — cannot send message")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json={
                'chat_id': chat_id,
                'text': _escape_markdown(text),
                'parse_mode': 'Markdown',
            })
            if resp.status_code != 200:
                logger.error(f"Telegram API error {resp.status_code}: {resp.text}")
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
