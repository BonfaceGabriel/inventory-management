import asyncio
import hmac
import logging
import os
import sqlite3
import time
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import TypeAdapter, ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models import Model
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from .agent import RECONCILIATION_DATE_REQUIRED, build_agent, reconciliation_needs_a_date, run_question
from .chatgpt import configured_model
from .client import RevenueClient
from .inbox import REPLY_WINDOW_SECONDS, Inbox, Message
from .models import (
    NAIROBI,
    BranchConfig,
    BranchReport,
    ConversationContext,
    DailyRevenue,
    DailyRevenueBreakdown,
    MerchandiseReport,
    MonthlyRevenueBreakdown,
    MonthlyAmount,
    MonthlyRevenueTotal,
    ProductReport,
    ReconciliationSummary,
    RevenueAmounts,
    RevenueComparison,
    RevenuePeriod,
    RevenueProblem,
    RevenueSummary,
    RevenueTrend,
    SalesSummary,
    SalesBreakdown,
    StockReport,
)
from .whatsapp import (
    TEXT_LIMIT,
    WebhookEvent,
    WhatsAppSettings,
    describe_reply_rejection,
    send_reply,
    valid_signature,
)

logger = logging.getLogger(__name__)
MAX_WEBHOOK_BYTES = 1024 * 1024
UNAVAILABLE_REPLY = "I couldn't verify the figures right now. Please try again."


def format_period(summary: BranchReport | RevenuePeriod) -> str:
    if summary.end_date == summary.start_date:
        return str(summary.start_date)
    return f"{summary.start_date} to {summary.end_date}"


def format_gateways(totals: RevenueAmounts) -> str:
    return f"Paybill {totals.paybill:,.2f} | PDQ {totals.pdq:,.2f} | Till {totals.till:,.2f}"


def format_change(trend: RevenueTrend) -> str:
    percent = trend.percent_change
    if percent is None:
        return (
            f"KES {trend.change:+,.2f}. "
            "Percentage undefined because the previous total was KES 0.00."
        )
    return f"{percent:+,.2f}%" if percent else "0.00%"


def render_daily_breakdown(report: DailyRevenueBreakdown) -> str:
    header = [
        f"{report.branch.name} — daily revenue ({format_period(report)})",
        f"Total revenue: KES {report.totals.total_revenue:,.2f}",
    ]
    if report.is_provisional:
        header.append(f"Includes provisional revenue for {report.end_date}.")
    if any(isinstance(row, DailyRevenue) for row in report.days):
        header.append(f"Period gateways (KES): {format_gateways(report.totals)}")
    rows = [
        f"{row.date}: {format_gateways(row)} | Total {row.total_revenue:,.2f}"
        if isinstance(row, DailyRevenue) else f"{row.date}: KES {row.total_revenue:,.2f}"
        for row in report.days
    ]

    footer = []
    trend = report.trend
    if trend is not None:
        footer.extend([
            "",
            f"Last 7 days ({format_period(trend.latest)}): KES {trend.latest_total:,.2f}",
            f"Previous 7 days ({format_period(trend.previous)}): KES {trend.previous_total:,.2f}",
        ])
        footer.append(f"Change: {format_change(trend)}")
    elif report.trend_requested:
        footer.append("Choose a range of at least 14 days for the seven-day comparison.")

    # Leave room for the range notice if we have to omit older rows for WhatsApp.
    notice = f"Showing the most recent {len(rows)} of {report.day_count} days."
    length = len("\n".join([*header, notice, *rows, *footer]))
    first = 0
    while first < len(rows) and length > TEXT_LIMIT:
        length -= len(rows[first]) + 1
        first += 1
    shown = len(rows) - first
    if shown < report.day_count:
        header.append(f"Showing the most recent {shown} of {report.day_count} days.")
    return "\n".join([*header, *rows[first:], *footer])


def render_monthly_breakdown(report: MonthlyRevenueBreakdown) -> str:
    lines = [
        f"{report.branch.name} — monthly revenue ({format_period(report)})",
        f"Total revenue: KES {report.totals.total_revenue:,.2f}",
    ]
    if report.is_provisional:
        lines.append(f"Includes provisional revenue for {report.end_date}.")
    for month in report.months:
        lines.extend(monthly_lines(month, month.total_revenue))
    return "\n".join(lines)


