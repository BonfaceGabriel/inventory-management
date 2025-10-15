from django_filters import rest_framework as filters
from django.db.models import Q
from .models import Transaction, ManualPayment


class TransactionFilter(filters.FilterSet):
    """
    Enhanced transaction filtering with multiple options.

    Available filters:
    - Date range: min_date, max_date, created_after, created_before
    - Amount range: min_amount, max_amount, min_remaining, max_remaining
    - Amount expected range: min_expected_amount, max_expected_amount
    - Status filters: status, is_locked, is_available
    - Text search: tx_id, sender_name, sender_phone, notes_contains
    - Gateway filters: gateway_type, is_manual_payment
    - Confidence range: min_confidence, max_confidence
    """

    # Date filters
    min_date = filters.DateTimeFilter(
        field_name="timestamp",
        lookup_expr='gte',
        help_text="Minimum transaction timestamp"
    )
    max_date = filters.DateTimeFilter(
        field_name="timestamp",
        lookup_expr='lte',
        help_text="Maximum transaction timestamp"
    )
    exact_time = filters.DateTimeFilter(
        field_name="timestamp",
        lookup_expr='exact',
        help_text="Exact transaction timestamp"
    )
    created_after = filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr='gte',
        help_text="Created after this date"
    )
    created_before = filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr='lte',
        help_text="Created before this date"
    )

    # Amount filters
    min_amount = filters.NumberFilter(
        field_name="amount",
        lookup_expr='gte',
        help_text="Minimum transaction amount"
    )
    max_amount = filters.NumberFilter(
        field_name="amount",
        lookup_expr='lte',
        help_text="Maximum transaction amount"
    )
    min_expected_amount = filters.NumberFilter(
        field_name="amount_expected",
        lookup_expr='gte',
        help_text="Minimum expected amount"
    )
    max_expected_amount = filters.NumberFilter(
        field_name="amount_expected",
        lookup_expr='lte',
        help_text="Maximum expected amount"
    )

    # Confidence filter
    min_confidence = filters.NumberFilter(
        field_name="confidence",
        lookup_expr='gte',
        help_text="Minimum confidence score (0.0 to 1.0)"
    )
    max_confidence = filters.NumberFilter(
        field_name="confidence",
        lookup_expr='lte',
        help_text="Maximum confidence score (0.0 to 1.0)"
    )

    # Text search filters
    sender_name = filters.CharFilter(
        field_name="sender_name",
        lookup_expr='icontains',
        help_text="Search sender name (case-insensitive)"
    )
    sender_phone = filters.CharFilter(
        field_name="sender_phone",
        lookup_expr='icontains',
        help_text="Search sender phone number"
    )
    notes_contains = filters.CharFilter(
        field_name="notes",
        lookup_expr='icontains',
        help_text="Search in notes (case-insensitive)"
    )

    # Gateway filters
    gateway_type = filters.CharFilter(
        field_name='gateway_type',
        lookup_expr='iexact',
        help_text="Filter by gateway type"
    )
    is_manual_payment = filters.BooleanFilter(
        method='filter_manual_payment',
        help_text="Filter manual payments (true/false)"
    )

    # Status and availability filters
    is_locked = filters.BooleanFilter(
        method='filter_locked',
        help_text="Filter locked transactions (FULFILLED or CANCELLED)"
    )
    is_available = filters.BooleanFilter(
        method='filter_available',
        help_text="Filter available transactions (has remaining amount)"
    )

    # Legacy filters (for backwards compatibility)
    device = filters.CharFilter(
        field_name='raw_messages__device__name',
        help_text="Filter by device name"
    )
    gateway = filters.CharFilter(
        field_name='gateway_type',
        help_text="Filter by gateway (deprecated, use gateway_type)"
    )

    class Meta:
        model = Transaction
        fields = [
            'tx_id', 'status', 'timestamp', 'amount',
            'min_date', 'max_date', 'exact_time', 'created_after', 'created_before',
            'min_amount', 'max_amount', 'min_expected_amount', 'max_expected_amount',
            'min_confidence', 'max_confidence',
            'sender_name', 'sender_phone', 'notes_contains',
            'gateway_type', 'is_manual_payment',
            'is_locked', 'is_available',
            'device', 'gateway'
        ]

    def filter_locked(self, queryset, name, value):
        """
        Filter transactions by locked status.

        Locked transactions are FULFILLED or CANCELLED.
        """
        if value is True:
            return queryset.filter(
                status__in=[
                    Transaction.OrderStatus.FULFILLED,
                    Transaction.OrderStatus.CANCELLED
                ]
            )
        elif value is False:
            return queryset.exclude(
                status__in=[
                    Transaction.OrderStatus.FULFILLED,
                    Transaction.OrderStatus.CANCELLED
                ]
            )
        return queryset

    def filter_available(self, queryset, name, value):
        """
        Filter transactions by availability.

        Available transactions:
        - Not locked (FULFILLED or CANCELLED)
        - Have remaining amount > 0
        """
        from django.db.models import F

        if value is True:
            # Not locked AND has remaining amount
            return queryset.exclude(
                status__in=[
                    Transaction.OrderStatus.FULFILLED,
                    Transaction.OrderStatus.CANCELLED
                ]
            ).filter(
                amount_paid__lt=F('amount_expected')
            )
        elif value is False:
            # Locked OR no remaining amount
            return queryset.filter(
                Q(status__in=[
                    Transaction.OrderStatus.FULFILLED,
                    Transaction.OrderStatus.CANCELLED
                ]) | Q(amount_paid__gte=F('amount_expected'))
            )
        return queryset

    def filter_manual_payment(self, queryset, name, value):
        """
        Filter manual payment transactions.

        Manual payments have gateway_type starting with 'MANUAL_'.
        """
        if value is True:
            return queryset.filter(gateway_type__istartswith='MANUAL_')
        elif value is False:
            return queryset.exclude(gateway_type__istartswith='MANUAL_')
        return queryset


