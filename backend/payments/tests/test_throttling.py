"""Regression guard: operational product/fulfillment/stock-take endpoints must not be throttled."""
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from payments import views


FUNCTION_VIEW_NAMES = [
    # products
    'product_summary',
    'product_search_by_sku',
    # fulfillment
    'activate_transaction_issuance',
    'scan_product_barcode',
    'complete_transaction_issuance',
    'cancel_transaction_issuance',
    'get_current_issuance',
    # stock take sessions
    'stock_take_create_session',
    'stock_take_list_active_sessions',
    'stock_take_session_detail',
    'stock_take_scan_product',
    'stock_take_scan_bulk',
    'stock_take_complete_session',
    'stock_take_cancel_session',
    'stock_take_remove_item',
    'stock_take_update_item_quantity',
    'stock_take_update_kit_quantity',
    'stock_take_cancel_all_active',
]

CLASS_VIEWS = [
    views.ProductListView,
    views.ProductDetailView,
    views.ProductLineListView,
    views.ProductLineDetailView,
]


class ThrottleExemptionTest(TestCase):
    @staticmethod
    def _resolved_throttle_classes(view):
        """DRF's @api_view stores decorators on the wrapped view class (view.cls), not the function."""
        wrapped_cls = getattr(view, 'cls', None)
        if wrapped_cls is not None and hasattr(wrapped_cls, 'throttle_classes'):
            return wrapped_cls.throttle_classes
        return getattr(view, 'throttle_classes', None)

    def test_function_views_are_not_throttled(self):
        for name in FUNCTION_VIEW_NAMES:
            view = getattr(views, name)
            self.assertEqual(
                self._resolved_throttle_classes(view),
                [],
                f"{name} should be decorated with @throttle_classes([])",
            )

    def test_class_views_are_not_throttled(self):
        for view_cls in CLASS_VIEWS:
            view_instance = view_cls()
            view_instance.request = APIRequestFactory().get('/')
            self.assertEqual(
                view_instance.throttle_classes,
                [],
                f"{view_cls.__name__} should define throttle_classes = []",
            )