def monthly_lines(month: MonthlyAmount | MonthlyRevenueTotal, amount: Decimal) -> list[str]:
    label = f"{month.start_date:%B %Y}"
    if month.coverage == "current_month":
        label += f" (incomplete current month, {format_period(month)})"
    elif month.coverage == "partial_month":
        label += f" (partial month, {format_period(month)})"
    lines = [f"{label}: KES {amount:,.2f}"]
    if comparison := month.comparison:
        lines.append(f"Change vs {comparison.previous.start_date:%B %Y}: {format_change(comparison)}")
    return lines


def sales_detail_lines(report: SalesBreakdown) -> list[str]:
    if report.months:
        return [line for month in report.months for line in monthly_lines(month, month.amount)]
    lines = []
    if len(report.days) < report.day_count:
        lines.append(f"Showing the most recent {len(report.days)} of {report.day_count} days.")
    lines.extend(f"{row.date}: KES {row.total_sales:,.2f}" for row in report.days)
    if trend := report.trend:
        lines.extend([
            "",
            f"Last 7 days ({format_period(trend.latest)}): KES {trend.latest_total:,.2f}",
            f"Previous 7 days ({format_period(trend.previous)}): KES {trend.previous_total:,.2f}",
            f"Change: {format_change(trend)}",
        ])
    elif report.trend_requested:
        lines.append("Choose a range of at least 14 days for the seven-day comparison.")
    return lines


def render_inventory(report: MerchandiseReport | StockReport) -> str:
    if isinstance(report, MerchandiseReport):
        as_of = report.generated_at.astimezone(NAIROBI).date()
        lines = [
            f"{report.branch.name} — merchandise ({format_period(report)})",
            f"Total fulfilled: KES {report.total_fulfilled:,.2f}",
        ]
        if report.previous_day_total is not None:
            previous = report.start_date - timedelta(days=1)
            trend = RevenueTrend(
                latest=RevenuePeriod(start_date=report.start_date, end_date=report.end_date),
                previous=RevenuePeriod(start_date=previous, end_date=previous),
                latest_total=report.total_fulfilled, previous_total=report.previous_day_total,
            )
            lines.extend([
                f"Previous day ({previous}): KES {report.previous_day_total:,.2f}",
                f"Change: {format_change(trend)}",
            ])
        if report.is_provisional:
            lines.append("Today's fulfillment is provisional.")
        lines.append(f"Remaining quantities as of {as_of}, valued at current catalog prices.")
        lines.extend(
            f"{item.name}: sold {item.units_sold:,} (KES {item.sales_value:,.2f}), "
            f"remaining {item.remaining_units:,} (KES {item.remaining_catalog_value:,.2f})"
            for item in report.items
        )
    else:
        lines = [
            f"{report.branch.name} — current product stock ({report.start_date})",
            f"Stock value at cost: KES {report.total_stock_value_at_cost:,.2f}",
            f"Out of stock: {report.out_of_stock_count:,} | Low stock: {report.low_stock_count:,}",
        ]
        lines.extend(
            f"{item.name}: {item.quantity:,} remaining ({item.status.replace('_', ' ').lower()})"
            for item in report.items
        )
    if report.page > report.page_count:
        lines.append(f"Page {report.page} is unavailable. Available pages: 1–{report.page_count}.")
    elif report.page_count > 1:
        lines.append(f"Page {report.page} of {report.page_count}.")
    return "\n".join(lines)


def date_validation_reply(errors: list[dict]) -> str | None:
    # Use known validation codes and field names. Retry prompts also carry the
    # rejected input, which must not be echoed back as an error message.
    codes = {error["type"] for error in errors}
    if "revenue_dates_out_of_order" in codes:
        return "The end date is before the start date. Please put the earlier date first."
    if "revenue_range_too_long" in codes:
        return "That date range is too long. Please ask for 366 days or fewer at a time."
    date_fields = {"start_date", "end_date", "report_date"}
    if any(date_fields.intersection(error.get("loc", ())) for error in errors):
        return "I couldn't read those dates. Please use complete dates like 18 November 2026."
    return None


