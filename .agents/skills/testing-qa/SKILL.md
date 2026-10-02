---
name: testing-qa
description: Backend testing patterns and quality assurance for this project. Use when writing or modifying Django test cases, creating test fixtures, running test suites, checking coverage, or validating business logic across the full system. Also use when testing API endpoints, service layer methods, state machine transitions, permission boundaries, or data integrity.
metadata:
  domain: testing
  type: quality
---

## Test Infrastructure

- **Framework**: Django `TestCase` + DRF `APIClient`. All tests in `backend/payments/tests/`.
- **Runner**: `docker-compose exec web python manage.py test payments.tests.<module>`
- **27 existing test files**, ranging from 1K to 87K lines.
- **Key test files** (by coverage value):
  - `test_stock_reconciliation_sales.py` (87K) — Most comprehensive. Full daily workflows with reversals.
  - `test_combined_order_service.py` (52K) — Combined order state machine.
  - `test_reconciliation_v2_service.py` (41K) — X/Y/Z formula calculations.
  - `test_stock_adjustment_item.py` (32K) — Stock adjustment auto-calc logic.
  - `test_stock_report_service.py` (28K) — Stock report generation.
  - `test_stock_reconciliation_sales.py` (87K) — The golden test file for end-to-end daily workflows.

## Test Patterns

### Structure Pattern
```python
from rest_framework.test import APITestCase, APIClient
from django.urls import reverse

class TestSomething(APITestCase):
    def setUp(self):
        self.client = APIClient()
        # Create users, products, gateways, etc.
        self.admin = User.objects.create(username='admin', role='ADMIN')
        self.client.force_authenticate(user=self.admin)

    def test_happy_path(self):
        """Description of what's being tested"""
        url = reverse('endpoint-name')
        response = self.client.post(url, data={...}, format='json')
        self.assertEqual(response.status_code, 200)
```

### Mocking
- **Celery**: Tasks are called with `.delay()` — in tests, this means they run synchronously. Just call the task function directly: `process_raw_message(msg.id)`.
- **WebSocket broadcast**: Tests generally don't test WebSocket. If needed, mock `channel_layer.group_send`.
- **External services**: No external services — everything is in-process.

### Fixture Creation Pattern
```python
def setUp(self):
    # 1. Create gateway
    self.gateway = PaymentGateway.objects.create(
        name='Till 1', gateway_type='MPESA_TILL',
        gateway_number='555000'
    )
    # 2. Create product
    self.product = Product.objects.create(
        prod_code='PROD001', prod_name='Test Product',
        current_price=Decimal('500.00'), quantity=100
    )
    # 3. Create transaction with specific status
    self.tx = Transaction.objects.create(
        tx_id='TX001', amount=Decimal('1000.00'),
        gateway=self.gateway, status='NOT_PROCESSED'
    )
```

## Coverage Status (from SYSTEM_FUNCTIONALITY_TEST_MATRIX.md)

| Domain | Coverage Level | Key Files |
|--------|---------------|-----------|
| Auth & Permissions | Good | `test_api.py`, `test_device_auth.py` |
| Device & Message Ingest | Moderate | `test_rawmessage.py`, `test_device_auth.py` |
| Transaction Lifecycle | Good | `test_filters.py`, `test_transaction_locking.py` |
| Fulfillment (Single TX) | Strong | `test_fulfillment_api.py`, `test_fulfillment_service.py` |
| Combined Orders | Strong | `test_combined_order_service.py` |
| Manual Payments | Good | `test_manual_payments.py` |
| Products & Inventory | Good | `test_product_api.py`, `test_product_model.py` |
| Stock Take | Moderate | `test_today_logic_streams.py` (partial) |
| Stock Reconciliation | Strong | `test_stock_reconciliation_sales.py`, `test_stock_adjustment_item.py` |
| EOD Value Reconciliation | Good | `test_eod_value_reconciliation.py` |
| Reports | Moderate | `test_stock_report_service.py`, `test_reconciliation_v2_service.py` |
| Analytics | Good | `test_analytics_api.py` |
| Promotions | Weak | No dedicated test file |
| Locations | Weak | No dedicated test file |
| Merchandise | Weak | No dedicated test file |
| Admin Operations | Strong | `test_stock_reconciliation_sales.py`, `test_today_logic_streams.py` |

## Writing Effective Tests

1. **Happy path first**: Create realistic fixture chains (device → message → TX → activate → scan → complete → verify inventory changes)
2. **Then test validation rules**: Each `ValidationError` should have a test proving it fires
3. **Test reversals**: Every forward operation should have a reverse test verifying inventory returns to original state
4. **Test permission boundaries**: Cross-role negative tests (e.g., ISSUER calling Processor endpoints should get 403)
5. **Test edge cases**: Duplicate SMS, zero-quantity scans, amount boundary conditions, concurrent access

## Key Gotchas

- **`force_authenticate()` vs login**: Use `force_authenticate()` for unit tests (avoids password hashing overhead). Use actual login for integration tests that need token-based auth.
- **Product quantities**: Reset between tests. Always create products with explicit `quantity` — default is 0.
- **Transaction status**: Always set explicit status when creating test transactions — default may not match your test flow.
- **Atomic test isolation**: Django TestCase wraps each test in a transaction, so DB state is clean between tests. No manual cleanup needed.
- **URL names**: Use `reverse('url-name')` from `payments/urls.py`. Names are defined in `path(..., name='endpoint-name')`.
- **Decimal values**: Always use `Decimal()` for monetary values, not floats. Compare with `assertEqual` (string comparison works because Decimal.__str__ is well-defined).

## Anti-patterns

- Don't test with real external services — everything should be in-process.
- Don't write tests without assertions — `response.status_code == 200` without `assertEqual` is not a test.
- Don't test WebSocket broadcast in unit tests unless specifically testing the consumer.
- Don't leave `print()` / `logger.info()` in test code.
- Don't create monolithic test methods — each test should verify one behavior.
- Don't forget to test both the happy path AND the error cases.
