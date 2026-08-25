from decimal import Decimal
from typing import Dict, Iterable

from django.db import transaction as db_transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Sum, Q

from payments.models import (
    PaymentGateway,
    Transaction,
    MerchandiseOrder,
    MerchandiseOrderLine,
    MerchandiseCatalogItem,
    MerchandiseStock,
    MerchandiseStockMovement,
)


class MerchandiseService:
    GATEWAY_ALIASES = {'till merchandise', 'merchandise'}
    PRIMARY_GATEWAY_NAME = 'Till Merchandise'

    @staticmethod
    def is_merchandise_gateway(gateway: PaymentGateway) -> bool:
        if not gateway:
            return False
        if gateway.gateway_type == PaymentGateway.GatewayType.MERCHANDISE:
            return True
        return gateway.name.strip().lower() in MerchandiseService.GATEWAY_ALIASES

    @staticmethod
    def create_pending_order_for_transaction(transaction: Transaction, device=None, force: bool = False) -> MerchandiseOrder | None:
        if not transaction or not transaction.gateway:
            return None
        if not force and not MerchandiseService.is_merchandise_gateway(transaction.gateway):
            return None

        order, _ = MerchandiseOrder.objects.get_or_create(
            transaction=transaction,
            defaults={
                'gateway': transaction.gateway,
                'device': device,
                'status': MerchandiseOrder.Status.PENDING,
            }
        )
        return order

    @staticmethod
    def get_pending_orders():
        return MerchandiseOrder.objects.filter(
            status=MerchandiseOrder.Status.PENDING
        ).select_related('transaction', 'gateway', 'device').order_by('created_at')

    @staticmethod
    def _normalize_optional(value):
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @staticmethod
    def _validate_line_item(item: MerchandiseCatalogItem, color: str | None, size: str | None):
        allowed_colors = set(
            item.options.filter(option_type='COLOR').values_list('value', flat=True)
        )
        allowed_sizes = set(
            item.options.filter(option_type='SIZE').values_list('value', flat=True)
        )

        if item.item_type == MerchandiseCatalogItem.ItemType.SET:
            if not color:
                raise ValidationError({'color': 'Colour is required for Set'})
            if not size:
                raise ValidationError({'size': 'Size is required for Set'})
            if color not in allowed_colors:
                raise ValidationError({'color': f'Invalid colour "{color}" for Set'})
            if size not in allowed_sizes:
                raise ValidationError({'size': f'Invalid size "{size}" for Set'})
        else:
            if color:
                raise ValidationError({'color': f'Colour is not allowed for {item.name}'})
            if size:
                raise ValidationError({'size': f'Size is not allowed for {item.name}'})

    @staticmethod
    def _variant_tuples_for_item(item: MerchandiseCatalogItem):
        colors = list(item.options.filter(option_type='COLOR').values_list('value', flat=True))
        sizes = list(item.options.filter(option_type='SIZE').values_list('value', flat=True))

        if item.item_type == MerchandiseCatalogItem.ItemType.SET:
            return [(color, size) for color in colors for size in sizes]
        return [(None, None)]

    @staticmethod
    def _get_or_create_stock(item: MerchandiseCatalogItem, color: str | None, size: str | None) -> MerchandiseStock:
        stock, _ = MerchandiseStock.objects.get_or_create(
            item=item,
            color=color,
            size=size,
            defaults={'quantity': 0}
        )
        return stock

    @staticmethod
    def get_stock_rows():
        rows = []
        items = MerchandiseCatalogItem.objects.filter(is_active=True).prefetch_related('options').order_by('name')

        for item in items:
            for color, size in MerchandiseService._variant_tuples_for_item(item):
                stock = MerchandiseService._get_or_create_stock(item, color, size)
                rows.append({
                    'stock_id': stock.id,
                    'item_code': item.code,
                    'item_name': item.name,
                    'item_type': item.item_type,
                    'color': color or '',
                    'size': size or '',
                    'quantity': stock.quantity,
                    'unit_price': item.unit_price,
                    'updated_at': stock.updated_at,
                })

        return rows

    @staticmethod
    @db_transaction.atomic
    def adjust_stock(adjustments: Iterable[Dict], user, notes: str = ''):
        adjustments = list(adjustments or [])
        if not adjustments:
            raise ValidationError({'adjustments': 'At least one stock adjustment is required'})

        updated_ids = set()
        for adjustment in adjustments:
            item_code = str(adjustment.get('item_code', '')).strip()
            quantity_change = adjustment.get('quantity_change')
            color = MerchandiseService._normalize_optional(adjustment.get('color'))
            size = MerchandiseService._normalize_optional(adjustment.get('size'))

            if not item_code:
                raise ValidationError({'item_code': 'item_code is required'})
            if not isinstance(quantity_change, int) or quantity_change == 0:
                raise ValidationError({'quantity_change': 'quantity_change must be a non-zero integer'})

            try:
                item = MerchandiseCatalogItem.objects.prefetch_related('options').get(
                    code=item_code,
                    is_active=True
                )
            except MerchandiseCatalogItem.DoesNotExist:
                raise ValidationError({'item_code': f'Unknown or inactive item code "{item_code}"'})

            MerchandiseService._validate_line_item(item, color, size)

            stock = MerchandiseService._get_or_create_stock(item, color, size)
            before = stock.quantity
            after = before + quantity_change
            if after < 0:
                raise ValidationError({
                    'quantity_change': f'Insufficient stock for {item.code} ({color or "n/a"} / {size or "n/a"})'
                })

            stock.quantity = after
            stock.save(update_fields=['quantity', 'updated_at'])
            updated_ids.add(stock.id)

            MerchandiseStockMovement.objects.create(
                stock=stock,
                movement_type=(
                    MerchandiseStockMovement.MovementType.MANUAL_ADD
                    if quantity_change > 0
                    else MerchandiseStockMovement.MovementType.MANUAL_DEDUCT
                ),
                quantity_change=quantity_change,
                quantity_before=before,
                quantity_after=after,
                reference='MANUAL_ADJUSTMENT',
                notes=notes,
                performed_by=user,
            )

        return list(updated_ids)

    @staticmethod
    def _variant_stock_query(item_id: int, color: str | None, size: str | None) -> Q:
        query = Q(item_id=item_id)
        query &= Q(color__isnull=True) if color is None else Q(color=color)
        query &= Q(size__isnull=True) if size is None else Q(size=size)
        return query

    @staticmethod
    @db_transaction.atomic
    def fulfill_order(order: MerchandiseOrder, lines_payload: Iterable[Dict], user) -> MerchandiseOrder:
        if order.status != MerchandiseOrder.Status.PENDING:
            raise ValidationError({'status': 'Only pending orders can be fulfilled'})

        lines_payload = list(lines_payload or [])
        if not lines_payload:
            raise ValidationError({'lines': 'At least one line is required'})

        total = Decimal('0.00')
        parsed_lines = []

        for entry in lines_payload:
            item_code = str(entry.get('item_code', '')).strip()
            quantity = entry.get('quantity')
            color = MerchandiseService._normalize_optional(entry.get('color'))
            size = MerchandiseService._normalize_optional(entry.get('size'))

            if not item_code:
                raise ValidationError({'item_code': 'item_code is required'})
            if not isinstance(quantity, int) or quantity <= 0:
                raise ValidationError({'quantity': 'quantity must be a positive integer'})

            try:
                item = MerchandiseCatalogItem.objects.prefetch_related('options').get(
                    code=item_code,
                    is_active=True
                )
            except MerchandiseCatalogItem.DoesNotExist:
                raise ValidationError({'item_code': f'Unknown or inactive item code "{item_code}"'})

            MerchandiseService._validate_line_item(item, color, size)
            parsed_lines.append({
                'item': item,
                'quantity': quantity,
                'color': color,
                'size': size,
            })

        # Lock stock rows before validating quantities so concurrent
        # fulfillments cannot oversell the same variant.
        from functools import reduce
        variant_keys = {(p['item'].id, p['color'], p['size']) for p in parsed_lines}
        stock_query = reduce(
            lambda acc, key: acc | MerchandiseService._variant_stock_query(*key),
            variant_keys,
            MerchandiseService._variant_stock_query(*next(iter(variant_keys))),
        )
        locked_stocks = MerchandiseStock.objects.select_for_update().filter(stock_query)
        stock_map = {(s.item_id, s.color, s.size): s for s in locked_stocks}

        # Aggregate demand per variant so duplicate lines are checked together,
        # and report every shortage in a single error instead of one at a time.
        demand: Dict[tuple, int] = {}
        for p in parsed_lines:
            key = (p['item'].id, p['color'], p['size'])
            demand[key] = demand.get(key, 0) + p['quantity']

        items_by_key = {(p['item'].id, p['color'], p['size']): p['item'] for p in parsed_lines}
        shortages = []
        shortage_details = []
        for key, requested in demand.items():
            available = stock_map[key].quantity if key in stock_map else 0
            if available < requested:
                item = items_by_key[key]
                label = f'{item.name} ({key[1] or "n/a"} / {key[2] or "n/a"})'
                shortages.append(
                    f'Insufficient stock for {label}. Available: {available}, requested: {requested}'
                )
                shortage_details.append({
                    'item_code': item.code,
                    'color': key[1],
                    'size': key[2],
                    'available': available,
                    'requested': requested,
                })
        if shortages:
            error = ValidationError({'stock': shortages})
            error.stock_details = shortage_details
            raise error

        order.lines.all().delete()
        validated_lines = []
        for entry in parsed_lines:
            item = entry['item']
            quantity = entry['quantity']
            key = (item.id, entry['color'], entry['size'])
            validated_lines.append({**entry, 'stock': stock_map[key]})

        for entry in validated_lines:
            item = entry['item']
            quantity = entry['quantity']
            color = entry['color']
            size = entry['size']
            stock = entry['stock']

            line_total = item.unit_price * quantity
            MerchandiseOrderLine.objects.create(
                order=order,
                item=item,
                quantity=quantity,
                unit_price_snapshot=item.unit_price,
                color=color,
                size=size,
                line_total=line_total,
            )
            total += line_total

            before = stock.quantity
            after = before - quantity
            stock.quantity = after
            stock.save(update_fields=['quantity', 'updated_at'])
            MerchandiseStockMovement.objects.create(
                stock=stock,
                movement_type=MerchandiseStockMovement.MovementType.FULFILLMENT,
                quantity_change=-quantity,
                quantity_before=before,
                quantity_after=after,
                reference=order.transaction.tx_id,
                notes='Auto-deducted on merchandise fulfillment',
                performed_by=user,
            )

        order.status = MerchandiseOrder.Status.FULFILLED
        order.fulfilled_by = user
        order.fulfilled_at = timezone.now()
        order.save(update_fields=['status', 'fulfilled_by', 'fulfilled_at', 'updated_at'])

        transaction = order.transaction
        # Respect transaction state machine:
        # NOT_PROCESSED -> PROCESSING -> FULFILLED
        if transaction.status == Transaction.OrderStatus.NOT_PROCESSED:
            transaction.status = Transaction.OrderStatus.PROCESSING
            transaction.save(update_fields=['status', 'updated_at'])
            transaction.refresh_from_db()

        transaction.amount_fulfilled = total
        transaction.status = Transaction.OrderStatus.FULFILLED
        update_fields = ['amount_fulfilled', 'status', 'completed_at', 'updated_at']
        if hasattr(transaction, 'completed_by_id'):
            transaction.completed_by = user
            update_fields.append('completed_by')
        transaction.completed_at = timezone.now()
        transaction.save(update_fields=update_fields)

        return order

    @staticmethod
    def get_daily_report_rows(target_date):
        rows = MerchandiseOrderLine.objects.filter(
            order__status=MerchandiseOrder.Status.FULFILLED,
            order__fulfilled_at__date=target_date
        ).values(
            'item__name',
            'size',
            'color'
        ).annotate(
            quantity=Sum('quantity'),
            total_amount=Sum('line_total')
        ).order_by('item__name', 'size', 'color')

        return [
            {
                'product': row['item__name'],
                'quantity': row['quantity'] or 0,
                'size': row['size'] or '',
                'colour': row['color'] or '',
                'total_amount': row['total_amount'] or Decimal('0.00'),
            }
            for row in rows
        ]
