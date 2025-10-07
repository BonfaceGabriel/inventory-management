from django.urls import path
from .views import DeviceRegisterView, MessageIngestView, RotateAPIKeyView

urlpatterns = [
    path('devices/register/', DeviceRegisterView.as_view(), name='device-register'),
    path('devices/<uuid:id>/rotate_key/', RotateAPIKeyView.as_view(), name='device-rotate-key'),
    path('messages/', MessageIngestView.as_view(), name='message-ingest'),
]
