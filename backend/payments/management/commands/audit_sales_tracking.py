"""
Audit command to find bugs in how sales are tracked.

Checks every possible correctness invariant for TransactionLineItem and
CombinedOrderLineItem records that have is_inventory_deducted=True.

Sections:
  1. CANCELLED transactions with deducted line items   (counted as sales — wrong)
  2. COMBINED_FULFILLED transactions whose deducted TLIs have NO matching CO line item
     (the copy step was skipped — sales are lost)
  3. CO line items with copied_from_transaction set but that transaction is NOT
     COMBINED_FULFILLED  (TLI would also be counted → double-count)
  4. CO line items with copied_from_transaction set but no matching TLI exists
     (dangling reference)
  5. TLIs with is_inventory_deducted=True on unexpected statuses
     (NOT_PROCESSED / PROCESSING — should never happen)
  6. CO line items with is_inventory_deducted=True that were NOT copied from a
     transaction (directly issued to CO) — sanity count
  7. Summary counts

Usage:
    docker-compose exec web python manage.py audit_sales_tracking
    docker-compose exec web python manage.py audit_sales_tracking --date 2026-02-25
    docker-compose exec web python manage.py audit_sales_tracking --from 2026-01-01 --to 2026-02-25
"""

from datetime import date, datetime, time

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum
from django.utils import timezone

from payments.models import (
    CombinedOrderLineItem,
    Transaction,
    TransactionLineItem,
)


