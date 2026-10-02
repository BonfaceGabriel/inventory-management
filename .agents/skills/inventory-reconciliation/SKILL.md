---
name: inventory-reconciliation
description: Inventory stock management, stock taking, daily reconciliation, and end-of-day value reconciliation for this project. Use when working with stock take sessions, DailyStockReconciliation adjustments, StockAdjustmentItem calculations, opening/closing stock baselines, the X-Y-Z formula, inventory movements, and stock report generation with adjustments.
metadata:
  domain: inventory
  type: workflow
---

## Stock Take Workflow

1. **Create session**: `StockTakeService.create_session()` → DRAFT status. Blocks issuance at main location.
2. **Scan products**: `scan_product()` records `quantity_before` (from Product.quantity at scan time) + `quantity_scanned`.
3. **Complete**: `complete_session()` → computes `quantity_after = quantity_before + (quantity_scanned - quantity_before)` = `quantity_scanned`. Creates `InventoryMovement(ADJUSTMENT)` for each item with quantity change. Sets session to COMPLETED.
4. **Cancel**: DRAFT → CANCELLED. No inventory impact.
5. **Kit-only completion**: Can complete a session with only `kit_quantity` set and no scanned products.

## Stock Reconciliation Formula

```
opening_stock = previous day's closing_stock (DailyStockReconciliation)
effective_opening_stock = opening_stock_baseline ?? opening_stock  (baseline overrides if set)
quantity_replenished = AUTO-CALCULATED from completed stock take sessions on this date (read-only)
quantity_added = manual input (found items, corrections)
quantity_deducted = manual input (damaged, stolen, shrinkage)
closing_stock = current Product.quantity  (DRAFT) OR formula result (CONFIRMED)
sales = (effective_opening + replenished + added - deducted) - closing

Expected Consignment = effective_opening + replenished + added - deducted - closing - sales
```

- **DRAFT refresh**: When viewing a DRAFT reconciliation, `quantity_replenished` and `closing_stock` are auto-refreshed from latest stock take and product data.
- **Baseline**: Admin-only. Overrides `opening_stock` for initial system setup. Can be set per-product or bulk (from current inventory).

## Reconciliation Workflow

1. **Create/Get**: `ReconciliationWorkflowService.get_or_create_reconciliation(date)` → creates DRAFT with StockAdjustmentItems for all active products.
2. **Adjust**: `update_adjustment()` — set `quantity_added` and `quantity_deducted` per product. Bulk update also supported.
3. **Confirm**: `confirm_reconciliation()` — applies net changes to `Product.quantity`, creates `InventoryMovement(ADJUSTMENT)` records, locks to CONFIRMED.
4. **Revert**: Admin-only. Reverses all inventory movements, sets back to DRAFT. Creates audit trail movements with `REVERT:` prefix.
5. **Cancel**: Can only cancel DRAFT. Hard delete (cascade removes adjustments).

## Transaction Reconciliation (X + Y = 0)

Implemented in `payments/services/reconciliation_v2_service.py`. This is the
per-day cash reconciliation shown on the Reports page.

```
X = Mpesa_Paybill - Unused + PDQ + Previous - Sales
Y = Till - Credit - KITS
X + Y should = 0
```

- **Mpesa_Paybill**: paybill received today.
- **Unused**: unfulfilled paybill **and PDQ** received today (`NOT_PROCESSED` or
  `PROCESSING`). Both are cash-in, so both must be backed out until fulfilled.
- **PDQ**: PDQ received today.
- **Previous**: paybill from a previous date that became active today.
- **Till**: till fulfilled today.
- **Credit**: remaining balances on partially fulfilled paybill/PDQ from today.
- **KITS**: `registration_kit_quantity * 200`.
- **Sales**: total fulfilled today at distributor price (kit margin excluded).

**`Previous` is deliberately NOT in Y.** It is a paybill-source term already
added in X; subtracting it in Y too would double-count it. Do not "fix" Y to
match an old docstring.

**Merchandise is excluded from every term, including cash-in.** It is matched by
the `MerchandiseOrder` link (`merchandise_order__isnull=False`), **not** by
gateway type — a merchandise payment keeps whatever gateway its money arrived on
(e.g. Till Products), so a gateway-type filter misses it and leaks it into the
books. If you add a new term to this service, exclude merchandise in it.

`raw_breakdown` (from `get_raw_gateway_totals`) is the untouched per-gateway
cash-in tally, used to tie out against the M-PESA statement. It is **not** an
input to X or Y, but it does apply the merchandise exclusion.

## End-of-Day Value Reconciliation (X - Y - Z = V)

Model `payments/models.py:EndOfDayValueReconciliation`. This is a separate
**stock-value** reconciliation, unrelated to the transaction reconciliation
above.

```
X = opening_stock_value + replenished_value - sales_value
Y = stock_value + bk_stock + duplicated
Z = hq + kitengela + kitui + nakuru
V = X - Y - Z   (expected to be <= 100)
```

- X values are system-derived from `StockAdjustmentItem` at `Product.cost_price`.
- Y and Z are manual inputs. Y and Z default to 0, so a fresh DRAFT shows
  `V = X` until someone fills the physical counts in.
- **Gotcha**: `is_within_threshold` is `v_value <= 100`, which passes large
  *negative* V as well. A one-sided check — do not treat "within threshold" as
  proof of balance.

## Inventory Movement Types

| Type | Code | Direction |
|------|------|-----------|
| Sale | `SALE` | Out (deduction) |
| Stock Take | `STOCK_TAKE` | Either (correction) |
| Adjustment | `ADJUSTMENT` | Either (reconciliation) |
| Return | `RETURN` | In (reversal) |
| Purchase | `PURCHASE` | In (restock) |

## Key Gotchas

- **Stock take blocks issuance**: Only at main shop location (checks `issuing_location.is_main`). Field locations can have stock take and issuance simultaneously.
- **`quantity_replenished` is READ-ONLY**: Auto-calculated from COMPLETED stock take sessions. Cannot be manually set.
- **`closing_stock` for DRAFT**: Uses current `Product.quantity`. For CONFIRMED, stores the formula result snapshot.
- **Baseline vs calculated**: If `opening_stock_baseline` is set, it overrides `opening_stock` from previous day's reconciliation. This is for initial setup only.
- **Concurrent session**: Only ONE DRAFT stock take session allowed at a time. Check via `StockTakeService.get_active_session()`.
- **EOD scoping**: Value reconciliation is main-shop only. Field location transactions are not included in the X/Y/Z calculation.

## Anti-patterns

- Don't allow stock take completion while issuance is active — block in `complete_session()`.
- Don't manually set `quantity_replenished` — it's auto-calculated from stock take sessions.
- Don't confirm a reconciliation that has unaccounted discrepancies.
- Don't forget to refresh DRAFT reconciliation auto-fields before display (the `get_stock_reconciliation` endpoint does this).
- Don't mix field location stock takes with main shop reconciliation.
- Don't edit a CONFIRMED reconciliation — use the revert → edit → reconfirm flow (admin only for revert).
