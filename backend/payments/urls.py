from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    DeviceRegisterView, MessageIngestView, RelayMessageIngestView, RotateAPIKeyView, DeviceSettingsUpdateView,
    promotion_list_create, promotion_detail,
    location_list_create, location_detail, location_close, set_user_location,
    merchandise_catalog, merchandise_catalog_item_detail,
    merchandise_pending_orders, merchandise_order_detail,
    merchandise_fulfill_order, merchandise_daily_report,
    merchandise_stock_list, merchandise_adjust_stock, merchandise_stock_movements,
    TransactionListView, TransactionDetailView, transaction_by_tx_id, gateway_list,
    ManualPaymentCreateView, ManualPaymentListView, manual_payment_summary,
    daily_reconciliation_report, date_range_reconciliation_report, discrepancies_report,
    daily_reconciliation_v2,
    daily_reconciliation_xlsx, date_range_reconciliation_xlsx,
    unified_report_export,
    analytics_overview, analytics_revenue, analytics_products, analytics_merchandise,
    # Product & Inventory views
    ProductLineListView, ProductLineDetailView,
    ProductListView, ProductDetailView, product_search_by_sku,
    InventoryMovementListView, product_summary, stock_report, stock_report_xlsx,
    stock_report_historical, stock_report_historical_xlsx,
    # Transaction Fulfillment views
    issue_registration_kit, activate_transaction_issuance, scan_product_barcode, remove_line_item,
    complete_transaction_issuance, cancel_transaction_issuance, get_current_issuance,
    revert_to_processing, revert_to_not_processed, issue_registration_from_partial,
    # Combined Order views
    combined_order_list_create, combined_order_detail,
    add_transactions_to_combined_order,
    combined_order_scan_product, combined_order_cancel, combined_order_cancel_issuance, combined_order_revert,
    combined_order_activate, combined_order_scan_staged,
    combined_order_complete, combined_order_remove_line_item,
    mark_combined_order_as_registration,
    # Stock Take views
    stock_take_create_session, stock_take_session_detail,
    stock_take_scan_product, stock_take_complete_session, stock_take_remove_item,
    stock_take_update_item_quantity, stock_take_update_kit_quantity,
    stock_take_list_active_sessions, stock_take_cancel_session, stock_take_cancel_all_active,
    # Authentication & User Management views
    CustomTokenObtainPairView, UserProfileView, ChangePasswordView, LogoutView,
    UserListCreateView, UserDetailView, AdminPasswordResetView,
    # Issuer Queue views
    issuer_queue, issuer_queue_pending, issuer_stats,
    # Admin Operations
    cancel_fulfilled_transaction, cancel_registration_order, delete_transaction, mark_transaction_as_registration,
    unmark_transaction_as_registration,
    # Stock Reconciliation views
    create_stock_reconciliation, update_stock_adjustment, confirm_stock_reconciliation, cancel_stock_reconciliation,
    get_stock_reconciliation, get_stock_reconciliation_by_date, stock_report_with_adjustments_xlsx,
    bulk_update_stock_adjustments, revert_stock_reconciliation,
    eod_value_reconciliation_today, eod_value_reconciliation_update_today, eod_value_reconciliation_confirm_today,
    # Opening Stock Baseline views (for initial setup)
    set_opening_stock_baseline, set_bulk_opening_stock_baseline, clear_opening_stock_baseline
)

