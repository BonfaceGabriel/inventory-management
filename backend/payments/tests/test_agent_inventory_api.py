from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from payments.models import MerchandiseCatalogItem, MerchandiseOrder, MerchandiseOrderLine, MerchandiseStock
from payments.tests.test_helpers import make_gateway, make_product, make_transaction


@override_settings(BI_AGENT_API_KEY="test-agent-secret", BRANCH_NAME="Kitengela")
class AgentInventoryAPITest(APITestCase):
    def setUp(self):
        self.url = reverse("agent-inventory")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer test-agent-secret")

    def get_report(self, view, day, **params):
        return self.client.get(self.url, {"view": view, "start_date": day, "end_date": day, **params})

    def test_merchandise_uses_fulfillment_date_and_snapshot_value(self):
        gateway = make_gateway("Merch", "MERCHANDISE", "merch")
        item = MerchandiseCatalogItem.objects.create(code="TS", name="T-shirt", unit_price=Decimal("500"))
        MerchandiseStock.objects.create(item=item, color="Red", quantity=3)
        MerchandiseStock.objects.create(item=item, color="Blue", quantity=2)
        # 21:00 UTC is midnight in Nairobi.
        fulfilled = datetime(2026, 6, 16, 21, tzinfo=UTC)
        for name, when, status, quantity in (
            ("today", fulfilled, "FULFILLED", 2),
            ("yesterday", fulfilled - timedelta(seconds=1), "FULFILLED", 1),
            ("pending", None, "PENDING", 8),
        ):
            transaction = make_transaction(tx_id=name, gateway=gateway, amount=Decimal("5000"))
            order = MerchandiseOrder.objects.create(
                transaction=transaction, gateway=gateway, status=status, fulfilled_at=when,
            )
            MerchandiseOrderLine.objects.create(
                order=order, item=item, quantity=quantity,
                unit_price_snapshot=Decimal("400"), line_total=Decimal(400 * quantity),
            )

        response = self.get_report("merchandise", "2026-06-17")
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(report["total_fulfilled"], "800.00")
        self.assertEqual(report["previous_day_total"], "400.00")
        self.assertEqual(report["items"], [{
            "code": "TS", "name": "T-shirt", "units_sold": 2, "sales_value": "800.00",
            "remaining_units": 5, "remaining_catalog_value": "2500.00",
        }])

    def test_stock_values_products_at_cost_and_paginates_all_alerts(self):
        for index in range(8):
            make_product(prod_code=f"empty-{index}", prod_name=f"Empty {index}", quantity=0)
        make_product(prod_code="low", prod_name="Low", quantity=3)
        make_product(prod_code="ok", prod_name="Ok", quantity=11)
        day = timezone.localdate()
        response = self.get_report("stock", day, page=2)
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(report["total_stock_value_at_cost"], "4200.00")
        self.assertEqual((report["out_of_stock_count"], report["low_stock_count"]), (8, 1))
        self.assertEqual(report["page_count"], 2)
        self.assertTrue(any(item["code"] == "low" and item["quantity"] == 3 for item in report["items"]))
        self.assertEqual(self.get_report("stock", day - timedelta(days=1)).status_code, 400)
        self.client.credentials()
        self.assertEqual(self.get_report("stock", day).status_code, 401)
