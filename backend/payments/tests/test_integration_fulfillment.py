from decimal import Decimal
from django.test import TransactionTestCase
from django.utils import timezone
from payments.services.fulfillment_service import FulfillmentService
from payments.services.combined_order_service import CombinedOrderService
from payments.services.admin_service import AdminService
from payments.services.registration_kit_service import RegistrationKitService
from payments.services.stock_take_service import StockTakeService
from payments.models import Transaction, InventoryMovement, Product
from .test_helpers import (
    make_admin, make_processor, make_issuer, make_gateway,
    make_product, make_transaction, make_registration_kit_product,
    make_location, today,
)


class FullFulfillmentFlowTest(TransactionTestCase):
    """End-to-end test: single transaction from activation to fulfillment to reversal."""

    def setUp(self):
        self.admin = make_admin()
        self.processor = make_processor()
        self.issuer = make_issuer()
        self.gateway = make_gateway()
        self.product_a = make_product(
            prod_code='FLOW-A', prod_name='Flow Product A',
            price=Decimal('500.00'), quantity=100,
        )
        self.product_b = make_product(
            prod_code='FLOW-B', prod_name='Flow Product B',
            price=Decimal('300.00'), quantity=50,
        )
        self.location = make_location()
        self.tx = make_transaction(
            tx_id='FLOW-TX-01', amount=Decimal('2000.00'),
        )

    def test_full_single_transaction_flow(self):
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.processor,
            location=self.location,
        )
        self.tx.refresh_from_db()
        self.assertTrue(self.tx.is_in_issuance)

        FulfillmentService.scan_barcode(
            transaction_id=self.tx.id,
            barcode_data={'sku': self.product_a.prod_code, 'quantity': 2},
            scanned_by_user=self.issuer,
        )
        FulfillmentService.scan_barcode(
            transaction_id=self.tx.id,
            barcode_data={'sku': self.product_b.prod_code, 'quantity': 2},
            scanned_by_user=self.issuer,
        )
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.amount_fulfilled, Decimal('1600.00'))
        self.assertEqual(self.tx.line_items.count(), 2)

        FulfillmentService.complete_issuance(
            transaction_id=self.tx.id,
            completed_by_user=self.issuer,
        )
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'PARTIALLY_FULFILLED')
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.quantity, 98)
        self.assertEqual(self.product_b.quantity, 48)

        result = AdminService.cancel_fulfilled_transaction(
            transaction_id=self.tx.id,
            cancelled_by_user=self.admin,
            reason='Integration test reversal',
        )
        self.assertTrue(result['success'])
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'NOT_PROCESSED')
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.quantity, 100)
        self.assertEqual(self.product_b.quantity, 50)


class CombinedOrderFlowTest(TransactionTestCase):
    """End-to-end test: combined order creation, activation, scanning, completion, revert."""

    def setUp(self):
        self.admin = make_admin()
        self.issuer = make_issuer()
        self.gateway = make_gateway()
        self.product_a = make_product(
            prod_code='COFLOW-A', prod_name='CO Product A',
            price=Decimal('500.00'), quantity=100,
        )
        self.product_b = make_product(
            prod_code='COFLOW-B', prod_name='CO Product B',
            price=Decimal('300.00'), quantity=50,
        )
        self.location = make_location()

    def test_full_combined_order_flow(self):
        tx1 = make_transaction(
            tx_id='CO-FLOW-1', amount=Decimal('1000.00'),
        )
        tx2 = make_transaction(
            tx_id='CO-FLOW-2', amount=Decimal('500.00'),
            unique_hash='hash_coflow2',
        )
        result = CombinedOrderService.create_combined_order(
            transaction_ids=[tx1.id, tx2.id],
            created_by=self.admin.username,
            created_by_user=self.admin,
            location=self.location,
        )
        co_id = result['combined_order_id']
        tx1.refresh_from_db()
        tx2.refresh_from_db()
        self.assertEqual(tx1.status, 'COMBINED_FULFILLED')
        self.assertEqual(tx2.status, 'COMBINED_FULFILLED')

        CombinedOrderService.activate_combined_order(
            combined_order_id=co_id,
            activated_by=str(self.admin.username),
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=co_id,
            barcode_data={'sku': self.product_a.prod_code, 'quantity': 2},
            scanned_by=self.issuer,
        )
        CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=co_id,
            barcode_data={'sku': self.product_b.prod_code, 'quantity': 1},
            scanned_by=self.issuer,
        )

        CombinedOrderService.complete_combined_order(
            combined_order_id=co_id,
            completed_by=str(self.admin.username),
        )
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.quantity, 98)
        self.assertEqual(self.product_b.quantity, 49)

        revert_result = CombinedOrderService.revert_combined_order(
            combined_order_id=co_id,
            reverted_by=self.admin,
        )
        self.assertTrue(revert_result['success'])
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.quantity, 100)
        self.assertEqual(self.product_b.quantity, 50)


