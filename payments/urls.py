from django.urls import path
from .views import DeviceRegisterView, MessageIngestView, RotateAPIKeyView, TransactionListView, TransactionDetailView

urlpatterns = [
    path('devices/register/', DeviceRegisterView.as_view(), name='device-register'),
    path('messages/', MessageIngestView.as_view(), name='message-ingest'),
    path('devices/<uuid:id>/rotate_key/', RotateAPIKeyView.as_view(), name='device-rotate-key'),
    path('transactions/', TransactionListView.as_view(), name='transaction-list'),
    path('transactions/<int:pk>/', TransactionDetailView.as_view(), name='transaction-detail'),
]
