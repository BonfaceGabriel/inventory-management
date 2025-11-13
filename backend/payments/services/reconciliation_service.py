"""
Daily Reconciliation Service

Generates daily reconciliation reports by payment gateway, showing:
- Total transactions per gateway
- Settlement calculations
- Payment method breakdown
- Missing/unprocessed transactions

This helps with end-of-day balancing and financial reporting.
"""

from decimal import Decimal
from datetime import date, datetime, timedelta
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from typing import Dict, List, Optional
import logging

from payments.models import Transaction, PaymentGateway, ManualPayment

logger = logging.getLogger(__name__)


class ReconciliationService:
    """
    Service for generating daily reconciliation reports.

    Provides methods to:
    - Generate gateway-wise reconciliation
    - Calculate settlement amounts
    - Identify discrepancies
    - Generate summary reports
    """

    @staticmethod
    def generate_daily_report(report_date: date = None) -> Dict:
        """
        Generate comprehensive daily reconciliation report.

        Args:
            report_date: Date to generate report for (defaults to today)

        Returns:
            Dictionary containing:
            - Date range
            - Gateway-wise breakdown
            - Overall totals
            - Settlement calculations
            - Transaction counts
        """
        if report_date is None:
            report_date = timezone.now().date()

        # Get start and end of day
        start_datetime = timezone.make_aware(datetime.combine(report_date, datetime.min.time()))
        end_datetime = timezone.make_aware(datetime.combine(report_date, datetime.max.time()))

        logger.info(f"Generating reconciliation report for {report_date}")

        # Get all transactions for the day
        transactions = Transaction.objects.filter(
            timestamp__gte=start_datetime,
            timestamp__lte=end_datetime
        ).select_related('gateway')

        # Generate gateway-wise breakdown
        gateway_reports = ReconciliationService._generate_gateway_breakdown(
            transactions, start_datetime, end_datetime
        )

        # Calculate overall totals from ALL transactions (not just gateway-grouped ones)
        overall_totals = ReconciliationService._calculate_overall_totals_from_transactions(transactions)

        # Get status breakdown
        status_breakdown = ReconciliationService._get_status_breakdown(transactions)

        # Get manual payments breakdown
        manual_payments_summary = ReconciliationService._get_manual_payments_summary(
            start_datetime, end_datetime
        )

        return {
            'report_date': report_date.isoformat(),
            'generated_at': timezone.now().isoformat(),
            'date_range': {
                'start': start_datetime.isoformat(),
                'end': end_datetime.isoformat()
            },
            'gateway_reports': gateway_reports,
            'overall_totals': overall_totals,
            'status_breakdown': status_breakdown,
            'manual_payments': manual_payments_summary,
            'summary': {
                'total_transactions': transactions.count(),
                'total_amount': float(overall_totals['total_amount']),
                'total_to_parent': float(overall_totals['total_parent_settlement']),
                'total_to_shop': float(overall_totals['total_shop_amount']),
                'gateways_count': len(gateway_reports)
            }
        }

    @staticmethod
    def _generate_gateway_breakdown(transactions, start_datetime, end_datetime) -> List[Dict]:
        """
        Generate breakdown by payment gateway.

        Args:
            transactions: QuerySet of transactions
            start_datetime: Start of date range
            end_datetime: End of date range

        Returns:
            List of gateway report dictionaries
        """
        gateway_reports = []

        # Get all active gateways
        gateways = PaymentGateway.objects.filter(is_active=True)

        for gateway in gateways:
            # Get transactions for this gateway
            gateway_txns = transactions.filter(gateway=gateway)

            if gateway_txns.count() == 0:
                # Skip gateways with no transactions
                continue

            # Calculate totals
            total_amount = gateway_txns.aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0.00')

            # Calculate settlement for this gateway
            settlement = gateway.calculate_settlement(total_amount)

            # Get status breakdown for this gateway
            gateway_status_breakdown = ReconciliationService._get_status_breakdown(gateway_txns)

            # Get transaction count by confidence level
            high_confidence_count = gateway_txns.filter(confidence__gte=0.9).count()
            medium_confidence_count = gateway_txns.filter(
                confidence__gte=0.7, confidence__lt=0.9
            ).count()
            low_confidence_count = gateway_txns.filter(confidence__lt=0.7).count()

            gateway_report = {
                'gateway_id': gateway.id,
                'gateway_name': gateway.name,
                'gateway_type': gateway.gateway_type,
                'gateway_number': gateway.gateway_number,
                'settlement_type': gateway.settlement_type,
                'transaction_count': gateway_txns.count(),
                'total_amount': float(total_amount),
                'settlement': {
                    'parent_amount': float(settlement['parent_amount']),
                    'shop_amount': float(settlement['shop_amount']),
                    'settlement_type': settlement['settlement_type'],
                    'calculation_note': settlement['calculation_note']
                },
                'status_breakdown': gateway_status_breakdown,
                'confidence_breakdown': {
                    'high_confidence': high_confidence_count,
                    'medium_confidence': medium_confidence_count,
                    'low_confidence': low_confidence_count
                },
                'transactions': [
                    {
                        'tx_id': tx.tx_id,
                        'amount': float(tx.amount),
                        'sender_name': tx.sender_name,
                        'timestamp': tx.timestamp.isoformat(),
                        'status': tx.status,
                        'confidence': tx.confidence
                    }
                    for tx in gateway_txns.order_by('-timestamp')
                ]
            }

            gateway_reports.append(gateway_report)

        # Sort by total amount descending
        gateway_reports.sort(key=lambda x: x['total_amount'], reverse=True)

        return gateway_reports

    @staticmethod
    def _calculate_overall_totals(gateway_reports: List[Dict]) -> Dict:
        """
        Calculate overall totals across all gateways.

        Args:
            gateway_reports: List of gateway report dictionaries

        Returns:
            Dictionary with overall totals
        """
        total_amount = Decimal('0.00')
        total_parent_settlement = Decimal('0.00')
        total_shop_amount = Decimal('0.00')
        total_transactions = 0

        for report in gateway_reports:
            total_amount += Decimal(str(report['total_amount']))
            total_parent_settlement += Decimal(str(report['settlement']['parent_amount']))
            total_shop_amount += Decimal(str(report['settlement']['shop_amount']))
            total_transactions += report['transaction_count']

        return {
            'total_amount': total_amount,
            'total_parent_settlement': total_parent_settlement,
            'total_shop_amount': total_shop_amount,
            'total_transactions': total_transactions
        }

    @staticmethod
    def _calculate_overall_totals_from_transactions(transactions) -> Dict:
        """
        Calculate overall totals directly from ALL transactions (including those without gateways).

        Args:
            transactions: QuerySet of Transaction objects

        Returns:
            Dictionary with overall totals
        """
        from django.db.models import Sum, Count

        # Calculate total amount from all transactions
        totals = transactions.aggregate(
            total_amount=Sum('amount'),
            total_transactions=Count('id')
        )

        total_amount = totals['total_amount'] or Decimal('0.00')
        total_transactions = totals['total_transactions'] or 0

        # Calculate settlement amounts for each transaction with a gateway
        total_parent_settlement = Decimal('0.00')
        total_shop_amount = Decimal('0.00')

        for txn in transactions.select_related('gateway'):
            if txn.gateway:
                settlement = txn.gateway.calculate_settlement(Decimal(str(txn.amount)))
                total_parent_settlement += settlement['parent_amount']
                total_shop_amount += settlement['shop_amount']
            else:
                # For transactions without gateway, assume all goes to parent
                total_parent_settlement += Decimal(str(txn.amount))

        return {
            'total_amount': total_amount,
            'total_parent_settlement': total_parent_settlement,
            'total_shop_amount': total_shop_amount,
            'total_transactions': total_transactions
        }

    @staticmethod
    def _get_status_breakdown(transactions) -> Dict:
        """
        Get breakdown of transactions by status.

        Args:
            transactions: QuerySet of transactions

        Returns:
            Dictionary with status counts and amounts
        """
        breakdown = {}

        for status_choice in Transaction.OrderStatus.choices:
            status_code = status_choice[0]
            status_label = status_choice[1]

            status_txns = transactions.filter(status=status_code)
            count = status_txns.count()
            total = status_txns.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

            breakdown[status_code] = {
                'label': status_label,
                'count': count,
                'total_amount': float(total)
            }

        return breakdown

    @staticmethod
    def _get_manual_payments_summary(start_datetime, end_datetime) -> Dict:
        """
        Get summary of manual payments for the day.

        Args:
            start_datetime: Start of date range
            end_datetime: End of date range

        Returns:
            Dictionary with manual payment summary
        """
        manual_payments = ManualPayment.objects.filter(
            payment_date__gte=start_datetime,
            payment_date__lte=end_datetime
        )

        total_count = manual_payments.count()
        total_amount = manual_payments.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        # Breakdown by payment method
        by_method = {}
        for method_choice in ManualPayment.PaymentMethod.choices:
            method_code = method_choice[0]
            method_label = method_choice[1]

            method_payments = manual_payments.filter(payment_method=method_code)
            method_count = method_payments.count()
            method_total = method_payments.aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0.00')

            if method_count > 0:
                by_method[method_code] = {
                    'label': method_label,
                    'count': method_count,
                    'total_amount': float(method_total)
                }

        return {
            'total_count': total_count,
            'total_amount': float(total_amount),
            'by_method': by_method
        }

    @staticmethod
    def generate_date_range_report(start_date: date, end_date: date) -> Dict:
        """
        Generate reconciliation report for a date range.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            Dictionary with aggregated report
        """
        logger.info(f"Generating reconciliation report from {start_date} to {end_date}")

        daily_reports = []
        current_date = start_date

        while current_date <= end_date:
            daily_report = ReconciliationService.generate_daily_report(current_date)
            daily_reports.append(daily_report)
            current_date += timedelta(days=1)

        # Calculate totals across all days
        grand_total_amount = Decimal('0.00')
        grand_total_parent = Decimal('0.00')
        grand_total_shop = Decimal('0.00')
        grand_total_transactions = 0

        for report in daily_reports:
            grand_total_amount += Decimal(str(report['overall_totals']['total_amount']))
            grand_total_parent += Decimal(str(report['overall_totals']['total_parent_settlement']))
            grand_total_shop += Decimal(str(report['overall_totals']['total_shop_amount']))
            grand_total_transactions += report['overall_totals']['total_transactions']

        return {
            'date_range': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
                'days': (end_date - start_date).days + 1
            },
            'generated_at': timezone.now().isoformat(),
            'daily_reports': daily_reports,
            'grand_totals': {
                'total_amount': float(grand_total_amount),
                'total_parent_settlement': float(grand_total_parent),
                'total_shop_amount': float(grand_total_shop),
                'total_transactions': grand_total_transactions
            }
        }

    @staticmethod
    def identify_discrepancies(report_date: date = None) -> Dict:
        """
        Identify potential discrepancies in transactions.

        Checks for:
        - Low confidence transactions
        - Unprocessed transactions
        - Transactions with missing gateway info

        Args:
            report_date: Date to check (defaults to today)

        Returns:
            Dictionary with discrepancy information
        """
        if report_date is None:
            report_date = timezone.now().date()

        start_datetime = timezone.make_aware(datetime.combine(report_date, datetime.min.time()))
        end_datetime = timezone.make_aware(datetime.combine(report_date, datetime.max.time()))

        transactions = Transaction.objects.filter(
            timestamp__gte=start_datetime,
            timestamp__lte=end_datetime
        )

        # Low confidence transactions (< 70%)
        low_confidence_txns = transactions.filter(confidence__lt=0.7)

        # Unprocessed transactions
        unprocessed_txns = transactions.filter(status=Transaction.OrderStatus.NOT_PROCESSED)

        # Transactions without gateway
        no_gateway_txns = transactions.filter(gateway__isnull=True)

        # Partially fulfilled but not updated recently (potential stuck orders)
        stuck_threshold = timezone.now() - timedelta(hours=24)
        potentially_stuck = transactions.filter(
            status=Transaction.OrderStatus.PARTIALLY_FULFILLED,
            updated_at__lt=stuck_threshold
        )

        return {
            'report_date': report_date.isoformat(),
            'discrepancies': {
                'low_confidence': {
                    'count': low_confidence_txns.count(),
                    'transactions': [
                        {'tx_id': tx.tx_id, 'confidence': tx.confidence}
                        for tx in low_confidence_txns
                    ]
                },
                'unprocessed': {
                    'count': unprocessed_txns.count(),
                    'transactions': [
                        {'tx_id': tx.tx_id, 'amount': float(tx.amount)}
                        for tx in unprocessed_txns
                    ]
                },
                'no_gateway': {
                    'count': no_gateway_txns.count(),
                    'transactions': [
                        {'tx_id': tx.tx_id, 'amount': float(tx.amount)}
                        for tx in no_gateway_txns
                    ]
                },
                'potentially_stuck': {
                    'count': potentially_stuck.count(),
                    'transactions': [
                        {
                            'tx_id': tx.tx_id,
                            'amount': float(tx.amount),
                            'last_updated': tx.updated_at.isoformat()
                        }
                        for tx in potentially_stuck
                    ]
                }
            },
            'requires_attention': (
                low_confidence_txns.count() +
                unprocessed_txns.count() +
                no_gateway_txns.count() +
                potentially_stuck.count()
            ) > 0
        }
