"""
Unified Report Export Service

Generates a single Excel workbook containing the unused paybill transactions
for the requested report date.

"Unused" = paybill transactions that arrived on the report date and are still
NOT_PROCESSED or PROCESSING (i.e. money received but not yet fulfilled).
Internal (7974481) traffic, combined-order parents, already combined orders,
and merchandise-linked transactions are excluded.
"""

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import List
import logging

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from django.utils import timezone
from django.db.models import Q

from payments.models import Transaction, PaymentGateway

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared style helpers
# ---------------------------------------------------------------------------

THIN_BORDER = Border(
    left=Side(style='thin', color='CBD5E0'),
    right=Side(style='thin', color='CBD5E0'),
    top=Side(style='thin', color='CBD5E0'),
    bottom=Side(style='thin', color='CBD5E0'),
)

HEADER_FONT = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
HEADER_FILL = PatternFill(start_color='4A5568', end_color='4A5568', fill_type='solid')
HEADER_ALIGN = Alignment(horizontal='center', vertical='center', wrap_text=True)

GRAND_FONT = Font(name='Calibri', size=12, bold=True, color='FFFFFF')
GRAND_FILL = PatternFill(start_color='1F2937', end_color='1F2937', fill_type='solid')

NUM_ALIGN = Alignment(horizontal='right', vertical='center')
LEFT_ALIGN = Alignment(horizontal='left', vertical='center')
CENTER_ALIGN = Alignment(horizontal='center', vertical='center')


def _autosize_columns(ws, min_width: int = 12, max_width: int = 60):
    """Set column widths based on the longest cell value in each column."""
    for col_idx, col in enumerate(ws.columns, start=1):
        max_length = 0
        col_letter = get_column_letter(col_idx)
        for cell in col:
            try:
                if cell.value is not None:
                    max_length = max(max_length, len(str(cell.value)))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max(max_length + 3, min_width), max_width)


def _apply_header_row(ws, row_num: int, headers: List[str]):
    """Write a styled column-header row and return the next row number."""
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=row_num, column=col, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
    return row_num + 1


def _get_date_range(report_date: date):
    start = timezone.make_aware(datetime.combine(report_date, datetime.min.time()))
    end = timezone.make_aware(datetime.combine(report_date, datetime.max.time()))
    return start, end


# ---------------------------------------------------------------------------
# Sheet – Unused Paybill Transactions
# ---------------------------------------------------------------------------

def _build_unused_paybill(ws, report_date: date):
    headers = ['Transaction ID', 'Amount (KES)', 'Status', 'Timestamp']

    unfulfilled_statuses = [
        Transaction.OrderStatus.NOT_PROCESSED,
        Transaction.OrderStatus.PROCESSING,
    ]

    start_dt, end_dt = _get_date_range(report_date)

    unused_paybill = Transaction.objects.exclude(
        Q(sender_name__icontains='7974481') | Q(sender_phone__icontains='7974481') |
        Q(combined_order_parent__isnull=False) |
        Q(status=Transaction.OrderStatus.COMBINED_FULFILLED) |
        Q(merchandise_order__isnull=False)
    ).filter(
        timestamp__gte=start_dt,
        timestamp__lte=end_dt,
        status__in=unfulfilled_statuses,
        gateway__gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL,
    ).select_related('gateway').order_by('timestamp')

    row = _apply_header_row(ws, 1, headers)
    ws.freeze_panes = 'A2'

    total = Decimal('0.00')
    count = 0

    for txn in unused_paybill:
        ws.cell(row=row, column=1, value=txn.tx_id or '').alignment = LEFT_ALIGN
        ws.cell(row=row, column=1).border = THIN_BORDER

        cell = ws.cell(row=row, column=2, value=float(txn.amount))
        cell.number_format = '#,##0.00'
        cell.alignment = NUM_ALIGN
        cell.border = THIN_BORDER

        ws.cell(row=row, column=3, value=txn.get_status_display()).alignment = CENTER_ALIGN
        ws.cell(row=row, column=3).border = THIN_BORDER

        ws.cell(
            row=row, column=4,
            value=txn.timestamp.strftime('%Y-%m-%d %H:%M:%S') if txn.timestamp else '',
        ).alignment = CENTER_ALIGN
        ws.cell(row=row, column=4).border = THIN_BORDER

        total += txn.amount
        count += 1
        row += 1

    if count == 0:
        ws.cell(row=row, column=1, value='No unused paybill transactions on this date.').font = Font(
            italic=True, color='6B7280'
        )
        row += 1

    # Total row
    for col in range(1, len(headers) + 1):
        ws.cell(row=row, column=col).fill = GRAND_FILL
        ws.cell(row=row, column=col).font = GRAND_FONT
        ws.cell(row=row, column=col).border = THIN_BORDER
    ws.cell(row=row, column=1, value=f'TOTAL ({count})').alignment = LEFT_ALIGN
    cell = ws.cell(row=row, column=2, value=float(total))
    cell.number_format = '#,##0.00'
    cell.alignment = NUM_ALIGN

    _autosize_columns(ws)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

class TransactionExportService:
    """Generates the daily unused-paybill report workbook."""

    @staticmethod
    def generate_unified_report(report_date: date) -> BytesIO:
        """
        Build a single-sheet Excel workbook of unused paybill transactions
        for the given report date.

        Args:
            report_date: The date to generate the report for.

        Returns:
            BytesIO containing the .xlsx file.
        """
        logger.info("Generating unused-paybill report for %s", report_date)

        wb = Workbook()
        ws = wb.active
        ws.title = "Unused Paybill"
        _build_unused_paybill(ws, report_date)

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        logger.info("Unused-paybill report for %s generated successfully", report_date)
        return output
