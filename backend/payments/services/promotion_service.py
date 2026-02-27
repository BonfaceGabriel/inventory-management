"""
Promotion Service

Checks active promotions against line items and adjusts scanned_price
to reflect bundle discounts.

Called after every scan and every line item removal.

Design:
- Promotions trigger when ALL required products have sufficient AVAILABLE quantities
- A product unit is "available" once per order; once consumed by a promotion bundle
  it cannot be used by another promotion (or a second instance of the same promotion)
- bundle_count = floor(available_qty / min_qty) — each complete bundle earns one discount
- Fixed discount: KES amount × bundle_count
- Percentage discount: % off the cost of the units actually in the promo (scales naturally)
- Discount distributed proportionally across each product's share of the promo bundle total
- Units not part of any complete bundle stay at cost_price
- When a product spans multiple promotions, its discounts accumulate; a weighted-average
  scanned_price is written once at the end (no intermediate saves)
- Only operates on items with is_inventory_deducted=False (not yet completed)
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
        Evaluate and apply promotions on a set of line items.

        Pass 1 — loop every active promotion:
          - Track available_qty per product (units consumed by earlier promos are unavailable)
          - Compute bundle_count = min(avail_qty // min_qty) across all required products
          - Accumulate total_discount and discounted_units per product

        Pass 2 — single write per line item:
          - Products with accumulated discount → weighted-average scanned_price
            = (cost_price × total_qty - total_discount) / total_qty
          - All other non-deducted items → revert to cost_price

        Args:
            line_items_qs: QuerySet of TransactionLineItem or CombinedOrderLineItem

        Returns:
            list of dicts describing applied promotions, e.g.:
            [{'promotion_name': '...', 'discount_applied': '702.00', 'bundle_count': 2}]
        """
        active_promotions = PromotionService.get_active_promotions()
        applied = []

        # Collect all non-deducted line items once
        all_non_deducted = list(
            line_items_qs.filter(is_inventory_deducted=False).select_related('product')
        )

        # available_qty[product_id] = total non-deducted qty still available for promotions.
        # Decremented as each qualifying promotion consumes units.
        available_qty = {}
        for item in all_non_deducted:
            available_qty[item.product_id] = (
                available_qty.get(item.product_id, 0) + item.quantity
            )

        # accumulated per product across all qualifying promotions:
        #   total_discount    — KES deducted from this product's units
        #   discounted_units  — how many units carry a discount
        product_discount_acc = {}  # product_id -> {'product', 'total_discount', 'discounted_units'}

        # --- Pass 1: process promotions ---
        for promo in active_promotions:
            promo_products = list(promo.promotion_products.all())
            if not promo_products:
                continue

            # Build per-product info using available (not yet consumed) qty
            items_by_product = {}
            for pp in promo_products:
                product = pp.product
                items_by_product[product.id] = {
                    'product': product,
                    'min_qty': pp.min_quantity,
                    'avail_qty': available_qty.get(product.id, 0),
                }

            # Promotion only fires if every required product has enough available units
            qualifies = all(
                data['avail_qty'] >= data['min_qty']
                for data in items_by_product.values()
            )
            if not qualifies:
                continue

            # How many complete bundles can be formed?
            bundle_count = min(
                data['avail_qty'] // data['min_qty']
                for data in items_by_product.values()
            )

            # Units of each product consumed by this promotion
            for data in items_by_product.values():
                data['units_in_promo'] = data['min_qty'] * bundle_count

            # Consume those units so subsequent promotions cannot reuse them
            for data in items_by_product.values():
                available_qty[data['product'].id] -= data['units_in_promo']

            # Bundle total is the cost of only the units participating in this promo
            bundle_total = sum(
                data['product'].cost_price * data['units_in_promo']
                for data in items_by_product.values()
            )

            # Discount amount for this promo
            if promo.discount_type == Promotion.DiscountType.FIXED:
                # Each complete bundle earns one fixed discount
                discount_amount = promo.discount_value * bundle_count
            else:  # PERCENTAGE
                # Applied to bundle_total which already covers all units_in_promo
                discount_amount = (
                    bundle_total * promo.discount_value / Decimal('100')
                ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            # Safety: discount cannot exceed the value of the participating units
            discount_amount = min(discount_amount, bundle_total)

            total_discount_applied = Decimal('0.00')

            for data in items_by_product.values():
                product = data['product']
                units_in_promo = data['units_in_promo']

                if bundle_total > Decimal('0.00') and units_in_promo > 0:
                    # Proportional share of the discount for this product
                    product_bundle_value = product.cost_price * units_in_promo
                    product_discount = (
                        discount_amount * product_bundle_value / bundle_total
                    ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                else:
                    product_discount = Decimal('0.00')

                # Accumulate across all promotions for this product
                if product.id not in product_discount_acc:
                    product_discount_acc[product.id] = {
                        'product': product,
                        'total_discount': Decimal('0.00'),
                        'discounted_units': 0,
                    }
                product_discount_acc[product.id]['total_discount'] += product_discount
                product_discount_acc[product.id]['discounted_units'] += units_in_promo

                total_discount_applied += product_discount

            logger.info(
                f"Promotion '{promo.name}' applied. "
                f"Bundles: {bundle_count}, Discount: {total_discount_applied} KES"
            )
            applied.append({
                'promotion_name': promo.name,
                'discount_applied': str(total_discount_applied),
                'discount_type': promo.discount_type,
                'discount_value': str(promo.discount_value),
                'bundle_count': bundle_count,
            })

        # --- Pass 2: write final prices ---
        # Each non-deducted line item gets one save with the correct price.
        # Products with accumulated discounts get a weighted-average price so that:
        #   scanned_price × total_qty = (discounted units at their price) + (full-price units)
        for item in all_non_deducted:
            product = item.product

            if item.product_id in product_discount_acc:
                acc = product_discount_acc[item.product_id]
                total_discount = acc['total_discount']
                # Weighted avg: spread the total discount across all units in the line item
                avg_price = (
                    (product.cost_price * item.quantity - total_discount) / item.quantity
                ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                new_price = max(avg_price, Decimal('0.00'))
            else:
                new_price = product.cost_price

            if item.scanned_price != new_price:
                item.scanned_price = new_price
                item.save()

        return applied
