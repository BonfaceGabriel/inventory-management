"""
Unified Report Export Service

Generates a single Excel workbook with four sheets:
  1. All Transactions   – every transaction for the date
  2. Combined Orders    – breakdown of combined-order fulfillment with child allocation
  3. Registration Kits  – kits issued that day (each kit = +200 to shop)
  4. Unfulfilled Orders – historical (from unused.xlsx) merged with system data
"""

import os
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import List, Dict
import logging

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from django.utils import timezone
from django.db.models import Q, Sum

from payments.models import Transaction, PaymentGateway, CombinedOrder

logger = logging.getLogger(__name__)

# Path to the historical unfulfilled file (pushed manually; monthly-only, temporary)
UNUSED_XLSX_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'unused.xlsx')

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

SECTION_FONT = Font(name='Calibri', size=12, bold=True, color='FFFFFF')
SECTION_FILL = PatternFill(start_color='2563EB', end_color='2563EB', fill_type='solid')
SECTION_ALIGN = Alignment(horizontal='center', vertical='center')

SUBTOTAL_FONT = Font(name='Calibri', size=11, bold=True)
SUBTOTAL_FILL = PatternFill(start_color='DBEAFE', end_color='DBEAFE', fill_type='solid')

GRAND_FONT = Font(name='Calibri', size=12, bold=True, color='FFFFFF')
GRAND_FILL = PatternFill(start_color='1F2937', end_color='1F2937', fill_type='solid')

NUM_ALIGN = Alignment(horizontal='right', vertical='center')
LEFT_ALIGN = Alignment(horizontal='left', vertical='center')
CENTER_ALIGN = Alignment(horizontal='center', vertical='center')


def _apply_header_row(ws, row_num: int, headers: List[str]):
    """Write a styled column-header row and return the next row number."""
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=row_num, column=col, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
    return row_num + 1


def _apply_section_banner(ws, row_num: int, text: str, num_cols: int, fill=None):
    """Write a merged section-banner row and return the next row number."""
    ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=num_cols)
    cell = ws.cell(row=row_num, column=1, value=text)
    cell.font = SECTION_FONT
    cell.fill = fill or SECTION_FILL
    cell.alignment = SECTION_ALIGN
    for col in range(1, num_cols + 1):
        ws.cell(row=row_num, column=col).border = THIN_BORDER
    return row_num + 1


def _get_date_range(report_date: date):
    start = timezone.make_aware(datetime.combine(report_date, datetime.min.time()))
    end = timezone.make_aware(datetime.combine(report_date, datetime.max.time()))
    return start, end


# ---------------------------------------------------------------------------
# Sheet 1 – All Transactions
# ---------------------------------------------------------------------------