class RegistrationKitFlowTest(TransactionTestCase):
    """End-to-end test: registration transaction with kit issuance."""

    def setUp(self):
        self.reg_kit = make_registration_kit_product()
        self.reg_kit.quantity = 50
        self.reg_kit.save()
        self.admin = make_admin()
        self.issuer = make_issuer()
        self.gateway = make_gateway()
        self.product = make_product(
            prod_code='REG-FLOW', prod_name='Reg Flow Product',
            price=Decimal('500.00'), quantity=100, pv=Decimal('10.00'),
        )
        self.location = make_location()
        self.tx = make_transaction(
            tx_id='REG-FLOW-TX', amount=Decimal('10000.00'),
            is_registration=True,
        )

    def test_registration_flow_with_kit(self):
        FulfillmentService.activate_issuance(
            transaction_id=self.tx.id,
            activated_by_user=self.admin,
            location=self.location,
        )
        FulfillmentService.scan_barcode(
            transaction_id=self.tx.id,
            barcode_data={'sku': self.product.prod_code, 'quantity': 5},
            scanned_by_user=self.issuer,
        )
        RegistrationKitService.issue_registration_kit(
            transaction_id=self.tx.id,
            quantity=1,
            issued_by='system',
        )
        self.tx.refresh_from_db()
        self.assertTrue(self.tx.registration_kit_issued)
        self.assertEqual(self.tx.registration_kit_quantity, 1)
        self.reg_kit.refresh_from_db()
        self.assertEqual(self.reg_kit.quantity, 49)

        FulfillmentService.complete_issuance(
            transaction_id=self.tx.id,
            completed_by_user=self.issuer,
        )
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'FULFILLED')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 95)


class StockTakeAndReconciliationFlowTest(TransactionTestCase):
    """End-to-end test: stock take, then daily reconciliation."""

    def setUp(self):
        self.admin = make_admin()
        self.gateway = make_gateway()
        self.product = make_product(
            prod_code='STKRECON', prod_name='Stock Take Recon Product',
            price=Decimal('500.00'), quantity=100,
        )
        self.location = make_location()

    def test_stock_take_then_reconciliation(self):
        session = StockTakeService.create_session(created_by=self.admin)
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=10,
            scanned_by=self.admin,
        )
        StockTakeService.complete_session(
            session_id=session.session_id,
            completed_by=self.admin,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 110)

        from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService
        rec = ReconciliationWorkflowService.get_or_create_reconciliation(
            reconciliation_date=today(),
            created_by=self.admin,
        )
        result = ReconciliationWorkflowService.update_adjustment(
            reconciliation=rec,
            product_data={'product_id': self.product.id},
            product_total=self.product.current_price,
            updated_by=self.admin,
        )
        self.assertTrue(result['success'])
        ReconciliationWorkflowService.confirm_reconciliation(
            reconciliation_id=rec.id,
            confirmed_by=self.admin,
        )
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'CONFIRMED')
