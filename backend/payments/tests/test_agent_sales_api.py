from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from payments.models import CombinedOrder, CombinedOrderTransaction, InventoryMovement, MerchandiseOrder, Transaction
from payments.tests.test_helpers import make_gateway, make_product, make_transaction


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
