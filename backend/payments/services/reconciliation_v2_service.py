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
- Previous: Paybill payments from ANY previous date that became ACTIVE today (combined, partially fulfilled, or fulfilled)
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

from payments.models import Transaction, PaymentGateway, CombinedOrder, CombinedOrderTransaction

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
        Base queryset for FULFILLMENT calculations that excludes:
        1. COMBINED_FULFILLED transactions (their fulfillment is tracked via combined order parent)
        2. Combined order parent transactions (internal accounting entries)
        3. Internal transactions from BF SUMA EAGLE SHOP LTD (7974481)

        For combined orders: fulfillment is tracked via the parent transaction.
        """
        return Transaction.objects.exclude(
            Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
            Q(combined_order_parent__isnull=False) |  # Exclude parent transactions
            Q(sender_name__icontains='7974481') |
            Q(sender_phone__icontains='7974481')
        )

    @staticmethod
    def _receipt_queryset():
        """
        Base queryset for RECEIPT calculations (money actually received).

        Includes:
        - Single (non-combined) transactions
        - Combined order CHILD transactions (they represent real money received)

        Excludes:
        - CANCELLED transactions (no longer count as received)
        - Combined order parent transactions (internal accounting entries)
        - Internal transactions from BF SUMA EAGLE SHOP LTD (7974481)
        """
        return Transaction.objects.exclude(
            Q(status=Transaction.OrderStatus.CANCELLED) |
            Q(combined_order_parent__isnull=False) |  # Exclude parent transactions
            Q(sender_name__icontains='7974481') |
            Q(sender_phone__icontains='7974481')
        )

    @staticmethod
    def calculate_mpesa_paybill(report_date: date, paybill_gateway: PaymentGateway) -> Dict:
        """
        Calculate total amount received to parent paybill gateway for TODAY.

        Includes:
        - Single (non-combined) paybill transactions
        - Combined order paybill children (full amount received)

        Excludes:
        - Combined order parent transactions (internal accounting entries)
        """
        if not paybill_gateway:
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': []}

        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)

        # Use _receipt_queryset which includes COMBINED_FULFILLED but excludes parents
        transactions = ReconciliationV2Service._receipt_queryset().filter(
            gateway=paybill_gateway,
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

        Includes:
        - Single (non-combined) PDQ transactions
        - Combined order PDQ children (full amount received)

        Excludes:
        - Combined order parent transactions
        """
        pdq_gateway = ReconciliationV2Service.get_pdq_gateway()
        if not pdq_gateway:
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': []}

        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)

        # Use _receipt_queryset which includes COMBINED_FULFILLED but excludes parents
        transactions = ReconciliationV2Service._receipt_queryset().filter(
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
        Calculate amounts paid on PREVIOUS days to paybill that became active TODAY.

        "Previous" = The WHOLE AMOUNT of paybill transactions that:
        1. Were PAID on a previous day (timestamp < today)
        2. Became ACTIVE today through any of:
           - Being COMBINED into a combined order today
           - Being PARTIALLY FULFILLED today (standalone)
           - Being FULLY FULFILLED today (standalone)

        IMPORTANT: Uses the ORIGINAL PAYMENT AMOUNT (not amount_fulfilled).
        The entire transaction amount counts as "Previous" once it becomes active.
        """
        if not paybill_gateway:
            logger.debug("calculate_previous: No paybill gateway found")
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': [], 'debug': {}}

        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)

        debug_info = {
            'report_date': str(report_date),
            'start_dt': str(start_dt),
            'end_dt': str(end_dt),
            'paybill_gateway_id': paybill_gateway.id,
            'paybill_gateway_name': paybill_gateway.name,
            'standalone': {},
            'combined': {},
        }

        # Track transaction IDs to avoid double-counting
        counted_tx_ids = set()
        total = Decimal('0.00')
        all_transactions = []

        # --- Part 1: Standalone fulfilled/partially fulfilled transactions ---
        # Paybill transactions from previous days that were fulfilled today (not in combined orders)
        #
        # We check:
        # - Status is PARTIALLY_FULFILLED or FULFILLED
        # - updated_at is today (status changed today)
        #
        # This is more robust than completed_at because:
        # - completed_at is only set when complete_issuance() is called
        # - A user could activate, scan products, then cancel - completed_at wouldn't be set
        # - But if status changed to PARTIALLY_FULFILLED/FULFILLED, real fulfillment happened
        fulfilled_statuses = [
            Transaction.OrderStatus.FULFILLED,
            Transaction.OrderStatus.PARTIALLY_FULFILLED
        ]

        standalone_txns = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway=paybill_gateway,
            timestamp__lt=start_dt,  # Payment was before today
            status__in=fulfilled_statuses,
            updated_at__gte=start_dt,  # Status changed today
            updated_at__lte=end_dt
        )

        standalone_total = Decimal('0.00')
        standalone_list = []

        for txn in standalone_txns:
            if txn.tx_id not in counted_tx_ids:
                counted_tx_ids.add(txn.tx_id)
                standalone_total += txn.amount  # Use WHOLE amount
                standalone_list.append({
                    'tx_id': txn.tx_id,
                    'amount': float(txn.amount),
                    'amount_fulfilled': float(txn.amount_fulfilled),
                    'status': txn.status,
                    'timestamp': str(txn.timestamp),
                    'updated_at': str(txn.updated_at),
                    'source': 'standalone_fulfilled'
                })

        debug_info['standalone'] = {
            'count': len(standalone_list),
            'total': float(standalone_total),
            'transactions': standalone_list
        }

        total += standalone_total
        all_transactions.extend(standalone_list)

        # --- Part 2: Paybill transactions combined into combined orders TODAY ---
        # Find paybill transactions from previous days that were added to combined orders today
        combined_today = CombinedOrderTransaction.objects.filter(
            transaction__gateway=paybill_gateway,
            transaction__timestamp__lt=start_dt,  # Payment was before today
            added_at__gte=start_dt,  # Added to combined order today
            added_at__lte=end_dt
        ).select_related('transaction', 'combined_order')

        combined_total = Decimal('0.00')
        combined_list = []

        for cot in combined_today:
            txn = cot.transaction
            if txn.tx_id not in counted_tx_ids:
                counted_tx_ids.add(txn.tx_id)
                combined_total += txn.amount  # Use WHOLE amount
                combined_list.append({
                    'tx_id': txn.tx_id,
                    'amount': float(txn.amount),
                    'combined_order_id': cot.combined_order.combined_order_id,
                    'timestamp': str(txn.timestamp),
                    'added_at': str(cot.added_at),
                    'source': 'combined_today'
                })

        debug_info['combined'] = {
            'count': len(combined_list),
            'total': float(combined_total),
            'transactions': combined_list
        }

        total += combined_total
        all_transactions.extend(combined_list)

        logger.debug(
            f"calculate_previous: standalone={standalone_total}, combined={combined_total}, "
            f"TOTAL={total} (using original payment amounts)"
        )

        return {
            'amount': total,
            'count': len(all_transactions),
            'transactions': all_transactions,
            'debug': debug_info
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
        Calculate all partially fulfilled BALANCES on paybill and PDQ for transactions received TODAY.

        Includes:
        1. Single paybill transactions that are partially fulfilled
        2. Single PDQ transactions that are partially fulfilled
        3. Combined orders where ALL children are paybill/PDQ (paybill/PDQ-only combined orders)

        The credit is the remaining amount (total - fulfilled) that stays as balance.
        """
        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)
        pdq_gateway = ReconciliationV2Service.get_pdq_gateway()

        total = Decimal('0.00')
        tx_list = []
        combined_order_list = []

        # Build list of gateway IDs to include (paybill + PDQ)
        gateway_ids = []
        if paybill_gateway:
            gateway_ids.append(paybill_gateway.id)
        if pdq_gateway:
            gateway_ids.append(pdq_gateway.id)

        if not gateway_ids:
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': [], 'combined_orders': []}

        # --- Part 1: Single paybill/PDQ transactions partially fulfilled TODAY ---
        # Received today (timestamp) OR fulfilled today (completed_at).
        # NOTE: Do NOT use updated_at — it is auto_now and fires on any .save(),
        # including ghost saves that don't change fulfillment state.
        transactions = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway_id__in=gateway_ids,
            status=Transaction.OrderStatus.PARTIALLY_FULFILLED
        ).filter(
            Q(timestamp__gte=start_dt, timestamp__lte=end_dt) |
            Q(completed_at__gte=start_dt, completed_at__lte=end_dt)
        )

        for txn in transactions:
            remaining = txn.amount - txn.amount_fulfilled
            total += remaining
            tx_list.append({
                'tx_id': txn.tx_id,
                'amount': txn.amount,
                'amount_fulfilled': txn.amount_fulfilled,
                'remaining': remaining,
                'sender_name': txn.sender_name,
                'gateway': txn.gateway.name if txn.gateway else 'Unknown'
            })

        # --- Part 2: Combined orders where ALL children are paybill/PDQ ---
        # These combined orders have credit if partially fulfilled
        combined_orders = CombinedOrder.objects.filter(
            status=CombinedOrder.Status.PARTIALLY_FULFILLED
        ).filter(
            Q(fulfilled_at__gte=start_dt, fulfilled_at__lte=end_dt) |
            Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
            Q(created_at__gte=start_dt, created_at__lte=end_dt)
        ).prefetch_related('transactions__transaction__gateway')

        for order in combined_orders:
            # Check if ALL children are paybill or PDQ
            all_paybill_pdq = True
            for cot in order.transactions.all():
                if cot.transaction.gateway_id not in gateway_ids:
                    all_paybill_pdq = False
                    break

            if all_paybill_pdq:
                remaining = order.total_amount - order.amount_fulfilled
                if remaining > 0:
                    total += remaining
                    combined_order_list.append({
                        'combined_order_id': order.combined_order_id,
                        'total_amount': float(order.total_amount),
                        'amount_fulfilled': float(order.amount_fulfilled),
                        'remaining': float(remaining)
                    })

        return {
            'amount': total,
            'count': len(tx_list) + len(combined_order_list),
            'transactions': tx_list,
            'combined_orders': combined_order_list
        }

    @staticmethod
    def calculate_kits(report_date: date) -> Dict:
        """
        Calculate KITS value: Sum of registration_kit_quantity * 200.

        Includes:
        - Single (non-combined) registration transactions
        - Combined order parent transactions with kits

        Uses the registration_kit_quantity field directly from transactions
        where is_registration=True and registration_kit_issued=True.
        """
        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)

        # Base exclusions (internal transactions only)
        base_exclude = Q(sender_name__icontains='7974481') | Q(sender_phone__icontains='7974481')

        # --- Part 1: Single (non-combined) registration transactions ---
        # NOTE: Do NOT use updated_at — it is auto_now and would re-count kits
        # issued on previous days if the record gets a ghost .save() today.
        single_reg_txns = Transaction.objects.exclude(
            base_exclude |
            Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
            Q(combined_order_parent__isnull=False)
        ).filter(
            is_registration=True,
            registration_kit_issued=True
        ).filter(
            Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
            Q(timestamp__gte=start_dt, timestamp__lte=end_dt)
        )

        single_kits = single_reg_txns.aggregate(
            total_kits=Sum('registration_kit_quantity')
        )['total_kits'] or 0

        # --- Part 2: Combined order parent transactions with kits ---
        combined_reg_txns = Transaction.objects.exclude(base_exclude).filter(
            combined_order_parent__isnull=False,  # Is a combined order parent
            is_registration=True,
            registration_kit_issued=True
        ).filter(
            Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
            Q(timestamp__gte=start_dt, timestamp__lte=end_dt)
        )

        combined_kits = combined_reg_txns.aggregate(
            total_kits=Sum('registration_kit_quantity')
        )['total_kits'] or 0

        kit_quantity_sum = single_kits + combined_kits
        total = REGISTRATION_KIT_VALUE * kit_quantity_sum

        # Combine all registration transactions for breakdown
        all_reg_txns = list(single_reg_txns.values('tx_id', 'amount', 'sender_name', 'registration_kit_quantity'))
        all_reg_txns.extend(list(combined_reg_txns.values('tx_id', 'amount', 'sender_name', 'registration_kit_quantity')))

        return {
            'amount': total,
            'count': kit_quantity_sum,
            'unit_value': REGISTRATION_KIT_VALUE,
            'transactions': all_reg_txns
        }

    @staticmethod
    def calculate_total_sales(report_date: date) -> Dict:
        """
        Calculate total fulfilled amount from ALL gateways for today at DISTRIBUTOR PRICE.

        Includes:
        1. Single (non-combined) transactions fulfilled today
        2. Combined order parent transactions (represent combined fulfillment)

        IMPORTANT: For registration kits, the amount_fulfilled includes 2900 (kit price),
        but the distributor price (what shop owes parent) is 2700. We subtract 200 per kit
        to get the correct sales amount for reconciliation.

        Formula: Sales = sum(amount_fulfilled) - (total_kits_issued * 200)
        """
        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)

        # All fulfilled transactions completed today
        fulfilled_statuses = [
            Transaction.OrderStatus.FULFILLED,
            Transaction.OrderStatus.PARTIALLY_FULFILLED
        ]

        # Base queryset excludes internal transactions
        base_exclude = Q(sender_name__icontains='7974481') | Q(sender_phone__icontains='7974481')

        # --- Part 1: Single (non-combined) transactions ---
        # Exclude COMBINED_FULFILLED (children) and combined order parents
        # NOTE: Do NOT use updated_at — it is auto_now and fires on any .save(),
        # which would re-pull previous-day transactions into today's Sales on ghost saves.
        single_txns = Transaction.objects.exclude(
            base_exclude |
            Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
            Q(combined_order_parent__isnull=False)
        ).filter(
            status__in=fulfilled_statuses
        ).filter(
            # Fulfilled today: completed_at (explicitly set during fulfillment)
            # or received today with fulfillment already done
            Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
            Q(timestamp__gte=start_dt, timestamp__lte=end_dt, amount_fulfilled__gt=0)
        )

        single_fulfilled = single_txns.aggregate(total=Sum('amount_fulfilled'))['total'] or Decimal('0.00')

        single_kits = single_txns.filter(
            is_registration=True,
            registration_kit_issued=True
        ).aggregate(total_kits=Sum('registration_kit_quantity'))['total_kits'] or 0

        # --- Part 2: Combined orders ---
        # We need to count:
        # 1. Fulfillment that happened AFTER combining (amount_fulfilled - base_amount_fulfilled)
        # 2. PLUS any base_amount_fulfilled from children that were fulfilled TODAY (before combining)
        #
        # base_amount_fulfilled includes fulfillment from children before they were combined.
        # We need to check each child's timestamp to determine if that fulfillment happened today.
        combined_orders = CombinedOrder.objects.filter(
            Q(status__in=[CombinedOrder.Status.IN_PROGRESS, CombinedOrder.Status.PARTIALLY_FULFILLED, CombinedOrder.Status.FULFILLED]),
            Q(fulfilled_at__gte=start_dt, fulfilled_at__lte=end_dt) |
            Q(updated_at__gte=start_dt, updated_at__lte=end_dt) |
            Q(created_at__gte=start_dt, created_at__lte=end_dt)
        ).prefetch_related('transactions__transaction')

        combined_fulfilled = Decimal('0.00')
        combined_order_count = 0
        for order in combined_orders:
            # Start with fulfillment that happened AFTER combining
            after_combine_fulfillment = order.amount_fulfilled - order.base_amount_fulfilled

            # Now calculate how much of base_amount_fulfilled was from TODAY
            # by checking each child transaction's timestamp
            base_from_today = Decimal('0.00')
            base_from_previous = Decimal('0.00')

            for cot in order.transactions.all():
                child_txn = cot.transaction
                child_fulfilled = child_txn.amount_fulfilled
                if child_fulfilled > 0:
                    # Check if child was received today
                    if child_txn.timestamp and start_dt <= child_txn.timestamp <= end_dt:
                        base_from_today += child_fulfilled
                    else:
                        base_from_previous += child_fulfilled

            # Today's sales from this combined order =
            # (fulfillment after combining) + (pre-combine fulfillment from children received today)
            today_fulfillment = after_combine_fulfillment + base_from_today

            if today_fulfillment > 0:
                combined_fulfilled += today_fulfillment
                combined_order_count += 1

            logger.debug(
                f"Combined order {order.combined_order_id}: "
                f"after_combine={after_combine_fulfillment}, base_today={base_from_today}, "
                f"base_prev={base_from_previous}, total_today={today_fulfillment}"
            )

        # For kits in combined orders, we need to check parent transactions
        combined_parent_txns = Transaction.objects.exclude(base_exclude).filter(
            combined_order_parent__isnull=False,
            status__in=fulfilled_statuses
        ).filter(
            Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
            Q(timestamp__gte=start_dt, timestamp__lte=end_dt, amount_fulfilled__gt=0)
        )

        combined_kits = combined_parent_txns.filter(
            is_registration=True,
            registration_kit_issued=True
        ).aggregate(total_kits=Sum('registration_kit_quantity'))['total_kits'] or 0

        # Combine totals
        total_fulfilled = single_fulfilled + combined_fulfilled
        total_kits = single_kits + combined_kits

        # Calculate kit adjustment: subtract 200 per kit issued
        kit_adjustment = REGISTRATION_KIT_VALUE * total_kits

        # Sales at distributor price = amount_fulfilled - kit margin
        total = total_fulfilled - kit_adjustment

        # Group by gateway for breakdown (single transactions only for simplicity)
        gateway_breakdown = {}
        for txn in single_txns.select_related('gateway'):
            gateway_name = txn.gateway.name if txn.gateway else 'No Gateway'
            if gateway_name not in gateway_breakdown:
                gateway_breakdown[gateway_name] = {'amount': Decimal('0.00'), 'count': 0}
            txn_amount = txn.amount_fulfilled
            if txn.is_registration and txn.registration_kit_issued and txn.registration_kit_quantity:
                txn_amount -= REGISTRATION_KIT_VALUE * txn.registration_kit_quantity
            gateway_breakdown[gateway_name]['amount'] += txn_amount
            gateway_breakdown[gateway_name]['count'] += 1

        # Add combined orders to breakdown
        if combined_fulfilled > 0:
            gateway_breakdown['Combined Orders'] = {
                'amount': combined_fulfilled - (REGISTRATION_KIT_VALUE * combined_kits),
                'count': combined_order_count
            }

        logger.debug(
            f"calculate_total_sales: single={single_fulfilled}, combined={combined_fulfilled}, "
            f"combined_order_count={combined_order_count}, "
            f"total_fulfilled={total_fulfilled}, kit_adjustment={kit_adjustment} ({total_kits} kits), "
            f"sales_at_distributor_price={total}"
        )

        return {
            'amount': total,
            'count': single_txns.count() + combined_order_count,
            'total_fulfilled': float(total_fulfilled),
            'kit_adjustment': float(kit_adjustment),
            'kits_issued': total_kits,
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
                    'description': 'Total fulfilled at distributor price (kit margin excluded)',
                    'total_fulfilled': calculations['sales'].get('total_fulfilled'),
                    'kit_adjustment': calculations['sales'].get('kit_adjustment'),
                    'kits_issued': calculations['sales'].get('kits_issued'),
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