class ManualPaymentFilter(filters.FilterSet):
    """
    Filters for manual payment entries.

    Available filters:
    - Date range: payment_date_after, payment_date_before
    - Amount range: min_amount, max_amount
    - Payment method filters
    - Creator filters
    - Text search
    """

    # Date filters
    payment_date_after = filters.DateTimeFilter(
        field_name="payment_date",
        lookup_expr='gte',
        help_text="Payment date after this date"
    )
    payment_date_before = filters.DateTimeFilter(
        field_name="payment_date",
        lookup_expr='lte',
        help_text="Payment date before this date"
    )
    created_after = filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr='gte',
        help_text="Created after this date"
    )
    created_before = filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr='lte',
        help_text="Created before this date"
    )

    # Amount filters
    min_amount = filters.NumberFilter(
        field_name="amount",
        lookup_expr='gte',
        help_text="Minimum payment amount"
    )
    max_amount = filters.NumberFilter(
        field_name="amount",
        lookup_expr='lte',
        help_text="Maximum payment amount"
    )

    # Text search filters
    payer_name = filters.CharFilter(
        field_name="payer_name",
        lookup_expr='icontains',
        help_text="Search payer name (case-insensitive)"
    )
    reference_number = filters.CharFilter(
        field_name="reference_number",
        lookup_expr='icontains',
        help_text="Search reference number"
    )
    notes_contains = filters.CharFilter(
        field_name="notes",
        lookup_expr='icontains',
        help_text="Search in notes (case-insensitive)"
    )

    class Meta:
        model = ManualPayment
        fields = [
            'payment_method', 'created_by',
            'payment_date_after', 'payment_date_before',
            'created_after', 'created_before',
            'min_amount', 'max_amount',
            'payer_name', 'reference_number', 'notes_contains'
        ]
