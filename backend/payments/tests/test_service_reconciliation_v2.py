from decimal import Decimal
from django.test import TransactionTestCase
from django.utils import timezone
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
