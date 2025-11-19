"""
Unit tests for Transaction Fulfillment API endpoints.

Tests the REST API endpoints for scanner-based transaction fulfillment:
- POST /api/v1/transactions/<id>/activate-issuance/
- POST /api/v1/transactions/<id>/scan-barcode/
- POST /api/v1/transactions/<id>/complete-issuance/
- POST /api/v1/transactions/<id>/cancel-issuance/
- GET /api/v1/transactions/current-issuance/
"""

from decimal import Decimal
from django.test import TransactionTestCase
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
import secrets
import hashlib

from payments.models import (
    Transaction, Product, ProductCategory, TransactionLineItem,
    InventoryMovement, PaymentGateway, Device
)


class FulfillmentAPITestCase(TransactionTestCase):
    """Base test case for Fulfillment API tests with authentication setup."""

    @classmethod
    def setUpClass(cls):
        """Set up class-level data (runs once for all tests in the class)."""
        super().setUpClass()
        # Clear all data once for the entire test class
        Transaction.objects.all().delete()
        Product.objects.all().delete()
        ProductCategory.objects.all().delete()
        TransactionLineItem.objects.all().delete()
        InventoryMovement.objects.all().delete()

    def setUp(self):
        """Set up test data and authentication."""
        # Clear data for test isolation
        Transaction.objects.all().delete()
        Product.objects.all().delete()
        ProductCategory.objects.all().delete()
        TransactionLineItem.objects.all().delete()
        InventoryMovement.objects.all().delete()

        # Create gateway
        self.gateway = PaymentGateway.objects.create(
            name='Test Gateway',
            gateway_type=PaymentGateway.GatewayType.MPESA_TILL,
            gateway_number='123456',
            settlement_type=PaymentGateway.SettlementType.NONE
        )

        # Create device with API key
        self.plain_api_key = secrets.token_urlsafe(32)
        self.device = Device.objects.create(
            name='Test Device',
            phone_number='0712345678',
            gateway=self.gateway,
            api_key=make_password(self.plain_api_key)
        )

        # Set up API client with authentication
        self.client = APIClient()
        self.client.credentials(HTTP_X_API_KEY=self.plain_api_key)

        # Create test products
        self.product1 = Product.objects.create(
            prod_code='AP004E',
            prod_name='MicroQ2 Cycle Tablets',
            sku='AP004E',
            sku_name='100 tablets',
            current_price=Decimal('2970.00'),
            cost_price=Decimal('2079.00'),
            current_pv=Decimal('11.00'),
            quantity=100,
            is_active=True
        )

        self.product2 = Product.objects.create(
            prod_code='AP008E',
            prod_name='Consiclean Capsules',
            sku='AP008E',
            sku_name='30s/Box',
            current_price=Decimal('3915.00'),
            cost_price=Decimal('2740.50'),
            current_pv=Decimal('22.00'),
            quantity=50,
            is_active=True
        )

        # Create test transaction
        unique_hash = hashlib.sha256(
            f"TEST001|5000.00|{timezone.now().isoformat()}".encode()
        ).hexdigest()
        self.transaction = Transaction.objects.create(
            tx_id='TEST001',
            amount=Decimal('5000.00'),
            sender_name='JOHN DOE',
            sender_phone='0712345678',
            timestamp=timezone.now(),
            gateway=self.gateway,
            unique_hash=unique_hash,
            status=Transaction.OrderStatus.NOT_PROCESSED
        )