class Command(BaseCommand):
    help = "Audit sales tracking for bugs (double-counts, missing sales, wrong statuses)."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, default=None,
                            help="Single date YYYY-MM-DD (overrides --from/--to).")
        parser.add_argument("--from", dest="from_date", type=str, default=None,
                            help="Start date YYYY-MM-DD (inclusive).")
        parser.add_argument("--to", dest="to_date", type=str, default=None,
                            help="End date YYYY-MM-DD (inclusive).")

    def handle(self, *args, **options):
        today = timezone.localtime(timezone.now()).date()

        if options["date"]:
            d = date.fromisoformat(options["date"])
            start_dt = timezone.make_aware(datetime.combine(d, time.min))
            end_dt = timezone.make_aware(datetime.combine(d, time.max))
            label = str(d)
        else:
            from_d = date.fromisoformat(options["from_date"]) if options["from_date"] else today
            to_d = date.fromisoformat(options["to_date"]) if options["to_date"] else today
            start_dt = timezone.make_aware(datetime.combine(from_d, time.min))
            end_dt = timezone.make_aware(datetime.combine(to_d, time.max))
            label = f"{from_d} → {to_d}"

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{'=' * 70}\n  Sales Tracking Audit — {label}\n{'=' * 70}"
        ))

        # Base querysets scoped to the date window
        tli_qs = TransactionLineItem.objects.filter(
            is_inventory_deducted=True,
            scanned_at__gte=start_dt,
            scanned_at__lte=end_dt,
        ).select_related("transaction", "product")

        coli_qs = CombinedOrderLineItem.objects.filter(
            is_inventory_deducted=True,
            scanned_at__gte=start_dt,
            scanned_at__lte=end_dt,
        ).select_related("combined_order", "product", "copied_from_transaction")

        total_issues = 0
        total_issues += self._check_cancelled_with_deducted_tli(tli_qs)
        total_issues += self._check_combined_fulfilled_missing_co_copy(tli_qs, start_dt, end_dt)
        total_issues += self._check_co_copy_txn_not_combined_fulfilled(coli_qs)
        total_issues += self._check_co_copy_dangling_tli(coli_qs)
        total_issues += self._check_unexpected_status_tli(tli_qs)
        self._print_summary(tli_qs, coli_qs)

        self.stdout.write("")
        if total_issues == 0:
            self.stdout.write(self.style.SUCCESS("No issues found."))
        else:
            self.stdout.write(self.style.ERROR(
                f"Total issues found: {total_issues}  — review sections above."
            ))

    # ------------------------------------------------------------------
    # Section 1: CANCELLED transactions with deducted TLIs
    # ------------------------------------------------------------------
    def _check_cancelled_with_deducted_tli(self, tli_qs):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n[1] CANCELLED transactions with is_inventory_deducted=True TLIs"
        ))
        self.stdout.write(
            "    These items are currently COUNTED as sales even though the transaction\n"
            "    was cancelled. If inventory was restored on cancellation, this is a bug."
        )

        items = tli_qs.filter(transaction__status=Transaction.OrderStatus.CANCELLED)
        if not items.exists():
            self.stdout.write(self.style.SUCCESS("    OK — none found."))
            return 0

        self.stdout.write(self.style.ERROR(f"    FOUND {items.count()} item(s):"))
        for item in items:
            self.stdout.write(
                f"      tx_id={item.transaction.tx_id}  "
                f"product={item.product.prod_code}  qty={item.quantity}  "
                f"scanned_at={_local(item.scanned_at)}"
            )
        return items.count()

    # ------------------------------------------------------------------
    # Section 2: COMBINED_FULFILLED TLIs with no matching CO copy
    # ------------------------------------------------------------------
    def _check_combined_fulfilled_missing_co_copy(self, tli_qs, start_dt, end_dt):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n[2] COMBINED_FULFILLED TLIs with no matching CombinedOrderLineItem copy"
        ))
        self.stdout.write(
            "    When a PARTIALLY_FULFILLED transaction is combined, its deducted TLIs\n"
            "    should be copied to CombinedOrderLineItem. If the copy is missing the\n"
            "    sale is EXCLUDED from TLI count (COMBINED_FULFILLED) and also absent\n"
            "    from CO count → sale is LOST entirely."
        )

        cf_items = tli_qs.filter(
            transaction__status=Transaction.OrderStatus.COMBINED_FULFILLED
        )

        missing = []
        for item in cf_items:
            has_copy = CombinedOrderLineItem.objects.filter(
                copied_from_transaction=item.transaction,
                product=item.product,
                is_inventory_deducted=True,
                # Don't restrict by scanned_at: CO copy may have slightly different timestamp
            ).exists()
            if not has_copy:
                missing.append(item)

        if not missing:
            self.stdout.write(self.style.SUCCESS("    OK — every COMBINED_FULFILLED TLI has a CO copy."))
            return 0

        self.stdout.write(self.style.ERROR(f"    FOUND {len(missing)} item(s) with no CO copy (LOST SALES):"))
        for item in missing:
            self.stdout.write(
                f"      tx_id={item.transaction.tx_id}  "
                f"product={item.product.prod_code}  qty={item.quantity}  "
                f"scanned_at={_local(item.scanned_at)}"
            )
        return len(missing)

    # ------------------------------------------------------------------
    # Section 3: CO copies whose source transaction is NOT COMBINED_FULFILLED
    # ------------------------------------------------------------------
    def _check_co_copy_txn_not_combined_fulfilled(self, coli_qs):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n[3] CO line items (copied_from_transaction set) where source txn is NOT COMBINED_FULFILLED"
        ))
        self.stdout.write(
            "    The source TLI would still be COUNTED (not excluded) AND the CO copy is\n"
            "    also counted → DOUBLE COUNT."
        )

        copied_items = coli_qs.filter(copied_from_transaction__isnull=False)
        bad = []
        for item in copied_items:
            src_status = item.copied_from_transaction.status
            if src_status != Transaction.OrderStatus.COMBINED_FULFILLED:
                bad.append((item, src_status))

        if not bad:
            self.stdout.write(self.style.SUCCESS("    OK — all copied CO items have COMBINED_FULFILLED source."))
            return 0

        self.stdout.write(self.style.ERROR(f"    FOUND {len(bad)} item(s) that may be DOUBLE COUNTED:"))
        for item, src_status in bad:
            self.stdout.write(
                f"      co_id={item.combined_order.combined_order_id}  "
                f"product={item.product.prod_code}  qty={item.quantity}  "
                f"source_tx={item.copied_from_transaction.tx_id}  source_status={src_status}  "
                f"scanned_at={_local(item.scanned_at)}"
            )
        return len(bad)

    # ------------------------------------------------------------------
    # Section 4: CO copies with a dangling copied_from_transaction reference
    # ------------------------------------------------------------------
    def _check_co_copy_dangling_tli(self, coli_qs):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n[4] CO line items with copied_from_transaction set but source TLI no longer exists"
        ))
        self.stdout.write(
            "    The original TLI was deleted. CO item is the only record of the sale —\n"
            "    not necessarily a counting bug but indicates unexpected data deletion."
        )

        copied_items = coli_qs.filter(copied_from_transaction__isnull=False)
        dangling = []
        for item in copied_items:
            has_tli = TransactionLineItem.objects.filter(
                transaction=item.copied_from_transaction,
                product=item.product,
                is_inventory_deducted=True,
            ).exists()
            if not has_tli:
                dangling.append(item)

        if not dangling:
            self.stdout.write(self.style.SUCCESS("    OK — all CO copies have a matching source TLI."))
            return 0

        self.stdout.write(self.style.WARNING(f"    FOUND {len(dangling)} item(s) with no source TLI:"))
        for item in dangling:
            self.stdout.write(
                f"      co_id={item.combined_order.combined_order_id}  "
                f"product={item.product.prod_code}  qty={item.quantity}  "
                f"source_tx={item.copied_from_transaction.tx_id}  "
                f"scanned_at={_local(item.scanned_at)}"
            )
        return len(dangling)

    # ------------------------------------------------------------------
    # Section 5: TLIs on impossible statuses
    # ------------------------------------------------------------------
    def _check_unexpected_status_tli(self, tli_qs):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n[5] TLIs with is_inventory_deducted=True on NOT_PROCESSED or PROCESSING transactions"
        ))
        self.stdout.write(
            "    Inventory should only be deducted on completion. These items should\n"
            "    never exist and indicate a state machine bug."
        )

        bad_statuses = [
            Transaction.OrderStatus.NOT_PROCESSED,
            Transaction.OrderStatus.PROCESSING,
        ]
        items = tli_qs.filter(transaction__status__in=bad_statuses)

        if not items.exists():
            self.stdout.write(self.style.SUCCESS("    OK — none found."))
            return 0

        self.stdout.write(self.style.ERROR(f"    FOUND {items.count()} item(s):"))
        for item in items:
            self.stdout.write(
                f"      tx_id={item.transaction.tx_id}  status={item.transaction.status}  "
                f"product={item.product.prod_code}  qty={item.quantity}  "
                f"scanned_at={_local(item.scanned_at)}"
            )
        return items.count()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def _print_summary(self, tli_qs, coli_qs):
        self.stdout.write(self.style.MIGRATE_HEADING("\n[6] Overall counts"))

        # TLI breakdown by transaction status
        from django.db.models import Count
        tli_by_status = (
            tli_qs
            .values("transaction__status")
            .annotate(rows=Count("id"), units=Sum("quantity"))
            .order_by("transaction__status")
        )
        self.stdout.write("\n  TransactionLineItem (is_inventory_deducted=True) by txn status:")
        counted_units = 0
        excluded_units = 0
        for row in tli_by_status:
            status = row["transaction__status"]
            rows = row["rows"]
            units = row["units"] or 0
            excluded = status == Transaction.OrderStatus.COMBINED_FULFILLED
            marker = "  [EXCLUDED from sales count]" if excluded else "  [COUNTED as sales]"
            self.stdout.write(f"    {status:<25}  rows={rows:<6} units={units:<6}{marker}")
            if excluded:
                excluded_units += units
            else:
                counted_units += units

        self.stdout.write(f"\n    TLI units counted as sales : {counted_units}")
        self.stdout.write(f"    TLI units excluded         : {excluded_units}")

        # CO line item breakdown
        co_copied = coli_qs.filter(copied_from_transaction__isnull=False)
        co_direct = coli_qs.filter(copied_from_transaction__isnull=True)
        co_copied_units = co_copied.aggregate(t=Sum("quantity"))["t"] or 0
        co_direct_units = co_direct.aggregate(t=Sum("quantity"))["t"] or 0
        co_total_units = co_copied_units + co_direct_units

        self.stdout.write("\n  CombinedOrderLineItem (is_inventory_deducted=True):")
        self.stdout.write(f"    Copied from txn (rows={co_copied.count()})  : {co_copied_units} units  [COUNTED as sales]")
        self.stdout.write(f"    Directly issued (rows={co_direct.count()})  : {co_direct_units} units  [COUNTED as sales]")
        self.stdout.write(f"    CO total units counted as sales : {co_total_units}")

        grand_total = counted_units + co_total_units
        self.stdout.write(self.style.SUCCESS(
            f"\n  Grand total sales units (TLI counted + CO total) : {grand_total}"
        ))


def _local(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M") if dt else "—"
