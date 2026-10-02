# Fulfillment & Orders Reference

## Transaction State Machine
```
NOT_PROCESSED ──┬──> PROCESSING ──┬──> PARTIALLY_FULFILLED ──┬──> PROCESSING (revert)
                │                 │                          ├──> FULFILLED
                ├──> COMBINED_FULFILLED                      └──> COMBINED_FULFILLED
                └──> CANCELLED                                    └──> CANCELLED
                                        │
                                  FULFILLED ──> CANCELLED (cancel-fulfilled endpoint)
                                  CANCELLED ──> locked (no transitions)
```

## Combined Order State Machine
```
PENDING ──> IN_PROGRESS ──┬──> PARTIALLY_FULFILLED ──┬──> IN_PROGRESS (revert)
                           │                          ├──> FULFILLED
                           ├──> FULFILLED              └──> CANCELLED
                           └──> CANCELLED
```

## Fulfillment Workflow
1. **Processor** marks transaction as PROCESSING (or creates combined order)
2. **Issuer** activates issuance → locks stock (select_for_update)
3. **Issuer** scans barcodes → creates TransactionLineItem / CombinedOrderLineItem
4. **Issuer** completes → marks FULFILLED, deducts inventory
5. **Reversal**: cancel-issuance → reverts to previous state (no inventory deduction reversal)

## Registration Kit Flow
- Eligibility: transaction total >= 2900 KES AND any product has PV >= 20
- Issued via `issue-registration-kit/` endpoint
- Products specifically marked as `is_registration_kit` in Product model
- Can also issue from PARTIALLY_FULFILLED state (`issue-registration-from-partial/`)

## Key Endpoints
```
POST   /transactions/<id>/activate-issuance/
POST   /transactions/<id>/scan-barcode/          { "barcode": "..." }
POST   /transactions/<id>/complete-issuance/
POST   /transactions/<id>/cancel-issuance/
POST   /transactions/<id>/revert-to-processing/
POST   /transactions/<id>/revert-to-not-processed/
POST   /transactions/<id>/cancel-fulfilled/
POST   /transactions/<id>/issue-registration-kit/
DELETE /transactions/<id>/line-items/<line_item_id>/
GET    /transactions/current-issuance/
```
Combined orders follow same pattern under `/combined-orders/<id>/...`.
