"""
Transaction Export Service

Generates CSV and XLSX exports for transaction data.
Supports filtering by date range, gateway, status, and other criteria.
"""

import csv
from datetime import date, datetime
from io import BytesIO, StringIO
from typing import Optional, Dict, Any
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from django.utils import timezone
from django.db.models import QuerySet
import logging

from payments.models import Transaction

logger = logging.getLogger(__name__)


class TransactionExportService:
    """
    Service for exporting transaction data to CSV and XLSX formats.

    Provides methods to:
    - Generate CSV exports
    - Generate XLSX exports with formatting
    - Filter transactions by date range
    - Include gateway and settlement information
    """

    # Column headers for export
    HEADERS = [
        'Transaction ID',
        'Timestamp',
        'Amount (KES)',
        'Amount Fulfilled (KES)',
        'Amount Remaining (KES)',
        'Sender Name',
        'Sender Phone',
        'Gateway Name',
        'Gateway Type',
        'Gateway Number',
        'Status',
        'Confidence',
        'Settlement - Parent (KES)',
        'Settlement - Shop (KES)',
        'Destination Number',
        'Notes',
        'Created At',
        'Updated At',
    ]

    @staticmethod
    def export_to_csv(transactions: QuerySet, filename: str = None) -> StringIO:
        """
        Export transactions to CSV format.

        Args:
            transactions: QuerySet of Transaction objects
            filename: Optional filename (for logging purposes)

        Returns:
            StringIO object containing CSV data
        """
        logger.info(f"Generating CSV export with {transactions.count()} transactions")

        # Create CSV buffer
        output = StringIO()
        writer = csv.writer(output)

        # Write headers
        writer.writerow(TransactionExportService.HEADERS)

        # Write data rows
        for txn in transactions.select_related('gateway'):
            # Calculate settlement
            settlement = TransactionExportService._calculate_settlement(txn)

            writer.writerow([
                txn.tx_id or '',
                txn.timestamp.strftime('%Y-%m-%d %H:%M:%S') if txn.timestamp else '',
                float(txn.amount),
                float(txn.amount_paid),
                float(txn.remaining_amount),
                txn.sender_name or '',
                txn.sender_phone or '',
                txn.gateway.name if txn.gateway else '',
                txn.gateway_type or '',
                txn.gateway.gateway_number if txn.gateway else '',
                txn.get_status_display(),
                txn.confidence,
                float(settlement['parent_amount']),
                float(settlement['shop_amount']),
                txn.destination_number or '',
                txn.notes or '',
                txn.created_at.strftime('%Y-%m-%d %H:%M:%S') if txn.created_at else '',
                txn.updated_at.strftime('%Y-%m-%d %H:%M:%S') if txn.updated_at else '',
            ])

        output.seek(0)
        logger.info(f"CSV export completed successfully")
        return output

    @staticmethod
    def export_to_xlsx(transactions: QuerySet, filename: str = None) -> BytesIO:
        """
        Export transactions to XLSX format with professional formatting.

        Args:
            transactions: QuerySet of Transaction objects
            filename: Optional filename (for logging purposes)

        Returns:
            BytesIO object containing XLSX data
        """
        logger.info(f"Generating XLSX export with {transactions.count()} transactions")

        # Create workbook and worksheet
        wb = Workbook()
        ws = wb.active
        ws.title = "Transactions"

        # Define styles
        header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        header_fill = PatternFill(start_color='4A5568', end_color='4A5568', fill_type='solid')
        header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        cell_alignment = Alignment(horizontal='left', vertical='center')
        number_alignment = Alignment(horizontal='right', vertical='center')
        center_alignment = Alignment(horizontal='center', vertical='center')

        border = Border(
            left=Side(style='thin', color='CBD5E0'),
            right=Side(style='thin', color='CBD5E0'),
            top=Side(style='thin', color='CBD5E0'),
            bottom=Side(style='thin', color='CBD5E0')
        )

        # Write headers
        for col_num, header in enumerate(TransactionExportService.HEADERS, 1):
            cell = ws.cell(row=1, column=col_num, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = border

        # Set column widths
        column_widths = {
            'A': 15,  # Transaction ID
            'B': 20,  # Timestamp
            'C': 15,  # Amount
            'D': 18,  # Amount Fulfilled
            'E': 18,  # Amount Remaining
            'F': 25,  # Sender Name
            'G': 15,  # Sender Phone
            'H': 20,  # Gateway Name
            'I': 20,  # Gateway Type
            'J': 15,  # Gateway Number
            'K': 18,  # Status
            'L': 12,  # Confidence
            'M': 18,  # Settlement Parent
            'N': 18,  # Settlement Shop
            'O': 18,  # Destination Number
            'P': 30,  # Notes
            'Q': 20,  # Created At
            'R': 20,  # Updated At
        }

        for col, width in column_widths.items():
            ws.column_dimensions[col].width = width

        # Write data rows
        row_num = 2
        for txn in transactions.select_related('gateway'):
            # Calculate settlement
            settlement = TransactionExportService._calculate_settlement(txn)

            # Transaction ID
            cell = ws.cell(row=row_num, column=1, value=txn.tx_id or '')
            cell.alignment = cell_alignment
            cell.border = border

            # Timestamp
            cell = ws.cell(row=row_num, column=2, value=txn.timestamp.strftime('%Y-%m-%d %H:%M:%S') if txn.timestamp else '')
            cell.alignment = center_alignment
            cell.border = border

            # Amount
            cell = ws.cell(row=row_num, column=3, value=float(txn.amount))
            cell.alignment = number_alignment
            cell.number_format = '#,##0.00'
            cell.border = border

            # Amount Fulfilled
            cell = ws.cell(row=row_num, column=4, value=float(txn.amount_paid))
            cell.alignment = number_alignment
            cell.number_format = '#,##0.00'
            cell.border = border

            # Amount Remaining
            cell = ws.cell(row=row_num, column=5, value=float(txn.remaining_amount))
            cell.alignment = number_alignment
            cell.number_format = '#,##0.00'
            cell.border = border

            # Sender Name
            cell = ws.cell(row=row_num, column=6, value=txn.sender_name or '')
            cell.alignment = cell_alignment
            cell.border = border

            # Sender Phone
            cell = ws.cell(row=row_num, column=7, value=txn.sender_phone or '')
            cell.alignment = cell_alignment
            cell.border = border

            # Gateway Name
            cell = ws.cell(row=row_num, column=8, value=txn.gateway.name if txn.gateway else '')
            cell.alignment = cell_alignment
            cell.border = border

            # Gateway Type
            cell = ws.cell(row=row_num, column=9, value=txn.gateway_type or '')
            cell.alignment = cell_alignment
            cell.border = border

            # Gateway Number
            cell = ws.cell(row=row_num, column=10, value=txn.gateway.gateway_number if txn.gateway else '')
            cell.alignment = cell_alignment
            cell.border = border

            # Status
            status_display = txn.get_status_display()
            cell = ws.cell(row=row_num, column=11, value=status_display)
            cell.alignment = center_alignment
            cell.border = border

            # Apply status-based coloring
            if txn.status == Transaction.OrderStatus.FULFILLED:
                cell.fill = PatternFill(start_color='D4EDDA', end_color='D4EDDA', fill_type='solid')
            elif txn.status == Transaction.OrderStatus.CANCELLED:
                cell.fill = PatternFill(start_color='F8D7DA', end_color='F8D7DA', fill_type='solid')
            elif txn.status == Transaction.OrderStatus.PROCESSING:
                cell.fill = PatternFill(start_color='FFF3CD', end_color='FFF3CD', fill_type='solid')

            # Confidence
            cell = ws.cell(row=row_num, column=12, value=txn.confidence)
            cell.alignment = center_alignment
            cell.number_format = '0.00'
            cell.border = border

            # Settlement - Parent
            cell = ws.cell(row=row_num, column=13, value=float(settlement['parent_amount']))
            cell.alignment = number_alignment
            cell.number_format = '#,##0.00'
            cell.border = border

            # Settlement - Shop
            cell = ws.cell(row=row_num, column=14, value=float(settlement['shop_amount']))
            cell.alignment = number_alignment
            cell.number_format = '#,##0.00'
            cell.border = border

            # Destination Number
            cell = ws.cell(row=row_num, column=15, value=txn.destination_number or '')
            cell.alignment = cell_alignment
            cell.border = border

            # Notes
            cell = ws.cell(row=row_num, column=16, value=txn.notes or '')
            cell.alignment = cell_alignment
            cell.border = border

            # Created At
            cell = ws.cell(row=row_num, column=17, value=txn.created_at.strftime('%Y-%m-%d %H:%M:%S') if txn.created_at else '')
            cell.alignment = center_alignment
            cell.border = border

            # Updated At
            cell = ws.cell(row=row_num, column=18, value=txn.updated_at.strftime('%Y-%m-%d %H:%M:%S') if txn.updated_at else '')
            cell.alignment = center_alignment
            cell.border = border

            row_num += 1

        # Freeze header row
        ws.freeze_panes = 'A2'

        # Add summary at the bottom
        row_num += 1
        total_amount = sum(float(txn.amount) for txn in transactions)
        total_fulfilled = sum(float(txn.amount_paid) for txn in transactions)
        total_remaining = sum(float(txn.remaining_amount) for txn in transactions)
        total_parent = sum(float(TransactionExportService._calculate_settlement(txn)['parent_amount']) for txn in transactions)
        total_shop = sum(float(TransactionExportService._calculate_settlement(txn)['shop_amount']) for txn in transactions)

        summary_font = Font(name='Calibri', size=11, bold=True)
        summary_fill = PatternFill(start_color='E2E8F0', end_color='E2E8F0', fill_type='solid')

        # Summary row
        cell = ws.cell(row=row_num, column=2, value='TOTAL')
        cell.font = summary_font
        cell.fill = summary_fill
        cell.alignment = center_alignment
        cell.border = border

        # Total Amount
        cell = ws.cell(row=row_num, column=3, value=total_amount)
        cell.font = summary_font
        cell.fill = summary_fill
        cell.alignment = number_alignment
        cell.number_format = '#,##0.00'
        cell.border = border

        # Total Amount Fulfilled
        cell = ws.cell(row=row_num, column=4, value=total_fulfilled)
        cell.font = summary_font
        cell.fill = summary_fill
        cell.alignment = number_alignment
        cell.number_format = '#,##0.00'
        cell.border = border

        # Total Amount Remaining
        cell = ws.cell(row=row_num, column=5, value=total_remaining)
        cell.font = summary_font
        cell.fill = summary_fill
        cell.alignment = number_alignment
        cell.number_format = '#,##0.00'
        cell.border = border

        # Total Settlement - Parent
        cell = ws.cell(row=row_num, column=13, value=total_parent)
        cell.font = summary_font
        cell.fill = summary_fill
        cell.alignment = number_alignment
        cell.number_format = '#,##0.00'
        cell.border = border

        # Total Settlement - Shop
        cell = ws.cell(row=row_num, column=14, value=total_shop)
        cell.font = summary_font
        cell.fill = summary_fill
        cell.alignment = number_alignment
        cell.number_format = '#,##0.00'
        cell.border = border

        # Save to buffer
        output = BytesIO()
        wb.save(output)
        output.seek(0)

        logger.info(f"XLSX export completed successfully")
        return output

    @staticmethod
    def _calculate_settlement(transaction: Transaction) -> Dict[str, Decimal]:
        """
        Calculate settlement amounts for a transaction.

        Args:
            transaction: Transaction object

        Returns:
            Dictionary with parent_amount and shop_amount
        """
        if transaction.gateway:
            settlement = transaction.gateway.calculate_settlement(transaction.amount)
            return {
                'parent_amount': settlement['parent_amount'],
                'shop_amount': settlement['shop_amount']
            }
        else:
            # If no gateway, assume all goes to parent
            return {
                'parent_amount': transaction.amount,
                'shop_amount': Decimal('0.00')
            }

    @staticmethod
    def get_transactions_for_date(export_date: date) -> QuerySet:
        """
        Get all transactions for a specific date.

        Args:
            export_date: Date to export transactions for

        Returns:
            QuerySet of Transaction objects
        """
        start_datetime = timezone.make_aware(datetime.combine(export_date, datetime.min.time()))
        end_datetime = timezone.make_aware(datetime.combine(export_date, datetime.max.time()))

        return Transaction.objects.filter(
            timestamp__gte=start_datetime,
            timestamp__lte=end_datetime
        ).select_related('gateway').order_by('timestamp')

    @staticmethod
    def get_transactions_for_date_range(start_date: date, end_date: date) -> QuerySet:
        """
        Get all transactions for a date range.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            QuerySet of Transaction objects
        """
        start_datetime = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        end_datetime = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))

        return Transaction.objects.filter(
            timestamp__gte=start_datetime,
            timestamp__lte=end_datetime
        ).select_related('gateway').order_by('timestamp')
