---
name: payment-systems
description: M-PESA SMS payment integration, manual payment processing, and device authentication for this project. Use when working with SMS message ingestion, M-PESA parsing, payment gateways (Till/Paybill/PDQ/Bank/Cash), settlement calculations, device registration/API key auth, and the Celery async SMS processing pipeline.
metadata:
  domain: payments
  type: integration
---

## M-PESA SMS Parsing

- **Parser**: `payments/parsers.py` — regex patterns for multiple M-PESA message formats (send money, till number, paybill, reversal).
- **Confidence scoring**: Each parse returns `confidence` (0-1). Only transactions with `confidence > 0.6` are created. Low-confidence messages are logged but skipped.
- **Deduplication**: `unique_hash = sha256(f"{tx_id}|{amount}|{timestamp}")`. DB has unique constraint on `unique_hash`. Celery task catches `IntegrityError` and links the RawMessage to the existing transaction.
- **Internal sender filter**: Messages containing `7974481` (BF SUMA EAGLE SHOP LTD) are silently skipped — this is the shop's own internal M-PESA sending.

## Message Ingestion Flow

```
Android App → POST /api/v1/messages/ (X-API-KEY header)
  → RawMessage stored in DB
  → Celery: process_raw_message.delay(message_id)
    → parse_mpesa_sms(raw_text)
    → if confidence > 0.6:
        → create Transaction (using device's gateway)
        → for MERCHANDISE tills: auto-create MerchandiseOrder
        → broadcast via WebSocket
```

## Gateway Types

| Type | Gateway Number | Purpose | Settlement |
|------|---------------|---------|------------|
| `MPESA_TILL` | 555000 | Supplements till | Shop keeps all (NONE) |
| `MERCHANDISE` | 555001 | Merchandise till | Shop keeps all (NONE) |
| `MPESA_PAYBILL` | 654321 | Parent company paybill | All to parent (`PARENT_TAKES_ALL`) |
| `PDQ` | — | Card payments | Configurable |
| `BANK_TRANSFER` | — | Bank transfers | Configurable |
| `CASH` | — | Cash payments | Configurable |

- **Settlement types**: `NONE` (all to shop), `PARENT_TAKES_ALL`, `COST_MARKUP`, `PERCENTAGE` (with `settlement_percentage`), `CUSTOM`.
- **Paybill rule**: All Paybill transactions automatically go to parent company — this is hardcoded in `PaymentGateway.calculate_settlement()`.

## Device Authentication

- **Registration**: `POST /devices/register/` — Android sends `phone_number` + `gateway_id` → gets back plaintext API key (the only time it's visible). Key is stored as Django `make_password()` hash.
- **Auth header**: `X-API-KEY` (not Bearer). Two auth classes: `DeviceAPIKeyAuthentication` (full device lookup) and `SimpleAPIKeyAuthentication` (lightweight).
- **Device ↔ Gateway**: Every device must have a gateway. Cannot be cleared (API rejects empty `gateway_id`). Gateway determines which M-PESA messages this device processes.
- **Dual auth in views**: Most views support both device and JWT auth. Check `hasattr(request.user, 'role')` to distinguish: if True, it's a JWT user; if False, it's a device wrapper.

## Manual Payments

- **Service**: `ManualPaymentService.create_manual_payment()` in `services/manual_payment_service.py`.
- **Creates both**: A `Transaction` record (for unified reporting) + a `ManualPayment` record (with method details).
- **Payment methods**: PDQ, BANK_TRANSFER, CASH, CHEQUE, OTHER.
- **TX ID format**: Auto-generated based on method + payer + amount + date hash.
- **Reference required**: For PDQ and Bank Transfer, `reference_number` is mandatory.
- **Gateway resolution**: Method is mapped to the appropriate PaymentGateway (e.g., PDQ → PDQ gateway, CASH → CASH gateway).

## Key Gotchas

- **Device gateway is REQUIRED**: The Celery task uses `message.device.gateway` as the transaction's gateway. If device has no gateway, the message is skipped with a warning.
- **Merchandise SMS auto-order**: When an M-PESA message arrives on a MERCHANDISE-type gateway, `MerchandiseService.create_pending_order_for_transaction()` is called automatically. This creates a pending `MerchandiseOrder` that must be manually fulfilled.
- **Reversal messages**: M-PESA reversal SMS is parsed and creates a separate transaction. It receives a different `tx_id` from M-PESA. No automatic reversal linking exists.
- **Confidence threshold**: Messages with confidence ≤ 0.6 are logged and NOT processed. They remain as unprocessed `RawMessage` records.
- **Duplicate detection**: The `unique_hash` constraint prevents duplicate transactions. The Celery task catches the exception and links the duplicate message to the existing transaction.

## Anti-patterns

- Don't create transactions without a gateway — the model requires it and reconciliation depends on gateway grouping.
- Don't parse M-PESA messages synchronously — always go through Celery (`process_raw_message.delay()`).
- Don't expose the plaintext API key after initial registration (only returned once on POST).
- Don't assume all M-PESA messages are customer payments — filter out internal sends (7974481).
- Don't hardcode gateway IDs or numbers — they're configured in the database via Django admin.
