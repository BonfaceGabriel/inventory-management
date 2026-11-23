from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from payments.models import CombinedOrder, CombinedOrderLineItem, CombinedOrderTransaction, InventoryMovement, MerchandiseOrder, Transaction
from payments.tests.test_helpers import make_combined_order, make_gateway, make_line_item, make_product, make_transaction


@override_settings(BI_AGENT_API_KEY="test-agent-secret", BRANCH_NAME="Kitengela")
class AgentSalesAPITest(APITestCase):
    def setUp(self):
        self.url = reverse("agent-sales")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer test-agent-secret")
        self.till = make_gateway("Sales Till", "MPESA_TILL", "sales-till")
        self.merch = make_gateway("Sales Merchandise", "MERCHANDISE", "sales-merch")
        zone = ZoneInfo("Africa/Nairobi")
        self.earlier = datetime(2026, 6, 15, 11, tzinfo=zone)
        self.later = datetime(2026, 6, 16, 11, tzinfo=zone)

    def transaction(self, name, amount, when, status="PARTIALLY_FULFILLED", gateway=None):
        transaction = make_transaction(
            tx_id=name, amount=Decimal("2500.00"), amount_fulfilled=Decimal(amount),
            status=status, gateway=gateway or self.till,
        )
        Transaction.objects.filter(pk=transaction.pk).update(timestamp=self.earlier, completed_at=when)
        return transaction

    def get_sales(self, start="2026-06-16", end="2026-06-16"):
        return self.client.get(self.url, {"start_date": start, "end_date": end})

    def test_reads_fulfilled_value_and_excludes_merchandise_and_pending_items(self):
        partial = self.transaction("FULFILLED-LATER", "50.75", self.later)
        Transaction.objects.filter(pk=partial.pk).update(
            is_in_issuance=True, amount_fulfilled=Decimal("77.00"),
            amount_fulfilled_before_activation=Decimal("50.75"),
        )
        self.transaction("MERCH-FULFILLED", "900.00", self.later, gateway=self.merch)
        legacy_merch = self.transaction("MERCH-STILL-ON-TILL", "500.00", self.later)
        MerchandiseOrder.objects.create(
            transaction=legacy_merch, gateway=self.merch,
            status=MerchandiseOrder.Status.FULFILLED, fulfilled_at=self.later,
        )
        self.transaction("SCANS-ONLY", "100.00", None, status="PROCESSING")
        response = self.get_sales()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_sales"], "50.75")
        self.assertEqual(response.json()["branch"], {"id": "kitengela", "name": "Kitengela"})
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_keeps_earlier_partial_and_new_combined_fulfillment_in_their_own_periods(self):
        original = self.transaction("EARLIER-CHILD", "800.00", self.earlier, status="COMBINED_FULFILLED")
        second = self.transaction("TODAY-CHILD", "0.00", None, status="COMBINED_FULFILLED")
        parent = self.transaction("SYNTHETIC-PARENT", "2000.00", self.later)
        order = CombinedOrder.objects.create(
            combined_order_id="CROSS-DAY", parent_transaction=parent, created_by="test",
            total_amount=Decimal("2000.00"), status=CombinedOrder.Status.FULFILLED,
            base_amount_fulfilled=Decimal("800.00"), amount_fulfilled=Decimal("2000.00"),
            fulfilled_at=self.later,
        )
        CombinedOrderTransaction.objects.create(combined_order=order, transaction=original)
        CombinedOrderTransaction.objects.create(combined_order=order, transaction=second)
        self.assertEqual(self.get_sales("2026-06-15", "2026-06-15").json()["total_sales"], "800.00")
        self.assertEqual(self.get_sales().json()["total_sales"], "1200.00")
        self.assertEqual(self.get_sales("2026-06-15").json()["total_sales"], "2000.00")

    def test_withholds_cumulative_amount_if_one_order_spans_the_requested_boundary(self):
        self.transaction("MULTI-SESSION", "2000.00", self.later)
        product = make_product()
        for when in (self.earlier, self.later):
            movement = InventoryMovement.objects.create(
                movement_type=InventoryMovement.MovementType.SALE, product=product,
                quantity_before=10, quantity_after=9, quantity_change=-1,
                reference="Transaction MULTI-SESSION",
            )
            InventoryMovement.objects.filter(pk=movement.pk).update(created_at=when)
        response = self.get_sales()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"code": "incomplete_fulfillment_history"})
        self.assertEqual(self.get_sales("2026-06-15").json()["total_sales"], "2000.00")
        response = self.client.get(self.url, {
            "start_date": "2026-06-15", "end_date": "2026-06-16", "daily": "true",
        })
        self.assertEqual(response.status_code, 409)

    def test_daily_sales_places_fulfillment_on_its_date_and_returns_zero_days(self):
        self.transaction("OLDER-PAYMENT", "800.25", self.later)
        response = self.client.get(self.url, {
            "start_date": "2026-06-15", "end_date": "2026-06-16", "daily": "true",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["daily"], [
            {"date": "2026-06-15", "total_sales": "0.00"},
            {"date": "2026-06-16", "total_sales": "800.25"},
        ])

    def test_products_rank_by_units_and_exclude_pending_scans(self):
        transaction = self.transaction("PRODUCTS", "800.00", self.later)
        popular = make_product(prod_code="POPULAR", prod_name="Popular", price=Decimal("100.00"))
        premium = make_product(prod_code="PREMIUM", prod_name="Premium", price=Decimal("500.00"))
        for product, quantity in ((popular, 3), (premium, 1)):
            item = make_line_item(transaction, product, quantity=quantity)
            item.is_inventory_deducted = True
            item.save(update_fields=["is_inventory_deducted"])
        pending = make_product(prod_code="PENDING", prod_name="Pending")
        make_line_item(transaction, pending, quantity=10)
        response = self.client.get(reverse("agent-products"), {
            "start_date": "2026-06-16", "end_date": "2026-06-16",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["products"], [
            {"name": "Popular", "code": "POPULAR", "units_sold": 3, "sales_value": "300.00"},
            {"name": "Premium", "code": "PREMIUM", "units_sold": 1, "sales_value": "500.00"},
        ])

    def test_product_ranking_counts_original_items_once_when_copied_to_combined_order(self):
        old = self.transaction("OLDER-ITEMS", "800.00", self.earlier)
        today = self.transaction("NEW-PAYMENT", "0.00", None, status="NOT_PROCESSED")
        original = make_product(prod_code="ORIGINAL", price=Decimal("200.00"))
        new = make_product(prod_code="NEW-ITEM", price=Decimal("600.00"))
        item = make_line_item(old, original, quantity=4)
        item.is_inventory_deducted = True
        item.save(update_fields=["is_inventory_deducted"])
        order = make_combined_order([old, today])
        CombinedOrder.objects.filter(pk=order.pk).update(
            amount_fulfilled=Decimal("2000.00"), fulfilled_at=self.later, updated_at=self.later,
        )
        CombinedOrderLineItem.objects.create(
            combined_order=order, product=new, scanned_prod_code=new.prod_code,
            scanned_prod_name=new.prod_name, scanned_sku=new.sku, scanned_sku_name=new.sku_name,
            scanned_price=Decimal("600.00"), quantity=2, line_total=Decimal("1200.00"),
            is_inventory_deducted=True,
        )
        response = self.client.get(reverse("agent-products"), {
            "start_date": "2026-06-15", "end_date": "2026-06-16",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(row["code"], row["units_sold"], row["sales_value"]) for row in response.json()["products"]],
            [("ORIGINAL", 4, "800.00"), ("NEW-ITEM", 2, "1200.00")],
        )

    def test_nairobi_day_uses_recorded_completion_and_empty_day_is_zero(self):
        self.transaction("BEFORE-NAIROBI-MIDNIGHT", "100.00", datetime(2026, 6, 15, 20, 59, 59, tzinfo=UTC))
        self.assertEqual(self.get_sales().json()["total_sales"], "0.00")
        self.transaction("ON-NAIROBI-MIDNIGHT", "30.00", datetime(2026, 6, 15, 21, tzinfo=UTC))
        self.assertEqual(self.get_sales().json()["total_sales"], "30.00")

    def test_endpoint_requires_the_agent_token_and_a_valid_range(self):
        self.assertEqual(self.get_sales("2026-06-17").status_code, 400)
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)
        self.client.credentials()
        self.assertEqual(self.get_sales().status_code, 401)
