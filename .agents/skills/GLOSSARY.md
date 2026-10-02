# Project Glossary

## Payment Terms
| Term | Meaning |
|---|---|
| M-PESA | Kenyan mobile money service; SMS message ingestion used (not API) |
| Till Number | M-PESA business till (settles to account balance) |
| Paybill | M-PESA paybill number (settles to account via statement) |
| PDQ | Point-of-sale card terminal (EFTPOS machine) |
| Settlement | Net amount after gateway fees credited to shop account |
| PV | Product Value (point/valuation on a Product); PV >= 20 unlocks registration kits |

## Transaction States
| Status | Meaning |
|---|---|
| NOT_PROCESSED | Initial state after SMS parse or manual payment |
| PROCESSING | Processor has started fulfillment |
| PARTIALLY_FULFILLED | Some line items fulfilled, others pending |
| FULFILLED | All items fully issued |
| COMBINED_FULFILLED | Fulfilled via combined (batch) order |
| CANCELLED | Order voided, never fulfilled |

## Inventory Terms
| Term | Meaning |
|---|---|
| EOD | End of Day value reconciliation (X - Y - Z = V formula) |
| PV | Product Value (points per unit); used for registration kit eligibility |
| SKU | Stock Keeping Unit (product code) |
| Opening Stock | Quantity at start of reconciliation period |
| Effective Opening | Opening stock minus expired/defective items |
| Replenished | Stock added via purchase orders during period |
| Closing Stock | Physical stock at end of period |
| Stock Take | Physical count session to verify system vs actual quantity |

## Roles & Locations
| Term | Meaning |
|---|---|
| ADMIN | Full system access |
| PROCESSOR | Transactions, reports, manual payments |
| ISSUER | Fulfillment, scanning, stock takes |
| Main Shop | Primary physical retail location (full reconciliation) |
| Field Location | Remote/outpost (limited stock operations) |
| X-Location-ID | HTTP header for location-scoped operations |

## Merchandise Items
Non-inventory goods (e.g., SIM cards, accessories). Tracked in `MerchandiseCatalogItem` / `MerchandiseStock`, separate from main inventory in `Product`.
