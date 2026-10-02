# Payment Systems Reference

## Gateway Types
| Type | Code | Settlement | Notes |
|---|---|---|---|
| M-PESA Till | `MPESA_TILL` | Gross (no fee calc) | Business till number |
| M-PESA Paybill | `MPESA_PAYBILL` | Net after fee | Account number sent via SMS |
| PDQ | `PDQ` | Net after percentage fee | Card terminal |
| Bank Transfer | `BANK_TRANSFER` | Gross | Manual entry |
| Cash | `CASH` | Gross | Manual entry |

## SMS Parsing Flow
```
Android SMS App → HTTP POST /api/v1/messages/ (RawMessage) → Celery (process_raw_message)
→ Regex match (parsers.py) → Create Transaction (NOT_PROCESSED) or attach to existing
→ WebSocket broadcast /ws/transactions/
```

## Payment Gateway -> Transaction mapping
Each Device is linked to one PaymentGateway. When a raw message arrives from a Device:
- The gateway for the transaction is set to the device's gateway
- Merchandise messages auto-create with gateway set to the device's gateway
- Manual payments allow choosing the gateway

## Device Auth Flow
```
Register: POST /devices/register/ → returns api_key (UUID)
Each request: X-API-KEY header → DeviceLookupAuthentication → sets request.device
```
