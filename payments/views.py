from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import DeviceRegisterSerializer, DeviceResponseSerializer, RawMessageSerializer
from .models import Device
from django.contrib.auth.hashers import make_password
import secrets
from .auth import DeviceAPIKeyAuthentication

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
            serializer.save(device=request.user)
            return Response({"message_id": serializer.instance.id, "status": "queued"}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class RotateAPIKeyView(APIView):
    authentication_classes = [DeviceAPIKeyAuthentication]

    def patch(self, request, *args, **kwargs):
        device = request.user
        plain_api_key = secrets.token_urlsafe(32)
        device.api_key = make_password(plain_api_key)
        device.save()
        return Response({'api_key': plain_api_key})