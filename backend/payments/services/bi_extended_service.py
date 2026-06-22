import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from django.db import models
from django.db.models import F, Q, Sum, Count
from django.utils import timezone

from payments.models import (
    CombinedOrder,
    CombinedOrderLineItem,
    InventoryMovement,
    ManualPayment,
    PaymentGateway,
    Product,
    ProductLine,
    Transaction,
    TransactionLineItem,
)
from payments.services.bi_core_service import (
    BiCoreService,
    PAYBILL_PDQ_TYPES,
    _base_exclude,
    _get_date_range,
    _get_gateway_ids_by_types,
)


logger = logging.getLogger(__name__)


# ============================================================================
# Product Queries
# ============================================================================

def _get_transaction_date_filter(date_obj):
    """Get start/end datetimes for a single date (covers both timestamp and completed_at)."""
    start, end = _get_date_range(date_obj)
    return start, end


def _product_search(name_or_code: str) -> List[Product]:
    """Search products by name or code (partial, case-insensitive)."""
    qs = Product.objects.filter(is_active=True).filter(
        Q(prod_name__icontains=name_or_code) |
        Q(prod_code__icontains=name_or_code) |
        Q(sku__icontains=name_or_code) |
        Q(barcode__icontains=name_or_code)
    ).select_related('product_line')
    return list(qs)


