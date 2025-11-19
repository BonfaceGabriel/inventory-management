from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics, filters
from rest_framework.decorators import api_view, authentication_classes
from django_filters.rest_framework import DjangoFilterBackend
from .serializers import (
    DeviceRegisterSerializer, DeviceResponseSerializer, RawMessageSerializer,
    TransactionSerializer, ManualPaymentSerializer, ManualPaymentCreateSerializer,
    ProductSerializer, ProductListSerializer, ProductCategorySerializer,
    TransactionLineItemSerializer, InventoryMovementSerializer
)
from .models import Device, Transaction, ManualPayment, PaymentGateway, Product, ProductCategory, InventoryMovement
from .filters import TransactionFilter, ManualPaymentFilter
from django.contrib.auth.hashers import make_password
import secrets
from .auth import DeviceAPIKeyAuthentication, SimpleAPIKeyAuthentication
from .tasks import process_raw_message
from .services import ManualPaymentService
from .services.reconciliation_service import ReconciliationService
from .services.pdf_report_service import PDFReportService
from .services.export_service import TransactionExportService
from django.utils.dateparse import parse_date
from django.http import HttpResponse

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
            if gateway_id == '':
                # Allow clearing the gateway
                device.gateway = None
            else:
                try:
                    gateway = PaymentGateway.objects.get(id=gateway_id, is_active=True)
                    device.gateway = gateway
                except PaymentGateway.DoesNotExist:
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

        # Return updated device info
        response_data = DeviceResponseSerializer(device).data
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
    authentication_classes = [DeviceAPIKeyAuthentication]
    serializer_class = TransactionSerializer
    queryset = Transaction.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = TransactionFilter
    search_fields = ['tx_id', 'sender_name', 'sender_phone', 'notes']
    ordering_fields = '__all__'
    ordering = ['-timestamp']  # Default: newest first

class TransactionDetailView(generics.RetrieveUpdateAPIView):
    authentication_classes = [DeviceAPIKeyAuthentication]
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication])
def gateway_list(request):
    """
    Get list of all active payment gateways.

    Returns:
    - id, name, gateway_type, gateway_number for each gateway
    """
    gateways = PaymentGateway.objects.filter(is_active=True).values(
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
    authentication_classes = [DeviceAPIKeyAuthentication]

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
    authentication_classes = [DeviceAPIKeyAuthentication]
    serializer_class = ManualPaymentSerializer
    queryset = ManualPayment.objects.all().select_related('transaction')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ManualPaymentFilter
    search_fields = ['payer_name', 'reference_number', 'notes']
    ordering_fields = ['payment_date', 'created_at', 'amount', 'payer_name']
    ordering = ['-payment_date']


@api_view(['GET'])
@authentication_classes([DeviceAPIKeyAuthentication])
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
@authentication_classes([DeviceAPIKeyAuthentication])
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
@authentication_classes([DeviceAPIKeyAuthentication])
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
@authentication_classes([DeviceAPIKeyAuthentication])
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
@authentication_classes([DeviceAPIKeyAuthentication])
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
@authentication_classes([DeviceAPIKeyAuthentication])
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
@authentication_classes([DeviceAPIKeyAuthentication])
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
@authentication_classes([DeviceAPIKeyAuthentication])
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

class ProductCategoryListView(generics.ListCreateAPIView):
    """
    List and create product categories.
    
    GET: List all categories
    POST: Create new category
    """
    authentication_classes = [DeviceAPIKeyAuthentication]
    queryset = ProductCategory.objects.all().prefetch_related('subcategories', 'products')
    serializer_class = ProductCategorySerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']


class ProductCategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a product category.
    
    GET: Get category details
    PUT/PATCH: Update category
    DELETE: Delete category (only if no products assigned)
    """
    authentication_classes = [DeviceAPIKeyAuthentication]
    queryset = ProductCategory.objects.all().prefetch_related('subcategories', 'products')
    serializer_class = ProductCategorySerializer


class ProductListView(generics.ListCreateAPIView):
    """
    List and create products.
    
    GET: List all products with search and filtering
    POST: Create new product
    
    Search fields:
    - prod_code, prod_name, sku, sku_name
    
    Filters:
    - is_active: Boolean (true/false)
    - category: Category ID
    """
    authentication_classes = [DeviceAPIKeyAuthentication]
    queryset = Product.objects.all().select_related('category')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['prod_code', 'prod_name', 'sku', 'sku_name']
    filterset_fields = ['is_active', 'category']
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
    queryset = Product.objects.all().select_related('category')
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


# ============================================================================
# Transaction Fulfillment API Views
# ============================================================================

@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication])
def activate_transaction_issuance(request, transaction_id):
    """
    Activate issuance mode for a transaction.

    This prepares the transaction for product scanning.
    Only one transaction can be in issuance at a time.
    """
    from payments.services.fulfillment_service import FulfillmentService
    from django.core.exceptions import ValidationError

    try:
        result = FulfillmentService.activate_issuance(transaction_id)
        return Response(result, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response({'error': e.message_dict}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error activating issuance for transaction {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication])
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
            scanned_by=serializer.validated_data.get('scanned_by', 'System')
        )
        return Response(result, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response({'error': e.message_dict}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error scanning barcode for transaction {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication])
def complete_transaction_issuance(request, transaction_id):
    """
    Complete the issuance and update inventory.

    This finalizes the transaction and deducts scanned products from inventory.
    Creates InventoryMovement records for audit trail.

    Request body:
    {
        "performed_by": "User"  // Who completed the issuance (optional)
    }
    """
    from payments.services.fulfillment_service import FulfillmentService
    from payments.serializers import IssuanceCompleteSerializer
    from django.core.exceptions import ValidationError

    serializer = IssuanceCompleteSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    try:
        result = FulfillmentService.complete_issuance(
            transaction_id,
            performed_by=serializer.validated_data.get('performed_by', 'System')
        )
        return Response(result, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response({'error': e.message_dict}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error completing issuance for transaction {transaction_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeviceAPIKeyAuthentication])
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
@authentication_classes([DeviceAPIKeyAuthentication])
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
