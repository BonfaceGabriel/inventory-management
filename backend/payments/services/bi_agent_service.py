import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone
from openai import OpenAI

from payments.services.bi_core_service import BiCoreService
from payments.services.bi_compare_service import BiCompareService
from payments.services.bi_trend_service import BiTrendService
from payments.services.bi_anomaly_service import BiAnomalyService
from payments.services.bi_briefing_service import BiBriefingService
from payments.services.bi_branch_aggregator import BiBranchAggregator
from payments.services.bi_extended_service import BiExtendedService
from payments.services.bi_conversation_service import ConversationMemory
from payments.services.bi_reconciliation_deep_dive_service import BiReconciliationDeepDiveService
from payments.services.bi_chart_adapter import BiChartAdapter
from payments.services.bi_xlsx_adapter import BiXlsxAdapter
from payments.services.bi_remote_service import BiRemoteService, get_local_branch_slug, _slugify

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Business Intelligence assistant for BF SUMA Eagle Shop, a health products retailer. Today is {today}.

You have {tool_count} function tools available covering revenue, fulfillment, sales, stock, products, transactions, customers, and operations.

SYSTEM DATA MODEL — THREE DISTINCT DATA TYPES:

1. REVENUE (money in) = Transaction.amount — money received via payment gateways
   - Revenue buckets: PAYBILL (M-PESA Paybill), PDQ (Card), TILL (M-PESA Till), MERCH (Merchandise)
        - Use get_revenue() for revenue data
    - get_briefing() includes revenue + fulfillment + stock + recon + merch in one call
    - get_reconciliation_deep_dive() gives transaction-level detail + root causes for X+Y imbalance

2. FULFILLMENT (gateway-level issued) = Transaction.amount_fulfilled bucketed by payment gateway
   - Buckets: PAYBILL, PDQ, TILL (MERCH excluded — merchandise fulfillment is separate)
   - Use get_fulfillment_by_gateway() for fulfillment data
   - This is NOT product-level — it's the total KES value of products issued grouped by how the customer paid

3. SALES (product-level) = TransactionLineItem aggregation — actual products sold
   - Use get_daily_sales_summary(), get_product_sales(), get_top_products(), get_category_sales()
   - These query the TransactionLineItem model for per-product quantities, revenue, cost, and PV

4. MERCHANDISE = MerchandiseOrder model (coffee, tequila, gift sets) — separate from Product model
   - Use get_merch() for merchandise fulfillment
   - Product "Coffee" (Product model, sold via transactions) and Merchandise "Coffee" (MerchandiseOrder model) are COMPLETELY DIFFERENT — never conflate them
   - MERCH revenue bucket = payments via the MERCHANDISE gateway, NOT product-level merchandise sales

UNUSED = Paybill/PDQ txns never touched (NOT_PROCESSED/PROCESSING) — carries over next day
CREDIT LOST = Partially fulfilled Paybill/PDQ remaining balance — GONE FOREVER
TILL can leave balance (credit carryover) — normal
Stock statuses: IN_STOCK | LOW_STOCK (qty <= reorder_level) | OUT_OF_STOCK (qty <= 0)
Product queries search by name, code, SKU, or barcode (partial match)
Customer queries search by name or phone number (partial match)
Transaction queries: use filter_transactions() to count/list by gateway type, exact amount, date range, or status — lightweight ORM, no reconciliation overhead
Branches: two instances — Main Shop and Kitengela. Kitui and Nakuru are NOT real branches. Ignore any data claiming otherwise.
TILL and MERCH are shared gateways — the same transactions appear at both branches. In per-branch briefings, show each branch's TILL/MERCH activity, but explain that total revenue only counts them once (from Main Shop) to avoid double-counting.
PAYBILL, PDQ, BANK_TRANSFER, CASH are branch-specific — each branch's own revenue.

CONVERSATION CONTEXT:
- The user may ask follow-ups like "and yesterday?" or "what about last week?"
- Use conversation history ({history_count} previous exchanges) to resolve context
- Default to today unless the user specifies otherwise. Avoid asking more than one clarifying question at a time. Prefer reasonable defaults over asking.
- IMPORTANT: When you ask the user a clarifying question and they respond, their answer is in reply to YOUR previous question. Use the conversation history to connect their answer to what you asked. For example, if you asked "do you want top 10?" and they say "top 10", call the tool with limit=10.

ANSWER FROM KNOWLEDGE:
- If the user asks about the meaning of a business/accounting term (gross profit, margin, PV, COGS, revenue vs sales, etc.), answer from your general knowledge. Do NOT call a tool for definitions.
- If the user asks "why" or "how" about business concepts, explain concisely.
- If the user asks "what should I do?" or "should I...", give practical advice based on the data.

