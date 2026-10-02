---
name: fulfillment-orders
description: Transaction fulfillment, combined orders, registration kits, and promotions workflow for this project. Use when working with the issuance lifecycle (activate → scan → complete/cancel), combined order state machine, registration kit issuance, promotion auto-apply logic, status transitions, and reversals.
metadata:
  domain: orders
  type: workflow
---

## Transaction State Machine

```
NOT_PROCESSED ──┬──→ PROCESSING ──┬──→ PARTIALLY_FULFILLED ──┬──→ FULFILLED
                │                 │                           │
                ├──→ CANCELLED    ├──→ COMBINED_FULFILLED     ├──→ CANCELLED
                │                 ├──→ FULFILLED              ├──→ PROCESSING (revert)
                │                 └──→ CANCELLED              └──→ COMBINED_FULFILLED
                └──→ COMBINED_FULFILLED
```

- **Locked states**: `FULFILLED` and `CANCELLED` are terminal — no transitions allowed.
- **`COMBINED_FULFILLED`**: Child transaction inside a combined order. The parent transaction tracks the actual fulfillment state.
- **Enforced by**: `Transaction.can_transition_to()` — never modify status without validation unless using `skip_validation=True`.

## Fulfillment Workflow (Single Transaction)

1. **Processor** marks transaction as `PROCESSING` (PUT to `/transactions/<id>/`)
2. **Issuer** calls `activate_issuance` — creates issuance lock per location, saves `status_before_activation`
3. **Issuer** scans products — `scan_barcode` with SKU/prod_code/barcode input, creates `TransactionLineItem`
4. **Issuer** completes — `complete_issuance` → deducts inventory, creates `InventoryMovement(SALE)`, sets status to `FULFILLED` or `PARTIALLY_FULFILLED`
5. **Cancel** — `cancel_issuance` removes all non-deducted line items, no inventory impact, restores previous status

## Combined Order State Machine

```
PENDING ──→ IN_PROGRESS ──→ PARTIALLY_FULFILLED ──→ FULFILLED
   │             │                  │
   └──→ CANCELLED                  └──→ CANCELLED
```

- **Creation**: `CombinedOrderService.create_combined_order()` — merges 2+ transactions (must be `NOT_PROCESSED` or `PARTIALLY_FULFILLED`). Creates parent transaction. Child transactions become `COMBINED_FULFILLED`.
- **Staged scanning**: `scan_product_to_combined_order_staged()` → creates `CombinedOrderLineItem` (no inventory deduct yet). Can be added to an active combined order.
- **Complete**: `complete_combined_order()` → deducts ALL line items from inventory, sets all children to `COMBINED_FULFILLED`, parent to `FULFILLED`.
- **Cancel**: `cancel_combined_order()` → returns ALL deducted inventory, restores children to previous status.
- **Revert**: `revert_combined_order()` → full undo including deleting the combined order itself. Restores children exactly.
- **Auto-fulfillment tracking**: `base_amount_fulfilled` (accumulated from child transactions being added) + real-time recalculation via `recalculate_amount_fulfilled()`.

## Registration Kit Issuance

- **Cost**: KES 2900 per kit. PV must be ≥ 20 (`MINIMUM_PV_REQUIRED`).
- **Flow**: Mark transaction as `is_registration=True` → issue kit → scans bar codes → complete.
- **Auto-complete**: If transaction is registration + kit not yet issued when `complete_issuance` is called, it auto-issues the kit.
- **From partial**: `issue_registration_from_partial` — uses remaining balance to issue kit(s) from a `PARTIALLY_FULFILLED` transaction.
- **Unmark**: Only before kit is issued. Reverts to `NOT_PROCESSED`, clears all issuance state.

## Promotion Auto-Apply

- **Triggered**: After every `scan_barcode` and `remove_line_item` call.
- **Mechanism**: `PromotionService.apply_promotions()` evaluates all active promotions against non-deducted line items.
- **Bundle logic**: `bundle_count = floor(available_qty / min_qty)` for each required product. Fixed discount = KES × bundle_count. Percentage discount = % off unit cost.
- **Rollback**: On item removal, promotions are re-evaluated and prices may revert.

## Key Gotchas

- **Issuance lock**: Only ONE transaction can be in issuance per location. Checked in `FulfillmentService.activate_issuance()`.
- **Stock take blocks issuance**: If a stock take session is active (DRAFT) at the main location, issuance is blocked. Checked only for main shop.
- **`is_inventory_deducted` flag**: Line items have this boolean. Scanned items start as `False`. Only completed issuance sets it to `True`. Inventory movements only happen on completion.
- **Revert restrictions**:
  - `PARTIALLY_FULFILLED → PROCESSING`: Processor role, not in combined order, not time-locked (unless admin).
  - `PROCESSING → NOT_PROCESSED`: Must have no line items, not in issuance, not in combined order.
- **Combined order parent sync**: Parent transaction's `amount`, `amount_fulfilled`, and `status` mirror the combined order's totals. Must update both.

## Anti-patterns

- Don't allow two issuances at the same location — check with `Transaction.objects.filter(is_in_issuance=True, location=location)`.
- Don't skip promotion re-application after scan or removal.
- Don't forget to update `amount_paid` when updating `amount_fulfilled` (model save() keeps them in sync).
- Don't hardcode product codes — `REG_KIT_001` for registration kit is the one exception, but check it exists.
- Don't forget to broadcast transaction updates via WebSocket after status changes.
