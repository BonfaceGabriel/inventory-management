from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APITestCase
from payments.models import (
    MerchandiseCatalogItem, MerchandiseCatalogOption,
    MerchandiseStock, MerchandiseOrder, MerchandiseOrderLine,
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
            unit_price=Decimal('1500.00'),
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
                'item_code': self.item.code,
                'quantity_change': 10,
                'color': 'Red',
                'size': 'Large',
            }],
            'notes': 'Restock via API',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 30)

    def test_adjust_stock_deduct(self):
        response = self.client.post(reverse('merchandise-stock-adjust'), {
            'adjustments': [{
                'item_code': self.item.code,
                'quantity_change': -5,
                'color': 'Red',
                'size': 'Large',
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
                'item_code': self.item.code,
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


class MerchandiseCatalogItemDeleteTest(APITestCase):
    """Items used by orders are archived; unused items are hard deleted."""

    def setUp(self):
        self.admin = make_admin(username='merch_del_admin')
        self.client = make_authenticated_client(self.admin)
        self.gateway = make_gateway(
            name='Till Merchandise', gateway_type='MERCHANDISE', gateway_number='MERCH-DEL',
        )

    def _make_used_item(self, code='USED-ITEM'):
        item = MerchandiseCatalogItem.objects.create(
            code=code, name='Used Item', unit_price=Decimal('1000.00'),
        )
        tx = make_transaction(
            tx_id=f'TX-{code}', amount=Decimal('1000.00'), gateway=self.gateway,
            unique_hash=f'hash_{code}',
        )
        order = MerchandiseOrder.objects.create(transaction=tx, gateway=self.gateway)
        MerchandiseOrderLine.objects.create(
            order=order, item=item, quantity=1,
            unit_price_snapshot=Decimal('1000.00'), line_total=Decimal('1000.00'),
        )
        return item

    def test_delete_used_item_archives_instead(self):
        item = self._make_used_item()
        response = self.client.delete(
            reverse('merchandise-catalog-item-detail', args=[item.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['archived'])

        item.refresh_from_db()
        self.assertFalse(item.is_active)
        # History survives.
        self.assertEqual(item.order_lines.count(), 1)

    def test_delete_unused_item_removes_it(self):
        item = MerchandiseCatalogItem.objects.create(
            code='UNUSED-ITEM', name='Unused Item', unit_price=Decimal('500.00'),
        )
        response = self.client.delete(
            reverse('merchandise-catalog-item-detail', args=[item.id])
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(MerchandiseCatalogItem.objects.filter(id=item.id).exists())

    def test_archived_item_disappears_from_catalog(self):
        item = self._make_used_item(code='HIDE-ITEM')
        self.client.delete(reverse('merchandise-catalog-item-detail', args=[item.id]))

        response = self.client.get(reverse('merchandise-catalog'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('HIDE-ITEM', [row['code'] for row in response.data])

    def test_archived_item_disappears_from_stock(self):
        item = self._make_used_item(code='HIDE-STOCK')
        MerchandiseStock.objects.create(item=item, quantity=7)
        self.client.delete(reverse('merchandise-catalog-item-detail', args=[item.id]))

        response = self.client.get(reverse('merchandise-stock-list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('HIDE-STOCK', [row['item_code'] for row in response.data])

    def test_catalog_marks_used_items(self):
        item = self._make_used_item(code='USED-FLAG')
        response = self.client.get(reverse('merchandise-catalog'))
        row = next(row for row in response.data if row['code'] == 'USED-FLAG')
        self.assertTrue(row['is_used'])
        self.assertFalse(row['has_variants'])


class MerchandiseVariantTest(APITestCase):
    """Variants come from declared colour/size options, not a fixed type."""

    def setUp(self):
        self.admin = make_admin(username='merch_var_admin')
        self.client = make_authenticated_client(self.admin)

    def _create(self, code, options):
        response = self.client.post(
            reverse('merchandise-catalog'),
            {
                'code': code,
                'name': f'Item {code}',
                'unit_price': '750.00',
                'options': options,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def test_color_only_item_lists_one_stock_row_per_color(self):
        self._create('HAT-COLORS', [
            {'option_type': 'COLOR', 'value': 'Black'},
            {'option_type': 'COLOR', 'value': 'White'},
        ])
        response = self.client.get(reverse('merchandise-stock-list'))
        rows = [row for row in response.data if row['item_code'] == 'HAT-COLORS']
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            sorted(row['color'] for row in rows), ['Black', 'White']
        )
        self.assertTrue(all(row['size'] is None for row in rows))

    def test_size_only_item_lists_one_stock_row_per_size(self):
        self._create('SHIRT-SIZES', [
            {'option_type': 'SIZE', 'value': 'S'},
            {'option_type': 'SIZE', 'value': 'M'},
            {'option_type': 'SIZE', 'value': 'L'},
        ])
        response = self.client.get(reverse('merchandise-stock-list'))
        rows = [row for row in response.data if row['item_code'] == 'SHIRT-SIZES']
        self.assertEqual(len(rows), 3)
        self.assertEqual(sorted(row['size'] for row in rows), ['L', 'M', 'S'])
        self.assertTrue(all(row['color'] is None for row in rows))

    def test_size_only_item_rejects_colour(self):
        self._create('SHIRT-NOCOLOR', [{'option_type': 'SIZE', 'value': 'M'}])
        response = self.client.post(reverse('merchandise-stock-adjust'), {
            'adjustments': [{
                'item_code': 'SHIRT-NOCOLOR',
                'quantity_change': 3,
                'color': 'Red',
            }],
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('color', response.data['error'])

    def test_color_and_size_item_lists_full_matrix(self):
        self._create('SHIRT-MATRIX', [
            {'option_type': 'COLOR', 'value': 'Red'},
            {'option_type': 'COLOR', 'value': 'Blue'},
            {'option_type': 'SIZE', 'value': 'S'},
            {'option_type': 'SIZE', 'value': 'M'},
        ])
        response = self.client.get(reverse('merchandise-stock-list'))
        rows = [row for row in response.data if row['item_code'] == 'SHIRT-MATRIX']
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            sorted((row['color'], row['size']) for row in rows),
            [('Blue', 'M'), ('Blue', 'S'), ('Red', 'M'), ('Red', 'S')],
        )

    def test_plain_item_has_single_stock_row(self):
        self._create('COFFEE-PLAIN', [])
        response = self.client.get(reverse('merchandise-stock-list'))
        rows = [row for row in response.data if row['item_code'] == 'COFFEE-PLAIN']
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['color'])
        self.assertIsNone(rows[0]['size'])

    def test_adjust_stock_rejects_colour_not_declared(self):
        self._create('COFFEE-STRICT', [])
        response = self.client.post(reverse('merchandise-stock-adjust'), {
            'adjustments': [{
                'item_code': 'COFFEE-STRICT',
                'quantity_change': 5,
                'color': 'Red',
            }],
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('color', response.data['error'])

    def test_adjust_stock_requires_declared_colour(self):
        self._create('CAP-REQ', [{'option_type': 'COLOR', 'value': 'Black'}])
        response = self.client.post(reverse('merchandise-stock-adjust'), {
            'adjustments': [{
                'item_code': 'CAP-REQ',
                'quantity_change': 5,
            }],
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('color', response.data['error'])

    def test_adjust_stock_accepts_declared_colour(self):
        self._create('CAP-OK', [{'option_type': 'COLOR', 'value': 'Black'}])
        response = self.client.post(reverse('merchandise-stock-adjust'), {
            'adjustments': [{
                'item_code': 'CAP-OK',
                'quantity_change': 5,
                'color': 'Black',
            }],
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        stock = MerchandiseStock.objects.get(item__code='CAP-OK', color='Black')
        self.assertEqual(stock.quantity, 5)

    def test_catalog_response_has_no_item_type(self):
        self._create('NO-TYPE', [])
        response = self.client.get(reverse('merchandise-catalog'))
        row = next(row for row in response.data if row['code'] == 'NO-TYPE')
        self.assertNotIn('item_type', row)

    def test_create_item_without_item_type_succeeds(self):
        response = self.client.post(
            reverse('merchandise-catalog'),
            {'code': 'NOTYPE-CREATE', 'name': 'No Type', 'unit_price': '250.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data['has_variants'])


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
        self.assertEqual(response.data['merchandise_order']['status'], 'PENDING')
        self.assertEqual(response.data['merchandise_order']['lines'], [])

    def test_unmarked_transaction_has_null_merchandise_order(self):
        client = make_authenticated_client(make_admin(username='merch_disp_admin3'))
        response = client.get(reverse('transaction-detail', args=[self.tx.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['merchandise_order'])

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
            unit_price=Decimal('1500.00'),
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

        # Transaction detail should expose the fulfilled merch line items
        detail = self.client.get(reverse('transaction-detail', args=[order.transaction.id]))
        self.assertEqual(detail.status_code, 200)
        merch = detail.data['merchandise_order']
        self.assertEqual(merch['status'], 'FULFILLED')
        self.assertEqual(len(merch['lines']), 1)
        line = merch['lines'][0]
        self.assertEqual(line['item_code'], 'TSHIRT-STOCK')
        self.assertEqual(line['quantity'], 2)
        self.assertEqual(line['color'], 'Red')
        self.assertEqual(line['size'], 'Large')
