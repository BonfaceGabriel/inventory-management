from django_filters import rest_framework as filters
from .models import Transaction

class TransactionFilter(filters.FilterSet):
    min_date = filters.DateTimeFilter(field_name="timestamp", lookup_expr='gte')
    max_date = filters.DateTimeFilter(field_name="timestamp", lookup_expr='lte')
    min_amount = filters.NumberFilter(field_name="amount", lookup_expr='gte')
    max_amount = filters.NumberFilter(field_name="amount", lookup_expr='lte')
    device = filters.CharFilter(field_name='raw_messages__device__name')
    gateway = filters.CharFilter(field_name='gateway_type')

    class Meta:
        model = Transaction
        fields = ['tx_id', 'status', 'timestamp', 'amount', 'min_date', 'max_date', 'min_amount', 'max_amount', 'device', 'gateway']
