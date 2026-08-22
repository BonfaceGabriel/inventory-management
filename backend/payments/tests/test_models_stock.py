from decimal import Decimal
from django.test import TestCase, TransactionTestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from payments.models import (
    DailyStockReconciliation, StockAdjustmentItem, StockTakeSession, StockTakeItem,
    EndOfDayValueReconciliation, InventoryMovement,
)
from .test_helpers import (
    make_admin, make_product, make_gateway, make_transaction, make_line_item,
    make_daily_stock_reconciliation, make_stock_adjustment_item,
    make_stock_take_session, today,
)


class DailyStockReconciliationTest(TestCase):
    def setUp(self):
        self.rec = make_daily_stock_reconciliation()

    def test_string_representation(self):
        self.assertIn(str(self.rec.reconciliation_date), str(self.rec))
        self.assertIn('DRAFT', str(self.rec))

    def test_initial_status_is_draft(self):
        self.assertEqual(self.rec.status, 'DRAFT')

    def test_is_confirmed_false_when_draft(self):
        self.assertFalse(self.rec.is_confirmed())

    def test_is_confirmed_true_when_confirmed(self):
        self.rec.status = 'CONFIRMED'
        self.assertTrue(self.rec.is_confirmed())

    def test_unique_reconciliation_date(self):
        with self.assertRaises(Exception):
            DailyStockReconciliation.objects.create(
                reconciliation_date=self.rec.reconciliation_date,
            )


class StockAdjustmentItemTest(TransactionTestCase):
    def setUp(self):
        self.admin = make_admin()
        self.product = make_product(quantity=100)
        self.rec = make_daily_stock_reconciliation(created_by=self.admin)
        self.adj = make_stock_adjustment_item(
            reconciliation=self.rec, product=self.product,
            opening_stock=100, closing_stock=100,
        )

    def test_string_representation(self):
        self.assertIn(self.product.prod_name, str(self.adj))
        self.assertIn('100', str(self.adj))

    def test_effective_opening_stock_uses_baseline_when_set(self):
        self.adj.opening_stock_baseline = 90
        self.assertEqual(self.adj.effective_opening_stock, 90)

    def test_effective_opening_stock_falls_back_to_opening(self):
        self.assertEqual(self.adj.effective_opening_stock, 100)

    def test_net_adjustment_calculation(self):
        self.adj.quantity_added = 10
        self.adj.quantity_deducted = 5
        self.assertEqual(self.adj.net_adjustment, 5)

    def test_calculated_totals_sum(self):
        self.adj.quantity_added = 15
        self.adj.quantity_deducted = 5
        self.adj.quantity_replenished = 20
        self.assertEqual(self.adj.calculated_totals, 130)

    def test_clean_rejects_negative_added(self):
        with self.assertRaises(ValidationError):
            self.adj.quantity_added = -5
            self.adj.clean()

    def test_clean_rejects_negative_deducted(self):
        with self.assertRaises(ValidationError):
            self.adj.quantity_deducted = -5
            self.adj.clean()

    def test_clean_passes_with_zero_values(self):
        self.adj.quantity_added = 0
        self.adj.quantity_deducted = 0
        self.adj.clean()

    def test_quantity_replenished_defaults_zero(self):
        self.assertEqual(self.adj.quantity_replenished, 0)

    def test_opening_stock_baseline_nullable(self):
        self.assertIsNone(self.adj.opening_stock_baseline)


