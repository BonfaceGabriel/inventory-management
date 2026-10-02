from decimal import Decimal
from django.test import TransactionTestCase
from django.utils import timezone
from payments.models import MerchandiseOrder
from payments.services.reconciliation_v2_service import ReconciliationV2Service
from .test_helpers import (
    make_admin, make_gateway, make_transaction, make_product,
    make_line_item, make_issuer, today,
)


class ReconciliationV2ServiceTest(TransactionTestCase):
    def setUp(self):
        self.admin = make_admin()
        self.issuer = make_issuer()
        self.till_gw = make_gateway(
            name='Till Products', gateway_type='MPESA_TILL', gateway_number='TILL-01',
        )
        self.paybill_gw = make_gateway(
            name='Parent Paybill', gateway_type='MPESA_PAYBILL', gateway_number='PAYBILL-01',
        )
        self.paybill_gw.is_parent_company = True
        self.paybill_gw.settlement_type = 'PARENT_TAKES_ALL'
        self.paybill_gw.save()
        self.pdq_gw = make_gateway(
            name='Test PDQ', gateway_type='PDQ', gateway_number='PDQ-01',
        )
        self.product = make_product(prod_code='RECV2-PROD', price=Decimal('500.00'), quantity=100)

    def _make_tx(self, tx_id, amount, gateway=None, status='FULFILLED', **kw):
        return make_transaction(
            tx_id=tx_id, amount=amount,
            gateway=gateway or self.till_gw,
            status=status, **kw
        )

    def _make_tx_with_timestamp(self, tx_id, amount, gateway=None, status='FULFILLED', timestamp=None, **kw):
        tx = make_transaction(
            tx_id=tx_id, amount=amount,
            gateway=gateway or self.till_gw,
            status=status, **kw
        )
        if timestamp:
            Transaction = type(tx)
            Transaction.objects.filter(pk=tx.pk).update(timestamp=timestamp)
            tx.refresh_from_db()
        return tx

    def test_get_parent_paybill_gateway(self):
        gw = ReconciliationV2Service.get_parent_paybill_gateway()
        self.assertIsNotNone(gw)
        self.assertEqual(gw.gateway_type, 'MPESA_PAYBILL')

    def test_get_till_gateways(self):
        till_2 = make_gateway(
            name='Till Products 2', gateway_type='MPESA_TILL', gateway_number='TILL-02',
        )
        tills = ReconciliationV2Service.get_till_gateways()
        self.assertIn(self.till_gw, tills)
        self.assertIn(till_2, tills)

    def test_get_pdq_gateway(self):
        gw = ReconciliationV2Service.get_pdq_gateway()
        self.assertIsNotNone(gw)
        self.assertEqual(gw.gateway_type, 'PDQ')

    def test_get_date_range_returns_today(self):
        from_dt, to_dt = ReconciliationV2Service.get_date_range(today())
        self.assertEqual(from_dt.date(), today())
        self.assertEqual(to_dt.date(), today())

    def test_calculate_mpesa_paybill(self):
        self._make_tx('RECV2-PB-1', Decimal('1000.00'), gateway=self.paybill_gw)
        self._make_tx('RECV2-PB-2', Decimal('500.00'), gateway=self.paybill_gw)
        result = ReconciliationV2Service.calculate_mpesa_paybill(today(), self.paybill_gw)
        self.assertEqual(result['amount'], Decimal('1500.00'))

    def test_calculate_mpesa_paybill_excludes_non_paybill(self):
        self._make_tx('RECV2-TL-1', Decimal('2000.00'), gateway=self.till_gw)
        result = ReconciliationV2Service.calculate_mpesa_paybill(today(), self.paybill_gw)
        self.assertEqual(result['amount'], Decimal('0.00'))

    def test_calculate_till_sales(self):
        self._make_tx('RECV2-TS-1', Decimal('1000.00'), gateway=self.till_gw)
        self._make_tx('RECV2-TS-2', Decimal('500.00'), gateway=self.till_gw)
        result = ReconciliationV2Service.calculate_till_sales(today())
        self.assertEqual(result['amount'], Decimal('1500.00'))

    def test_calculate_pdq_total(self):
        self._make_tx('RECV2-PDQ-1', Decimal('3000.00'), gateway=self.pdq_gw)
        result = ReconciliationV2Service.calculate_pdq_total(today())
        self.assertEqual(result['amount'], Decimal('3000.00'))

    def test_calculate_previous_with_paybill(self):
        yesterday = today() - timezone.timedelta(days=1)
        ts = timezone.make_aware(
            timezone.datetime.combine(yesterday, timezone.datetime.min.time())
        )
        tx = self._make_tx('RECV2-PREV', Decimal('2000.00'), gateway=self.paybill_gw,
                           unique_hash='hash_prev')
        Transaction = type(tx)
        Transaction.objects.filter(pk=tx.pk).update(timestamp=ts, completed_at=timezone.now())
        result = ReconciliationV2Service.calculate_previous(today(), self.paybill_gw)
        self.assertEqual(result['amount'], Decimal('2000.00'))

    def test_calculate_credit(self):
        self._make_tx('RECV2-CR-1', Decimal('1000.00'), gateway=self.paybill_gw, status='PARTIALLY_FULFILLED')
        result = ReconciliationV2Service.calculate_credit(today(), self.paybill_gw)
        self.assertEqual(result['amount'], Decimal('1000.00'))

    def test_calculate_kits(self):
        make_product(
            prod_code='REG_KIT_001', prod_name='Reg Kit RECV2',
            price=Decimal('2900.00'), quantity=50,
        )
        tx = self._make_tx('RECV2-KIT', Decimal('2900.00'), gateway=self.till_gw,
                           is_registration=True)
        tx.registration_kit_issued = True
        tx.registration_kit_quantity = 1
        tx.registration_kit_amount_deducted = Decimal('2900.00')
        tx.save(skip_validation=True)
        result = ReconciliationV2Service.calculate_kits(today())
        self.assertEqual(result['amount'], Decimal('200.00'))

    def test_calculate_total_sales(self):
        self._make_tx('RECV2-SA-1', Decimal('1000.00'), gateway=self.till_gw)
        result = ReconciliationV2Service.calculate_total_sales(today())
        self.assertIn('amount', result)

    def test_get_raw_gateway_totals(self):
        self._make_tx('RECV2-RG-1', Decimal('1000.00'), gateway=self.till_gw)
        totals = ReconciliationV2Service.get_raw_gateway_totals(today())
        self.assertIn('till', totals)

    def test_generate_daily_report_structure(self):
        self._make_tx('RECV2-REP-1', Decimal('1000.00'), gateway=self.till_gw)
        report = ReconciliationV2Service.generate_daily_report(today())
        self.assertIn('report_date', report)
        self.assertIn('details', report)
        self.assertIn('x_formula', report)
        self.assertIn('y_formula', report)


