from asyncio import gather
from datetime import date, timedelta
from decimal import Decimal

from .client import RevenueClient
from .models import (
    MerchandiseReport,
    ProductReport,
    ReconciliationSummary,
    RegistrationReport,
    RevenuePeriod,
    RevenueQuery,
    RevenueReport,
    RevenueTrend,
    SalesSeries,
    StockReport,
)
from .web import format_change, format_period, registration_lines


def money(amount: Decimal) -> str:
    return f"KES {amount:,.2f}"


def trend_lines(rows: list[tuple[date, Decimal]], day: date, name: str) -> list[str]:
    yesterday, current = rows[-2:]
    trend = RevenueTrend(
        latest=RevenuePeriod(start_date=day, end_date=day),
        previous=RevenuePeriod(start_date=yesterday[0], end_date=yesterday[0]),
        latest_total=current[1], previous_total=yesterday[1],
    )
    start = day.replace(day=1)
    month = [value for when, value in rows if when >= start]
    floor = min([Decimal(0), *month])
    peak = max(month, default=Decimal(0))
    levels = "▁▂▃▄▅▆▇█"
    span = peak - floor
    chart = "".join(levels[int((value - floor) * 7 / span)] if span else levels[0] for value in month)
    lines = [
        f"Versus yesterday ({yesterday[0]}, {money(yesterday[1])}): {format_change(trend)}",
        f"{name} by day, {start} to {day} (scale {money(floor)} to {money(peak)})",
        chart,
    ]
    rolling = RevenueTrend.for_daily_rows(rows)
    if rolling is not None:
        lines.append(
            f"Seven-day change ({format_period(rolling.latest)} vs {format_period(rolling.previous)}): "
            f"{format_change(rolling)}"
        )
    return lines


async def render_briefing_preview(client: RevenueClient, day: date) -> str:
    today = client.today
    if day > today:
        raise ValueError("Choose a reporting date up to today in Nairobi.")
    start = min(day.replace(day=1), day - timedelta(days=13))

    async def branch_report(branch):
        query = RevenueQuery(branch=branch.id, start_date=day, end_date=day)
        window = RevenueQuery(branch=branch.id, start_date=start, end_date=day)
        revenue, sales, products, registrations, reconciliation, merchandise, stock = await gather(
            client.get_revenue(window), client.get_sales(window, daily=True),
            client.get_products(query), client.get_registrations(query), client.get_reconciliation(query),
            client.get_merchandise(query, 1), client.get_stock(branch.id, 1),
        )
        lines = [f"*{branch.name}*"]

        def section(name: str):
            lines.extend(["", f"*{name}*"])

        sales_total = merch_total = stock_total = None
        section("Revenue")
        if isinstance(revenue, RevenueReport):
            last = revenue.daily[-1]
            lines += [
                f"Revenue: {money(last.total_revenue)}",
                f"Paybill {money(last.paybill)} · PDQ {money(last.pdq)} · Till {money(last.till)}",
                *trend_lines([(row.date, row.total_revenue) for row in revenue.daily], day, "Revenue"),
            ]
        else:
            lines.append("Revenue unavailable.")
        section("Fulfilled sales")
        if isinstance(sales, SalesSeries):
            sales_total = sales.daily[-1].total_sales
            lines += [
                f"Fulfilled sales: {money(sales_total)}",
                *trend_lines([(row.date, row.total_sales) for row in sales.daily], day, "Sales"),
            ]
        else:
            lines.append("Fulfilled sales and daily trend unavailable.")
        if isinstance(products, ProductReport):
            if products.products:
                first = products.products[0]
                lines.append(f"Best-selling product: {first.name}, {first.units_sold:,} units ({money(first.sales_value)}).")
            else:
                lines.append("No completed product sales.")
        else:
            lines.append("Best-selling product unavailable.")
        section("Registrations")
        if isinstance(registrations, RegistrationReport):
            lines.extend(registration_lines(registrations))
        else:
            lines.append("Registrations unavailable.")
        section("Payment reconciliation")
        if isinstance(reconciliation, ReconciliationSummary):
            status = "Balanced" if reconciliation.is_balanced else "Discrepancy"
            lines.append(
                f"Reconciliation: {status}. X {money(reconciliation.x_value)} · "
                f"Y {money(reconciliation.y_value)} · Result {money(reconciliation.result)}"
            )
        else:
            lines.append("Reconciliation unavailable.")
        section("Merchandise")
        if isinstance(merchandise, MerchandiseReport):
            merch_total = merchandise.total_fulfilled
            lines.append(f"Merchandise fulfilled: {money(merch_total)}")
            if merchandise.previous_day_total is not None:
                previous = day - timedelta(days=1)
                change = RevenueTrend(
                    latest=query, previous=RevenuePeriod(start_date=previous, end_date=previous),
                    latest_total=merch_total, previous_total=merchandise.previous_day_total,
                )
                lines.append(f"Versus yesterday ({previous}): {format_change(change)}")
            pages = await gather(*(client.get_merchandise(query, page) for page in range(2, merchandise.page_count + 1)))
            lines.append(f"Merchandise remaining as of {today}, at current catalog prices.")
            for page in [merchandise, *pages]:
                if not isinstance(page, MerchandiseReport) or page.page_count != merchandise.page_count:
                    lines.append("Some merchandise items are unavailable.")
                    break
                lines.extend(
                    f"{item.name}: sold {item.units_sold:,} ({money(item.sales_value)}), "
                    f"remaining {item.remaining_units:,} ({money(item.remaining_catalog_value)})"
                    for item in page.items
                )
        else:
            lines.append("Merchandise unavailable.")
        section("Stock")
        if isinstance(stock, StockReport):
            stock_total = stock.total_stock_value_at_cost
            lines.append(f"Product stock at cost ({stock.start_date}): {money(stock_total)}")
            lines.append(f"Out of stock: {stock.out_of_stock_count:,} · Low stock: {stock.low_stock_count:,}")
            pages = await gather(*(client.get_stock(branch.id, page) for page in range(2, stock.page_count + 1)))
            for page in [stock, *pages]:
                if not isinstance(page, StockReport) or page.page_count != stock.page_count:
                    lines.append("Some stock alerts are unavailable.")
                    break
                lines.extend(
                    f"{item.name}: {item.quantity:,} remaining ({item.status.replace('_', ' ').lower()})"
                    for item in page.items
                )
        else:
            lines.append("Product stock unavailable.")
        return lines, (sales_total, merch_total, stock_total)

    lines = [f"*End-of-day briefing preview — {day} (Africa/Nairobi)*"]
    if day == today:
        lines.append("Today's figures are provisional.")
    reports = await gather(*(branch_report(branch) for branch in client.branches))
    for branch_lines, _ in reports:
        lines.extend(["", *branch_lines])
    lines.extend(["", "*All branches*", "Revenue unavailable pending verification of shared-receipt deduplication."])
    for index, name in enumerate(("Fulfilled sales", "Merchandise fulfilled", "Current product stock at cost")):
        values = [(client.branches[i].name, totals[index]) for i, (_, totals) in enumerate(reports)]
        missing = [branch for branch, value in values if value is None]
        if missing:
            lines.append(f"{name}: incomplete. Unavailable: {', '.join(missing)}.")
        else:
            lines.append(f"{name}: {money(sum((value for _, value in values), start=Decimal(0)))}")
    return "\n".join(lines)
