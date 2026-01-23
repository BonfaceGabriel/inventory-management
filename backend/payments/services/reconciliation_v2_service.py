"""
Daily Reconciliation Service V2

Implements the new reconciliation formula:

X = Mpesa_Paybill - Unused + PDQ + Previous - Sales
Y = Till - Previous - Credit - KITS

X + Y should = 0

Definitions:
- Mpesa_Paybill: Total amount received to parent paybill gateway for TODAY (report date)
- Unused: Unfulfilled paybill transactions (Excel pre-go-live + TODAY's unfulfilled)
- PDQ: Total manual PDQ transactions for TODAY
- Previous: Paybill payments from ANY previous date that were FULFILLED TODAY
- Till: Till transactions FULFILLED TODAY (payment can be from any date)
- Credit: Remaining balances on partially fulfilled paybill transactions from TODAY
- KITS: Registration kits issued TODAY * 200 KES
- Sales: Total amount fulfilled from ALL gateways TODAY

Excel File (unused.xlsx) - Go-Live Support:
- Before go-live: Update Excel with all unfulfilled TX IDs from month start to go-live day
- Launch month ONLY: Excel transactions checked for current status
  * Still UNFULFILLED → Include in Unused
  * FULFILLED/CANCELLED → Exclude from Unused
- Next month onwards: Excel NOT used (monthly reset)

Important Rules:
- Reconciliation is done on a MONTHLY basis
- Unused resets monthly (transactions from previous months expire)
- Unused transactions from previous months CANNOT be fulfilled
- When an Unused transaction is fulfilled, it appears in "Previous" for that day
- Till doesn't care when payment was made, only when it was fulfilled
- Exclude COMBINED_FULFILLED child transactions (only count parent transactions)
"""

from decimal import Decimal
from datetime import date, datetime, timedelta
from calendar import monthrange
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from typing import Dict, List, Optional, Tuple
import logging
import os

from payments.models import Transaction, PaymentGateway, CombinedOrder

logger = logging.getLogger(__name__)

# Constants
REGISTRATION_KIT_VALUE = Decimal('200.00')  # KES 200 per registration for reconciliation
SYSTEM_LAUNCH_DATE = date(2026, 1, 22)  # First day of production use (go-live date)


