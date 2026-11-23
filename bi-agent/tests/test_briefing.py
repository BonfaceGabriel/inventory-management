from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from whatsapp_bi.briefing import render_briefing_preview, trend_lines
from whatsapp_bi.client import RevenueClient
from whatsapp_bi.models import BranchConfig


def test_chart_resets_at_month_boundary_but_rolling_comparison_crosses_it():
    day = date(2026, 11, 2)
    rows = [(day - timedelta(days=13 - i), Decimal(100 if i < 7 else 200)) for i in range(14)]
    lines = trend_lines(rows, day, "Sales")
    assert "2026-11-01 to 2026-11-02" in lines[1]
    assert lines[2] == "██"
    assert lines[3] == "Seven-day change (2026-10-27 to 2026-11-02 vs 2026-10-20 to 2026-10-26): +100.00%"


@pytest.mark.parametrize("missing_sales", [False, True])
async def test_briefing_combines_available_reports_and_lists_all_alert_pages(missing_sales):
    day = date(2026, 11, 2)
    today = day + timedelta(days=1)
    branches = [
        BranchConfig(id=branch, name=branch.capitalize(), base_url=f"https://{branch}.example/api/v1", token_env="TOKEN")
        for branch in ("first", "second")
    ]

    def transport(request):
        branch = request.url.host.split(".")[0]
        start, end = [date.fromisoformat(request.url.params[key]) for key in ("start_date", "end_date")]
        metric = request.url.path.split("/")[-2]
        data = {
            "schema_version": 1, "branch": {"id": branch, "name": branch.capitalize()},
            "start_date": str(start), "end_date": str(end), "timezone": "Africa/Nairobi", "currency": "KES",
            "generated_at": f"{today}T08:00:00Z", "is_provisional": end == today,
        }
        dates = [str(start + timedelta(days=i)) for i in range((end - start).days + 1)]
        if metric == "revenue":
            assert start == day - timedelta(days=13)
            data |= {
                "totals": {
                    "paybill": "140.00", "pdq": "0.00", "till": "0.00", "total_revenue": "140.00",
                    "transaction_count": 14,
                },
                "daily": [
                    {"date": when, "paybill": "10.00", "pdq": "0.00", "till": "0.00",
                     "total_revenue": "10.00", "transaction_count": 1} for when in dates
                ],
            }
        elif metric == "sales":
            if missing_sales and branch == "second":
                return httpx.Response(503)
            data |= {
                "total_sales": "280.00",
                "daily": [{"date": when, "total_sales": "20.00"} for when in dates],
            }
        elif metric == "products":
            data["products"] = [{"code": "X", "name": "Top product", "units_sold": 2, "sales_value": "20.00"}]
        elif metric == "reconciliation":
            data |= {"x_value": "-1.00", "y_value": "1.00", "result": "0.00", "is_balanced": True}
        elif request.url.params["view"] == "merchandise":
            data |= {"page": 1, "page_count": 1, "items": [], "total_fulfilled": "7.00", "previous_day_total": "5.00"}
        else:
            page = int(request.url.params["page"])
            data |= {
                "page": page, "page_count": 2, "total_stock_value_at_cost": "90.00",
                "out_of_stock_count": 1, "low_stock_count": 1,
                "items": [{"code": str(page), "name": f"Alert page {page}", "quantity": 0,
                           "reorder_level": 2, "status": "OUT_OF_STOCK"}],
            }
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        client = RevenueClient(branches, http, token_lookup=lambda _: "fixture", clock=lambda: today)
        report = await render_briefing_preview(client, day)
    assert "Best-selling product: Top product, 2 units (KES 20.00)." in report
    assert "Reconciliation: Balanced. X KES -1.00 · Y KES 1.00 · Result KES 0.00" in report
    assert "Alert page 2: 0 remaining" in report
    assert "Product stock at cost (2026-11-03): KES 90.00" in report
    company = report.split("\nAll branches\n")[1]
    assert "Revenue unavailable pending verification of shared-receipt deduplication." in company
    assert "Merchandise fulfilled: KES 14.00" in company
    assert "Current product stock at cost: KES 180.00" in company
    expected = "Fulfilled sales: incomplete. Unavailable: Second." if missing_sales else "Fulfilled sales: KES 40.00"
    assert expected in company