def _build_all_transactions(ws, report_date: date):
    headers = ['Transaction ID', 'Amount (KES)', 'Amount Fulfilled (KES)',
               'Amount Remaining (KES)', 'Gateway Name', 'Timestamp']

    ws.column_dimensions['A'].width = 22
    ws.column_dimensions['B'].width = 16
    ws.column_dimensions['C'].width = 22
    ws.column_dimensions['D'].width = 22
    ws.column_dimensions['E'].width = 26
    ws.column_dimensions['F'].width = 22

    row = _apply_header_row(ws, 1, headers)
    ws.freeze_panes = 'A2'

    start_dt, end_dt = _get_date_range(report_date)

    # All transactions for the date – exclude internal (7974481) and combined-order parents
    transactions = Transaction.objects.exclude(
        Q(sender_name__icontains='7974481') | Q(sender_phone__icontains='7974481') |
        Q(combined_order_parent__isnull=False)
    ).filter(
        timestamp__gte=start_dt,
        timestamp__lte=end_dt
    ).select_related('gateway').order_by('timestamp')

    grand_total = Decimal('0.00')
    grand_fulfilled = Decimal('0.00')
    grand_remaining = Decimal('0.00')

    for txn in transactions:
        remaining = txn.remaining_amount

        ws.cell(row=row, column=1, value=txn.tx_id or '').alignment = LEFT_ALIGN
        ws.cell(row=row, column=1).border = THIN_BORDER

        cell = ws.cell(row=row, column=2, value=float(txn.amount))
        cell.number_format = '#,##0.00'
        cell.alignment = NUM_ALIGN
        cell.border = THIN_BORDER

        cell = ws.cell(row=row, column=3, value=float(txn.amount_fulfilled))
        cell.number_format = '#,##0.00'
        cell.alignment = NUM_ALIGN
        cell.border = THIN_BORDER

        cell = ws.cell(row=row, column=4, value=float(remaining))
        cell.number_format = '#,##0.00'
        cell.alignment = NUM_ALIGN
        cell.border = THIN_BORDER
        if remaining > 0:
            cell.fill = PatternFill(start_color='FEE2E2', end_color='FEE2E2', fill_type='solid')

        ws.cell(row=row, column=5, value=txn.gateway.name if txn.gateway else '').alignment = LEFT_ALIGN
        ws.cell(row=row, column=5).border = THIN_BORDER

        ws.cell(row=row, column=6, value=txn.timestamp.strftime('%Y-%m-%d %H:%M:%S') if txn.timestamp else '').alignment = CENTER_ALIGN
        ws.cell(row=row, column=6).border = THIN_BORDER

        grand_total += txn.amount
        grand_fulfilled += txn.amount_fulfilled
        grand_remaining += remaining
        row += 1

    # Grand total row
    row += 1
    for col in range(1, 7):
        ws.cell(row=row, column=col).fill = GRAND_FILL
        ws.cell(row=row, column=col).font = GRAND_FONT
        ws.cell(row=row, column=col).border = THIN_BORDER

    ws.cell(row=row, column=1, value='GRAND TOTAL').alignment = LEFT_ALIGN
    for col, val in [(2, grand_total), (3, grand_fulfilled), (4, grand_remaining)]:
        cell = ws.cell(row=row, column=col, value=float(val))
        cell.number_format = '#,##0.00'
        cell.alignment = NUM_ALIGN


# ---------------------------------------------------------------------------
# Sheet 2 – Combined Orders Breakdown
# ---------------------------------------------------------------------------