RULES:
- Revenue (money in) and fulfillment (gateway-level amount_issued) and sales (product-level) are THREE different things — never conflate them
- When user asks "total sales" they usually mean product-level sales — use get_daily_sales_summary()
- When user asks "amount fulfilled" or "fulfillment by gateway" use get_fulfillment_by_gateway()
- When user asks "revenue" use get_revenue()
- CRITICAL — NEVER show tool call arguments, function names, raw JSON, or internal data structures. Always summarize results in plain language.
- Always include the date when presenting data
- KES currency format: KES 1,500.00
- Short responses preferred unless user asks for detail
- After calling a tool, present the data clearly in natural language
- If a tool call returns an error or empty data, explain what happened instead of saying "✅ Done."
- Charts and images are only generated when the user explicitly asks for one using words like 'chart', 'graph', 'plot', or 'visual'. Do NOT generate or offer charts unprompted.
- The bot CAN generate and send XLSX/CSV spreadsheet files as Telegram documents. When the user asks for a spreadsheet, CSV, or data export, say "I'll prepare the file" and the file will be attached automatically. Do NOT paste raw tabular data as text — the system will generate the spreadsheet. Never format CSV rows or column definitions in your response.
- When generating a spreadsheet with per-branch data (e.g., "yesterday transactions broken down by branch"), make TWO separate filter_transactions calls — one per branch with branch param — and pass page_size: 10000 on each so ALL matching transactions are included. Never call filter_transactions without page_size for spreadsheet exports.
- Do NOT paste CSV headers, rows, or column specs in your response text. The system handles file generation.
- Never ask numbered questions like "1) ... or 2) ..." or "Reply with 1 or 2". Never ask "Would you like me to..." offering options. If the user asks for something, just do it and report the result. If you need clarification, ask one simple question without offering numbered choices.
- Answer only what was asked. No upsell. No "would you like me to also...". No "next steps" list.
- If the user says "ignore", "forget it", "never mind", or drops a topic, move on. Do not re-ask.
"""


def _token_kwargs(model: str, tokens: int) -> dict:
    if model.startswith(('gpt-5', 'o1', 'o3', 'o4')):
        return {'max_completion_tokens': max(tokens, 4096)}
    return {'max_tokens': tokens}


def _limit_tool_data(data, max_len=8000):
    content = json.dumps(data, default=str)
    if len(content) > max_len:
        return content[:max_len] + '\n...[truncated]'
    return content


MERGE_LIST_FIELDS = {
    'sample_transactions', 'transactions', 'products', 'orders', 'gateways',
    'branches', 'categories', 'users', 'data_points', 'out_of_stock_products',
    'low_stock_products', 'top_products',
}

MERGE_NUMERIC_FIELDS = {
    'total_count', 'total_amount', 'total_revenue', 'total_sales', 'total_products_sold',
}


def _merge_tool_data(existing: dict, new: dict) -> dict:
    merged = dict(existing)
    for key in MERGE_LIST_FIELDS:
        existing_list = existing.get(key)
        new_list = new.get(key)
        if isinstance(existing_list, list) and isinstance(new_list, list):
            seen = {json.dumps(item, default=str, sort_keys=True) for item in existing_list}
            for item in new_list:
                sig = json.dumps(item, default=str, sort_keys=True)
                if sig not in seen:
                    seen.add(sig)
                    existing_list.append(item)
    for key in MERGE_NUMERIC_FIELDS:
        existing_val = existing.get(key)
        new_val = new.get(key)
        if isinstance(existing_val, (int, float)) and isinstance(new_val, (int, float)):
            merged[key] = existing_val + new_val
    return merged


def _execute_tool(fn_name: str, args: dict) -> dict:
    branch = args.pop('branch', None) if isinstance(args, dict) else None
    if branch and branch != get_local_branch_slug():
        return BiRemoteService.execute(branch, fn_name, args)
    fn = _TOOL_FUNCTIONS.get(fn_name)
    if fn is None:
        return {'error': f'Unknown tool: {fn_name}'}
    return fn(args)


BRANCH_PARAM = {
    'type': 'string',
    'description': 'Branch slug (e.g., "kitengela") to query. Defaults to local branch ("main-shop"). Use list_branches to see available branches.',
}


def _add_branch_param(tool_def):
    fn = tool_def.get('function', {})
    params = fn.get('parameters')
    if params:
        params.setdefault('properties', {})['branch'] = BRANCH_PARAM
    return tool_def


def _build_tool_definitions():
    return [
        {
            'type': 'function',
            'function': {
                'name': 'get_briefing',
                'description': 'Get the daily EOD briefing with revenue/fulfillment/unused/credit/stock/recon/merch for a date',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD. Defaults to today.'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_revenue',
                'description': 'Get revenue breakdown by bucket (PAYBILL, PDQ, TILL, MERCH) for a date',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': ['date']},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_fulfillment_by_gateway',
                'description': 'Get gateway-level fulfillment (amount_fulfilled) broken down by payment gateway bucket for a date. Buckets: PAYBILL, PDQ, TILL. MERCH excluded.',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': ['date']},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_revenue_vs_sales',
                'description': 'Compare revenue vs gateway-level fulfillment with per-bucket gap and fulfillment rate for a date',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': ['date']},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_stock_alerts',
                'description': 'Get current low stock and out-of-stock alerts across all products',
                'parameters': {'type': 'object', 'properties': {}},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_inventory_value',
                'description': 'Get total inventory value at retail price and cost price across all products',
                'parameters': {'type': 'object', 'properties': {}},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_product_stock',
                'description': 'Get current stock level, price, status, and value for a product by name/code',
                'parameters': {'type': 'object', 'properties': {'product_name': {'type': 'string', 'description': 'Product name, code, or SKU'}}, 'required': ['product_name']},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_all_products',
                'description': 'List all active products with optional filters (stock_status, category, search)',
                'parameters': {'type': 'object', 'properties': {
                    'stock_status': {'type': 'string', 'description': 'Filter: IN_STOCK, LOW_STOCK, or OUT_OF_STOCK'},
                    'category': {'type': 'string', 'description': 'Filter by category/product line name'},
                    'search': {'type': 'string', 'description': 'Search by name, code, SKU, or barcode'},
                }},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_daily_sales_summary',
                'description': 'Get product-level daily sales summary (quantities, revenue, cost, PV from TransactionLineItem) for a date',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_product_sales',
                'description': 'Get sales quantity, revenue, cost, and PV for a product by name/code on a date',
                'parameters': {'type': 'object', 'properties': {'product_name': {'type': 'string', 'description': 'Product name, code, or SKU'}, 'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': ['product_name']},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_top_products',
                'description': 'Get top N selling products by quantity for a date',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}, 'limit': {'type': 'integer', 'description': 'Number of products (default 10)'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_top_products_by_revenue',
                'description': 'Get top N products by revenue for a date',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}, 'limit': {'type': 'integer', 'description': 'Number of products (default 10)'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_category_sales',
                'description': 'Get sales for a product category (product line) on a date',
                'parameters': {'type': 'object', 'properties': {'category': {'type': 'string', 'description': 'Category name'}, 'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': ['category']},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_stock_by_category',
                'description': 'Get current stock grouped by product category with values',
                'parameters': {'type': 'object', 'properties': {}},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_stock_movements',
                'description': 'Get recent stock movements optionally filtered by product',
                'parameters': {'type': 'object', 'properties': {'product_name': {'type': 'string', 'description': 'Optional product name'}, 'days': {'type': 'integer', 'description': 'Days to look back (default 7)'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_product_sales_trend',
                'description': 'Get daily sales trend for a product over N days',
                'parameters': {'type': 'object', 'properties': {'product_name': {'type': 'string', 'description': 'Product name or code'}, 'days': {'type': 'integer', 'description': 'Number of days (default 30)'}}, 'required': ['product_name']},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'search_transactions',
                'description': 'Search transactions by ID, customer name, phone, or notes',
                'parameters': {'type': 'object', 'properties': {'query': {'type': 'string', 'description': 'Search query (tx_id, name, phone)'}}, 'required': ['query']},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'filter_transactions',
                'description': 'Filter and count transactions by gateway type, exact amount, amount range, date range, and status. Use this instead of get_trend when you need to count or list transactions matching specific criteria (e.g., "TILL transactions of KES 700 over 30 days").',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'gateway_type': {'type': 'string', 'description': 'Gateway type: TILL, PAYBILL, PDQ, MERCH, or ALL (default ALL)'},
                        'amount': {'type': 'number', 'description': 'Exact transaction amount to filter by'},
                        'amount_min': {'type': 'number', 'description': 'Minimum amount filter'},
                        'amount_max': {'type': 'number', 'description': 'Maximum amount filter'},
                        'start_date': {'type': 'string', 'description': 'Start date YYYY-MM-DD'},
                        'end_date': {'type': 'string', 'description': 'End date YYYY-MM-DD'},
                        'days': {'type': 'integer', 'description': 'Days back from today (alternative to explicit date range)'},
                        'status': {'type': 'string', 'description': 'Status: ALL, NOT_PROCESSED, PROCESSING, PARTIALLY_FULFILLED, FULFILLED, COMBINED_FULFILLED, CANCELLED (default ALL)'},
                        'page_size': {'type': 'integer', 'description': 'Number of sample transactions to return (default 10, max 10000). Use 10000 when generating a spreadsheet so all matching transactions are included.'},
                    },
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_transaction_detail',
                'description': 'Get full transaction detail with all line items, costs, PV, and combined order info',
                'parameters': {'type': 'object', 'properties': {'tx_id': {'type': 'string', 'description': 'Transaction ID'}}, 'required': ['tx_id']},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'search_customer',
                'description': 'Find customers by name or phone and show their history and total spend',
                'parameters': {'type': 'object', 'properties': {'query': {'type': 'string', 'description': 'Customer name or phone number'}}, 'required': ['query']},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_pending_fulfillments',
                'description': 'Get all pending/partially fulfilled transactions needing attention',
                'parameters': {'type': 'object', 'properties': {}},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_fulfillment_pipeline',
                'description': 'Get count of transactions at each stage of the fulfillment pipeline',
                'parameters': {'type': 'object', 'properties': {}},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_gateway_breakdown',
                'description': 'Get revenue and gateway-level fulfillment broken down by individual payment gateway type',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_period_revenue_vs_sales',
                'description': 'Compare total revenue vs gateway-level fulfillment with gap and fulfillment rate for a date range',
                'parameters': {'type': 'object', 'properties': {'start_date': {'type': 'string', 'description': 'Start date YYYY-MM-DD'}, 'end_date': {'type': 'string', 'description': 'End date YYYY-MM-DD'}}, 'required': ['start_date', 'end_date']},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_month_comparison',
                'description': 'Compare current month revenue and gateway-level fulfillment to previous month',
                'parameters': {'type': 'object', 'properties': {}},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_year_comparison',
                'description': 'Compare current year-to-date revenue and gateway-level fulfillment to previous year',
                'parameters': {'type': 'object', 'properties': {}},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_product_comparison',
                'description': 'Compare a product sales quantity and revenue between two dates',
                'parameters': {'type': 'object', 'properties': {'product_name': {'type': 'string', 'description': 'Product name or code'}, 'date1': {'type': 'string', 'description': 'First date YYYY-MM-DD'}, 'date2': {'type': 'string', 'description': 'Second date YYYY-MM-DD'}}, 'required': ['product_name', 'date1', 'date2']},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_registration_kits_summary',
                'description': 'Get registration kit issuance statistics over a date range',
                'parameters': {'type': 'object', 'properties': {'start_date': {'type': 'string', 'description': 'Start date YYYY-MM-DD'}, 'end_date': {'type': 'string', 'description': 'End date YYYY-MM-DD'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_pv_summary',
                'description': 'Get total Point Value (PV) for fulfilled transactions on a date',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_total_cost',
                'description': 'Get total cost of goods sold (COGS) for a date',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_user_performance',
                'description': 'Get user performance stats (processed, activated, completed, scanned) for a date',
                'parameters': {'type': 'object', 'properties': {'username': {'type': 'string', 'description': 'Username (optional)'}, 'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_combined_orders_summary',
                'description': 'Get combined order stats, status breakdown, and list for a date',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_merch',
                'description': 'Get merchandise fulfillment stats (coffee/sets) for a date',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_branches',
                'description': 'Get aggregated multi-branch performance summary. Each branch shows their full activity including shared gateways (TILL/MERCH). Total revenue de-duplicates shared gateways to avoid double-counting.',
                'parameters': {'type': 'object', 'properties': {}},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_reconciliation',
                'description': 'Get daily reconciliation X+Y formula result for a date',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_reconciliation_deep_dive',
                'description': 'Get transaction-level reconciliation deep dive with issue detection for a date. Identifies specific transactions causing X+Y imbalance, unfulfilled/partially fulfilled/combined order issues.',
                'parameters': {'type': 'object', 'properties': {'date': {'type': 'string', 'description': 'Date YYYY-MM-DD'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_trend',
                'description': 'Get revenue trend with daily breakdown over N days',
                'parameters': {'type': 'object', 'properties': {'days': {'type': 'integer', 'description': 'Number of days (default 30)'}}, 'required': []},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'get_anomalies',
                'description': 'Detect unusual days in revenue using z-score anomaly detection over N days',
                'parameters': {'type': 'object', 'properties': {'days': {'type': 'integer', 'description': 'Lookback days (default 30)'}}, 'required': []},
            },
        },
    ]


_TOOL_DEFINITIONS = [_add_branch_param(t) for t in _build_tool_definitions()]

_TOOL_FUNCTIONS = {
    'get_briefing': lambda args: BiBriefingService.generate_daily_briefing(_parse_date(args.get('date'))),
    'get_revenue': lambda args: BiCoreService.get_revenue_by_bucket(_parse_date(args.get('date'))),
    'get_fulfillment_by_gateway': lambda args: BiCoreService.get_fulfillment_by_gateway(_parse_date(args.get('date'))),
    'get_revenue_vs_sales': lambda args: BiCoreService.get_revenue_vs_sales(_parse_date(args.get('date'))),
    'get_stock_alerts': lambda args: BiCoreService.get_stock_alerts(),
    'get_inventory_value': lambda args: BiExtendedService.get_inventory_value(),
    'get_product_stock': lambda args: BiExtendedService.get_product_stock(args['product_name']),
    'get_all_products': lambda args: BiExtendedService.get_all_products(args.get('stock_status'), args.get('category'), args.get('search')),
    'get_daily_sales_summary': lambda args: BiExtendedService.get_daily_sales_summary(_parse_date(args.get('date'))),
    'get_product_sales': lambda args: BiExtendedService.get_product_sales(args['product_name'], _parse_date(args.get('date'))),
    'get_top_products': lambda args: BiExtendedService.get_top_products(_parse_date(args.get('date')), args.get('limit', 10)),
    'get_top_products_by_revenue': lambda args: BiExtendedService.get_top_products_by_revenue(_parse_date(args.get('date')), args.get('limit', 10)),
    'get_category_sales': lambda args: BiExtendedService.get_category_sales(args['category'], _parse_date(args.get('date'))),
    'get_stock_by_category': lambda args: BiExtendedService.get_stock_by_category(),
    'get_stock_movements': lambda args: BiExtendedService.get_stock_movements(args.get('product_name'), args.get('days', 7)),
    'get_product_sales_trend': lambda args: BiExtendedService.get_product_sales_trend(args['product_name'], args.get('days', 30)),
    'search_transactions': lambda args: BiExtendedService.search_transactions(args['query']),
    'get_transaction_detail': lambda args: BiExtendedService.get_transaction_detail(args['tx_id']),
    'search_customer': lambda args: BiExtendedService.search_customer(args['query']),
    'get_pending_fulfillments': lambda args: BiExtendedService.get_pending_fulfillments(),
    'get_fulfillment_pipeline': lambda args: BiExtendedService.get_fulfillment_pipeline(),
    'get_gateway_breakdown': lambda args: BiExtendedService.get_gateway_breakdown(_parse_date(args.get('date'))),
    'get_period_revenue_vs_sales': lambda args: BiExtendedService.get_period_revenue_vs_sales(_parse_date(args['start_date']), _parse_date(args['end_date'])),
    'get_month_comparison': lambda args: BiExtendedService.get_month_comparison(),
    'get_year_comparison': lambda args: BiExtendedService.get_year_comparison(),
    'get_product_comparison': lambda args: BiExtendedService.get_product_comparison(args['product_name'], _parse_date(args['date1']), _parse_date(args['date2'])),
    'get_registration_kits_summary': lambda args: BiExtendedService.get_registration_kits_summary(_parse_date(args.get('start_date')), _parse_date(args.get('end_date'))),
    'get_pv_summary': lambda args: BiExtendedService.get_pv_summary(_parse_date(args.get('date'))),
    'get_total_cost': lambda args: BiExtendedService.get_total_cost(_parse_date(args.get('date'))),
    'get_user_performance': lambda args: BiExtendedService.get_user_performance(args.get('username'), _parse_date(args.get('date'))),
    'get_combined_orders_summary': lambda args: BiExtendedService.get_combined_orders_summary(_parse_date(args.get('date'))),
    'get_merch': lambda args: BiCoreService.get_merch_fulfillment(_parse_date(args.get('date'))),
    'get_branches': lambda args: BiBranchAggregator.aggregate_branch_revenue(),
    'get_reconciliation': lambda args: BiCoreService.get_reconciliation(_parse_date(args.get('date'))),
    'get_reconciliation_deep_dive': lambda args: BiReconciliationDeepDiveService.get_deep_dive(_parse_date(args.get('date'))),
    'filter_transactions': lambda args: BiExtendedService.filter_transactions(
        gateway_type=args.get('gateway_type'),
        amount=args.get('amount'),
        amount_min=args.get('amount_min'),
        amount_max=args.get('amount_max'),
        start_date=args.get('start_date'),
        end_date=args.get('end_date'),
        days=args.get('days'),
        status=args.get('status'),
        page_size=args.get('page_size', 10),
    ),
    'get_trend': lambda args: BiTrendService.revenue_trend(args.get('days', 30)),
    'get_anomalies': lambda args: BiAnomalyService.check_revenue_anomaly(args.get('days', 30), 2.0),
}


class BIAgent:
    @staticmethod
    async def process_message(chat_id: str, text: str) -> str:
        try:
            history = await sync_to_async(ConversationMemory.get_history)(chat_id)
        except Exception:
            logger.warning("Conversation memory unavailable, proceeding without history")
            history = []

        result = await BIAgent._process(text, chat_id, history)

        try:
            await sync_to_async(ConversationMemory.add_exchange)(chat_id, text, result)
        except Exception as e:
            logger.warning(f"Failed to save conversation: {e}")

        return result

    @staticmethod
    async def _process(text: str, chat_id: str, history: list) -> str:
        provider = getattr(settings, 'LLM_PROVIDER', 'openai')
        today = await sync_to_async(timezone.localdate)()

        if provider == 'gemini':
            api_key = getattr(settings, 'GEMINI_API_KEY', '')
            if not api_key:
                return "❌ Gemini not configured. Add GEMINI_API_KEY to .env or use /commands."
            client = OpenAI(
                api_key=api_key,
                base_url='https://generativelanguage.googleapis.com/v1beta/openai/',
            )
            model = getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')
            return await BIAgent._call_with_tools(client, model, text, today, history)

        if provider == 'groq':
            api_key = getattr(settings, 'GROQ_API_KEY', '')
            if not api_key:
                return "❌ Groq not configured. Set GROQ_API_KEY in .env or use /commands."
            client = OpenAI(api_key=api_key, base_url='https://api.groq.com/openai/v1')
            model = getattr(settings, 'GROQ_MODEL', 'llama-3.3-70b-versatile')
            return await BIAgent._call_groq(client, model, text, today, history)

        api_key = getattr(settings, 'OPENAI_API_KEY', '')
        if not api_key:
            return "❌ LLM not configured. Set OPENAI_API_KEY or LLM_PROVIDER=groq/gemini, or use /commands."
        client = OpenAI(api_key=api_key)
        model = getattr(settings, 'LLM_MODEL', 'gpt-4o-mini')
        return await BIAgent._call_with_tools(client, model, text, today, history)

    @staticmethod
    def _build_messages(text: str, today, history: list) -> list:
        branches = BiRemoteService.list_branches()
        branch_names = ', '.join(f"{b['name']} ({b['slug']})" for b in branches)
        sys_prompt = SYSTEM_PROMPT.format(
            today=today.isoformat(),
            tool_count=len(_TOOL_DEFINITIONS),
            history_count=len(history),
        )
        sys_prompt += f"\nREAL BRANCHES (only these exist): {branch_names}"
        if history:
            last = history[-1]
            sys_prompt += f"\n\nLAST USER MESSAGE IN CONTEXT: \"{last.get('user', '')}\""
        messages = [{'role': 'system', 'content': sys_prompt}]

        for exchange in history[-10:]:
            messages.append({'role': 'user', 'content': exchange.get('user', '')})
            messages.append({'role': 'assistant', 'content': exchange.get('bot', '')})

        messages.append({'role': 'user', 'content': text})
        return messages

    @staticmethod
    async def _call_with_tools(client, model: str, text: str, today, history: list) -> str:
        messages = BIAgent._build_messages(text, today, history)

        def do_first_call():
            return client.chat.completions.create(
                model=model,
                messages=messages,
                tools=_TOOL_DEFINITIONS,
                tool_choice='auto',
                **_token_kwargs(model, 600),
            )

        try:
            response = await sync_to_async(do_first_call)()
            msg = response.choices[0].message

            # Retry once if model returned nothing — force it to answer
            if not msg.tool_calls and not (msg.content and msg.content.strip()):
                logger.info(f"First LLM call returned empty for: {text[:80]}")
                is_conceptual = any(kw in text.lower() for kw in [
                    'what does', 'what is', 'why does', 'how is', 'explain',
                    'define', 'meaning', 'difference', 'should i',
                ])
                if is_conceptual:
                    messages.append({
                        'role': 'user',
                        'content': (
                            "Answer this question directly from your general business "
                            "knowledge. DO NOT use any tool. Provide a short explanation."
                        ),
                    })
                    response = await sync_to_async(client.chat.completions.create)(
                        model=model, messages=messages,
                        **_token_kwargs(model, 800),
                    )
                else:
                    messages.append({
                        'role': 'user',
                        'content': (
                            "Answer the question using the conversation history. "
                            "Call a tool if you need fresh data, then summarize concisely."
                        ),
                    })
                    response = await sync_to_async(client.chat.completions.create)(
                        model=model, messages=messages, tools=_TOOL_DEFINITIONS,
                        tool_choice='auto', **_token_kwargs(model, 800),
                    )
                msg = response.choices[0].message

            if msg.tool_calls:
                messages.append(msg)
                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        raw_data = await sync_to_async(_execute_tool)(fn_name, args)
                    except Exception as e:
                        logger.error(f"Tool {fn_name} failed: {e}")
                        raw_data = {'error': str(e)}

                    messages.append({
                        'role': 'tool',
                        'tool_call_id': tc.id,
                        'content': _limit_tool_data(raw_data),
                    })

                completion = await sync_to_async(client.chat.completions.create)(
                    model=model,
                    messages=messages,
                    **_token_kwargs(model, 1000),
                )
                content = completion.choices[0].message.content
                if content:
                    return content

                last_tool_data = None
                for m in reversed(messages):
                    if m['role'] == 'tool':
                        try:
                            last_tool_data = json.loads(m['content'])
                            break
                        except (json.JSONDecodeError, TypeError):
                            pass
                if last_tool_data:
                    return _format_json_summary(last_tool_data)
                return "✅ Done."

            return msg.content and msg.content.strip() or "I couldn't find an answer to that question."

        except Exception as e:
            logger.error(f"LLM query failed: {e}")
            return "❌ Sorry, I couldn't process that question. Try using / commands or rephrase your question."

    @staticmethod
    async def _process_message_data(chat_id: str, text: str) -> tuple:
        """Returns (text_resp, tool_name, tool_data, client, model, history). No chart. No memory save."""
        try:
            history = await sync_to_async(ConversationMemory.get_history)(chat_id)
        except Exception:
            history = []

        provider = getattr(settings, 'LLM_PROVIDER', 'openai')
        today = await sync_to_async(timezone.localdate)()

        if provider == 'gemini':
            api_key = getattr(settings, 'GEMINI_API_KEY', '')
            if not api_key:
                return "❌ Gemini not configured.", None, None, None, None, []
            client = OpenAI(api_key=api_key, base_url='https://generativelanguage.googleapis.com/v1beta/openai/')
            model = getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')
            text_resp, tool_name, tool_data = await BIAgent._call_with_tools_and_data(client, model, text, today, history)
        else:
            api_key = getattr(settings, 'OPENAI_API_KEY', '')
            if not api_key:
                return "❌ LLM not configured.", None, None, None, None, []
            client = OpenAI(api_key=api_key)
            model = getattr(settings, 'LLM_MODEL', 'gpt-4o-mini')
            text_resp, tool_name, tool_data = await BIAgent._call_with_tools_and_data(client, model, text, today, history)

        return text_resp, tool_name, tool_data, client, model, history

    @staticmethod
    def should_generate_chart(text: str, force_chart: bool = False) -> bool:
        chart_keywords = ['chart', 'graph', 'plot', 'visual', 'show me']
        return force_chart or any(kw in text.lower() for kw in chart_keywords)

    @staticmethod
    def should_generate_xlsx(text: str, force_xlsx: bool = False) -> bool:
        xlsx_keywords = ['spreadsheet', 'xlsx', 'excel', 'sheet', 'export', 'download', 'csv']
        return force_xlsx or any(kw in text.lower() for kw in xlsx_keywords)

    @staticmethod
    def generate_chart(tool_name: str, tool_data: dict) -> Optional[BytesIO]:
        if tool_name and tool_data:
            return BiChartAdapter.for_any(tool_name, tool_data)
        return None

    @staticmethod
    def generate_xlsx(tool_name: str, tool_data: dict) -> Optional[tuple]:
        if tool_name and tool_data:
            return BiXlsxAdapter.for_any(tool_name, tool_data)
        return None

    @staticmethod
    async def process_message_with_chart(chat_id: str, text: str, force_chart: bool = False, force_xlsx: bool = False) -> tuple:
        text_resp, tool_name, tool_data, client, model, history = await BIAgent._process_message_data(chat_id, text)

        if text_resp.startswith("❌"):
            return text_resp, None, None, None

        wants_chart_now = BIAgent.should_generate_chart(text, force_chart)
        wants_xlsx_now = BIAgent.should_generate_xlsx(text, force_xlsx)
        should_chart = wants_chart_now
        should_xlsx = wants_xlsx_now
        if tool_name and tool_data:
            if not wants_chart_now:
                should_chart = await sync_to_async(ConversationMemory.has_chart_intent)(chat_id, history=history)
            if not wants_xlsx_now:
                should_xlsx = await sync_to_async(ConversationMemory.has_xlsx_intent)(chat_id, history=history)

        chart_buf = None
        if tool_name and tool_data and should_chart:
            chart_buf = await sync_to_async(BiChartAdapter.for_any)(tool_name, tool_data)

        xlsx_buf = None
        xlsx_name = None
        if tool_name and tool_data and should_xlsx:
            xlsx_result = await sync_to_async(BiXlsxAdapter.for_any)(tool_name, tool_data)
            if xlsx_result:
                xlsx_buf, xlsx_name = xlsx_result

        try:
            if getattr(settings, 'LLM_EVALUATOR_ENABLED', True):
                eval_result = await ResponseReflector.evaluate(
                    text_resp, text, tool_name or '', {},
                    client, model,
                    threshold=getattr(settings, 'LLM_EVALUATOR_THRESHOLD', 7),
                )
                if eval_result['action'] == 'rewrite':
                    eval_messages = BIAgent._build_messages(text, await sync_to_async(timezone.localdate)(), history[-5:])
                    text_resp = await ResponseReflector.regenerate(
                        text_resp, eval_result['issues'], eval_messages, client, model,
                    )
        except Exception as e:
            logger.warning(f"Evaluator failed: {e}")

        try:
            await sync_to_async(ConversationMemory.add_exchange)(
                chat_id, text, text_resp, chart_intent=wants_chart_now, xlsx_intent=wants_xlsx_now,
            )
        except Exception as e:
            logger.warning(f"Failed to save conversation: {e}")

        return text_resp, chart_buf, xlsx_buf, xlsx_name

    @staticmethod
    async def _call_with_tools_and_data(client, model: str, text: str, today, history: list) -> tuple:
        messages = BIAgent._build_messages(text, today, history)
        tool_name = None
        tool_data = None

        def do_first():
            return client.chat.completions.create(
                model=model, messages=messages, tools=_TOOL_DEFINITIONS, tool_choice='auto', **_token_kwargs(model, 600),
            )

        try:
            response = await sync_to_async(do_first)()
            msg = response.choices[0].message

            if not msg.tool_calls and not (msg.content and msg.content.strip()):
                logger.info(f"First chart LLM call returned empty for: {text[:80]}")
                messages.append({
                    'role': 'user',
                    'content': 'Please answer the question directly. If you need data, use a tool. Otherwise provide a helpful response from your knowledge.',
                })
                response = await sync_to_async(do_first)()
                msg = response.choices[0].message

            if msg.tool_calls:
                messages.append(msg)
                branch_data = {}
                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        raw_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        raw_args = {}
                    branch = raw_args.get('branch') if isinstance(raw_args, dict) else None
                    try:
                        raw_data = await sync_to_async(_execute_tool)(fn_name, args)
                    except Exception as e:
                        logger.error(f"Tool {fn_name} failed: {e}")
                        raw_data = {'error': str(e)}

                    if tool_name and tool_name == fn_name:
                        tool_data = _merge_tool_data(tool_data, raw_data)
                    else:
                        tool_name = fn_name
                        tool_data = raw_data

                    if branch and fn_name == tool_name:
                        branch_data[branch] = raw_data

                    messages.append({
                        'role': 'tool',
                        'tool_call_id': tc.id,
                        'content': _limit_tool_data(raw_data),
                    })

                if len(branch_data) > 1:
                    tool_data['_branch_data'] = branch_data

                completion = await sync_to_async(client.chat.completions.create)(
                    model=model, messages=messages, **_token_kwargs(model, 1000),
                )
                content = completion.choices[0].message.content
                if content:
                    return content, tool_name, tool_data
                if tool_data:
                    return _format_json_summary(tool_data), tool_name, tool_data
                return "✅ Done.", tool_name, tool_data

            return msg.content and msg.content.strip() or "I couldn't find an answer to that question.", None, None

        except Exception as e:
            logger.error(f"LLM query with data failed: {e}")
            return "❌ Sorry, I couldn't process that question.", None, None

    @staticmethod
    async def _call_groq(client, model: str, text: str, today, history: list) -> str:
        messages = BIAgent._build_messages(text, today, history)

        functions = [
            {'name': t['function']['name'], 'description': t['function']['description'], 'parameters': t['function']['parameters']}
            for t in _TOOL_DEFINITIONS
        ]

        try:
            response = await sync_to_async(client.chat.completions.create)(
                model=model,
                messages=messages,
                functions=functions,
                function_call='auto',
                max_tokens=600,
            )

            msg = response.choices[0].message

            if msg.function_call:
                fn_name = msg.function_call.name
                try:
                    args = json.loads(msg.function_call.arguments)
                except json.JSONDecodeError:
                    args = {}

                try:
                    raw_data = await sync_to_async(_execute_tool)(fn_name, args)
                except Exception as e:
                    logger.error(f"Groq tool {fn_name} failed: {e}")
                    return f"❌ Error executing {fn_name}"

                messages.append(msg)
                messages.append({
                    'role': 'function',
                    'name': fn_name,
                    'content': _limit_tool_data(raw_data),
                })

                completion = await sync_to_async(client.chat.completions.create)(
                    model=model,
                    messages=messages,
                    max_tokens=1000,
                )
                content = completion.choices[0].message.content
                if content:
                    return content

                return _format_json_summary(raw_data)

            return msg.content or "I couldn't find an answer to that question."

        except Exception as e:
            logger.error(f"Groq query failed: {e}")
            return "❌ Sorry, I couldn't process that question. Try using / commands or rephrase your question."


def _parse_date(val):
    if val:
        return datetime.strptime(val, '%Y-%m-%d').date()
    return timezone.localdate()


class ResponseReflector:
    EVALUATOR_PROMPT = """You are a strict Quality Evaluator for a Business Intelligence assistant.