class BiExtendedService:

    # ========================================================================
    # PRODUCT QUERIES
    # ========================================================================

    @staticmethod
    def get_product_sales(product_query: str, report_date=None) -> Dict:
        """
        Sales (quantity + revenue) for a product by name/code/SKU on a given date.
        Searches TransactionLineItem by the frozen scanned name/code and by Product FK.
        """
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        products = _product_search(product_query)
        if not products:
            return {
                'query': product_query,
                'date': report_date.isoformat(),
                'found': False,
                'message': f"No product found matching '{product_query}'",
            }

        product_ids = [p.id for p in products]

        line_items = TransactionLineItem.objects.filter(
            product_id__in=product_ids,
            scanned_at__gte=start_dt,
            scanned_at__lte=end_dt,
        ).select_related('transaction')

        total_qty = 0
        total_revenue = Decimal('0.00')
        total_cost = Decimal('0.00')
        total_pv = Decimal('0.00')
        fulfillment_count = 0

        for li in line_items:
            txn = li.transaction
            if txn.status in [
                Transaction.OrderStatus.FULFILLED,
                Transaction.OrderStatus.PARTIALLY_FULFILLED,
                Transaction.OrderStatus.COMBINED_FULFILLED,
            ]:
                total_qty += li.quantity
                total_revenue += li.line_total
                total_cost += li.line_cost
                total_pv += li.line_pv
                fulfillment_count += 1

        results = []
        for p in products:
            results.append({
                'id': p.id,
                'name': p.prod_name,
                'code': p.prod_code,
                'price': float(p.current_price),
                'current_stock': p.quantity,
                'stock_status': p.stock_status if hasattr(p, 'stock_status') else 'unknown',
            })

        return {
            'query': product_query,
            'date': report_date.isoformat(),
            'found': True,
            'products': results,
            'total_quantity_sold': total_qty,
            'total_revenue': float(total_revenue),
            'total_cost': float(total_cost),
            'total_pv': float(total_pv),
            'fulfillment_count': fulfillment_count,
        }

    @staticmethod
    def get_product_stock(product_query: str) -> Dict:
        """Current stock information for a product by name/code/SKU."""
        products = _product_search(product_query)
        if not products:
            return {
                'query': product_query,
                'found': False,
                'message': f"No product found matching '{product_query}'",
            }

        results = []
        for p in products:
            line_name = p.product_line.name if p.product_line else None
            status = 'OUT_OF_STOCK' if p.quantity <= 0 else (
                'LOW_STOCK' if p.quantity <= p.reorder_level else 'IN_STOCK'
            )
            results.append({
                'id': p.id,
                'name': p.prod_name,
                'code': p.prod_code,
                'category': line_name,
                'quantity': p.quantity,
                'reorder_level': p.reorder_level,
                'stock_status': status,
                'price': float(p.current_price),
                'cost_price': float(p.cost_price),
                'pv': float(p.current_pv),
                'stock_value': float(p.quantity * p.current_price),
            })

        total_value = sum(r['stock_value'] for r in results)
        return {
            'query': product_query,
            'found': True,
            'products': results,
            'total_products': len(results),
            'total_stock_value': total_value,
        }

    @staticmethod
    def get_top_products(report_date=None, limit: int = 10) -> Dict:
        """Top N selling products by quantity on a given date."""
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        line_items = TransactionLineItem.objects.filter(
            scanned_at__gte=start_dt,
            scanned_at__lte=end_dt,
        ).select_related('product')

        product_agg = {}
        for li in line_items:
            if li.transaction.status not in [
                Transaction.OrderStatus.FULFILLED,
                Transaction.OrderStatus.PARTIALLY_FULFILLED,
                Transaction.OrderStatus.COMBINED_FULFILLED,
            ]:
                continue
            pid = li.product_id
            if pid not in product_agg:
                p = li.product
                product_agg[pid] = {
                    'name': p.prod_name,
                    'code': p.prod_code,
                    'category': p.product_line.name if p.product_line else None,
                    'quantity': 0,
                    'revenue': Decimal('0.00'),
                }
            product_agg[pid]['quantity'] += li.quantity
            product_agg[pid]['revenue'] += li.line_total

        ranked = sorted(product_agg.values(), key=lambda x: x['quantity'], reverse=True)
        top = ranked[:limit]

        return {
            'date': report_date.isoformat(),
            'limit': limit,
            'products': [
                {
                    'name': p['name'],
                    'code': p['code'],
                    'category': p['category'],
                    'quantity_sold': p['quantity'],
                    'revenue': float(p['revenue']),
                }
                for p in top
            ],
            'total_products_sold': len(product_agg),
        }

    @staticmethod
    def get_top_products_by_revenue(report_date=None, limit: int = 10) -> Dict:
        """Top N products by revenue on a given date."""
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        line_items = TransactionLineItem.objects.filter(
            scanned_at__gte=start_dt,
            scanned_at__lte=end_dt,
        ).select_related('product')

        product_agg = {}
        for li in line_items:
            if li.transaction.status not in [
                Transaction.OrderStatus.FULFILLED,
                Transaction.OrderStatus.PARTIALLY_FULFILLED,
                Transaction.OrderStatus.COMBINED_FULFILLED,
            ]:
                continue
            pid = li.product_id
            if pid not in product_agg:
                p = li.product
                product_agg[pid] = {
                    'name': p.prod_name,
                    'code': p.prod_code,
                    'category': p.product_line.name if p.product_line else None,
                    'quantity': 0,
                    'revenue': Decimal('0.00'),
                }
            product_agg[pid]['quantity'] += li.quantity
            product_agg[pid]['revenue'] += li.line_total

        ranked = sorted(product_agg.values(), key=lambda x: x['revenue'], reverse=True)
        top = ranked[:limit]

        return {
            'date': report_date.isoformat(),
            'limit': limit,
            'products': [
                {
                    'name': p['name'],
                    'code': p['code'],
                    'category': p['category'],
                    'quantity_sold': p['quantity'],
                    'revenue': float(p['revenue']),
                }
                for p in top
            ],
            'total_products_sold': len(product_agg),
        }

    @staticmethod
    def get_category_sales(category_name: str, report_date=None) -> Dict:
        """Sales for a product category (ProductLine) on a given date."""
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        lines = ProductLine.objects.filter(name__icontains=category_name)
        if not lines:
            return {
                'query': category_name,
                'date': report_date.isoformat(),
                'found': False,
                'message': f"No product category found matching '{category_name}'",
            }

        product_ids = Product.objects.filter(
            product_line__in=lines, is_active=True
        ).values_list('id', flat=True)

        line_items = TransactionLineItem.objects.filter(
            product_id__in=list(product_ids),
            scanned_at__gte=start_dt,
            scanned_at__lte=end_dt,
        ).select_related('transaction')

        total_qty = 0
        total_revenue = Decimal('0.00')
        total_cost = Decimal('0.00')
        total_pv = Decimal('0.00')

        for li in line_items:
            if li.transaction.status not in [
                Transaction.OrderStatus.FULFILLED,
                Transaction.OrderStatus.PARTIALLY_FULFILLED,
                Transaction.OrderStatus.COMBINED_FULFILLED,
            ]:
                continue
            total_qty += li.quantity
            total_revenue += li.line_total
            total_cost += li.line_cost
            total_pv += li.line_pv

        categories = [{'id': pl.id, 'name': pl.name} for pl in lines]

        return {
            'query': category_name,
            'date': report_date.isoformat(),
            'found': True,
            'categories': categories,
            'total_quantity_sold': total_qty,
            'total_revenue': float(total_revenue),
            'total_cost': float(total_cost),
            'total_pv': float(total_pv),
        }

    @staticmethod
    def get_stock_by_category() -> Dict:
        """Current stock grouped by product category (ProductLine)."""
        lines = ProductLine.objects.all().order_by('name')
        result_categories = []
        total_value = Decimal('0.00')
        total_products = 0

        for pl in lines:
            products = Product.objects.filter(product_line=pl, is_active=True)
            cat_value = Decimal('0.00')
            cat_count = 0
            for p in products:
                cat_value += p.quantity * p.current_price
                cat_count += p.quantity
            total_value += cat_value
            total_products += products.count()
            result_categories.append({
                'id': pl.id,
                'name': pl.name,
                'product_count': products.count(),
                'total_stock_units': cat_count,
                'total_value': float(cat_value),
            })

        return {
            'total_categories': len(result_categories),
            'total_products': total_products,
            'total_stock_value': float(total_value),
            'categories': result_categories,
        }

    @staticmethod
    def get_inventory_value() -> Dict:
        """Total current inventory value (stock level × current price)."""
        products = Product.objects.filter(is_active=True)
        total_value = Decimal('0.00')
        total_cost_value = Decimal('0.00')
        total_pv = Decimal('0.00')
        total_units = 0
        total_products = products.count()

        for p in products:
            qty = p.quantity
            total_value += qty * p.current_price
            total_cost_value += qty * p.cost_price
            total_pv += qty * p.current_pv
            total_units += qty

        return {
            'total_products': total_products,
            'total_stock_units': total_units,
            'total_value_at_retail': float(total_value),
            'total_value_at_cost': float(total_cost_value),
            'total_pv': float(total_pv),
        }

    @staticmethod
    def get_stock_movements(product_query: str = None, days: int = 7) -> Dict:
        """Recent inventory movements, optionally filtered by product."""
        start_dt = timezone.now() - timedelta(days=days)

        qs = InventoryMovement.objects.filter(created_at__gte=start_dt)

        if product_query:
            products = _product_search(product_query)
            if not products:
                return {
                    'query': product_query,
                    'days': days,
                    'found': False,
                    'message': f"No product found matching '{product_query}'",
                }
            qs = qs.filter(product__in=products)

        qs = qs.select_related('product', 'performed_by_user').order_by('-created_at')[:50]

        by_type = {}
        movements_list = []
        for mov in qs:
            mtype = mov.movement_type
            if mtype not in by_type:
                by_type[mtype] = {'count': 0, 'total_change': 0}
            by_type[mtype]['count'] += 1
            by_type[mtype]['total_change'] += mov.quantity_change

            movements_list.append({
                'id': mov.id,
                'type': mov.get_movement_type_display(),
                'product': mov.product.prod_name,
                'quantity_change': mov.quantity_change,
                'quantity_before': mov.quantity_before,
                'quantity_after': mov.quantity_after,
                'reference': mov.reference,
                'performed_by': mov.performed_by_user.username if mov.performed_by_user else mov.performed_by,
                'created_at': mov.created_at.isoformat(),
            })

        return {
            'days': days,
            'product_query': product_query,
            'total_movements': len(movements_list),
            'by_type': by_type,
            'movements': movements_list,
        }

    @staticmethod
    def get_product_sales_trend(product_query: str, days: int = 30) -> Dict:
        """Daily sales trend for a product over N days."""
        products = _product_search(product_query)
        if not products:
            return {
                'query': product_query,
                'found': False,
                'message': f"No product found matching '{product_query}'",
            }

        product_ids = [p.id for p in products]
        end_date = timezone.localdate()
        start_date = end_date - timedelta(days=days - 1)

        data_points = []
        current = start_date
        while current <= end_date:
            s, e = _get_date_range(current)
            line_items = TransactionLineItem.objects.filter(
                product_id__in=product_ids,
                scanned_at__gte=s,
                scanned_at__lte=e,
            ).select_related('transaction')

            qty = 0
            rev = Decimal('0.00')
            for li in line_items:
                if li.transaction.status not in [
                    Transaction.OrderStatus.FULFILLED,
                    Transaction.OrderStatus.PARTIALLY_FULFILLED,
                    Transaction.OrderStatus.COMBINED_FULFILLED,
                ]:
                    continue
                qty += li.quantity
                rev += li.line_total

            data_points.append({
                'date': current.isoformat(),
                'quantity': qty,
                'revenue': float(rev),
            })
            current += timedelta(days=1)

        total_qty = sum(dp['quantity'] for dp in data_points)
        total_rev = sum(dp['revenue'] for dp in data_points)
        days_with_sales = sum(1 for dp in data_points if dp['quantity'] > 0)

        product_info = [
            {'name': p.prod_name, 'code': p.prod_code} for p in products
        ]

        return {
            'query': product_query,
            'product_info': product_info,
            'period_days': days,
            'total_quantity': total_qty,
            'total_revenue': total_rev,
            'days_with_sales': days_with_sales,
            'daily_average_qty': round(total_qty / days, 1) if days else 0,
            'daily_average_revenue': round(total_rev / days, 2) if days else 0,
            'data_points': data_points,
        }

    # ========================================================================
    # TRANSACTION & CUSTOMER QUERIES
    # ========================================================================

    @staticmethod
    def search_transactions(query: str) -> Dict:
        """
        Search transactions by tx_id, sender name, phone, or notes (partial match).
        Returns up to 20 results.
        """
        results = Transaction.objects.exclude(
            _base_exclude()
        ).filter(
            Q(tx_id__icontains=query) |
            Q(sender_name__icontains=query) |
            Q(sender_phone__icontains=query) |
            Q(notes__icontains=query)
        ).select_related('gateway', 'processed_by', 'completed_by').order_by('-timestamp')[:20]

        return {
            'query': query,
            'total_found': results.count(),
            'transactions': [
                {
                    'tx_id': t.tx_id,
                    'amount': float(t.amount),
                    'amount_fulfilled': float(t.amount_fulfilled) if t.amount_fulfilled else 0,
                    'status': t.status,
                    'status_display': t.get_status_display(),
                    'sender_name': t.sender_name,
                    'sender_phone': t.sender_phone,
                    'gateway': t.gateway.name if t.gateway else None,
                    'gateway_type': t.gateway.gateway_type if t.gateway else None,
                    'timestamp': t.timestamp.isoformat() if t.timestamp else None,
                    'completed_at': t.completed_at.isoformat() if t.completed_at else None,
                    'is_registration': t.is_registration,
                    'registration_kit_issued': t.registration_kit_issued,
                }
                for t in results
            ],
        }

    @staticmethod
    def get_transaction_detail(tx_id: str) -> Dict:
        """Full detail for a single transaction by tx_id."""
        try:
            txn = Transaction.objects.select_related(
                'gateway', 'processed_by', 'completed_by', 'cancelled_by', 'location'
            ).prefetch_related('line_items__product__product_line').get(tx_id=tx_id)
        except Transaction.DoesNotExist:
            return {'found': False, 'message': f"Transaction '{tx_id}' not found"}

        line_items = []
        for li in txn.line_items.all():
            line_items.append({
                'product_name': li.scanned_prod_name,
                'product_code': li.scanned_prod_code,
                'quantity': li.quantity,
                'unit_price': float(li.scanned_price),
                'line_total': float(li.line_total),
                'line_cost': float(li.line_cost),
                'line_pv': float(li.line_pv),
                'scanned_at': li.scanned_at.isoformat(),
            })

        combined_info = None
        try:
            co = txn.combined_order_parent
            if co:
                combined_info = {
                    'combined_order_id': co.combined_order_id,
                    'status': co.status,
                    'total_amount': float(co.total_amount),
                    'amount_fulfilled': float(co.amount_fulfilled),
                }
        except CombinedOrder.DoesNotExist:
            pass

        return {
            'found': True,
            'tx_id': txn.tx_id,
            'sender_name': txn.sender_name,
            'sender_phone': txn.sender_phone,
            'amount': float(txn.amount),
            'amount_fulfilled': float(txn.amount_fulfilled) if txn.amount_fulfilled else 0,
            'remaining': float(txn.amount - (txn.amount_fulfilled or 0)),
            'status': txn.status,
            'status_display': txn.get_status_display(),
            'gateway': txn.gateway.name if txn.gateway else None,
            'gateway_type': txn.gateway.gateway_type if txn.gateway else None,
            'timestamp': txn.timestamp.isoformat() if txn.timestamp else None,
            'completed_at': txn.completed_at.isoformat() if txn.completed_at else None,
            'is_registration': txn.is_registration,
            'registration_kit_issued': txn.registration_kit_issued,
            'registration_kit_quantity': txn.registration_kit_quantity,
            'processed_by': txn.processed_by.username if txn.processed_by else None,
            'completed_by': txn.completed_by.username if txn.completed_by else None,
            'cancelled_by': txn.cancelled_by.username if txn.cancelled_by else None,
            'location': txn.location.name if txn.location else None,
            'total_cost': float(txn.total_cost) if txn.total_cost else 0,
            'total_pv': float(txn.total_pv) if txn.total_pv else 0,
            'notes': txn.notes,
            'line_items': line_items,
            'combined_order': combined_info,
        }

    @staticmethod
    def search_customer(query: str) -> Dict:
        """Find customers by name or phone and show their transaction history."""
        transactions = Transaction.objects.exclude(
            _base_exclude()
        ).filter(
            Q(sender_name__icontains=query) |
            Q(sender_phone__icontains=query)
        ).select_related('gateway').order_by('-timestamp')[:20]

        if not transactions:
            return {
                'query': query,
                'found': False,
                'message': f"No customers found matching '{query}'",
            }

        customers = {}
        for t in transactions:
            key = f"{t.sender_name}|{t.sender_phone}"
            if key not in customers:
                customers[key] = {
                    'name': t.sender_name,
                    'phone': t.sender_phone,
                    'total_spent': Decimal('0.00'),
                    'total_fulfilled': Decimal('0.00'),
                    'transaction_count': 0,
                    'last_purchase': None,
                    'first_purchase': None,
                    'payment_methods': set(),
                }
            c = customers[key]
            c['total_spent'] += t.amount
            c['total_fulfilled'] += t.amount_fulfilled or Decimal('0.00')
            c['transaction_count'] += 1
            if t.gateway:
                c['payment_methods'].add(t.gateway.gateway_type)
            ts = t.timestamp
            if c['last_purchase'] is None or (ts and ts > c['last_purchase']):
                c['last_purchase'] = ts
            if c['first_purchase'] is None or (ts and ts < c['first_purchase']):
                c['first_purchase'] = ts

        customer_list = []
        for key, c in customers.items():
            customer_list.append({
                'name': c['name'],
                'phone': c['phone'],
                'total_spent': float(c['total_spent']),
                'total_fulfilled': float(c['total_fulfilled']),
                'fulfillment_rate': round(float(c['total_fulfilled'] / c['total_spent'] * 100), 1) if c['total_spent'] > 0 else 0,
                'transaction_count': c['transaction_count'],
                'last_purchase': c['last_purchase'].isoformat() if c['last_purchase'] else None,
                'first_purchase': c['first_purchase'].isoformat() if c['first_purchase'] else None,
                'payment_methods': list(c['payment_methods']),
            })

        return {
            'query': query,
            'found': True,
            'customers_found': len(customer_list),
            'total_transactions': len(transactions),
            'customers': customer_list,
            'recent_transactions': [
                {
                    'tx_id': t.tx_id,
                    'amount': float(t.amount),
                    'status': t.get_status_display(),
                    'timestamp': t.timestamp.isoformat() if t.timestamp else None,
                }
                for t in transactions[:10]
            ],
        }

    # ========================================================================
    @staticmethod
    def filter_transactions(gateway_type: str = None, amount: float = None,
                            amount_min: float = None, amount_max: float = None,
                            start_date: str = None, end_date: str = None,
                            days: int = None, status: str = None) -> Dict:
        filters = Q()

        if gateway_type and gateway_type.upper() != 'ALL':
            gt_map = {
                'TILL': PaymentGateway.GatewayType.MPESA_TILL,
                'PAYBILL': PaymentGateway.GatewayType.MPESA_PAYBILL,
                'PDQ': PaymentGateway.GatewayType.PDQ,
                'MERCH': PaymentGateway.GatewayType.MERCHANDISE,
            }
            mapped = gt_map.get(gateway_type.upper())
            if mapped:
                filters &= Q(gateway__gateway_type=mapped)

        if amount is not None:
            filters &= Q(amount=Decimal(str(amount)))
        else:
            if amount_min is not None:
                filters &= Q(amount__gte=Decimal(str(amount_min)))
            if amount_max is not None:
                filters &= Q(amount__lte=Decimal(str(amount_max)))

        if start_date:
            try:
                sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            except ValueError:
                sd = timezone.localdate()
        elif days is not None:
            sd = timezone.localdate() - timedelta(days=days - 1)
        else:
            sd = None

        if end_date:
            try:
                ed = datetime.strptime(end_date, '%Y-%m-%d').date()
            except ValueError:
                ed = timezone.localdate()
        elif days is not None:
            ed = timezone.localdate()
        else:
            ed = None

        if sd and ed:
            filters &= Q(timestamp__date__gte=sd, timestamp__date__lte=ed)
        elif sd:
            filters &= Q(timestamp__date__gte=sd)
        elif ed:
            filters &= Q(timestamp__date__lte=ed)

        if status and status.upper() != 'ALL':
            filters &= Q(status=status.upper())

        qs = Transaction.objects.exclude(
            _base_exclude()
        ).filter(filters).select_related('gateway').order_by('-timestamp')

        total_count = qs.count()
        total_amount = qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        by_status = {}
        status_qs = qs.values('status').annotate(
            count=Count('id'), amount=Sum('amount')
        ).order_by('-count')
        for row in status_qs:
            by_status[row['status']] = {
                'count': row['count'],
                'amount': float(row['amount'] or 0),
            }

        by_gateway = {}
        gateway_qs = qs.values('gateway__gateway_type').annotate(
            count=Count('id'), amount=Sum('amount')
        ).order_by('-count')
        for row in gateway_qs:
            gt = row['gateway__gateway_type'] or 'UNKNOWN'
            by_gateway[gt] = {
                'count': row['count'],
                'amount': float(row['amount'] or 0),
            }

        samples = []
        for t in qs[:10]:
            samples.append({
                'tx_id': t.tx_id,
                'amount': float(t.amount),
                'status': t.status,
                'sender_name': t.sender_name,
                'gateway_type': t.gateway.gateway_type if t.gateway else None,
                'timestamp': t.timestamp.isoformat() if t.timestamp else None,
            })

        return {
            'total_count': total_count,
            'total_amount': float(total_amount),
            'by_status': by_status,
            'by_gateway': by_gateway,
            'sample_transactions': samples,
            'filters': {
                'gateway_type': gateway_type,
                'amount': amount,
                'amount_min': amount_min,
                'amount_max': amount_max,
                'start_date': start_date,
                'end_date': end_date,
                'days': days,
                'status': status,
            },
        }

    # OPERATIONAL QUERIES
    # ========================================================================

    @staticmethod
    def get_fulfillment_pipeline() -> Dict:
        """Count of transactions at each stage of the fulfillment pipeline."""
        counts = {}
        for status_choice in Transaction.OrderStatus.choices:
            code = status_choice[0]
            count = Transaction.objects.exclude(
                _base_exclude()
            ).filter(status=code).count()
            counts[status_choice[1]] = count

        combined_counts = {}
        for status_choice in CombinedOrder.Status.choices:
            code = status_choice[0]
            count = CombinedOrder.objects.filter(status=code).count()
            combined_counts[status_choice[1]] = count

        return {
            'transaction_pipeline': counts,
            'combined_order_pipeline': combined_counts,
            'total_transactions': Transaction.objects.exclude(_base_exclude()).count(),
            'total_combined_orders': CombinedOrder.objects.count(),
        }

    @staticmethod
    def get_pending_fulfillments(limit: int = 20) -> Dict:
        """
        Transactions that need attention:
        - PROCESSING: activated but not yet started scanning
        - PARTIALLY_FULFILLED: partially scanned
        """
        pending_statuses = [
            Transaction.OrderStatus.PROCESSING,
            Transaction.OrderStatus.PARTIALLY_FULFILLED,
        ]

        transactions = Transaction.objects.exclude(
            _base_exclude() | Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) | Q(combined_order_parent__isnull=False)
        ).filter(
            status__in=pending_statuses
        ).select_related('gateway').order_by('timestamp')[:limit]

        combined = CombinedOrder.objects.filter(
            status__in=[
                CombinedOrder.Status.PENDING,
                CombinedOrder.Status.IN_PROGRESS,
                CombinedOrder.Status.PARTIALLY_FULFILLED,
            ]
        ).order_by('created_at')[:limit]

        return {
            'pending_transactions': [
                {
                    'tx_id': t.tx_id,
                    'amount': float(t.amount),
                    'amount_fulfilled': float(t.amount_fulfilled) if t.amount_fulfilled else 0,
                    'remaining': float(t.amount - (t.amount_fulfilled or 0)),
                    'status': t.status,
                    'status_display': t.get_status_display(),
                    'sender_name': t.sender_name,
                    'sender_phone': t.sender_phone,
                    'gateway': t.gateway.name if t.gateway else None,
                    'timestamp': t.timestamp.isoformat() if t.timestamp else None,
                    'days_old': (timezone.now() - t.timestamp).days if t.timestamp else 0,
                }
                for t in transactions
            ],
            'pending_combined_orders': [
                {
                    'id': c.combined_order_id,
                    'total_amount': float(c.total_amount),
                    'amount_fulfilled': float(c.amount_fulfilled),
                    'remaining': float(c.remaining_amount),
                    'status': c.status,
                    'transaction_count': c.transaction_count,
                    'customer_name': c.customer_name,
                    'created_at': c.created_at.isoformat(),
                    'days_old': (timezone.now() - c.created_at).days,
                }
                for c in combined
            ],
            'total_pending_transactions': transactions.count(),
            'total_pending_combined_orders': combined.count(),
        }

    @staticmethod
    def get_user_performance(username: str = None, report_date=None) -> Dict:
        """Performance stats for a user (or all users) on a date."""
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        from payments.models import User

        if username:
            users = User.objects.filter(username__icontains=username)
        else:
            users = User.objects.all()

        if not users:
            return {
                'query': username,
                'date': report_date.isoformat(),
                'found': False,
                'message': f"No user found matching '{username}'",
            }

        user_stats = []
        for u in users:
            processed = Transaction.objects.exclude(_base_exclude()).filter(
                processed_by=u,
                timestamp__gte=start_dt,
                timestamp__lte=end_dt,
            ).count()

            completed = Transaction.objects.exclude(_base_exclude()).filter(
                completed_by=u,
                completed_at__gte=start_dt,
                completed_at__lte=end_dt,
            ).count()

            activated = Transaction.objects.exclude(_base_exclude()).filter(
                activated_by=u,
                activated_at__gte=start_dt,
                activated_at__lte=end_dt,
            ).count()

            scanned = TransactionLineItem.objects.filter(
                scanned_by_user=u,
                scanned_at__gte=start_dt,
                scanned_at__lte=end_dt,
            ).count()

            combined_created = CombinedOrder.objects.filter(
                combined_by_user=u,
                created_at__gte=start_dt,
                created_at__lte=end_dt,
            ).count()

            user_stats.append({
                'username': u.username,
                'role': u.get_role_display(),
                'transactions_processed': processed,
                'transactions_activated': activated,
                'transactions_completed': completed,
                'items_scanned': scanned,
                'combined_orders_created': combined_created,
                'total_actions': processed + activated + completed + scanned + combined_created,
            })

        user_stats.sort(key=lambda x: x['total_actions'], reverse=True)

        return {
            'date': report_date.isoformat(),
            'query': username,
            'users': user_stats,
            'total_users': len(user_stats),
        }

    @staticmethod
    def get_combined_orders_summary(report_date=None) -> Dict:
        """Combined order stats for a date."""
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        orders = CombinedOrder.objects.filter(
            created_at__gte=start_dt,
            created_at__lte=end_dt,
        ).select_related('combined_by_user', 'fulfilled_by_user')

        total_amount = Decimal('0.00')
        total_fulfilled = Decimal('0.00')
        status_counts = {}

        for order in orders:
            total_amount += order.total_amount
            total_fulfilled += order.amount_fulfilled
            s = order.status
            status_counts[s] = status_counts.get(s, 0) + 1

        return {
            'date': report_date.isoformat(),
            'total_orders_created': orders.count(),
            'total_amount': float(total_amount),
            'total_amount_fulfilled': float(total_fulfilled),
            'status_breakdown': status_counts,
            'orders': [
                {
                    'id': c.combined_order_id,
                    'total_amount': float(c.total_amount),
                    'amount_fulfilled': float(c.amount_fulfilled),
                    'status': c.status,
                    'transaction_count': c.transaction_count,
                    'customer_name': c.customer_name,
                    'created_by': c.combined_by_user.username if c.combined_by_user else None,
                    'created_at': c.created_at.isoformat(),
                }
                for c in orders
            ],
        }

    @staticmethod
    def get_gateway_breakdown(report_date=None) -> Dict:
        """Revenue breakdown by individual gateway (not just buckets)."""
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        txns = Transaction.objects.exclude(
            _base_exclude() | Q(combined_order_parent__isnull=False)
        ).filter(
            timestamp__gte=start_dt, timestamp__lte=end_dt
        ).select_related('gateway')

        gateway_data = {}
        for txn in txns:
            g = txn.gateway
            key = g.gateway_type if g else 'UNKNOWN'
            name = g.name if g else 'Unknown'
            if key not in gateway_data:
                gateway_data[key] = {
                    'gateway_type': key,
                    'gateway_name': name,
                    'count': 0,
                    'revenue': Decimal('0.00'),
                    'sales': Decimal('0.00'),
                    'statuses': {},
                }
            gateway_data[key]['count'] += 1
            gateway_data[key]['revenue'] += txn.amount or Decimal('0.00')
            gateway_data[key]['sales'] += txn.amount_fulfilled or Decimal('0.00')
            s = txn.status
            gateway_data[key]['statuses'][s] = gateway_data[key]['statuses'].get(s, 0) + 1

        return {
            'date': report_date.isoformat(),
            'gateways': [
                {
                    'type': g['gateway_type'],
                    'name': g['gateway_name'],
                    'count': g['count'],
                    'revenue': float(g['revenue']),
                    'sales': float(g['sales']),
                    'status_breakdown': g['statuses'],
                }
                for g in sorted(gateway_data.values(), key=lambda x: x['revenue'], reverse=True)
            ],
        }

    @staticmethod
    def get_registration_kits_summary(start_date=None, end_date=None) -> Dict:
        """Registration kit issuance over a date range."""
        if end_date is None:
            end_date = timezone.localdate()
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        start_dt, end_dt = _get_date_range(end_date)  # end inclusive
        start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))

        txns = Transaction.objects.exclude(
            _base_exclude() | Q(status=Transaction.OrderStatus.COMBINED_FULFILLED)
        ).filter(
            is_registration=True,
            registration_kit_issued=True,
        ).filter(
            completed_at__gte=start_dt,
            completed_at__lte=end_dt,
        ).select_related('completed_by')

        total_kits = sum(t.registration_kit_quantity or 0 for t in txns)
        total_value = total_kits * 200

        daily = {}
        for t in txns:
            day = t.completed_at.date().isoformat() if t.completed_at else 'unknown'
            if day not in daily:
                daily[day] = {'kits': 0, 'count': 0}
            daily[day]['kits'] += t.registration_kit_quantity or 0
            daily[day]['count'] += 1

        return {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'total_kits_issued': total_kits,
            'total_value': float(total_value),
            'total_transactions': txns.count(),
            'daily_breakdown': daily,
        }

    @staticmethod
    def get_pv_summary(report_date=None) -> Dict:
        """Total PV (Point Value) for fulfilled transactions on a date."""
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        line_items = TransactionLineItem.objects.filter(
            scanned_at__gte=start_dt,
            scanned_at__lte=end_dt,
        ).select_related('transaction')

        total_pv = Decimal('0.00')
        bucket_pv = {b: Decimal('0.00') for b in BiCoreService.REVENUE_BUCKETS}
        total_qty = 0

        for li in line_items:
            txn = li.transaction
            if txn.status not in [
                Transaction.OrderStatus.FULFILLED,
                Transaction.OrderStatus.PARTIALLY_FULFILLED,
                Transaction.OrderStatus.COMBINED_FULFILLED,
            ]:
                continue
            total_pv += li.line_pv
            total_qty += li.quantity

            from payments.services.bi_core_service import _classify_gateway
            bucket = _classify_gateway(txn.gateway)
            bucket_pv[bucket] = bucket_pv.get(bucket, Decimal('0.00')) + li.line_pv

        return {
            'date': report_date.isoformat(),
            'total_pv': float(total_pv),
            'total_items': total_qty,
            'per_bucket': {b: float(v) for b, v in bucket_pv.items()},
        }

    @staticmethod
    def get_total_cost(report_date=None) -> Dict:
        """Total cost of goods sold for a date."""
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        line_items = TransactionLineItem.objects.filter(
            scanned_at__gte=start_dt,
            scanned_at__lte=end_dt,
        ).select_related('transaction')

        total_cost = Decimal('0.00')
        total_items = 0

        for li in line_items:
            if li.transaction.status not in [
                Transaction.OrderStatus.FULFILLED,
                Transaction.OrderStatus.PARTIALLY_FULFILLED,
                Transaction.OrderStatus.COMBINED_FULFILLED,
            ]:
                continue
            total_cost += li.line_cost
            total_items += li.quantity

        return {
            'date': report_date.isoformat(),
            'total_cost_of_goods_sold': float(total_cost),
            'total_items_sold': total_items,
        }

    # ========================================================================
    # LISTING & SUMMARY QUERIES
    # ========================================================================

    @staticmethod
    def get_all_products(stock_status: str = None, category: str = None, search: str = None) -> Dict:
        """List all active products with optional filters."""
        qs = Product.objects.filter(is_active=True).select_related('product_line')

        if search:
            qs = qs.filter(
                Q(prod_name__icontains=search) |
                Q(prod_code__icontains=search) |
                Q(sku__icontains=search) |
                Q(barcode__icontains=search)
            )

        if category:
            qs = qs.filter(product_line__name__icontains=category)

        if stock_status:
            if stock_status == 'OUT_OF_STOCK':
                qs = qs.filter(quantity__lte=0)
            elif stock_status == 'LOW_STOCK':
                qs = qs.filter(quantity__gt=0, quantity__lte=models.F('reorder_level'))
            elif stock_status == 'IN_STOCK':
                qs = qs.filter(quantity__gt=models.F('reorder_level'))

        qs = qs.order_by('prod_name')

        results = []
        for p in qs:
            line_name = p.product_line.name if p.product_line else None
            status = 'OUT_OF_STOCK' if p.quantity <= 0 else (
                'LOW_STOCK' if p.quantity <= p.reorder_level else 'IN_STOCK'
            )
            results.append({
                'id': p.id,
                'name': p.prod_name,
                'code': p.prod_code,
                'sku': p.sku or '',
                'barcode': p.barcode or '',
                'category': line_name,
                'quantity': p.quantity,
                'reorder_level': p.reorder_level,
                'stock_status': status,
                'price': float(p.current_price),
                'cost_price': float(p.cost_price),
                'pv': float(p.current_pv),
                'stock_value': float(p.quantity * p.current_price),
            })

        return {
            'total_products': len(results),
            'filters': {
                'stock_status': stock_status,
                'category': category,
                'search': search,
            },
            'products': results,
        }

    @staticmethod
    def get_daily_sales_summary(report_date=None) -> Dict:
        """Product-level daily sales summary from TransactionLineItem."""
        if report_date is None:
            report_date = timezone.localdate()
        start_dt, end_dt = _get_date_range(report_date)

        line_items = TransactionLineItem.objects.filter(
            scanned_at__gte=start_dt,
            scanned_at__lte=end_dt,
        ).select_related('transaction', 'product__product_line')

        total_qty = 0
        total_revenue = Decimal('0.00')
        total_cost = Decimal('0.00')
        total_pv = Decimal('0.00')
        fulfillment_count = 0
        product_agg = {}

        for li in line_items:
            if li.transaction.status not in [
                Transaction.OrderStatus.FULFILLED,
                Transaction.OrderStatus.PARTIALLY_FULFILLED,
                Transaction.OrderStatus.COMBINED_FULFILLED,
            ]:
                continue
            total_qty += li.quantity
            total_revenue += li.line_total
            total_cost += li.line_cost
            total_pv += li.line_pv
            fulfillment_count += 1

            pid = li.product_id
            if pid not in product_agg:
                p = li.product
                product_agg[pid] = {
                    'name': p.prod_name,
                    'code': p.prod_code,
                    'category': p.product_line.name if p.product_line else None,
                    'quantity': 0,
                    'revenue': Decimal('0.00'),
                }
            product_agg[pid]['quantity'] += li.quantity
            product_agg[pid]['revenue'] += li.line_total

        ranked = sorted(product_agg.values(), key=lambda x: x['quantity'], reverse=True)

        return {
            'date': report_date.isoformat(),
            'total_quantity_sold': total_qty,
            'total_revenue': float(total_revenue),
            'total_cost': float(total_cost),
            'total_pv': float(total_pv),
            'unique_products': len(product_agg),
            'fulfillment_count': fulfillment_count,
            'top_products': [
                {
                    'name': p['name'],
                    'code': p['code'],
                    'category': p['category'],
                    'quantity_sold': p['quantity'],
                    'revenue': float(p['revenue']),
                }
                for p in ranked[:10]
            ],
        }

    # ========================================================================
    # PERIOD & COMPARISON QUERIES
    # ========================================================================

    @staticmethod
    def get_period_revenue(start_date: date, end_date: date) -> Dict:
        """Revenue aggregated over a date range, with daily breakdown."""
        start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))

        txns = Transaction.objects.exclude(
            _base_exclude() | Q(combined_order_parent__isnull=False)
        ).filter(
            timestamp__gte=start_dt,
            timestamp__lte=end_dt,
        ).select_related('gateway')

        total = Decimal('0.00')
        bucket_totals = {b: Decimal('0.00') for b in BiCoreService.REVENUE_BUCKETS}
        daily = {}
        txn_count = 0

        for txn in txns:
            from payments.services.bi_core_service import _classify_gateway
            amount = txn.amount or Decimal('0.00')
            total += amount
            txn_count += 1
            bucket = _classify_gateway(txn.gateway)
            bucket_totals[bucket] += amount

            day_key = txn.timestamp.date().isoformat()
            if day_key not in daily:
                daily[day_key] = {'revenue': Decimal('0.00'), 'count': 0}
            daily[day_key]['revenue'] += amount
            daily[day_key]['count'] += 1

        return {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'total_revenue': float(total),
            'total_transactions': txn_count,
            'daily_average': round(float(total / max(len(daily), 1)), 2),
            'buckets': {b: float(v) for b, v in bucket_totals.items()},
            'daily_breakdown': {
                k: {'revenue': float(v['revenue']), 'count': v['count']}
                for k, v in sorted(daily.items())
            },
            'days_in_range': (end_date - start_date).days + 1,
        }

    @staticmethod
    def get_period_sales(start_date: date, end_date: date) -> Dict:
        """Sales (fulfillment) aggregated over a date range, with daily breakdown."""
        start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))

        fulfilled_statuses = [
            Transaction.OrderStatus.FULFILLED,
            Transaction.OrderStatus.PARTIALLY_FULFILLED,
        ]

        txns = Transaction.objects.exclude(
            _base_exclude() | Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) | Q(combined_order_parent__isnull=False)
        ).filter(
            status__in=fulfilled_statuses,
            completed_at__gte=start_dt,
            completed_at__lte=end_dt,
        ).select_related('gateway')

        total = Decimal('0.00')
        bucket_totals = {b: Decimal('0.00') for b in BiCoreService.SALES_BUCKETS}
        daily = {}
        txn_count = 0

        for txn in txns:
            from payments.services.bi_core_service import _classify_gateway
            amount = txn.amount_fulfilled or Decimal('0.00')
            total += amount
            txn_count += 1
            bucket = _classify_gateway(txn.gateway)
            if bucket in bucket_totals:
                bucket_totals[bucket] += amount

            day_key = txn.completed_at.date().isoformat() if txn.completed_at else 'unknown'
            if day_key not in daily:
                daily[day_key] = {'sales': Decimal('0.00'), 'count': 0}
            daily[day_key]['sales'] += amount
            daily[day_key]['count'] += 1

        return {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'total_sales': float(total),
            'total_transactions': txn_count,
            'daily_average': round(float(total / max(len(daily), 1)), 2),
            'buckets': {b: float(v) for b, v in bucket_totals.items() if v > 0},
            'daily_breakdown': {
                k: {'sales': float(v['sales']), 'count': v['count']}
                for k, v in sorted(daily.items())
            },
        }

    @staticmethod
    def get_period_revenue_vs_sales(start_date: date, end_date: date) -> Dict:
        """Revenue vs Sales comparison over a date range."""
        revenue = BiExtendedService.get_period_revenue(start_date, end_date)
        sales = BiExtendedService.get_period_sales(start_date, end_date)

        total_rev = Decimal(str(revenue['total_revenue']))
        total_sales = Decimal(str(sales['total_sales']))
        gap = total_rev - total_sales
        fulfillment_rate = float(total_sales / total_rev * 100) if total_rev > 0 else 0.0

        return {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'total_revenue': float(total_rev),
            'total_sales': float(total_sales),
            'gap': float(gap),
            'fulfillment_rate': fulfillment_rate,
            'transaction_count': revenue['total_transactions'],
        }

    @staticmethod
    def get_month_comparison() -> Dict:
        """Compare current month to previous month."""
        today = timezone.localdate()
        current_start = today.replace(day=1)
        if current_start.month == 1:
            prev_start = current_start.replace(year=current_start.year - 1, month=12)
        else:
            prev_start = current_start.replace(month=current_start.month - 1)
        prev_end = current_start - timedelta(days=1)

        current = BiExtendedService.get_period_revenue_vs_sales(current_start, today)
        previous = BiExtendedService.get_period_revenue_vs_sales(prev_start, prev_end)
        days_in_current = (today - current_start).days + 1
        days_in_prev = (prev_end - prev_start).days + 1

        return {
            'current_period': {
                'start': current_start.isoformat(),
                'end': today.isoformat(),
                'days': days_in_current,
                'revenue': current['total_revenue'],
                'sales': current['total_sales'],
                'fulfillment_rate': current['fulfillment_rate'],
            },
            'previous_period': {
                'start': prev_start.isoformat(),
                'end': prev_end.isoformat(),
                'days': days_in_prev,
                'revenue': previous['total_revenue'],
                'sales': previous['total_sales'],
                'fulfillment_rate': previous['fulfillment_rate'],
            },
            'change': {
                'revenue': round(current['total_revenue'] - previous['total_revenue'], 2),
                'revenue_pct': round(
                    (current['total_revenue'] - previous['total_revenue']) / previous['total_revenue'] * 100, 1
                ) if previous['total_revenue'] > 0 else 0,
                'sales': round(current['total_sales'] - previous['total_sales'], 2),
                'sales_pct': round(
                    (current['total_sales'] - previous['total_sales']) / previous['total_sales'] * 100, 1
                ) if previous['total_sales'] > 0 else 0,
            },
        }

    @staticmethod
    def get_year_comparison() -> Dict:
        """Compare current year to previous year (year-to-date)."""
        today = timezone.localdate()
        current_start = today.replace(month=1, day=1)
        prev_start = current_start.replace(year=current_start.year - 1)
        prev_end = current_start - timedelta(days=1)

        current = BiExtendedService.get_period_revenue_vs_sales(current_start, today)
        previous = BiExtendedService.get_period_revenue_vs_sales(prev_start, prev_end)

        return {
            'current_year': today.year,
            'previous_year': today.year - 1,
            'current_period': {
                'start': current_start.isoformat(),
                'end': today.isoformat(),
                'revenue': current['total_revenue'],
                'sales': current['total_sales'],
                'fulfillment_rate': current['fulfillment_rate'],
            },
            'previous_period': {
                'start': prev_start.isoformat(),
                'end': prev_end.isoformat(),
                'revenue': previous['total_revenue'],
                'sales': previous['total_sales'],
                'fulfillment_rate': previous['fulfillment_rate'],
            },
            'change': {
                'revenue_change': round(current['total_revenue'] - previous['total_revenue'], 2),
                'revenue_pct': round(
                    (current['total_revenue'] - previous['total_revenue']) / previous['total_revenue'] * 100, 1
                ) if previous['total_revenue'] > 0 else 0,
                'sales_change': round(current['total_sales'] - previous['total_sales'], 2),
                'sales_pct': round(
                    (current['total_sales'] - previous['total_sales']) / previous['total_sales'] * 100, 1
                ) if previous['total_sales'] > 0 else 0,
            },
        }

    @staticmethod
    def get_product_comparison(product_query: str, date1: date, date2: date) -> Dict:
        """Compare a product's sales between two dates."""
        sales1 = BiExtendedService.get_product_sales(product_query, date1)
        sales2 = BiExtendedService.get_product_sales(product_query, date2)

        if not sales1.get('found') or not sales2.get('found'):
            return {
                'query': product_query,
                'found': False,
                'message': f"Product not found for one or both dates",
            }

        qty_change = sales2['total_quantity_sold'] - sales1['total_quantity_sold']
        rev_change = sales2['total_revenue'] - sales1['total_revenue']

        return {
            'product': sales1['products'],
            'date1': {
                'date': date1.isoformat(),
                'quantity': sales1['total_quantity_sold'],
                'revenue': sales1['total_revenue'],
            },
            'date2': {
                'date': date2.isoformat(),
                'quantity': sales2['total_quantity_sold'],
                'revenue': sales2['total_revenue'],
            },
            'change': {
                'quantity_change': qty_change,
                'revenue_change': round(rev_change, 2),
                'quantity_pct': round((qty_change / max(sales1['total_quantity_sold'], 1)) * 100, 1),
                'revenue_pct': round((rev_change / max(sales1['total_revenue'], 0.01)) * 100, 1),
            },
        }
