"""
Role-based permission classes for the payment management system.

Permission hierarchy:
- Admin: Full access to all endpoints
- Processor: Access to transactions, reconciliation, reports, manual payments
- Issuer: Access to issuance queue, scanning, fulfillment, stock taking, products

Device authentication (API key) is supported alongside JWT for Android app compatibility.
"""

from rest_framework.permissions import BasePermission
import logging

logger = logging.getLogger(__name__)


class IsAdmin(BasePermission):
    """
    Permission class for Admin-only endpoints.
    Only users with ADMIN role can access.
    """
    message = "Admin access required."

    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            hasattr(request.user, 'role') and
            request.user.role == 'ADMIN'
        )


class IsProcessor(BasePermission):
    """
    Permission class for Processor endpoints.
    Allows ADMIN and PROCESSOR roles.

    Used for:
    - Transaction list/detail views
    - Activate issuance
    - Combined orders
    - Manual payments
    - Reports and reconciliation
    - Analytics
    """
    message = "Processor or Admin access required."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if not hasattr(request.user, 'role'):
            return False

        return request.user.role in ['ADMIN', 'PROCESSOR']


class IsIssuer(BasePermission):
    """
    Permission class for Issuer endpoints.
    Allows ADMIN and ISSUER roles.

    Used for:
    - Issuer queue
    - Scanning products
    - Complete/cancel issuance
    - Stock taking
    - Products management
    """
    message = "Issuer or Admin access required."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if not hasattr(request.user, 'role'):
            return False

        return request.user.role in ['ADMIN', 'ISSUER']


class IsAdminOrProcessor(BasePermission):
    """
    Alias for IsProcessor - allows Admin or Processor roles.
    """
    message = "Admin or Processor access required."

    def has_permission(self, request, view):
        logger.info(f"IsAdminOrProcessor: Checking permissions for {request.method} {request.path}")
        logger.info(f"  request.user: {request.user}")
        logger.info(f"  request.user type: {type(request.user)}")
        logger.info(f"  is_authenticated: {request.user.is_authenticated if request.user else 'N/A'}")

        if not request.user or not request.user.is_authenticated:
            logger.warning(f"  DENIED: User not authenticated")
            return False

        logger.info(f"  hasattr 'role': {hasattr(request.user, 'role')}")
        logger.info(f"  hasattr 'device': {hasattr(request.user, 'device')}")

        if hasattr(request.user, 'device'):
            logger.warning(f"  DENIED: Request authenticated via device wrapper (no role)")
            return False

        if not hasattr(request.user, 'role'):
            logger.error(f"  DENIED: User {request.user.username if hasattr(request.user, 'username') else 'unknown'} missing role attribute")
            return False

        logger.info(f"  user.role: {request.user.role}")

        if request.user.role not in ['ADMIN', 'PROCESSOR']:
            logger.warning(f"  DENIED: User {request.user.username} has role {request.user.role}, requires ADMIN or PROCESSOR")
            return False

        logger.info(f"  GRANTED: User {request.user.username} with role {request.user.role}")
        return True


class IsAdminOrIssuer(BasePermission):
    """
    Alias for IsIssuer - allows Admin or Issuer roles.
    """
    message = "Admin or Issuer access required."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if not hasattr(request.user, 'role'):
            return False

        return request.user.role in ['ADMIN', 'ISSUER']


class IsDeviceOrAuthenticated(BasePermission):
    """
    Allow access via device API key OR JWT user authentication.

    This permission supports dual authentication:
    - Android devices use X-API-KEY header (device-based auth)
    - Web frontend uses Bearer token (JWT auth)

    Used for endpoints that need to work with both Android app and web dashboard.
    """
    message = "Authentication required (device API key or user login)."

    def has_permission(self, request, view):
        logger.info(f"IsDeviceOrAuthenticated: Checking permissions for {request.method} {request.path}")
        logger.info(f"  request.user: {request.user}")
        logger.info(f"  user type: {type(request.user)}")
        logger.info(f"  is_authenticated: {request.user.is_authenticated if request.user else 'N/A'}")
        logger.info(f"  hasattr 'device': {hasattr(request, 'device')}")
        logger.info(f"  request.device: {request.device if hasattr(request, 'device') else 'N/A'}")

        # Check if request is from a registered device (API key auth)
        if hasattr(request, 'device') and request.device is not None:
            logger.info("  GRANTED: Device authentication")
            return True

        # Check if request is from an authenticated user (JWT auth)
        if request.user and request.user.is_authenticated:
            logger.info(f"  GRANTED: JWT user authentication ({request.user})")
            return True

        logger.warning("  DENIED: No valid authentication")
        return False


class IsDeviceOrProcessor(BasePermission):
    """
    Allow access via device API key OR Processor/Admin JWT authentication.

    Used for endpoints that Android devices need access to,
    but web users need Processor role.
    """
    message = "Device API key or Processor/Admin access required."

    def has_permission(self, request, view):
        # Check if request is from a registered device (API key auth)
        if hasattr(request, 'device') and request.device is not None:
            return True

        # Check if request is from an authenticated Processor/Admin user
        if request.user and request.user.is_authenticated:
            if hasattr(request.user, 'role'):
                return request.user.role in ['ADMIN', 'PROCESSOR']

        return False


class IsDeviceOrIssuer(BasePermission):
    """
    Allow access via device API key OR Issuer/Admin JWT authentication.

    Used for endpoints that Android devices need access to,
    but web users need Issuer role.
    """
    message = "Device API key or Issuer/Admin access required."

    def has_permission(self, request, view):
        # Check if request is from a registered device (API key auth)
        if hasattr(request, 'device') and request.device is not None:
            return True

        # Check if request is from an authenticated Issuer/Admin user
        if request.user and request.user.is_authenticated:
            if hasattr(request.user, 'role'):
                return request.user.role in ['ADMIN', 'ISSUER']

        return False


class IsAuthenticatedUser(BasePermission):
    """
    Requires JWT user authentication (not device API key).

    Used for user-specific endpoints like:
    - Profile
    - Change password
    """
    message = "User authentication required."

    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            hasattr(request.user, 'role')
        )
