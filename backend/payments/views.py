from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics, filters
from rest_framework.decorators import api_view, authentication_classes
from django_filters.rest_framework import DjangoFilterBackend
from .serializers import (
    DeviceRegisterSerializer, DeviceResponseSerializer, RawMessageSerializer,
    TransactionSerializer, ManualPaymentSerializer, ManualPaymentCreateSerializer
)
from .models import Device, Transaction, ManualPayment
from .filters import TransactionFilter, ManualPaymentFilter
from django.contrib.auth.hashers import make_password
import secrets
from .auth import DeviceAPIKeyAuthentication
from .tasks import process_raw_message
from .services import ManualPaymentService
from .services.reconciliation_service import ReconciliationService
from .services.pdf_report_service import PDFReportService
from django.utils.dateparse import parse_date
from django.http import HttpResponse

class DeviceRegisterView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = DeviceRegisterSerializer(data=request.data)
        if serializer.is_valid():
            device = Device(**serializer.validated_data)
            plain_api_key = secrets.token_urlsafe(32)
            device.api_key = make_password(plain_api_key)
            device.save()
            response_data = DeviceResponseSerializer(device).data
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