Evaluate the assistant's response against the user's query and tool data.

USER QUERY: "{query}"
ASSISTANT RESPONSE: "{response}"
TOOL CALLED: {tool_called}
TOOL ARGUMENTS: {tool_args}

EVALUATION CRITERIA (score each 0-10, PASS ≥ {threshold}):

1. format_quality: No raw JSON, function names, or tool internals. KES format correct.
2. conciseness: Answers directly. No excessive clarifying questions. Defaults to today.
3. data_fidelity: Numbers match what the tools would return. No invented data.
4. branch_awareness: Only references Main Shop or Kitengela. Never Kitui/Nakuru.

OUTPUT STRICT JSON ONLY (no markdown, no extra text):
{{"score": <int>, "pass": <bool>, "issues": [<str>],
 "format_quality": <int>, "conciseness": <int>,
 "data_fidelity": <int>, "branch_awareness": <int>}}"""

    RULE_PATTERNS = {
        'raw_json': r'\{.*?"name":\s*".*?".*?\}',
        'phantom_branches': r'\b(kitui|nakuru)\b',
        'excessive_questions': r'\?.*\?',
        'weak_language': r"I can('t|not)|unfortunately|I'm (sorry|unable)",
        'csv_dump': r'(?:tx_id|transaction_id)\s*,\s*(?:amount|sender)',
        'excessive_options': r'(?:\d\)\s*(?:Paste|Prepare|Fetch|Check|Fetch the))',
    }

    @classmethod
    def rule_check(cls, response: str) -> list:
        issues = []
        if re.search(cls.RULE_PATTERNS['raw_json'], response):
            issues.append("Response contains raw JSON or tool call internals")
        if re.search(cls.RULE_PATTERNS['phantom_branches'], response, re.IGNORECASE):
            issues.append("Response references non-existent branches")
        if re.search(cls.RULE_PATTERNS['excessive_questions'], response):
            issues.append("Response asks too many clarifying questions")
        if re.search(cls.RULE_PATTERNS['weak_language'], response, re.IGNORECASE):
            issues.append("Response uses weak language instead of offering solutions")
        if re.search(cls.RULE_PATTERNS['csv_dump'], response, re.IGNORECASE):
            issues.append("Response contains raw CSV data dump instead of letting the system generate the file")
        if re.search(cls.RULE_PATTERNS['excessive_options'], response, re.IGNORECASE):
            issues.append("Response presents numbered options or asks user to pick a choice instead of just doing it")
        if len(response) > 3000:
            issues.append("Response is too verbose")
        return issues

    @staticmethod
    async def evaluate(response: str, query: str, tool_name: str,
                       tool_args: dict, client, model: str,
                       threshold: int = 7) -> dict:
        rule_issues = ResponseReflector.rule_check(response)
        if rule_issues:
            return {
                'score': 0, 'pass': False,
                'issues': rule_issues,
                'action': 'rewrite',
            }

        eval_prompt = ResponseReflector.EVALUATOR_PROMPT.format(
            query=query[:500],
            response=response[:2000],
            tool_called=tool_name or 'none',
            tool_args=json.dumps(tool_args)[:500],
            threshold=threshold,
        )
        try:
            completion = await sync_to_async(client.chat.completions.create)(
                model=model,
                messages=[{'role': 'user', 'content': eval_prompt}],
                max_tokens=300,
            )
            result = json.loads(completion.choices[0].message.content)
            if isinstance(result, dict):
                result.setdefault('issues', [])
                result.setdefault('action', 'accept' if result.get('pass') else 'rewrite')
                return result
        except Exception as e:
            logger.warning(f"Evaluator parse failed: {e}")
        return {'score': 10, 'pass': True, 'issues': [], 'action': 'accept'}

    @staticmethod
    async def regenerate(response: str, issues: list,
                         messages: list, client, model: str) -> str:
        correction = (
            "Your previous answer had quality issues. Rewrite it fixing these:\n"
            + "\n".join(f"- {issue}" for issue in issues)
            + "\nKeep all data accurate. Be direct and concise. Do NOT add suggestions."
        )
        try:
            completion = await sync_to_async(client.chat.completions.create)(
                model=model,
                messages=messages + [
                    {'role': 'assistant', 'content': response},
                    {'role': 'user', 'content': correction},
                ],
                max_tokens=1000,
            )
            corrected = completion.choices[0].message.content
            return corrected or response
        except Exception as e:
            logger.warning(f"Regeneration failed: {e}")
            return response


def _format_json_summary(data):
    if isinstance(data, dict):
        lines = []

        if any(k in data for k in ('total_revenue', 'total_sales')):
            tr = float(data.get('total_revenue', 0))
            ts = float(data.get('total_sales', 0))
            if tr:
                lines.append(f"Total revenue: KES {tr:,.2f}")
            if ts:
                lines.append(f"Total sales: KES {ts:,.2f}")

        if 'total' in data and not lines:
            total_val = data['total']
            if isinstance(total_val, dict):
                for k, v in total_val.items():
                    try:
                        lines.append(f"{k}: KES {float(v):,.2f}")
                    except (ValueError, TypeError):
                        lines.append(f"{k}: {v}")
            else:
                try:
                    lines.append(f"Total: KES {float(total_val):,.2f}")
                except (ValueError, TypeError):
                    lines.append(f"Total: {total_val}")

        if 'buckets' in data:
            for k, v in data['buckets'].items():
                if isinstance(v, dict):
                    amt = float(v.get('amount', 0))
                    lines.append(f"{k}: KES {amt:,.2f}")
                else:
                    try:
                        lines.append(f"{k}: KES {float(v):,.2f}")
                    except (ValueError, TypeError):
                        lines.append(f"{k}: {v}")

        for key, label in [
            ('out_of_stock_count', 'Out of stock'),
            ('low_stock_count', 'Low stock'),
            ('in_stock_count', 'In stock'),
            ('total_products', 'Products'),
            ('total_stock_value', 'Stock value'),
            ('x', 'X (Sales)'),
            ('y', 'Y (Payment)'),
            ('z', 'Z (Diff)'),
            ('status', 'Status'),
        ]:
            if key in data and not any(key in l for l in lines):
                val = data[key]
                if key in ('x', 'y') and isinstance(val, (int, float)):
                    lines.append(f"{label}: KES {float(val):,}")
                elif key == 'z' and isinstance(val, (int, float)):
                    v = float(val)
                    lines.append(f"{label}: {'OVER' if v > 0 else 'UNDER'} KES {abs(v):,}")
                elif key == 'total_stock_value':
                    try:
                        lines.append(f"{label}: KES {float(val):,.2f}")
                    except (ValueError, TypeError):
                        lines.append(f"{label}: {val}")
                else:
                    lines.append(f"{label}: {val}")

        if 'error' in data:
            lines.append(f"⚠️ {data['error']}")

        if lines:
            return ' | '.join(lines)

        top_keys = list(data.keys())[:6]
        parts = []
        for k in top_keys:
            v = data[k]
            if isinstance(v, (int, float)):
                parts.append(f"{k}: {float(v):,.2f}")
            elif isinstance(v, str) and len(v) < 80:
                parts.append(f"{k}: {v}")
        if parts:
            return ' | '.join(parts)

        return f"Data from {len(data)} fields"

    if isinstance(data, list):
        return f"Results: {len(data)} items"

    return str(data)[:500]
