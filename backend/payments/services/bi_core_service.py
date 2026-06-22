from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from django.db.models import Q, Sum
from django.utils import timezone

from payments.models import (
    CombinedOrder,
    CombinedOrderLineItem,
    InventoryMovement,
    MerchandiseOrder,
    MerchandiseOrderLine,
    PaymentGateway,
    Product,
    ProductLine,
    StockTakeSession,
    Transaction,
    TransactionLineItem,
)
from payments.services.analytics_service import AnalyticsService
from payments.services.stock_report_service import StockReportService
from payments.services.reconciliation_v2_service import ReconciliationV2Service
from payments.services.merchandise_service import MerchandiseService


PAYBILL_TYPES = [PaymentGateway.GatewayType.MPESA_PAYBILL]
PDQ_TYPES = [PaymentGateway.GatewayType.PDQ]
TILL_TYPE = PaymentGateway.GatewayType.MPESA_TILL
MERCH_TYPE = PaymentGateway.GatewayType.MERCHANDISE
COMBINED_POOL_TYPES = [PaymentGateway.GatewayType.MPESA_PAYBILL, PaymentGateway.GatewayType.PDQ]
PAYBILL_PDQ_TYPES = COMBINED_POOL_TYPES


def _base_exclude():
    return Q(sender_name__icontains='7974481') | Q(sender_phone__icontains='7974481')


def _get_gateway_ids_by_types(types: List[str]) -> List[int]:
    return list(PaymentGateway.objects.filter(gateway_type__in=types, is_active=True).values_list('id', flat=True))


def _classify_gateway(gateway) -> str:
    if not gateway:
        return 'PAYBILL'
    gt = gateway.gateway_type
    if gt == PaymentGateway.GatewayType.MPESA_PAYBILL:
        return 'PAYBILL'
    if gt == PaymentGateway.GatewayType.PDQ:
        return 'PDQ'
    if gt == TILL_TYPE:
        return 'TILL'
    if gt == MERCH_TYPE:
        return 'MERCH'
    return 'PAYBILL'


def _get_date_range(date_obj):
    start = timezone.make_aware(datetime.combine(date_obj, datetime.min.time()))
    end = timezone.make_aware(datetime.combine(date_obj, datetime.max.time()))
    return start, end


