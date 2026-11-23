from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers, status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from payments.auth import BiAgentAuthentication
from payments.services.agent_inventory_service import AgentInventoryService
from payments.services.agent_revenue_service import AgentRevenueService
from payments.services.agent_sales_service import AgentSalesService, IncompleteFulfillmentHistory
from payments.services.reconciliation_v2_service import ReconciliationV2Service


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


class AgentSalesRangeSerializer(AgentDateRangeSerializer):
    daily = serializers.BooleanField(required=False, default=False)


class AgentInventoryQuerySerializer(AgentDateRangeSerializer):
    view = serializers.ChoiceField(choices=("merchandise", "stock"))
    page = serializers.IntegerField(min_value=1, default=1)


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
    query = AgentSalesRangeSerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    try:
        response = Response(AgentSalesService.get_sales(**query.validated_data))
    except IncompleteFulfillmentHistory:
        response = Response(
            {"code": "incomplete_fulfillment_history"}, status=status.HTTP_409_CONFLICT
        )
    response["Cache-Control"] = "no-store"
    return response


@api_view(["GET"])
@authentication_classes([BiAgentAuthentication])
@permission_classes([IsAuthenticated])
def agent_products(request):
    query = AgentDateRangeSerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    try:
        response = Response(AgentSalesService.get_products(**query.validated_data))
    except IncompleteFulfillmentHistory:
        response = Response({"code": "incomplete_fulfillment_history"}, status=status.HTTP_409_CONFLICT)
    response["Cache-Control"] = "no-store"
    return response


@api_view(["GET"])
@authentication_classes([BiAgentAuthentication])
@permission_classes([IsAuthenticated])
def agent_reconciliation(request):
    query = AgentDateRangeSerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    day = query.validated_data["start_date"]
    if day != query.validated_data["end_date"]:
        raise serializers.ValidationError("Reconciliation requires one reporting date")

    report = ReconciliationV2Service.generate_daily_report(day, decimal_totals=True)
    response = Response({
        "schema_version": 1,
        "branch": {"id": slugify(settings.BRANCH_NAME), "name": settings.BRANCH_NAME},
        "start_date": day.isoformat(),
        "end_date": day.isoformat(),
        "timezone": "Africa/Nairobi",
        "currency": "KES",
        "generated_at": report["generated_at"],
        "is_provisional": day == timezone.localdate(),
        "x_value": format(report["x_value"], ".2f"),
        "y_value": format(report["y_value"], ".2f"),
        "result": format(report["result"], ".2f"),
        "is_balanced": report["is_balanced"],
    })
    response["Cache-Control"] = "no-store"
    return response


@api_view(["GET"])
@authentication_classes([BiAgentAuthentication])
@permission_classes([IsAuthenticated])
def agent_inventory(request):
    query = AgentInventoryQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    params = query.validated_data
    if params["view"] == "stock":
        today = timezone.localdate()
        if params["start_date"] != today or params["end_date"] != today:
            raise serializers.ValidationError("Stock is a current snapshot")
        data = AgentInventoryService.get_stock(page=params["page"])
    else:
        data = AgentInventoryService.get_merchandise(params["start_date"], params["end_date"], page=params["page"])
    response = Response(data)
    response["Cache-Control"] = "no-store"
    return response
