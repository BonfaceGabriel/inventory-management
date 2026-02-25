"""
Management command to run a reconciliation V2 discrepancy check.

Usage:
    # Today
    docker-compose exec web python manage.py check_reconciliation

    # Specific date
    docker-compose exec web python manage.py check_reconciliation --date 2026-02-24

    # Date range
    docker-compose exec web python manage.py check_reconciliation --date 2026-02-20 --end-date 2026-02-24
"""

import json
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from payments.services.reconciliation_v2_service import ReconciliationV2Service


class Command(BaseCommand):
    help = "Run a reconciliation V2 discrepancy check and print the full breakdown."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Report date in YYYY-MM-DD format (default: today).",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default=None,
            help="End date for a range (inclusive). Requires --date as start.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            default=False,
            help="Output raw JSON instead of the human-readable summary.",
        )
        parser.add_argument(
            "--detail",
            action="store_true",
            default=False,
            help="Include per-transaction detail in output (verbose).",
        )

    def handle(self, *args, **options):
        today = timezone.localtime(timezone.now()).date()

        start_date = (
            date.fromisoformat(options["date"]) if options["date"] else today
        )
        end_date = (
            date.fromisoformat(options["end_date"]) if options["end_date"] else start_date
        )

        current = start_date
        while current <= end_date:
            self._run_for_date(current, options)
            current += timedelta(days=1)

    def _run_for_date(self, report_date: date, options: dict):
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\n{'=' * 60}\nReconciliation V2 Check — {report_date}\n{'=' * 60}"
            )
        )

        report = ReconciliationV2Service.generate_daily_report(report_date)

        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2, default=str))
            return

        # --- Formula summary ---
        x = report["x_value"]
        y = report["y_value"]
        result = report["result"]
        balanced = report["is_balanced"]

        status = self.style.SUCCESS("BALANCED") if balanced else self.style.ERROR("DISCREPANCY")

        xf = report["x_formula"]
        yf = report["y_formula"]

        self.stdout.write(
            f"\nX = Paybill - Unused + PDQ + Previous - Sales\n"
            f"    {xf['mpesa_paybill']:>12,.2f}  (Paybill)\n"
            f"  - {xf['unused']:>12,.2f}  (Unused)\n"
            f"  + {xf['pdq']:>12,.2f}  (PDQ)\n"
            f"  + {xf['previous']:>12,.2f}  (Previous)\n"
            f"  - {xf['sales']:>12,.2f}  (Sales)\n"
            f"  {'─' * 22}\n"
            f"  X = {x:>18,.2f}\n"
        )

        self.stdout.write(
            f"Y = Till - Credit - KITS\n"
            f"    {yf['till']:>12,.2f}  (Till)\n"
            f"  - {yf['credit']:>12,.2f}  (Credit)\n"
            f"  - {yf['kits']:>12,.2f}  (KITS)\n"
            f"  {'─' * 22}\n"
            f"  Y = {y:>18,.2f}\n"
        )

        self.stdout.write(
            f"\nResult (X + Y) = {result:,.2f}   [{status}]\n"
        )

        # --- Raw gateway totals ---
        raw = report.get("raw_breakdown", {})
        self.stdout.write(
            f"\nRaw gateway receipts (no combined-order logic):\n"
            f"  Paybill : {raw.get('paybill', 0):>12,.2f}\n"
            f"  Till    : {raw.get('till', 0):>12,.2f}\n"
            f"  PDQ     : {raw.get('pdq', 0):>12,.2f}\n"
        )

        # --- Component detail ---
        d = report["details"]
        self.stdout.write(f"\nComponent breakdown:")
        rows = [
            ("Paybill",  d["mpesa_paybill"]["amount"],  d["mpesa_paybill"]["count"],  d["mpesa_paybill"]["description"]),
            ("Unused",   d["unused"]["amount"],          d["unused"]["count"],          d["unused"]["description"]),
            ("PDQ",      d["pdq"]["amount"],              d["pdq"]["count"],              d["pdq"]["description"]),
            ("Previous", d["previous"]["amount"],        d["previous"]["count"],        d["previous"]["description"]),
            ("Till",     d["till"]["amount"],            d["till"]["count"],            d["till"]["description"]),
            ("Credit",   d["credit"]["amount"],          d["credit"]["count"],          d["credit"]["description"]),
            ("KITS",     d["kits"]["amount"],            d["kits"]["count"],            d["kits"]["description"]),
            ("Sales",    d["sales"]["amount"],           d["sales"]["count"],           d["sales"]["description"]),
        ]
        for label, amount, count, desc in rows:
            self.stdout.write(f"  {label:<10} {amount:>12,.2f}  (n={count})  {desc}")

        # Sales sub-breakdown
        by_gw = d["sales"].get("by_gateway", {})
        if by_gw:
            self.stdout.write(f"\n  Sales by gateway:")
            for gw_name, gw_data in by_gw.items():
                self.stdout.write(
                    f"    {gw_name:<30} {gw_data['amount']:>12,.2f}  (n={gw_data['count']})"
                )
            tf = d["sales"].get("total_fulfilled") or 0
            ka = d["sales"].get("kit_adjustment") or 0
            ki = d["sales"].get("kits_issued") or 0
            self.stdout.write(
                f"    {'Total fulfilled (raw)':<30} {tf:>12,.2f}\n"
                f"    {'Kit adjustment ({ki} kits)':<30} {ka:>12,.2f}\n"
                .replace("{ki}", str(ki))
            )

        # --- Verbose transaction detail ---
        if options["detail"]:
            self._print_detail(report)

    def _print_detail(self, report: dict):
        # We need to re-run individual calculations to get transaction lists.
        # The generate_daily_report only returns aggregates in `details`.
        # Re-run each calculator directly.
        from datetime import date as date_cls
        report_date = date_cls.fromisoformat(report["report_date"])
        paybill_gw = ReconciliationV2Service.get_parent_paybill_gateway()

        sections = {
            "Paybill transactions": ReconciliationV2Service.calculate_mpesa_paybill(report_date, paybill_gw).get("transactions", []),
            "Unused transactions": ReconciliationV2Service.calculate_unused_unfulfilled(report_date, paybill_gw).get("transactions", []),
            "PDQ transactions": ReconciliationV2Service.calculate_pdq_total(report_date).get("transactions", []),
            "Previous transactions": ReconciliationV2Service.calculate_previous(report_date, paybill_gw).get("transactions", []),
            "Till transactions": ReconciliationV2Service.calculate_till_sales(report_date).get("transactions", []),
            "Credit transactions": ReconciliationV2Service.calculate_credit(report_date, paybill_gw).get("transactions", []),
            "KITS transactions": ReconciliationV2Service.calculate_kits(report_date).get("transactions", []),
        }

        self.stdout.write(f"\n{'─' * 60}\nTransaction detail:")
        for section, txns in sections.items():
            self.stdout.write(f"\n  {section} ({len(txns)} items):")
            for t in txns:
                self.stdout.write(f"    {json.dumps(t, default=str)}")