class BiCoreService:
    REVENUE_BUCKETS = ['PAYBILL', 'PDQ', 'TILL', 'MERCH']
    SALES_BUCKETS = ['PAYBILL', 'PDQ', 'TILL']

    @staticmethod
    def get_revenue_by_bucket(report_date=None) -> Dict:
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        buckets = {b: Decimal('0.00') for b in BiCoreService.REVENUE_BUCKETS}
        bucket_counts = {b: 0 for b in BiCoreService.REVENUE_BUCKETS}
        bucket_txns = {b: [] for b in BiCoreService.REVENUE_BUCKETS}

        txns = Transaction.objects.exclude(
            _base_exclude() | Q(combined_order_parent__isnull=False)
        ).filter(
            timestamp__gte=start_dt, timestamp__lte=end_dt
        ).select_related('gateway')

        for txn in txns:
            bucket = _classify_gateway(txn.gateway)
            amount = txn.amount or Decimal('0.00')
            buckets[bucket] += amount
            bucket_counts[bucket] += 1
            bucket_txns[bucket].append({
                'tx_id': txn.tx_id,
                'amount': float(amount),
                'status': txn.status,
            })

        return {
            'date': report_date.isoformat(),
            'buckets': {
                b: {
                    'amount': float(buckets[b]),
                    'count': bucket_counts[b],
                }
                for b in BiCoreService.REVENUE_BUCKETS
            },
            'total': float(sum(buckets.values())),
        }

    @staticmethod
    def get_fulfillment_by_gateway(report_date=None) -> Dict:
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        buckets = {b: Decimal('0.00') for b in BiCoreService.SALES_BUCKETS}
        bucket_counts = {b: 0 for b in BiCoreService.SALES_BUCKETS}

        fulfilled_statuses = [
            Transaction.OrderStatus.FULFILLED,
            Transaction.OrderStatus.PARTIALLY_FULFILLED,
        ]

        single_txns = Transaction.objects.exclude(
            _base_exclude() | Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) | Q(combined_order_parent__isnull=False)
        ).filter(
            status__in=fulfilled_statuses
        ).filter(
            Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
            Q(timestamp__gte=start_dt, timestamp__lte=end_dt, amount_fulfilled__gt=0)
        ).select_related('gateway')

        for txn in single_txns:
            bucket = _classify_gateway(txn.gateway)
            if bucket == 'MERCH':
                continue
            fulfilled = txn.amount_fulfilled or Decimal('0.00')
            buckets[bucket] += fulfilled
            bucket_counts[bucket] += 1

        combined_fulfilled = Decimal('0.00')
        combined_orders = CombinedOrder.objects.filter(
            Q(status__in=[
                CombinedOrder.Status.PARTIALLY_FULFILLED,
                CombinedOrder.Status.FULFILLED,
            ]),
            Q(fulfilled_at__gte=start_dt, fulfilled_at__lte=end_dt) |
            Q(updated_at__gte=start_dt, updated_at__lte=end_dt)
        )
        for order in combined_orders:
            after_combine = order.amount_fulfilled - order.base_amount_fulfilled
            if after_combine > 0:
                combined_fulfilled += after_combine

        buckets['TILL'] += combined_fulfilled
        if combined_fulfilled > 0:
            bucket_counts['TILL'] += combined_orders.count()

        return {
            'date': report_date.isoformat(),
            'buckets': {
                b: {
                    'amount': float(buckets[b]),
                    'count': bucket_counts[b],
                }
                for b in BiCoreService.SALES_BUCKETS
            },
            'total': float(sum(buckets.values())),
        }

    @staticmethod
    def get_unused_combined_pool(report_date=None) -> Dict:
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        gateway_ids = _get_gateway_ids_by_types(COMBINED_POOL_TYPES)
        unfulfilled_statuses = [
            Transaction.OrderStatus.NOT_PROCESSED,
            Transaction.OrderStatus.PROCESSING,
        ]

        transactions = Transaction.objects.exclude(
            _base_exclude() | Q(combined_order_parent__isnull=False) | Q(status=Transaction.OrderStatus.COMBINED_FULFILLED)
        ).filter(
            gateway_id__in=gateway_ids,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt,
            status__in=unfulfilled_statuses,
        )

        total = transactions.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        return {
            'date': report_date.isoformat(),
            'amount': float(total),
            'count': transactions.count(),
            'transactions': list(transactions.values('tx_id', 'amount', 'sender_name', 'status')),
        }

    @staticmethod
    def get_credit_lost(report_date=None) -> Dict:
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        gateway_ids = _get_gateway_ids_by_types(COMBINED_POOL_TYPES)

        transactions = Transaction.objects.exclude(
            _base_exclude() | Q(combined_order_parent__isnull=False) | Q(status=Transaction.OrderStatus.COMBINED_FULFILLED)
        ).filter(
            gateway_id__in=gateway_ids,
            status=Transaction.OrderStatus.PARTIALLY_FULFILLED,
        ).filter(
            Q(timestamp__gte=start_dt, timestamp__lte=end_dt) |
            Q(completed_at__gte=start_dt, completed_at__lte=end_dt)
        )

        total_lost = Decimal('0.00')
        tx_list = []
        for txn in transactions:
            remaining = txn.amount - txn.amount_fulfilled
            if remaining > 0:
                total_lost += remaining
                tx_list.append({
                    'tx_id': txn.tx_id,
                    'amount': float(txn.amount),
                    'amount_fulfilled': float(txn.amount_fulfilled),
                    'remaining_lost': float(remaining),
                    'sender_name': txn.sender_name,
                })

        return {
            'date': report_date.isoformat(),
            'amount': float(total_lost),
            'count': len(tx_list),
            'transactions': tx_list,
        }

    @staticmethod
    def get_merch_fulfillment(report_date=None) -> Dict:
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        fulfilled_orders = MerchandiseOrder.objects.filter(
            status=MerchandiseOrder.Status.FULFILLED,
            fulfilled_at__gte=start_dt,
            fulfilled_at__lte=end_dt,
        )

        total_revenue = Decimal('0.00')
        total_items = 0
        for order in fulfilled_orders:
            for line in order.lines.all():
                total_revenue += line.line_total
                total_items += line.quantity

        pending_orders = MerchandiseOrder.objects.filter(
            status=MerchandiseOrder.Status.PENDING,
            created_at__gte=start_dt,
            created_at__lte=end_dt,
        )

        return {
            'date': report_date.isoformat(),
            'fulfilled_revenue': float(total_revenue),
            'fulfilled_items': total_items,
            'fulfilled_orders': fulfilled_orders.count(),
            'pending_orders': pending_orders.count(),
        }

    @staticmethod
    def get_stock_alerts() -> Dict:
        report = StockReportService.generate_stock_report()
        summary = report['summary']
        low_stock_products = []
        out_of_stock_products = []

        for line_data in report['product_lines']:
            for product in line_data['products']:
                if product['stock_status'] == 'OUT_OF_STOCK':
                    out_of_stock_products.append(product)
                elif product['stock_status'] == 'LOW_STOCK':
                    low_stock_products.append(product)

        return {
            'generated_at': report['generated_at'],
            'out_of_stock_count': summary['out_of_stock_count'],
            'low_stock_count': summary['low_stock_count'],
            'in_stock_count': summary['in_stock_count'],
            'total_stock_value': summary['total_stock_value'],
            'out_of_stock_products': [
                {'name': p['prod_name'], 'code': p['prod_code'], 'quantity': p['quantity']}
                for p in out_of_stock_products[:20]
            ],
            'low_stock_products': [
                {'name': p['prod_name'], 'code': p['prod_code'], 'quantity': p['quantity'], 'reorder_level': p['reorder_level']}
                for p in low_stock_products[:20]
            ],
        }

    @staticmethod
    def get_discrepancies(report_date=None) -> Dict:
        if report_date is None:
            report_date = timezone.localdate()
        from payments.services.reconciliation_service import ReconciliationService
        return ReconciliationService.identify_discrepancies(report_date)

    @staticmethod
    def get_reconciliation(report_date=None) -> Dict:
        if report_date is None:
            report_date = timezone.localdate()
        return ReconciliationV2Service.generate_daily_report(report_date)

    @staticmethod
    def get_issuer_stats() -> Dict:
        active = Transaction.objects.filter(is_in_issuance=True).count()
        pending = Transaction.objects.exclude(
            _base_exclude() | Q(status__in=[
                Transaction.OrderStatus.FULFILLED,
                Transaction.OrderStatus.CANCELLED,
                Transaction.OrderStatus.COMBINED_FULFILLED,
            ])
        ).count()
        in_issuance = Transaction.objects.filter(
            is_in_issuance=True,
            status__in=[Transaction.OrderStatus.PROCESSING, Transaction.OrderStatus.PARTIALLY_FULFILLED],
        ).count()
        return {
            'pending_transactions': pending,
            'active_issuances': active,
            'in_issuance': in_issuance,
        }

    @staticmethod
    def get_registration_kits(report_date=None) -> Dict:
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)
        base_exclude = _base_exclude()

        reg_txns = Transaction.objects.exclude(
            base_exclude | Q(status=Transaction.OrderStatus.COMBINED_FULFILLED)
        ).filter(
            is_registration=True,
            registration_kit_issued=True,
        ).filter(
            Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
            Q(timestamp__gte=start_dt, timestamp__lte=end_dt)
        ).select_related('gateway')

        total_kits = reg_txns.aggregate(total=Sum('registration_kit_quantity'))['total'] or 0
        kit_value = Decimal('200.00')
        total_value = kit_value * total_kits

        return {
            'date': report_date.isoformat(),
            'kits_issued': total_kits,
            'total_value': float(total_value),
            'transaction_count': reg_txns.count(),
        }

    @staticmethod
    def get_revenue_vs_sales(report_date=None) -> Dict:
        if report_date is None:
            report_date = timezone.localdate()

        revenue = BiCoreService.get_revenue_by_bucket(report_date)
        sales = BiCoreService.get_fulfillment_by_gateway(report_date)
        unused = BiCoreService.get_unused_combined_pool(report_date)
        credit_lost = BiCoreService.get_credit_lost(report_date)

        total_revenue = Decimal(str(revenue['total']))
        total_sales = Decimal(str(sales['total']))
        gap = total_revenue - total_sales
        fulfillment_rate = float(total_sales / total_revenue * 100) if total_revenue > 0 else 0.0

        buckets_with_gap = {}
        for b in BiCoreService.SALES_BUCKETS:
            rev = Decimal(str(revenue['buckets'][b]['amount']))
            sal = Decimal(str(sales['buckets'][b]['amount']))
            b_gap = rev - sal
            b_rate = float(sal / rev * 100) if rev > 0 else 0.0
            buckets_with_gap[b] = {
                'revenue': float(rev),
                'sales': float(sal),
                'gap': float(b_gap),
                'fulfillment_rate': b_rate,
            }
        buckets_with_gap['MERCH'] = {
            'revenue': float(revenue['buckets']['MERCH']['amount']),
            'sales': 0.0,
            'gap': float(revenue['buckets']['MERCH']['amount']),
            'fulfillment_rate': 0.0,
        }

        return {
            'date': report_date.isoformat(),
            'total_revenue': float(total_revenue),
            'total_sales': float(total_sales),
            'gap': float(gap),
            'fulfillment_rate': fulfillment_rate,
            'unused_pool': unused,
            'credit_lost_pool': credit_lost,
            'buckets': buckets_with_gap,
        }