class ReconciliationV2BalanceTest(TransactionTestCase):
    """
    The books must balance (X + Y == 0) for every combination of flows.

    These cover the two defects that let a 43,300 phantom survive unnoticed:
    PDQ cash-in had no matching unfulfilled exclusion, and merchandise
    transactions were identified by gateway type instead of by MerchandiseOrder
    link, so a merchandise payment on a till gateway leaked into the books.
    """

    def setUp(self):
        make_admin()
        self.till_gw = make_gateway(
            name='Till Products', gateway_type='MPESA_TILL', gateway_number='TILL-BAL',
        )
        self.paybill_gw = make_gateway(
            name='Parent Paybill', gateway_type='MPESA_PAYBILL', gateway_number='PAYBILL-BAL',
        )
        self.paybill_gw.is_parent_company = True
        self.paybill_gw.settlement_type = 'PARENT_TAKES_ALL'
        self.paybill_gw.save()
        self.pdq_gw = make_gateway(
            name='Balance PDQ', gateway_type='PDQ', gateway_number='PDQ-BAL',
        )

    def _tx(self, tx_id, amount, gateway, status='NOT_PROCESSED', fulfilled=None):
        return make_transaction(
            tx_id=tx_id, amount=amount, gateway=gateway, status=status,
            amount_fulfilled=fulfilled if fulfilled is not None else Decimal('0.00'),
        )

    def _mark_merchandise(self, tx, gateway=None):
        """Attach a MerchandiseOrder, which is what makes a transaction merchandise."""
        return MerchandiseOrder.objects.create(
            transaction=tx,
            gateway=gateway or self.till_gw,
            status=MerchandiseOrder.Status.FULFILLED,
        )

    # ---------- PDQ: inflow needs a matching unfulfilled exclusion ----------

    def test_unfulfilled_pdq_is_backed_out_by_unused(self):
        self._tx('PDQ-NP', Decimal('3000.00'), self.pdq_gw)
        unused = ReconciliationV2Service.calculate_unused_unfulfilled(today(), self.paybill_gw)
        self.assertEqual(unused['amount'], Decimal('3000.00'))

    def test_unfulfilled_pdq_does_not_unbalance_the_books(self):
        self._tx('PDQ-NP2', Decimal('3000.00'), self.pdq_gw)
        report = ReconciliationV2Service.generate_daily_report(today())
        self.assertEqual(report['result'], 0.0)
        self.assertTrue(report['is_balanced'])

    def test_fulfilled_pdq_nets_through_sales(self):
        self._tx('PDQ-FUL', Decimal('3000.00'), self.pdq_gw, 'FULFILLED', Decimal('3000.00'))
        report = ReconciliationV2Service.generate_daily_report(today())
        unused = ReconciliationV2Service.calculate_unused_unfulfilled(today(), self.paybill_gw)
        sales = ReconciliationV2Service.calculate_total_sales(today())
        self.assertEqual(unused['amount'], Decimal('0.00'))
        self.assertEqual(sales['amount'], Decimal('3000.00'))
        self.assertTrue(report['is_balanced'])

    def test_partially_fulfilled_pdq_balance_goes_to_credit(self):
        self._tx('PDQ-PART', Decimal('1000.00'), self.pdq_gw, 'PARTIALLY_FULFILLED', Decimal('400.00'))
        credit = ReconciliationV2Service.calculate_credit(today(), self.paybill_gw)
        unused = ReconciliationV2Service.calculate_unused_unfulfilled(today(), self.paybill_gw)
        self.assertEqual(credit['amount'], Decimal('600.00'))
        self.assertEqual(unused['amount'], Decimal('0.00'))
        report = ReconciliationV2Service.generate_daily_report(today())
        self.assertTrue(report['is_balanced'])

    def test_processing_pdq_is_treated_as_unfulfilled(self):
        self._tx('PDQ-PROC', Decimal('2500.00'), self.pdq_gw, 'PROCESSING')
        unused = ReconciliationV2Service.calculate_unused_unfulfilled(today(), self.paybill_gw)
        self.assertEqual(unused['amount'], Decimal('2500.00'))
        self.assertTrue(ReconciliationV2Service.generate_daily_report(today())['is_balanced'])

    def test_unused_still_counts_unfulfilled_paybill(self):
        self._tx('PB-NP', Decimal('5000.00'), self.paybill_gw)
        unused = ReconciliationV2Service.calculate_unused_unfulfilled(today(), self.paybill_gw)
        self.assertEqual(unused['amount'], Decimal('5000.00'))

    # ---------- Merchandise is invisible in every term ----------

    def test_merchandise_till_transaction_excluded_from_till(self):
        tx = self._tx('MERCH-TILL', Decimal('1000.00'), self.till_gw, 'FULFILLED', Decimal('1000.00'))
        self._mark_merchandise(tx)
        self.assertEqual(
            ReconciliationV2Service.calculate_till_sales(today())['amount'], Decimal('0.00')
        )

    def test_merchandise_till_transaction_excluded_from_sales(self):
        tx = self._tx('MERCH-TILL-2', Decimal('1000.00'), self.till_gw, 'FULFILLED', Decimal('1000.00'))
        self._mark_merchandise(tx)
        self.assertEqual(
            ReconciliationV2Service.calculate_total_sales(today())['amount'], Decimal('0.00')
        )

    def test_merchandise_paybill_transaction_excluded_from_cash_in(self):
        tx = self._tx('MERCH-PB', Decimal('5000.00'), self.paybill_gw)
        self._mark_merchandise(tx, gateway=self.paybill_gw)
        self.assertEqual(
            ReconciliationV2Service.calculate_mpesa_paybill(today(), self.paybill_gw)['amount'],
            Decimal('0.00'),
        )

    def test_merchandise_pdq_transaction_excluded_everywhere(self):
        tx = self._tx('MERCH-PDQ', Decimal('2000.00'), self.pdq_gw)
        self._mark_merchandise(tx, gateway=self.pdq_gw)
        self.assertEqual(
            ReconciliationV2Service.calculate_pdq_total(today())['amount'], Decimal('0.00')
        )
        self.assertEqual(
            ReconciliationV2Service.calculate_unused_unfulfilled(today(), self.paybill_gw)['amount'],
            Decimal('0.00'),
        )

    def test_merchandise_excluded_from_raw_gateway_totals(self):
        tx = self._tx('MERCH-RAW', Decimal('1000.00'), self.till_gw, 'FULFILLED', Decimal('1000.00'))
        self._mark_merchandise(tx)
        self.assertEqual(
            ReconciliationV2Service.get_raw_gateway_totals(today())['till'], 0.0
        )

    def test_merchandise_alongside_real_sales_still_balances(self):
        merch = self._tx('MIX-MERCH', Decimal('1000.00'), self.till_gw, 'FULFILLED', Decimal('1000.00'))
        self._mark_merchandise(merch)
        self._tx('MIX-REAL', Decimal('500.00'), self.till_gw, 'FULFILLED', Decimal('500.00'))
        report = ReconciliationV2Service.generate_daily_report(today())
        self.assertEqual(report['y_formula']['till'], 500.0)
        self.assertEqual(report['x_formula']['sales'], 500.0)
        self.assertTrue(report['is_balanced'])

    # ---------- End-to-end balance across mixed flows ----------

    def test_books_balance_across_mixed_flows(self):
        self._tx('MIX-PB-NP', Decimal('5000.00'), self.paybill_gw)
        self._tx('MIX-PDQ-NP', Decimal('3000.00'), self.pdq_gw)
        self._tx('MIX-TILL-F', Decimal('1000.00'), self.till_gw, 'FULFILLED', Decimal('1000.00'))
        report = ReconciliationV2Service.generate_daily_report(today())
        self.assertEqual(report['x_formula']['unused'], 8000.0)
        self.assertEqual(report['x_formula']['mpesa_paybill'], 5000.0)
        self.assertEqual(report['x_formula']['pdq'], 3000.0)
        self.assertEqual(report['x_formula']['sales'], 1000.0)
        self.assertEqual(report['result'], 0.0)
        self.assertTrue(report['is_balanced'])

    def test_books_balance_regression_for_reported_figures(self):
        """
        Mirrors the 2026-10-02 figures that produced a 43,300 discrepancy:
        paybill partly unfulfilled, PDQ entirely unfulfilled, one till sale.
        """
        self._tx('REG-PB-NP', Decimal('85050.00'), self.paybill_gw)
        self._tx('REG-PB-PROC', Decimal('8500.00'), self.paybill_gw, 'PROCESSING')
        self._tx('REG-PB-PART', Decimal('13500.00'), self.paybill_gw, 'PARTIALLY_FULFILLED', Decimal('8856.00'))
        self._tx('REG-PDQ-NP', Decimal('43300.00'), self.pdq_gw)
        self._tx('REG-TILL-F', Decimal('7400.00'), self.till_gw, 'FULFILLED', Decimal('7400.00'))

        report = ReconciliationV2Service.generate_daily_report(today())
        self.assertEqual(report['x_formula']['unused'], 136850.0)
        self.assertEqual(report['x_formula']['mpesa_paybill'], 107050.0)
        self.assertEqual(report['x_formula']['pdq'], 43300.0)
        self.assertEqual(report['y_formula']['credit'], 4644.0)
        # The whole PDQ intake must no longer surface as a phantom surplus.
        self.assertEqual(report['result'], 0.0)
        self.assertTrue(report['is_balanced'])
