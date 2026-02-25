"""
Diagnostic command to expose exactly what is driving the expected consignment
and sales figures in the stock report.

Shows for each product (or a single product with --sku):
  - Raw TransactionLineItems counted as sales (and those excluded)
  - Raw CombinedOrderLineItems counted as sales
  - Per-day sales breakdown used in expected_consignment accumulation
  - The start_date logic (last replenishment / first reconciliation)
  - Final expected_consignment vs today's sales

Usage:
    docker-compose exec web python manage.py diagnose_stock_report
    docker-compose exec web python manage.py diagnose_stock_report --date 2026-02-25
    docker-compose exec web python manage.py diagnose_stock_report --sku PROD001
    docker-compose exec web python manage.py diagnose_stock_report --sku PROD001 --date 2026-02-25
    docker-compose exec web python manage.py diagnose_stock_report --all-products
"""

from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from payments.models import (
    CombinedOrderLineItem,
    DailyStockReconciliation,
    Product,
    StockAdjustmentItem,
    Transaction,
    TransactionLineItem,
)


class Command(BaseCommand):
    help = "Diagnose expected consignment and sales figures for the stock report."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Target date in YYYY-MM-DD format (default: today).",
        )
        parser.add_argument(
            "--sku",
            type=str,
            default=None,
            help="Limit to a single product SKU.",
        )
        parser.add_argument(
            "--all-products",
            action="store_true",
            default=False,
            help="Show all active products (default: only products with sales or a reconciliation item).",
        )

    def handle(self, *args, **options):
        today = timezone.localtime(timezone.now()).date()
        target_date = (
            date.fromisoformat(options["date"]) if options["date"] else today
        )

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\n{'=' * 70}\n  Stock Report Diagnostic — {target_date}\n{'=' * 70}"
            )
        )

        # --- Reconciliation for the target date ---
        reconciliation = DailyStockReconciliation.objects.filter(
            reconciliation_date=target_date
        ).first()

        if reconciliation:
            self.stdout.write(
                f"\nReconciliation: id={reconciliation.id}  status={reconciliation.status}"
            )
        else:
            self.stdout.write(
                self.style.WARNING("\nNo DailyStockReconciliation found for this date.")
            )

        # --- Product selection ---
        qs = Product.objects.filter(is_active=True).order_by("prod_code")
        if options["sku"]:
            qs = qs.filter(sku=options["sku"])
            if not qs.exists():
                self.stderr.write(self.style.ERROR(f"No active product with SKU={options['sku']}"))
                return

        if not options["all_products"] and not options["sku"]:
            # Default: products that either have a reconciliation item or have sales today
            start_of_day = timezone.make_aware(datetime.combine(target_date, time.min))
            end_of_day = timezone.make_aware(datetime.combine(target_date, time.max))

            products_with_sales = set(
                TransactionLineItem.objects.filter(
                    scanned_at__gte=start_of_day,
                    scanned_at__lte=end_of_day,
                    is_inventory_deducted=True,
                ).values_list("product_id", flat=True)
            ) | set(
                CombinedOrderLineItem.objects.filter(
                    scanned_at__gte=start_of_day,
                    scanned_at__lte=end_of_day,
                    is_inventory_deducted=True,
                ).values_list("product_id", flat=True)
            )

            if reconciliation:
                products_with_recon = set(
                    reconciliation.adjustments.values_list("product_id", flat=True)
                )
            else:
                products_with_recon = set()

            relevant_ids = products_with_sales | products_with_recon
            if relevant_ids:
                qs = qs.filter(id__in=relevant_ids)
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "\nNo sales or reconciliation items found for this date. "
                        "Use --all-products to show every product."
                    )
                )
                return

        products = list(qs)
        self.stdout.write(f"\nInspecting {len(products)} product(s).\n")

        for product in products:
            self._diagnose_product(product, target_date, reconciliation)

    # ------------------------------------------------------------------

    def _diagnose_product(self, product, target_date, reconciliation):
        SEP = "─" * 70
        self.stdout.write(f"\n{SEP}")
        self.stdout.write(
            self.style.SUCCESS(
                f"  {product.prod_code} | {product.prod_name} (id={product.id})"
            )
        )
        self.stdout.write(SEP)

        # ---- reconciliation item ----
        adj = None
        if reconciliation:
            adj = reconciliation.adjustments.filter(product=product).first()

        if adj:
            self.stdout.write(
                f"  Reconciliation item: opening={adj.opening_stock}  "
                f"replenished={adj.quantity_replenished}  "
                f"added={adj.quantity_added}  deducted={adj.quantity_deducted}"
            )
        else:
            self.stdout.write(
                self.style.WARNING("  No StockAdjustmentItem for this product on this date.")
            )

        # ---- raw line items for today ----
        start_of_day = timezone.make_aware(datetime.combine(target_date, time.min))
        end_of_day = timezone.make_aware(datetime.combine(target_date, time.max))

        txn_items_all = TransactionLineItem.objects.filter(
            product=product,
            scanned_at__gte=start_of_day,
            scanned_at__lte=end_of_day,
            is_inventory_deducted=True,
        ).select_related("transaction")

        txn_items_excluded = txn_items_all.filter(
            transaction__status=Transaction.OrderStatus.COMBINED_FULFILLED
        )
        txn_items_counted = txn_items_all.exclude(
            transaction__status=Transaction.OrderStatus.COMBINED_FULFILLED
        )

        co_items = CombinedOrderLineItem.objects.filter(
            product=product,
            scanned_at__gte=start_of_day,
            scanned_at__lte=end_of_day,
            is_inventory_deducted=True,
        )

        txn_qty = txn_items_counted.aggregate(t=Sum("quantity"))["t"] or 0
        co_qty = co_items.aggregate(t=Sum("quantity"))["t"] or 0
        excl_qty = txn_items_excluded.aggregate(t=Sum("quantity"))["t"] or 0
        today_sales = txn_qty + co_qty

        self.stdout.write(f"\n  --- Today's sales ({target_date}) ---")
        self.stdout.write(
            f"  TransactionLineItem (counted)   : {txn_qty} units  ({txn_items_counted.count()} rows)"
        )
        self.stdout.write(
            f"  TransactionLineItem (excluded)  : {excl_qty} units  ({txn_items_excluded.count()} rows)  [COMBINED_FULFILLED txns]"
        )
        self.stdout.write(
            f"  CombinedOrderLineItem (counted) : {co_qty} units  ({co_items.count()} rows)"
        )
        self.stdout.write(
            self.style.SUCCESS(f"  Today's sales total             : {today_sales} units")
        )

        # Show individual excluded items so we can see if they're double-counted elsewhere
        if txn_items_excluded.exists():
            self.stdout.write(self.style.WARNING("\n  EXCLUDED TransactionLineItems (COMBINED_FULFILLED):"))
            for item in txn_items_excluded:
                self.stdout.write(
                    f"    tx_id={item.transaction.tx_id}  qty={item.quantity}  "
                    f"scanned_at={item.scanned_at.astimezone(timezone.get_current_timezone()).strftime('%Y-%m-%d %H:%M')}"
                )

        # Show individual counted txn line items
        if txn_items_counted.exists():
            self.stdout.write(f"\n  Counted TransactionLineItems:")
            for item in txn_items_counted:
                self.stdout.write(
                    f"    tx_id={item.transaction.tx_id}  status={item.transaction.status}  "
                    f"qty={item.quantity}  "
                    f"scanned_at={item.scanned_at.astimezone(timezone.get_current_timezone()).strftime('%Y-%m-%d %H:%M')}"
                )

        # Show CO line items
        if co_items.exists():
            self.stdout.write(f"\n  Counted CombinedOrderLineItems:")
            for item in co_items.select_related("combined_order"):
                self.stdout.write(
                    f"    co_id={item.combined_order.combined_order_id}  qty={item.quantity}  "
                    f"scanned_at={item.scanned_at.astimezone(timezone.get_current_timezone()).strftime('%Y-%m-%d %H:%M')}"
                )

        # ---- expected consignment breakdown ----
        self.stdout.write(f"\n  --- Expected Consignment Breakdown ---")

        last_replenishment = StockAdjustmentItem.objects.filter(
            product=product,
            quantity_replenished__gt=0,
            reconciliation__status="CONFIRMED",
            reconciliation__reconciliation_date__lte=target_date,
        ).order_by("-reconciliation__reconciliation_date").values_list(
            "reconciliation__reconciliation_date", flat=True
        ).first()

        if last_replenishment:
            self.stdout.write(f"  Last replenishment date : {last_replenishment}")
        else:
            self.stdout.write(f"  Last replenishment date : None (never replenished)")

        if last_replenishment == target_date:
            self.stdout.write(
                "  Replenished today → counter resets, expected = today's sales only"
            )
            expected = today_sales
        elif last_replenishment:
            start_date = last_replenishment + timedelta(days=1)
            self.stdout.write(f"  Accumulating from       : {start_date} (day after replenishment)")
            expected = self._accumulate_sales(product.id, start_date, target_date)
        else:
            first_reconciliation = StockAdjustmentItem.objects.filter(
                product=product,
                reconciliation__status="CONFIRMED",
            ).order_by("reconciliation__reconciliation_date").values_list(
                "reconciliation__reconciliation_date", flat=True
            ).first()

            if first_reconciliation:
                self.stdout.write(
                    f"  First confirmed recon   : {first_reconciliation}  → accumulating from there"
                )
                start_date = first_reconciliation
            else:
                self.stdout.write(
                    f"  No confirmed reconciliations → start_date = target_date ({target_date})"
                )
                start_date = target_date

            expected = self._accumulate_sales(product.id, start_date, target_date)

        # Per-day breakdown if range spans more than 1 day
        if "start_date" in dir() and start_date < target_date:  # noqa: F821
            self.stdout.write(f"\n  Per-day sales (for accumulation):")
            current = start_date  # noqa: F821
            while current <= target_date:
                day_sales = StockAdjustmentItem.calculate_issued_from_orders(product.id, current)
                marker = " ◀ today" if current == target_date else ""
                self.stdout.write(f"    {current}  →  {day_sales} units{marker}")
                current += timedelta(days=1)

        # Property value from model (what the report actually uses)
        model_expected = StockAdjustmentItem.calculate_expected_consignment(product.id, target_date)

        self.stdout.write(f"\n  Expected consignment (computed above) : {expected}")
        self.stdout.write(f"  Expected consignment (model method)   : {model_expected}")

        if expected != model_expected:
            self.stdout.write(
                self.style.ERROR(
                    f"  !! MISMATCH between computed and model method — investigate !!"
                )
            )

        gap = model_expected - today_sales
        if gap == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Expected consignment == today's sales ({today_sales})  ✓"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  Expected consignment ({model_expected}) vs today's sales ({today_sales})  "
                    f"→ gap = {gap:+d}  "
                    f"({'accumulated from prior days' if gap > 0 else 'unexpected'})"
                )
            )

    def _accumulate_sales(self, product_id, start_date, target_date):
        total = 0
        current = start_date
        while current <= target_date:
            total += StockAdjustmentItem.calculate_issued_from_orders(product_id, current)
            current += timedelta(days=1)
        return total
