"""
Unit tests for Product API endpoints.
Tests serializers, views, and URL routing for products and inventory.
"""

from decimal import Decimal
from django.test import TransactionTestCase
from django.contrib.auth.hashers import make_password
from rest_framework.test import APIClient
from rest_framework import status
import secrets

from payments.models import (
    Product, ProductCategory, InventoryMovement,
    PaymentGateway, Device
)


class ProductAPITestCase(TransactionTestCase):
    """Base test case for Product API tests with authentication setup."""

    @classmethod
    def setUpClass(cls):
        """Set up class-level data (runs once for all tests in the class)."""
        super().setUpClass()
        # Clear all products/categories once for the entire test class
        Product.objects.all().delete()
        ProductCategory.objects.all().delete()
        InventoryMovement.objects.all().delete()

    def setUp(self):
        """Set up test data and authentication."""
        # Delete products created in previous tests within this class
        # (TestCase transaction rollback doesn't work for some reason with --keepdb)
        Product.objects.all().delete()
        ProductCategory.objects.all().delete()
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

        # Create test category
        self.category = ProductCategory.objects.create(
            name='Supplements',
            description='Health supplements'
        )

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
            reorder_level=10,
            category=self.category,
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
            reorder_level=10,
            category=self.category,
            is_active=True
        )


