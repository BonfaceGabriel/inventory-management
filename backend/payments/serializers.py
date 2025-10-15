from rest_framework import serializers
from .models import Device, RawMessage, Transaction, ManualPayment

class DeviceRegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ['name', 'phone_number', 'default_gateway', 'gateway_number']

class DeviceResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ['id', 'name', 'phone_number', 'default_gateway', 'gateway_number', 'api_key']
        read_only_fields = ['id', 'api_key']

class RawMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = RawMessage
        fields = ['device', 'raw_text', 'received_at']
        read_only_fields = ['device']

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
        # Require reference number for PDQ and Bank Transfer
        if data['payment_method'] in ['PDQ', 'BANK_TRANSFER']:
            if not data.get('reference_number'):
                raise serializers.ValidationError({
                    'reference_number': f'Reference number is required for {data["payment_method"]} payments'
                })
        return data

class TransactionSerializer(serializers.ModelSerializer):
    raw_messages = RawMessageSerializer(many=True, read_only=True)
    manual_payments = ManualPaymentSerializer(many=True, read_only=True)
    remaining_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_locked = serializers.BooleanField(read_only=True)
    status_display = serializers.ReadOnlyField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'tx_id', 'amount', 'sender_name', 'sender_phone',
            'timestamp', 'status', 'status_display', 'amount_expected', 'amount_paid',
            'remaining_amount', 'is_locked', 'notes', 'raw_messages', 'manual_payments',
            'gateway_type', 'destination_number', 'confidence',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'tx_id', 'amount', 'created_at', 'updated_at', 'remaining_amount', 'is_locked', 'status_display']
