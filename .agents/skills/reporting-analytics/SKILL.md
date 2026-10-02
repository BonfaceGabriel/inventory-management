---
name: reporting-analytics
description: Report generation, analytics queries, and data exports for this project. Use when working with XLSX report generation (openpyxl), reconciliation reports (daily/date-range), the unified daily export, stock reports (current/historical), analytics endpoints (revenue, products, merchandise), Celery automated report scheduling, and any data aggregation or export functionality.
metadata:
  domain: reporting
  type: data
---

## Report Types

| Report | Format | Endpoint | Service |
|--------|--------|----------|---------|
| Daily Reconciliation | JSON | `/reports/daily-reconciliation/` | `ReconciliationService` |
| Daily Reconciliation V2 | JSON | `/reports/daily-reconciliation-v2/` | `ReconciliationV2Service` |
| Date Range Reconciliation | JSON | `/reports/date-range-reconciliation/` | `ReconciliationService` |
| Discrepancies | JSON | `/reports/discrepancies/` | `ReconciliationService` |
| Daily Reconciliation XLSX | XLSX | `/reports/daily-reconciliation/xlsx/` | `ReconciliationReportService` |
| Date Range Reconciliation XLSX | XLSX | `/reports/date-range-reconciliation/xlsx/` | `ReconciliationReportService` |
| Unified Report (4 sheets) | XLSX | `/exports/report/` | `TransactionExportService` |
| Stock Report | JSON | `/reports/stock/` | `StockReportService` |
| Stock Report XLSX | XLSX | `/reports/stock/xlsx/` | `StockReportService` |
| Historical Stock | JSON | `/reports/stock/historical/` | `StockReportService` |
| Historical Stock XLSX | XLSX | `/reports/stock/historical/xlsx/` | `StockReportService` |
| Stock with Adjustments XLSX | XLSX | `/reports/stock/with-adjustments/xlsx/` | `StockReportService` |
| Merchandise Daily | JSON | `/reports/merchandise/` | `MerchandiseService` |

## Analytics Endpoints

| Endpoint | Parameters | Purpose |
|----------|-----------|---------|
| `/analytics/overview/` | start_date, end_date | Revenue summary + top product + top merch |
| `/analytics/revenue/` | start_date, end_date, granularity | Revenue timeline by gateway (day/week/month) |
| `/analytics/products/` | start_date, end_date | Fast/slow moving products |
| `/analytics/merchandise/` | start_date, end_date | Merchandise sales breakdown |

- **Default range**: Last 30 days if no dates provided.
- **Granularity**: `day`, `week`, or `month`. Uses `_bucket_label()` for ISO week formatting.
- **All analytics**: Powered by `AnalyticsService` in `services/analytics_service.py`.

## Unified Report (XLSX) — 4 Sheets

1. **All Transactions** — Every transaction for the selected date with gateway, status, amounts
2. **Combined Orders** — Combined-order fulfillment breakdown with child transaction allocation
3. **Registration Kits** — Kits issued that day (each kit = +200 to shop)
4. **Unfulfilled Orders** — Historical unfulfilled data merged with system data

- **On-the-fly generation**: Generated on request for current date.
- **Cached for past dates**: Celery nightly task at 23:59 EAT persists to `GeneratedReport` DB model. Uses `get_or_create` for idempotency.
- **Fallback**: If no cached report exists for a past date, generates on-the-fly.

## XLSX Generation Patterns (openpyxl)

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

wb = Workbook()
ws = wb.active
ws.title = "Sheet Name"

# Headers
headers = ['Column A', 'Column B']
header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
header_font = Font(bold=True, color='FFFFFF')

for col, header in enumerate(headers, 1):
    cell = ws.cell(row=1, column=col, value=header)
    cell.fill = header_fill
    cell.font = header_font

# Color coding for stock status
colors = {
    'OUT_OF_STOCK': PatternFill(start_color='FF0000', end_color='FF0000', fill_type='solid'),
    'LOW_STOCK': PatternFill(start_color='FFD700', end_color='FFD700', fill_type='solid'),
    'IN_STOCK': PatternFill(start_color='00FF00', end_color='00FF00', fill_type='solid'),
}

# Response
response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
response['Content-Disposition'] = f'attachment; filename="report_{date}.xlsx"'
response.write(buffer.getvalue())
```

## Key Gotchas

- **XLSX in DB**: `GeneratedReport.report_file` is a `BinaryField` storing the raw XLSX bytes. Use `bytes(stored.report_file)` to retrieve.
- **Date-stamped filenames**: All exports use format `eagle_shop_report_{date}.xlsx` or similar.
- **Historical stock reconstruction**: Uses `InventoryMovement` audit trail. Reverses movements from today back to the target date to reconstruct past stock levels.
- **Reconciliation V2 formula**: `X = Mpesa_Paybill - Unused + PDQ + Previous - Sales`, `Y = Till - Previous - Credit - KITS`, `V = X + Y`. Should equal 0.
- **Celery Beat schedule**: Runs at 20:59:59 UTC (23:59:59 EAT). Only creates if no report exists for that date (`get_or_create`). Re-running is safe — it won't overwrite.

## Analytics Query Patterns

```python
# Revenue by gateway type
Transaction.objects.filter(
    status__in=['FULFILLED', 'PARTIALLY_FULFILLED'],
    timestamp__date__gte=start_date,
    timestamp__date__lte=end_date,
).values('gateway__gateway_type').annotate(
    total=Sum('amount_fulfilled')
).order_by('-total')

# Fast/slow moving products
TransactionLineItem.objects.filter(
    transaction__status='FULFILLED',
    created_at__date__gte=start_date,
).values('product__prod_name').annotate(
    count=Count('id')
).order_by('-count')
```

## Anti-patterns

- Don't regenerate `GeneratedReport` for past dates — serve from cache (Celery snapshot is authoritative).
- Don't hardcode gateway names in reports — always reference via `PaymentGateway` model.
- Don't forget timezone conversion — all date queries should use `timezone.localdate()` not `date.today()`.
- Don't use float for monetary values in reports — always `Decimal` with appropriate precision.
- Don't load the entire dataset into memory for XLSX generation — use streaming or chunking for large datasets.