def _build_combined_orders(ws, report_date: date):
    headers = ['Child TX ID', 'Amount (KES)', 'Amount Fulfilled (KES)']

    ws.column_dimensions['A'].width = 24
    ws.column_dimensions['B'].width = 18
    ws.column_dimensions['C'].width = 22

    row = 1
    start_dt, end_dt = _get_date_range(report_date)

    paybill_gw = PaymentGateway.objects.filter(
        gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL,
        is_parent_company=True, is_active=True
    ).first()
    pdq_gw = PaymentGateway.objects.filter(
        gateway_type=PaymentGateway.GatewayType.PDQ, is_active=True
    ).first()
    till_gw_ids = list(PaymentGateway.objects.filter(
        gateway_type=PaymentGateway.GatewayType.MPESA_TILL,
        name__icontains='Products', is_active=True
    ).values_list('id', flat=True))

    paybill_pdq_ids = set()
    if paybill_gw:
        paybill_pdq_ids.add(paybill_gw.id)
    if pdq_gw:
        paybill_pdq_ids.add(pdq_gw.id)

    # Combined orders that have had activity on this date
    combined_orders = CombinedOrder.objects.filter(
        Q(status__in=[CombinedOrder.Status.IN_PROGRESS,
                      CombinedOrder.Status.PARTIALLY_FULFILLED,
                      CombinedOrder.Status.FULFILLED]),
        Q(fulfilled_at__gte=start_dt, fulfilled_at__lte=end_dt) |
        Q(updated_at__gte=start_dt, updated_at__lte=end_dt)
    ).prefetch_related('transactions__transaction__gateway').order_by('-updated_at')

    if not combined_orders.exists():
        ws.cell(row=1, column=1, value='No combined orders fulfilled on this date.')
        ws.cell(row=1, column=1).font = Font(italic=True, color='6B7280')
        return

    for order in combined_orders:
        today_fulfillment = order.amount_fulfilled - order.base_amount_fulfilled
        if today_fulfillment <= 0:
            continue

        # --- Section banner: combined order header ---
        banner_text = (
            f"{order.combined_order_id}  |  "
            f"Total: {float(order.total_amount):,.2f}  |  "
            f"Fulfilled: {float(order.amount_fulfilled):,.2f}  |  "
            f"Status: {order.get_status_display()}"
        )
        row = _apply_section_banner(ws, row, banner_text, 3)

        # Column headers
        row = _apply_header_row(ws, row, headers)

        # Gather child transactions and compute allocation
        children = []
        paybill_pdq_pool = Decimal('0.00')
        till_pool = Decimal('0.00')

        for cot in order.transactions.all():
            child = cot.transaction
            children.append(child)
            if child.gateway_id in paybill_pdq_ids:
                paybill_pdq_pool += child.amount
            elif child.gateway_id in till_gw_ids:
                till_pool += child.amount

        # Priority allocation: paybill/PDQ consumed first, till gets remainder
        paybill_pdq_consumed = min(today_fulfillment, paybill_pdq_pool)
        till_consumed = max(Decimal('0.00'), min(today_fulfillment - paybill_pdq_consumed, till_pool))

        # Distribute consumed amounts proportionally among children per pool
        paybill_pdq_remaining_to_allocate = paybill_pdq_consumed
        till_remaining_to_allocate = till_consumed

        order_subtotal_fulfilled = Decimal('0.00')

        for child in children:
            in_paybill_pool = child.gateway_id in paybill_pdq_ids
            in_till_pool = child.gateway_id in till_gw_ids

            if in_paybill_pool and paybill_pdq_pool > 0:
                # Proportional share of paybill/PDQ pool
                share = (child.amount / paybill_pdq_pool) * paybill_pdq_consumed
                # Don't exceed child's amount or what's left to allocate
                allocated = min(share, paybill_pdq_remaining_to_allocate, child.amount)
                paybill_pdq_remaining_to_allocate -= allocated
            elif in_till_pool and till_pool > 0:
                share = (child.amount / till_pool) * till_consumed
                allocated = min(share, till_remaining_to_allocate, child.amount)
                till_remaining_to_allocate -= allocated
            else:
                allocated = Decimal('0.00')

            # Write child row
            ws.cell(row=row, column=1, value=child.tx_id or '').alignment = LEFT_ALIGN
            ws.cell(row=row, column=1).border = THIN_BORDER

            cell = ws.cell(row=row, column=2, value=float(child.amount))
            cell.number_format = '#,##0.00'
            cell.alignment = NUM_ALIGN
            cell.border = THIN_BORDER

            cell = ws.cell(row=row, column=3, value=float(allocated))
            cell.number_format = '#,##0.00'
            cell.alignment = NUM_ALIGN
            cell.border = THIN_BORDER

            # Highlight till rows
            if in_till_pool:
                for col in range(1, 4):
                    ws.cell(row=row, column=col).fill = PatternFill(
                        start_color='F0FDF4', end_color='F0FDF4', fill_type='solid'
                    )

            order_subtotal_fulfilled += allocated
            row += 1

        # Subtotal row for this combined order
        for col in range(1, 4):
            ws.cell(row=row, column=col).fill = SUBTOTAL_FILL
            ws.cell(row=row, column=col).font = SUBTOTAL_FONT
            ws.cell(row=row, column=col).border = THIN_BORDER
        ws.cell(row=row, column=1, value='Subtotal').alignment = LEFT_ALIGN
        cell = ws.cell(row=row, column=2, value=float(order.total_amount))
        cell.number_format = '#,##0.00'
        cell.alignment = NUM_ALIGN
        cell = ws.cell(row=row, column=3, value=float(order_subtotal_fulfilled))
        cell.number_format = '#,##0.00'
        cell.alignment = NUM_ALIGN

        row += 2  # blank row between orders


