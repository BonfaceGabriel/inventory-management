from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from payments.auth import BiAgentAuthentication
from payments.services.agent_revenue_service import AgentRevenueService
from payments.services.agent_sales_service import AgentSalesService, IncompleteFulfillmentHistory


class AgentDateRangeSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, attrs):
        start, end = attrs["start_date"], attrs["end_date"]
        if end < start:
            raise serializers.ValidationError("end_date must be on or after start_date")
        if (end - start).days >= 366:
            raise serializers.ValidationError("Request at most 366 days at a time")
        if end > timezone.localdate():
            raise serializers.ValidationError("Future reporting dates are not available")
        return attrs


@api_view(["GET"])
@authentication_classes([BiAgentAuthentication])
@permission_classes([IsAuthenticated])
def agent_revenue(request):
    query = AgentDateRangeSerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    response = Response(AgentRevenueService.get_revenue(**query.validated_data))
    response["Cache-Control"] = "no-store"
    return response


@api_view(["GET"])
@authentication_classes([BiAgentAuthentication])
@permission_classes([IsAuthenticated])
def agent_sales(request):
    query = AgentDateRangeSerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    try:
        response = Response(AgentSalesService.get_sales(**query.validated_data))
    except IncompleteFulfillmentHistory:
        response = Response(
            {"code": "incomplete_fulfillment_history"}, status=status.HTTP_409_CONFLICT
        )
    response["Cache-Control"] = "no-store"
    return response