class ReconciliationV2Service:
    """
    Service for generating daily reconciliation reports using the X/Y formula.

    X = Mpesa_Paybill - Unused + PDQ + Previous - Sales
    Y = Till - Previous - Credit - KITS

    X + Y should = 0 for balanced books
    """

    @staticmethod
    def get_parent_paybill_gateway() -> Optional[PaymentGateway]:
        """Get the parent company paybill gateway."""
        try:
            return PaymentGateway.objects.get(
                gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL,
                is_parent_company=True,
                is_active=True
            )
        except PaymentGateway.DoesNotExist:
            # Fallback: try to find any active paybill gateway
            return PaymentGateway.objects.filter(
                gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL,
                is_active=True
            ).first()
        except PaymentGateway.MultipleObjectsReturned:
            return PaymentGateway.objects.filter(
                gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL,
                is_parent_company=True,
                is_active=True
            ).first()

    @staticmethod
    def get_till_gateways() -> List[PaymentGateway]:
        """Get all Till product gateways (excluding Merchandise)."""
        return list(PaymentGateway.objects.filter(
            gateway_type=PaymentGateway.GatewayType.MPESA_TILL,
            name__icontains='Products',  # Only include Till Products
            is_active=True
        ))

    @staticmethod
    def get_pdq_gateway() -> Optional[PaymentGateway]:
        """Get the PDQ/manual payment gateway."""
        return PaymentGateway.objects.filter(
            gateway_type=PaymentGateway.GatewayType.PDQ,
            is_active=True
        ).first()

    @staticmethod
    def get_date_range(report_date: date) -> Tuple[datetime, datetime]:
        """Get start and end datetime for a given date."""
        start_datetime = timezone.make_aware(datetime.combine(report_date, datetime.min.time()))
        end_datetime = timezone.make_aware(datetime.combine(report_date, datetime.max.time()))
        return start_datetime, end_datetime

    @staticmethod
    def get_month_start(report_date: date) -> date:
        """Get the first day of the month for the given date."""
        return date(report_date.year, report_date.month, 1)

    @staticmethod
    def _base_transaction_queryset():
        """
        Base queryset that excludes:
        1. COMBINED_FULFILLED transactions (we only count parents)
        2. Internal transactions from BF SUMA EAGLE SHOP LTD (7974481)
        """
        return Transaction.objects.exclude(
            Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
            Q(sender_name__icontains='7974481') |
            Q(sender_phone__icontains='7974481')
        )

    @staticmethod
    def calculate_mpesa_paybill(report_date: date, paybill_gateway: PaymentGateway) -> Dict:
        """
        Calculate total amount received to parent paybill gateway for TODAY.

        This is the total of all transactions that came in on the report date
        to the paybill gateway (regardless of fulfillment status).
        """
        if not paybill_gateway:
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': []}

        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)

        transactions = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway=paybill_gateway,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt,
            combined_order_parent__isnull=True  # Exclude combined order parents (internal adjustments)
        )

        total = transactions.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        return {
            'amount': total,
            'count': transactions.count(),
            'transactions': list(transactions.values('tx_id', 'amount', 'status', 'sender_name'))
        }

    @staticmethod
    def calculate_unused_unfulfilled(report_date: date, paybill_gateway: PaymentGateway) -> Dict:
        """
        Calculate money on paybill that has not been processed/fulfilled FOR THE CURRENT DAY ONLY.
        
        Logic:
        - Sum of amount for transactions on report_date with status in [NOT_PROCESSED, PROCESSING]
        - IGNORES 'unused.xlsx' or any historic carry-over as per requirements.
        """
        if not paybill_gateway:
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': []}

        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)

        unfulfilled_statuses = [
            Transaction.OrderStatus.NOT_PROCESSED,
            Transaction.OrderStatus.PROCESSING
        ]
        
        # Filter for today's unfulfilled transactions on paybill
        transactions = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway=paybill_gateway,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt,
            status__in=unfulfilled_statuses
        )

        total = transactions.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        return {
            'amount': total,
            'count': transactions.count(),
            'transactions': list(transactions.values('tx_id', 'amount', 'status', 'sender_name', 'timestamp'))
        }

    @staticmethod
    def get_raw_gateway_totals(report_date: date) -> Dict[str, float]:
        """
        Calculate raw total receipts per gateway for the day.
        Ignores combined order logic. Strictly sums transaction amounts by gateway.
        
        Returns:
            Dict with keys: 'paybill', 'till', 'pdq' and their float amounts.
        """
        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)
        
        totals = {
            'paybill': 0.0,
            'till': 0.0,
            'pdq': 0.0
        }
        
        # Paybill
        paybill_amount = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway__gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        totals['paybill'] = float(paybill_amount)
        
        # Till
        till_amount = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway__gateway_type=PaymentGateway.GatewayType.MPESA_TILL,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        totals['till'] = float(till_amount)
        
        # PDQ
        pdq_amount = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway__gateway_type=PaymentGateway.GatewayType.PDQ,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        totals['pdq'] = float(pdq_amount)
        
        return totals

    @staticmethod
    def calculate_pdq_total(report_date: date) -> Dict:
        """
        Calculate total PDQ transactions for today.
        PDQ transactions are manual card payments.
        """
        pdq_gateway = ReconciliationV2Service.get_pdq_gateway()
        if not pdq_gateway:
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': []}

        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)

        transactions = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway=pdq_gateway,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt
        )

        total = transactions.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        return {
            'amount': total,
            'count': transactions.count(),
            'transactions': list(transactions.values('tx_id', 'amount', 'status', 'sender_name'))
        }

    @staticmethod
    def calculate_previous(report_date: date, paybill_gateway: PaymentGateway) -> Dict:
        """
        Calculate amounts paid on PREVIOUS days to paybill but FULFILLED TODAY.

        Includes:
        1. Standalone paybill transactions from previous days fulfilled today.
        2. Paybill/PDQ child transactions in Combined Orders that received fulfillment today
           (using priority-based allocation: Paybill/PDQ consumed first, then Till).
        """
        if not paybill_gateway:
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': [], 'combined_allocations': []}

        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)
        pdq_gateway = ReconciliationV2Service.get_pdq_gateway()

        # --- Part 1: Standalone transactions (existing logic) ---
        fulfilled_statuses = [
            Transaction.OrderStatus.FULFILLED,
            Transaction.OrderStatus.PARTIALLY_FULFILLED
        ]

        standalone_txns = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway=paybill_gateway,
            timestamp__lt=start_dt,  # Payment was before today
            status__in=fulfilled_statuses,
            completed_at__gte=start_dt,  # Completed today
            completed_at__lte=end_dt
        )

        standalone_total = standalone_txns.aggregate(total=Sum('amount_fulfilled'))['total'] or Decimal('0.00')

        # --- Part 2: Combined Order allocations ---
        combined_allocations = []
        combined_total = Decimal('0.00')

        # Find Combined Orders with fulfillment activity today
        combined_orders = CombinedOrder.objects.filter(
            Q(status__in=[CombinedOrder.Status.IN_PROGRESS, CombinedOrder.Status.PARTIALLY_FULFILLED, CombinedOrder.Status.FULFILLED]),
            Q(fulfilled_at__gte=start_dt, fulfilled_at__lte=end_dt) |  # Fulfilled today
            Q(updated_at__gte=start_dt, updated_at__lte=end_dt)  # Or updated today
        ).prefetch_related('transactions__transaction__gateway')

        for order in combined_orders:
            # Calculate today's increment
            today_fulfillment = order.amount_fulfilled - order.base_amount_fulfilled
            if today_fulfillment <= 0:
                continue

            # Sum child amounts by gateway type (priority pools)
            paybill_pdq_pool = Decimal('0.00')
            till_pool = Decimal('0.00')
            paybill_pdq_ids = set()
            if pdq_gateway:
                paybill_pdq_ids.add(pdq_gateway.id)
            paybill_pdq_ids.add(paybill_gateway.id)

            for cot in order.transactions.all():
                child_txn = cot.transaction
                if child_txn.gateway_id in paybill_pdq_ids:
                    paybill_pdq_pool += child_txn.amount
                else:
                    till_pool += child_txn.amount

            # Priority allocation: Paybill/PDQ first
            paybill_pdq_consumed = min(today_fulfillment, paybill_pdq_pool)
            
            if paybill_pdq_consumed > 0:
                combined_total += paybill_pdq_consumed
                combined_allocations.append({
                    'combined_order_id': order.combined_order_id,
                    'today_fulfillment': float(today_fulfillment),
                    'paybill_pdq_pool': float(paybill_pdq_pool),
                    'allocated_to_previous': float(paybill_pdq_consumed)
                })

        total = standalone_total + combined_total

        return {
            'amount': total,
            'count': standalone_txns.count() + len(combined_allocations),
            'transactions': list(standalone_txns.values(
                'tx_id', 'amount', 'amount_fulfilled', 'status', 'sender_name', 'timestamp'
            )),
            'combined_allocations': combined_allocations
        }

    @staticmethod
    def calculate_till_sales(report_date: date) -> Dict:
        """
        Calculate amounts fulfilled for payments made on Till gateway.

        Includes:
        1. Standalone Till transactions fulfilled today.
        2. Till portion of Combined Order fulfillment today (priority-based: Till consumed last).
        """
        till_gateways = ReconciliationV2Service.get_till_gateways()
        if not till_gateways:
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': [], 'gateways': [], 'combined_allocations': []}

        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)
        gateway_ids = [g.id for g in till_gateways]
        paybill_gateway = ReconciliationV2Service.get_parent_paybill_gateway()
        pdq_gateway = ReconciliationV2Service.get_pdq_gateway()

        # --- Part 1: Standalone Till transactions ---
        fulfilled_statuses = [
            Transaction.OrderStatus.FULFILLED,
            Transaction.OrderStatus.PARTIALLY_FULFILLED
        ]

        standalone_txns = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway_id__in=gateway_ids,
            status__in=fulfilled_statuses
        ).filter(
            Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
            Q(timestamp__gte=start_dt, timestamp__lte=end_dt)
        )

        standalone_total = standalone_txns.aggregate(total=Sum('amount_fulfilled'))['total'] or Decimal('0.00')

        # --- Part 2: Combined Order allocations (Till gets remainder) ---
        combined_allocations = []
        combined_total = Decimal('0.00')

        paybill_pdq_ids = set()
        if paybill_gateway:
            paybill_pdq_ids.add(paybill_gateway.id)
        if pdq_gateway:
            paybill_pdq_ids.add(pdq_gateway.id)

        combined_orders = CombinedOrder.objects.filter(
            Q(status__in=[CombinedOrder.Status.IN_PROGRESS, CombinedOrder.Status.PARTIALLY_FULFILLED, CombinedOrder.Status.FULFILLED]),
            Q(fulfilled_at__gte=start_dt, fulfilled_at__lte=end_dt) |
            Q(updated_at__gte=start_dt, updated_at__lte=end_dt)
        ).prefetch_related('transactions__transaction__gateway')

        for order in combined_orders:
            today_fulfillment = order.amount_fulfilled - order.base_amount_fulfilled
            if today_fulfillment <= 0:
                continue

            paybill_pdq_pool = Decimal('0.00')
            till_pool = Decimal('0.00')

            for cot in order.transactions.all():
                child_txn = cot.transaction
                if child_txn.gateway_id in paybill_pdq_ids:
                    paybill_pdq_pool += child_txn.amount
                elif child_txn.gateway_id in gateway_ids:
                    till_pool += child_txn.amount

            # Priority: Paybill/PDQ first, Till gets remainder
            paybill_pdq_consumed = min(today_fulfillment, paybill_pdq_pool)
            till_consumed = max(Decimal('0.00'), min(today_fulfillment - paybill_pdq_consumed, till_pool))

            if till_consumed > 0:
                combined_total += till_consumed
                combined_allocations.append({
                    'combined_order_id': order.combined_order_id,
                    'today_fulfillment': float(today_fulfillment),
                    'till_pool': float(till_pool),
                    'allocated_to_till': float(till_consumed)
                })

        total = standalone_total + combined_total

        return {
            'amount': total,
            'count': standalone_txns.count() + len(combined_allocations),
            'transactions': list(standalone_txns.values(
                'tx_id', 'amount', 'amount_fulfilled', 'status', 'sender_name'
            )),
            'gateways': [g.name for g in till_gateways],
            'combined_allocations': combined_allocations
        }

    @staticmethod
    def calculate_credit(report_date: date, paybill_gateway: PaymentGateway) -> Dict:
        """
        Calculate all partially fulfilled BALANCES on paybill parent company
        for transactions received TODAY.

        This is the REMAINING amount (not fulfilled) on partially fulfilled transactions
        on the paybill gateway that arrived on the report date.
        """
        if not paybill_gateway:
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': []}

        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)

        # Partially fulfilled transactions on paybill received TODAY
        transactions = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway=paybill_gateway,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt,
            status=Transaction.OrderStatus.PARTIALLY_FULFILLED
        )

        # Calculate remaining balances (amount - amount_fulfilled)
        total = Decimal('0.00')
        tx_list = []
        for txn in transactions:
            remaining = txn.amount - txn.amount_fulfilled
            total += remaining
            tx_list.append({
                'tx_id': txn.tx_id,
                'amount': txn.amount,
                'amount_fulfilled': txn.amount_fulfilled,
                'remaining': remaining,
                'sender_name': txn.sender_name
            })

        return {
            'amount': total,
            'count': transactions.count(),
            'transactions': tx_list
        }

    @staticmethod
    def calculate_kits(report_date: date) -> Dict:
        """
        Calculate KITS value: Sum of registration_kit_quantity * 200.
        
        Uses the registration_kit_quantity field directly from transactions
        where is_registration=True and registration_kit_issued=True.
        """
        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)

        # Count registration transactions issued/completed today
        registration_txns = ReconciliationV2Service._base_transaction_queryset().filter(
            is_registration=True,
            registration_kit_issued=True
        ).filter(
            Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
            Q(timestamp__gte=start_dt, timestamp__lte=end_dt)
        )

        # Sum registration_kit_quantity directly from the transaction field
        kit_quantity_sum = registration_txns.aggregate(
            total_kits=Sum('registration_kit_quantity')
        )['total_kits'] or 0

        total = REGISTRATION_KIT_VALUE * kit_quantity_sum

        return {
            'amount': total,
            'count': kit_quantity_sum,
            'unit_value': REGISTRATION_KIT_VALUE,
            'transactions': list(registration_txns.values('tx_id', 'amount', 'sender_name', 'registration_kit_quantity'))
        }

    @staticmethod
    def calculate_total_sales(report_date: date) -> Dict:
        """
        Calculate total fulfilled amount from ALL gateways for today.

        This is the sum of amount_fulfilled for all transactions that had
        fulfillment activity today.
        """
        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)

        # All fulfilled transactions completed today
        fulfilled_statuses = [
            Transaction.OrderStatus.FULFILLED,
            Transaction.OrderStatus.PARTIALLY_FULFILLED
        ]

        # Get transactions completed today or received today with fulfillment
        transactions = ReconciliationV2Service._base_transaction_queryset().filter(
            status__in=fulfilled_statuses
        ).filter(
            Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
            Q(timestamp__gte=start_dt, timestamp__lte=end_dt, amount_fulfilled__gt=0)
        )

        total = transactions.aggregate(total=Sum('amount_fulfilled'))['total'] or Decimal('0.00')

        # Group by gateway for breakdown
        gateway_breakdown = {}
        for txn in transactions.select_related('gateway'):
            gateway_name = txn.gateway.name if txn.gateway else 'No Gateway'
            if gateway_name not in gateway_breakdown:
                gateway_breakdown[gateway_name] = {'amount': Decimal('0.00'), 'count': 0}
            gateway_breakdown[gateway_name]['amount'] += txn.amount_fulfilled
            gateway_breakdown[gateway_name]['count'] += 1

        return {
            'amount': total,
            'count': transactions.count(),
            'by_gateway': gateway_breakdown
        }



    @staticmethod
    def generate_daily_report(report_date: date = None) -> Dict:
        """
        Generate daily reconciliation report using the X/Y formula.

        X = Mpesa_Paybill - Unused + PDQ + Previous - Sales
        Y = Till - Credit - KITS

        Returns comprehensive breakdown with X, Y, and X+Y result.
        """
        if report_date is None:
            report_date = timezone.localtime(timezone.now()).date()

        logger.info(f"Generating V2 reconciliation report for {report_date}")

        # Get gateways
        paybill_gateway = ReconciliationV2Service.get_parent_paybill_gateway()

        # Calculate all components
        mpesa_paybill = ReconciliationV2Service.calculate_mpesa_paybill(report_date, paybill_gateway)
        unused = ReconciliationV2Service.calculate_unused_unfulfilled(report_date, paybill_gateway)
        pdq = ReconciliationV2Service.calculate_pdq_total(report_date)
        previous = ReconciliationV2Service.calculate_previous(report_date, paybill_gateway)
        till = ReconciliationV2Service.calculate_till_sales(report_date)
        credit = ReconciliationV2Service.calculate_credit(report_date, paybill_gateway)
        kits = ReconciliationV2Service.calculate_kits(report_date)
        sales = ReconciliationV2Service.calculate_total_sales(report_date)

        calculations = {
            'mpesa_paybill': mpesa_paybill,
            'unused': unused,
            'pdq': pdq,
            'previous': previous,
            'till': till,
            'credit': credit,
            'kits': kits,
            'sales': sales
        }

        # Calculate X
        # X = Mpesa_Paybill - Unused + PDQ + Previous - Sales
        x_value = (
            calculations['mpesa_paybill']['amount']
            - calculations['unused']['amount']
            + calculations['pdq']['amount']
            + calculations['previous']['amount']
            - calculations['sales']['amount']
        )

        # Calculate Y
        # Y = Till - Credit - KITS (Previous removed - it's Paybill-source)
        y_value = (
            calculations['till']['amount']
            - calculations['credit']['amount']
            - calculations['kits']['amount']
        )

        # Calculate result
        result = x_value + y_value
        is_balanced = result == Decimal('0.00')

        return {
            'report_date': report_date.isoformat(),
            'generated_at': timezone.now().isoformat(),

            # Main formula results
            'x_value': float(x_value),
            'y_value': float(y_value),
            'result': float(result),
            'is_balanced': is_balanced,
            'raw_breakdown': ReconciliationV2Service.get_raw_gateway_totals(report_date),

            # Formula breakdown
            'x_formula': {
                'description': 'X = Mpesa_Paybill - Unused + PDQ + Previous - Sales',
                'mpesa_paybill': float(calculations['mpesa_paybill']['amount']),
                'unused': float(calculations['unused']['amount']),
                'pdq': float(calculations['pdq']['amount']),
                'previous': float(calculations['previous']['amount']),
                'sales': float(calculations['sales']['amount'])
            },
            'y_formula': {
                'description': 'Y = Till - Credit - KITS',
                'till': float(calculations['till']['amount']),
                'credit': float(calculations['credit']['amount']),
                'kits': float(calculations['kits']['amount'])
            },

            # Detailed breakdowns
            'details': {
                'mpesa_paybill': {
                    'amount': float(calculations['mpesa_paybill']['amount']),
                    'count': calculations['mpesa_paybill']['count'],
                    'description': 'Total received to parent paybill today'
                },
                'unused': {
                    'amount': float(calculations['unused']['amount']),
                    'count': calculations['unused']['count'],
                    'description': 'Unprocessed/unfulfilled on paybill (current month)',
                    'month_boundary': calculations['unused'].get('month_boundary'),
                    'december_carryover': calculations['unused'].get('december_carryover')
                },
                'pdq': {
                    'amount': float(calculations['pdq']['amount']),
                    'count': calculations['pdq']['count'],
                    'description': 'Manual PDQ transactions today'
                },
                'previous': {
                    'amount': float(calculations['previous']['amount']),
                    'count': calculations['previous']['count'],
                    'description': 'Previous days paybill payments fulfilled today'
                },
                'till': {
                    'amount': float(calculations['till']['amount']),
                    'count': calculations['till']['count'],
                    'description': 'Till gateway fulfillment today',
                    'gateways': calculations['till'].get('gateways', [])
                },
                'credit': {
                    'amount': float(calculations['credit']['amount']),
                    'count': calculations['credit']['count'],
                    'description': 'Partially fulfilled balances on paybill'
                },
                'kits': {
                    'amount': float(calculations['kits']['amount']),
                    'count': calculations['kits']['count'],
                    'unit_value': float(calculations['kits']['unit_value']),
                    'description': f'Registration count ({calculations["kits"]["count"]}) x {REGISTRATION_KIT_VALUE}'
                },
                'sales': {
                    'amount': float(calculations['sales']['amount']),
                    'count': calculations['sales']['count'],
                    'description': 'Total fulfilled from all gateways',
                    'by_gateway': {
                        k: {'amount': float(v['amount']), 'count': v['count']}
                        for k, v in calculations['sales'].get('by_gateway', {}).items()
                    }
                }
            },

            # Metadata
            'paybill_gateway': paybill_gateway.name if paybill_gateway else None,
            'cmb_exception': calculations.get('cmb_exception'),
            'is_launch_date': report_date == SYSTEM_LAUNCH_DATE
        }
