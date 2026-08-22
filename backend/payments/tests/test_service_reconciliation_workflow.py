from decimal import Decimal
from django.test import TransactionTestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService
from payments.models import (
    DailyStockReconciliation, StockAdjustmentItem, InventoryMovement,
)
from .test_helpers import (
    make_admin, make_product, make_gateway, make_transaction,
    make_daily_stock_reconciliation, make_stock_adjustment_item, today,
)


class ReconciliationWorkflowServiceTest(TransactionTestCase):
    def setUp(self):
        self.admin = make_admin(username='rw_admin')
        self.gateway = make_gateway()
        self.product = make_product(prod_code='RW-PROD', quantity=100, price=Decimal('500.00'))

    def test_get_or_create_reconciliation_creates(self):
        rec = ReconciliationWorkflowService.get_or_create_reconciliation(
            reconciliation_date=today(),
            created_by=self.admin,
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.reconciliation_date, today())
        self.assertEqual(rec.status, 'DRAFT')

    def test_get_or_create_reconciliation_returns_existing(self):
        first = ReconciliationWorkflowService.get_or_create_reconciliation(
            reconciliation_date=today(), created_by=self.admin,
        )
        second = ReconciliationWorkflowService.get_or_create_reconciliation(
            reconciliation_date=today(), created_by=self.admin,
        )
        self.assertEqual(first.id, second.id)

    def test_update_adjustment_creates(self):
        rec = ReconciliationWorkflowService.get_or_create_reconciliation(
            reconciliation_date=today(), created_by=self.admin,
        )
        result = ReconciliationWorkflowService.update_adjustment(
            reconciliation=rec,
            product_data={'product_id': self.product.id},
            product_total=self.product.current_price,
            updated_by=self.admin,
        )
        self.assertTrue(result['success'])
        self.assertEqual(rec.adjustments.count(), 1)

    def test_update_adjustment_updates_existing(self):
        rec = ReconciliationWorkflowService.get_or_create_reconciliation(
            reconciliation_date=today(), created_by=self.admin,
        )
        ReconciliationWorkflowService.update_adjustment(
            reconciliation=rec,
            product_data={'product_id': self.product.id},
            product_total=self.product.current_price,
            updated_by=self.admin,
        )
        ReconciliationWorkflowService.update_adjustment(
            reconciliation=rec,
            product_data={
                'product_id': self.product.id,
                'quantity_added': 10,
                'quantity_deducted': 5,
            },
            product_total=self.product.current_price,
            updated_by=self.admin,
        )
        adj = rec.adjustments.first()
        self.assertEqual(adj.quantity_added, 10)
        self.assertEqual(adj.quantity_deducted, 5)

    def test_confirm_reconciliation(self):
        rec = ReconciliationWorkflowService.get_or_create_reconciliation(
            reconciliation_date=today(), created_by=self.admin,
        )
        ReconciliationWorkflowService.update_adjustment(
            reconciliation=rec,
            product_data={'product_id': self.product.id},
            product_total=self.product.current_price,
            updated_by=self.admin,
        )
        result = ReconciliationWorkflowService.confirm_reconciliation(
            reconciliation_id=rec.id,
            confirmed_by=self.admin,
        )
        self.assertTrue(result['success'])
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'CONFIRMED')

    def test_get_reconciliation_by_date(self):
        rec = ReconciliationWorkflowService.get_or_create_reconciliation(
            reconciliation_date=today(), created_by=self.admin,
        )
        found = ReconciliationWorkflowService.get_reconciliation_by_date(today())
        self.assertEqual(found.id, rec.id)

    def test_can_create_reconciliation(self):
        can, reason = ReconciliationWorkflowService.can_create_reconciliation(today())
        self.assertTrue(can)

    def test_set_opening_stock_baseline(self):
        rec = ReconciliationWorkflowService.get_or_create_reconciliation(
            reconciliation_date=today(), created_by=self.admin,
        )
        adj = make_stock_adjustment_item(
            reconciliation=rec, product=self.product,
            opening_stock=100, closing_stock=100,
        )
        result = ReconciliationWorkflowService.set_opening_stock_baseline(
            reconciliation=rec,
            product_id=self.product.id,
            baseline_qty=90,
            updated_by=self.admin,
        )
        self.assertTrue(result['success'])
        adj.refresh_from_db()
        self.assertEqual(adj.opening_stock_baseline, 90)

    def test_clear_opening_stock_baseline(self):
        rec = ReconciliationWorkflowService.get_or_create_reconciliation(
            reconciliation_date=today(), created_by=self.admin,
        )
        adj = make_stock_adjustment_item(
            reconciliation=rec, product=self.product,
            opening_stock=100, closing_stock=100,
        )
        adj.opening_stock_baseline = 90
        adj.save()
        ReconciliationWorkflowService.clear_opening_stock_baseline(
            reconciliation=rec,
            updated_by=self.admin,
        )
        adj.refresh_from_db()
        self.assertIsNone(adj.opening_stock_baseline)
