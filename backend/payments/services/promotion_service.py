"""
Promotion Service

Checks active promotions against line items and adjusts scanned_price
to distribute bundle discounts proportionally.

Called after every scan and every line item removal.

Design:
- Promotions trigger when ALL required products have sufficient quantities
- Fixed discount: KES amount off the bundle total
- Percentage discount: % off the total cost_price of qualifying items
- Discount distributed proportionally across each product's share of bundle total
- Only adjusts items with is_inventory_deducted=False (not yet completed)
- Reverts prices when qualification is lost
"""

import logging
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from payments.models import Promotion, PromotionProduct

logger = logging.getLogger(__name__)


class PromotionService:

    @staticmethod
    def get_active_promotions():
        """Return all currently active promotions with their products prefetched."""
        now = timezone.now()
        return Promotion.objects.filter(
            is_active=True,
            start_date__lte=now,
            end_date__gte=now
        ).prefetch_related('promotion_products__product')

    @staticmethod
    def apply_promotions(line_items_qs):
        """
        Evaluate and apply/revert promotions on a set of line items.

        Operates on non-deducted line items only (is_inventory_deducted=False).
        Promotions trigger when ALL required products meet their min_quantity.
        Discount is distributed proportionally by each product's share of bundle total.

        Args:
            line_items_qs: QuerySet of TransactionLineItem or CombinedOrderLineItem

        Returns:
            list of dicts describing applied promotions, e.g.:
            [{'promotion_name': '...', 'discount_applied': '810.00'}]
        """
        active_promotions = PromotionService.get_active_promotions()
        applied = []

        # Track which products are covered by at least one qualifying promotion
        # so we can revert products that are no longer covered
        products_with_active_promo = set()

        for promo in active_promotions:
            promo_products = list(promo.promotion_products.all())

            if not promo_products:
                continue

            # Gather non-deducted line items for each required product
            items_by_product = {}
            for pp in promo_products:
                product = pp.product
                items = list(
                    line_items_qs.filter(
                        product=product,
                        is_inventory_deducted=False
                    )
                )
                total_qty = sum(item.quantity for item in items)
                items_by_product[product.id] = {
                    'product': product,
                    'min_qty': pp.min_quantity,
                    'items': items,
                    'total_qty': total_qty,
                }

            # Check if ALL required products qualify
            qualifies = all(
                data['total_qty'] >= data['min_qty']
                for data in items_by_product.values()
            )

            if qualifies:
                # Calculate total bundle cost (sum of cost_price * qty per qualifying product)
                bundle_total = Decimal('0.00')
                for data in items_by_product.values():
                    bundle_total += data['product'].cost_price * data['total_qty']

                # Calculate the discount amount
                if promo.discount_type == Promotion.DiscountType.FIXED:
                    discount_amount = promo.discount_value
                else:  # PERCENTAGE
                    discount_amount = (bundle_total * promo.discount_value / Decimal('100')).quantize(
                        Decimal('0.01'), rounding=ROUND_HALF_UP
                    )

                # Safety: discount cannot exceed bundle total
                discount_amount = min(discount_amount, bundle_total)

                total_discount_applied = Decimal('0.00')

                for data in items_by_product.values():
                    product = data['product']
                    products_with_active_promo.add(product.id)
                    items = data['items']
                    total_qty = data['total_qty']

                    if bundle_total > Decimal('0.00'):
                        product_bundle_value = product.cost_price * total_qty
                        # Proportional share of discount for this product
                        product_discount = (discount_amount * product_bundle_value / bundle_total).quantize(
                            Decimal('0.01'), rounding=ROUND_HALF_UP
                        )
                    else:
                        product_discount = Decimal('0.00')

                    # Discount per unit for this product
                    if total_qty > 0:
                        discount_per_unit = (product_discount / total_qty).quantize(
                            Decimal('0.01'), rounding=ROUND_HALF_UP
                        )
                    else:
                        discount_per_unit = Decimal('0.00')

                    new_price = max(product.cost_price - discount_per_unit, Decimal('0.00'))

                    for item in items:
                        if item.scanned_price != new_price:
                            item.scanned_price = new_price
                            item.save()

                    total_discount_applied += discount_per_unit * total_qty

                logger.info(
                    f"Promotion '{promo.name}' applied. "
                    f"Discount: {total_discount_applied} KES"
                )
                applied.append({
                    'promotion_name': promo.name,
                    'discount_applied': str(total_discount_applied),
                    'discount_type': promo.discount_type,
                    'discount_value': str(promo.discount_value),
                })

            else:
                # Promotion does not qualify — revert prices for these products
                for data in items_by_product.values():
                    product = data['product']
                    for item in data['items']:
                        if item.scanned_price != product.cost_price:
                            item.scanned_price = product.cost_price
                            item.save()

        # Revert any non-deducted items whose product is not covered by a qualifying promotion
        # (handles expired or deactivated promotions mid-session)
        for item in line_items_qs.filter(is_inventory_deducted=False).select_related('product'):
            if item.product_id not in products_with_active_promo:
                if item.scanned_price != item.product.cost_price:
                    item.scanned_price = item.product.cost_price
                    item.save()

        return applied
