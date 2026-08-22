from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APITestCase
from payments.services.stock_take_service import StockTakeService
from .test_helpers import (
    make_admin, make_issuer, make_processor,
    make_product, make_gateway, make_device,
    make_authenticated_client,
)


class StockTakeAPITest(APITestCase):
    def setUp(self):
        self.admin = make_admin(username='stk_api_admin')
        self.product = make_product(prod_code='API-STK', quantity=100)
        self.gateway = make_gateway()
        self.device = make_device(gateway=self.gateway)
        self.client = make_authenticated_client(self.admin)

    def test_create_session(self):
        response = self.client.post(reverse('stock-take-create-session'), {}, format='json')
        self.assertEqual(response.status_code, 201)

    def test_list_active_sessions(self):
        StockTakeService.create_session(created_by=self.admin)
        response = self.client.get(reverse('stock-take-list-active-sessions'))
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.data), 0)

    def test_cancel_all_active(self):
        StockTakeService.create_session(created_by=self.admin)
        StockTakeService.create_session(created_by=self.admin)
        response = self.client.post(reverse('stock-take-cancel-all-active'), {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_session_detail(self):
        session = StockTakeService.create_session(created_by=self.admin)
        url = reverse('stock-take-session-detail', args=[session.session_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_scan_product(self):
        session = StockTakeService.create_session(created_by=self.admin)
        url = reverse('stock-take-scan-product', args=[session.session_id])
        response = self.client.post(url, {
            'product_id': self.product.id,
            'quantity': 10,
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_complete_session(self):
        session = StockTakeService.create_session(created_by=self.admin)
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=10,
            scanned_by=self.admin,
        )
        url = reverse('stock-take-complete-session', args=[session.session_id])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_complete_session_without_items_fails(self):
        session = StockTakeService.create_session(created_by=self.admin)
        url = reverse('stock-take-complete-session', args=[session.session_id])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_cancel_session(self):
        session = StockTakeService.create_session(created_by=self.admin)
        url = reverse('stock-take-cancel-session', args=[session.session_id])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_update_item_quantity(self):
        session = StockTakeService.create_session(created_by=self.admin)
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=10,
            scanned_by=self.admin,
        )
        item = session.items.first()
        url = reverse('stock-take-update-item', args=[session.session_id, item.id])
        response = self.client.patch(url, {'quantity': 25}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_remove_item(self):
        session = StockTakeService.create_session(created_by=self.admin)
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=10,
            scanned_by=self.admin,
        )
        item = session.items.first()
        url = reverse('stock-take-remove-item', args=[session.session_id, item.id])
        response = self.client.delete(url, {}, format='json')
        self.assertEqual(response.status_code, 200)


class StockTakeRolePermissionTest(APITestCase):
    """Role boundary checks for stock take endpoints."""

    def setUp(self):
        self.admin = make_admin(username='stk_role_admin')
        self.issuer = make_issuer(username='stk_role_issuer')
        self.processor = make_processor(username='stk_role_processor')
        self.product = make_product(prod_code='API-STK-ROLE', quantity=100)

    def _session(self, created_by='admin'):
        return StockTakeService.create_session(created_by=created_by)

    def _cancel_url(self, session=None):
        session = session or self._session()
        return reverse('stock-take-cancel-session', args=[session.session_id])

    # ------------------------------------------------------------------
    # ISSUER is allowed (the stock-take domain belongs to the issuer role)
    # ------------------------------------------------------------------

    def test_issuer_can_list_active_sessions(self):
        self._session()
        client = make_authenticated_client(self.issuer)
        response = client.get(reverse('stock-take-list-active-sessions'))
        self.assertEqual(response.status_code, 200)

    def test_issuer_can_cancel_session(self):
        client = make_authenticated_client(self.issuer)
        response = client.post(self._cancel_url(), {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_issuer_can_cancel_all_active(self):
        self._session()
        self._session()
        client = make_authenticated_client(self.issuer)
        response = client.post(reverse('stock-take-cancel-all-active'), {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get('count'), 2)

    def test_issuer_can_complete_session(self):
        session = self._session()
        StockTakeService.scan_product(
            session_id=session.session_id,
            product_id=self.product.id,
            quantity=10,
            scanned_by=self.issuer,
        )
        client = make_authenticated_client(self.issuer)
        url = reverse('stock-take-complete-session', args=[session.session_id])
        response = client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    # ------------------------------------------------------------------
    # PROCESSOR is denied (stock taking is not a processor action)
    # ------------------------------------------------------------------

    def test_processor_denied_list_active_sessions(self):
        self._session()
        client = make_authenticated_client(self.processor)
        response = client.get(reverse('stock-take-list-active-sessions'))
        self.assertEqual(response.status_code, 403)

    def test_processor_denied_cancel_session(self):
        client = make_authenticated_client(self.processor)
        response = client.post(self._cancel_url(), {}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_processor_denied_cancel_all_active(self):
        self._session()
        client = make_authenticated_client(self.processor)
        response = client.post(reverse('stock-take-cancel-all-active'), {}, format='json')
        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # Unauthenticated / device-only is denied
    # ------------------------------------------------------------------

    def test_unauthenticated_denied_cancel_session(self):
        # No authenticator provides a WWW-Authenticate challenge, so DRF
        # reports anonymous requests as 403 PermissionDenied.
        response = self.client.post(self._cancel_url(), {}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_device_auth_denied_cancel_session(self):
        gateway = make_gateway()
        register = self.client.post(reverse('device-register'), {
            'name': 'Stock Take Device',
            'phone_number': '0711111111',
            'gateway_id': gateway.id,
        }, format='json')
        self.assertEqual(register.status_code, 201)
        raw_key = register.data['api_key']
        device_id = register.data['id']

        response = self.client.post(
            self._cancel_url(),
            {'device': device_id},
            format='json',
            HTTP_X_DEVICE_KEY=raw_key,
        )
        self.assertEqual(response.status_code, 403)
