"""
Daily Reconciliation Service V2

Implements the new reconciliation formula:

X = Mpesa_Paybill - Unused + PDQ + Previous - Sales
Y = Till - Previous - Credit - KITS

X + Y should = 0

Definitions:
- Mpesa_Paybill: Total amount received to parent paybill gateway for the report date
- Unused/Unfulfilled: All unprocessed/unfulfilled money on paybill (monthly boundary)
- PDQ: Total manual PDQ transactions for today
- Previous: Amounts paid on previous days to paybill but fulfilled today
- Till: Amounts fulfilled for payments made on Till gateway + Previous
- Credit: Partially fulfilled balances on paybill parent company
- KITS: Registration transaction count for today * 200
- Sales: Total fulfilled amount from all gateways

Important Rules:
- Exclude COMBINED_FULFILLED child transactions (only count parent transactions)
- Unfulfilled amounts reset monthly (from 1st of current month)
- Today (2026-01-16) has special handling for December Excel import
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
SYSTEM_LAUNCH_DATE = date(2026, 1, 18)  # First day of production use (go-live date)


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
        Base queryset that excludes COMBINED_FULFILLED transactions.
        We only want to count parent transactions, not the children that were combined.
        """
        return Transaction.objects.exclude(
            status=Transaction.OrderStatus.COMBINED_FULFILLED
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
        Calculate all unprocessed/unfulfilled money on paybill.

        Includes:
        1. Transactions from 'unused.xlsx' (historical/January context) that are still unfulfilled.
        2. Transactions from TODAY that are unfulfilled.
        
        The Daily Reconciliation formula (X+Y=0) requires 'Unused' to represent
        money available but not used.
        """
        if not paybill_gateway:
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': []}

        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)
        
        unfulfilled_statuses = [
            Transaction.OrderStatus.NOT_PROCESSED,
            Transaction.OrderStatus.PROCESSING
        ]

        # 1. Get transactions from unused.xlsx (Historical context)
        # ONLY apply this for January 2026 (Launch Month).
        # In February, we don't carry forward this static list; the formula relies on
        # daily "Previous" inflows to balance out fulfilling old transactions.
        excel_ids = []
        if report_date.year == 2026 and report_date.month == 1:
            # USER INSTRUCTION: Do not check status for these IDs, just add their amounts.
            # This treats the Excel list as a static set of "known unused" transactions
            # regardless of their current system status.
            excel_ids = ReconciliationV2Service._load_unused_excel_ids()
        
        qs_excel = Transaction.objects.none()
        if excel_ids:
            qs_excel = ReconciliationV2Service._base_transaction_queryset().filter(
                tx_id__in=excel_ids
            )

        # 2. Get unfulfilled transactions for TODAY (New incomings)
        # For today's data, we DO check status to find what is currently unfulfilled
        qs_today = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway=paybill_gateway,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt,
            status__in=unfulfilled_statuses
        )

        # Combine and deduplicate
        combined_qs = (qs_excel | qs_today).distinct()

        total = combined_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        result = {
            'amount': total,
            'count': combined_qs.count(),
            'transactions': list(combined_qs.values('tx_id', 'amount', 'status', 'sender_name')),
            'note': f"Includes {len(excel_ids)} IDs from unused.xlsx" if excel_ids else "No Excel IDs loaded"
        }

        return result

    @staticmethod
    def _load_unused_excel_ids() -> List[str]:
        """
        Load Transaction IDs from 'unused.xlsx'.
        """
        # File is at backend/unused.xlsx
        excel_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'unused.xlsx'
        )

        if not os.path.exists(excel_path):
            logger.warning(f"Unused Excel file not found at {excel_path}")
            return []

        try:
            import openpyxl
            wb = openpyxl.load_workbook(excel_path)
            ws = wb.active

            ids = []
            # Iterate rows, skipping header
            # Assuming 'TX ID' is the first column (index 0) based on inspection
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row[0]:
                    ids.append(str(row[0]).strip())
            
            return ids
        except Exception as e:
            logger.error(f"Error loading unused.xlsx: {e}")
            return []

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

        These are transactions where:
        - Gateway is paybill
        - Transaction timestamp is BEFORE today
        - Fulfillment happened today (completed_at is today or amount_fulfilled changed today)
        """
        if not paybill_gateway:
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': []}

        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)
        yesterday_end = start_dt - timedelta(seconds=1)

        # Transactions from previous days that were fulfilled (completed) today
        fulfilled_statuses = [
            Transaction.OrderStatus.FULFILLED,
            Transaction.OrderStatus.PARTIALLY_FULFILLED
        ]

        transactions = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway=paybill_gateway,
            timestamp__lt=start_dt,  # Payment was before today
            status__in=fulfilled_statuses,
            completed_at__gte=start_dt,  # Completed today
            completed_at__lte=end_dt
        )

        # Sum the amount_fulfilled (not total amount, since they might be partial)
        total = transactions.aggregate(total=Sum('amount_fulfilled'))['total'] or Decimal('0.00')

        return {
            'amount': total,
            'count': transactions.count(),
            'transactions': list(transactions.values(
                'tx_id', 'amount', 'amount_fulfilled', 'status', 'sender_name', 'timestamp'
            ))
        }

    @staticmethod
    def calculate_till_sales(report_date: date) -> Dict:
        """
        Calculate amounts fulfilled for payments made on Till gateway.

        Includes:
        - All transactions on Till gateways that have fulfillment today
        - Both partial and full fulfillment amounts
        """
        till_gateways = ReconciliationV2Service.get_till_gateways()
        if not till_gateways:
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': [], 'gateways': []}

        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)
        gateway_ids = [g.id for g in till_gateways]

        # Transactions on Till gateways with fulfillment activity today
        fulfilled_statuses = [
            Transaction.OrderStatus.FULFILLED,
            Transaction.OrderStatus.PARTIALLY_FULFILLED
        ]

        # Get transactions that were completed today or updated today with fulfillment
        transactions = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway_id__in=gateway_ids,
            status__in=fulfilled_statuses
        ).filter(
            Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |  # Completed today
            Q(timestamp__gte=start_dt, timestamp__lte=end_dt)  # Or received today
        )

        # Sum amount_fulfilled for these transactions
        total = transactions.aggregate(total=Sum('amount_fulfilled'))['total'] or Decimal('0.00')

        return {
            'amount': total,
            'count': transactions.count(),
            'transactions': list(transactions.values(
                'tx_id', 'amount', 'amount_fulfilled', 'status', 'sender_name'
            )),
            'gateways': [g.name for g in till_gateways]
        }

    @staticmethod
    def calculate_credit(report_date: date, paybill_gateway: PaymentGateway) -> Dict:
        """
        Calculate all partially fulfilled BALANCES on paybill parent company.

        This is the REMAINING amount (not fulfilled) on partially fulfilled transactions
        on the paybill gateway.
        """
        if not paybill_gateway:
            return {'amount': Decimal('0.00'), 'count': 0, 'transactions': []}

        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)
        month_start = ReconciliationV2Service.get_month_start(report_date)
        month_start_dt = timezone.make_aware(datetime.combine(month_start, datetime.min.time()))

        # Partially fulfilled transactions on paybill from start of month
        transactions = ReconciliationV2Service._base_transaction_queryset().filter(
            gateway=paybill_gateway,
            timestamp__gte=month_start_dt,
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
        Calculate KITS value: registration transaction count for today * 200.
        """
        start_dt, end_dt = ReconciliationV2Service.get_date_range(report_date)

        # Count registration transactions completed today
        registration_txns = ReconciliationV2Service._base_transaction_queryset().filter(
            is_registration=True,
            registration_kit_issued=True,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt
        )

        count = registration_txns.count()
        total = REGISTRATION_KIT_VALUE * count

        return {
            'amount': total,
            'count': count,
            'unit_value': REGISTRATION_KIT_VALUE,
            'transactions': list(registration_txns.values('tx_id', 'amount', 'sender_name'))
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
        Y = Till - Previous - Credit - KITS

        Returns comprehensive breakdown with X, Y, and X+Y result.
        """
        if report_date is None:
            report_date = timezone.now().date()

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
        # Y = Till - Previous - Credit - KITS
        y_value = (
            calculations['till']['amount']
            - calculations['previous']['amount']
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
                'description': 'Y = Till - Previous - Credit - KITS',
                'till': float(calculations['till']['amount']),
                'previous': float(calculations['previous']['amount']),
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
