"""
ASGI config for management project.

It exposes the ASGI callable as a module-level variable named ``application``.

Supports both HTTP and WebSocket protocols for real-time updates.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'management.settings')

# Initialize Django ASGI application early to populate Django apps
django_asgi_app = get_asgi_application()

# Import routing after Django setup
from channels.routing import ProtocolTypeRouter, URLRouter
from payments.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": URLRouter(
        websocket_urlpatterns
    ),
})
