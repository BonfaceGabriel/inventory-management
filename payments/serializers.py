from rest_framework import serializers
from .models import Device, RawMessage, Transaction

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

class TransactionSerializer(serializers.ModelSerializer):
    raw_messages = RawMessageSerializer(many=True, read_only=True)

    class Meta:
        model = Transaction
        fields = ['id', 'tx_id', 'amount', 'sender_name', 'sender_phone', 'timestamp', 'status', 'raw_messages']
