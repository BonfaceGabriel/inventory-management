"""
WebSocket URL routing for payments app.

Defines WebSocket endpoints for real-time updates.
"""
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'^ws/transactions/$', consumers.TransactionConsumer.as_asgi()),
]
