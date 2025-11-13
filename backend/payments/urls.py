from django.urls import path
from .views import (
    DeviceRegisterView, MessageIngestView, RotateAPIKeyView, DeviceSettingsUpdateView,
    TransactionListView, TransactionDetailView, transaction_by_tx_id, gateway_list,
    ManualPaymentCreateView, ManualPaymentListView, manual_payment_summary,
    daily_reconciliation_report, date_range_reconciliation_report, discrepancies_report,
    daily_reconciliation_pdf, date_range_reconciliation_pdf,
    transactions_csv_export, transactions_xlsx_export
)

urlpatterns = [
    path('devices/register/', DeviceRegisterView.as_view(), name='device-register'),
    path('messages/', MessageIngestView.as_view(), name='message-ingest'),
    path('devices/<uuid:id>/rotate_key/', RotateAPIKeyView.as_view(), name='device-rotate-key'),
    path('devices/settings/', DeviceSettingsUpdateView.as_view(), name='device-settings-update'),
    path('gateways/', gateway_list, name='gateway-list'),
    path('transactions/', TransactionListView.as_view(), name='transaction-list'),
    path('transactions/by-tx-id/<str:tx_id>/', transaction_by_tx_id, name='transaction-by-tx-id'),
    path('transactions/<int:pk>/', TransactionDetailView.as_view(), name='transaction-detail'),
    path('payments/manual/', ManualPaymentCreateView.as_view(), name='manual-payment-create'),
    path('payments/manual/list/', ManualPaymentListView.as_view(), name='manual-payment-list'),
    path('payments/manual/summary/', manual_payment_summary, name='manual-payment-summary'),
    # Reconciliation Reports (JSON)
    path('reports/daily-reconciliation/', daily_reconciliation_report, name='daily-reconciliation'),
    path('reports/date-range-reconciliation/', date_range_reconciliation_report, name='date-range-reconciliation'),
    path('reports/discrepancies/', discrepancies_report, name='discrepancies-report'),
    # Reconciliation Reports (PDF)
    path('reports/daily-reconciliation/pdf/', daily_reconciliation_pdf, name='daily-reconciliation-pdf'),
    path('reports/date-range-reconciliation/pdf/', date_range_reconciliation_pdf, name='date-range-reconciliation-pdf'),
    # Transaction Exports (CSV/XLSX)
    path('exports/transactions/csv/', transactions_csv_export, name='transactions-csv-export'),
    path('exports/transactions/xlsx/', transactions_xlsx_export, name='transactions-xlsx-export'),
]
