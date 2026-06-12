from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .auth import InventoryAPIAuthentication
from .serializers import (
    BranchInfoSerializer,
    ProductWithStockSerializer,
    StockLevelSerializer,
)
from .services import inventory_aggregation_service as svc


# ─── Branch-Level Endpoints (deployed on EVERY instance) ────────────────────

@api_view(['GET'])
@authentication_classes([InventoryAPIAuthentication])
@permission_classes([IsAuthenticated])
def branch_products_list(request):
    """Return this branch's full product catalog with local stock."""
    products = svc.get_local_products()
    serializer = ProductWithStockSerializer(products, many=True, context={'request': request})
    return Response({
        'branch': svc.get_local_branch_info(),
        'products': serializer.data,
    })


@api_view(['GET'])
@authentication_classes([InventoryAPIAuthentication])
@permission_classes([IsAuthenticated])
def branch_product_detail(request, code):
    """Return a single product with this branch's stock."""
    product = svc.get_local_product_by_code(code)
    if product is None:
        return Response(
            {'error': 'Product not found'},
            status=status.HTTP_404_NOT_FOUND,
        )
    serializer = ProductWithStockSerializer(product, context={'request': request})
    return Response(serializer.data)


# ─── Aggregation Endpoints (on MAIN instance) ───────────────────────────────

@api_view(['GET'])
@authentication_classes([InventoryAPIAuthentication])
@permission_classes([IsAuthenticated])
def inventory_products_list(request):
    """Return aggregated product catalog with stock per branch.

    Supports ?category={name} query parameter for filtering.
    """
    category = request.query_params.get('category')
    use_cache = request.query_params.get('refresh', '').lower() != 'true'

    if category:
        products = svc.get_aggregated_products_by_category(category, use_cache=use_cache)
    else:
        products = svc.get_aggregated_products(use_cache=use_cache)

    serializer = ProductWithStockSerializer(products, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([InventoryAPIAuthentication])
@permission_classes([IsAuthenticated])
def inventory_product_detail(request, code):
    """Return a single product aggregated across all branches."""
    use_cache = request.query_params.get('refresh', '').lower() != 'true'
    product = svc.get_aggregated_product_by_code(code, use_cache=use_cache)
    if product is None:
        return Response(
            {'error': 'Product not found'},
            status=status.HTTP_404_NOT_FOUND,
        )
    serializer = ProductWithStockSerializer(product, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([InventoryAPIAuthentication])
@permission_classes([IsAuthenticated])
def inventory_branches_list(request):
    """Return list of all known branches."""
    use_cache = request.query_params.get('refresh', '').lower() != 'true'
    branches = svc.get_branches(use_cache=use_cache)
    serializer = BranchInfoSerializer(branches, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([InventoryAPIAuthentication])
@permission_classes([IsAuthenticated])
def inventory_stock_by_branch(request):
    """Return stock levels for all products at a specific branch.

    Query params:
        branch (str): The slugified branch ID (e.g. 'main-shop', 'kitengela')
    """
    branch_id = request.query_params.get('branch')
    if not branch_id:
        return Response(
            {'error': 'branch query parameter is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    use_cache = request.query_params.get('refresh', '').lower() != 'true'
    products = svc.get_aggregated_products(use_cache=use_cache)

    stock_levels = []
    for product in products:
        for stock_entry in product.get('stock', []):
            if stock_entry.get('branch_id') == branch_id:
                stock_levels.append(stock_entry)
                break

    serializer = StockLevelSerializer(stock_levels, many=True)
    return Response(serializer.data)
