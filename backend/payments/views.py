from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics, filters
from rest_framework.decorators import api_view, authentication_classes, permission_classes
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
    UserUpdateSerializer, ChangePasswordSerializer, AdminPasswordResetSerializer
)
from .models import Device, Transaction, ManualPayment, PaymentGateway, Product, ProductLine, InventoryMovement
from .filters import TransactionFilter, ManualPaymentFilter
from .permissions import (
    IsAdmin, IsProcessor, IsIssuer, IsAdminOrProcessor, IsAdminOrIssuer,
    IsDeviceOrAuthenticated, IsDeviceOrProcessor, IsDeviceOrIssuer, IsAuthenticatedUser
)
from django.contrib.auth.hashers import make_password
import secrets
from .auth import DeviceAPIKeyAuthentication, SimpleAPIKeyAuthentication
from .tasks import process_raw_message
from .services import ManualPaymentService
from .services.reconciliation_service import ReconciliationService
from .services.pdf_report_service import PDFReportService
from .services.export_service import TransactionExportService
from .services.time_locking_service import TimeLockingService
from .services.combined_order_service import CombinedOrderService
from .services.stock_take_service import StockTakeService
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.http import HttpResponse
from django.core.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)
User = get_user_model()

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
    authentication_classes = [DeviceAPIKeyAuthentication]

    def post(self, request, *args, **kwargs):
        serializer = RawMessageSerializer(data=request.data)
        if serializer.is_valid():
            # Extract the actual Device object from the AuthenticatedDevice wrapper
            device = getattr(request.user, 'device', request.user)
            message = serializer.save(device=device)
            process_raw_message.delay(message.id)
            return Response({"message_id": message.id, "status": "queued"}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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

        - ISSUER role: Only see PROCESSING transactions (their work queue)
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
            # If user is ISSUER, only show PROCESSING transactions
            if self.request.user.role == 'ISSUER':
                logger.info(f"  FILTERING: Applying status=PROCESSING filter for ISSUER")
                queryset = queryset.filter(status='PROCESSING')
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

    Returns only M-Pesa gateways (MPESA_TILL and MPESA_PAYBILL) since
    devices forward M-Pesa SMS messages. Other payment methods (Bank Transfer,
    Cash, PDQ, Cheque) are not relevant for device gateway assignment.

    Returns:
    - id, name, gateway_type, gateway_number for each M-Pesa gateway

    Note: Ordered alphabetically by name for consistent display across apps
    """
    gateways = PaymentGateway.objects.filter(
        is_active=True,
        gateway_type__in=['MPESA_TILL', 'MPESA_PAYBILL']
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
def daily_reconciliation_pdf(request):
    """
    Generate and download daily reconciliation report as PDF.

    Query params:
    - report_date: Date in YYYY-MM-DD format (defaults to today)

    Example:
    GET /api/reports/daily-reconciliation/pdf/?report_date=2025-10-09

    Returns:
    PDF file download
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
        from django.utils import timezone
        report_date = timezone.now().date()

    try:
        pdf_buffer = PDFReportService.generate_daily_reconciliation_pdf(report_date)

        # Create HTTP response with PDF
        response = HttpResponse(pdf_buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="reconciliation_report_{report_date}.pdf"'
        return response

    except Exception as e:
        return Response(
            {'error': f'Failed to generate PDF: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def date_range_reconciliation_pdf(request):
    """
    Generate and download date range reconciliation report as PDF.

    Query params (required):
    - start_date: Start date in YYYY-MM-DD format
    - end_date: End date in YYYY-MM-DD format

    Example:
    GET /api/reports/date-range-reconciliation/pdf/?start_date=2025-10-01&end_date=2025-10-09

    Returns:
    PDF file download
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
        pdf_buffer = PDFReportService.generate_date_range_reconciliation_pdf(start_date, end_date)

        # Create HTTP response with PDF
        response = HttpResponse(pdf_buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="reconciliation_report_{start_date}_to_{end_date}.pdf"'
        return response

    except Exception as e:
        return Response(
            {'error': f'Failed to generate PDF: {str(e)}'},
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
        report_date = timezone.now().date()

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
def transactions_csv_export(request):
    """
    Export transactions to CSV format.

    Query params:
    - date: Export transactions for a specific date (YYYY-MM-DD format)
    - start_date: Start date for range export (YYYY-MM-DD format)
    - end_date: End date for range export (YYYY-MM-DD format)

    If only 'date' is provided, exports transactions for that day.
    If 'start_date' and 'end_date' are provided, exports range.
    If no params, exports today's transactions.

    Examples:
    GET /api/v1/exports/transactions/csv/?date=2025-10-09
    GET /api/v1/exports/transactions/csv/?start_date=2025-10-01&end_date=2025-10-09
    GET /api/v1/exports/transactions/csv/

    Returns:
    CSV file download
    """
    date_str = request.query_params.get('date')
    start_date_str = request.query_params.get('start_date')
    end_date_str = request.query_params.get('end_date')

    try:
        # Determine which date range to use
        if start_date_str and end_date_str:
            # Date range export
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

            transactions = TransactionExportService.get_transactions_for_date_range(start_date, end_date)
            filename = f'transactions_{start_date}_to_{end_date}.csv'

        elif date_str:
            # Single date export
            export_date = parse_date(date_str)
            if not export_date:
                return Response(
                    {'error': 'Invalid date format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            transactions = TransactionExportService.get_transactions_for_date(export_date)
            filename = f'transactions_{export_date}.csv'

        else:
            # Default to today
            from django.utils import timezone
            today = timezone.now().date()
            transactions = TransactionExportService.get_transactions_for_date(today)
            filename = f'transactions_{today}.csv'

        # Generate CSV
        csv_buffer = TransactionExportService.export_to_csv(transactions, filename)

        # Create HTTP response
        response = HttpResponse(csv_buffer.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        return Response(
            {'error': f'Failed to generate CSV export: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def transactions_xlsx_export(request):
    """
    Export transactions to XLSX (Excel) format with formatting.

    Query params:
    - date: Export transactions for a specific date (YYYY-MM-DD format)
    - start_date: Start date for range export (YYYY-MM-DD format)
    - end_date: End date for range export (YYYY-MM-DD format)

    If only 'date' is provided, exports transactions for that day.
    If 'start_date' and 'end_date' are provided, exports range.
    If no params, exports today's transactions.

    Examples:
    GET /api/v1/exports/transactions/xlsx/?date=2025-10-09
    GET /api/v1/exports/transactions/xlsx/?start_date=2025-10-01&end_date=2025-10-09
    GET /api/v1/exports/transactions/xlsx/

    Returns:
    XLSX file download with professional formatting
    """
    date_str = request.query_params.get('date')
    start_date_str = request.query_params.get('start_date')
    end_date_str = request.query_params.get('end_date')

    try:
        # Determine which date range to use
        if start_date_str and end_date_str:
            # Date range export
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

            transactions = TransactionExportService.get_transactions_for_date_range(start_date, end_date)
            filename = f'transactions_{start_date}_to_{end_date}.xlsx'

        elif date_str:
            # Single date export
            export_date = parse_date(date_str)
            if not export_date:
                return Response(
                    {'error': 'Invalid date format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            transactions = TransactionExportService.get_transactions_for_date(export_date)
            filename = f'transactions_{export_date}.xlsx'

        else:
            # Default to today
            from django.utils import timezone
            today = timezone.now().date()
            transactions = TransactionExportService.get_transactions_for_date(today)
            filename = f'transactions_{today}.xlsx'

        # Generate XLSX
        xlsx_buffer = TransactionExportService.export_to_xlsx(transactions, filename)

        # Create HTTP response
        response = HttpResponse(
            xlsx_buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        return Response(
            {'error': f'Failed to generate XLSX export: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

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
    DELETE: Delete product (only if not referenced in transactions)
    """
    authentication_classes = [DeviceAPIKeyAuthentication]
    queryset = Product.objects.all().select_related('product_line')
    serializer_class = ProductSerializer


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication])
def product_search_by_sku(request):
    """
    Search for a product by SKU or prod_code (for barcode scanner).
    
    Query params:
    - sku: SKU to search for
    - prod_code: Product code to search for
    
    Returns single product if found, 404 if not found.
    """
    sku = request.query_params.get('sku')
    prod_code = request.query_params.get('prod_code')
    
    if not sku and not prod_code:
        return Response(
            {'error': 'Either sku or prod_code parameter is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        if sku:
            product = Product.objects.get(sku=sku, is_active=True)
        else:
            product = Product.objects.get(prod_code=prod_code, is_active=True)
        
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


# ============================================================================
# Transaction Fulfillment API Views
# ============================================================================

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
        result = FulfillmentService.activate_issuance(
            transaction_id,
            activated_by_user=request.user
        )
        return Response(result, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response({'error': e.message_dict}, status=status.HTTP_400_BAD_REQUEST)
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
        "sku": "AP004E",          // Product SKU (or prod_code)
        "prod_code": "AP004E",    // Alternative to sku
        "quantity": 1,            // Quantity scanned (default: 1)
        "scanned_by": "User"      // Who performed the scan
    }
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
        # Check if registration transaction (use special workflow)
        transaction = Transaction.objects.get(id=transaction_id)

        if transaction.is_registration:
            # Get quantity from request data (default to 1)
            quantity = request.data.get('quantity', 1)
            result = FulfillmentService.complete_registration_issuance(
                transaction_id,
                quantity=quantity,
                completed_by_user=request.user if hasattr(request.user, 'role') else None
            )
        else:
            result = FulfillmentService.complete_issuance(
                transaction_id,
                completed_by_user=request.user if hasattr(request.user, 'role') else None
            )
        return Response(result, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response({'error': e.message_dict}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error completing issuance for transaction {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrIssuer])
def remove_line_item(request, transaction_id, line_item_id):
    """
    Remove a specific line item from the transaction during issuance.

    Does NOT update inventory - only removes the line item and updates transaction totals.
    Can only be used while transaction is in issuance mode (before completion).
    """
    from payments.models import Transaction, TransactionLineItem
    from django.core.exceptions import ValidationError
    from decimal import Decimal

    try:
        # Get transaction
        transaction = Transaction.objects.get(id=transaction_id)

        # Verify transaction is in issuance or can be modified
        # Allow deletion for PROCESSING and PARTIALLY_FULFILLED (before inventory deduction)
        if transaction.status not in [Transaction.OrderStatus.PROCESSING, Transaction.OrderStatus.PARTIALLY_FULFILLED, Transaction.OrderStatus.NOT_PROCESSED]:
            return Response(
                {'error': {'is_in_issuance': [f'Cannot modify line items for {transaction.get_status_display()} transactions']}},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get and delete line item
        line_item = TransactionLineItem.objects.get(
            id=line_item_id,
            transaction=transaction
        )

        # Store line total before deleting
        line_total = line_item.line_total
        product_name = line_item.scanned_prod_name

        # Delete the line item
        line_item.delete()

        # Recalculate transaction totals
        remaining_items = transaction.line_items.all()
        new_fulfilled = sum(item.line_total for item in remaining_items)
        transaction.amount_fulfilled = new_fulfilled

        # Update status based on new totals
        if new_fulfilled == 0:
            transaction.status = Transaction.OrderStatus.NOT_PROCESSED
        elif new_fulfilled > 0 and new_fulfilled < transaction.amount:
            transaction.status = Transaction.OrderStatus.PARTIALLY_FULFILLED
        elif new_fulfilled >= transaction.amount:
            transaction.status = Transaction.OrderStatus.FULFILLED

        # Skip validation to allow status transitions when removing line items
        transaction.save(skip_validation=True)

        # Refresh from DB to get updated property values
        transaction.refresh_from_db()

        return Response({
            'success': True,
            'message': f'Removed {product_name}',
            'line_item_id': line_item_id,
            'amount_removed': str(line_total),
            'transaction_totals': {
                'amount_fulfilled': str(transaction.amount_fulfilled),
                'remaining_amount': str(transaction.remaining_amount),
                'status': transaction.status
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
        result = FulfillmentService.get_current_issuance()
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
                notes=serializer.validated_data.get('notes', '')
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
@authentication_classes([DeviceAPIKeyAuthentication])
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
    from payments.models import CombinedOrder, Transaction, CombinedOrderTransaction, StockTakeSession
    from django.core.exceptions import ValidationError
    from django.utils import timezone
    from decimal import Decimal

    try:
        # Get combined order
        combined_order = CombinedOrder.objects.get(combined_order_id=combined_order_id)

        # Validation: Combined order must be PENDING or PARTIALLY_FULFILLED
        if combined_order.status not in ['PENDING', 'PARTIALLY_FULFILLED']:
            return Response(
                {'error': f'Can only add transactions to PENDING or PARTIALLY_FULFILLED orders. Current status: {combined_order.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get transaction IDs from request
        transaction_ids = request.data.get('transaction_ids', [])
        if not transaction_ids:
            return Response(
                {'error': 'transaction_ids is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validation: Check for active stock-taking session
        if StockTakeSession.objects.filter(status='DRAFT').exists():
            return Response(
                {'error': 'Cannot modify combined orders while stock-taking session is active'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get transactions
        transactions = Transaction.objects.filter(id__in=transaction_ids)

        if transactions.count() != len(transaction_ids):
            return Response(
                {'error': 'Some transactions not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Validate each transaction
        errors = []
        for transaction in transactions:
            # Must be NOT_PROCESSED or PROCESSING
            if transaction.status not in [Transaction.OrderStatus.NOT_PROCESSED, Transaction.OrderStatus.PROCESSING]:
                errors.append(f'Transaction {transaction.tx_id}: Must be NOT_PROCESSED or PROCESSING (current: {transaction.get_status_display()})')

            # Not already in another combined order
            if transaction.combined_orders.exists():
                existing_order = transaction.combined_orders.first().combined_order
                errors.append(f'Transaction {transaction.tx_id}: Already in combined order {existing_order.combined_order_id}')

            # Not time-locked
            if transaction.is_time_locked:
                errors.append(f'Transaction {transaction.tx_id}: Time-locked and cannot be modified')

        if errors:
            return Response({'error': errors}, status=status.HTTP_400_BAD_REQUEST)

        # Add transactions to combined order
        from django.db.models import Max
        added_count = 0
        current_max_sequence = combined_order.transactions.aggregate(
            max_seq=Max('combinedordertransaction__sequence')
        )['max_seq'] or 0

        for idx, transaction in enumerate(transactions):
            # Create link
            CombinedOrderTransaction.objects.create(
                combined_order=combined_order,
                transaction=transaction,
                sequence=current_max_sequence + idx + 1,
                added_by=request.user.username if hasattr(request.user, 'username') else 'System'
            )

            # Update transaction status to PROCESSING if NOT_PROCESSED
            if transaction.status == Transaction.OrderStatus.NOT_PROCESSED:
                transaction.status = Transaction.OrderStatus.PROCESSING
                transaction.processed_by = request.user
                transaction.processed_at = timezone.now()
                transaction.save()

            added_count += 1

        # Recalculate combined order total_amount
        combined_order.refresh_from_db()
        total_amount = sum(
            Decimal(str(t.transaction.amount))
            for t in combined_order.combinedordertransaction_set.all()
        )
        combined_order.total_amount = total_amount
        combined_order.save()

        combined_order.refresh_from_db()

        return Response({
            'success': True,
            'message': f'Added {added_count} transaction(s) to combined order',
            'combined_order': CombinedOrderSerializer(combined_order).data,
            'added_count': added_count,
            'new_total_amount': str(combined_order.total_amount)
        }, status=status.HTTP_200_OK)

    except CombinedOrder.DoesNotExist:
        return Response(
            {'error': 'Combined order not found'},
            status=status.HTTP_404_NOT_FOUND
        )
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

    try:
        result = CombinedOrderService.cancel_combined_order(
            combined_order_id=combined_order_id,
            cancelled_by=serializer.validated_data['cancelled_by'],
            reason=serializer.validated_data.get('reason', '')
        )

        return Response(result, status=status.HTTP_200_OK)

    except ValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to cancel combined order: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
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

        from payments.serializers import CombinedOrderLineItemSerializer
        return Response({
            'success': True,
            'line_item': CombinedOrderLineItemSerializer(line_item).data,
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

        return Response({
            'success': True,
            'message': 'Line item removed'
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


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication, JWTAuthentication])
@permission_classes([IsAdminOrProcessor])
def unfulfilled_orders_xlsx_export(request):
    """
    Export unfulfilled orders to XLSX with two sections:
    - Today's unfulfilled orders
    - All other days' unfulfilled orders

    This endpoint is typically used at end-of-day closing, so it also triggers
    time-locking of partially fulfilled transactions for today.

    GET /api/v1/exports/unfulfilled-orders/xlsx/

    Query Parameters:
    - lock_today: If 'true', lock today's partially fulfilled transactions (default: true)

    Returns:
        XLSX file with formatted unfulfilled orders report
    """
    try:
        # Check if we should lock today's partially fulfilled transactions
        lock_today = request.GET.get('lock_today', 'true').lower() == 'true'

        # Lock today's partially fulfilled transactions (end-of-day operation)
        lock_result = None
        if lock_today:
            try:
                today = timezone.now().date()
                lock_result = TimeLockingService.lock_partially_fulfilled_transactions(
                    target_date=today,
                    locked_by="End-of-Day: Unfulfilled Orders Report"
                )
                logger.info(
                    f"Locked {lock_result['locked_count']} partially fulfilled transactions "
                    f"during unfulfilled orders report generation"
                )
            except Exception as e:
                logger.error(f"Failed to lock transactions during unfulfilled report: {e}")
                # Don't fail the export if locking fails, just log it

        output = TransactionExportService.export_unfulfilled_orders_xlsx()

        # Generate filename with timestamp
        filename = f"unfulfilled_orders_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        logger.info(f"Generated unfulfilled orders XLSX export: {filename}")
        return response

    except Exception as e:
        logger.error(f"Failed to generate unfulfilled orders XLSX: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


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
    - In issuance mode (is_in_issuance=True), OR
    - Status is PROCESSING (queued by Processor for Issuer)

    Ordered by most recently updated first.

    GET /api/v1/issuer/queue/
    """
    queue = Transaction.objects.filter(
        Q(is_in_issuance=True) | Q(status='PROCESSING')
    ).order_by('-updated_at')

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