class ActivateIssuanceAPITest(FulfillmentAPITestCase):
    """Test POST /api/v1/transactions/<id>/activate-issuance/"""

    def test_activate_issuance_success(self):
        """Test successfully activating issuance for a transaction."""
        url = f'/api/v1/transactions/{self.transaction.id}/activate-issuance/'
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['tx_id'], 'TEST001')

        # Verify transaction state
        self.transaction.refresh_from_db()
        self.assertTrue(self.transaction.is_in_issuance)
        self.assertEqual(self.transaction.status, Transaction.OrderStatus.PROCESSING)

    def test_activate_issuance_already_active(self):
        """Test that activating when another transaction is in issuance fails."""
        # Activate first transaction
        url1 = f'/api/v1/transactions/{self.transaction.id}/activate-issuance/'
        self.client.post(url1)

        # Create second transaction
        unique_hash = hashlib.sha256(
            f"TEST002|3000.00|{timezone.now().isoformat()}".encode()
        ).hexdigest()
        transaction2 = Transaction.objects.create(
            tx_id='TEST002',
            amount=Decimal('3000.00'),
            sender_name='JANE DOE',
            sender_phone='0723456789',
            timestamp=timezone.now(),
            gateway=self.gateway,
            unique_hash=unique_hash,
            status=Transaction.OrderStatus.NOT_PROCESSED
        )

        # Try to activate second transaction
        url2 = f'/api/v1/transactions/{transaction2.id}/activate-issuance/'
        response = self.client.post(url2)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)
        self.assertIn('is_in_issuance', response.data['error'])

    def test_activate_issuance_locked_transaction(self):
        """Test that locked transactions cannot be activated."""
        # Mark transaction as fulfilled (locked)
        Transaction.objects.filter(id=self.transaction.id).update(
            status=Transaction.OrderStatus.FULFILLED
        )

        url = f'/api/v1/transactions/{self.transaction.id}/activate-issuance/'
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_activate_issuance_nonexistent_transaction(self):
        """Test activating a non-existent transaction."""
        url = '/api/v1/transactions/99999/activate-issuance/'
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ScanBarcodeAPITest(FulfillmentAPITestCase):
    """Test POST /api/v1/transactions/<id>/scan-barcode/"""

    def test_scan_barcode_success(self):
        """Test successfully scanning a product barcode."""
        # Activate issuance first
        activate_url = f'/api/v1/transactions/{self.transaction.id}/activate-issuance/'
        self.client.post(activate_url)

        # Scan product
        scan_url = f'/api/v1/transactions/{self.transaction.id}/scan-barcode/'
        data = {
            'sku': 'AP004E',
            'quantity': 1,
            'scanned_by': 'Test User'
        }
        response = self.client.post(scan_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['product_code'], 'AP004E')
        self.assertEqual(response.data['quantity'], 1)
        self.assertEqual(Decimal(response.data['line_total']), Decimal('2970.00'))

        # Verify line item created
        line_items = TransactionLineItem.objects.filter(transaction=self.transaction)
        self.assertEqual(line_items.count(), 1)

    def test_scan_barcode_without_issuance(self):
        """Test that scanning fails if transaction not in issuance."""
        scan_url = f'/api/v1/transactions/{self.transaction.id}/scan-barcode/'
        data = {'sku': 'AP004E', 'quantity': 1}
        response = self.client.post(scan_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_scan_barcode_exceeds_amount(self):
        """Test that scanning fails if total exceeds transaction amount."""
        # Activate issuance
        activate_url = f'/api/v1/transactions/{self.transaction.id}/activate-issuance/'
        self.client.post(activate_url)

        # Try to scan 2 items (would exceed 5000 limit)
        scan_url = f'/api/v1/transactions/{self.transaction.id}/scan-barcode/'
        data = {'sku': 'AP004E', 'quantity': 2}  # 2 * 2970 = 5940 > 5000
        response = self.client.post(scan_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_scan_barcode_insufficient_stock(self):
        """Test that scanning fails if insufficient stock."""
        # Activate issuance
        activate_url = f'/api/v1/transactions/{self.transaction.id}/activate-issuance/'
        self.client.post(activate_url)

        # Try to scan more than available
        scan_url = f'/api/v1/transactions/{self.transaction.id}/scan-barcode/'
        data = {'sku': 'AP004E', 'quantity': 150}  # Only 100 available
        response = self.client.post(scan_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_scan_barcode_invalid_sku(self):
        """Test that scanning fails for non-existent product."""
        # Activate issuance
        activate_url = f'/api/v1/transactions/{self.transaction.id}/activate-issuance/'
        self.client.post(activate_url)

        # Try to scan non-existent product
        scan_url = f'/api/v1/transactions/{self.transaction.id}/scan-barcode/'
        data = {'sku': 'NOTEXIST', 'quantity': 1}
        response = self.client.post(scan_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_scan_barcode_missing_sku_and_prod_code(self):
        """Test that scanning fails if neither sku nor prod_code provided."""
        # Activate issuance
        activate_url = f'/api/v1/transactions/{self.transaction.id}/activate-issuance/'
        self.client.post(activate_url)

        # Try to scan without sku or prod_code
        scan_url = f'/api/v1/transactions/{self.transaction.id}/scan-barcode/'
        data = {'quantity': 1}
        response = self.client.post(scan_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)


class CompleteIssuanceAPITest(FulfillmentAPITestCase):
    """Test POST /api/v1/transactions/<id>/complete-issuance/"""

    def test_complete_issuance_success(self):
        """Test successfully completing issuance."""
        # Activate and scan products
        activate_url = f'/api/v1/transactions/{self.transaction.id}/activate-issuance/'
        self.client.post(activate_url)

        scan_url = f'/api/v1/transactions/{self.transaction.id}/scan-barcode/'
        self.client.post(scan_url, {'sku': 'AP004E', 'quantity': 1}, format='json')

        # Record initial stock
        initial_stock = self.product1.quantity

        # Complete issuance
        complete_url = f'/api/v1/transactions/{self.transaction.id}/complete-issuance/'
        data = {'performed_by': 'Test User'}
        response = self.client.post(complete_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(len(response.data['inventory_updates']), 1)

        # Verify inventory updated
        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity, initial_stock - 1)

        # Verify transaction no longer in issuance
        self.transaction.refresh_from_db()
        self.assertFalse(self.transaction.is_in_issuance)

    def test_complete_issuance_without_line_items(self):
        """Test that completing issuance fails if no products scanned."""
        # Activate without scanning
        activate_url = f'/api/v1/transactions/{self.transaction.id}/activate-issuance/'
        self.client.post(activate_url)

        # Try to complete without scanning any products
        complete_url = f'/api/v1/transactions/{self.transaction.id}/complete-issuance/'
        response = self.client.post(complete_url, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_complete_issuance_not_in_issuance(self):
        """Test that completing fails if transaction not in issuance."""
        complete_url = f'/api/v1/transactions/{self.transaction.id}/complete-issuance/'
        response = self.client.post(complete_url, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)


class CancelIssuanceAPITest(FulfillmentAPITestCase):
    """Test POST /api/v1/transactions/<id>/cancel-issuance/"""

    def test_cancel_issuance_success(self):
        """Test successfully cancelling issuance."""
        # Activate and scan products
        activate_url = f'/api/v1/transactions/{self.transaction.id}/activate-issuance/'
        self.client.post(activate_url)

        scan_url = f'/api/v1/transactions/{self.transaction.id}/scan-barcode/'
        self.client.post(scan_url, {'sku': 'AP004E', 'quantity': 1}, format='json')

        # Record initial stock
        initial_stock = self.product1.quantity

        # Cancel issuance
        cancel_url = f'/api/v1/transactions/{self.transaction.id}/cancel-issuance/'
        data = {'reason': 'Testing cancellation'}
        response = self.client.post(cancel_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['line_items_removed'], 1)

        # Verify line items deleted
        line_items = TransactionLineItem.objects.filter(transaction=self.transaction)
        self.assertEqual(line_items.count(), 0)

        # Verify inventory NOT changed
        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity, initial_stock)

        # Verify transaction state reset
        self.transaction.refresh_from_db()
        self.assertFalse(self.transaction.is_in_issuance)
        self.assertEqual(self.transaction.amount_fulfilled, Decimal('0.00'))

    def test_cancel_issuance_not_in_issuance(self):
        """Test that cancelling fails if transaction not in issuance."""
        cancel_url = f'/api/v1/transactions/{self.transaction.id}/cancel-issuance/'
        response = self.client.post(cancel_url, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)


class GetCurrentIssuanceAPITest(FulfillmentAPITestCase):
    """Test GET /api/v1/transactions/current-issuance/"""

    def test_get_current_issuance_none(self):
        """Test getting current issuance when none is active."""
        url = '/api/v1/transactions/current-issuance/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['current_issuance'])

    def test_get_current_issuance_active(self):
        """Test getting current issuance when one is active."""
        # Activate issuance
        activate_url = f'/api/v1/transactions/{self.transaction.id}/activate-issuance/'
        self.client.post(activate_url)

        # Get current issuance
        url = '/api/v1/transactions/current-issuance/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data.get('transaction_id'))
        self.assertEqual(response.data['tx_id'], 'TEST001')
        self.assertEqual(response.data['line_items_count'], 0)

    def test_get_current_issuance_with_line_items(self):
        """Test getting current issuance with scanned products."""
        # Activate and scan product
        activate_url = f'/api/v1/transactions/{self.transaction.id}/activate-issuance/'
        self.client.post(activate_url)

        scan_url = f'/api/v1/transactions/{self.transaction.id}/scan-barcode/'
        self.client.post(scan_url, {'sku': 'AP004E', 'quantity': 1}, format='json')

        # Get current issuance
        url = '/api/v1/transactions/current-issuance/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['line_items_count'], 1)
        self.assertEqual(len(response.data['line_items']), 1)
        self.assertEqual(response.data['line_items'][0]['product_code'], 'AP004E')