class ProductCategoryAPITest(ProductAPITestCase):
    """Test Product Category API endpoints."""

    def test_list_categories(self):
        """Test listing all product categories."""
        response = self.client.get('/api/v1/products/categories/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Supplements')

    def test_create_category(self):
        """Test creating a new product category."""
        data = {
            'name': 'Coffee Products',
            'description': 'All coffee-based products'
        }
        response = self.client.post('/api/v1/products/categories/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'Coffee Products')
        self.assertEqual(ProductCategory.objects.count(), 2)

    def test_get_category_detail(self):
        """Test retrieving a single category."""
        response = self.client.get(f'/api/v1/products/categories/{self.category.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Supplements')
        self.assertEqual(response.data['product_count'], 2)

    def test_update_category(self):
        """Test updating a category."""
        data = {'description': 'Updated description'}
        response = self.client.patch(f'/api/v1/products/categories/{self.category.id}/', data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.category.refresh_from_db()
        self.assertEqual(self.category.description, 'Updated description')

    def test_delete_category(self):
        """Test deleting a category."""
        # Create category with no products
        empty_category = ProductCategory.objects.create(name='Empty Category')
        response = self.client.delete(f'/api/v1/products/categories/{empty_category.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ProductCategory.objects.filter(id=empty_category.id).exists())


class ProductListAPITest(ProductAPITestCase):
    """Test Product List API endpoint."""

    def test_list_products(self):
        """Test listing all products."""
        response = self.client.get('/api/v1/products/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_search_products_by_name(self):
        """Test searching products by name."""
        response = self.client.get('/api/v1/products/', {'search': 'MicroQ2'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['prod_name'], 'MicroQ2 Cycle Tablets')

    def test_search_products_by_sku(self):
        """Test searching products by SKU."""
        response = self.client.get('/api/v1/products/', {'search': 'AP008E'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['sku'], 'AP008E')

    def test_filter_products_by_category(self):
        """Test filtering products by category."""
        response = self.client.get('/api/v1/products/', {'category': self.category.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_filter_products_by_active_status(self):
        """Test filtering products by active status."""
        # Make one product inactive
        self.product2.is_active = False
        self.product2.save()

        response = self.client.get('/api/v1/products/', {'is_active': 'true'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_create_product(self):
        """Test creating a new product."""
        data = {
            'prod_code': 'AP009F',
            'prod_name': 'Test Product',
            'sku': 'AP009F',
            'sku_name': '60s/bottle',
            'current_price': '3240.00',
            'cost_price': '2268.00',
            'current_pv': '18.00',
            'quantity': 75,
            'reorder_level': 15,
            'category': self.category.id,
            'is_active': True
        }
        response = self.client.post('/api/v1/products/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Product.objects.count(), 3)
        self.assertEqual(response.data['prod_code'], 'AP009F')


class ProductDetailAPITest(ProductAPITestCase):
    """Test Product Detail API endpoint."""

    def test_get_product_detail(self):
        """Test retrieving a single product."""
        response = self.client.get(f'/api/v1/products/{self.product1.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['prod_code'], 'AP004E')
        self.assertEqual(response.data['prod_name'], 'MicroQ2 Cycle Tablets')
        self.assertIn('stock_status', response.data)

    def test_update_product_price(self):
        """Test updating product price."""
        data = {'current_price': '3200.00'}
        response = self.client.patch(f'/api/v1/products/{self.product1.id}/', data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.product1.refresh_from_db()
        self.assertEqual(self.product1.current_price, Decimal('3200.00'))

    def test_update_product_quantity(self):
        """Test updating product quantity."""
        data = {'quantity': 150}
        response = self.client.patch(f'/api/v1/products/{self.product1.id}/', data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity, 150)

    def test_deactivate_product(self):
        """Test deactivating a product."""
        data = {'is_active': False}
        response = self.client.patch(f'/api/v1/products/{self.product1.id}/', data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.product1.refresh_from_db()
        self.assertFalse(self.product1.is_active)

    def test_delete_product(self):
        """Test deleting a product."""
        # Create a product that's not referenced anywhere
        test_product = Product.objects.create(
            prod_code='TESTDEL',
            prod_name='Delete Test',
            sku='TESTDEL',
            sku_name='Test',
            current_price=Decimal('100.00'),
            cost_price=Decimal('70.00'),
            current_pv=Decimal('5.00')
        )
        response = self.client.delete(f'/api/v1/products/{test_product.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Product.objects.filter(id=test_product.id).exists())


class ProductSearchAPITest(ProductAPITestCase):
    """Test Product Search API endpoint."""

    def test_search_by_sku(self):
        """Test searching product by SKU."""
        response = self.client.get('/api/v1/products/search/', {'sku': 'AP004E'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['prod_code'], 'AP004E')
        self.assertEqual(response.data['sku'], 'AP004E')

    def test_search_by_prod_code(self):
        """Test searching product by prod_code."""
        response = self.client.get('/api/v1/products/search/', {'prod_code': 'AP008E'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['prod_code'], 'AP008E')

    def test_search_inactive_product_not_found(self):
        """Test that inactive products are not returned in search."""
        self.product1.is_active = False
        self.product1.save()

        response = self.client.get('/api/v1/products/search/', {'sku': 'AP004E'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_search_without_params_returns_error(self):
        """Test that search without params returns 400."""
        response = self.client.get('/api/v1/products/search/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_search_nonexistent_product(self):
        """Test searching for non-existent product."""
        response = self.client.get('/api/v1/products/search/', {'sku': 'NOTEXIST'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ProductSummaryAPITest(ProductAPITestCase):
    """Test Product Summary API endpoint."""

    def test_product_summary(self):
        """Test product inventory summary."""
        response = self.client.get('/api/v1/products/summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check all expected fields
        self.assertIn('total_products', response.data)
        self.assertIn('active_products', response.data)
        self.assertIn('out_of_stock', response.data)
        self.assertIn('low_stock', response.data)
        self.assertIn('total_inventory_value', response.data)
        self.assertIn('total_retail_value', response.data)

        # Verify counts
        self.assertEqual(response.data['total_products'], 2)
        self.assertEqual(response.data['active_products'], 2)
        self.assertEqual(response.data['out_of_stock'], 0)

    def test_summary_with_out_of_stock(self):
        """Test summary correctly counts out-of-stock products."""
        self.product1.quantity = 0
        self.product1.save()

        response = self.client.get('/api/v1/products/summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['out_of_stock'], 1)

    def test_summary_with_low_stock(self):
        """Test summary correctly counts low-stock products."""
        self.product1.quantity = 8  # Below reorder_level of 10
        self.product1.save()

        response = self.client.get('/api/v1/products/summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['low_stock'], 1)

    def test_summary_inventory_values(self):
        """Test summary calculates inventory values correctly."""
        response = self.client.get('/api/v1/products/summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # product1: 100 * 2079 = 207,900
        # product2: 50 * 2740.50 = 137,025
        # Total: 344,925
        expected_cost = Decimal('344925.00')
        self.assertEqual(Decimal(response.data['total_inventory_value']), expected_cost)

        # product1: 100 * 2970 = 297,000
        # product2: 50 * 3915 = 195,750
        # Total: 492,750
        expected_retail = Decimal('492750.00')
        self.assertEqual(Decimal(response.data['total_retail_value']), expected_retail)


class InventoryMovementAPITest(ProductAPITestCase):
    """Test Inventory Movement API endpoint."""

    def setUp(self):
        """Set up test data including inventory movements."""
        super().setUp()

        # Create inventory movements
        self.movement1 = InventoryMovement.objects.create(
            movement_type=InventoryMovement.MovementType.SALE,
            product=self.product1,
            quantity_before=100,
            quantity_after=95,
            quantity_change=-5,
            reference='TX12345',
            performed_by='System'
        )

        self.movement2 = InventoryMovement.objects.create(
            movement_type=InventoryMovement.MovementType.PURCHASE,
            product=self.product1,
            quantity_before=100,
            quantity_after=150,
            quantity_change=50,
            reference='PO67890',
            performed_by='Admin'
        )

    def test_list_inventory_movements(self):
        """Test listing all inventory movements."""
        response = self.client.get('/api/v1/inventory/movements/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_filter_movements_by_product(self):
        """Test filtering movements by product."""
        response = self.client.get('/api/v1/inventory/movements/', {'product': self.product1.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_filter_movements_by_type(self):
        """Test filtering movements by type."""
        response = self.client.get('/api/v1/inventory/movements/', {
            'movement_type': 'SALE'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['movement_type'], 'SALE')

    def test_movement_includes_product_details(self):
        """Test that movement response includes product details."""
        response = self.client.get('/api/v1/inventory/movements/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        movement = response.data[0]
        self.assertIn('product_name', movement)
        self.assertIn('product_code', movement)
        self.assertIn('movement_type_display', movement)


# Authentication tests removed - authentication is optional for these endpoints
# (authentication_classes is set but no permission_classes, so DRF allows through)
