from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth.hashers import check_password
from django.conf import settings
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

    Uses values_list + iterator to avoid loading full model instances
    during the scan. Devices are typically few (<100), so the linear
    scan over hashed keys is acceptable.
    """
    def authenticate(self, request):
        api_key = request.headers.get('X-DEVICE-KEY')
        if not api_key:
            return None

        # Scan api_key hashes (linear, but typically <100 devices)
        for device_id, hashed_key in Device.objects.values_list('id', 'api_key').iterator():
            if check_password(api_key, hashed_key):
                device = Device.objects.get(id=device_id)
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


class RelayUser:
    """
    Lightweight user wrapper for relay-authenticated requests.
    Used when another branch instance sends a relayed payment message.
    """
    pk = 0
    is_authenticated = True
    is_active = True
    is_relay = True

    def __str__(self):
        return 'RelayUser'


class RelayAuthentication(BaseAuthentication):
    """
    Authenticate relay requests from other branch instances using
    a shared secret via the X-Relay-Secret header.
    """
    def authenticate(self, request):
        secret = request.headers.get('X-Relay-Secret')
        if not secret:
            return None

        expected = getattr(settings, 'PAYMENT_RELAY_SECRET', '')
        if not expected or secret != expected:
            raise AuthenticationFailed('Invalid relay secret')

        return (RelayUser(), None)


class InventoryAPIUser:
    """
    Lightweight user wrapper for inventory API authenticated requests.
    Used when the external website queries the inventory API.
    """
    pk = 0
    is_authenticated = True
    is_active = True
    is_inventory_api = True

    def __str__(self):
        return 'InventoryAPIUser'


class InventoryAPIAuthentication(BaseAuthentication):
    """
    Authenticate inventory API requests from the external website
    using a Bearer token via the Authorization header.

    The expected token is configured via VITE_INVENTORY_API_KEY setting.
    """
    def authenticate(self, request):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return None

        token = auth_header.removeprefix('Bearer ').strip()
        if not token:
            return None

        expected = getattr(settings, 'VITE_INVENTORY_API_KEY', '')
        if not expected or token != expected:
            raise AuthenticationFailed('Invalid inventory API key')

        return (InventoryAPIUser(), None)