def render_answer(
    parts: list[ToolReturnPart], branches: list[BranchConfig]
) -> tuple[str, ConversationContext | None]:
    results = [part.content for part in parts if part.outcome == "success"]
    if not results:
        for part in reversed(parts):
            if part.retry and part.retry.cause == "validation_error" and isinstance(part.content, list):
                if reply := date_validation_reply(part.content):
                    return reply, None
        names = ", ".join(branch.name for branch in branches)
        return (
            f"Ask for revenue, sales, or reconciliation for one branch and include the date. Branches: {names}.",
            None,
        )

    problem = next((result for result in results if isinstance(result, RevenueProblem)), None)
    if problem is not None:
        if problem.status == "unknown_branch":
            names = ", ".join(branch.name for branch in branches)
            return f"I couldn't match that branch. Available branches: {names}.", None
        if problem.status == "invalid_request":
            return "I couldn't use that date range. Use dates up to today in Nairobi, with the start date first.", None
        if problem.status == "reconciliation_date_required":
            return RECONCILIATION_DATE_REQUIRED, None
        if problem.status == "incomplete_fulfillment_history":
            if any(part.tool_name == "get_top_products" for part in parts):
                return "I couldn't verify the product ranking from the completed fulfillment records for those dates.", None
            return (
                "I couldn't verify sales for those dates from the fulfillment records. "
                "If an order was fulfilled over several days, try a range that includes all of them.", None
            )
        logger.warning("Verified figures unavailable (%s)", problem.status)
        return UNAVAILABLE_REPLY, None
    if len(results) != 1:
        return "Ask for one report at a time, or compare two revenue periods at one branch.", None

    summary = results[0]
    if isinstance(summary, RevenueComparison):
        lines = [summary.period.branch.name]
        for label, item in (("Period", summary.period), ("Baseline", summary.baseline)):
            status = " (provisional)" if item.is_provisional else ""
            lines.append(
                f"{label} ({format_period(item)}): KES {item.totals.total_revenue:,.2f}{status}"
            )
        change = summary.change
        lines.append(f"Change: KES {change:+,.2f}" if change else "Change: KES 0.00")
        start = min(summary.period.start_date, summary.baseline.start_date)
        end = max(summary.period.end_date, summary.baseline.end_date)
        month = start.replace(day=1)
        context = ConversationContext(
            branch_id=summary.period.branch.id,
            comparison_month=month if end.replace(day=1) == month else None,
        )
        return "\n".join(lines), context
    if isinstance(summary, (MerchandiseReport, StockReport)):
        return render_inventory(summary), ConversationContext(
            branch_id=summary.branch.id,
            period=RevenuePeriod(start_date=summary.start_date, end_date=summary.end_date),
            metric="merchandise" if isinstance(summary, MerchandiseReport) else "stock",
        )
    if isinstance(summary, ReconciliationSummary):
        status = "Balanced" if summary.is_balanced else "Discrepancy"
        lines = [
            f"{summary.branch.name} — reconciliation for {summary.start_date}",
            f"Status: {status}",
            f"X: KES {summary.x_value:,.2f}",
            f"Y: KES {summary.y_value:,.2f}",
            f"Result (X + Y): KES {summary.result:,.2f}",
        ]
        if summary.is_provisional:
            lines.append("This result is provisional.")
        return "\n".join(lines), ConversationContext(
            branch_id=summary.branch.id,
            period=RevenuePeriod(start_date=summary.start_date, end_date=summary.end_date),
            metric="reconciliation",
        )
    if isinstance(summary, ProductReport):
        lines = [f"{summary.branch.name} — products by units sold ({format_period(summary)})"]
        lines.extend(f"{p.name}: {p.units_sold:,} units, KES {p.sales_value:,.2f}" for p in summary.products)
        if not summary.products:
            lines.append("No completed product sales were recorded.")
        if summary.is_provisional:
            lines.append("This result is provisional.")
        return "\n".join(lines), ConversationContext(
            branch_id=summary.branch.id,
            period=RevenuePeriod(start_date=summary.start_date, end_date=summary.end_date),
            metric="product performance",
        )
    if not isinstance(summary, (RevenueSummary, SalesSummary)):
        return UNAVAILABLE_REPLY, None
    context = ConversationContext(
        branch_id=summary.branch.id,
        period=RevenuePeriod(start_date=summary.start_date, end_date=summary.end_date),
        metric="sales" if isinstance(summary, SalesSummary) else "revenue",
    )
    if isinstance(summary, SalesSummary):
        lines = [
            f"{summary.branch.name} — {format_period(summary)}",
            f"Total fulfilled sales: KES {summary.total_sales:,.2f}",
        ]
        if summary.is_provisional:
            lines.append("This result is provisional.")
        if isinstance(summary, SalesBreakdown):
            lines.extend(sales_detail_lines(summary))
        return "\n".join(lines), context
    if isinstance(summary, DailyRevenueBreakdown):
        return render_daily_breakdown(summary), context
    if isinstance(summary, MonthlyRevenueBreakdown):
        return render_monthly_breakdown(summary), context
    totals = summary.totals
    lines = [
        f"{summary.branch.name} — {format_period(summary)}",
        f"Paybill: KES {totals.paybill:,.2f}",
        f"PDQ: KES {totals.pdq:,.2f}",
        f"Till: KES {totals.till:,.2f}",
        f"Total revenue: KES {totals.total_revenue:,.2f}",
    ]
    if summary.is_provisional:
        lines.append("This result is provisional.")
    return "\n".join(lines), context


