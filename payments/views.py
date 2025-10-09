from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics, filters
from django_filters.rest_framework import DjangoFilterBackend
from .serializers import DeviceRegisterSerializer, DeviceResponseSerializer, RawMessageSerializer, TransactionSerializer
from .models import Device, Transaction
from .filters import TransactionFilter
from django.contrib.auth.hashers import make_password
import secrets
from .auth import DeviceAPIKeyAuthentication
from .tasks import process_raw_message

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
            message = serializer.save(device=request.user)
            process_raw_message.delay(message.id)
            return Response({"message_id": message.id, "status": "queued"}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class RotateAPIKeyView(APIView):
    authentication_classes = [DeviceAPIKeyAuthentication]

    def patch(self, request, *args, **kwargs):
        device = request.user
        plain_api_key = secrets.token_urlsafe(32)
        device.api_key = make_password(plain_api_key)
        device.save()
        return Response({'api_key': plain_api_key})

class TransactionListView(generics.ListAPIView):
    authentication_classes = [DeviceAPIKeyAuthentication]
    serializer_class = TransactionSerializer
    queryset = Transaction.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = TransactionFilter
    search_fields = ['tx_id', 'notes']
    ordering_fields = '__all__'

class TransactionDetailView(generics.RetrieveUpdateAPIView):
    authentication_classes = [DeviceAPIKeyAuthentication]
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer