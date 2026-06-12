import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.conf import settings
from django.core.cache import cache
import requests

logger = logging.getLogger(__name__)

CACHE_KEY_PRODUCTS = 'inventory:products'
CACHE_KEY_BRANCHES = 'inventory:branches'
CACHE_TTL = 60  # seconds


def _slugify_branch_name(name):
    return name.lower().replace(' ', '-')


def _build_branch_stock(product, branch_id, branch_name, quantity):
    return {
        'branch_id': branch_id,
        'branch_name': branch_name,
        'quantity': quantity,
        'in_stock': quantity > 0,
    }


def _serialize_product(product, stock_entries):
    return {
        'prod_code': product.prod_code,
        'prod_name': product.prod_name,
        'category_name': product.product_line.name if product.product_line else None,
        'description': product.description or None,
        'image_url': product.image_url or None,
        'image': product.image.url if product.image else None,
        'stock': stock_entries,
    }


def get_local_branch_info():
    """Return this instance's branch info from settings."""
    name = getattr(settings, 'BRANCH_NAME', 'Main Shop')
    return {
        'id': _slugify_branch_name(name),
        'name': name,
    }


def get_local_products():
    """Return products with stock for this local branch."""
    from payments.models import Product, ProductLine

    branch = get_local_branch_info()
    excluded_lines = ProductLine.objects.filter(name__iexact='registration')
    excluded_line_ids = list(excluded_lines.values_list('id', flat=True))

    products = Product.objects.filter(
        is_active=True,
    ).exclude(
        product_line_id__in=excluded_line_ids,
    ).exclude(
        product_line__isnull=True,
    ).select_related('product_line')

    result = []
    for product in products:
        stock_entry = _build_branch_stock(
            product, branch['id'], branch['name'], product.quantity
        )
        result.append(_serialize_product(product, [stock_entry]))
    return result


def get_local_product_by_code(code):
    """Return a single product with stock for this local branch."""
    from payments.models import Product, ProductLine

    branch = get_local_branch_info()
    excluded_lines = ProductLine.objects.filter(name__iexact='registration')
    excluded_line_ids = list(excluded_lines.values_list('id', flat=True))

    try:
        product = Product.objects.filter(
            prod_code=code,
            is_active=True,
        ).exclude(
            product_line_id__in=excluded_line_ids,
        ).exclude(
            product_line__isnull=True,
        ).select_related('product_line').get()
    except Product.DoesNotExist:
        return None

    stock_entry = _build_branch_stock(
        product, branch['id'], branch['name'], product.quantity
    )
    return _serialize_product(product, [stock_entry])


def _fetch_branch_products(target_url, api_key, timeout=5):
    """Fetch products from a target branch instance."""
    try:
        url = target_url.rstrip('/') + '/api/v1/inventory/branch-products/'
        resp = requests.get(
            url,
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get('products', [])
        else:
            logger.warning(
                f"Inventory aggregation: {target_url} returned {resp.status_code}"
            )
            return []
    except requests.RequestException as e:
        logger.error(f"Inventory aggregation: failed to fetch {target_url}: {e}")
        return []


def _merge_products(local_products, remote_products_list):
    """Merge products from multiple branches by product code."""
    merged = {}
    for product in local_products:
        merged[product['prod_code']] = product

    for remote_list in remote_products_list:
        for product in remote_list:
            code = product['prod_code']
            if code in merged:
                merged[code]['stock'].extend(product['stock'])
            else:
                merged[code] = product

    return list(merged.values())


def _get_target_branches():
    """Return list of target branch configs from settings."""
    return getattr(settings, 'PAYMENT_RELAY_TARGETS', [])


def get_aggregated_products(use_cache=True):
    """Fetch and merge products from all branches with Redis caching."""
    if use_cache:
        cached = cache.get(CACHE_KEY_PRODUCTS)
        if cached is not None:
            return cached

    api_key = getattr(settings, 'VITE_INVENTORY_API_KEY', '')
    local = get_local_products()

    targets = _get_target_branches()
    remote_results = []
    if targets and api_key:
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(
                    _fetch_branch_products, target['url'], api_key
                ): target['name']
                for target in targets
            }
            for future in as_completed(futures):
                result = future.result()
                if result:
                    remote_results.append(result)

    merged = _merge_products(local, remote_results)

    if use_cache:
        cache.set(CACHE_KEY_PRODUCTS, merged, CACHE_TTL)

    return merged


def get_aggregated_product_by_code(code, use_cache=True):
    """Fetch a single product aggregated across all branches."""
    products = get_aggregated_products(use_cache=use_cache)
    for product in products:
        if product['prod_code'] == code:
            return product
    return None


def get_aggregated_products_by_category(category_name, use_cache=True):
    """Filter aggregated products by category name."""
    products = get_aggregated_products(use_cache=use_cache)
    return [
        p for p in products
        if p.get('category_name') and p['category_name'].lower() == category_name.lower()
    ]


def get_branches(use_cache=True):
    """Return list of all known branches (self + targets)."""
    if use_cache:
        cached = cache.get(CACHE_KEY_BRANCHES)
        if cached is not None:
            return cached

    local = get_local_branch_info()
    branches = [local]

    for target in _get_target_branches():
        branches.append({
            'id': _slugify_branch_name(target['name']),
            'name': target['name'],
        })

    if use_cache:
        cache.set(CACHE_KEY_BRANCHES, branches, CACHE_TTL)

    return branches