async def deliver_reply(
    http: httpx.AsyncClient, settings: WhatsAppSettings, message: Message, answer: str
) -> str | None:
    """Return a safe diagnostic on failure, or None when Meta accepts the reply."""
    # Connect and pool failures happen before a request reaches Meta. A write
    # or read failure can mean Meta accepted the reply, so stop on those.
    safe_failures = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
    for delay in (0, 0.5, 1):
        if delay:
            await asyncio.sleep(delay)
        if time.time() >= message.timestamp + REPLY_WINDOW_SECONDS:
            return "The WhatsApp reply window closed before delivery."
        try:
            await send_reply(
                http, settings, recipient=message.sender, message_id=message.id, text=answer
            )
        except safe_failures:
            continue
        except httpx.HTTPStatusError as error:
            return describe_reply_rejection(error.response)
        except httpx.RequestError as error:
            return f"Delivery outcome is unknown ({type(error).__name__}). Check WhatsApp before resending."
        else:
            return None
    return "Could not connect to Meta after retrying. Check outbound connectivity."


def create_app(
    settings: WhatsAppSettings,
    branches: list[BranchConfig],
    model: str | Model | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Starlette:
    inbox = Inbox(settings.inbox_path)
    ready = asyncio.Event()

    async def work(http: httpx.AsyncClient, agent: Agent[RevenueClient, str]) -> None:
        while True:
            try:
                ready.clear()
                message = inbox.next_message()
                if message is None:
                    await ready.wait()
                    continue
                if message.sender not in settings.allowed_senders:
                    if inbox.reserve_reply(message.id):
                        inbox.finish_reply(message, sent=False, failure_reason="Sender is no longer allowed.")
                    continue

                try:
                    if reconciliation_needs_a_date(message.body):
                        answer, context = RECONCILIATION_DATE_REQUIRED, None
                    else:
                        sent_date = datetime.fromtimestamp(message.timestamp, NAIROBI).date()
                        client = RevenueClient(branches, http, clock=lambda: sent_date)
                        previous = inbox.get_context(message)
                        async with asyncio.timeout(75):
                            result = await run_question(agent, message.body, client, context=previous)
                        tool_parts = [
                            part
                            for exchange in result.new_messages()
                            for part in exchange.parts
                            if isinstance(part, ToolReturnPart)
                            and part.tool_name in {
                                "get_revenue", "compare_revenue", "get_sales", "get_reconciliation", "get_top_products",
                                "get_merchandise", "get_stock",
                            }
                        ]
                        answer, context = render_answer(tool_parts, branches)
                except UnexpectedModelBehavior as error:
                    cause = error.__cause__
                    feedback = (
                        date_validation_reply(cause.errors(include_input=False))
                        if isinstance(cause, ValidationError)
                        else None
                    )
                    if feedback is None:
                        logger.warning("BI agent request failed (%s)", type(error).__name__)
                    answer = feedback or UNAVAILABLE_REPLY
                    context = None
                except Exception as error:
                    logger.warning("BI agent request failed (%s)", type(error).__name__)
                    answer = UNAVAILABLE_REPLY
                    context = None

                if not inbox.reserve_reply(message.id):
                    continue
                failure_reason = "Reply attempt was interrupted. Delivery outcome is unknown."
                try:
                    failure_reason = await deliver_reply(http, settings, message, answer)
                finally:
                    if failure_reason:
                        logger.warning("WhatsApp reply failed. %s", failure_reason)
                    inbox.finish_reply(
                        message,
                        sent=failure_reason is None,
                        context=context,
                        failure_reason=failure_reason,
                    )
            except sqlite3.Error:
                logger.warning("WhatsApp inbox unavailable")
                await asyncio.sleep(1)

    @asynccontextmanager
    async def lifespan(_app):
        async with AsyncExitStack() as stack:
            http = await stack.enter_async_context(httpx.AsyncClient(transport=transport))
            selected_model = await stack.enter_async_context(configured_model()) if model is None else model
            agent = build_agent(selected_model)
            if isinstance(selected_model, Model):
                await stack.enter_async_context(agent)
            RevenueClient(branches, http)  # Validate branch configuration before accepting messages.
            worker = asyncio.create_task(work(http, agent))
            try:
                yield
            finally:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

    async def verify(request: Request) -> Response:
        query = request.query_params
        challenge = query.get("hub.challenge")
        token = query.get("hub.verify_token", "")
        if query.get("hub.mode") == "subscribe" and challenge and hmac.compare_digest(
            token.encode(), settings.verify_token.get_secret_value().encode()
        ):
            return PlainTextResponse(challenge)
        return Response(status_code=403)

    async def receive(request: Request) -> Response:
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not signature:
            return Response(status_code=403)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_WEBHOOK_BYTES:
                return Response(status_code=413)
            body.extend(chunk)
        if not valid_signature(body, signature, settings.app_secret):
            return Response(status_code=403)
        try:
            event = WebhookEvent.model_validate_json(body)
        except ValidationError:
            return Response(status_code=400)
        if event.object != "whatsapp_business_account":
            return Response()

        messages = [
            Message(message.id, message.sender, message.timestamp, message.text.body.strip())
            for entry in event.entry
            for change in entry.changes
            if change.field == "messages"
            and change.value.metadata
            and change.value.metadata.phone_number_id == settings.phone_number_id
            for message in change.value.messages
            if message.type == "text"
            and message.sender in settings.allowed_senders
            and message.text
            and 0 < len(message.text.body.strip()) <= TEXT_LIMIT
        ]
        if messages:
            try:
                inbox.enqueue(messages)
            except sqlite3.Error:
                logger.warning("Could not save incoming WhatsApp messages")
                return Response(status_code=503)
            ready.set()
        return Response()

    async def health(_request: Request) -> Response:
        return PlainTextResponse("ok")

    return Starlette(
        lifespan=lifespan,
        routes=[
            Route("/health/", health),
            Route("/webhooks/whatsapp/", verify, methods=["GET"]),
            Route("/webhooks/whatsapp/", receive, methods=["POST"]),
        ],
    )


def from_env() -> Starlette:
    load_dotenv()
    try:
        settings = WhatsAppSettings(
            app_secret=os.getenv("WHATSAPP_APP_SECRET", ""),
            verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN", ""),
            access_token=os.getenv("WHATSAPP_ACCESS_TOKEN", ""),
            phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
            allowed_senders=frozenset(
                part.strip()
                for part in os.getenv("WHATSAPP_ALLOWED_SENDERS", "").split(",")
                if part.strip()
            ),
            graph_version=os.getenv("WHATSAPP_GRAPH_VERSION", "v27.0"),
            inbox_path=Path(os.getenv("WHATSAPP_INBOX_PATH", "whatsapp-inbox.sqlite3")),
        )
    except ValidationError as error:
        names = ", ".join(str(item["loc"][0]).upper() for item in error.errors(include_input=False))
        raise ValueError(f"Check WhatsApp settings: {names}") from None
    path = Path(os.getenv("BI_BRANCH_CONFIG", "branches.json"))
    branches = TypeAdapter(list[BranchConfig]).validate_json(path.read_text())
    return create_app(settings, branches)
