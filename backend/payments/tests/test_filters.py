from decimal import Decimal
from django.test import TestCase
from payments.filters import TransactionFilter
from payments.models import Transaction
from .test_helpers import (
    make_gateway, make_transaction, make_device, today,
)


class TransactionFilterTest(TestCase):
    def setUp(self):
        self.till_gw = make_gateway(
            name='Filter Till', gateway_type='MPESA_TILL', gateway_number='FILTER-TILL',
        )
        self.paybill_gw = make_gateway(
            name='Filter Paybill', gateway_type='MPESA_PAYBILL', gateway_number='FILTER-PB',
        )
        self.tx1 = make_transaction(
            tx_id='FIL-TX1', amount=Decimal('1000.00'),
            gateway=self.till_gw, status='NOT_PROCESSED',
            sender_name='Alice', sender_phone='0711111111',
        )
        self.tx2 = make_transaction(
            tx_id='FIL-TX2', amount=Decimal('500.00'),
            gateway=self.till_gw, status='PROCESSING',
            sender_name='Bob', sender_phone='0722222222',
            unique_hash='hash_fil2',
        )
        self.tx3 = make_transaction(
            tx_id='FIL-TX3', amount=Decimal('2000.00'),
            gateway=self.paybill_gw, status='FULFILLED',
            sender_name='Charlie', sender_phone='0733333333',
            amount_fulfilled=Decimal('2000.00'),
            unique_hash='hash_fil3',
        )
        self.device = make_device(gateway=self.till_gw)

    def _filter(self, params):
        qs = Transaction.objects.all()
        f = TransactionFilter(params, queryset=qs)
        return f.qs

    def test_filter_by_status(self):
        qs = self._filter({'status': 'NOT_PROCESSED'})
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().tx_id, 'FIL-TX1')

    def test_filter_by_multiple_statuses(self):
        qs = self._filter({'status__in': 'NOT_PROCESSED,PROCESSING'})
        self.assertEqual(qs.count(), 2)

    def test_filter_by_amount_min(self):
        qs = self._filter({'amount_min': '1000'})
        for t in qs:
            self.assertGreaterEqual(t.amount, Decimal('1000.00'))

    def test_filter_by_amount_max(self):
        qs = self._filter({'amount_max': '1000'})
        for t in qs:
            self.assertLessEqual(t.amount, Decimal('1000.00'))

    def test_filter_by_amount_range(self):
        qs = self._filter({'amount_min': '500', 'amount_max': '1500'})
        self.assertEqual(qs.count(), 2)

    def test_filter_by_date_min(self):
        qs = self._filter({'date_min': today().isoformat()})
        self.assertEqual(qs.count(), 3)

    def test_filter_by_date_max(self):
        qs = self._filter({'date_max': today().isoformat()})
        self.assertEqual(qs.count(), 3)

    def test_filter_by_gateway_type(self):
        qs = self._filter({'gateway_type': 'MPESA_TILL'})
        self.assertEqual(qs.count(), 2)

    def test_filter_by_gateway_type_paybill(self):
        qs = self._filter({'gateway_type': 'MPESA_PAYBILL'})
        self.assertEqual(qs.count(), 1)

    def test_filter_search_by_sender_name(self):
        qs = self._filter({'search': 'Alice'})
        self.assertEqual(qs.count(), 1)

    def test_filter_search_by_phone(self):
        qs = self._filter({'search': '0722222222'})
        self.assertEqual(qs.count(), 1)

    def test_filter_search_by_tx_id(self):
        qs = self._filter({'search': 'FIL-TX1'})
        self.assertEqual(qs.count(), 1)

    def test_filter_combined_filters(self):
        qs = self._filter({'status': 'FULFILLED', 'amount_min': '1500'})
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().tx_id, 'FIL-TX3')

    def test_filter_ordering_by_amount(self):
        qs = self._filter({'ordering': 'amount'})
        amounts = list(qs.values_list('amount', flat=True))
        self.assertEqual(amounts, sorted(amounts))

    def test_filter_ordering_descending(self):
        qs = self._filter({'ordering': '-amount'})
        amounts = list(qs.values_list('amount', flat=True))
        self.assertEqual(amounts, sorted(amounts, reverse=True))

    def test_filter_no_params_returns_all(self):
        qs = self._filter({})
        self.assertEqual(qs.count(), 3)

    def test_filter_by_confidence(self):
        qs = self._filter({'confidence_min': '0.5'})
        self.assertEqual(qs.count(), 3)
