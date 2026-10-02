# Reporting & Analytics Reference

## Report Types
| Report | Endpoint | Format | Backend Service |
|---|---|---|---|
| Daily Reconciliation | `reports/daily-reconciliation/` | JSON | `reconciliation_service` |
| Daily Reconciliation V2 | `reports/daily-reconciliation-v2/` | JSON | `reconciliation_v2_service` |
| Date Range Reconciliation | `reports/date-range-reconciliation/` | JSON | `reconciliation_report_service` |
| Discrepancies | `reports/discrepancies/` | JSON | `reconciliation_report_service` |
| Stock Report | `reports/stock/` | JSON | `stock_report_service` |
| Historical Stock | `reports/stock/historical/` | JSON | `stock_report_service` |
| Daily/Date-Range XLSX | `reports/*/xlsx/` | XLSX | `reconciliation_report_service` |
| Stock with Adjustments XLSX | `reports/stock/with-adjustments/xlsx/` | XLSX | `stock_report_service` |
| Unified Export | `exports/report/` | XLSX | `export_service` |
| Merchandise Daily | `reports/merchandise/` | JSON | `merchandise_service` |

## Analytics Endpoints
| Endpoint | Purpose |
|---|---|
| `analytics/overview/` | Aggregate KPIs (total revenue, order count, top products) |
| `analytics/revenue/` | Revenue breakdown by gateway, time period |
| `analytics/products/` | Product velocity, stock turnover |
| `analytics/merchandise/` | Merchandise item sales |

## Celery Scheduled Task
```python
# Runs daily at 23:59:59 Africa/Nairobi
CELERY_BEAT_SCHEDULE = {
    "generate_daily_report": {
        "task": "payments.tasks.generate_daily_report",
        "schedule": crontab(hour=23, minute=59, day_of_week="*"),
    }
}
```
Uses `DailyStockReconciliation.get_or_create()` — safe to re-run.

## XLSX Generation (openpyxl)
- Color coding: green header rows, yellow for totals
- `BinaryField` on `GeneratedReport` model stores .xlsx bytes
- Date-stamped filenames: `report-YYYY-MM-DD_HHMM.xlsx`
- 4 sheets in unified export: Summary, Transactions, Stock, EOD
