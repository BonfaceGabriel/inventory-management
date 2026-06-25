from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics, filters
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.auth import get_user_model
from django.db.models import Q
from .serializers import (
    DeviceRegisterSerializer, DeviceResponseSerializer, RawMessageSerializer,
    TransactionSerializer, ManualPaymentSerializer, ManualPaymentCreateSerializer,
    ProductSerializer, ProductListSerializer, ProductLineSerializer,
    TransactionLineItemSerializer, InventoryMovementSerializer,
    CustomTokenObtainPairSerializer, UserSerializer, UserCreateSerializer,
    UserUpdateSerializer, ChangePasswordSerializer, AdminPasswordResetSerializer,
    LocationSerializer,
    MerchandiseCatalogItemSerializer, MerchandiseCatalogItemCreateSerializer,
    MerchandiseOrderSerializer,
    MerchandiseFulfillRequestSerializer, MerchandiseStockSerializer,
    MerchandiseStockAdjustRequestSerializer, MerchandiseStockMovementSerializer,
)
from .models import (
    Device, Transaction, ManualPayment, PaymentGateway, Product, ProductLine,
    InventoryMovement, CombinedOrder, Location, RawMessage,
    MerchandiseCatalogItem, MerchandiseOrder, MerchandiseStock, MerchandiseStockMovement,
)
from .filters import TransactionFilter, ManualPaymentFilter
from .permissions import (
    IsAdmin, IsProcessor, IsIssuer, IsAdminOrProcessor, IsAdminOrIssuer,
    IsDeviceOrAuthenticated, IsDeviceOrProcessor, IsDeviceOrIssuer, IsAuthenticatedUser
)
import uuid
import logging
from django.conf import settings
from django.contrib.auth.hashers import make_password
import secrets
from .auth import DeviceAPIKeyAuthentication, SimpleAPIKeyAuthentication, RelayAuthentication, InventoryAPIAuthentication

logger = logging.getLogger(__name__)
from .tasks import process_raw_message, relay_message_to_branches
from .services import ManualPaymentService
from .services.reconciliation_service import ReconciliationService
from .services.export_service import TransactionExportService
from .services.time_locking_service import TimeLockingService
from .services.combined_order_service import CombinedOrderService
from .services.stock_take_service import StockTakeService
from .services.merchandise_service import MerchandiseService
from .services.analytics_service import AnalyticsService
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.http import HttpResponse
from django.core.exceptions import ValidationError
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


def get_request_location(request):
    """
    Resolve the Location for the current request.

    Priority:
    1. X-Location-ID header (UUID sent by the frontend)
    2. request.user.current_location (stored on the user)
    3. Main Shop (singleton fallback)
    """
    location_id = request.headers.get('X-Location-ID')
    if location_id:
        try:
            return Location.objects.get(pk=location_id, status='ACTIVE')
        except (Location.DoesNotExist, Exception):
            pass

    user = getattr(request, 'user', None)
    if user and hasattr(user, 'current_location_id') and user.current_location_id:
        return user.current_location

    return Location.get_main_location()


class DeviceRegisterView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = DeviceRegisterSerializer(data=request.data)
        if serializer.is_valid():
            validated_data = serializer.validated_data

            # Extract gateway_id if provided
            gateway_id = validated_data.pop('gateway_id', None)

            # Create device instance
            device = Device(**validated_data)
            plain_api_key = secrets.token_urlsafe(32)
            device.api_key = make_password(plain_api_key)

            # If gateway_id provided, assign the gateway
            if gateway_id:
                try:
                    gateway = PaymentGateway.objects.get(id=gateway_id, is_active=True)
                    device.gateway = gateway
                except PaymentGateway.DoesNotExist:
                    return Response(
                        {'error': f'Gateway with id {gateway_id} not found or inactive'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            device.save()

            # Debug logging
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Device saved: ID={device.id}, Name={device.name}")
            logger.info(f"Device gateway_id: {device.gateway_id}")
            if device.gateway:
                logger.info(f"Device gateway name: {device.gateway.name}")
                logger.info(f"Device gateway type: {device.gateway.gateway_type}")

            response_data = DeviceResponseSerializer(device).data
            logger.info(f"Serialized response: {response_data}")
            response_data['api_key'] = plain_api_key
            return Response(response_data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class MessageIngestView(APIView):
    """
    Receive raw payment SMS from Android forwarder devices.

    POST /api/v1/messages/
    Authenticated via Device API key (X-DEVICE-KEY header).
    Saves the RawMessage, queues Celery processing, and fans out the
    message to all configured relay targets.
    """
    authentication_classes = [DeviceAPIKeyAuthentication]

    def post(self, request, *args, **kwargs):
        serializer = RawMessageSerializer(data=request.data)
        if serializer.is_valid():
            device = getattr(request.user, 'device', request.user)
            message = serializer.save(device=device)

            from django.db import transaction as db_transaction

            # Queue local processing after DB commit
            db_transaction.on_commit(
                lambda message_id=message.id: process_raw_message.delay(message_id)
            )

            relay_targets = getattr(settings, 'PAYMENT_RELAY_TARGETS', None)
            relay_types = getattr(settings, 'PAYMENT_RELAY_GATEWAY_TYPES', ['MPESA_TILL', 'MERCHANDISE'])
            gateway = getattr(device, 'gateway', None)
            should_relay = (
                relay_targets
                and gateway is not None
                and gateway.gateway_type in relay_types
            )

            if should_relay:
                db_transaction.on_commit(
                    lambda message_id=message.id: relay_message_to_branches.delay(message_id)
                )

            return Response(
                {"message_id": message.id, "status": "queued"},
                status=status.HTTP_201_CREATED,
            )
        logger.warning(
            f"[TILL_PIPELINE_DEBUG] MessageIngestView.post() serializer errors: "
            f"{serializer.errors}"
        )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class RelayMessageIngestView(APIView):
    """
    Receive relayed payment SMS from the primary branch instance.

    POST /api/v1/messages/relay/
    Authenticated via shared relay secret (X-Relay-Secret header).
    Payload includes raw_text, received_at, gateway_type, and source_branch.
    Creates a RawMessage with is_relayed=True and triggers normal processing.
    """
    authentication_classes = [RelayAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        from django.db import transaction as db_transaction
        import logging
        logger = logging.getLogger(__name__)

        with db_transaction.atomic():
            raw_text = request.data.get('raw_text')
            received_at = request.data.get('received_at')
            gateway_type = request.data.get('gateway_type')
            source_branch = request.data.get('source_branch', '')

            if not raw_text or not received_at or not gateway_type:
                return Response(
                    {'detail': 'raw_text, received_at, and gateway_type are required'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Find an active PaymentGateway matching the incoming gateway_type.
            gateway = (
                PaymentGateway.objects
                .filter(gateway_type=gateway_type, is_active=True)
                .order_by('id')
                .first()
            )
            if gateway is None:
                return Response(
                    {'detail': f'No active {gateway_type} gateway found on this branch'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get or create a Relay device linked to that gateway.
            device, created = Device.objects.get_or_create(
                name=f"Relay - {gateway_type}",
                defaults={
                    'gateway': gateway,
                    'api_key': f'relay-internal-{uuid.uuid4()}',
                },
            )
            if not created and device.gateway_id != gateway.pk:
                device.gateway = gateway
                device.save(update_fields=['gateway'])

            raw_message = RawMessage.objects.create(
                device=device,
                raw_text=raw_text,
                received_at=received_at,
                is_relayed=True,
                source_branch=source_branch,
            )

            # Queue local processing after DB commit
            logger.info(f"Relay received: Queuing process_raw_message for message {raw_message.id}")
            db_transaction.on_commit(
                lambda message_id=raw_message.id: process_raw_message.delay(message_id)
            )

        return Response(
            {"message_id": raw_message.id, "status": "queued"},
            status=status.HTTP_202_ACCEPTED,
        )

class RotateAPIKeyView(APIView):
    authentication_classes = [DeviceAPIKeyAuthentication]

    def patch(self, request, *args, **kwargs):
        # Extract the actual Device object from the AuthenticatedDevice wrapper
        device = getattr(request.user, 'device', request.user)
        plain_api_key = secrets.token_urlsafe(32)
        device.api_key = make_password(plain_api_key)
        device.save()
        return Response({'api_key': plain_api_key})


class DeviceSettingsUpdateView(APIView):
    """
    Update device settings including gateway assignment.

    PATCH /api/v1/devices/settings/
    Headers: X-API-KEY: <device_api_key>
    {
        "gateway_id": 1,  // Optional: Update gateway assignment
        "name": "Updated Device Name",  // Optional: Update device name
        "phone_number": "+254712345678"  // Optional: Update phone number
    }
    """
    authentication_classes = [SimpleAPIKeyAuthentication]
    permission_classes = []

    def patch(self, request, *args, **kwargs):
        # Extract the actual Device object from the AuthenticatedDevice wrapper
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"request.user type: {type(request.user)}")
        logger.info(f"request.user has device attr: {hasattr(request.user, 'device')}")

        if hasattr(request.user, 'device'):
            device = request.user.device
            logger.info(f"device type: {type(device)}")
            logger.info(f"device: {device}")
        else:
            return Response(
                {'error': 'Authentication required'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Update gateway if gateway_id provided
        gateway_id = request.data.get('gateway_id')
        if gateway_id is not None:
            logger.info(f"🔄 Gateway Update Request - Device: {device.name}, Requested Gateway ID: {gateway_id}, Current Gateway: {device.gateway.name if device.gateway else 'None'} (ID: {device.gateway_id})")

            if gateway_id == '':
                # Prevent clearing the gateway - gateway is now required
                return Response(
                    {'error': 'Gateway cannot be removed. Gateway is required for all devices.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            else:
                try:
                    gateway = PaymentGateway.objects.get(id=gateway_id, is_active=True)
                    logger.info(f"✅ Found Gateway: {gateway.name} (ID: {gateway.id})")
                    device.gateway = gateway
                except PaymentGateway.DoesNotExist:
                    logger.error(f"❌ Gateway ID {gateway_id} not found or inactive")
                    return Response(
                        {'error': f'Gateway with id {gateway_id} not found or inactive'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

        # Update other fields if provided
        if 'name' in request.data:
            device.name = request.data['name']

        if 'phone_number' in request.data:
            device.phone_number = request.data['phone_number']

        device.save()

        # Refresh from database to ensure all relations are loaded
        device.refresh_from_db()

        # Log final state after refresh
        logger.info(f"💾 Device Saved - Name: {device.name}, Gateway: {device.gateway.name if device.gateway else 'None'} (ID: {device.gateway_id})")

        # Return updated device info with all relation fields
        response_data = DeviceResponseSerializer(device).data
        logger.info(f"📤 Response Data: id={response_data.get('id')}, gateway={response_data.get('gateway')}, gateway_name={response_data.get('gateway_name')}, gateway_type={response_data.get('gateway_type')}, gateway_type_display={response_data.get('gateway_type_display')}")
        return Response(response_data)

class TransactionListView(generics.ListAPIView):
    """
    List transactions with comprehensive search and filtering.

    Search fields (use ?search=...):
    - tx_id: Transaction ID
    - sender_name: Sender name
    - sender_phone: Sender phone number
    - notes: Transaction notes

    Filter fields (use ?filter_name=value):
    - tx_id: Exact transaction ID
    - status: Transaction status
    - gateway_type: Payment gateway
    - min_date, max_date: Date range by timestamp
    - created_after, created_before: Date range by creation
    - min_amount, max_amount: Amount range
    - sender_name, sender_phone: Text search
    - is_locked, is_available: Boolean filters
    - And many more (see TransactionFilter)

    Examples:
    - Search: /api/transactions/?search=TX001
    - Filter by amount: /api/transactions/?min_amount=5000&max_amount=10000
    - Filter by date: /api/transactions/?min_date=2025-10-01T00:00:00Z&max_date=2025-10-09T23:59:59Z
    - Combined: /api/transactions/?search=JOHN&min_amount=5000&is_locked=false
    """
    authentication_classes = [DeviceAPIKeyAuthentication, JWTAuthentication]
    permission_classes = [IsDeviceOrAuthenticated]  # Allow both devices and JWT users
    serializer_class = TransactionSerializer
    queryset = Transaction.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = TransactionFilter
    search_fields = ['tx_id', 'sender_name', 'sender_phone', 'notes']
    ordering_fields = '__all__'
    ordering = ['-timestamp']  # Default: newest first

    def get_queryset(self):
        """
        Filter queryset based on user role.

        - ISSUER role: See PROCESSING, PARTIALLY_FULFILLED, and active combined order children
        - PROCESSOR/ADMIN: See all transactions
        - Devices (API key auth): See all transactions
        """
        import logging
        logger = logging.getLogger(__name__)

        queryset = super().get_queryset()

        logger.info(f"TransactionListView.get_queryset called")
        logger.info(f"  request.user: {self.request.user}")
        logger.info(f"  hasattr role: {hasattr(self.request.user, 'role') if self.request.user else 'N/A'}")

        # Check if this is a JWT user (not device)
        if self.request.user and hasattr(self.request.user, 'role'):
            logger.info(f"  user.role: {self.request.user.role}")
            # If user is ISSUER, show their work queue
            if self.request.user.role == 'ISSUER':
                active_statuses = ['PROCESSING', 'PARTIALLY_FULFILLED']
                logger.info(f"  FILTERING: Applying issuer queue filter for ISSUER")
                # Show: PROCESSING, PARTIALLY_FULFILLED, and active combined order children
                queryset = queryset.filter(
                    Q(is_in_issuance=True) |
                    Q(status__in=active_statuses) |
                    Q(
                        status='COMBINED_FULFILLED',
                        combined_orders__combined_order__parent_transaction__status__in=active_statuses
                    )
                ).distinct()
                logger.info(f"  Filtered queryset count: {queryset.count()}")
            else:
                logger.info(f"  NO FILTER: User role is {self.request.user.role}, showing all transactions")
        else:
            logger.info(f"  NO FILTER: Device or user without role")

        return queryset

class TransactionDetailView(generics.RetrieveUpdateAPIView):
    authentication_classes = [DeviceAPIKeyAuthentication, JWTAuthentication]
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer

    def get_permissions(self):
        """
        Custom permissions based on HTTP method.

        - GET (retrieve): Allow Devices, Processor, and Issuer
        - PUT/PATCH (update): Only Devices and Processor
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"TransactionDetailView.get_permissions: method={self.request.method}")
        logger.info(f"  request.user: {self.request.user}")
        logger.info(f"  user type: {type(self.request.user)}")
        logger.info(f"  is_authenticated: {self.request.user.is_authenticated if self.request.user else 'N/A'}")
        logger.info(f"  hasattr role: {hasattr(self.request.user, 'role') if self.request.user else 'N/A'}")

        if self.request.method == 'GET':
            # Anyone authenticated can view transactions
            logger.info("  Returning IsDeviceOrAuthenticated for GET")
            return [IsDeviceOrAuthenticated()]
        else:
            # Only Processor and devices can update
            logger.info("  Returning IsDeviceOrProcessor for PUT/PATCH")
            return [IsDeviceOrProcessor()]

    def update(self, request, *args, **kwargs):
        """
        Custom update logic with role-based validation and user tracking.

        Rules:
        - Processor: Can change status to PROCESSING (to queue for Issuer)
        - Processor: Can change PARTIALLY_FULFILLED back to PROCESSING
        - Issuer: CANNOT update (blocked by permissions)
        - Device: Can update (legacy support)

        User Tracking:
        - Automatically track who changed status to PROCESSING or CANCELLED
        """
        instance = self.get_object()

        # Check if this is a JWT user (not device)
        if request.user and hasattr(request.user, 'role'):
            # Track user actions for status changes
            if 'status' in request.data:
                new_status = request.data['status']

                # Track PROCESSING
                if new_status == 'PROCESSING' and instance.status != 'PROCESSING':
                    instance.processed_by = request.user
                    instance.processed_at = timezone.now()

                # Track CANCELLED
                if new_status == 'CANCELLED' and instance.status != 'CANCELLED':
                    instance.cancelled_by = request.user
                    instance.cancelled_at = timezone.now()

                # Processor can only change to PROCESSING or CANCELLED
                if request.user.role == 'PROCESSOR':
                    if new_status not in ['PROCESSING', 'CANCELLED']:
                        return Response(
                            {'error': 'Processor can only change status to PROCESSING or CANCELLED.'},
                            status=status.HTTP_400_BAD_REQUEST
                        )

        return super().update(request, *args, **kwargs)


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication])
def gateway_list(request):
    """
    Get list of M-Pesa payment gateways for device configuration.

    Returns only M-Pesa/merch gateways (MPESA_TILL, MERCHANDISE, MPESA_PAYBILL) since
    devices forward M-Pesa SMS messages. Other payment methods (Bank Transfer,
    Cash, PDQ, Cheque) are not relevant for device gateway assignment.

    Returns:
    - id, name, gateway_type, gateway_number for each M-Pesa gateway

    Note: Ordered alphabetically by name for consistent display across apps
    """
    gateways = PaymentGateway.objects.filter(
        is_active=True,
        gateway_type__in=['MPESA_TILL', 'MERCHANDISE', 'MPESA_PAYBILL']
    ).order_by('name').values(
        'id', 'name', 'gateway_type', 'gateway_number'
    )
    return Response(list(gateways))


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication])
def transaction_by_tx_id(request, tx_id):
    """
    Get transaction by tx_id (transaction ID).

    Usage:
    GET /api/transactions/by-tx-id/TX001234/

    Returns the transaction with matching tx_id.
    """
    try:
        transaction = Transaction.objects.get(tx_id=tx_id)
        serializer = TransactionSerializer(transaction)
        return Response(serializer.data)
    except Transaction.DoesNotExist:
        return Response(
            {'error': f'Transaction with tx_id "{tx_id}" not found'},
            status=status.HTTP_404_NOT_FOUND
        )


class ManualPaymentCreateView(APIView):
    """
    Create a manual payment entry.

    POST /api/payments/manual/
    {
        "payment_method": "PDQ",
        "reference_number": "PDQ123456",
        "payer_name": "John Doe",
        "payer_phone": "+254700000000",
        "payer_email": "john@example.com",
        "amount": "5000.00",
        "payment_date": "2025-10-09T10:30:00Z",
        "notes": "Payment for order #123",
        "created_by": "staff_user_1"
    }
    """
    authentication_classes = [DeviceAPIKeyAuthentication, JWTAuthentication]
    permission_classes = [IsAdminOrProcessor]

    def post(self, request, *args, **kwargs):
        serializer = ManualPaymentCreateSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        try:
            transaction, manual_payment = ManualPaymentService.create_manual_payment(
                payment_method=data['payment_method'],
                payer_name=data['payer_name'],
                amount=data['amount'],
                payment_date=data['payment_date'],
                created_by=data['created_by'],
                reference_number=data.get('reference_number'),
                payer_phone=data.get('payer_phone'),
                payer_email=data.get('payer_email'),
                notes=data.get('notes')
            )

            return Response({
                'transaction': TransactionSerializer(transaction).data,
                'manual_payment': ManualPaymentSerializer(manual_payment).data
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class ManualPaymentListView(generics.ListAPIView):
    """List all manual payment entries with enhanced filtering"""
    authentication_classes = [DeviceAPIKeyAuthentication, JWTAuthentication]
    permission_classes = [IsAdminOrProcessor]
    serializer_class = ManualPaymentSerializer
    queryset = ManualPayment.objects.all().select_related('transaction')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ManualPaymentFilter
    search_fields = ['payer_name', 'reference_number', 'notes']
    ordering_fields = ['payment_date', 'created_at', 'amount', 'payer_name']
    ordering = ['-payment_date']


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def manual_payment_summary(request):
    """
    Get summary of manual payments.

    Query params:
    - start_date: ISO format date (optional)
    - end_date: ISO format date (optional)
    - payment_method: Payment method filter (optional)
    """
    from django.utils.dateparse import parse_datetime

    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')
    payment_method = request.query_params.get('payment_method')

    if start_date:
        start_date = parse_datetime(start_date)
    if end_date:
        end_date = parse_datetime(end_date)

    summary = ManualPaymentService.get_manual_payments_summary(
        start_date=start_date,
        end_date=end_date,
        payment_method=payment_method
    )

    return Response(summary)


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def daily_reconciliation_report(request):
    """
    Generate daily reconciliation report by payment gateway.

    Query params:
    - report_date: Date in YYYY-MM-DD format (defaults to today)

    Example:
    GET /api/reports/daily-reconciliation/?report_date=2025-10-09

    Returns:
    - Gateway-wise transaction breakdown
    - Settlement calculations (parent vs shop amounts)
    - Status breakdown
    - Manual payments summary
    - Overall totals
    """
    report_date_str = request.query_params.get('report_date')

    if report_date_str:
        report_date = parse_date(report_date_str)
        if not report_date:
            return Response(
                {'error': 'Invalid date format. Use YYYY-MM-DD'},
                status=status.HTTP_400_BAD_REQUEST
            )
    else:
        report_date = None  # Will default to today

    try:
        report = ReconciliationService.generate_daily_report(report_date)
        return Response(report)
    except Exception as e:
        return Response(
            {'error': f'Failed to generate report: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def date_range_reconciliation_report(request):
    """
    Generate reconciliation report for a date range.

    Query params (required):
    - start_date: Start date in YYYY-MM-DD format
    - end_date: End date in YYYY-MM-DD format

    Example:
    GET /api/reports/date-range-reconciliation/?start_date=2025-10-01&end_date=2025-10-09

    Returns:
    - Daily reports for each day in range
    - Grand totals across all days
    """
    start_date_str = request.query_params.get('start_date')
    end_date_str = request.query_params.get('end_date')

    if not start_date_str or not end_date_str:
        return Response(
            {'error': 'Both start_date and end_date are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    start_date = parse_date(start_date_str)
    end_date = parse_date(end_date_str)

    if not start_date or not end_date:
        return Response(
            {'error': 'Invalid date format. Use YYYY-MM-DD'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if start_date > end_date:
        return Response(
            {'error': 'start_date must be before or equal to end_date'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        report = ReconciliationService.generate_date_range_report(start_date, end_date)
        return Response(report)
    except Exception as e:
        return Response(
            {'error': f'Failed to generate report: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def discrepancies_report(request):
    """
    Identify potential discrepancies in transactions.

    Checks for:
    - Low confidence transactions (< 70%)
    - Unprocessed transactions
    - Transactions without gateway info
    - Potentially stuck partially fulfilled orders

    Query params:
    - report_date: Date in YYYY-MM-DD format (defaults to today)

    Example:
    GET /api/reports/discrepancies/?report_date=2025-10-09

    Returns:
    - List of discrepancies by type
    - Count of issues requiring attention
    """
    report_date_str = request.query_params.get('report_date')

    if report_date_str:
        report_date = parse_date(report_date_str)
        if not report_date:
            return Response(
                {'error': 'Invalid date format. Use YYYY-MM-DD'},
                status=status.HTTP_400_BAD_REQUEST
            )
    else:
        report_date = None  # Will default to today

    try:
        report = ReconciliationService.identify_discrepancies(report_date)
        return Response(report)
    except Exception as e:
        return Response(
            {'error': f'Failed to generate discrepancy report: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def daily_reconciliation_v2(request):
    """
    Generate daily reconciliation report using the X/Y formula.

    Formula:
    X = Mpesa_Paybill - Unused + PDQ + Previous - Sales
    Y = Till - Previous - Credit - KITS
    X + Y should = 0

    Definitions:
    - Mpesa_Paybill: Total received to parent paybill gateway today
    - Unused: Unprocessed/unfulfilled on paybill (from 1st of month)
    - PDQ: Manual PDQ transactions today
    - Previous: Paybill payments from previous days fulfilled today
    - Till: Fulfilled amounts for Till gateway payments
    - Credit: Partially fulfilled balances on paybill
    - KITS: Registration count * 200
    - Sales: Total fulfilled from all gateways

    Query params:
    - report_date: Date in YYYY-MM-DD format (defaults to today)

    Returns:
    - x_value: Calculated X value
    - y_value: Calculated Y value
    - result: X + Y (should be 0 for balanced books)
    - is_balanced: Boolean indicating if result == 0
    - x_formula: Breakdown of X calculation
    - y_formula: Breakdown of Y calculation
    - details: Detailed breakdown of each component
    """
    from payments.services.reconciliation_v2_service import ReconciliationV2Service

    report_date_str = request.query_params.get('report_date')

    if report_date_str:
        report_date = parse_date(report_date_str)
        if not report_date:
            return Response(
                {'error': 'Invalid date format. Use YYYY-MM-DD'},
                status=status.HTTP_400_BAD_REQUEST
            )
    else:
        report_date = None  # Will default to today

    try:
        report = ReconciliationV2Service.generate_daily_report(report_date)
        return Response(report)
    except Exception as e:
        logger.error(f"Error generating V2 reconciliation report: {e}")
        return Response(
            {'error': f'Failed to generate V2 reconciliation report: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def daily_reconciliation_xlsx(request):
    """
    Generate and download enhanced daily reconciliation report as XLSX.

    Features:
    - Separate sheet per gateway
    - Status sections per sheet
    - Minimal field set (only required columns)
    - Gateway name for manual transactions
    - Date in filename

    Query params (optional):
    - date: Report date in YYYY-MM-DD format (defaults to today)

    Example:
    GET /api/reports/daily-reconciliation/xlsx/?date=2025-10-09

    Returns:
    XLSX file download with date-stamped filename
    """
    from payments.services.reconciliation_report_service import ReconciliationReportService
    from django.utils.dateparse import parse_date

    date_str = request.query_params.get('date')

    if date_str:
        report_date = parse_date(date_str)
        if not report_date:
            return Response(
                {'error': 'Invalid date format. Use YYYY-MM-DD'},
                status=status.HTTP_400_BAD_REQUEST
            )
    else:
        from django.utils import timezone
        report_date = timezone.localtime(timezone.now()).date()

    try:
        xlsx_buffer, filename = ReconciliationReportService.generate_daily_report_xlsx(report_date)

        # Create HTTP response with XLSX
        response = HttpResponse(
            xlsx_buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        logger.error(f"Error generating daily reconciliation XLSX: {e}")
        return Response(
            {'error': f'Failed to generate XLSX: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def date_range_reconciliation_xlsx(request):
    """
    Generate and download enhanced date range reconciliation report as XLSX.

    Features:
    - Separate sheet per gateway
    - Status sections per sheet
    - Minimal field set (only required columns)
    - Gateway name for manual transactions
    - Date range in filename

    Query params (required):
    - start_date: Start date in YYYY-MM-DD format
    - end_date: End date in YYYY-MM-DD format

    Example:
    GET /api/reports/date-range-reconciliation/xlsx/?start_date=2025-10-01&end_date=2025-10-09

    Returns:
    XLSX file download with date-stamped filename
    """
    from payments.services.reconciliation_report_service import ReconciliationReportService
    from django.utils.dateparse import parse_date

    start_date_str = request.query_params.get('start_date')
    end_date_str = request.query_params.get('end_date')

    if not start_date_str or not end_date_str:
        return Response(
            {'error': 'Both start_date and end_date are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    start_date = parse_date(start_date_str)
    end_date = parse_date(end_date_str)

    if not start_date or not end_date:
        return Response(
            {'error': 'Invalid date format. Use YYYY-MM-DD'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if start_date > end_date:
        return Response(
            {'error': 'start_date must be before or equal to end_date'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        xlsx_buffer, filename = ReconciliationReportService.generate_date_range_report_xlsx(start_date, end_date)

        # Create HTTP response with XLSX
        response = HttpResponse(
            xlsx_buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        logger.error(f"Error generating date range reconciliation XLSX: {e}")
        return Response(
            {'error': f'Failed to generate XLSX: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def unified_report_export(request):
    """
    Generate the unified daily report as a single Excel workbook.

    Sheets: All Transactions, Combined Orders, Registration Kits, Unfulfilled Orders.

    Query params:
    - date: Report date in YYYY-MM-DD format (defaults to today)

    GET /api/v1/exports/report/?date=2026-02-04
    """
    date_str = request.query_params.get('date')

    if date_str:
        report_date = parse_date(date_str)
        if not report_date:
            return Response(
                {'error': 'Invalid date format. Use YYYY-MM-DD'},
                status=status.HTTP_400_BAD_REQUEST
            )
    else:
        report_date = timezone.localtime(timezone.now()).date()

    today = timezone.localtime(timezone.now()).date()
    xlsx_bytes = None

    # For past dates, serve the persisted copy generated by the nightly task.
    # Fall back to on-the-fly generation if the row is missing.
    if report_date < today:
        from .models import GeneratedReport
        try:
            stored = GeneratedReport.objects.get(report_date=report_date)
            xlsx_bytes = bytes(stored.report_file)
        except GeneratedReport.DoesNotExist:
            pass  # fall through to on-the-fly generation

    try:
        if xlsx_bytes is None:
            xlsx_buffer = TransactionExportService.generate_unified_report(report_date)
            xlsx_bytes = xlsx_buffer.getvalue()

        filename = f'eagle_shop_report_{report_date}.xlsx'
        response = HttpResponse(
            xlsx_bytes,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        logger.error(f"Failed to generate unified report: {e}")
        return Response(
            {'error': f'Failed to generate report: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def analytics_overview(request):
    """
    Lightweight analytics summary for top cards.
    """
    try:
        start_date, end_date = AnalyticsService.parse_date_range(
            request.query_params.get('start_date'),
            request.query_params.get('end_date'),
        )
        revenue = AnalyticsService.revenue_analytics(start_date, end_date)
        products = AnalyticsService.product_analytics(start_date, end_date)
        merchandise = AnalyticsService.merchandise_analytics(start_date, end_date)

        return Response(
            {
                "date_range": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
                "revenue": revenue["summary"],
                "top_product": products["fast_moving_products"][0] if products["fast_moving_products"] else None,
                "top_merch_item": merchandise["top_items"][0] if merchandise["top_items"] else None,
            },
            status=status.HTTP_200_OK,
        )
    except ValueError:
        return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to build analytics overview: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def analytics_revenue(request):
    try:
        granularity = request.query_params.get('granularity', 'day')
        if granularity not in {'day', 'week', 'month'}:
            return Response({'error': 'granularity must be day, week, or month'}, status=status.HTTP_400_BAD_REQUEST)
        start_date, end_date = AnalyticsService.parse_date_range(
            request.query_params.get('start_date'),
            request.query_params.get('end_date'),
        )
        data = AnalyticsService.revenue_analytics(start_date, end_date, granularity=granularity)
        return Response(data, status=status.HTTP_200_OK)
    except ValueError:
        return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to build revenue analytics: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def analytics_products(request):
    try:
        start_date, end_date = AnalyticsService.parse_date_range(
            request.query_params.get('start_date'),
            request.query_params.get('end_date'),
        )
        data = AnalyticsService.product_analytics(start_date, end_date)
        return Response(data, status=status.HTTP_200_OK)
    except ValueError:
        return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to build products analytics: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def analytics_merchandise(request):
    try:
        start_date, end_date = AnalyticsService.parse_date_range(
            request.query_params.get('start_date'),
            request.query_params.get('end_date'),
        )
        data = AnalyticsService.merchandise_analytics(start_date, end_date)
        return Response(data, status=status.HTTP_200_OK)
    except ValueError:
        return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to build merchandise analytics: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ============================================================================
# Product & Inventory Views
# ============================================================================

class ProductLineListView(generics.ListCreateAPIView):
    """
    List and create product lines.

    GET: List all product lines
    POST: Create new product line
    """
    authentication_classes = [DeviceAPIKeyAuthentication]
    queryset = ProductLine.objects.all().prefetch_related('sublines', 'products')
    serializer_class = ProductLineSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']


class ProductLineDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a product line.

    GET: Get product line details
    PUT/PATCH: Update product line
    DELETE: Delete product line (only if no products assigned)
    """
    authentication_classes = [DeviceAPIKeyAuthentication]
    queryset = ProductLine.objects.all().prefetch_related('sublines', 'products')
    serializer_class = ProductLineSerializer


class ProductListView(generics.ListCreateAPIView):
    """
    List and create products.

    GET: List all products with search and filtering
    POST: Create new product

    Search fields:
    - prod_code, prod_name, sku, sku_name

    Filters:
    - is_active: Boolean (true/false)
    - product_line: Product Line ID
    """
    authentication_classes = [DeviceAPIKeyAuthentication]
    queryset = Product.objects.all().select_related('product_line')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['prod_code', 'prod_name', 'sku', 'sku_name']
    filterset_fields = ['is_active', 'product_line']
    ordering_fields = ['prod_code', 'prod_name', 'current_price', 'quantity', 'created_at']
    ordering = ['prod_code']
    
    def get_serializer_class(self):
        """Use minimal serializer for list, full serializer for detail/create."""
        if self.request.method == 'GET':
            return ProductListSerializer
        return ProductSerializer


class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a product.

    GET: Get product details
    PUT/PATCH: Update product (price, quantity, etc.)
    DELETE: Delete product (Admin only, only if not referenced in transactions)
    """
    authentication_classes = [DeviceAPIKeyAuthentication, JWTAuthentication]
    queryset = Product.objects.all().select_related('product_line')
    serializer_class = ProductSerializer

    def get_permissions(self):
        if self.request.method == 'DELETE':
            return [IsAdmin()]
        return []

    def destroy(self, request, *args, **kwargs):
        from django.db.models.deletion import ProtectedError
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError as e:
            return Response(
                {
                    'error': (
                        f'Cannot delete product — it is referenced in existing '
                        f'transactions, orders, or stock records. '
                        f'Remove all references first ({len(e.protected_objects)} references found).'
                    )
                },
                status=status.HTTP_409_CONFLICT
            )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsDeviceOrAuthenticated])
def product_search_by_sku(request):
    """
    Search for a product by SKU, prod_code, or barcode (for barcode scanner).

    Query params:
    - sku: SKU to search for
    - prod_code: Product code to search for
    - barcode: Barcode to search for (falls back to sku/prod_code match if barcode
               field is not populated on the product)

    Returns single product if found, 404 if not found.
    """
    sku = request.query_params.get('sku')
    prod_code = request.query_params.get('prod_code')
    barcode = request.query_params.get('barcode')

    if not sku and not prod_code and not barcode:
        return Response(
            {'error': 'Either sku, prod_code, or barcode parameter is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        if sku:
            product = Product.objects.get(sku=sku, is_active=True)
        elif prod_code:
            product = Product.objects.get(prod_code=prod_code, is_active=True)
        else:
            # Try dedicated barcode field first, then fall back to sku/prod_code.
            # This handles cases where products are identified by their SKU/prod_code
            # value rather than a separate barcode field.
            try:
                product = Product.objects.get(barcode=barcode, is_active=True)
            except Product.DoesNotExist:
                product = Product.objects.get(
                    Q(sku=barcode) | Q(prod_code=barcode),
                    is_active=True
                )

        serializer = ProductSerializer(product)
        return Response(serializer.data)
    except Product.DoesNotExist:
        return Response(
            {'error': 'Product not found'},
            status=status.HTTP_404_NOT_FOUND
        )


class InventoryMovementListView(generics.ListAPIView):
    """
    List inventory movements (audit trail).
    
    Filters:
    - product: Product ID
    - movement_type: Type of movement (SALE, PURCHASE, ADJUSTMENT, etc.)
    - start_date, end_date: Date range
    """
    authentication_classes = [DeviceAPIKeyAuthentication]
    queryset = InventoryMovement.objects.all().select_related('product')
    serializer_class = InventoryMovementSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['product', 'movement_type']
    ordering_fields = ['created_at', 'product', 'movement_type']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Filter by date range if provided."""
        queryset = super().get_queryset()
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date:
            queryset = queryset.filter(created_at__gte=parse_date(start_date))
        if end_date:
            queryset = queryset.filter(created_at__lte=parse_date(end_date))
        
        return queryset


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication])
def product_summary(request):
    """
    Get product inventory summary.
    
    Returns:
    - total_products: Total number of products
    - active_products: Number of active products
    - out_of_stock: Number of products with 0 quantity
    - low_stock: Number of products at or below reorder level
    - total_inventory_value: Sum of (quantity * cost_price) for all products
    """
    from django.db.models import Sum, Count, Q, F
    from decimal import Decimal
    
    products = Product.objects.filter(is_active=True)
    
    summary = {
        'total_products': Product.objects.count(),
        'active_products': products.count(),
        'out_of_stock': products.filter(quantity=0).count(),
        'low_stock': products.filter(Q(quantity__lte=F('reorder_level')) & Q(quantity__gt=0)).count(),
        'total_inventory_value': products.aggregate(
            total=Sum(F('quantity') * F('cost_price'))
        )['total'] or Decimal('0.00'),
        'total_retail_value': products.aggregate(
            total=Sum(F('quantity') * F('current_price'))
        )['total'] or Decimal('0.00'),
    }

    return Response(summary)


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def stock_report(request):
    """
    Generate comprehensive inventory stock report (JSON).

    Returns detailed stock information including:
    - Overall summary (total products, stock values, status counts)
    - Category-wise breakdown
    - Individual product details with stock status

    Example:
    GET /api/v1/reports/stock/

    Returns:
    JSON object with stock report data
    """
    from payments.services.stock_report_service import StockReportService

    try:
        report_data = StockReportService.generate_stock_report()
        return Response(report_data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error generating stock report: {e}")
        return Response(
            {'error': f'Failed to generate stock report: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def stock_report_xlsx(request):
    """
    Generate and download inventory stock report as XLSX.

    Features:
    - Summary sheet with overall statistics
    - Separate sheet per category
    - Color-coded stock status (Out of Stock, Low Stock, In Stock)
    - Timestamped filename

    Example:
    GET /api/v1/reports/stock/xlsx/

    Returns:
    XLSX file download with timestamped filename
    """
    from payments.services.stock_report_service import StockReportService

    try:
        xlsx_buffer, filename = StockReportService.generate_stock_report_xlsx()

        # Create HTTP response with XLSX
        response = HttpResponse(
            xlsx_buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        logger.error(f"Error generating stock report XLSX: {e}")
        return Response(
            {'error': f'Failed to generate XLSX: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def stock_report_historical(request):
    """
    Generate historical inventory stock report (JSON) for a specific date.

    Reconstructs stock levels as they were on the specified date by analyzing
    inventory movement records.

    Query Parameters:
    - date (required): Target date in YYYY-MM-DD format (e.g., 2025-01-15)

    Returns:
    JSON object with historical stock report data including:
    - Overall summary (total products, stock values, status counts)
    - Product line breakdown
    - Individual product details with historical quantities

    Example:
    GET /api/v1/reports/stock/historical/?date=2025-01-15
    """
    from payments.services.stock_report_service import StockReportService
    from datetime import datetime

    target_date_str = request.query_params.get('date')
    if not target_date_str:
        return Response(
            {'error': 'date parameter is required (format: YYYY-MM-DD)'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response(
            {'error': 'Invalid date format. Use YYYY-MM-DD (e.g., 2025-01-15)'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Use generate_stock_report_with_adjustments to include Added/Deducted/Notes columns
        report_data = StockReportService.generate_stock_report_with_adjustments(target_date)
        return Response(report_data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error generating historical stock report for {target_date}: {e}")
        return Response(
            {'error': f'Failed to generate historical stock report: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def stock_report_historical_xlsx(request):
    """
    Generate and download historical inventory stock report as XLSX for a specific date.

    Reconstructs stock levels as they were on the specified date by analyzing
    inventory movement records.

    Query Parameters:
    - date (required): Target date in YYYY-MM-DD format (e.g., 2025-01-15)

    Features:
    - Summary sheet with overall statistics
    - Separate sheet per product line
    - Color-coded stock status (Out of Stock, Low Stock, In Stock)
    - Date-specific filename

    Returns:
    XLSX file download with date in filename

    Example:
    GET /api/v1/reports/stock/historical/xlsx/?date=2025-01-15
    """
    from payments.services.stock_report_service import StockReportService
    from datetime import datetime

    target_date_str = request.query_params.get('date')
    if not target_date_str:
        return Response(
            {'error': 'date parameter is required (format: YYYY-MM-DD)'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response(
            {'error': 'Invalid date format. Use YYYY-MM-DD (e.g., 2025-01-15)'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Use generate_stock_report_xlsx_with_adjustments to include Added/Deducted/Notes columns
        xlsx_buffer, filename = StockReportService.generate_stock_report_xlsx_with_adjustments(target_date)

        # Create HTTP response with XLSX
        response = HttpResponse(
            xlsx_buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        logger.error(f"Error generating historical stock report XLSX for {target_date}: {e}")
        return Response(
            {'error': f'Failed to generate historical XLSX: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ============================================================================
# Transaction Fulfillment API Views
# ============================================================================

@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def issue_registration_kit(request, transaction_id):
    """
    Issue registration kit for a registration transaction.

    POST /api/v1/transactions/<id>/issue-registration-kit/

    Body: { "quantity": int (default 1) }

    Requirements:
    - Transaction must be marked as registration
    - Registration kit not already issued
    - Amount >= 2900 KES per kit
    """
    from payments.services.registration_kit_service import RegistrationKitService
    from django.core.exceptions import ValidationError

    try:
        quantity = request.data.get('quantity', 1)

        transaction_obj = RegistrationKitService.issue_registration_kit(
            transaction_id=transaction_id,
            quantity=int(quantity),
            issued_by=request.user.username if request.user else 'system'
        )

        return Response({
            'success': True,
            'message': f'Registration kit(s) issued successfully',
            'transaction': {
                'id': transaction_obj.id,
                'tx_id': transaction_obj.tx_id,
                'registration_kit_issued': transaction_obj.registration_kit_issued,
                'registration_kit_quantity': transaction_obj.registration_kit_quantity,
                'registration_kit_amount_deducted': str(transaction_obj.registration_kit_amount_deducted),
                'amount': str(transaction_obj.amount),
                'amount_fulfilled': str(transaction_obj.amount_fulfilled),
                'remaining_amount': str(transaction_obj.remaining_amount),
            }
        }, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except ValueError:
        return Response({'error': 'Invalid quantity value'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error issuing registration kit for transaction {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])  # Only JWT (users), not devices
@permission_classes([IsAdminOrIssuer])  # Changed: Issuer activates issuance, not Processor
def activate_transaction_issuance(request, transaction_id):
    """
    Activate issuance mode for a transaction (ISSUER role).

    Workflow:
    1. Processor changes transaction status to PROCESSING
    2. Issuer sees PROCESSING transactions in their queue
    3. Issuer activates issuance and fulfills the order

    Only one transaction can be in issuance at a time.
    """
    from payments.services.fulfillment_service import FulfillmentService
    from django.core.exceptions import ValidationError

    try:
        location = get_request_location(request)
        result = FulfillmentService.activate_issuance(
            transaction_id,
            activated_by_user=request.user,
            location=location,
        )
        return Response(result, status=status.HTTP_200_OK)
    except ValidationError as e:
        # Handle both dict-style and list-style ValidationErrors
        if hasattr(e, 'message_dict'):
            error_response = {'error': e.message_dict}
        elif hasattr(e, 'messages'):
            error_response = {'error': e.messages[0] if e.messages else str(e)}
        else:
            error_response = {'error': str(e)}
        return Response(error_response, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error activating issuance for transaction {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def scan_product_barcode(request, transaction_id):
    """
    Scan a product barcode and add it to the transaction.

    Request body:
    {
        "sku": "AP004E",          // Product SKU (optional)
        "prod_code": "AP004E",    // Product code (optional)
        "barcode": "893663002913", // Product barcode (optional)
        "quantity": 1,            // Quantity scanned (default: 1)
        "scanned_by": "User"      // Who performed the scan
    }
    Note: At least one of sku, prod_code, or barcode must be provided
    """
    from payments.services.fulfillment_service import FulfillmentService
    from payments.serializers import BarcodeScanSerializer
    from django.core.exceptions import ValidationError

    serializer = BarcodeScanSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    try:
        result = FulfillmentService.scan_barcode(
            transaction_id,
            serializer.validated_data,
            scanned_by_user=request.user if hasattr(request.user, 'role') else None
        )
        return Response(result, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response({'error': e.message_dict}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error scanning barcode for transaction {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def complete_transaction_issuance(request, transaction_id):
    """
    Complete the issuance and update inventory.

    This finalizes the transaction and deducts scanned products from inventory.
    Creates InventoryMovement records for audit trail.

    User automatically tracked from JWT token. If transaction is marked as registration,
    it will use the registration workflow instead.

    Request body: Empty (user from token)
    """
    from payments.services.fulfillment_service import FulfillmentService
    from payments.serializers import IssuanceCompleteSerializer
    from django.core.exceptions import ValidationError

    serializer = IssuanceCompleteSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Check if registration transaction
        transaction = Transaction.objects.get(id=transaction_id)

        # IMPORTANT: There are two registration workflows:
        # 1. Manual workflow: Issue registration kit manually, scan products, then complete
        #    -> Use normal complete_issuance() to preserve all scanned items
        # 2. Auto workflow: Complete registration in one step without manual kit issuance
        #    -> Use complete_registration_issuance() to auto-create registration kit line item
        #
        # We determine which workflow by checking if registration kit was already issued manually
        if transaction.is_registration and not transaction.registration_kit_issued:
            # Auto workflow: registration kit not yet issued, auto-issue it now
            quantity = request.data.get('quantity', 1)
            result = FulfillmentService.complete_registration_issuance(
                transaction_id,
                quantity=quantity,
                completed_by_user=request.user if hasattr(request.user, 'role') else None
            )
        else:
            # Normal workflow (including manual registration workflow)
            # This preserves all scanned products and correctly calculates status
            result = FulfillmentService.complete_issuance(
                transaction_id,
                completed_by_user=request.user if hasattr(request.user, 'role') else None
            )
        return Response(result, status=status.HTTP_200_OK)
    except ValidationError as e:
        # Handle both dict-style and list-style ValidationErrors
        if hasattr(e, 'message_dict'):
            error_response = {'error': e.message_dict}
        elif hasattr(e, 'messages'):
            error_response = {'error': e.messages[0] if e.messages else str(e)}
        else:
            error_response = {'error': str(e)}
        return Response(error_response, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error completing issuance for transaction {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def remove_line_item(request, transaction_id, line_item_id):
    """
    Remove a specific line item from the transaction during issuance.

    Behavior:
    - If item has NOT been deducted from inventory (is_inventory_deducted=False):
      Just deletes the item and updates totals. No inventory change.
    - If item HAS been deducted (is_inventory_deducted=True):
      Returns the inventory and creates an InventoryMovement record for audit.

    Can only be used while transaction is in an active/modifiable state.
    """
    from payments.models import Transaction, TransactionLineItem, Product, InventoryMovement
    from django.db import transaction as db_transaction
    from decimal import Decimal

    try:
        with db_transaction.atomic():
            # Get transaction
            txn = Transaction.objects.select_for_update().get(id=transaction_id)

            # Verify transaction can be modified
            if txn.status not in [
                Transaction.OrderStatus.NOT_PROCESSED,
                Transaction.OrderStatus.PROCESSING,
                Transaction.OrderStatus.PARTIALLY_FULFILLED
            ]:
                return Response(
                    {'error': f'Cannot modify line items for {txn.get_status_display()} transactions'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Get line item
            line_item = TransactionLineItem.objects.select_for_update().get(
                id=line_item_id,
                transaction=txn
            )

            # Store values before deleting
            line_total = line_item.line_total
            line_cost = line_item.line_cost
            line_pv = line_item.line_pv
            product_name = line_item.scanned_prod_name
            was_deducted = line_item.is_inventory_deducted
            quantity = line_item.quantity
            product_id = line_item.product_id

            inventory_returned = False

            # If inventory was already deducted, return it
            if was_deducted and product_id:
                product = Product.objects.select_for_update().get(id=product_id)
                quantity_before = product.quantity
                product.quantity += quantity
                product.save()

                # Create inventory movement for audit trail
                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.MovementType.RETURN,
                    product=product,
                    quantity_before=quantity_before,
                    quantity_after=product.quantity,
                    quantity_change=quantity,
                    reference=f'Removed from Transaction {txn.tx_id}',
                    performed_by=request.user.username if hasattr(request.user, 'username') else 'System'
                )
                inventory_returned = True
                logger.info(
                    f"Returned {quantity}x {product_name} to inventory "
                    f"(removed from transaction {txn.tx_id})"
                )

            # Delete the line item
            line_item.delete()

            # Re-evaluate promotions after removal (may revert prices on remaining items)
            from payments.services.promotion_service import PromotionService
            PromotionService.apply_promotions(
                TransactionLineItem.objects.filter(transaction=txn)
            )

            # Recalculate transaction totals from remaining items
            remaining_items = txn.line_items.all()
            new_fulfilled = sum(item.line_total for item in remaining_items)
            new_cost = sum(item.line_cost for item in remaining_items)
            new_pv = sum(item.line_pv for item in remaining_items)

            # For registration transactions, add the kit amount to fulfilled
            # ONLY if the kit is NOT already in remaining line items.
            # If RegistrationKitService.issue_registration_kit created a REG_KIT_001
            # line item, it's already included in the sum above.
            reg_kit_in_remaining = any(
                item.product and item.product.prod_code == 'REG_KIT_001'
                for item in remaining_items
            )
            if txn.is_registration and txn.registration_kit_issued and not reg_kit_in_remaining:
                new_fulfilled += txn.registration_kit_amount_deducted

            txn.amount_fulfilled = new_fulfilled
            txn.amount_paid = new_fulfilled  # Keep in sync to avoid model save() override
            txn.total_cost = new_cost
            txn.total_pv = new_pv

            # Update status based on new totals
            # Check if there are any completed items remaining
            has_completed_items = remaining_items.filter(is_inventory_deducted=True).exists()
            has_kit_issued = txn.is_registration and txn.registration_kit_issued

            if new_fulfilled == 0 and not has_kit_issued:
                # Keep PROCESSING if still in issuance (transaction was activated, not yet completed)
                if not txn.is_in_issuance:
                    txn.status = Transaction.OrderStatus.NOT_PROCESSED
                else:
                    txn.status = Transaction.OrderStatus.PROCESSING
            elif new_fulfilled > 0 and new_fulfilled < txn.amount:
                txn.status = Transaction.OrderStatus.PARTIALLY_FULFILLED
            elif new_fulfilled >= txn.amount:
                txn.status = Transaction.OrderStatus.FULFILLED

            # Skip validation to allow status transitions when removing line items
            txn.save(skip_validation=True)

            # Refresh from DB to get updated property values
            txn.refresh_from_db()

            message = f'Removed {product_name}'
            if inventory_returned:
                message += f' ({quantity} returned to inventory)'

            return Response({
                'success': True,
                'message': message,
                'line_item_id': line_item_id,
                'amount_removed': str(line_total),
                'inventory_returned': inventory_returned,
                'quantity_returned': quantity if inventory_returned else 0,
                'all_line_items': [
                    {
                        'id': item.id,
                        'product_code': item.scanned_prod_code,
                        'product_name': item.scanned_prod_name,
                        'quantity': item.quantity,
                        'unit_price': str(item.scanned_price),
                        'line_total': str(item.line_total),
                    }
                    for item in remaining_items
                ],
                'transaction_totals': {
                    'amount_fulfilled': str(txn.amount_fulfilled),
                    'remaining_amount': str(txn.remaining_amount),
                    'status': txn.status
                }
            }, status=status.HTTP_200_OK)

    except Transaction.DoesNotExist:
        return Response(
            {'error': 'Transaction not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except TransactionLineItem.DoesNotExist:
        return Response(
            {'error': 'Line item not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Product.DoesNotExist:
        return Response(
            {'error': 'Product not found for inventory return'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    except Exception as e:
        logger.error(f"Error removing line item {line_item_id} from transaction {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsProcessor])
def revert_to_processing(request, transaction_id):
    """
    Revert a PARTIALLY_FULFILLED transaction back to PROCESSING status.

    This allows processors to add more items to a partially fulfilled transaction.

    Validation:
    - Transaction must be PARTIALLY_FULFILLED
    - Cannot be in a combined order
    - Time-locked transactions require admin role

    Request body:
    {
        "reason": "Need to add more items"  // Optional reason for audit
    }
    """
    from payments.models import Transaction
    from django.core.exceptions import ValidationError
    from django.utils import timezone

    try:
        transaction = Transaction.objects.get(id=transaction_id)

        # Validation: Must be PARTIALLY_FULFILLED
        if transaction.status != Transaction.OrderStatus.PARTIALLY_FULFILLED:
            return Response(
                {'error': f'Transaction must be PARTIALLY_FULFILLED. Current status: {transaction.get_status_display()}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validation: Cannot be in combined order
        if transaction.combined_orders.exists():
            return Response(
                {'error': 'Cannot revert transactions that are part of a combined order'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validation: Time-locked requires admin role
        if transaction.is_time_locked and not request.user.is_admin():
            return Response(
                {'error': 'Time-locked transactions can only be reverted by admins'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get reason from request
        reason = request.data.get('reason', 'Reverted to add more items')

        # Update transaction status
        transaction.status = Transaction.OrderStatus.PROCESSING
        transaction.processed_by = request.user
        transaction.processed_at = timezone.now()

        # Append note with reason
        timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        revert_note = f"\n[{timestamp}] Reverted to PROCESSING by {request.user.username}: {reason}"
        transaction.notes = (transaction.notes or '') + revert_note

        # Clear time-lock if admin is reverting
        if transaction.is_time_locked and request.user.is_admin():
            transaction.is_time_locked = False
            transaction.locked_at = None
            transaction.locked_by = None

        transaction.save()
        transaction.refresh_from_db()

        return Response({
            'success': True,
            'message': 'Transaction reverted to PROCESSING',
            'transaction': TransactionSerializer(transaction).data
        }, status=status.HTTP_200_OK)

    except Transaction.DoesNotExist:
        return Response(
            {'error': 'Transaction not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Error reverting transaction {transaction_id} to processing: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def cancel_transaction_issuance(request, transaction_id):
    """
    Cancel the current issuance without updating inventory.

    Removes all line items and resets the transaction to its previous state.
    Does NOT update inventory.

    Request body:
    {
        "reason": "Optional cancellation reason"
    }
    """
    from payments.services.fulfillment_service import FulfillmentService
    from payments.serializers import IssuanceCancelSerializer
    from django.core.exceptions import ValidationError

    serializer = IssuanceCancelSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    try:
        result = FulfillmentService.cancel_issuance(
            transaction_id,
            reason=serializer.validated_data.get('reason', '')
        )
        return Response(result, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response({'error': e.message_dict}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error cancelling issuance for transaction {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def get_current_issuance(request):
    """
    Get the currently active issuance transaction, if any.

    Returns transaction details with line items if one is in issuance,
    otherwise returns null.
    """
    from payments.services.fulfillment_service import FulfillmentService

    try:
        location = get_request_location(request)
        result = FulfillmentService.get_current_issuance(location=location)
        if result is None:
            return Response({'current_issuance': None}, status=status.HTTP_200_OK)
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error getting current issuance: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================================
# Time-Locking Endpoints
# ============================================================================

@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def lock_partial_transactions(request):
    """
    Manually trigger time-locking of partially fulfilled transactions.
    
    Locks all PARTIALLY_FULFILLED transactions for a specific date.
    Once locked, transactions cannot be unlocked (permanent lock per business rules).
    
    POST /api/v1/transactions/lock-partial/
    
    Request body:
    {
        "target_date": "2025-12-02",  # Optional, defaults to today
        "locked_by": "Admin User"      # Optional, defaults to "Manual API Call"
    }
    
    Response:
    {
        "success": true,
        "locked_count": 5,
        "locked_tx_ids": ["TX001", "TX002", ...],
        "total_remaining_amount": 1500.00,
        "target_date": "2025-12-02",
        "locked_at": "2025-12-02T23:59:59Z",
        "locked_by": "Admin User"
    }
    """
    target_date_str = request.data.get('target_date')
    target_date = parse_date(target_date_str) if target_date_str else None
    locked_by = request.data.get('locked_by', 'Manual API Call')
    
    try:
        result = TimeLockingService.lock_partially_fulfilled_transactions(
            target_date=target_date,
            locked_by=locked_by
        )
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Failed to lock transactions: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def lockable_transactions(request):
    """
    Get list of transactions eligible for time-locking.
    
    Returns PARTIALLY_FULFILLED transactions that are not yet locked for a specific date.
    
    GET /api/v1/transactions/lockable/?date=2025-12-02
    
    Query parameters:
    - date: Date to check (defaults to today)
    
    Response:
    {
        "count": 5,
        "transactions": [...]  # Array of transaction objects
    }
    """
    target_date_str = request.GET.get('date')
    target_date = parse_date(target_date_str) if target_date_str else None
    
    transactions = TimeLockingService.get_lockable_transactions(target_date)
    serializer = TransactionSerializer(transactions, many=True)
    
    return Response({
        'count': transactions.count(),
        'transactions': serializer.data
    })


# ============================================================================
# Combined Order Views (Phase 2: Transaction Combination)
# ============================================================================

@api_view(['GET', 'POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def combined_order_list_create(request):
    """
    List combined orders or create a new one.

    GET /api/v1/combined-orders/
    Query parameters:
    - status: Filter by status (PENDING, IN_PROGRESS, FULFILLED, CANCELLED)
    - limit: Max results (default 50)
    - offset: Pagination offset (default 0)

    POST /api/v1/combined-orders/
    Body:
    {
        "transaction_ids": [123, 456, 789],
        "customer_name": "John Doe",
        "customer_phone": "0712345678",
        "notes": "...",
        "created_by": "admin"
    }
    """
    if request.method == 'GET':
        status_filter = request.GET.get('status')
        limit = int(request.GET.get('limit', 50))
        offset = int(request.GET.get('offset', 0))

        result = CombinedOrderService.list_combined_orders(
            status=status_filter,
            limit=limit,
            offset=offset
        )

        return Response(result, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        from payments.serializers import CombinedOrderCreateSerializer

        serializer = CombinedOrderCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = CombinedOrderService.create_combined_order(
                transaction_ids=serializer.validated_data['transaction_ids'],
                created_by=serializer.validated_data['created_by'],
                customer_name=serializer.validated_data.get('customer_name', ''),
                customer_phone=serializer.validated_data.get('customer_phone', ''),
                notes=serializer.validated_data.get('notes', ''),
                created_by_user=request.user if hasattr(request.user, 'role') else None,
                location=get_request_location(request),
            )

            return Response(result, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            # Extract error message from ValidationError
            if hasattr(e, 'message_dict'):
                error_message = e.message_dict
            elif hasattr(e, 'messages'):
                error_message = e.messages[0] if e.messages else str(e)
            else:
                error_message = str(e.message) if hasattr(e, 'message') else str(e)
            return Response({'error': error_message}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Failed to create combined order: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsDeviceOrAuthenticated])
def combined_order_detail(request, combined_order_id):
    """
    Get detailed information about a combined order.

    GET /api/v1/combined-orders/<combined_order_id>/

    Response includes:
    - Combined order details
    - All linked transactions
    - All line items
    """
    try:
        result = CombinedOrderService.get_combined_order_details(combined_order_id)
        return Response(result, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Failed to get combined order details: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def add_transactions_to_combined_order(request, combined_order_id):
    """
    Add NOT_PROCESSED or PROCESSING transactions to a PENDING or PARTIALLY_FULFILLED combined order.

    POST /api/v1/combined-orders/<combined_order_id>/add-transactions/
    Body:
    {
        "transaction_ids": [15, 16, 17]
    }

    Validation:
    - Combined order must be PENDING or PARTIALLY_FULFILLED
    - Transactions must be NOT_PROCESSED or PROCESSING
    - Transactions not already in another combined order
    - No active stock-taking session
    - Transactions not time-locked

    Response:
    {
        "success": true,
        "message": "Added 3 transactions to combined order",
        "combined_order": {...},
        "added_count": 3,
        "new_total_amount": "1200.00"
    }
    """
    from payments.models import CombinedOrder, Transaction, CombinedOrderTransaction, CombinedOrderLineItem, StockTakeSession, Product
    from payments.serializers import CombinedOrderSerializer
    from payments.services.combined_order_service import CombinedOrderService
    from django.core.exceptions import ValidationError
    from django.utils import timezone
    from django.db import transaction as db_transaction
    from django.db.models import Max
    from decimal import Decimal

    # --- validation phase (outside the atomic block; read-only) ---
    try:
        combined_order = CombinedOrder.objects.get(combined_order_id=combined_order_id)
    except CombinedOrder.DoesNotExist:
        return Response(
            {'error': 'Combined order not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if combined_order.status not in ['PENDING', 'IN_PROGRESS', 'PARTIALLY_FULFILLED', 'PROCESSING']:
        return Response(
            {'error': f'Can only add transactions to PENDING, IN_PROGRESS, PROCESSING, or PARTIALLY_FULFILLED orders. Current status: {combined_order.status}'},
            status=status.HTTP_400_BAD_REQUEST
        )

    transaction_ids = request.data.get('transaction_ids', [])
    if not transaction_ids:
        return Response(
            {'error': 'transaction_ids is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Stock take check only applies when modifying a main-shop combined order
    order_location = combined_order.location or Location.get_main_location()
    if order_location.is_main and StockTakeSession.objects.filter(status='DRAFT').exists():
        return Response(
            {'error': 'Cannot modify combined orders while stock-taking session is active'},
            status=status.HTTP_400_BAD_REQUEST
        )

    transactions = Transaction.objects.filter(id__in=transaction_ids)
    if transactions.count() != len(transaction_ids):
        return Response(
            {'error': 'Some transactions not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Collect parent-transaction IDs in one query instead of per-row hasattr
    parent_tx_ids = set(
        CombinedOrder.objects.filter(parent_transaction_id__in=transaction_ids)
        .values_list('parent_transaction_id', flat=True)
    )

    errors = []
    additional_amount_fulfilled = Decimal('0')
    for txn in transactions:
        if txn.id in parent_tx_ids:
            errors.append(f'Transaction {txn.tx_id}: Cannot add a combined order parent transaction')

        allowed_statuses = [
            Transaction.OrderStatus.NOT_PROCESSED,
            Transaction.OrderStatus.PARTIALLY_FULFILLED
        ]
        if txn.status not in allowed_statuses:
            errors.append(f'Transaction {txn.tx_id}: Must be NOT_PROCESSED or PARTIALLY_FULFILLED (current: {txn.get_status_display()})')

        if txn.combined_orders.exists():
            existing_order = txn.combined_orders.first().combined_order
            errors.append(f'Transaction {txn.tx_id}: Already in combined order {existing_order.combined_order_id}')

        if txn.is_time_locked:
            errors.append(f'Transaction {txn.tx_id}: Time-locked and cannot be modified')

        if txn.amount_fulfilled > 0:
            additional_amount_fulfilled += txn.amount_fulfilled

    if errors:
        return Response({'error': errors}, status=status.HTTP_400_BAD_REQUEST)

    # --- mutation phase (atomic) ---
    try:
        with db_transaction.atomic():
            added_by = request.user.username if hasattr(request.user, 'username') else 'System'

            current_max_sequence = CombinedOrderTransaction.objects.filter(
                combined_order=combined_order
            ).aggregate(max_seq=Max('sequence'))['max_seq'] or 0

            copied_items_count = 0
            for idx, txn in enumerate(transactions):
                CombinedOrderTransaction.objects.create(
                    combined_order=combined_order,
                    transaction=txn,
                    sequence=current_max_sequence + idx + 1,
                    added_by=added_by
                )

                # Copy deducted line items from partially fulfilled transactions
                for line_item in txn.line_items.filter(is_inventory_deducted=True):
                    co_line_item = CombinedOrderLineItem.objects.create(
                        combined_order=combined_order,
                        product=line_item.product,
                        scanned_prod_code=line_item.scanned_prod_code,
                        scanned_prod_name=line_item.scanned_prod_name,
                        scanned_sku=line_item.scanned_sku,
                        scanned_sku_name=line_item.scanned_sku_name,
                        scanned_price=line_item.scanned_price,
                        scanned_pv=line_item.scanned_pv,
                        quantity=line_item.quantity,
                        line_total=line_item.line_total,
                        line_cost=line_item.line_cost,
                        line_pv=line_item.line_pv,
                        is_inventory_deducted=True,
                        copied_from_transaction=txn,
                        scanned_by=line_item.scanned_by or added_by
                    )
                    # Preserve original scan timestamp for accurate daily sales reporting
                    CombinedOrderLineItem.objects.filter(pk=co_line_item.pk).update(
                        scanned_at=line_item.scanned_at
                    )
                    copied_items_count += 1

                # Synthetic line item for registration kits (same as create_combined_order)
                if txn.is_registration and txn.registration_kit_issued:
                    try:
                        reg_kit_product = Product.objects.get(prod_code='REG_KIT_001')
                        kit_quantity = txn.registration_kit_quantity or 1
                        kit_price = txn.registration_kit_amount_deducted / kit_quantity
                        CombinedOrderLineItem.objects.create(
                            combined_order=combined_order,
                            product=reg_kit_product,
                            scanned_prod_code='REG_KIT_001',
                            scanned_prod_name='Registration Kit',
                            scanned_sku=reg_kit_product.sku,
                            scanned_sku_name=reg_kit_product.sku_name or '',
                            scanned_price=kit_price,
                            scanned_pv=reg_kit_product.current_pv,
                            quantity=kit_quantity,
                            line_total=txn.registration_kit_amount_deducted,
                            line_cost=reg_kit_product.cost_price * kit_quantity,
                            line_pv=reg_kit_product.current_pv * kit_quantity,
                            is_inventory_deducted=True,
                            copied_from_transaction=txn,
                            scanned_by='System (Registration Kit)'
                        )
                        copied_items_count += 1
                        logger.info(f"Created registration kit line item for transaction {txn.tx_id}")
                    except Product.DoesNotExist:
                        logger.warning(f"Registration kit product (REG_KIT_001) not found when adding transaction {txn.tx_id}")

                # Mark child as COMBINED_FULFILLED (same as create_combined_order)
                txn.status = Transaction.OrderStatus.COMBINED_FULFILLED
                txn.processed_by = request.user
                txn.processed_at = timezone.now()
                txn.save()

            logger.info(f"Copied {copied_items_count} line items from added transactions")

            # --- recalculate totals (mirrors create_combined_order logic) ---
            combined_order.refresh_from_db()

            # total_amount = sum of ALL linked child transaction amounts
            linked_transactions = CombinedOrderTransaction.objects.filter(
                combined_order=combined_order
            ).select_related('transaction')
            total_amount = sum(
                Decimal(str(link.transaction.amount))
                for link in linked_transactions
            )

            # base_amount_fulfilled accumulates: previous base + newly added transactions' fulfillment.
            # It must NOT be recomputed from line items because completed-order line items
            # (is_inventory_deducted=True, copied_from_transaction=None) would inflate it.
            combined_order.base_amount_fulfilled = combined_order.base_amount_fulfilled + additional_amount_fulfilled

            # amount_fulfilled via the shared helper — handles orphan fulfillment correctly
            combined_order.total_amount = total_amount
            combined_order.amount_fulfilled = CombinedOrderService.recalculate_amount_fulfilled(combined_order)

            # Status: bump to PARTIALLY_FULFILLED if anything is fulfilled and we were PENDING
            if combined_order.amount_fulfilled > 0 and combined_order.status == 'PENDING':
                combined_order.status = CombinedOrder.Status.PARTIALLY_FULFILLED

            combined_order.save(update_fields=['total_amount', 'amount_fulfilled', 'base_amount_fulfilled', 'status', 'updated_at'])

            logger.info(
                f"Recalculated combined order {combined_order_id}: "
                f"linked={linked_transactions.count()}, total={total_amount}, "
                f"fulfilled={combined_order.amount_fulfilled}, base={combined_order.base_amount_fulfilled}"
            )

            # Sync parent transaction (same pattern as create_combined_order)
            if combined_order.parent_transaction:
                parent = combined_order.parent_transaction
                parent.amount = combined_order.total_amount
                parent.amount_fulfilled = combined_order.amount_fulfilled
                parent.amount_paid = combined_order.amount_fulfilled
                if combined_order.amount_fulfilled >= combined_order.total_amount:
                    parent.status = Transaction.OrderStatus.FULFILLED
                elif combined_order.amount_fulfilled > 0:
                    parent.status = Transaction.OrderStatus.PARTIALLY_FULFILLED
                elif parent.status == Transaction.OrderStatus.NOT_PROCESSED:
                    parent.status = Transaction.OrderStatus.PROCESSING
                parent.save(update_fields=['amount', 'amount_fulfilled', 'amount_paid', 'status', 'updated_at'], skip_validation=True)
                logger.info(f"Updated parent transaction {parent.tx_id}: amount={parent.amount}, fulfilled={parent.amount_fulfilled}, status={parent.status}")

        # atomic block committed — safe to read back and respond
        combined_order.refresh_from_db()
        return Response({
            'success': True,
            'message': f'Added {len(transaction_ids)} transaction(s) to combined order',
            'combined_order': CombinedOrderSerializer(combined_order).data,
            'added_count': len(transaction_ids),
            'new_total_amount': str(combined_order.total_amount)
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error adding transactions to combined order {combined_order_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def combined_order_scan_product(request, combined_order_id):
    """
    Scan a product into a combined order for fulfillment.

    POST /api/v1/combined-orders/<combined_order_id>/scan/
    Body:
    {
        "product_id": 123,
        "quantity": 2,
        "scanned_by": "admin"
    }

    Response:
    {
        "success": true,
        "line_item": {...},
        "combined_order": {...},
        "amount_fulfilled": "800.00",
        "remaining_amount": "400.00",
        "fulfillment_percentage": "66.67",
        "is_fulfilled": false
    }
    """
    from payments.serializers import CombinedOrderScanSerializer

    serializer = CombinedOrderScanSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        result = CombinedOrderService.scan_product_to_combined_order(
            combined_order_id=combined_order_id,
            product_id=serializer.validated_data['product_id'],
            quantity=serializer.validated_data.get('quantity', 1),
            scanned_by=serializer.validated_data.get('scanned_by', 'System')
        )

        # Convert Decimal fields to strings for JSON response
        from payments.serializers import CombinedOrderSerializer, CombinedOrderLineItemSerializer

        response_data = {
            'success': True,
            'line_item': CombinedOrderLineItemSerializer(result['line_item']).data,
            'combined_order': CombinedOrderSerializer(result['combined_order']).data,
            'amount_fulfilled': str(result['amount_fulfilled']),
            'remaining_amount': str(result['remaining_amount']),
            'fulfillment_percentage': str(result['fulfillment_percentage']),
            'is_fulfilled': result['is_fulfilled']
        }

        return Response(response_data, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to scan product to combined order: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def combined_order_cancel(request, combined_order_id):
    """
    Cancel a combined order and reverse any issued products.

    POST /api/v1/combined-orders/<combined_order_id>/cancel/
    Body:
    {
        "cancelled_by": "admin",
        "reason": "Customer request"
    }

    Response:
    {
        "success": true,
        "combined_order_id": "CMB-20251202-001",
        "reversed_line_items": 3,
        "status": "CANCELLED"
    }
    """
    from payments.serializers import CombinedOrderCancelSerializer

    serializer = CombinedOrderCancelSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    cancelled_by = serializer.validated_data.get('cancelled_by')
    if not cancelled_by:
        if hasattr(request.user, 'username'):
            cancelled_by = request.user.username
        elif hasattr(request.user, 'name'):
            cancelled_by = request.user.name
        else:
            cancelled_by = 'system'

    try:
        result = CombinedOrderService.cancel_combined_order(
            combined_order_id=combined_order_id,
            cancelled_by=cancelled_by,
            reason=serializer.validated_data.get('reason', '')
        )

        return Response(result, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def combined_order_revert(request, combined_order_id):
    """
    Completely revert a combined order to pre-combination state.

    This endpoint:
    1. Reverses ALL inventory changes (returns products to stock)
    2. Restores child transactions to their original status
    3. Deletes all line items
    4. Deletes the combined order entirely

    Use this when you want to completely undo a combination and start fresh.

    POST /api/v1/combined-orders/<combined_order_id>/revert/
    Body:
    {
        "reverted_by": "admin",
        "reason": "Need to recombine with correct transactions"
    }

    Response:
    {
        "success": true,
        "combined_order_id": "CMB-20251202-001",
        "parent_transaction_id": "CMB-20251202-001",
        "reversed_line_items": 3,
        "restored_transactions": [
            {"tx_id": "ABC123", "restored_status": "NOT_PROCESSED"}
        ],
        "inventory_movements_created": 3,
        "message": "Combined order reverted successfully..."
    }
    """
    from payments.serializers import CombinedOrderCancelSerializer

    serializer = CombinedOrderCancelSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    reverted_by = serializer.validated_data.get('cancelled_by')  # Reuse same field
    if not reverted_by:
        if hasattr(request.user, 'username'):
            reverted_by = request.user.username
        elif hasattr(request.user, 'name'):
            reverted_by = request.user.name
        else:
            reverted_by = 'system'

    try:
        result = CombinedOrderService.revert_combined_order(
            combined_order_id=combined_order_id,
            reverted_by=reverted_by,
            reason=serializer.validated_data.get('reason', '')
        )

        return Response(result, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def combined_order_cancel_issuance(request, combined_order_id):
    """
    Cancel current issuance session for a combined order.
    Reverts only the pending changes from this session.

    POST /api/v1/combined-orders/<combined_order_id>/cancel-issuance/
    Body:
    {
        "cancelled_by": "admin",
        "reason": "User cancelled session"
    }
    """
    from payments.serializers import CombinedOrderCancelSerializer

    logger.info(f"[CANCEL ISSUANCE API] Received cancel-issuance request for order: {combined_order_id}")
    logger.info(f"[CANCEL ISSUANCE API] Request data: {request.data}")

    serializer = CombinedOrderCancelSerializer(data=request.data)
    if not serializer.is_valid():
        logger.error(f"[CANCEL ISSUANCE API] Serializer validation failed: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    cancelled_by = serializer.validated_data.get('cancelled_by')
    if not cancelled_by:
        if hasattr(request.user, 'username'):
            cancelled_by = request.user.username
        elif hasattr(request.user, 'name'):
            cancelled_by = request.user.name
        else:
            cancelled_by = 'system'

    reason = serializer.validated_data.get('reason', '')
    logger.info(f"[CANCEL ISSUANCE API] Serializer validated: cancelled_by={cancelled_by}, reason={reason}")

    try:
        result = CombinedOrderService.cancel_combined_order_issuance(
            combined_order_id=combined_order_id,
            cancelled_by=cancelled_by,
            reason=reason
        )

        logger.info(f"[CANCEL ISSUANCE API] Cancel successful: {result}")
        return Response(result, status=status.HTTP_200_OK)

    except ValidationError as e:
        # Log the full ValidationError details
        logger.error(f"[CANCEL ISSUANCE API] ValidationError raised")
        logger.error(f"[CANCEL ISSUANCE API] Error message: {str(e)}")
        if hasattr(e, 'message_dict'):
            logger.error(f"[CANCEL ISSUANCE API] Message dict: {e.message_dict}")
        if hasattr(e, 'messages'):
            logger.error(f"[CANCEL ISSUANCE API] Messages: {e.messages}")
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"[CANCEL ISSUANCE API] Unexpected error: {type(e).__name__}: {str(e)}")
        import traceback
        logger.error(f"[CANCEL ISSUANCE API] Traceback: {traceback.format_exc()}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def combined_order_activate(request, combined_order_id):
    """
    Activate a combined order for fulfillment.

    POST /api/v1/combined-orders/<combined_order_id>/activate/
    Body: {"activated_by": "admin"}
    """
    activated_by = request.data.get('activated_by', 'system')

    try:
        order = CombinedOrderService.activate_combined_order(
            combined_order_id=combined_order_id,
            activated_by=activated_by
        )

        return Response({
            'success': True,
            'combined_order_id': order.combined_order_id,
            'status': order.status
        }, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to activate combined order: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def combined_order_scan_staged(request, combined_order_id):
    """
    Scan product to combined order (staged - inventory not updated yet).

    POST /api/v1/combined-orders/<combined_order_id>/scan-staged/
    Body: {
        "product_id": 1,
        "quantity": 2,
        "scanned_by": "admin"
    }
    """
    product_id = request.data.get('product_id')
    quantity = request.data.get('quantity', 1)
    scanned_by = request.data.get('scanned_by', 'system')

    if not product_id:
        return Response({'error': 'product_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        line_item = CombinedOrderService.scan_product_to_combined_order_staged(
            combined_order_id=combined_order_id,
            product_id=product_id,
            quantity=quantity,
            scanned_by=scanned_by
        )

        # Refresh the combined order to get updated amounts
        from payments.models import CombinedOrder
        from payments.serializers import CombinedOrderLineItemSerializer
        order = CombinedOrder.objects.get(combined_order_id=combined_order_id)
        
        return Response({
            'success': True,
            'line_item': CombinedOrderLineItemSerializer(line_item).data,
            'order_totals': {
                'amount_fulfilled': str(order.amount_fulfilled),
                'remaining_amount': str(order.remaining_amount),
                'total_amount': str(order.total_amount),
                'fulfillment_percentage': float(order.fulfillment_percentage),
                'status': order.status,
            },
            'message': f'Added {quantity}x {line_item.scanned_prod_name} (STAGED)'
        }, status=status.HTTP_201_CREATED)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to scan product to combined order: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def combined_order_complete(request, combined_order_id):
    """
    Complete combined order and update inventory.
    Marks all linked transactions as COMBINED_FULFILLED.

    POST /api/v1/combined-orders/<combined_order_id>/complete/
    Body: {"completed_by": "admin"}
    """
    completed_by = request.data.get('completed_by', 'system')

    try:
        order = CombinedOrderService.complete_combined_order(
            combined_order_id=combined_order_id,
            completed_by=completed_by
        )

        return Response({
            'success': True,
            'combined_order_id': order.combined_order_id,
            'status': order.status,
            'fulfilled_at': order.fulfilled_at,
            'message': f'Combined order completed. {order.transactions.count()} transactions marked as COMBINED_FULFILLED.'
        }, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to complete combined order: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def combined_order_remove_line_item(request, combined_order_id, line_item_id):
    """
    Remove a line item from combined order.

    DELETE /api/v1/combined-orders/<combined_order_id>/line-items/<line_item_id>/
    """
    try:
        CombinedOrderService.remove_combined_order_line_item(
            combined_order_id=combined_order_id,
            line_item_id=line_item_id
        )

        # Refresh the combined order to get updated amounts
        from payments.models import CombinedOrder
        order = CombinedOrder.objects.get(combined_order_id=combined_order_id)

        return Response({
            'success': True,
            'message': 'Line item removed',
            'amount_fulfilled': str(order.amount_fulfilled),
            'remaining_amount': str(order.remaining_amount),
            'status': order.status
        }, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to remove line item: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================================
# Stock Taking Views
# ============================================================================

@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def stock_take_create_session(request):
    """
    Create a new stock take session.

    POST /api/v1/stock-take/sessions/
    Body: {
        "created_by": "admin",
        "notes": "Monthly stock check"
    }
    """
    created_by = request.data.get('created_by', 'system')
    notes = request.data.get('notes', '')

    try:
        session = StockTakeService.create_session(
            created_by=created_by,
            notes=notes
        )

        return Response({
            'success': True,
            'session_id': session.session_id,
            'status': session.status,
            'created_at': session.created_at
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Failed to create stock take session: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication])
def stock_take_session_detail(request, session_id):
    """
    Get stock take session details with all items.

    GET /api/v1/stock-take/sessions/<session_id>/
    """
    try:
        session = StockTakeService.get_session_details(session_id)

        from payments.serializers import StockTakeSessionSerializer
        return Response(StockTakeSessionSerializer(session).data, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Failed to get stock take session: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
@throttle_classes([])  # No throttling for rapid scanning operations
def stock_take_scan_product(request, session_id):
    """
    Scan product to stock take session (staged - inventory not updated yet).

    POST /api/v1/stock-take/sessions/<session_id>/scan/
    Body: {
        "product_id": 1,
        "quantity": 10,
        "scanned_by": "admin"
    }
    """
    product_id = request.data.get('product_id')
    quantity = request.data.get('quantity', 1)
    scanned_by = request.data.get('scanned_by', 'system')

    if not product_id:
        return Response({'error': 'product_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        item = StockTakeService.scan_product(
            session_id=session_id,
            product_id=product_id,
            quantity=quantity,
            scanned_by=scanned_by
        )

        from payments.serializers import StockTakeItemSerializer
        return Response({
            'success': True,
            'item': StockTakeItemSerializer(item).data,
            'message': f'Scanned {quantity}x {item.product.prod_name}'
        }, status=status.HTTP_201_CREATED)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to scan product: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def stock_take_complete_session(request, session_id):
    """
    Complete stock take session and update inventory.

    POST /api/v1/stock-take/sessions/<session_id>/complete/
    Body: {"completed_by": "admin"}
    """
    completed_by = request.data.get('completed_by', 'system')

    try:
        session = StockTakeService.complete_session(
            session_id=session_id,
            completed_by=completed_by
        )

        return Response({
            'success': True,
            'session_id': session.session_id,
            'status': session.status,
            'completed_at': session.completed_at,
            'items_count': session.items.count()
        }, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to complete stock take session: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@authentication_classes([DeviceAPIKeyAuthentication])
def stock_take_remove_item(request, session_id, item_id):
    """
    Remove an item from stock take session.

    DELETE /api/v1/stock-take/sessions/<session_id>/items/<item_id>/
    """
    try:
        StockTakeService.remove_item(
            session_id=session_id,
            item_id=item_id
        )

        return Response({
            'success': True,
            'message': 'Item removed'
        }, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to remove item: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PATCH'])
@authentication_classes([DeviceAPIKeyAuthentication])
@throttle_classes([])  # No throttling for rapid quantity updates
def stock_take_update_item_quantity(request, session_id, item_id):
    """
    Update the quantity of an item in a stock take session.

    PATCH /api/v1/stock-take/sessions/<session_id>/items/<item_id>/

    Body: { "quantity": int }
    """
    try:
        new_quantity = request.data.get('quantity')
        if new_quantity is None:
            return Response({'error': 'quantity is required'}, status=status.HTTP_400_BAD_REQUEST)

        item = StockTakeService.update_item_quantity(
            session_id=session_id,
            item_id=item_id,
            new_quantity=int(new_quantity)
        )

        return Response({
            'success': True,
            'message': 'Quantity updated',
            'item': {
                'id': item.id,
                'quantity_scanned': item.quantity_scanned,
                'quantity_before': item.quantity_before,
                'quantity_after': item.quantity_after,
            }
        }, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except ValueError:
        return Response({'error': 'Invalid quantity value'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to update item quantity: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PATCH'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
@throttle_classes([])
def stock_take_update_kit_quantity(request, session_id):
    """
    Update the registration kit quantity for a stock take session.

    PATCH /api/v1/stock-take/sessions/<session_id>/kit-quantity/
    Body: { "kit_quantity": int }
    """
    try:
        kit_quantity = request.data.get('kit_quantity')
        if kit_quantity is None:
            return Response({'error': 'kit_quantity is required'}, status=status.HTTP_400_BAD_REQUEST)

        session = StockTakeService.update_kit_quantity(
            session_id=session_id,
            kit_quantity=int(kit_quantity)
        )

        return Response({
            'success': True,
            'session_id': session.session_id,
            'kit_quantity': session.kit_quantity,
        }, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except ValueError:
        return Response({'error': 'Invalid kit_quantity value'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to update kit quantity: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def stock_take_list_active_sessions(request):
    """
    List all active (DRAFT) stock take sessions.

    GET /api/v1/stock-take/sessions/active/
    """
    try:
        from payments.models import StockTakeSession
        from payments.serializers import StockTakeSessionSerializer

        active_sessions = StockTakeSession.objects.filter(
            status=StockTakeSession.Status.DRAFT
        ).prefetch_related('items__product').order_by('-created_at')

        serializer = StockTakeSessionSerializer(active_sessions, many=True)

        return Response({
            'success': True,
            'count': active_sessions.count(),
            'sessions': serializer.data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Failed to list active stock take sessions: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def stock_take_cancel_session(request, session_id):
    """
    Cancel a specific stock take session.

    POST /api/v1/stock-take/sessions/<session_id>/cancel/
    Body: {"cancelled_by": "admin"}
    """
    cancelled_by = request.data.get('cancelled_by', 'system')

    try:
        session = StockTakeService.cancel_session(
            session_id=session_id,
            cancelled_by=cancelled_by
        )

        from payments.serializers import StockTakeSessionSerializer

        return Response({
            'success': True,
            'message': f'Stock take session {session_id} cancelled',
            'session': StockTakeSessionSerializer(session).data
        }, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to cancel stock take session: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def stock_take_cancel_all_active(request):
    """
    Cancel all active (DRAFT) stock take sessions.
    Useful for cleanup operations.

    POST /api/v1/stock-take/sessions/cancel-all/
    Body: {"cancelled_by": "admin"}
    """
    cancelled_by = request.data.get('cancelled_by', 'system')

    try:
        from payments.models import StockTakeSession

        active_sessions = StockTakeSession.objects.filter(
            status=StockTakeSession.Status.DRAFT
        )

        count = active_sessions.count()

        if count == 0:
            return Response({
                'success': True,
                'message': 'No active sessions to cancel',
                'count': 0
            }, status=status.HTTP_200_OK)

        # Cancel all active sessions
        cancelled_ids = []
        for session in active_sessions:
            session.status = StockTakeSession.Status.CANCELLED
            session.completed_at = timezone.now()
            session.completed_by = cancelled_by
            session.save()
            cancelled_ids.append(session.session_id)

        return Response({
            'success': True,
            'message': f'Cancelled {count} active session(s)',
            'count': count,
            'cancelled_sessions': cancelled_ids
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Failed to cancel all active stock take sessions: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================================
# Authentication & User Management Views
# ============================================================================

class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Custom token obtain view that returns user info along with tokens.

    POST /api/v1/auth/login/
    Body: {"username": "...", "password": "..."}

    Response:
    {
        "access": "...",
        "refresh": "...",
        "user": {
            "id": 1,
            "username": "admin",
            "email": "admin@example.com",
            "role": "ADMIN",
            "role_display": "Administrator",
            ...
        }
    }
    """
    serializer_class = CustomTokenObtainPairSerializer


class UserProfileView(APIView):
    """
    Get current user's profile.

    GET /api/v1/auth/profile/
    Headers: Authorization: Bearer <access_token>
    """
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class ChangePasswordView(APIView):
    """
    Change current user's password.

    POST /api/v1/auth/change-password/
    Body: {
        "old_password": "current_password",
        "new_password": "new_password",
        "new_password_confirm": "new_password"
    }
    """
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Update password
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save()

        # Blacklist all existing refresh tokens for this user
        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
            tokens = OutstandingToken.objects.filter(user=request.user)
            for token in tokens:
                BlacklistedToken.objects.get_or_create(token=token)
        except Exception as e:
            logger.warning(f"Could not blacklist tokens for user {request.user.username}: {e}")

        return Response({'message': 'Password changed successfully'}, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """
    Logout user by blacklisting their refresh token.

    POST /api/v1/auth/logout/
    Body: {"refresh": "<refresh_token>"}
    """
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
            return Response({'message': 'Logged out successfully'}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.warning(f"Error during logout: {e}")
            return Response({'message': 'Logged out successfully'}, status=status.HTTP_200_OK)


class UserListCreateView(generics.ListCreateAPIView):
    """
    List all users or create a new user (Admin only).

    GET /api/v1/users/
    POST /api/v1/users/
    Body: {
        "username": "newuser",
        "email": "user@example.com",
        "password": "securepassword",
        "password_confirm": "securepassword",
        "first_name": "John",
        "last_name": "Doe",
        "role": "PROCESSOR",
        "is_active": true
    }
    """
    permission_classes = [IsAdmin]
    queryset = User.objects.all().order_by('-date_joined')
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['username', 'email', 'first_name', 'last_name']
    ordering_fields = ['username', 'date_joined', 'role']
    ordering = ['-date_joined']

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return UserCreateSerializer
        return UserSerializer


class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a user (Admin only).

    GET /api/v1/users/<id>/
    PUT/PATCH /api/v1/users/<id>/
    DELETE /api/v1/users/<id>/
    """
    permission_classes = [IsAdmin]
    queryset = User.objects.all()

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return UserUpdateSerializer
        return UserSerializer

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()

        # Prevent deleting self
        if user.id == request.user.id:
            return Response(
                {'error': 'Cannot delete your own account'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Soft delete - just deactivate
        user.is_active = False
        user.save()

        return Response({'message': 'User deactivated successfully'}, status=status.HTTP_200_OK)


class AdminPasswordResetView(APIView):
    """
    Admin resets another user's password.

    POST /api/v1/users/<id>/reset-password/
    Body: {
        "new_password": "newpassword",
        "new_password_confirm": "newpassword"
    }
    """
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = AdminPasswordResetSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(serializer.validated_data['new_password'])
        user.save()

        # Blacklist all existing refresh tokens for this user
        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
            tokens = OutstandingToken.objects.filter(user=user)
            for token in tokens:
                BlacklistedToken.objects.get_or_create(token=token)
        except Exception as e:
            logger.warning(f"Could not blacklist tokens for user {user.username}: {e}")

        return Response({'message': f'Password reset for user {user.username}'}, status=status.HTTP_200_OK)


# ============================================================================
# Issuer Queue View (Role-Based)
# ============================================================================

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def issuer_queue(request):
    """
    Get transactions activated for issuance (Issuer's queue).

    Returns transactions that are:
    - In issuance mode (is_in_issuance=True)
    - Status is PROCESSING or PARTIALLY_FULFILLED (Active work)
    - Status is COMBINED_FULFILLED (Child transactions) IF the parent combined order is active

    Ordered by most recently updated first.

    GET /api/v1/issuer/queue/
    """
    active_statuses = [
        Transaction.OrderStatus.PROCESSING,
        Transaction.OrderStatus.PARTIALLY_FULFILLED
    ]

    queue = Transaction.objects.filter(
        # 1. Active issuing transactions
        Q(is_in_issuance=True) |
        # 2. Processing or Partially Fulfilled (Processor queued)
        Q(status__in=active_statuses) |
        # 3. Child transactions of ACTIVE combined orders
        # (Where child is COMBINED_FULFILLED but parent is PROCESSING/PARTIALLY)
        Q(
            status=Transaction.OrderStatus.COMBINED_FULFILLED,
            combined_orders__combined_order__parent_transaction__status__in=active_statuses
        )
    ).distinct().order_by('-updated_at')

    serializer = TransactionSerializer(queue, many=True)
    return Response({
        'count': queue.count(),
        'queue': serializer.data
    })


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def issuer_queue_pending(request):
    """
    Get transactions that have been activated for issuance but not yet started.

    These are transactions where:
    - Status is NOT_PROCESSED (payment received, ready to be issued)
    - Not currently in issuance mode

    This is the "waiting room" for issuers.

    GET /api/v1/issuer/queue/pending/
    """
    # Get transactions activated for issuance (marked by Processor)
    # that haven't started issuance yet
    pending = Transaction.objects.filter(
        status=Transaction.OrderStatus.NOT_PROCESSED,
        is_in_issuance=False
    ).exclude(
        # Exclude manual payments without M-Pesa transactions
        gateway_type__in=['MANUAL_CASH', 'MANUAL_BANK_TRANSFER', 'MANUAL_CHEQUE', 'MANUAL_OTHER']
    ).order_by('-timestamp')

    serializer = TransactionSerializer(pending, many=True)
    return Response({
        'count': pending.count(),
        'pending': serializer.data
    })


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def issuer_stats(request):
    """
    Get fulfillment statistics for issuers.

    Returns count and total amount of transactions fulfilled today
    (Africa/Nairobi timezone). Counts FULFILLED transactions only —
    combined order parent transactions (CMB-*) count as one order each,
    so there is no double-counting of child COMBINED_FULFILLED transactions.

    GET /api/v1/issuer/stats/
    """
    from django.db.models import Sum, Count
    from datetime import datetime, timedelta
    from decimal import Decimal

    tz = timezone.get_current_timezone()
    today = timezone.localtime(timezone.now(), tz).date()
    today_start = timezone.make_aware(datetime.combine(today, datetime.min.time()), tz)
    today_end = today_start + timedelta(days=1)

    result = Transaction.objects.filter(
        status=Transaction.OrderStatus.FULFILLED,
        updated_at__gte=today_start,
        updated_at__lt=today_end,
    ).aggregate(
        count=Count('id'),
        total_amount=Sum('amount_fulfilled'),
    )

    return Response({
        'fulfilled_today': result['count'] or 0,
        'amount_fulfilled_today': str(result['total_amount'] or Decimal('0')),
    })


# ============================================================================
# Admin-Only Operations
# ============================================================================

@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
def cancel_fulfilled_transaction(request, transaction_id):
    """
    Cancel a fulfilled transaction and return inventory (Admin only).

    This reverses a completed fulfillment by returning all products to inventory
    and creating reverse InventoryMovement records for audit trail.

    Only FULFILLED transactions can be cancelled. This operation requires
    administrator privileges.

    Request body:
    {
        "reason": "Customer refund"  // Required: explanation for cancellation
    }

    Returns:
    {
        "success": true,
        "tx_id": "TXID123",
        "status": "CANCELLED",
        "reversed_items_count": 3,
        "inventory_updates": [...]
    }
    """
    from payments.serializers import CancelFulfilledSerializer
    from payments.services.admin_service import AdminService
    from django.core.exceptions import ValidationError

    serializer = CancelFulfilledSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        result = AdminService.cancel_fulfilled_transaction(
            transaction_id=transaction_id,
            cancelled_by_user=request.user,
            reason=serializer.validated_data['reason']
        )
        return Response(result, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response({'error': e.message_dict}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error cancelling fulfilled transaction {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
def cancel_registration_order(request, transaction_id):
    """
    Cancel a registration order and return both kit and products to inventory (Admin only).

    This cancels a registration transaction by:
    - Returning all scanned products to inventory
    - Returning registration kit(s) to inventory
    - Resetting transaction to NOT_PROCESSED
    - Creating reverse InventoryMovement records for audit trail

    Only registration transactions with issued kits can be cancelled this way.

    Request body:
    {
        "reason": "Cancelled registration - customer refund"  // Required
    }

    Returns:
    {
        "success": true,
        "tx_id": "TXID123",
        "status": "NOT_PROCESSED",
        "reversed_items_count": 5,
        "inventory_updates": [...]
    }
    """
    from payments.serializers import CancelFulfilledSerializer
    from payments.services.admin_service import AdminService
    from django.core.exceptions import ValidationError

    serializer = CancelFulfilledSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        result = AdminService.cancel_registration_order(
            transaction_id=transaction_id,
            cancelled_by_user=request.user,
            reason=serializer.validated_data['reason']
        )
        return Response(result, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response({'error': e.message_dict}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error cancelling registration order {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
def delete_transaction(request, transaction_id):
    """
    Permanently delete a transaction (Admin only, use with extreme caution).

    This is a destructive operation that completely removes a transaction.
    Should only be used for duplicate, test, or erroneous transactions.

    Only NOT_PROCESSED transactions without line items can be deleted.

    Request body:
    {
        "reason": "Duplicate transaction - test data"  // Required
    }

    Returns:
    {
        "success": true,
        "tx_id": "TXID123",
        "deleted_by": "admin",
        "message": "Transaction permanently deleted."
    }
    """
    from payments.serializers import CancelFulfilledSerializer
    from payments.services.admin_service import AdminService
    from django.core.exceptions import ValidationError

    serializer = CancelFulfilledSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        result = AdminService.delete_transaction(
            transaction_id=transaction_id,
            deleted_by_user=request.user,
            reason=serializer.validated_data['reason']
        )
        return Response(result, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response({'error': e.message_dict}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error deleting transaction {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def mark_transaction_as_registration(request, transaction_id):
    """
    Mark a transaction as registration (Processor/Admin).

    Registration transactions receive special handling during fulfillment:
    - No product scanning required
    - Automatically issues one "Registration Kit" product
    - Completes immediately after activation

    Only NOT_PROCESSED or PROCESSING transactions can be marked as registration.

    Request body:
    {
        "notes": "New member registration"  // Optional notes
    }

    Returns:
    {
        "success": true,
        "tx_id": "TXID123",
        "is_registration": true,
        "message": "Transaction marked as registration"
    }
    """
    from payments.serializers import MarkRegistrationSerializer
    from django.db import transaction as db_transaction
    from django.core.exceptions import ValidationError

    serializer = MarkRegistrationSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        with db_transaction.atomic():
            transaction = Transaction.objects.select_for_update().get(id=transaction_id)

            # Validate transaction is not locked
            if transaction.is_locked:
                return Response(
                    {'error': f'Transaction {transaction.tx_id} is locked and cannot be modified'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate status
            if transaction.status not in [
                Transaction.OrderStatus.NOT_PROCESSED,
                Transaction.OrderStatus.PROCESSING
            ]:
                return Response(
                    {'error': f'Can only mark NOT_PROCESSED or PROCESSING transactions as registration. Current: {transaction.status}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Mark as registration
            transaction.is_registration = True

            # Add registration note
            reg_note = (
                f"\n[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"REGISTRATION by {request.user.username}"
            )
            if serializer.validated_data.get('notes'):
                reg_note += f": {serializer.validated_data['notes']}"

            transaction.notes = (
                f"{transaction.notes}{reg_note}" if transaction.notes else reg_note
            )
            transaction.save()

            logger.info(f"Transaction {transaction.tx_id} marked as registration by {request.user.username}")

            return Response({
                'success': True,
                'transaction_id': transaction.id,
                'tx_id': transaction.tx_id,
                'is_registration': True,
                'message': f'Transaction {transaction.tx_id} marked as registration'
            }, status=status.HTTP_200_OK)

    except Transaction.DoesNotExist:
        return Response({'error': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error marking transaction {transaction_id} as registration: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def unmark_transaction_as_registration(request, transaction_id):
    """
    Remove the registration flag from a transaction before kit issuance (Processor/Admin).

    Safety checks (mirrors the unmark_registration management command):
    - Transaction must be marked as registration
    - Registration kit must NOT have been issued yet
    - Transaction must not be part of a combined order (child)
    - No inventory-deducted line items

    Resets transaction to NOT_PROCESSED and clears all issuance state.

    POST /api/v1/transactions/<id>/unmark-registration/
    """
    from django.db import transaction as db_transaction
    from decimal import Decimal

    try:
        with db_transaction.atomic():
            txn = Transaction.objects.select_for_update().get(id=transaction_id)

            if not txn.is_registration:
                return Response(
                    {'error': 'Transaction is not marked as registration.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if txn.registration_kit_issued:
                return Response(
                    {'error': 'Registration kit has already been issued. Use "Cancel Registration" to fully reverse it.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if txn.combined_orders.exists():
                return Response(
                    {'error': 'Transaction is part of a combined order. Unmark via the combined order instead.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if txn.line_items.filter(is_inventory_deducted=True).exists():
                return Response(
                    {'error': 'Transaction has deducted inventory items. Use "Cancel Registration" to fully reverse it.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            txn.is_registration = False
            txn.status = Transaction.OrderStatus.NOT_PROCESSED
            txn.amount_fulfilled = Decimal('0.00')
            txn.amount_paid = Decimal('0.00')
            txn.is_in_issuance = False
            txn.activated_by = None
            txn.activated_at = None
            txn.completed_by = None
            txn.completed_at = None
            txn.processed_by = None
            txn.processed_at = None
            txn.status_before_activation = None
            txn.amount_fulfilled_before_activation = None

            timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            note = (
                f'\n[{timestamp}] Registration flag removed by {request.user.username}. '
                f'Reverted to NOT_PROCESSED.'
            )
            txn.notes = (txn.notes or '') + note

            txn.save(skip_validation=True)

            logger.info(f"Transaction {txn.tx_id} unmarked as registration by {request.user.username}")

            return Response({
                'success': True,
                'tx_id': txn.tx_id,
                'is_registration': False,
                'status': txn.status,
                'message': f'Transaction {txn.tx_id} is no longer a registration order.',
            }, status=status.HTTP_200_OK)

    except Transaction.DoesNotExist:
        return Response({'error': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error unmarking transaction {transaction_id} as registration: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def mark_combined_order_as_registration(request, combined_order_id):
    """
    Mark a combined order as a registration order (Processor/Admin).

    Sets is_registration=True on the combined order's parent transaction so that
    kit counts in reconciliation work the same way as single registration transactions.

    Only PENDING, IN_PROGRESS, or PARTIALLY_FULFILLED orders can be marked.

    Request body:
    {
        "notes": "New member registration"  // Optional
    }
    """
    from payments.serializers import MarkRegistrationSerializer
    from django.db import transaction as db_transaction

    serializer = MarkRegistrationSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        with db_transaction.atomic():
            combined_order = CombinedOrder.objects.select_related(
                'parent_transaction'
            ).get(combined_order_id=combined_order_id)

            allowed_statuses = [
                CombinedOrder.Status.PENDING,
                CombinedOrder.Status.IN_PROGRESS,
                CombinedOrder.Status.PARTIALLY_FULFILLED,
            ]
            if combined_order.status not in allowed_statuses:
                return Response(
                    {'error': f'Cannot mark a {combined_order.get_status_display()} combined order as registration.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            parent = combined_order.parent_transaction
            if not parent:
                return Response(
                    {'error': 'Combined order has no parent transaction.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            parent.is_registration = True

            reg_note = (
                f"\n[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"REGISTRATION by {request.user.username}"
            )
            if serializer.validated_data.get('notes'):
                reg_note += f": {serializer.validated_data['notes']}"

            parent.notes = f"{parent.notes}{reg_note}" if parent.notes else reg_note
            parent.save(update_fields=['is_registration', 'notes', 'updated_at'])

            logger.info(
                f"Combined order {combined_order_id} marked as registration "
                f"by {request.user.username} (parent tx: {parent.tx_id})"
            )

            return Response({
                'success': True,
                'combined_order_id': combined_order_id,
                'parent_tx_id': parent.tx_id,
                'is_registration': True,
                'message': f'Combined order {combined_order_id} marked as registration',
            }, status=status.HTTP_200_OK)

    except CombinedOrder.DoesNotExist:
        return Response({'error': 'Combined order not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error marking combined order {combined_order_id} as registration: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def revert_to_not_processed(request, transaction_id):
    """
    Revert a PROCESSING transaction back to NOT_PROCESSED status.

    Use this when a transaction was accidentally activated for processing
    or needs to be returned to the unprocessed queue.

    Validation:
    - Transaction must be PROCESSING
    - Cannot be in issuance mode (is_in_issuance=False)
    - Cannot be in a combined order
    - Must not have any line items

    Request body:
    {
        "reason": "Accidentally activated"  // Optional reason for audit
    }
    """
    from payments.models import Transaction
    from django.core.exceptions import ValidationError
    from django.utils import timezone

    try:
        transaction = Transaction.objects.get(id=transaction_id)

        # Validation: Must be PROCESSING
        if transaction.status != Transaction.OrderStatus.PROCESSING:
            return Response(
                {'error': f'Transaction must be PROCESSING. Current status: {transaction.get_status_display()}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validation: Cannot be in issuance mode
        if transaction.is_in_issuance:
            return Response(
                {'error': 'Cannot revert transaction while it is in issuance mode. Cancel issuance first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validation: Cannot be in combined order
        if transaction.combined_orders.exists():
            return Response(
                {'error': 'Cannot revert transactions that are part of a combined order'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validation: Must not have line items (indicates fulfillment started)
        if transaction.line_items.exists():
            return Response(
                {'error': 'Cannot revert transaction with line items. Use cancel issuance instead.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get reason from request
        reason = request.data.get('reason', 'Reverted to not processed')

        # Append note with reason
        timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        revert_note = f"\n[{timestamp}] Reverted to NOT_PROCESSED by {request.user.username}: {reason}"
        new_notes = (transaction.notes or '') + revert_note

        # Use update() to bypass model validation that blocks PROCESSING -> NOT_PROCESSED
        Transaction.objects.filter(pk=transaction.pk).update(
            status=Transaction.OrderStatus.NOT_PROCESSED,
            processed_by=None,
            processed_at=None,
            notes=new_notes
        )
        transaction.refresh_from_db()

        logger.info(f"Transaction {transaction.tx_id} reverted to NOT_PROCESSED by {request.user.username}")

        return Response({
            'success': True,
            'message': 'Transaction reverted to NOT_PROCESSED',
            'transaction': TransactionSerializer(transaction).data
        }, status=status.HTTP_200_OK)

    except Transaction.DoesNotExist:
        return Response(
            {'error': 'Transaction not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Error reverting transaction {transaction_id} to not processed: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def issue_registration_from_partial(request, transaction_id):
    """
    Issue registration kit from a PARTIALLY_FULFILLED transaction's remaining balance.

    Use case:
    - User partially fulfills an order with some products
    - User has remaining balance (e.g., Ksh 5000 paid, Ksh 2100 fulfilled, Ksh 2900 remaining)
    - User comes back and wants to use the remaining balance for registration

    Flow:
    1. Validates transaction is PARTIALLY_FULFILLED with sufficient balance for registration
    2. Marks transaction as registration (is_registration=True)
    3. Issues Registration Kit (2900) from the balance
    4. If balance remaining after kit: PARTIALLY_FULFILLED
    5. If no balance remaining: FULFILLED

    Request body:
    {
        "quantity": 1,  // Optional, defaults to 1
        "notes": "Customer requested registration"  // Optional
    }
    """
    from payments.models import Transaction, Product, TransactionLineItem, InventoryMovement
    from payments.serializers import TransactionSerializer
    from django.db import transaction as db_transaction
    from django.core.exceptions import ValidationError
    from decimal import Decimal

    try:
        quantity = int(request.data.get('quantity', 1))
        notes = request.data.get('notes', '')

        if quantity < 1:
            return Response(
                {'error': 'Quantity must be at least 1'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with db_transaction.atomic():
            txn = Transaction.objects.select_for_update().get(id=transaction_id)

            # Validation: Must be PARTIALLY_FULFILLED
            if txn.status != Transaction.OrderStatus.PARTIALLY_FULFILLED:
                return Response(
                    {'error': f'Transaction must be PARTIALLY_FULFILLED. Current: {txn.get_status_display()}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validation: Cannot be locked
            if txn.is_locked:
                return Response(
                    {'error': f'Transaction {txn.tx_id} is locked and cannot be modified'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Get Registration Kit product
            try:
                reg_kit = Product.objects.select_for_update().get(prod_code='REG_KIT_001')
            except Product.DoesNotExist:
                return Response(
                    {'error': 'Registration Kit product not found (prod_code=REG_KIT_001).'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            kit_total_cost = reg_kit.current_price * quantity
            remaining_balance = txn.amount - txn.amount_fulfilled

            # Validation: Sufficient balance for registration kit
            if remaining_balance < kit_total_cost:
                return Response({
                    'error': f'Insufficient balance for registration. '
                             f'Balance: {remaining_balance}, Kit cost: {kit_total_cost}'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Validation: Check stock
            if reg_kit.quantity < quantity:
                return Response({
                    'error': f'Insufficient registration kits in stock. '
                             f'Available: {reg_kit.quantity}, Requested: {quantity}'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Mark as registration
            txn.is_registration = True

            # Create line item for registration kit
            line_item = TransactionLineItem.objects.create(
                transaction=txn,
                product=reg_kit,
                scanned_prod_code=reg_kit.prod_code,
                scanned_prod_name=reg_kit.prod_name,
                scanned_sku=reg_kit.sku,
                scanned_sku_name=reg_kit.sku_name,
                scanned_price=reg_kit.current_price,
                scanned_pv=reg_kit.current_pv,
                quantity=quantity,
                scanned_by=request.user.username,
                scanned_by_user=request.user,
                is_inventory_deducted=True
            )

            # Update inventory
            quantity_before = reg_kit.quantity
            reg_kit.quantity -= quantity
            quantity_after = reg_kit.quantity
            reg_kit.save()

            # Create inventory movement record
            InventoryMovement.objects.create(
                movement_type=InventoryMovement.MovementType.SALE,
                product=reg_kit,
                quantity_before=quantity_before,
                quantity_after=quantity_after,
                quantity_change=-quantity,
                reference=f'Registration from partial {txn.tx_id}',
                performed_by=request.user.username,
                performed_by_user=request.user
            )

            # Update transaction - recalculate amount_fulfilled from all line items
            # (Don't manually add kit_total_cost as the line item already represents it)
            all_line_items_total = sum(item.line_total for item in txn.line_items.all())
            txn.amount_fulfilled = all_line_items_total
            txn.amount_paid = txn.amount_fulfilled  # Keep in sync for backwards compatibility
            txn.registration_kit_issued = True
            txn.registration_kit_quantity = quantity
            txn.registration_kit_amount_deducted = kit_total_cost

            # Also add to total_cost
            txn.total_cost = (txn.total_cost or Decimal('0.00')) + (reg_kit.current_price * quantity)
            txn.total_pv = (txn.total_pv or Decimal('0.00')) + (reg_kit.current_pv * quantity)

            # Determine final status based on recalculated amount_fulfilled
            if txn.amount_fulfilled >= txn.amount:
                txn.status = Transaction.OrderStatus.FULFILLED
                txn.completed_by = request.user
                txn.completed_at = timezone.now()
            # Otherwise remains PARTIALLY_FULFILLED

            # Add notes
            timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            reg_note = (
                f"\n[{timestamp}] REGISTRATION from partial by {request.user.username}. "
                f"{quantity}x {reg_kit.prod_name} @ {reg_kit.current_price} = {kit_total_cost}"
            )
            if notes:
                reg_note += f": {notes}"
            txn.notes = (txn.notes or '') + reg_note

            txn.save()

            new_balance = txn.amount - txn.amount_fulfilled

            logger.info(
                f"Registration kit issued from partial {txn.tx_id} by {request.user.username}. "
                f"Kit: {quantity}x{reg_kit.current_price}={kit_total_cost}, "
                f"New balance: {new_balance}, Status: {txn.status}"
            )

            return Response({
                'success': True,
                'transaction_id': txn.id,
                'tx_id': txn.tx_id,
                'status': txn.status,
                'is_registration': True,
                'kit_issued': {
                    'product_code': reg_kit.prod_code,
                    'product_name': reg_kit.prod_name,
                    'quantity': quantity,
                    'unit_price': str(reg_kit.current_price),
                    'total_cost': str(kit_total_cost),
                    'new_stock': quantity_after
                },
                'amount_paid': str(txn.amount),
                'amount_fulfilled': str(txn.amount_fulfilled),
                'remaining_balance': str(new_balance),
                'message': f'Registration kit issued. {quantity}x {reg_kit.prod_name} @ {reg_kit.current_price}. '
                          f'New balance: {new_balance}. Status: {txn.get_status_display()}'
            }, status=status.HTTP_200_OK)

    except Transaction.DoesNotExist:
        return Response({'error': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error issuing registration from partial {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================================
# Stock Reconciliation API Endpoints
# ============================================================================

@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def eod_value_reconciliation_today(request):
    """
    Get today's end-of-day value reconciliation (X - Y - Z).

    Scope note:
    - This resolves at main-shop level only (field locations are ignored).
    - Only today's record is editable.
    """
    from payments.serializers import EndOfDayValueReconciliationSerializer
    from payments.services.eod_value_reconciliation_service import EndOfDayValueReconciliationService

    try:
        reconciliation = EndOfDayValueReconciliationService.get_or_create_today(request.user)
        serializer = EndOfDayValueReconciliationSerializer(reconciliation)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error fetching EOD value reconciliation: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PATCH'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def eod_value_reconciliation_update_today(request):
    """
    Update today's editable Y/Z inputs for value reconciliation.
    """
    from payments.serializers import EndOfDayValueReconciliationSerializer
    from payments.services.eod_value_reconciliation_service import EndOfDayValueReconciliationService

    try:
        reconciliation = EndOfDayValueReconciliationService.update_today_inputs(request.user, request.data or {})
        serializer = EndOfDayValueReconciliationSerializer(reconciliation)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error updating EOD value reconciliation: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def eod_value_reconciliation_confirm_today(request):
    """
    Confirm today's value reconciliation and lock it.
    """
    from payments.serializers import EndOfDayValueReconciliationSerializer
    from payments.services.eod_value_reconciliation_service import EndOfDayValueReconciliationService

    try:
        reconciliation = EndOfDayValueReconciliationService.confirm_today(request.user)
        serializer = EndOfDayValueReconciliationSerializer(reconciliation)
        return Response(
            {
                'success': True,
                'message': 'End-of-day value reconciliation confirmed',
                'reconciliation': serializer.data,
            },
            status=status.HTTP_200_OK,
        )
    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error confirming EOD value reconciliation: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def create_stock_reconciliation(request):
    """
    Create or get existing draft stock reconciliation for a specific date.

    POST /api/v1/stock-reconciliation/create/
    Body: {
        "reconciliation_date": "2026-01-12"  // defaults to today
    }

    Returns: reconciliation object with adjustments for all products
    """
    from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService
    from payments.serializers import DailyStockReconciliationSerializer
    from datetime import date

    try:
        reconciliation_date_str = request.data.get('reconciliation_date')
        if reconciliation_date_str:
            from datetime import datetime
            reconciliation_date = datetime.strptime(reconciliation_date_str, '%Y-%m-%d').date()
        else:
            reconciliation_date = date.today()

        # Check if can create
        can_create, reason = ReconciliationWorkflowService.can_create_reconciliation(reconciliation_date)
        if not can_create:
            return Response({'error': reason}, status=status.HTTP_400_BAD_REQUEST)

        # Get or create reconciliation
        reconciliation = ReconciliationWorkflowService.get_or_create_reconciliation(
            reconciliation_date=reconciliation_date,
            created_by=request.user
        )

        serializer = DailyStockReconciliationSerializer(reconciliation)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error creating stock reconciliation: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PATCH'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def update_stock_adjustment(request, reconciliation_id):
    """
    Update adjustment for a specific product in the reconciliation.

    PATCH /api/v1/stock-reconciliation/{reconciliation_id}/adjust/
    Body: {
        "product_id": 1,
        "quantity_added": 50,
        "quantity_deducted": 10,
        "notes": "Shipment received, 10 damaged"
    }

    Returns: updated adjustment item
    """
    from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService
    from payments.serializers import StockAdjustmentItemUpdateSerializer, StockAdjustmentItemSerializer

    try:
        serializer = StockAdjustmentItemUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Note: quantity_replenished is auto-calculated from stock take sessions
        # and is not included in the update payload
        adjustment = ReconciliationWorkflowService.update_adjustment(
            reconciliation_id=reconciliation_id,
            product_id=serializer.validated_data['product_id'],
            quantity_added=serializer.validated_data['quantity_added'],
            quantity_deducted=serializer.validated_data['quantity_deducted'],
            notes=serializer.validated_data.get('notes', '')
        )

        result_serializer = StockAdjustmentItemSerializer(adjustment)
        return Response(result_serializer.data, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error updating stock adjustment: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def confirm_stock_reconciliation(request, reconciliation_id):
    """
    Confirm the reconciliation and apply all adjustments to inventory.

    POST /api/v1/stock-reconciliation/{reconciliation_id}/confirm/

    This:
    - Updates product quantities
    - Creates InventoryMovement records
    - Locks the reconciliation (no further edits)
    - Enables export

    Returns: confirmed reconciliation object
    """
    from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService
    from payments.serializers import DailyStockReconciliationSerializer

    try:
        reconciliation = ReconciliationWorkflowService.confirm_reconciliation(
            reconciliation_id=reconciliation_id,
            confirmed_by=request.user
        )

        serializer = DailyStockReconciliationSerializer(reconciliation)
        return Response({
            'success': True,
            'message': f'Reconciliation for {reconciliation.reconciliation_date} confirmed',
            'reconciliation': serializer.data
        }, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error confirming stock reconciliation: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def cancel_stock_reconciliation(request, reconciliation_id):
    """
    Cancel (delete) a draft stock reconciliation.

    DELETE /api/v1/stock-reconciliation/{reconciliation_id}/cancel/

    Only works for DRAFT reconciliations. CONFIRMED reconciliations cannot be cancelled.
    """
    from payments.models import DailyStockReconciliation
    from payments.serializers import DailyStockReconciliationSerializer

    try:
        reconciliation = DailyStockReconciliation.objects.get(id=reconciliation_id)

        # Only allow cancelling DRAFT reconciliations
        if reconciliation.status == DailyStockReconciliation.Status.CONFIRMED:
            return Response(
                {'error': 'Cannot cancel a confirmed reconciliation'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Delete the reconciliation (cascade deletes all adjustments)
        reconciliation_date = reconciliation.reconciliation_date
        reconciliation.delete()

        return Response({
            'success': True,
            'message': f'Draft reconciliation for {reconciliation_date} has been cancelled'
        }, status=status.HTTP_200_OK)

    except DailyStockReconciliation.DoesNotExist:
        return Response({'error': 'Reconciliation not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error cancelling stock reconciliation: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def get_stock_reconciliation(request, reconciliation_id):
    """
    Get reconciliation details with all adjustments.

    GET /api/v1/stock-reconciliation/{reconciliation_id}/

    Note: For DRAFT reconciliations, this also refreshes:
    - quantity_replenished: from completed stock take sessions (read-only)
    - closing_stock: from current product.quantity

    Returns: reconciliation object with adjustments
    """
    from payments.serializers import DailyStockReconciliationSerializer
    from payments.models import DailyStockReconciliation, StockAdjustmentItem

    try:
        reconciliation = DailyStockReconciliation.objects.prefetch_related(
            'adjustments__product'
        ).get(id=reconciliation_id)

        # For DRAFT reconciliations, refresh replenished and closing_stock values
        # (in case stock takes were completed after reconciliation was created)
        if not reconciliation.is_confirmed():
            for adjustment in reconciliation.adjustments.all():
                # Refresh replenished from stock takes
                new_replenished = StockAdjustmentItem.calculate_replenished_from_stock_takes(
                    adjustment.product_id,
                    reconciliation.reconciliation_date
                )
                # Refresh closing stock via calculation
                from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService
                new_closing = ReconciliationWorkflowService._get_closing_stock(adjustment)

                # Only update if values changed
                if adjustment.quantity_replenished != new_replenished or adjustment.closing_stock != new_closing:
                    adjustment.quantity_replenished = new_replenished
                    adjustment.closing_stock = new_closing

                    adjustment.save()

        serializer = DailyStockReconciliationSerializer(reconciliation)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except DailyStockReconciliation.DoesNotExist:
        return Response({'error': 'Reconciliation not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error getting stock reconciliation: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def get_stock_reconciliation_by_date(request):
    """
    Get reconciliation for a specific date.

    GET /api/v1/stock-reconciliation/by-date/?date=2026-01-12

    Note: For DRAFT reconciliations, this also refreshes:
    - quantity_replenished: from completed stock take sessions (read-only)
    - closing_stock: from current product.quantity

    Returns: reconciliation object or null if not found
    """
    from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService
    from payments.serializers import DailyStockReconciliationSerializer
    from payments.models import StockAdjustmentItem
    from datetime import datetime

    try:
        date_str = request.query_params.get('date')
        if not date_str:
            return Response({'error': 'date parameter required'}, status=status.HTTP_400_BAD_REQUEST)

        reconciliation_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        reconciliation = ReconciliationWorkflowService.get_reconciliation_by_date(reconciliation_date)

        if reconciliation:
            # For DRAFT reconciliations, refresh replenished and closing_stock values
            if not reconciliation.is_confirmed():
                for adjustment in reconciliation.adjustments.all():
                    # Refresh replenished from stock takes
                    new_replenished = StockAdjustmentItem.calculate_replenished_from_stock_takes(
                        adjustment.product_id,
                        reconciliation.reconciliation_date
                    )
                    # Refresh closing stock via calculation
                    new_closing = ReconciliationWorkflowService._get_closing_stock(adjustment)

                    # Only update if values changed
                    if adjustment.quantity_replenished != new_replenished or adjustment.closing_stock != new_closing:
                        adjustment.quantity_replenished = new_replenished
                        adjustment.closing_stock = new_closing
                        adjustment.save()

            serializer = DailyStockReconciliationSerializer(reconciliation)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response({'message': 'No reconciliation found for this date'}, status=status.HTTP_404_NOT_FOUND)

    except ValueError:
        return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error getting stock reconciliation by date: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def stock_report_with_adjustments_xlsx(request):
    """
    Generate and download stock report with adjustments as XLSX.

    GET /api/v1/reports/stock/with-adjustments/xlsx/?date=2026-01-12

    If no date provided, uses today's date.

    Returns: XLSX file with Added/Deducted columns
    """
    from payments.services.stock_report_service import StockReportService
    from datetime import datetime, date

    try:
        date_str = request.query_params.get('date')
        if date_str:
            report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            report_date = date.today()

        xlsx_buffer, filename = StockReportService.generate_stock_report_xlsx_with_adjustments(report_date)

        # Create HTTP response with XLSX
        response = HttpResponse(
            xlsx_buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except ValueError:
        return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error generating stock report XLSX with adjustments: {e}")
        return Response(
            {'error': f'Failed to generate stock report: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ============================================================================
# Opening Stock Baseline Endpoints (for initial setup)
# ============================================================================

@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdmin])
def set_opening_stock_baseline(request, reconciliation_id):
    """
    Set baseline opening stock for a single product.

    POST /api/v1/stock-reconciliation/{reconciliation_id}/set-baseline/

    Use this for initial setup when previous reconciliation data is incorrect.
    The baseline overrides the calculated opening stock from previous day.

    Body: {
        "product_id": 1,
        "opening_stock_baseline": 100
    }

    Returns: updated adjustment item
    """
    from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService
    from payments.serializers import OpeningStockBaselineSerializer, StockAdjustmentItemSerializer

    try:
        serializer = OpeningStockBaselineSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        adjustment = ReconciliationWorkflowService.set_opening_stock_baseline(
            reconciliation_id=reconciliation_id,
            product_id=serializer.validated_data['product_id'],
            baseline_value=serializer.validated_data['opening_stock_baseline']
        )

        result_serializer = StockAdjustmentItemSerializer(adjustment)
        return Response(result_serializer.data, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error setting opening stock baseline: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdmin])
def set_bulk_opening_stock_baseline(request, reconciliation_id):
    """
    Set baseline opening stock for multiple products at once.

    POST /api/v1/stock-reconciliation/{reconciliation_id}/set-baseline-bulk/

    Use this for initial system setup to set real opening stock values for
    all products, ignoring previous placeholder reconciliation data.

    Body Option 1 - Use current inventory as baseline (recommended for initial setup):
    {
        "use_current_inventory": true
    }

    Body Option 2 - Set specific baselines:
    {
        "baselines": [
            {"product_id": 1, "opening_stock_baseline": 100},
            {"product_id": 2, "opening_stock_baseline": 50}
        ]
    }

    Returns: {"count": number of products updated, "message": "..."}
    """
    from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService
    from payments.serializers import BulkOpeningStockBaselineSerializer

    try:
        serializer = BulkOpeningStockBaselineSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        count = ReconciliationWorkflowService.set_bulk_opening_stock_baseline(
            reconciliation_id=reconciliation_id,
            use_current_inventory=serializer.validated_data.get('use_current_inventory', False),
            baselines=serializer.validated_data.get('baselines', [])
        )

        return Response({
            'count': count,
            'message': f'Set baseline opening stock for {count} products'
        }, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error setting bulk opening stock baseline: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdmin])
def clear_opening_stock_baseline(request, reconciliation_id):
    """
    Clear baseline opening stock, reverting to calculated value.

    POST /api/v1/stock-reconciliation/{reconciliation_id}/clear-baseline/

    Body (optional - if omitted, clears ALL baselines):
    {
        "product_id": 1
    }

    Returns: {"count": number of baselines cleared, "message": "..."}
    """
    from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService

    try:
        product_id = request.data.get('product_id')

        count = ReconciliationWorkflowService.clear_opening_stock_baseline(
            reconciliation_id=reconciliation_id,
            product_id=product_id
        )

        return Response({
            'count': count,
            'message': f'Cleared baseline for {count} products'
        }, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error clearing opening stock baseline: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def bulk_update_stock_adjustments(request, reconciliation_id):
    """
    Update multiple adjustments in a single request.

    POST /api/v1/stock-reconciliation/{reconciliation_id}/adjust-bulk/
    Body: {
        "adjustments": [
            {"product_id": 1, "quantity_added": 5, "quantity_deducted": 0, "notes": "Found 5 more"},
            {"product_id": 2, "quantity_added": 0, "quantity_deducted": 2, "notes": "Damaged"}
        ]
    }

    Returns: updated reconciliation with all adjustments
    """
    from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService
    from payments.serializers import DailyStockReconciliationSerializer
    from payments.models import DailyStockReconciliation

    try:
        adjustments_data = request.data.get('adjustments', [])
        if not adjustments_data:
            return Response({'error': 'No adjustments provided'}, status=status.HTTP_400_BAD_REQUEST)

        # Get reconciliation
        try:
            reconciliation = DailyStockReconciliation.objects.get(id=reconciliation_id)
        except DailyStockReconciliation.DoesNotExist:
            return Response({'error': 'Reconciliation not found'}, status=status.HTTP_404_NOT_FOUND)

        # Check if confirmed
        if reconciliation.is_confirmed():
            return Response(
                {'error': 'Cannot modify a confirmed reconciliation'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update each adjustment
        updated_count = 0
        for adj_data in adjustments_data:
            product_id = adj_data.get('product_id')
            if not product_id:
                continue

            ReconciliationWorkflowService.update_adjustment(
                reconciliation_id=str(reconciliation_id),
                product_id=product_id,
                quantity_added=adj_data.get('quantity_added', 0),
                quantity_deducted=adj_data.get('quantity_deducted', 0),
                notes=adj_data.get('notes', '')
            )
            updated_count += 1

        # Refresh and return reconciliation
        reconciliation.refresh_from_db()
        serializer = DailyStockReconciliationSerializer(reconciliation)

        return Response({
            'success': True,
            'updated_count': updated_count,
            'message': f'Updated {updated_count} adjustments',
            'reconciliation': serializer.data
        }, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error bulk updating stock adjustments: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdmin])
def revert_stock_reconciliation(request, reconciliation_id):
    """
    Revert a confirmed reconciliation back to DRAFT status.

    POST /api/v1/stock-reconciliation/{reconciliation_id}/revert/

    This is an ADMIN-ONLY operation that:
    - Reverses all inventory movements created during confirmation
    - Creates audit trail for the reversal
    - Resets reconciliation status to DRAFT
    - Allows re-editing and re-confirmation

    Returns: reverted reconciliation object
    """
    from payments.models import DailyStockReconciliation, InventoryMovement, Product
    from payments.serializers import DailyStockReconciliationSerializer
    from django.db import transaction as db_transaction
    from django.utils import timezone

    try:
        with db_transaction.atomic():
            # Get and lock reconciliation
            reconciliation = DailyStockReconciliation.objects.select_for_update().get(
                id=reconciliation_id
            )

            # Must be confirmed to revert
            if reconciliation.status != DailyStockReconciliation.Status.CONFIRMED:
                return Response(
                    {'error': f'Can only revert CONFIRMED reconciliations. Current status: {reconciliation.status}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Find and reverse inventory movements created during confirmation
            recon_date = reconciliation.reconciliation_date
            reference_pattern = f"EOD Reconciliation {recon_date}"
            movements = InventoryMovement.objects.filter(
                reference__startswith=reference_pattern
            ).select_related('product')

            reversed_count = 0
            for mov in movements:
                if mov.quantity_change == 0:
                    continue

                product = Product.objects.select_for_update().get(id=mov.product.id)
                qty_before = product.quantity

                # Reverse the change
                product.quantity -= mov.quantity_change
                product.save()

                # Create a reversal movement for audit trail
                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.MovementType.ADJUSTMENT,
                    product=product,
                    quantity_before=qty_before,
                    quantity_after=product.quantity,
                    quantity_change=-mov.quantity_change,  # Opposite of original
                    reference=f"REVERT: {mov.reference}",
                    performed_by=request.user.username
                )
                reversed_count += 1

            # Update adjustment closing_stock values to reflect new state
            from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService
            for adjustment in reconciliation.adjustments.select_related('product').all():
                adjustment.closing_stock = ReconciliationWorkflowService._get_closing_stock(adjustment)
                adjustment.save()

            # Reset reconciliation status
            reconciliation.status = DailyStockReconciliation.Status.DRAFT
            reconciliation.confirmed_by = None
            reconciliation.confirmed_at = None

            # Add note about reversion
            revert_note = (
                f"\n[{timezone.now().strftime('%Y-%m-%d %H:%M')}] "
                f"REVERTED by {request.user.username}"
            )
            reconciliation.notes = f"{reconciliation.notes or ''}{revert_note}"
            reconciliation.save()

            logger.warning(
                f"Admin {request.user.username} reverted reconciliation for {recon_date}. "
                f"Reversed {reversed_count} inventory movements."
            )

            serializer = DailyStockReconciliationSerializer(reconciliation)
            return Response({
                'success': True,
                'message': f'Reconciliation for {recon_date} reverted to DRAFT. {reversed_count} inventory movements reversed.',
                'reversed_count': reversed_count,
                'reconciliation': serializer.data
            }, status=status.HTTP_200_OK)

    except DailyStockReconciliation.DoesNotExist:
        return Response({'error': 'Reconciliation not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error reverting stock reconciliation: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================================
# Promotions API
# ============================================================================

@api_view(['GET', 'POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def promotion_list_create(request):
    """List all promotions or create a new one (admin or processor)."""
    from payments.models import Promotion
    from payments.serializers import PromotionSerializer

    if request.method == 'GET':
        promotions = Promotion.objects.prefetch_related('promotion_products__product').all()
        serializer = PromotionSerializer(promotions, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = PromotionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def promotion_detail(request, pk):
    """Retrieve, update or delete a promotion (admin or processor)."""
    from payments.models import Promotion
    from payments.serializers import PromotionSerializer

    try:
        promotion = Promotion.objects.prefetch_related('promotion_products__product').get(pk=pk)
    except Promotion.DoesNotExist:
        return Response({'error': 'Promotion not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = PromotionSerializer(promotion)
        return Response(serializer.data)

    elif request.method in ['PUT', 'PATCH']:
        partial = request.method == 'PATCH'
        serializer = PromotionSerializer(promotion, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    elif request.method == 'DELETE':
        promotion.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================================================================
# Location Endpoints (Multi-Location Support)
# ============================================================================

@api_view(['GET', 'POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def location_list_create(request):
    """
    GET  /api/v1/locations/ — list all active locations
    POST /api/v1/locations/ — create a new field location (ADMIN only)
    """
    if request.method == 'GET':
        locations = Location.objects.filter(status=Location.LocationStatus.ACTIVE).order_by('name')
        serializer = LocationSerializer(locations, many=True)
        return Response(serializer.data)

    # POST — admin only
    if not request.user.is_admin():
        return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)

    serializer = LocationSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    location = serializer.save(created_by=request.user)
    return Response(LocationSerializer(location).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def location_detail(request, location_id):
    """
    GET   /api/v1/locations/<uuid>/ — retrieve location detail
    PATCH /api/v1/locations/<uuid>/ — update location (ADMIN only)
    """
    try:
        location = Location.objects.get(pk=location_id)
    except Location.DoesNotExist:
        return Response({'error': 'Location not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(LocationSerializer(location).data)

    if not request.user.is_admin():
        return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)

    serializer = LocationSerializer(location, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    serializer.save()
    return Response(serializer.data)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def location_close(request, location_id):
    """
    POST /api/v1/locations/<uuid>/close/ — close a field location (ADMIN only)
    """
    if not request.user.is_admin():
        return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)

    try:
        location = Location.objects.get(pk=location_id)
    except Location.DoesNotExist:
        return Response({'error': 'Location not found'}, status=status.HTTP_404_NOT_FOUND)

    if location.is_main:
        return Response({'error': 'Cannot close the Main Shop location'}, status=status.HTTP_400_BAD_REQUEST)

    if location.status == Location.LocationStatus.CLOSED:
        return Response({'error': 'Location is already closed'}, status=status.HTTP_400_BAD_REQUEST)

    location.status = Location.LocationStatus.CLOSED
    location.closed_at = timezone.now()
    location.save()

    return Response(LocationSerializer(location).data)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def set_user_location(request):
    """
    POST /api/v1/locations/set-mine/ — set the calling user's current_location

    Body: { "location_id": "<uuid>" }
    """
    location_id = request.data.get('location_id')
    if not location_id:
        return Response({'error': 'location_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        location = Location.objects.get(pk=location_id, status=Location.LocationStatus.ACTIVE)
    except Location.DoesNotExist:
        return Response({'error': 'Active location not found'}, status=status.HTTP_404_NOT_FOUND)

    request.user.current_location = location
    request.user.save(update_fields=['current_location'])

    return Response({
        'success': True,
        'current_location': LocationSerializer(location).data,
    })


@api_view(['GET', 'POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def merchandise_catalog(request):
    if request.method == 'GET':
        items = MerchandiseCatalogItem.objects.filter(is_active=True).prefetch_related('options').order_by('name')
        return Response(MerchandiseCatalogItemSerializer(items, many=True).data)

    serializer = MerchandiseCatalogItemCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    item = serializer.save()
    return Response(
        MerchandiseCatalogItemSerializer(item).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def merchandise_catalog_item_detail(request, item_id):
    try:
        item = MerchandiseCatalogItem.objects.prefetch_related('options').get(id=item_id)
    except MerchandiseCatalogItem.DoesNotExist:
        return Response({'error': 'Merchandise catalog item not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(MerchandiseCatalogItemSerializer(item).data)

    if request.method == 'DELETE':
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = MerchandiseCatalogItemCreateSerializer(item, data=request.data, partial=request.method == 'PATCH')
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    updated = serializer.save()
    return Response(MerchandiseCatalogItemSerializer(updated).data)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def merchandise_pending_orders(request):
    queryset = MerchandiseService.get_pending_orders()
    return Response(MerchandiseOrderSerializer(queryset, many=True).data)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def merchandise_order_detail(request, order_id):
    try:
        order = MerchandiseOrder.objects.select_related(
            'transaction', 'gateway', 'fulfilled_by'
        ).prefetch_related('lines__item').get(id=order_id)
    except MerchandiseOrder.DoesNotExist:
        return Response({'error': 'Merchandise order not found'}, status=status.HTTP_404_NOT_FOUND)

    return Response(MerchandiseOrderSerializer(order).data)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def merchandise_fulfill_order(request, order_id):
    try:
        order = MerchandiseOrder.objects.select_related('transaction', 'gateway').get(id=order_id)
    except MerchandiseOrder.DoesNotExist:
        return Response({'error': 'Merchandise order not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = MerchandiseFulfillRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        updated = MerchandiseService.fulfill_order(
            order=order,
            lines_payload=serializer.validated_data['lines'],
            user=request.user
        )
    except ValidationError as exc:
        details = getattr(exc, 'message_dict', None) or getattr(exc, 'messages', None) or str(exc)
        return Response({'error': details}, status=status.HTTP_400_BAD_REQUEST)

    if serializer.validated_data.get('notes'):
        updated.notes = serializer.validated_data['notes']
        updated.save(update_fields=['notes', 'updated_at'])

    updated = MerchandiseOrder.objects.select_related(
        'transaction', 'gateway', 'fulfilled_by'
    ).prefetch_related('lines__item').get(id=updated.id)
    return Response(MerchandiseOrderSerializer(updated).data)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def merchandise_daily_report(request):
    report_date_str = request.query_params.get('date')
    if report_date_str:
        report_date = parse_date(report_date_str)
        if not report_date:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
    else:
        report_date = timezone.localdate()

    rows = MerchandiseService.get_daily_report_rows(report_date)
    return Response({
        'date': report_date.isoformat(),
        'headers': ['Product', 'Quantity', 'Size', 'Colour', 'Total Amount'],
        'rows': rows
    })


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def merchandise_stock_list(request):
    # Ensure all expected variants exist, then return current stock rows.
    MerchandiseService.get_stock_rows()
    queryset = MerchandiseStock.objects.select_related('item').order_by('item__name', 'color', 'size')
    return Response(MerchandiseStockSerializer(queryset, many=True).data)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def merchandise_adjust_stock(request):
    serializer = MerchandiseStockAdjustRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        MerchandiseService.adjust_stock(
            adjustments=serializer.validated_data['adjustments'],
            user=request.user,
            notes=serializer.validated_data.get('notes', '')
        )
    except ValidationError as exc:
        details = getattr(exc, 'message_dict', None) or getattr(exc, 'messages', None) or str(exc)
        return Response({'error': details}, status=status.HTTP_400_BAD_REQUEST)

    queryset = MerchandiseStock.objects.select_related('item').order_by('item__name', 'color', 'size')
    return Response({
        'success': True,
        'stock': MerchandiseStockSerializer(queryset, many=True).data
    })


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def merchandise_stock_movements(request):
    limit = request.query_params.get('limit', '100')
    try:
        limit_value = max(1, min(500, int(limit)))
    except ValueError:
        return Response({'error': 'limit must be an integer'}, status=status.HTTP_400_BAD_REQUEST)

    queryset = MerchandiseStockMovement.objects.select_related(
        'stock__item', 'performed_by'
    ).order_by('-created_at')[:limit_value]
    return Response(MerchandiseStockMovementSerializer(queryset, many=True).data)


@api_view(['GET'])
@authentication_classes([InventoryAPIAuthentication])
@permission_classes([IsAuthenticated])
def bi_briefing(request):
    from datetime import date
    from payments.services.bi_briefing_service import BiBriefingService

    date_param = request.query_params.get('date')
    if date_param:
        try:
            report_date = datetime.strptime(date_param, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
    else:
        report_date = timezone.localdate()

    briefing = BiBriefingService.generate_daily_briefing(report_date)
    return Response(briefing)


def _escape_md(text):
    return text.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[')


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def telegram_webhook(request):
    from asgiref.sync import async_to_sync
    from payments.bi_telegram_bot import handle_message_with_media

    update = request.data
    message = update.get('message', {})
    chat_id = message.get('chat', {}).get('id')
    text = message.get('text', '')
    user_id = message.get('from', {}).get('id')

    if text and chat_id:
        from django.conf import settings
        import httpx
        from payments.services.bi_conversation_service import ConversationMemory
        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        if not token:
            return Response({'ok': True})

        is_command = text.strip().startswith('/')
        chart_buf = None
        xlsx_buf = None
        xlsx_name = None

        if is_command:
            response, chart_buf, xlsx_buf, xlsx_name = async_to_sync(handle_message_with_media)(text, user_id)
        else:
            from payments.services.bi_agent_service import BIAgent, ResponseReflector
            text_resp, tool_name, tool_data, client, model, history = async_to_sync(BIAgent._process_message_data)(
                str(user_id or '0'), text,
            )
            response = text_resp
            if not response.startswith("❌"):
                from django.conf import settings as dj_settings
                if getattr(dj_settings, 'LLM_EVALUATOR_ENABLED', True):
                    eval_result = async_to_sync(ResponseReflector.evaluate)(
                        response, text, tool_name or '', {}, client, model,
                        threshold=getattr(dj_settings, 'LLM_EVALUATOR_THRESHOLD', 7),
                    )
                    if eval_result['action'] == 'rewrite':
                        eval_messages = BIAgent._build_messages(text, timezone.localdate(), history[-5:])
                        response = async_to_sync(ResponseReflector.regenerate)(
                            response, eval_result['issues'], eval_messages, client, model,
                        )
                try:
                    ConversationMemory.add_exchange(
                        str(user_id or '0'), text, response,
                        chart_intent=BIAgent.should_generate_chart(text),
                        xlsx_intent=BIAgent.should_generate_xlsx(text),
                    )
                except Exception:
                    pass
                wants_chart = BIAgent.should_generate_chart(text)
                wants_xlsx = BIAgent.should_generate_xlsx(text)
                if not wants_chart and tool_name and tool_data:
                    wants_chart = ConversationMemory.has_chart_intent(
                        str(user_id or '0'), history=history,
                    )
                if not wants_xlsx and tool_name and tool_data:
                    wants_xlsx = ConversationMemory.has_xlsx_intent(
                        str(user_id or '0'), history=history,
                    )
                if wants_chart:
                    chart_buf = BIAgent.generate_chart(tool_name, tool_data)
                if wants_xlsx:
                    xlsx_result = BIAgent.generate_xlsx(tool_name, tool_data)
                    if xlsx_result:
                        xlsx_buf, xlsx_name = xlsx_result

        def _send_text(text_str):
            if not text_str:
                return
            text_str = _escape_md(text_str)
            if len(text_str) <= MAX_LEN:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                r = httpx.post(url, json={
                    'chat_id': chat_id, 'text': text_str, 'parse_mode': 'Markdown',
                })
                if r.status_code != 200:
                    logger.error("Telegram sendMessage 400: %s", r.text[:500])
            else:
                chunks = []
                remaining = text_str
                while remaining:
                    if len(remaining) <= MAX_LEN:
                        chunks.append(remaining)
                        break
                    split_at = remaining.rfind('\n', 0, MAX_LEN)
                    if split_at == -1:
                        split_at = remaining.rfind('. ', 0, MAX_LEN)
                    if split_at == -1:
                        split_at = remaining.rfind(', ', 0, MAX_LEN)
                    if split_at == -1:
                        split_at = MAX_LEN
                    chunk = remaining[:split_at + 1].strip()
                    remaining = remaining[split_at + 1:].strip()
                    if chunk:
                        chunks.append(chunk)
                if remaining.strip():
                    chunks.append(remaining.strip())
                for chunk in chunks:
                    if chunk:
                        url = f"https://api.telegram.org/bot{token}/sendMessage"
                        r = httpx.post(url, json={
                            'chat_id': chat_id, 'text': chunk, 'parse_mode': 'Markdown',
                        })
                        if r.status_code != 200:
                            logger.error("Telegram sendMessage (chunk) 400: %s", r.text[:500])

        MAX_LEN = 4000
        _send_text(response)

        if chart_buf:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            httpx.post(url, files={
                'photo': ('chart.png', chart_buf.getvalue(), 'image/png'),
            }, data={'chat_id': chat_id})

        if xlsx_buf and xlsx_name:
            url = f"https://api.telegram.org/bot{token}/sendDocument"
            httpx.post(url, files={
                'document': (xlsx_name, xlsx_buf.getvalue(),
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            }, data={'chat_id': chat_id})

    return Response({'ok': True})


# ============================================================================
# BI Extended Query API Endpoints
# ============================================================================

_BI_QUERY_HANDLERS = {}


def _bi_handler(query_type):
    """Decorator to register a handler for a BI query type."""
    def decorator(fn):
        _BI_QUERY_HANDLERS[query_type] = fn
        return fn
    return decorator


def _parse_date_param(val):
    if not val:
        return None
    try:
        return datetime.strptime(val, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        raise ValidationError(f"Invalid date format '{val}'. Use YYYY-MM-DD")


@api_view(['GET'])
@authentication_classes([InventoryAPIAuthentication])
@permission_classes([IsAuthenticated])
def bi_query(request, query_type):
    from payments.services.bi_extended_service import BiExtendedService

    handler = _BI_QUERY_HANDLERS.get(query_type)
    if not handler:
        available = sorted(_BI_QUERY_HANDLERS.keys())
        return Response(
            {'error': f"Unknown query type '{query_type}'. Available: {', '.join(available)}"},
            status=status.HTTP_404_NOT_FOUND,
        )
    try:
        data = handler(request, BiExtendedService)
        return Response(data)
    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"BI query '{query_type}' failed: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@_bi_handler('product-stock')
def _handle_product_stock(request, svc):
    q = request.query_params.get('q', '').strip()
    if not q:
        raise ValidationError("'q' parameter required (product name or code)")
    return svc.get_product_stock(q)


@_bi_handler('product-sales')
def _handle_product_sales(request, svc):
    q = request.query_params.get('q', '').strip()
    if not q:
        raise ValidationError("'q' parameter required (product name or code)")
    date = _parse_date_param(request.query_params.get('date')) or timezone.localdate()
    return svc.get_product_sales(q, date)


@_bi_handler('product-trend')
def _handle_product_trend(request, svc):
    q = request.query_params.get('q', '').strip()
    if not q:
        raise ValidationError("'q' parameter required (product name or code)")
    days = int(request.query_params.get('days', '30'))
    return svc.get_product_sales_trend(q, days)


@_bi_handler('top-products')
def _handle_top_products(request, svc):
    date = _parse_date_param(request.query_params.get('date')) or timezone.localdate()
    limit = int(request.query_params.get('limit', '10'))
    return svc.get_top_products(date, limit)


@_bi_handler('top-products-by-revenue')
def _handle_top_products_revenue(request, svc):
    date = _parse_date_param(request.query_params.get('date')) or timezone.localdate()
    limit = int(request.query_params.get('limit', '10'))
    return svc.get_top_products_by_revenue(date, limit)


@_bi_handler('category-sales')
def _handle_category_sales(request, svc):
    q = request.query_params.get('q', '').strip()
    if not q:
        raise ValidationError("'q' parameter required (category name)")
    date = _parse_date_param(request.query_params.get('date')) or timezone.localdate()
    return svc.get_category_sales(q, date)


@_bi_handler('stock-by-category')
def _handle_stock_by_category(request, svc):
    return svc.get_stock_by_category()


@_bi_handler('inventory-value')
def _handle_inventory_value(request, svc):
    return svc.get_inventory_value()


@_bi_handler('stock-movements')
def _handle_stock_movements(request, svc):
    q = request.query_params.get('q', '').strip() or None
    days = int(request.query_params.get('days', '7'))
    return svc.get_stock_movements(q, days)


@_bi_handler('transaction-search')
def _handle_transaction_search(request, svc):
    q = request.query_params.get('q', '').strip()
    if not q:
        raise ValidationError("'q' parameter required (search query)")
    return svc.search_transactions(q)


@_bi_handler('transaction-detail')
def _handle_transaction_detail(request, svc):
    tx_id = request.query_params.get('tx_id', '').strip()
    if not tx_id:
        raise ValidationError("'tx_id' parameter required")
    return svc.get_transaction_detail(tx_id)


@_bi_handler('customer-search')
def _handle_customer_search(request, svc):
    q = request.query_params.get('q', '').strip()
    if not q:
        raise ValidationError("'q' parameter required (name or phone)")
    return svc.search_customer(q)


@_bi_handler('pending-fulfillments')
def _handle_pending_fulfillments(request, svc):
    return svc.get_pending_fulfillments()


@_bi_handler('fulfillment-pipeline')
def _handle_fulfillment_pipeline(request, svc):
    return svc.get_fulfillment_pipeline()


@_bi_handler('user-performance')
def _handle_user_performance(request, svc):
    username = request.query_params.get('username', '').strip() or None
    date = _parse_date_param(request.query_params.get('date')) or timezone.localdate()
    return svc.get_user_performance(username, date)


@_bi_handler('combined-orders')
def _handle_combined_orders(request, svc):
    date = _parse_date_param(request.query_params.get('date')) or timezone.localdate()
    return svc.get_combined_orders_summary(date)


@_bi_handler('gateway-breakdown')
def _handle_gateway_breakdown(request, svc):
    date = _parse_date_param(request.query_params.get('date')) or timezone.localdate()
    return svc.get_gateway_breakdown(date)


@_bi_handler('period-revenue')
def _handle_period_revenue(request, svc):
    start = _parse_date_param(request.query_params.get('start'))
    end = _parse_date_param(request.query_params.get('end'))
    if not start or not end:
        raise ValidationError("'start' and 'end' parameters required (YYYY-MM-DD)")
    return svc.get_period_revenue(start, end)


@_bi_handler('period-sales')
def _handle_period_sales(request, svc):
    start = _parse_date_param(request.query_params.get('start'))
    end = _parse_date_param(request.query_params.get('end'))
    if not start or not end:
        raise ValidationError("'start' and 'end' parameters required (YYYY-MM-DD)")
    return svc.get_period_sales(start, end)


@_bi_handler('period-revenue-vs-sales')
def _handle_period_revenue_vs_sales(request, svc):
    start = _parse_date_param(request.query_params.get('start'))
    end = _parse_date_param(request.query_params.get('end'))
    if not start or not end:
        raise ValidationError("'start' and 'end' parameters required (YYYY-MM-DD)")
    return svc.get_period_revenue_vs_sales(start, end)


@_bi_handler('month-comparison')
def _handle_month_comparison(request, svc):
    return svc.get_month_comparison()


@_bi_handler('year-comparison')
def _handle_year_comparison(request, svc):
    return svc.get_year_comparison()


@_bi_handler('product-comparison')
def _handle_product_comparison(request, svc):
    q = request.query_params.get('q', '').strip()
    date1 = _parse_date_param(request.query_params.get('date1'))
    date2 = _parse_date_param(request.query_params.get('date2'))
    if not q:
        raise ValidationError("'q' parameter required (product name or code)")
    if not date1 or not date2:
        raise ValidationError("'date1' and 'date2' parameters required (YYYY-MM-DD)")
    return svc.get_product_comparison(q, date1, date2)


@_bi_handler('registration-kits')
def _handle_registration_kits(request, svc):
    start = _parse_date_param(request.query_params.get('start'))
    end = _parse_date_param(request.query_params.get('end'))
    today = timezone.localdate()
    if not start:
        start = today - timedelta(days=30)
    if not end:
        end = today
    return svc.get_registration_kits_summary(start, end)


@_bi_handler('pv-summary')
def _handle_pv_summary(request, svc):
    date = _parse_date_param(request.query_params.get('date')) or timezone.localdate()
    return svc.get_pv_summary(date)


@_bi_handler('cost-of-goods')
def _handle_cost_of_goods(request, svc):
    date = _parse_date_param(request.query_params.get('date')) or timezone.localdate()
    return svc.get_total_cost(date)


@api_view(['POST'])
@authentication_classes([RelayAuthentication])
@permission_classes([AllowAny])
def bi_execute(request):
    from payments.services.bi_agent_service import _TOOL_FUNCTIONS
    tool_name = request.data.get('tool_name')
    args = request.data.get('args', {})

    if not tool_name:
        return Response({'error': 'tool_name required'}, status=400)

    fn = _TOOL_FUNCTIONS.get(tool_name)
    if fn is None:
        return Response({'error': f'Unknown tool: {tool_name}'}, status=400)

    try:
        result = fn(args)
        return Response(result)
    except Exception as e:
        logger.error(f"bi_execute error for {tool_name}: {e}")
        return Response({'error': str(e)}, status=500)


# ============================================================================
# Health Check Endpoint
# ============================================================================

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def health_check(request):
    """
    System health check endpoint.

    Checks:
    - Database connectivity
    - Celery worker responsiveness (via ping)
    - Stale relayed messages

    Returns HTTP 200 if healthy, 503 if degraded.
    Does not require authentication — designed for external monitoring.
    """
    from datetime import timedelta
    from payments.models import RawMessage

    healthy = True
    checks = {}

    # 1. Database
    try:
        from django.db import connection as db_conn
        db_conn.ensure_connection()
        checks['database'] = {'status': 'ok'}
    except Exception as e:
        checks['database'] = {'status': 'error', 'detail': str(e)}
        healthy = False

    # 2. Celery worker ping
    try:
        from celery.app.control import Inspect
        from management.celery import app as celery_app
        inspect = Inspect(app=celery_app)
        stats = inspect.stats(timeout=3)
        if stats:
            workers = list(stats.keys())
            checks['celery'] = {'status': 'ok', 'workers': workers}
        else:
            checks['celery'] = {'status': 'error', 'detail': 'No workers responded'}
            healthy = False
    except Exception as e:
        checks['celery'] = {'status': 'error', 'detail': str(e)}
        healthy = False

    # 3. Stale relayed messages
    cutoff = timezone.now() - timedelta(minutes=5)
    stale_relayed = RawMessage.objects.filter(
        processed=False,
        is_relayed=True,
        created_at__lte=cutoff,
    ).count()

    checks['stale_relayed_messages'] = {
        'status': 'warning' if stale_relayed > 0 else 'ok',
        'count': stale_relayed,
        'detail': f'{stale_relayed} unprocessed relayed messages older than 5 minutes' if stale_relayed else 'none',
    }
    if stale_relayed >= 10:
        healthy = False

    # 4. Pending relayed messages (recent, may still be processing)
    recent_pending = RawMessage.objects.filter(
        processed=False,
        is_relayed=True,
    ).count()

    checks['pending_relayed_messages'] = {
        'status': 'ok',
        'count': recent_pending,
    }

    status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return Response({
        'status': 'healthy' if healthy else 'degraded',
        'checks': checks,
    }, status=status_code)