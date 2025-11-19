from rest_framework import serializers
from .models import (
    Device, RawMessage, Transaction, ManualPayment,
    Product, ProductCategory, TransactionLineItem, InventoryMovement
)

class DeviceRegisterSerializer(serializers.ModelSerializer):
    gateway_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = Device
        fields = ['name', 'phone_number', 'gateway_id', 'default_gateway', 'gateway_number']

class DeviceResponseSerializer(serializers.ModelSerializer):
    gateway_name = serializers.CharField(source='gateway.name', read_only=True, allow_null=True)
    gateway_type = serializers.CharField(source='gateway.gateway_type', read_only=True, allow_null=True)

    class Meta:
        model = Device
        fields = ['id', 'name', 'phone_number', 'gateway', 'gateway_name', 'gateway_type', 'default_gateway', 'gateway_number', 'api_key']
        read_only_fields = ['id', 'api_key', 'gateway_name', 'gateway_type']

class RawMessageSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)

    class Meta:
        model = RawMessage
        fields = ['device', 'device_name', 'raw_text', 'received_at']
        read_only_fields = ['device', 'device_name']

class ManualPaymentSerializer(serializers.ModelSerializer):
    """Serializer for manual payment entries"""
    payment_method_display = serializers.CharField(
        source='get_payment_method_display',
        read_only=True
    )

    class Meta:
        model = ManualPayment
        fields = [
            'id', 'transaction', 'payment_method', 'payment_method_display',
            'reference_number', 'payer_name', 'payer_phone', 'payer_email',
            'amount', 'payment_date', 'notes', 'created_by',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'payment_method_display']

class ManualPaymentCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a manual payment entry.

    This creates both a Transaction and ManualPayment record.
    """
    payment_method = serializers.ChoiceField(choices=ManualPayment.PaymentMethod.choices)
    reference_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    payer_name = serializers.CharField(max_length=255)
    payer_phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    payer_email = serializers.EmailField(required=False, allow_blank=True)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    payment_date = serializers.DateTimeField()
    notes = serializers.CharField(required=False, allow_blank=True)
    created_by = serializers.CharField(max_length=255)

    def validate_amount(self, value):
        """Ensure amount is positive"""
        from decimal import Decimal
        if value <= Decimal('0.00'):
            raise serializers.ValidationError("Amount must be greater than zero")
        return value

    def validate(self, data):
        """Cross-field validation"""
        # Reference number is now optional for all payment methods
        # Transaction ID is auto-generated, so no validation needed
        return data

class TransactionSerializer(serializers.ModelSerializer):
    raw_messages = serializers.SerializerMethodField()
    manual_payments = ManualPaymentSerializer(many=True, read_only=True)
    line_items = serializers.SerializerMethodField()
    remaining_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_locked = serializers.BooleanField(read_only=True)
    status_display = serializers.ReadOnlyField()
    gateway_name = serializers.CharField(source='gateway.name', read_only=True, allow_null=True)

    def get_raw_messages(self, obj):
        """Return unique raw messages (deduplicated by raw_text)"""
        messages = obj.raw_messages.all()
        seen_texts = set()
        unique_messages = []

        for message in messages:
            if message.raw_text not in seen_texts:
                seen_texts.add(message.raw_text)
                unique_messages.append(message)

        return RawMessageSerializer(unique_messages, many=True).data

    def get_line_items(self, obj):
        """Return fulfilled line items for this transaction"""
        line_items = obj.line_items.all()
        return [{
            'id': item.id,
            'product_code': item.scanned_prod_code,
            'product_name': item.scanned_prod_name,
            'sku': item.scanned_sku,
            'quantity': item.quantity,
            'unit_price': str(item.scanned_price),
            'line_total': str(item.line_total),
            'scanned_at': item.scanned_at,
            'scanned_by': item.scanned_by,
        } for item in line_items]

    class Meta:
        model = Transaction
        fields = [
            'id', 'tx_id', 'amount', 'sender_name', 'sender_phone',
            'timestamp', 'status', 'status_display', 'amount_expected', 'amount_paid', 'amount_fulfilled',
            'remaining_amount', 'is_locked', 'notes', 'raw_messages', 'manual_payments',
            'line_items', 'gateway_type', 'gateway_name', 'destination_number', 'confidence',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'tx_id', 'amount', 'created_at', 'updated_at', 'remaining_amount', 'is_locked', 'status_display', 'gateway_name', 'line_items', 'amount_fulfilled']

# ============================================================================
# Product & Inventory Serializers
# ============================================================================

class ProductCategorySerializer(serializers.ModelSerializer):
    """Serializer for product categories."""
    subcategory_count = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = ProductCategory
        fields = [
            'id', 'name', 'description', 'parent_category',
            'subcategory_count', 'product_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_subcategory_count(self, obj):
        """Return count of subcategories."""
        return obj.subcategories.count()

    def get_product_count(self, obj):
        """Return count of products in this category."""
        return obj.products.count()


class ProductSerializer(serializers.ModelSerializer):
    """Serializer for products with inventory details."""
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)
    stock_status = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'prod_code', 'prod_name', 'sku', 'sku_name',
            'current_price', 'cost_price', 'current_pv',
            'quantity', 'reorder_level', 'stock_status',
            'category', 'category_name', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'category_name']

    def get_stock_status(self, obj):
        """Return stock status based on quantity and reorder level."""
        if obj.quantity <= 0:
            return 'OUT_OF_STOCK'
        elif obj.quantity <= obj.reorder_level:
            return 'LOW_STOCK'
        else:
            return 'IN_STOCK'


class ProductListSerializer(serializers.ModelSerializer):
    """Minimal serializer for product list views (faster)."""
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)
    stock_status = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'prod_code', 'prod_name', 'sku', 'sku_name',
            'current_price', 'cost_price', 'current_pv',
            'quantity', 'reorder_level', 'stock_status',
            'category', 'category_name', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'category_name', 'stock_status']

    def get_stock_status(self, obj):
        """Return stock status based on quantity and reorder level."""
        if obj.quantity <= 0:
            return 'OUT_OF_STOCK'
        elif obj.quantity <= obj.reorder_level:
            return 'LOW_STOCK'
        else:
            return 'IN_STOCK'


class TransactionLineItemSerializer(serializers.ModelSerializer):
    """Serializer for transaction line items."""
    product_name = serializers.CharField(source='product.prod_name', read_only=True)
    
    class Meta:
        model = TransactionLineItem
        fields = [
            'id', 'transaction', 'product', 'product_name',
            'scanned_prod_code', 'scanned_prod_name',
            'scanned_sku', 'scanned_sku_name',
            'scanned_price', 'scanned_pv',
            'quantity', 'line_total', 'line_cost', 'line_pv',
            'scanned_at', 'scanned_by'
        ]
        read_only_fields = ['id', 'line_total', 'line_cost', 'line_pv', 'scanned_at', 'product_name']


class InventoryMovementSerializer(serializers.ModelSerializer):
    """Serializer for inventory movements (audit trail)."""
    movement_type_display = serializers.CharField(source='get_movement_type_display', read_only=True)
    product_name = serializers.CharField(source='product.prod_name', read_only=True)
    product_code = serializers.CharField(source='product.prod_code', read_only=True)

    class Meta:
        model = InventoryMovement
        fields = [
            'id', 'movement_type', 'movement_type_display',
            'product', 'product_name', 'product_code',
            'quantity_before', 'quantity_after', 'quantity_change',
            'reference', 'performed_by', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'movement_type_display', 'product_name', 'product_code']


# ============================================================================
# Transaction Fulfillment Serializers
# ============================================================================

class BarcodeScanSerializer(serializers.Serializer):
    """Serializer for barcode scan input."""
    sku = serializers.CharField(required=False, allow_blank=True)
    prod_code = serializers.CharField(required=False, allow_blank=True)
    quantity = serializers.IntegerField(default=1, min_value=1)
    scanned_by = serializers.CharField(required=False, default='System')

    def validate(self, data):
        """Ensure either sku or prod_code is provided."""
        if not data.get('sku') and not data.get('prod_code'):
            raise serializers.ValidationError('Either sku or prod_code must be provided')
        return data


class IssuanceCancelSerializer(serializers.Serializer):
    """Serializer for cancelling issuance."""
    reason = serializers.CharField(required=False, allow_blank=True)


class IssuanceCompleteSerializer(serializers.Serializer):
    """Serializer for completing issuance."""
    performed_by = serializers.CharField(required=False, default='System')