class StockAdjustmentItemCalculationsTest(TransactionTestCase):
    def setUp(self):
        self.admin = make_admin()
        self.gateway = make_gateway()
        self.product = make_product(quantity=100)
        self.tx = make_transaction(tx_id='SAC-TX', amount=Decimal('1000.00'))
        self.tx.status = 'PROCESSING'
        self.tx.save()
        self.rec = make_daily_stock_reconciliation(created_by=self.admin)
        self.adj = make_stock_adjustment_item(
            reconciliation=self.rec, product=self.product,
            opening_stock=100, closing_stock=100,
        )

    def test_calculate_issued_from_orders_with_line_items(self):
        li = make_line_item(self.tx, self.product, quantity=3)
        li.is_inventory_deducted = True
        li.save()
        issued = StockAdjustmentItem.calculate_issued_from_orders(
            self.product.id, today()
        )
        self.assertEqual(issued, 3)

    def test_calculate_issued_from_orders_excludes_undeducted(self):
        make_line_item(self.tx, self.product, quantity=3)
        issued = StockAdjustmentItem.calculate_issued_from_orders(
            self.product.id, today()
        )
        self.assertEqual(issued, 0)

    def test_calculate_issued_from_orders_ignores_wrong_date(self):
        li = make_line_item(self.tx, self.product, quantity=3)
        li.is_inventory_deducted = True
        li.save()
        yesterday = today() - timezone.timedelta(days=1)
        issued = StockAdjustmentItem.calculate_issued_from_orders(
            self.product.id, yesterday
        )
        self.assertEqual(issued, 0)

    def test_calculate_issued_from_orders_cross_day(self):
        li = make_line_item(self.tx, self.product, quantity=5)
        li.is_inventory_deducted = True
        li.save()
        yesterday = today() - timezone.timedelta(days=1)
        issued_today = StockAdjustmentItem.calculate_issued_from_orders(
            self.product.id, today()
        )
        issued_yesterday = StockAdjustmentItem.calculate_issued_from_orders(
            self.product.id, yesterday
        )
        self.assertEqual(issued_today, 5)
        self.assertEqual(issued_yesterday, 0)

    def test_calculate_expected_consignment_with_no_replenishment(self):
        consignment = StockAdjustmentItem.calculate_expected_consignment(
            self.product.id, today()
        )
        self.assertEqual(consignment, 0)

    def test_calculate_expected_consignment_with_replenishment(self):
        StockTakeSession.objects.create(
            session_id='STK-CONSIGN-001', status='COMPLETED',
            created_at=today() - timezone.timedelta(days=2),
            completed_at=today() - timezone.timedelta(days=2),
        )
        rec = make_daily_stock_reconciliation(
            date=today() - timezone.timedelta(days=1),
            created_by=self.admin,
        )
        adj = make_stock_adjustment_item(
            reconciliation=rec, product=self.product,
            opening_stock=100, closing_stock=100,
        )
        adj.quantity_replenished = 20
        adj.save()
        consignment = StockAdjustmentItem.calculate_expected_consignment(
            self.product.id, today()
        )
        self.assertEqual(consignment, 0)


class StockTakeSessionTest(TestCase):
    def setUp(self):
        self.admin = make_admin()

    def test_session_id_format(self):
        session = StockTakeSession.objects.create(
            session_id='STK-20260101-120000',
            status='DRAFT',
            performed_by_user=self.admin,
        )
        self.assertTrue(session.session_id.startswith('STK-'))

    def test_initial_status_is_draft(self):
        session = StockTakeSession.objects.create(
            session_id='STK-20260101-120001',
            performed_by_user=self.admin,
        )
        self.assertEqual(session.status, 'DRAFT')

    def test_string_representation(self):
        session = StockTakeSession.objects.create(
            session_id='STK-20260101-120002',
            performed_by_user=self.admin,
        )
        self.assertIn(session.session_id, str(session))

    def test_kit_quantity_defaults_zero(self):
        session = StockTakeSession.objects.create(
            session_id='STK-20260101-120003',
            performed_by_user=self.admin,
        )
        self.assertEqual(session.kit_quantity, 0)

    def test_completed_at_nullable(self):
        session = StockTakeSession.objects.create(
            session_id='STK-20260101-120004',
            performed_by_user=self.admin,
        )
        self.assertIsNone(session.completed_at)


class StockTakeItemTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.product = make_product(quantity=100)
        self.session = StockTakeSession.objects.create(
            session_id='STK-ITEM-001',
            performed_by_user=self.admin,
        )

    def test_quantity_after_calculation(self):
        item = StockTakeItem.objects.create(
            session=self.session,
            product=self.product,
            quantity_before=100,
            quantity_scanned=10,
            quantity_after=110,
        )
        self.assertEqual(item.quantity_after, 110)
        self.assertEqual(item.quantity_before, 100)
        self.assertEqual(item.quantity_scanned, 10)

    def test_clean_validates_arithmetic(self):
        item = StockTakeItem(
            session=self.session,
            product=self.product,
            quantity_before=100,
            quantity_scanned=10,
            quantity_after=200,
        )
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_string_representation(self):
        item = StockTakeItem.objects.create(
            session=self.session,
            product=self.product,
            quantity_before=100,
            quantity_scanned=15,
            quantity_after=115,
        )
        self.assertIn(self.product.prod_name, str(item))


class EndOfDayValueReconciliationTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.eod = EndOfDayValueReconciliation.objects.create(
            reconciliation_date=today(),
            created_by=self.admin,
        )

    def test_initial_status_is_draft(self):
        self.assertEqual(self.eod.status, 'DRAFT')

    def test_default_values_are_zero(self):
        self.assertEqual(self.eod.opening_stock_value, Decimal('0.00'))
        self.assertEqual(self.eod.replenished_value, Decimal('0.00'))
        self.assertEqual(self.eod.sales_value, Decimal('0.00'))
        self.assertEqual(self.eod.x_value, Decimal('0.00'))

    def test_recalculate_x_formula(self):
        self.eod.opening_stock_value = Decimal('1000.00')
        self.eod.replenished_value = Decimal('200.00')
        self.eod.sales_value = Decimal('300.00')
        self.eod.recalculate()
        self.assertEqual(self.eod.x_value, Decimal('900.00'))

    def test_recalculate_y_formula(self):
        self.eod.stock_value = Decimal('800.00')
        self.eod.bk_stock = Decimal('50.00')
        self.eod.duplicated = Decimal('20.00')
        self.eod.recalculate()
        self.assertEqual(self.eod.y_value, Decimal('870.00'))

    def test_recalculate_z_formula(self):
        self.eod.hq_value = Decimal('500.00')
        self.eod.kitengela_value = Decimal('200.00')
        self.eod.kitui_value = Decimal('100.00')
        self.eod.nakuru_value = Decimal('50.00')
        self.eod.recalculate()
        self.assertEqual(self.eod.z_value, Decimal('850.00'))

    def test_recalculate_v_formula(self):
        self.eod.opening_stock_value = Decimal('1000.00')
        self.eod.replenished_value = Decimal('200.00')
        self.eod.sales_value = Decimal('300.00')
        self.eod.stock_value = Decimal('800.00')
        self.eod.bk_stock = Decimal('50.00')
        self.eod.duplicated = Decimal('20.00')
        self.eod.hq_value = Decimal('500.00')
        self.eod.kitengela_value = Decimal('200.00')
        self.eod.kitui_value = Decimal('100.00')
        self.eod.nakuru_value = Decimal('50.00')
        self.eod.recalculate()
        self.assertEqual(self.eod.x_value, Decimal('900.00'))
        self.assertEqual(self.eod.y_value, Decimal('870.00'))
        self.assertEqual(self.eod.z_value, Decimal('850.00'))
        self.assertEqual(self.eod.v_value, Decimal('-820.00'))

    def test_is_within_threshold_true_when_v_under_100(self):
        self.eod.opening_stock_value = Decimal('100')
        self.eod.replenished_value = Decimal('0')
        self.eod.sales_value = Decimal('0')
        self.eod.stock_value = Decimal('50')
        self.eod.recalculate()
        self.assertTrue(self.eod.is_within_threshold)

    def test_is_within_threshold_false_when_v_over_100(self):
        self.eod.opening_stock_value = Decimal('1000')
        self.eod.sales_value = Decimal('0')
        self.eod.replenished_value = Decimal('0')
        self.eod.stock_value = Decimal('100')
        self.eod.hq_value = Decimal('500')
        self.eod.recalculate()
        self.assertFalse(self.eod.is_within_threshold)
