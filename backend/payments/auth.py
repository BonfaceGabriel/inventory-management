from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth.hashers import check_password
from .models import Device
import uuid

class AuthenticatedDevice:
    """Wrapper for Device to make it compatible with DRF's authentication system"""
    def __init__(self, device):
        self.device = device
        self.is_authenticated = True
        self.is_active = True

    def __getattr__(self, name):
        # Delegate all other attribute access to the wrapped device
        return getattr(self.device, name)

class SimpleAPIKeyAuthentication(BaseAuthentication):
    """
    Authentication using only API key (X-DEVICE-KEY header).
    Looks up device by matching the API key hash.
    """
    def authenticate(self, request):
        api_key = request.headers.get('X-DEVICE-KEY')
        if not api_key:
            return None

        # Find device by checking API key against all devices
        for device in Device.objects.all():
            if check_password(api_key, device.api_key):
                return (AuthenticatedDevice(device), None)

        raise AuthenticationFailed('Invalid API Key')


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

        return (AuthenticatedDevice(device), None)
