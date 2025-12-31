from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    DeviceRegisterView, MessageIngestView, RotateAPIKeyView, DeviceSettingsUpdateView,
    TransactionListView, TransactionDetailView, transaction_by_tx_id, gateway_list,
    ManualPaymentCreateView, ManualPaymentListView, manual_payment_summary,
    daily_reconciliation_report, date_range_reconciliation_report, discrepancies_report,
    daily_reconciliation_pdf, date_range_reconciliation_pdf,
    daily_reconciliation_xlsx, date_range_reconciliation_xlsx,
    transactions_csv_export, transactions_xlsx_export,
    # Product & Inventory views
    ProductLineListView, ProductLineDetailView,
    ProductListView, ProductDetailView, product_search_by_sku,
    InventoryMovementListView, product_summary, stock_report, stock_report_xlsx,
    stock_report_historical, stock_report_historical_xlsx,
    # Transaction Fulfillment views
    activate_transaction_issuance, scan_product_barcode, remove_line_item,
    complete_transaction_issuance, cancel_transaction_issuance, get_current_issuance,
    revert_to_processing,
    # Time-Locking views
    lock_partial_transactions, lockable_transactions,
    # Combined Order views
    combined_order_list_create, combined_order_detail,
    add_transactions_to_combined_order,
    combined_order_scan_product, combined_order_cancel,
    combined_order_activate, combined_order_scan_staged,
    combined_order_complete, combined_order_remove_line_item,
    # Stock Take views
    stock_take_create_session, stock_take_session_detail,
    stock_take_scan_product, stock_take_complete_session, stock_take_remove_item,
    stock_take_list_active_sessions, stock_take_cancel_session, stock_take_cancel_all_active,
    # Unfulfilled orders export
    unfulfilled_orders_xlsx_export,
    # Authentication & User Management views
    CustomTokenObtainPairView, UserProfileView, ChangePasswordView, LogoutView,
    UserListCreateView, UserDetailView, AdminPasswordResetView,
    # Issuer Queue views
    issuer_queue, issuer_queue_pending,
    # Admin Operations
    cancel_fulfilled_transaction, mark_transaction_as_registration
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
    # Reconciliation Reports (XLSX - Enhanced with gateway sheets)
    path('reports/daily-reconciliation/xlsx/', daily_reconciliation_xlsx, name='daily-reconciliation-xlsx'),
    path('reports/date-range-reconciliation/xlsx/', date_range_reconciliation_xlsx, name='date-range-reconciliation-xlsx'),
    # Transaction Exports (CSV/XLSX)
    path('exports/transactions/csv/', transactions_csv_export, name='transactions-csv-export'),
    path('exports/transactions/xlsx/', transactions_xlsx_export, name='transactions-xlsx-export'),
    path('exports/unfulfilled-orders/xlsx/', unfulfilled_orders_xlsx_export, name='unfulfilled-orders-xlsx-export'),

    # Product & Inventory
    path('products/lines/', ProductLineListView.as_view(), name='product-line-list'),
    path('products/lines/<int:pk>/', ProductLineDetailView.as_view(), name='product-line-detail'),
    path('products/', ProductListView.as_view(), name='product-list'),
    path('products/<int:pk>/', ProductDetailView.as_view(), name='product-detail'),
    path('products/search/', product_search_by_sku, name='product-search'),
    path('products/summary/', product_summary, name='product-summary'),
    # Stock Reports
    path('reports/stock/', stock_report, name='stock-report'),
    path('reports/stock/xlsx/', stock_report_xlsx, name='stock-report-xlsx'),
    path('reports/stock/historical/', stock_report_historical, name='stock-report-historical'),
    path('reports/stock/historical/xlsx/', stock_report_historical_xlsx, name='stock-report-historical-xlsx'),
    path('inventory/movements/', InventoryMovementListView.as_view(), name='inventory-movement-list'),

    # Transaction Fulfillment
    path('transactions/<int:transaction_id>/activate-issuance/', activate_transaction_issuance, name='transaction-activate-issuance'),
    path('transactions/<int:transaction_id>/scan-barcode/', scan_product_barcode, name='transaction-scan-barcode'),
    path('transactions/<int:transaction_id>/line-items/<int:line_item_id>/', remove_line_item, name='transaction-remove-line-item'),
    path('transactions/<int:transaction_id>/complete-issuance/', complete_transaction_issuance, name='transaction-complete-issuance'),
    path('transactions/<int:transaction_id>/cancel-issuance/', cancel_transaction_issuance, name='transaction-cancel-issuance'),
    path('transactions/<int:transaction_id>/revert-to-processing/', revert_to_processing, name='transaction-revert-to-processing'),
    path('transactions/current-issuance/', get_current_issuance, name='transaction-current-issuance'),

    # Time-Locking
    path('transactions/lock-partial/', lock_partial_transactions, name='lock-partial-transactions'),
    path('transactions/lockable/', lockable_transactions, name='lockable-transactions'),

    # Combined Orders
    path('combined-orders/', combined_order_list_create, name='combined-order-list-create'),
    path('combined-orders/<str:combined_order_id>/', combined_order_detail, name='combined-order-detail'),
    path('combined-orders/<str:combined_order_id>/add-transactions/', add_transactions_to_combined_order, name='combined-order-add-transactions'),
    path('combined-orders/<str:combined_order_id>/scan/', combined_order_scan_product, name='combined-order-scan'),
    path('combined-orders/<str:combined_order_id>/cancel/', combined_order_cancel, name='combined-order-cancel'),
    path('combined-orders/<str:combined_order_id>/activate/', combined_order_activate, name='combined-order-activate'),
    path('combined-orders/<str:combined_order_id>/scan-staged/', combined_order_scan_staged, name='combined-order-scan-staged'),
    path('combined-orders/<str:combined_order_id>/complete/', combined_order_complete, name='combined-order-complete'),
    path('combined-orders/<str:combined_order_id>/line-items/<int:line_item_id>/', combined_order_remove_line_item, name='combined-order-remove-line-item'),

    # Stock Take
    path('stock-take/sessions/', stock_take_create_session, name='stock-take-create-session'),
    path('stock-take/sessions/active/', stock_take_list_active_sessions, name='stock-take-list-active-sessions'),
    path('stock-take/sessions/cancel-all/', stock_take_cancel_all_active, name='stock-take-cancel-all-active'),
    path('stock-take/sessions/<str:session_id>/', stock_take_session_detail, name='stock-take-session-detail'),
    path('stock-take/sessions/<str:session_id>/scan/', stock_take_scan_product, name='stock-take-scan-product'),
    path('stock-take/sessions/<str:session_id>/complete/', stock_take_complete_session, name='stock-take-complete-session'),
    path('stock-take/sessions/<str:session_id>/cancel/', stock_take_cancel_session, name='stock-take-cancel-session'),
    path('stock-take/sessions/<str:session_id>/items/<int:item_id>/', stock_take_remove_item, name='stock-take-remove-item'),

    # Authentication & User Management
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='auth-login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='auth-refresh'),
    path('auth/logout/', LogoutView.as_view(), name='auth-logout'),
    path('auth/profile/', UserProfileView.as_view(), name='auth-profile'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='auth-change-password'),
    path('users/', UserListCreateView.as_view(), name='user-list-create'),
    path('users/<int:pk>/', UserDetailView.as_view(), name='user-detail'),
    path('users/<int:pk>/reset-password/', AdminPasswordResetView.as_view(), name='admin-reset-password'),

    # Issuer Queue (Role-Based)
    path('issuer/queue/', issuer_queue, name='issuer-queue'),
    path('issuer/queue/pending/', issuer_queue_pending, name='issuer-queue-pending'),

    # Admin Operations
    path('transactions/<int:transaction_id>/cancel-fulfilled/', cancel_fulfilled_transaction, name='cancel-fulfilled'),
    path('transactions/<int:transaction_id>/mark-registration/', mark_transaction_as_registration, name='mark-registration'),
]
