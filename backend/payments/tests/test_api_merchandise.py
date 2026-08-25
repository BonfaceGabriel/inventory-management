from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APITestCase
from payments.models import (
    MerchandiseCatalogItem, MerchandiseCatalogOption,
    MerchandiseStock, MerchandiseOrder,
)
from .test_helpers import (
    make_admin, make_processor, make_issuer, make_gateway, make_transaction, make_device,
    make_authenticated_client, make_device_client,
)


class MerchandiseAPITest(APITestCase):
    def setUp(self):
        self.admin = make_admin(username='merch_api_admin')
        self.client = make_authenticated_client(self.admin)
        self.merch_gw = make_gateway(
            name='Merch API GW', gateway_type='MERCHANDISE', gateway_number='MERCH-API',
        )
        self.item = MerchandiseCatalogItem.objects.create(
            code='TSHIRT-API', name='API T-Shirt',
            item_type='TSHIRT', unit_price=Decimal('1500.00'),
        )
        MerchandiseCatalogOption.objects.create(item=self.item, option_type='COLOR', value='Red')
        MerchandiseCatalogOption.objects.create(item=self.item, option_type='SIZE', value='Large')
        self.stock = MerchandiseStock.objects.create(
            item=self.item, color='Red', size='Large', quantity=20,
        )

    def test_catalog_list(self):
        response = self.client.get(reverse('merchandise-catalog'))
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.data), 0)

    def test_pending_orders(self):
        response = self.client.get(reverse('merchandise-pending-orders'))
        self.assertEqual(response.status_code, 200)

    def test_stock_list(self):
        response = self.client.get(reverse('merchandise-stock-list'))
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.data), 0)

    def test_adjust_stock_add(self):
        response = self.client.post(reverse('merchandise-stock-adjust'), {
            'adjustments': [{
                'stock_id': self.stock.id,
                'quantity_change': 10,
            }],
            'notes': 'Restock via API',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 30)

    def test_adjust_stock_deduct(self):
        response = self.client.post(reverse('merchandise-stock-adjust'), {
            'adjustments': [{
                'stock_id': self.stock.id,
                'quantity_change': -5,
            }],
            'notes': 'Damaged',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 15)

    def test_stock_movements(self):
        response = self.client.get(reverse('merchandise-stock-movements'))
        self.assertEqual(response.status_code, 200)

    def test_daily_report(self):
        response = self.client.get(reverse('merchandise-daily-report'), {
            'date': '2026-05-26',
        })
        self.assertEqual(response.status_code, 200)

    def test_fulfill_order(self):
        tx = make_transaction(
            tx_id='MERCH-API-ORD', amount=Decimal('3000.00'), gateway=self.merch_gw,
        )
        order = MerchandiseOrder.objects.create(transaction=tx, gateway=self.merch_gw)
        url = reverse('merchandise-fulfill-order', args=[order.id])
        response = self.client.post(url, {
            'lines': [{
                'item_id': self.item.id,
                'quantity': 2,
                'color': 'Red',
                'size': 'Large',
            }],
        }, format='json')
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'FULFILLED')

    def test_order_detail(self):
        tx = make_transaction(
            tx_id='MERCH-API-DET', amount=Decimal('3000.00'), gateway=self.merch_gw,
            unique_hash='hash_merch_api_det',
        )
        order = MerchandiseOrder.objects.create(transaction=tx, gateway=self.merch_gw)
        url = reverse('merchandise-order-detail', args=[order.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_unauthenticated_access_fails(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        response = anon.get(reverse('merchandise-catalog'))
        self.assertEqual(response.status_code, 401)


class MerchandiseManualClassificationTest(APITestCase):
    """Mark-as-merchandise flow for shared-till payments (no dedicated merch till)."""

    def setUp(self):
        self.till_gw = make_gateway(
            name='Till Products', gateway_type='MPESA_TILL', gateway_number='555000',
        )
        self.merch_gw = make_gateway(
            name='Till Merchandise', gateway_type='MERCHANDISE', gateway_number='555001',
        )
        self.paybill_gw = make_gateway(
            name='Paybill Parent Company', gateway_type='MPESA_PAYBILL', gateway_number='555002',
        )
        self.pdq_gw = make_gateway(
            name='PDQ/Card Payment', gateway_type='PDQ', gateway_number='555003',
        )
        self.tx = make_transaction(
            tx_id='TILL-MERCH-01', amount=Decimal('3000.00'), gateway=self.till_gw,
        )

    def test_processor_can_mark_till_transaction_as_merchandise(self):
        client = make_authenticated_client(make_processor(username='merch_proc'))
        response = client.post(
            reverse('merchandise-create-order-for-transaction', args=[self.tx.id]),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'PENDING')
        self.assertTrue(MerchandiseOrder.objects.filter(transaction=self.tx).exists())

    def test_admin_can_mark_till_transaction_as_merchandise(self):
        client = make_authenticated_client(make_admin(username='merch_admin'))
        response = client.post(
            reverse('merchandise-create-order-for-transaction', args=[self.tx.id]),
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(MerchandiseOrder.objects.filter(transaction=self.tx).exists())

    def test_issuer_cannot_mark_transaction_as_merchandise(self):
        client = make_authenticated_client(make_issuer(username='merch_issuer'))
        response = client.post(
            reverse('merchandise-create-order-for-transaction', args=[self.tx.id]),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(MerchandiseOrder.objects.filter(transaction=self.tx).exists())

    def test_double_mark_returns_400(self):
        client = make_authenticated_client(make_processor(username='merch_proc2'))
        first = client.post(
            reverse('merchandise-create-order-for-transaction', args=[self.tx.id]),
        )
        self.assertEqual(first.status_code, 201)
        second = client.post(
            reverse('merchandise-create-order-for-transaction', args=[self.tx.id]),
        )
        self.assertEqual(second.status_code, 400)

    def test_fulfilled_transaction_cannot_be_marked(self):
        tx = make_transaction(
            tx_id='TILL-MERCH-FUL', amount=Decimal('1500.00'), gateway=self.till_gw,
            status='FULFILLED', unique_hash='hash_till_merch_ful',
            amount_fulfilled=Decimal('1500.00'),
        )
        client = make_authenticated_client(make_processor(username='merch_proc3'))
        response = client.post(
            reverse('merchandise-create-order-for-transaction', args=[tx.id]),
        )
        self.assertEqual(response.status_code, 400)

    def test_cancelled_transaction_cannot_be_marked(self):
        tx = make_transaction(
            tx_id='TILL-MERCH-CAN', amount=Decimal('1500.00'), gateway=self.till_gw,
            status='CANCELLED', unique_hash='hash_till_merch_can',
        )
        client = make_authenticated_client(make_processor(username='merch_proc5'))
        response = client.post(
            reverse('merchandise-create-order-for-transaction', args=[tx.id]),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(MerchandiseOrder.objects.filter(transaction=tx).exists())

    def test_partially_fulfilled_transaction_cannot_be_marked(self):
        tx = make_transaction(
            tx_id='TILL-MERCH-PAR', amount=Decimal('1500.00'), gateway=self.till_gw,
            status='PARTIALLY_FULFILLED', unique_hash='hash_till_merch_par',
            amount_fulfilled=Decimal('500.00'),
        )
        client = make_authenticated_client(make_processor(username='merch_proc6'))
        response = client.post(
            reverse('merchandise-create-order-for-transaction', args=[tx.id]),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(MerchandiseOrder.objects.filter(transaction=tx).exists())

    def test_non_till_transaction_cannot_be_marked(self):
        for gw, tx_id in [
            (self.paybill_gw, 'PB-MERCH-01'),
            (self.pdq_gw, 'PDQ-MERCH-01'),
        ]:
            tx = make_transaction(
                tx_id=tx_id, amount=Decimal('2000.00'), gateway=gw,
                unique_hash=f'hash_{tx_id}',
            )
            self.assertNotEqual(tx.gateway_type, 'MPESA_TILL')
            client = make_authenticated_client(
                make_processor(username=f'merch_proc_{tx_id.lower()}')
            )
            response = client.post(
                reverse('merchandise-create-order-for-transaction', args=[tx.id]),
            )
            self.assertEqual(response.status_code, 400)
            self.assertFalse(MerchandiseOrder.objects.filter(transaction=tx).exists())

    def test_missing_transaction_returns_404(self):
        client = make_authenticated_client(make_processor(username='merch_proc4'))
        response = client.post(
            reverse('merchandise-create-order-for-transaction', args=[999999]),
        )
        self.assertEqual(response.status_code, 404)

    def test_issuer_queue_excludes_merchandise_transactions(self):
        make_transaction(
            tx_id='TILL-PROD-01', amount=Decimal('1000.00'), gateway=self.till_gw,
            status='PROCESSING', is_in_issuance=True, unique_hash='hash_till_prod_01',
        )
        client = make_authenticated_client(make_issuer(username='merch_queue_issuer'))
        response = client.get(reverse('transaction-list'))
        self.assertEqual(response.status_code, 200)
        tx_ids = {item['tx_id'] for item in response.data['results']}
        self.assertNotIn('TILL-MERCH-01', tx_ids)
        self.assertIn('TILL-PROD-01', tx_ids)

    def test_activation_blocked_for_merchandise_transaction(self):
        MerchandiseOrder.objects.create(transaction=self.tx, gateway=self.till_gw)
        client = make_authenticated_client(make_issuer(username='merch_act_issuer'))
        response = client.post(
            reverse('transaction-activate-issuance', args=[self.tx.id]),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('merchandise', response.data['error'].lower())

    def test_marked_transaction_displays_as_merch(self):
        MerchandiseOrder.objects.create(transaction=self.tx, gateway=self.till_gw)
        client = make_authenticated_client(make_admin(username='merch_disp_admin'))
        response = client.get(reverse('transaction-detail', args=[self.tx.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['gateway_type'], 'MERCH')
        self.assertTrue(response.data['is_merchandise'])

    def test_unmarked_till_transaction_displays_real_gateway(self):
        client = make_authenticated_client(make_admin(username='merch_disp_admin2'))
        response = client.get(reverse('transaction-detail', args=[self.tx.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['gateway_type'], 'MPESA_TILL')
        self.assertFalse(response.data['is_merchandise'])

    def test_till_type_filter_excludes_marked_transactions(self):
        make_transaction(
            tx_id='TILL-PROD-FILT', amount=Decimal('1000.00'), gateway=self.till_gw,
            unique_hash='hash_till_prod_filt',
        )
        MerchandiseOrder.objects.create(transaction=self.tx, gateway=self.till_gw)
        client = make_authenticated_client(make_admin(username='merch_filt_admin'))

        response = client.get(reverse('transaction-list'), {'gateway_type': 'MPESA_TILL'})
        self.assertEqual(response.status_code, 200)
        tx_ids = {item['tx_id'] for item in response.data['results']}
        self.assertNotIn('TILL-MERCH-01', tx_ids)
        self.assertIn('TILL-PROD-FILT', tx_ids)

    def test_merchandise_type_filter_includes_marked_transactions(self):
        MerchandiseOrder.objects.create(transaction=self.tx, gateway=self.till_gw)
        client = make_authenticated_client(make_admin(username='merch_filt_admin2'))

        response = client.get(reverse('transaction-list'), {'gateway_type': 'MERCHANDISE'})
        self.assertEqual(response.status_code, 200)
        tx_ids = {item['tx_id'] for item in response.data['results']}
        self.assertIn('TILL-MERCH-01', tx_ids)

    def test_till_gateway_id_filter_excludes_marked_transactions(self):
        make_transaction(
            tx_id='TILL-PROD-GW', amount=Decimal('1000.00'), gateway=self.till_gw,
            unique_hash='hash_till_prod_gw',
        )
        MerchandiseOrder.objects.create(transaction=self.tx, gateway=self.till_gw)
        client = make_authenticated_client(make_admin(username='merch_gwfilt_admin'))

        response = client.get(reverse('transaction-list'), {'gateway_id': self.till_gw.id})
        self.assertEqual(response.status_code, 200)
        tx_ids = {item['tx_id'] for item in response.data['results']}
        self.assertNotIn('TILL-MERCH-01', tx_ids)
        self.assertIn('TILL-PROD-GW', tx_ids)

    def test_merch_gateway_id_filter_includes_marked_transactions(self):
        MerchandiseOrder.objects.create(transaction=self.tx, gateway=self.till_gw)
        client = make_authenticated_client(make_admin(username='merch_gwfilt_admin2'))

        response = client.get(reverse('transaction-list'), {'gateway_id': self.merch_gw.id})
        self.assertEqual(response.status_code, 200)
        tx_ids = {item['tx_id'] for item in response.data['results']}
        self.assertIn('TILL-MERCH-01', tx_ids)

    def test_is_merchandise_filter(self):
        make_transaction(
            tx_id='TILL-PLAIN-ISMERCH', amount=Decimal('500.00'), gateway=self.till_gw,
            unique_hash='hash_till_plain_ismerch',
        )
        MerchandiseOrder.objects.create(transaction=self.tx, gateway=self.till_gw)
        client = make_authenticated_client(make_admin(username='merch_ismerch_admin'))

        response = client.get(reverse('transaction-list'), {'is_merchandise': 'true'})
        self.assertEqual(response.status_code, 200)
        tx_ids = {item['tx_id'] for item in response.data['results']}
        self.assertIn('TILL-MERCH-01', tx_ids)
        self.assertNotIn('TILL-PLAIN-ISMERCH', tx_ids)

        response = client.get(reverse('transaction-list'), {'is_merchandise': 'false'})
        self.assertEqual(response.status_code, 200)
        tx_ids = {item['tx_id'] for item in response.data['results']}
        self.assertNotIn('TILL-MERCH-01', tx_ids)
        self.assertIn('TILL-PLAIN-ISMERCH', tx_ids)


class MerchandiseFulfillmentStockTest(APITestCase):
    """Out-of-stock error handling for merchandise fulfillment."""

    def setUp(self):
        self.admin = make_admin(username='merch_stock_admin')
        self.client = make_authenticated_client(self.admin)
        self.till_gw = make_gateway(
            name='Till Products', gateway_type='MPESA_TILL', gateway_number='555000',
        )
        self.tshirt = MerchandiseCatalogItem.objects.create(
            code='TSHIRT-STOCK', name='Stock Set',
            item_type='SET', unit_price=Decimal('1500.00'),
        )
        MerchandiseCatalogOption.objects.create(item=self.tshirt, option_type='COLOR', value='Red')
        MerchandiseCatalogOption.objects.create(item=self.tshirt, option_type='COLOR', value='Blue')
        MerchandiseCatalogOption.objects.create(item=self.tshirt, option_type='SIZE', value='Large')
        MerchandiseStock.objects.create(item=self.tshirt, color='Red', size='Large', quantity=2)

    def _make_pending_order(self, amount=Decimal('3000.00'), tx_id='STOCK-TX-01'):
        tx = make_transaction(
            tx_id=tx_id, amount=amount, gateway=self.till_gw,
            unique_hash=f'hash_{tx_id}',
        )
        return MerchandiseOrder.objects.create(transaction=tx, gateway=self.till_gw)

    def _fulfill(self, order, lines):
        return self.client.post(
            reverse('merchandise-fulfill-order', args=[order.id]),
            {'lines': lines}, format='json',
        )

    def test_insufficient_stock_returns_400_with_details(self):
        order = self._make_pending_order(amount=Decimal('4500.00'))
        response = self._fulfill(order, [
            {'item_code': 'TSHIRT-STOCK', 'quantity': 3, 'color': 'Red', 'size': 'Large'},
        ])
        self.assertEqual(response.status_code, 400)
        messages = ' '.join(response.data['error']['stock'])
        self.assertIn('Available: 2', messages)
        self.assertIn('requested: 3', messages)
        detail = response.data['stock_details'][0]
        self.assertEqual(detail['item_code'], 'TSHIRT-STOCK')
        self.assertEqual(detail['available'], 2)
        self.assertEqual(detail['requested'], 3)

        order.refresh_from_db()
        self.assertEqual(order.status, 'PENDING')
        stock = MerchandiseStock.objects.get(item=self.tshirt, color='Red', size='Large')
        self.assertEqual(stock.quantity, 2)

    def test_multiple_shortages_reported_together(self):
        order = self._make_pending_order(tx_id='STOCK-TX-02')
        response = self._fulfill(order, [
            {'item_code': 'TSHIRT-STOCK', 'quantity': 5, 'color': 'Red', 'size': 'Large'},
            {'item_code': 'TSHIRT-STOCK', 'quantity': 1, 'color': 'Blue', 'size': 'Large'},
        ])
        self.assertEqual(response.status_code, 400)
        errors = ' '.join(response.data['error']['stock'])
        self.assertIn('Stock Set (Red / Large)', errors)
        self.assertIn('Stock Set (Blue / Large)', errors)
        self.assertEqual(len(response.data['stock_details']), 2)

    def test_duplicate_lines_aggregated_against_stock(self):
        order = self._make_pending_order(amount=Decimal('6000.00'), tx_id='STOCK-TX-03')
        response = self._fulfill(order, [
            {'item_code': 'TSHIRT-STOCK', 'quantity': 1, 'color': 'Red', 'size': 'Large'},
            {'item_code': 'TSHIRT-STOCK', 'quantity': 2, 'color': 'Red', 'size': 'Large'},
        ])
        self.assertEqual(response.status_code, 400)
        errors = ' '.join(response.data['error']['stock'])
        self.assertIn('Available: 2, requested: 3', errors)
        self.assertEqual(len(response.data['stock_details']), 1)

    def test_unknown_variant_treated_as_zero_without_creating_row(self):
        order = self._make_pending_order(tx_id='STOCK-TX-04')
        response = self._fulfill(order, [
            {'item_code': 'TSHIRT-STOCK', 'quantity': 1, 'color': 'Blue', 'size': 'Large'},
        ])
        self.assertEqual(response.status_code, 400)
        messages = ' '.join(response.data['error']['stock'])
        self.assertIn('Available: 0, requested: 1', messages)
        self.assertFalse(
            MerchandiseStock.objects.filter(item=self.tshirt, color='Blue').exists()
        )

    def test_fulfillment_within_stock_succeeds_and_deducts(self):
        order = self._make_pending_order(amount=Decimal('3000.00'))
        response = self._fulfill(order, [
            {'item_code': 'TSHIRT-STOCK', 'quantity': 2, 'color': 'Red', 'size': 'Large'},
        ])
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'FULFILLED')
        stock = MerchandiseStock.objects.get(item=self.tshirt, color='Red', size='Large')
        self.assertEqual(stock.quantity, 0)

