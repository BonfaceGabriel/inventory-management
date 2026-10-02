# Inventory Reconciliation Reference

## Stock Reconciliation Formula
```
Effective Opening + Replenished + Added - Deducted = Closing + Sales + Adjustments
Where:
  Effective Opening = Opening Stock - Expired/Defective
  Adjustments = Stock Take variance corrections
  Sales = quantity sold during period
```

## EOD Value Reconciliation (X - Y - Z = V)
```
X = Opening Stock Value + Purchases during day
Y = Sales Revenue (from transactions)
Z = Adjustments (stock take variances, write-offs, etc.)
V = Expected Closing Stock Value
   = X - Y - Z
```

## Inventory Movement Types
| Movement | Direction | Triggered By |
|---|---|---|
| SALE | Out | Transaction fulfillment (complete-issuance) |
| STOCK_TAKE | In/Out | StockTakeSession completion |
| ADJUSTMENT | In/Out | DailyStockReconciliation adjust/confirm |
| RETURN | In | Manual return processing |
| PURCHASE | In | Stock replenishment (manual) |

## Stock Take Workflow
```
Create Session (DRAFT) → Scan Products (add StockTakeItem) → Complete → System:
  1. Calculates variance (system_qty - counted_qty)
  2. Creates InventoryMovement records
  3. Updates Product.quantity
→ Cancel: discards session without changes
```

## Key Constraints
- Only one ACTIVE stock take session per location at a time
- Stock take blocks issuance for same-location products
- `quantity_replenished` on ProductLine is read-only (set via baseline)
- Main shop locations use `DailyStockReconciliation`; field locations may skip
- Opening stock baseline can be manually overridden via `set-baseline/` endpoints
