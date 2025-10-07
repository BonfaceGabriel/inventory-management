from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth.hashers import check_password
from .models import Device
import uuid

class DeviceAPIKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        api_key = request.headers.get('X-DEVICE-KEY')
        if not api_key:
            return None

        # The device_id can be in the request body or in the URL kwargs
        device_id_str = request.data.get('device') or request.parser_context.get('kwargs', {}).get('id')

        if not device_id_str:
            return None # No device_id provided, cannot authenticate

        try:
            device_id = uuid.UUID(device_id_str)
        except (ValueError, TypeError):
            raise AuthenticationFailed('Invalid device_id format')

        try:
            device = Device.objects.get(id=device_id)
        except Device.DoesNotExist:
            raise AuthenticationFailed('Device not found')

        if not check_password(api_key, device.api_key):
            raise AuthenticationFailed('Invalid API Key')

        return (device, None)