urlpatterns = [
    path('devices/register/', DeviceRegisterView.as_view(), name='device-register'),
    path('messages/', MessageIngestView.as_view(), name='message-ingest'),
    path('messages/relay/', RelayMessageIngestView.as_view(), name='message-relay-ingest'),
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
    path('reports/daily-reconciliation-v2/', daily_reconciliation_v2, name='daily-reconciliation-v2'),
    path('reports/date-range-reconciliation/', date_range_reconciliation_report, name='date-range-reconciliation'),
    path('reports/discrepancies/', discrepancies_report, name='discrepancies-report'),
    # Reconciliation Reports (XLSX - Enhanced with gateway sheets)
    path('reports/daily-reconciliation/xlsx/', daily_reconciliation_xlsx, name='daily-reconciliation-xlsx'),
    path('reports/date-range-reconciliation/xlsx/', date_range_reconciliation_xlsx, name='date-range-reconciliation-xlsx'),
    # Unified daily report
    path('exports/report/', unified_report_export, name='unified-report-export'),
    # Analytics
    path('analytics/overview/', analytics_overview, name='analytics-overview'),
    path('analytics/revenue/', analytics_revenue, name='analytics-revenue'),
    path('analytics/products/', analytics_products, name='analytics-products'),
    path('analytics/merchandise/', analytics_merchandise, name='analytics-merchandise'),

    # Product & Inventory
    path('products/lines/', ProductLineListView.as_view(), name='product-line-list'),
    path('products/lines/<int:pk>/', ProductLineDetailView.as_view(), name='product-line-detail'),
    path('products/', ProductListView.as_view(), name='product-list'),
    path('products/search/', product_search_by_sku, name='product-search'),
    path('products/summary/', product_summary, name='product-summary'),
    path('products/<int:pk>/', ProductDetailView.as_view(), name='product-detail'),
    # Stock Reports
    path('reports/stock/', stock_report, name='stock-report'),
    path('reports/stock/xlsx/', stock_report_xlsx, name='stock-report-xlsx'),
    path('reports/stock/historical/', stock_report_historical, name='stock-report-historical'),
    path('reports/stock/historical/xlsx/', stock_report_historical_xlsx, name='stock-report-historical-xlsx'),
    path('inventory/movements/', InventoryMovementListView.as_view(), name='inventory-movement-list'),

    # Transaction Fulfillment
    path('transactions/<int:transaction_id>/issue-registration-kit/', issue_registration_kit, name='transaction-issue-registration-kit'),
    path('transactions/<int:transaction_id>/activate-issuance/', activate_transaction_issuance, name='transaction-activate-issuance'),
    path('transactions/<int:transaction_id>/scan-barcode/', scan_product_barcode, name='transaction-scan-barcode'),
    path('transactions/<int:transaction_id>/line-items/<int:line_item_id>/', remove_line_item, name='transaction-remove-line-item'),
    path('transactions/<int:transaction_id>/complete-issuance/', complete_transaction_issuance, name='transaction-complete-issuance'),
    path('transactions/<int:transaction_id>/cancel-issuance/', cancel_transaction_issuance, name='transaction-cancel-issuance'),
    path('transactions/<int:transaction_id>/revert-to-processing/', revert_to_processing, name='transaction-revert-to-processing'),
    path('transactions/<int:transaction_id>/revert-to-not-processed/', revert_to_not_processed, name='transaction-revert-to-not-processed'),
    path('transactions/<int:transaction_id>/issue-registration-from-partial/', issue_registration_from_partial, name='transaction-issue-registration-from-partial'),
    path('transactions/current-issuance/', get_current_issuance, name='transaction-current-issuance'),

    # Combined Orders
    path('combined-orders/', combined_order_list_create, name='combined-order-list-create'),
    path('combined-orders/<str:combined_order_id>/', combined_order_detail, name='combined-order-detail'),
    path('combined-orders/<str:combined_order_id>/add-transactions/', add_transactions_to_combined_order, name='combined-order-add-transactions'),
    path('combined-orders/<str:combined_order_id>/scan/', combined_order_scan_product, name='combined-order-scan'),
    path('combined-orders/<str:combined_order_id>/cancel/', combined_order_cancel, name='combined-order-cancel'),
    path('combined-orders/<str:combined_order_id>/cancel-issuance/', combined_order_cancel_issuance, name='combined-order-cancel-issuance'),
    path('combined-orders/<str:combined_order_id>/revert/', combined_order_revert, name='combined-order-revert'),
    path('combined-orders/<str:combined_order_id>/activate/', combined_order_activate, name='combined-order-activate'),
    path('combined-orders/<str:combined_order_id>/scan-staged/', combined_order_scan_staged, name='combined-order-scan-staged'),
    path('combined-orders/<str:combined_order_id>/complete/', combined_order_complete, name='combined-order-complete'),
    path('combined-orders/<str:combined_order_id>/line-items/<int:line_item_id>/', combined_order_remove_line_item, name='combined-order-remove-line-item'),
    path('combined-orders/<str:combined_order_id>/mark-registration/', mark_combined_order_as_registration, name='combined-order-mark-registration'),

    # Stock Take
    path('stock-take/sessions/', stock_take_create_session, name='stock-take-create-session'),
    path('stock-take/sessions/active/', stock_take_list_active_sessions, name='stock-take-list-active-sessions'),
    path('stock-take/sessions/cancel-all/', stock_take_cancel_all_active, name='stock-take-cancel-all-active'),
    path('stock-take/sessions/<str:session_id>/', stock_take_session_detail, name='stock-take-session-detail'),
    path('stock-take/sessions/<str:session_id>/scan/', stock_take_scan_product, name='stock-take-scan-product'),
    path('stock-take/sessions/<str:session_id>/complete/', stock_take_complete_session, name='stock-take-complete-session'),
    path('stock-take/sessions/<str:session_id>/cancel/', stock_take_cancel_session, name='stock-take-cancel-session'),
    path('stock-take/sessions/<str:session_id>/items/<int:item_id>/', stock_take_update_item_quantity, name='stock-take-update-item'),
    path('stock-take/sessions/<str:session_id>/items/<int:item_id>/delete/', stock_take_remove_item, name='stock-take-remove-item'),
    path('stock-take/sessions/<str:session_id>/kit-quantity/', stock_take_update_kit_quantity, name='stock-take-update-kit-quantity'),

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
    path('issuer/stats/', issuer_stats, name='issuer-stats'),

    # Admin Operations
    path('transactions/<int:transaction_id>/cancel-fulfilled/', cancel_fulfilled_transaction, name='cancel-fulfilled'),
    path('transactions/<int:transaction_id>/cancel-registration/', cancel_registration_order, name='cancel-registration'),
    path('transactions/<int:transaction_id>/delete/', delete_transaction, name='delete-transaction'),
    path('transactions/<int:transaction_id>/mark-registration/', mark_transaction_as_registration, name='mark-registration'),
    path('transactions/<int:transaction_id>/unmark-registration/', unmark_transaction_as_registration, name='unmark-registration'),

    # Stock Reconciliation
    path('stock-reconciliation/create/', create_stock_reconciliation, name='stock-reconciliation-create'),
    path('stock-reconciliation/<uuid:reconciliation_id>/', get_stock_reconciliation, name='stock-reconciliation-detail'),
    path('stock-reconciliation/<uuid:reconciliation_id>/adjust/', update_stock_adjustment, name='stock-reconciliation-adjust'),
    path('stock-reconciliation/<uuid:reconciliation_id>/adjust-bulk/', bulk_update_stock_adjustments, name='stock-reconciliation-adjust-bulk'),
    path('stock-reconciliation/<uuid:reconciliation_id>/confirm/', confirm_stock_reconciliation, name='stock-reconciliation-confirm'),
    path('stock-reconciliation/<uuid:reconciliation_id>/cancel/', cancel_stock_reconciliation, name='stock-reconciliation-cancel'),
    path('stock-reconciliation/<uuid:reconciliation_id>/revert/', revert_stock_reconciliation, name='stock-reconciliation-revert'),
    path('stock-reconciliation/by-date/', get_stock_reconciliation_by_date, name='stock-reconciliation-by-date'),
    path('reports/stock/with-adjustments/xlsx/', stock_report_with_adjustments_xlsx, name='stock-report-with-adjustments-xlsx'),
    path('stock-reconciliation/eod-value/today/', eod_value_reconciliation_today, name='eod-value-reconciliation-today'),
    path('stock-reconciliation/eod-value/today/update/', eod_value_reconciliation_update_today, name='eod-value-reconciliation-update-today'),
    path('stock-reconciliation/eod-value/today/confirm/', eod_value_reconciliation_confirm_today, name='eod-value-reconciliation-confirm-today'),

    # Opening Stock Baseline (for initial setup)
    path('stock-reconciliation/<uuid:reconciliation_id>/set-baseline/', set_opening_stock_baseline, name='stock-reconciliation-set-baseline'),
    path('stock-reconciliation/<uuid:reconciliation_id>/set-baseline-bulk/', set_bulk_opening_stock_baseline, name='stock-reconciliation-set-baseline-bulk'),
    path('stock-reconciliation/<uuid:reconciliation_id>/clear-baseline/', clear_opening_stock_baseline, name='stock-reconciliation-clear-baseline'),

    # Promotions
    path('promotions/', promotion_list_create, name='promotion-list-create'),
    path('promotions/<int:pk>/', promotion_detail, name='promotion-detail'),

    # Locations
    path('locations/', location_list_create, name='location-list-create'),
    path('locations/set-mine/', set_user_location, name='location-set-mine'),
    path('locations/<uuid:location_id>/', location_detail, name='location-detail'),
    path('locations/<uuid:location_id>/close/', location_close, name='location-close'),

    # Merchandise
    path('merchandise/catalog/', merchandise_catalog, name='merchandise-catalog'),
    path('merchandise/catalog/<int:item_id>/', merchandise_catalog_item_detail, name='merchandise-catalog-item-detail'),
    path('merchandise/orders/pending/', merchandise_pending_orders, name='merchandise-pending-orders'),
    path('merchandise/orders/<int:order_id>/', merchandise_order_detail, name='merchandise-order-detail'),
    path('merchandise/orders/<int:order_id>/fulfill/', merchandise_fulfill_order, name='merchandise-fulfill-order'),
    path('merchandise/stock/', merchandise_stock_list, name='merchandise-stock-list'),
    path('merchandise/stock/adjust/', merchandise_adjust_stock, name='merchandise-stock-adjust'),
    path('merchandise/stock/movements/', merchandise_stock_movements, name='merchandise-stock-movements'),
    path('reports/merchandise/', merchandise_daily_report, name='merchandise-daily-report'),
]
