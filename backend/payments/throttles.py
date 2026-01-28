"""
Custom throttle classes for the payment system.
"""
from rest_framework.throttling import UserRateThrottle


class BurstRateThrottle(UserRateThrottle):
    """
    Throttle class for high-frequency operations like barcode scanning.
    Allows burst of requests for rapid scanning operations.

    Rate: 1000 requests per minute (about 16-17 per second)
    """
    scope = 'burst'


class NoThrottle(UserRateThrottle):
    """
    No throttling - for internal operations that need unlimited rate.
    Use with caution and only for authenticated internal endpoints.
    """
    def allow_request(self, request, view):
        return True
