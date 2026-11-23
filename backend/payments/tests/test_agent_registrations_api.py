from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from payments.models import InventoryMovement, Transaction
from payments.services.fulfillment_service import FulfillmentService
from payments.services.reconciliation_v2_service import ReconciliationV2Service
from payments.services.registration_kit_service import RegistrationKitService
from payments.tests.test_helpers import make_combined_order, make_registration_kit_product, make_transaction


@override_settings(BI_AGENT_API_KEY="test-agent-key", BRANCH_NAME="Kitengela")
class AgentRegistrationsAPITest(APITestCase):
    def setUp(self):
        self.kit = make_registration_kit_product()
        self.kit.quantity = 12
        self.kit.save(update_fields=["quantity"])
        self.url = reverse("agent-registrations")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer test-agent-key")

    def report_for(self, day):
        response = self.client.get(self.url, {"start_date": day, "end_date": day})
        self.assertEqual(response.status_code, 200, response.json())
        return response.json()

    def test_two_kits_are_two_registrations_and_adjust_reconciliation_by_400(self):
        day = timezone.localdate()
        tx = make_transaction(tx_id="TWO-KITS", amount=Decimal("7000.00"), is_registration=True)
        make_transaction(tx_id="PENDING-REGISTRATION", is_registration=True)
        RegistrationKitService.issue_registration_kit(tx.pk, quantity=2)
        tx.refresh_from_db()
        self.kit.refresh_from_db()
        self.assertEqual(tx.registration_kit_amount_deducted, Decimal("5800.00"))
        self.assertEqual(self.kit.quantity, 10)
        self.assertEqual(ReconciliationV2Service.calculate_kits(day)["amount"], Decimal("400.00"))
        report = self.report_for(day)
        self.assertEqual(report["registration_transactions"], 1)
        self.assertEqual(report["kits_issued"], 2)
        self.assertEqual(report["registration_margin"], "400.00")
        self.client.credentials()
        self.assertEqual(self.client.get(self.url, {"start_date": day, "end_date": day}).status_code, 401)

    def test_combining_moves_no_kits_to_the_combination_date(self):
        day = timezone.localdate()
        txn = make_transaction(tx_id="OLD-KITS", amount=Decimal("7000.00"), is_registration=True)
        RegistrationKitService.issue_registration_kit(txn.pk, quantity=2)
        Transaction.objects.filter(pk=txn.pk).update(status=Transaction.OrderStatus.PARTIALLY_FULFILLED)
        InventoryMovement.objects.filter(reference__endswith=txn.tx_id).update(
            created_at=timezone.now() - timedelta(days=1),
        )
        target = make_transaction(tx_id="OTHER-RECEIPT", amount=Decimal("5000.00"))
        make_combined_order(transactions=[txn, target])
        self.assertEqual(self.report_for(day)["kits_issued"], 0)
        self.assertEqual(self.report_for(day - timedelta(days=1))["kits_issued"], 2)

    def test_direct_issuance_populates_the_fields_used_by_reconciliation(self):
        day = timezone.localdate()
        tx = make_transaction(tx_id="DIRECT-REGISTRATION", amount=Decimal("10000.00"), is_registration=True)
        FulfillmentService.complete_registration_issuance(tx.pk, quantity=2)
        tx.refresh_from_db()
        self.assertTrue(tx.registration_kit_issued)
        self.assertEqual(tx.registration_kit_quantity, 2)
        self.assertEqual(tx.registration_kit_amount_deducted, 2 * self.kit.cost_price)
        self.assertEqual(ReconciliationV2Service.calculate_kits(day)["amount"], Decimal("400.00"))
        with self.assertRaises(ValidationError):
            FulfillmentService.complete_registration_issuance(tx.pk, quantity=2)
        self.assertEqual(self.report_for(day)["kits_issued"], 2)
        # Older issues can still be counted by their actual inventory movement.
        Transaction.objects.filter(pk=tx.pk).update(registration_kit_issued=False, registration_kit_quantity=0)
        self.assertEqual(self.report_for(day)["kits_issued"], 2)
