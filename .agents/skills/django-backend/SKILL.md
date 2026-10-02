---
name: django-backend
description: Django backend architecture and development for this project. Use when modifying models, views, serializers, services, URLs, permissions, filters, management commands, or migration files. Also use when working with the service layer pattern, database queries, or API view logic.
metadata:
  domain: backend
  framework: django-drf
---

## Project Conventions

- **Service layer pattern**: `views.py → services/*.py → models.py`. Views handle HTTP; services hold business logic; models are data + validation.
- **21 service files** in `payments/services/`. Services are classes with `@staticmethod` methods, never mixins. Return dicts or model instances, not HTTP responses.
- **Views** in `payments/views.py` (5072 lines). Use `@api_view` decorators for simple endpoints, `generics.*` or `APIView` for CRUD.
- **Serializers** in `payments/serializers.py` (1806 lines). Use DRF serializers with `Meta` class. Keep read vs write serializers separate (e.g. `ProductSerializer` vs `ProductListSerializer`).
- **Auth**: Dual auth — JWT (simplejwt) for web users, API key (`X-API-KEY` header) for Android devices. Auth backends in `payments/auth.py`.
- **Permissions** in `payments/permissions.py`. 7 classes: `IsAdmin`, `IsProcessor`, `IsIssuer`, `IsAdminOrProcessor`, `IsAdminOrIssuer`, `IsDeviceOrAuthenticated`, `IsDeviceOrProcessor`, `IsDeviceOrIssuer`, `IsAuthenticatedUser`.

## Key Gotchas

- **Location resolution**: Use `get_request_location(request)` helper (not direct user lookup). Priority: `X-Location-ID` header → `user.current_location` → Main Shop singleton.
- **Concurrent safety**: Always use `select_for_update()` inside `db_transaction.atomic()` blocks when modifying financial records or inventory.
- **Transaction state machine**: Enforced in `Transaction.can_transition_to()`. Never change status directly without going through this validation unless you pass `skip_validation=True`.
- **`skip_validation=True`**: Only use when you explicitly need to bypass state machine rules (e.g., reverting during line item removal). Document why.
- **Dual auth in views**: Most views need `authentication_classes = [DeviceAPIKeyAuthentication, JWTAuthentication]`. Check `hasattr(request.user, 'role')` to distinguish JWT users from device auth.
- **UUID primary keys**: `Location`, `Device`, `DailyStockReconciliation`, `ManualPayment` use UUID PKs. `Transaction`, `Product`, `CombinedOrder` use integer/auto PKs. Check before writing URL patterns.
- **Timezone**: Always `Africa/Nairobi`. Use `timezone.localtime(timezone.now())` not `datetime.now()`. Use `timezone.localdate()` for date comparisons.
- **WebSocket broadcast**: After creating/updating transactions, broadcast via `_broadcast_transaction_created()` in tasks.py. Pattern: serialize → JSON-safe convert → `channel_layer.group_send('transactions', {...})`.

## File Map

```
backend/
├── payments/
│   ├── models.py        # 28 models, 2553 lines
│   ├── views.py         # 5072 lines — ALL API views
│   ├── serializers.py   # 1806 lines
│   ├── urls.py          # 195 lines — ALL routes under /api/v1/
│   ├── permissions.py   # 229 lines — role/device permission classes
│   ├── filters.py       # DRF FilterSet definitions
│   ├── auth.py          # DeviceAPIKeyAuthentication, SimpleAPIKeyAuthentication
│   ├── parsers.py       # M-PESA SMS regex parsers
│   ├── tasks.py         # Celery: process_raw_message, generate_daily_report
│   ├── consumers.py     # Django Channels WebSocket consumer
│   ├── routing.py       # WebSocket URL routing
│   ├── services/        # 21 service files — ALL business logic
│   ├── management/commands/  # ~25 management commands
│   └── tests/           # 27 test files
├── management/
│   ├── settings.py      # Django settings
│   ├── urls.py          # Root URL conf
│   ├── celery.py        # Celery app config
│   └── asgi.py          # Daphne ASGI config
└── utils/
    ├── constants.py     # STATUS_COLORS, STATUS_ICONS
    └── exceptions.py    # TransactionLockedException, InvalidStatusTransitionError, etc.
```

## Model Reference (28 models)

Core: `Location(UUID)`, `User(AbstractUser)`, `PaymentGateway`, `Device(UUID)`, `RawMessage`
Transactions: `Transaction`, `ManualPayment(UUID)`, `TransactionLineItem`
Products: `ProductLine`, `Product`, `InventoryMovement`
Combined Orders: `CombinedOrder`, `CombinedOrderTransaction`, `CombinedOrderLineItem`
Stock Take: `StockTakeSession`, `StockTakeItem`
Reconciliation: `DailyStockReconciliation(UUID)`, `StockAdjustmentItem(UUID)`, `EndOfDayValueReconciliation`
Merchandise: `MerchandiseCatalogItem`, `MerchandiseCatalogOption`, `MerchandiseOrder`, `MerchandiseOrderLine`, `MerchandiseStock`, `MerchandiseStockMovement`
Other: `Promotion`, `PromotionProduct`, `GeneratedReport`

## Patterns

- **Filtering**: Use `DjangoFilterBackend` + `filters.SearchFilter` + `filters.OrderingFilter` combo on list views.
- **Pagination**: DRF default pagination. Use `page` and `page_size` query params.
- **Error handling**: Views return `Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)`. Services raise `ValidationError` or `django.core.exceptions.ValidationError`.
- **Atomic operations**: Wrap mutating service calls in `with db_transaction.atomic():`. Use `select_for_update()` on any row being modified.
- **Management commands**: Created in `payments/management/commands/`. Use Django's `BaseCommand` pattern.

## Anti-patterns

- Don't put business logic in views — use services.
- Don't skip `can_transition_to()` unless `skip_validation=True` and you've documented why.
- Don't use raw SQL where the ORM suffices.
- Don't forget `select_related()`/`prefetch_related()` on querysets in list views.
- Don't hardcode timezone offsets — always use `pytz`/`zoneinfo` with `Africa/Nairobi`.
- Don't forget `on_delete` on ForeignKey fields.
