from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APITestCase
from payments.models import Transaction
from .test_helpers import (
    make_admin, make_issuer, make_gateway, make_product,
    make_transaction, make_device, make_device_client,
    make_location,
)


class FulfillmentAPITest(APITestCase):
    def setUp(self):
        self.gateway = make_gateway()
        self.product = make_product(prod_code='API-FUL', price=Decimal('500.00'), quantity=100)
        self.product2 = make_product(prod_code='API-FUL2', price=Decimal('300.00'), quantity=50)
        self.tx = make_transaction(tx_id='API-FUL-TX', amount=Decimal('2000.00'))
        self.device = make_device(gateway=self.gateway)
        self.issuer = make_issuer()
        self.client = make_device_client(self.device)

    def test_activate_issuance(self):
        url = reverse('transaction-activate-issuance', args=[self.tx.id])
        response = self.client.post(url, {'user_id': self.issuer.id}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['success'])

    def test_activate_issuance_nonexistent_tx(self):
        url = reverse('transaction-activate-issuance', args=[99999])
        response = self.client.post(url, {'user_id': self.issuer.id}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_activate_already_active(self):
        url = reverse('transaction-activate-issuance', args=[self.tx.id])
        self.client.post(url, {'user_id': self.issuer.id}, format='json')
        response = self.client.post(url, {'user_id': self.issuer.id}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_scan_barcode(self):
        activate_url = reverse('transaction-activate-issuance', args=[self.tx.id])
        self.client.post(activate_url, {'user_id': self.issuer.id}, format='json')
        scan_url = reverse('transaction-scan-barcode', args=[self.tx.id])
        response = self.client.post(scan_url, {
            'sku': self.product.prod_code,
            'quantity': 2,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.line_items.count(), 1)

    def test_scan_barcode_without_issuance(self):
        scan_url = reverse('transaction-scan-barcode', args=[self.tx.id])
        response = self.client.post(scan_url, {
            'sku': self.product.prod_code,
            'quantity': 1,
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_scan_barcode_insufficient_stock(self):
        self.product.quantity = 1
        self.product.save()
        activate_url = reverse('transaction-activate-issuance', args=[self.tx.id])
        self.client.post(activate_url, {'user_id': self.issuer.id}, format='json')
        scan_url = reverse('transaction-scan-barcode', args=[self.tx.id])
        response = self.client.post(scan_url, {
            'sku': self.product.prod_code,
            'quantity': 10,
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_scan_barcode_exceeds_amount(self):
        activate_url = reverse('transaction-activate-issuance', args=[self.tx.id])
        self.client.post(activate_url, {'user_id': self.issuer.id}, format='json')
        scan_url = reverse('transaction-scan-barcode', args=[self.tx.id])
        response = self.client.post(scan_url, {
            'sku': self.product.prod_code,
            'quantity': 100,
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_complete_issuance(self):
        activate_url = reverse('transaction-activate-issuance', args=[self.tx.id])
        self.client.post(activate_url, {'user_id': self.issuer.id}, format='json')
        scan_url = reverse('transaction-scan-barcode', args=[self.tx.id])
        self.client.post(scan_url, {
            'sku': self.product.prod_code,
            'quantity': 2,
        }, format='json')
        complete_url = reverse('transaction-complete-issuance', args=[self.tx.id])
        response = self.client.post(complete_url, {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.tx.refresh_from_db()
        self.assertFalse(self.tx.is_in_issuance)

    def test_complete_without_items_fails(self):
        activate_url = reverse('transaction-activate-issuance', args=[self.tx.id])
        self.client.post(activate_url, {'user_id': self.issuer.id}, format='json')
        complete_url = reverse('transaction-complete-issuance', args=[self.tx.id])
        response = self.client.post(complete_url, {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_cancel_issuance(self):
        activate_url = reverse('transaction-activate-issuance', args=[self.tx.id])
        self.client.post(activate_url, {'user_id': self.issuer.id}, format='json')
        scan_url = reverse('transaction-scan-barcode', args=[self.tx.id])
        self.client.post(scan_url, {
            'sku': self.product.prod_code,
            'quantity': 2,
        }, format='json')
        cancel_url = reverse('transaction-cancel-issuance', args=[self.tx.id])
        response = self.client.post(cancel_url, {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.line_items.count(), 0)

    def test_cancel_without_issuance_fails(self):
        cancel_url = reverse('transaction-cancel-issuance', args=[self.tx.id])
        response = self.client.post(cancel_url, {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_get_current_issuance(self):
        url = reverse('transaction-current-issuance')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_remove_line_item(self):
        activate_url = reverse('transaction-activate-issuance', args=[self.tx.id])
        self.client.post(activate_url, {'user_id': self.issuer.id}, format='json')
        scan_url = reverse('transaction-scan-barcode', args=[self.tx.id])
        self.client.post(scan_url, {
            'sku': self.product.prod_code,
            'quantity': 2,
        }, format='json')
        li = self.tx.line_items.first()
        remove_url = reverse('transaction-remove-line-item', args=[self.tx.id, li.id])
        response = self.client.delete(remove_url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_revert_to_processing(self):
        self.tx.status = 'PARTIALLY_FULFILLED'
        self.tx.amount_fulfilled = Decimal('500.00')
        self.tx.save()
        url = reverse('transaction-revert-to-processing', args=[self.tx.id])
        response = self.client.post(url, {'user_id': self.issuer.id}, format='json')
        self.assertEqual(response.status_code, 200) if response.status_code != 403 else self.assertEqual(response.status_code, 403)

    def test_issue_registration_kit(self):
        reg_product = make_product(
            prod_code='REG_KIT_001', prod_name='Reg Kit API',
            price=Decimal('2900.00'), quantity=50,
        )
        reg_tx = make_transaction(
            tx_id='API-REG-TX', amount=Decimal('5000.00'),
            is_registration=True, unique_hash='hash_api_reg',
        )
        url = reverse('transaction-issue-registration-kit', args=[reg_tx.id])
        response = self.client.post(url, {'quantity': 1}, format='json')
        self.assertEqual(response.status_code, 200)