# ---------------------------------------------------------------------------
# Sheet 3 – Registration Kits
# ---------------------------------------------------------------------------

def _build_registration_kits(ws, report_date: date):
    headers = ['Transaction ID', 'Kits Issued', 'Value (KES)', 'Gateway Name']

    ws.column_dimensions['A'].width = 22
    ws.column_dimensions['B'].width = 14
    ws.column_dimensions['C'].width = 16
    ws.column_dimensions['D'].width = 26

    KIT_VALUE = Decimal('200.00')  # Same as REGISTRATION_KIT_VALUE in reconciliation_v2

    row = _apply_header_row(ws, 1, headers)
    ws.freeze_panes = 'A2'

    start_dt, end_dt = _get_date_range(report_date)

    # All registration transactions with kits issued on this date
    # (singles + combined-order parents, same logic as reconciliation_v2.calculate_kits)
    base_exclude = Q(sender_name__icontains='7974481') | Q(sender_phone__icontains='7974481')

    reg_txns = Transaction.objects.exclude(
        base_exclude | Q(status=Transaction.OrderStatus.COMBINED_FULFILLED)
    ).filter(
        is_registration=True,
        registration_kit_issued=True,
    ).filter(
        Q(completed_at__gte=start_dt, completed_at__lte=end_dt) |
        Q(timestamp__gte=start_dt, timestamp__lte=end_dt)
    ).select_related('gateway').order_by('timestamp')

    total_kits = 0
    total_value = Decimal('0.00')

    for txn in reg_txns:
        qty = txn.registration_kit_quantity or 0
        value = KIT_VALUE * qty

        ws.cell(row=row, column=1, value=txn.tx_id or '').alignment = LEFT_ALIGN
        ws.cell(row=row, column=1).border = THIN_BORDER

        ws.cell(row=row, column=2, value=qty).alignment = CENTER_ALIGN
        ws.cell(row=row, column=2).border = THIN_BORDER

        cell = ws.cell(row=row, column=3, value=float(value))
        cell.number_format = '#,##0.00'
        cell.alignment = NUM_ALIGN
        cell.border = THIN_BORDER

        ws.cell(row=row, column=4, value=txn.gateway.name if txn.gateway else '').alignment = LEFT_ALIGN
        ws.cell(row=row, column=4).border = THIN_BORDER

        total_kits += qty
        total_value += value
        row += 1

    if total_kits == 0:
        ws.cell(row=row, column=1, value='No registration kits issued on this date.')
        ws.cell(row=row, column=1).font = Font(italic=True, color='6B7280')
        return

    # Summary row
    row += 1
    for col in range(1, 5):
        ws.cell(row=row, column=col).fill = GRAND_FILL
        ws.cell(row=row, column=col).font = GRAND_FONT
        ws.cell(row=row, column=col).border = THIN_BORDER

    ws.cell(row=row, column=1, value='TOTAL').alignment = LEFT_ALIGN
    ws.cell(row=row, column=2, value=total_kits).alignment = CENTER_ALIGN
    cell = ws.cell(row=row, column=3, value=float(total_value))
    cell.number_format = '#,##0.00'
    cell.alignment = NUM_ALIGN
    ws.cell(row=row, column=4, value=f'{total_kits} kit(s) × 200 KES').alignment = LEFT_ALIGN


# ---------------------------------------------------------------------------
# Sheet 4 – Unfulfilled Orders
# ---------------------------------------------------------------------------

def _read_unused_xlsx() -> Dict[str, Decimal]:
    """
    Read the historical unfulfilled file (unused.xlsx).
    Returns {tx_id: amount}.  Returns empty dict if file missing.
    """
    path = os.path.abspath(UNUSED_XLSX_PATH)
    if not os.path.exists(path):
        logger.info("unused.xlsx not found at %s — skipping historical section", path)
        return {}

    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        result = {}
        for row in ws.iter_rows(min_row=2, values_only=True):  # skip header
            if row[0] is None:
                continue
            tx_id = str(row[0]).strip()
            amount = Decimal(str(row[1])) if row[1] is not None else Decimal('0.00')
            if tx_id:
                result[tx_id] = amount
        wb.close()
        return result
    except Exception as e:
        logger.error("Failed to read unused.xlsx: %s", e)
        return {}


