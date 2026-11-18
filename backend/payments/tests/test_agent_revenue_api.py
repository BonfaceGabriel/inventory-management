from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from payments.models import CombinedOrder, Transaction
from payments.tests.test_helpers import make_gateway, make_transaction


@override_settings(BI_AGENT_API_KEY="test-agent-secret", BRANCH_NAME="Kitengela")
class AgentRevenueAPITest(APITestCase):
    def setUp(self):
        self.url = reverse("agent-revenue")
        self.day = date(2026, 6, 15)
        self.params = {"start_date": "2026-06-15", "end_date": "2026-06-16"}
        self.client.credentials(HTTP_AUTHORIZATION="Bearer test-agent-secret")
        self.gateways = {
            "paybill": make_gateway("Agent Paybill", "MPESA_PAYBILL", "agent-paybill"),
            "pdq": make_gateway("Agent PDQ", "PDQ", "agent-pdq"),
            "till": make_gateway("Agent Till", "MPESA_TILL", "agent-till"),
            "merch": make_gateway("Agent Merchandise", "MERCHANDISE", "agent-merch"),
        }

    def receipt(self, name, amount, gateway="till", when=None, **kwargs):
        tx = make_transaction(
            tx_id=name, amount=Decimal(amount), gateway=self.gateways[gateway], **kwargs
        )
        when = when or datetime(2026, 6, 15, 12, tzinfo=ZoneInfo("Africa/Nairobi"))
        Transaction.objects.filter(pk=tx.pk).update(timestamp=when)
        return tx

    def test_token_is_required_and_scoped_to_new_api(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.url, self.params).status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer wrong-token")
        self.assertEqual(self.client.get(self.url, self.params).status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer test-agent-secret")
        self.assertNotEqual(
            self.client.get(reverse("inventory-branches")).status_code, 200
        )

    @override_settings(BI_AGENT_API_KEY="")
    def test_unconfigured_token_fails_closed(self):
        self.assertEqual(self.client.get(self.url, self.params).status_code, 401)

    def test_read_only_and_strict_date_validation(self):
        self.assertEqual(self.client.post(self.url, self.params).status_code, 405)
        for params in [
            {},
            {"start_date": "yesterday", "end_date": "2026-06-16"},
            {"start_date": "2026-06-16", "end_date": "2026-06-15"},
            {"start_date": "2024-01-01", "end_date": "2026-06-15"},
            {
                "start_date": timezone.localdate().isoformat(),
                "end_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
            },
        ]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 400)

    def test_receipt_totals_are_decimal_strings_and_zero_days_are_explicit(self):
        self.receipt("AGENT-P1", "10.10", "paybill")
        self.receipt("AGENT-P2", "0.20", "paybill")
        self.receipt("AGENT-D1", "20.30", "pdq")
        self.receipt("AGENT-T1", "30.40", "till")
        self.receipt("AGENT-M1", "999.99", "merch")
        before = Transaction.objects.count()
        response = self.client.get(self.url, self.params)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["branch"], {"id": "kitengela", "name": "Kitengela"})
        self.assertEqual(
            payload["totals"],
            {
                "paybill": "10.30",
                "pdq": "20.30",
                "till": "30.40",
                "total_revenue": "61.00",
                "transaction_count": 4,
            },
        )
        self.assertEqual(payload["daily"][1]["total_revenue"], "0.00")
        self.assertEqual(payload["daily"][1]["date"], "2026-06-16")
        self.assertEqual(Transaction.objects.count(), before)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_nairobi_boundaries_and_daily_buckets(self):
        # Nairobi midnight is 21:00 UTC on the preceding date.
        self.receipt(
            "BOUNDARY-BEFORE", "100", when=datetime(2026, 6, 14, 20, 59, 59, tzinfo=UTC)
        )
        self.receipt("BOUNDARY-START", "10", when=datetime(2026, 6, 14, 21, tzinfo=UTC))
        self.receipt("BOUNDARY-DAY2", "20", when=datetime(2026, 6, 15, 21, tzinfo=UTC))
        self.receipt("BOUNDARY-STOP", "100", when=datetime(2026, 6, 16, 21, tzinfo=UTC))
        payload = self.client.get(self.url, self.params).json()
        self.assertEqual(
            [day["total_revenue"] for day in payload["daily"]], ["10.00", "20.00"]
        )
        self.assertEqual(payload["totals"]["total_revenue"], "30.00")

    def test_internal_identity_is_exact_not_a_phone_substring(self):
        self.receipt("INTERNAL-PHONE", "100", sender_phone="7974481")
        self.receipt(
            "INTERNAL-NAME", "100", sender_name="7974481 - BF SUMA EAGLE SHOP LTD"
        )
        self.receipt("LEGITIMATE-PHONE", "25", sender_phone="254797448145")
        payload = self.client.get(self.url, self.params).json()
        self.assertEqual(payload["totals"]["total_revenue"], "25.00")

    def test_combined_parent_excluded_but_children_and_cancelled_receipts_count(self):
        parent = self.receipt("AGENT-PARENT", "500")
        CombinedOrder.objects.create(
            combined_order_id="AGENT-COMBINED",
            parent_transaction=parent,
            total_amount=Decimal(500),
            created_by="test",
        )
        self.receipt("AGENT-CHILD", "500", status="COMBINED_FULFILLED")
        self.receipt("AGENT-CANCELLED", "100", status="CANCELLED")
        payload = self.client.get(self.url, self.params).json()
        self.assertEqual(payload["totals"]["total_revenue"], "600.00")
        self.assertEqual(payload["totals"]["transaction_count"], 2)

    def test_current_day_is_labelled_provisional(self):
        today = timezone.localdate().isoformat()
        payload = self.client.get(
            self.url, {"start_date": today, "end_date": today}
        ).json()
        self.assertTrue(payload["is_provisional"])
