# Testing & QA Reference

## Test Files by Domain

| Domain | File | Lines |
|---|---|---|
| Auth | `payments/tests/test_auth.py` | 148 |
| Devices | `payments/tests/test_devices.py` | 141 |
| API (Transaction) | `payments/tests/test_api.py` | 1517 |
| Fulfillment | `payments/tests/test_fulfillment.py` | 638 |
| Combined Orders | `payments/tests/test_combined_orders.py` | 864 |
| Manual Payments | `payments/tests/test_manual_payments.py` | 536 |
| Products | `payments/tests/test_products.py` | 235 |
| Stock Take | `payments/tests/test_stock_take.py` | 588 |
| Reconciliation | `payments/tests/test_reconciliation.py` | 1238 |
| EOD Value | `payments/tests/test_eod_value.py` | 368 |
| Reports | `payments/tests/test_reports.py` | 613 |
| Analytics | `payments/tests/test_analytics.py` | 472 |
| Promotions | `payments/tests/test_promotions.py` | 109 |
| Locations | `payments/tests/test_locations.py` | 139 |
| SMS Parsing | `payments/tests/test_parsers.py` | 144 |
| Merchandise | `payments/tests/test_merchandise.py` | 411 |
| Permissions | `payments/tests/test_permissions.py` | 95 |
| Inventory | `payments/tests/test_inventory_movements.py` | 163 |
| Exports | `payments/tests/test_exports.py` | 156 |
| Commands | `payments/tests/test_commands.py` | 150 |
| Admin | `payments/tests/test_admin_operations.py` | 315 |
| Raw Message | `payments/tests/test_raw_message.py` | 131 |
| PDF Report | `payments/tests/test_pdf_report.py` | 112 |
| Services (unit) | `payments/tests/test_services.py` | 667 |

## Running Tests
```bash
docker-compose exec web python manage.py test                           # all
docker-compose exec web python manage.py test payments.tests.test_api   # single file
docker-compose exec web python manage.py test payments.tests.test_api.TestClass  # class
docker-compose exec web python manage.py test payments.tests.test_api.TestClass.test_method  # single test
```

## Test Pattern
```python
class TestSomething(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = UserFactory()  # or User.objects.create_user(...)
        self.client.force_authenticate(user=self.user)
        # create test data...

    def test_happy_path(self):
        response = self.client.post('/api/v1/endpoint/', data={...})
        self.assertEqual(response.status_code, 200)
```

## Coverage Matrix (priority areas)
- **Strong**: Auth, Devices, API, Fulfillment, Combined Orders, Manual Payments
- **Medium**: Products, Stock Take, Reconciliation, EOD, Reports, Analytics
- **Weak**: Promotions, Locations, Merchandise — needs more tests