def _build_unfulfilled_orders(ws, report_date: date):
    headers = ['Transaction ID', 'Amount (KES)', 'Status', 'Source']

    ws.column_dimensions['A'].width = 22
    ws.column_dimensions['B'].width = 16
    ws.column_dimensions['C'].width = 18
    ws.column_dimensions['D'].width = 16

    unfulfilled_statuses = [
        Transaction.OrderStatus.NOT_PROCESSED,
        Transaction.OrderStatus.PROCESSING,
    ]

    # --------------- Section 1: Historical (from unused.xlsx) ---------------
    row = _apply_section_banner(ws, 1, 'HISTORICAL UNFULFILLED (from uploaded file)', 4,
                                fill=PatternFill(start_color='DC2626', end_color='DC2626', fill_type='solid'))
    row = _apply_header_row(ws, row, headers)

    historical_data = _read_unused_xlsx()
    hist_total = Decimal('0.00')
    hist_count = 0

    if historical_data:
        # Batch-check which of those TX IDs are still unfulfilled
        tx_ids = list(historical_data.keys())
        still_unfulfilled = set(
            Transaction.objects.filter(
                tx_id__in=tx_ids,
                status__in=unfulfilled_statuses
            ).values_list('tx_id', flat=True)
        )

        for tx_id in tx_ids:
            if tx_id not in still_unfulfilled:
                continue  # already fulfilled or cancelled – skip

            amount = historical_data[tx_id]
            ws.cell(row=row, column=1, value=tx_id).alignment = LEFT_ALIGN
            ws.cell(row=row, column=1).border = THIN_BORDER

            cell = ws.cell(row=row, column=2, value=float(amount))
            cell.number_format = '#,##0.00'
            cell.alignment = NUM_ALIGN
            cell.border = THIN_BORDER

            # Pull live status
            try:
                live_txn = Transaction.objects.get(tx_id=tx_id)
                ws.cell(row=row, column=3, value=live_txn.get_status_display()).alignment = CENTER_ALIGN
            except Transaction.DoesNotExist:
                ws.cell(row=row, column=3, value='Unknown').alignment = CENTER_ALIGN
            ws.cell(row=row, column=3).border = THIN_BORDER

            ws.cell(row=row, column=4, value='Uploaded File').alignment = CENTER_ALIGN
            ws.cell(row=row, column=4).border = THIN_BORDER
            ws.cell(row=row, column=4).fill = PatternFill(start_color='FEE2E2', end_color='FEE2E2', fill_type='solid')

            hist_total += amount
            hist_count += 1
            row += 1
    else:
        ws.cell(row=row, column=1, value='No historical file available.').font = Font(italic=True, color='6B7280')
        row += 1

    # Historical subtotal
    for col in range(1, 5):
        ws.cell(row=row, column=col).fill = SUBTOTAL_FILL
        ws.cell(row=row, column=col).font = SUBTOTAL_FONT
        ws.cell(row=row, column=col).border = THIN_BORDER
    ws.cell(row=row, column=1, value=f'Historical Subtotal ({hist_count})').alignment = LEFT_ALIGN
    cell = ws.cell(row=row, column=2, value=float(hist_total))
    cell.number_format = '#,##0.00'
    cell.alignment = NUM_ALIGN
    row += 2  # blank

    # --------------- Section 2: Today onwards (from system) -----------------
    row = _apply_section_banner(ws, row, f'UNFULFILLED FROM SYSTEM (from {report_date})', 4)
    row = _apply_header_row(ws, row, headers)

    start_dt, _ = _get_date_range(report_date)

    # Paybill transactions from report_date onwards that are still unfulfilled
    # (only paybill – till transactions don't carry over as "unused")
    system_unfulfilled = Transaction.objects.exclude(
        Q(sender_name__icontains='7974481') | Q(sender_phone__icontains='7974481') |
        Q(combined_order_parent__isnull=False) |
        Q(status=Transaction.OrderStatus.COMBINED_FULFILLED)
    ).filter(
        timestamp__gte=start_dt,
        status__in=unfulfilled_statuses,
        gateway__gateway_type=PaymentGateway.GatewayType.MPESA_PAYBILL
    ).select_related('gateway').order_by('timestamp')

    sys_total = Decimal('0.00')
    sys_count = 0

    for txn in system_unfulfilled:
        ws.cell(row=row, column=1, value=txn.tx_id or '').alignment = LEFT_ALIGN
        ws.cell(row=row, column=1).border = THIN_BORDER

        cell = ws.cell(row=row, column=2, value=float(txn.amount))
        cell.number_format = '#,##0.00'
        cell.alignment = NUM_ALIGN
        cell.border = THIN_BORDER

        ws.cell(row=row, column=3, value=txn.get_status_display()).alignment = CENTER_ALIGN
        ws.cell(row=row, column=3).border = THIN_BORDER

        ws.cell(row=row, column=4, value='System').alignment = CENTER_ALIGN
        ws.cell(row=row, column=4).border = THIN_BORDER
        ws.cell(row=row, column=4).fill = PatternFill(start_color='DBEAFE', end_color='DBEAFE', fill_type='solid')

        sys_total += txn.amount
        sys_count += 1
        row += 1

    if sys_count == 0:
        ws.cell(row=row, column=1, value='No unfulfilled paybill transactions from this date.').font = Font(italic=True, color='6B7280')
        row += 1

    # System subtotal
    for col in range(1, 5):
        ws.cell(row=row, column=col).fill = SUBTOTAL_FILL
        ws.cell(row=row, column=col).font = SUBTOTAL_FONT
        ws.cell(row=row, column=col).border = THIN_BORDER
    ws.cell(row=row, column=1, value=f'System Subtotal ({sys_count})').alignment = LEFT_ALIGN
    cell = ws.cell(row=row, column=2, value=float(sys_total))
    cell.number_format = '#,##0.00'
    cell.alignment = NUM_ALIGN
    row += 2

    # Grand total
    for col in range(1, 5):
        ws.cell(row=row, column=col).fill = GRAND_FILL
        ws.cell(row=row, column=col).font = GRAND_FONT
        ws.cell(row=row, column=col).border = THIN_BORDER
    ws.cell(row=row, column=1, value='GRAND TOTAL').alignment = LEFT_ALIGN
    cell = ws.cell(row=row, column=2, value=float(hist_total + sys_total))
    cell.number_format = '#,##0.00'
    cell.alignment = NUM_ALIGN


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

class TransactionExportService:
    """Generates the unified daily report workbook."""

    @staticmethod
    def generate_unified_report(report_date: date) -> BytesIO:
        """
        Build a single Excel workbook with all four report sheets.

        Args:
            report_date: The date to generate the report for.

        Returns:
            BytesIO containing the .xlsx file.
        """
        logger.info("Generating unified report for %s", report_date)

        wb = Workbook()

        # Sheet 1 – All Transactions
        ws1 = wb.active
        ws1.title = "All Transactions"
        _build_all_transactions(ws1, report_date)

        # Sheet 2 – Combined Orders
        ws2 = wb.create_sheet("Combined Orders")
        _build_combined_orders(ws2, report_date)

        # Sheet 3 – Registration Kits
        ws3 = wb.create_sheet("Registration Kits")
        _build_registration_kits(ws3, report_date)

        # Sheet 4 – Unfulfilled Orders
        ws4 = wb.create_sheet("Unfulfilled Orders")
        _build_unfulfilled_orders(ws4, report_date)

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        logger.info("Unified report for %s generated successfully", report_date)
        return output
