# Django Backend Reference

## URL Routes (base: `/api/v1/`)
```
Auth:       auth/login/ auth/refresh/ auth/logout/ auth/profile/ auth/change-password/
Users:      users/ users/<pk>/
Devices:    devices/register/ devices/<uuid>/rotate_key/ devices/settings/
Gateways:   gateways/
Messages:   messages/

Transactions:
  transactions/  transactions/by-tx-id/<str>/  transactions/<int:pk>/
  transactions/<int>/issue-registration-kit/
  transactions/<int>/activate-issuance/  .../scan-barcode/  .../complete-issuance/
  transactions/<int>/cancel-issuance/  .../revert-to-processing/
  transactions/<int>/revert-to-not-processed/
  transactions/<int>/cancel-fulfilled/  .../cancel-registration/  .../delete/
  transactions/<int>/mark-registration/  .../unmark-registration/
  transactions/<int>/line-items/<int>/remove-line-item/
  transactions/current-issuance/

Combined Orders:
  combined-orders/  combined-orders/<str:combined_order_id>/
  combined-orders/<id>/add-transactions/ scan/ cancel/ cancel-issuance/
  combined-orders/<id>/revert/ activate/ scan-staged/ complete/
  combined-orders/<id>/line-items/<int>/  .../mark-registration/

Payments:     payments/manual/ payments/manual/list/ payments/manual/summary/

Products:     products/ products/<pk>/ products/search/ products/summary/
              products/lines/ products/lines/<pk>/

Stock Take:
  stock-take/sessions/  stock-take/sessions/active/  .../cancel-all/
  stock-take/sessions/<str>/  .../scan/  .../complete/  .../cancel/
  stock-take/sessions/<id>/items/<int>/  .../items/<int>/delete/
  stock-take/sessions/<id>/kit-quantity/

Reconciliation:
  stock-reconciliation/create/  stock-reconciliation/by-date/
  stock-reconciliation/<uuid>/  .../adjust/  .../adjust-bulk/  .../confirm/
  stock-reconciliation/<uuid>/cancel/  .../revert/  .../set-baseline/
  stock-reconciliation/<uuid>/set-baseline-bulk/  .../clear-baseline/
  stock-reconciliation/eod-value/today/  .../today/update/  .../today/confirm/

Reports:      reports/daily-reconciliation/ reports/daily-reconciliation-v2/
              reports/date-range-reconciliation/ reports/discrepancies/
              reports/daily-reconciliation/xlsx/ reports/date-range-reconciliation/xlsx/
              reports/stock/ reports/stock/xlsx/ reports/stock/historical/
              reports/stock/historical/xlsx/ reports/stock/with-adjustments/xlsx/
              reports/merchandise/
Exports:      exports/report/
Analytics:    analytics/overview/ analytics/revenue/ analytics/products/ analytics/merchandise/
Issuer:       issuer/queue/ issuer/queue/pending/ issuer/stats/
Promotions:   promotions/ promotions/<pk>/
Locations:    locations/ locations/<uuid>/ locations/<uuid>/close/ locations/set-mine/
Merchandise:
  merchandise/catalog/ merchandise/orders/pending/
  merchandise/orders/<int>/ merchandise/orders/<int>/fulfill/
  merchandise/stock/ merchandise/stock/adjust/ merchandise/stock/movements/
```

## Model Relationships
```
Location ──< User (current_location)
User ──< Device (user FK)
Device >── PaymentGateway
Transaction >── PaymentGateway
Transaction >── Location
Transaction >── User (activated_by, completed_by, cancelled_by, processed_by)
Transaction >── Transaction (duplicate_of self-ref)
RawMessage >── Device
RawMessage >── Transaction
ManualPayment >── Transaction, User
ProductLine >── ProductLine (parent_line self-ref)
Product >── ProductLine
TransactionLineItem >── Transaction, Product, User
InventoryMovement >── Product, User
StockTakeSession >── User (performed_by, completed_by)
StockTakeItem >── StockTakeSession, Product
CombinedOrder >── Transaction (parent_transaction one-to-one), User, Location
CombinedOrderTransaction >── CombinedOrder, Transaction
CombinedOrderLineItem >── CombinedOrder, Product, Transaction
DailyStockReconciliation >── User (created_by, confirmed_by)
StockAdjustmentItem >── DailyStockReconciliation, Product
EndOfDayValueReconciliation >── User (created_by, updated_by, confirmed_by)
Promotion >── User
PromotionProduct >── Promotion, Product
MerchandiseOrder >── Transaction (one-to-one), PaymentGateway, Device, User
MerchandiseOrderLine >── MerchandiseOrder, MerchandiseCatalogItem
MerchandiseStock >── MerchandiseCatalogItem
MerchandiseStockMovement >── MerchandiseStock, User
```

## Service Layer
```
views.py → services/*.py → models.py (+ serializers.py)
```
20 service files in `payments/services/`: admin, analytics, combined_order, eod_value_reconciliation, export, fulfillment, manual_payment, merchandise, order, pdf_report, promotion, reconciliation (x3), reconciliation_report, registration_kit, stock_report, stock_take, time_locking

## Permission Classes
`IsAdmin` `IsProcessor` `IsIssuer` `IsAdminOrProcessor` `IsAdminOrIssuer` `IsDeviceOrAuthenticated` `IsDeviceOrProcessor` `IsDeviceOrIssuer` `IsAuthenticatedUser`

## Management Commands (24)
`payments/management/commands/` — see SKILL.md section or browse the directory.
