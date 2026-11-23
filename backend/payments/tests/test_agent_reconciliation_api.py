from datetime import timedelta
from decimal import Decimal

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from payments.services.reconciliation_v2_service import ReconciliationV2Service
from payments.tests.test_helpers import make_gateway, make_transaction


@override_settings(BI_AGENT_API_KEY="test-agent-secret", BRANCH_NAME="Kitengela")
class AgentReconciliationAPITest(APITestCase):
    def setUp(self):
        self.url = reverse("agent-reconciliation")
        self.day = timezone.localdate()
        self.params = {"start_date": self.day.isoformat(), "end_date": self.day.isoformat()}
        self.client.credentials(HTTP_AUTHORIZATION="Bearer test-agent-secret")

    def test_returns_existing_report_totals_as_exact_amounts(self):
        till = make_gateway(name="Till Products", gateway_type="MPESA_TILL")
        make_transaction(tx_id="RECON-TILL", amount=Decimal("125.75"), status="FULFILLED", gateway=till)
        response = self.client.get(self.url, self.params)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["branch"], {"id": "kitengela", "name": "Kitengela"})
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertTrue(payload["is_provisional"])
        self.assertEqual(payload["x_value"], "-125.75")
        self.assertEqual(payload["y_value"], "125.75")
        self.assertEqual(payload["result"], "0.00")
        self.assertTrue(payload["is_balanced"])
        self.assertNotIn("details", payload)

        other = make_gateway(name="Other Till", gateway_type="MPESA_TILL", gateway_number="other-till")
        make_transaction(tx_id="RECON-OTHER", amount=Decimal("0.25"), status="FULFILLED", gateway=other)
        existing = ReconciliationV2Service.generate_daily_report(self.day)
        payload = self.client.get(self.url, self.params).json()
        self.assertIsInstance(existing["x_value"], float)
        self.assertEqual(payload["result"], "-0.25")
        self.assertFalse(payload["is_balanced"])
        for field in ("x_value", "y_value", "result"):
            self.assertEqual(payload[field], f"{existing[field]:.2f}")
        self.assertEqual(payload["is_balanced"], existing["is_balanced"])

    def test_requires_the_agent_token_and_one_nonfuture_date(self):
        self.assertEqual(self.client.post(self.url, self.params).status_code, 405)
        self.assertEqual(self.client.get(self.url, {
            **self.params, "start_date": (self.day - timedelta(days=1)).isoformat(),
        }).status_code, 400)
        self.assertEqual(self.client.get(self.url, {
            **self.params, "end_date": (self.day + timedelta(days=1)).isoformat(),
        }).status_code, 400)
        self.client.credentials()
        self.assertEqual(self.client.get(self.url, self.params).status_code, 401)
