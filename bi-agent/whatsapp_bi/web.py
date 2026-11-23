import asyncio
import hmac
import logging
import os
import sqlite3
import time
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import TypeAdapter, ValidationError
from pydantic_ai import Agent
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models import Model
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from .agent import build_agent, run_question
from .chatgpt import configured_model
from .client import RevenueClient
from .inbox import REPLY_WINDOW_SECONDS, Inbox, Message
from .models import (
    NAIROBI,
    BranchConfig,
    ConversationContext,
    RevenueComparison,
    RevenuePeriod,
    RevenueProblem,
    RevenueSummary,
)
from .whatsapp import TEXT_LIMIT, WebhookEvent, WhatsAppSettings, send_reply, valid_signature

logger = logging.getLogger(__name__)
MAX_WEBHOOK_BYTES = 1024 * 1024
UNAVAILABLE_REPLY = "I couldn't get a verified revenue answer right now. Please try again."


def format_period(summary: RevenueSummary) -> str:
    if summary.end_date == summary.start_date:
        return str(summary.start_date)
    return f"{summary.start_date} to {summary.end_date}"


def render_answer(
    parts: list[ToolReturnPart], branches: list[BranchConfig]
) -> tuple[str, ConversationContext | None]:
    if not parts:
        names = ", ".join(branch.name for branch in branches)
        return f"Ask for one branch's revenue and include a date or date range. Branches: {names}.", None

    if any(isinstance(part.content, RevenueProblem) for part in parts):
        return UNAVAILABLE_REPLY, None
    if len(parts) != 1:
        return "Ask for one branch's revenue or a comparison between two periods at that branch.", None

    summary = parts[0].content
    if isinstance(summary, RevenueComparison):
        lines = [summary.period.branch.name]
        for label, item in (("Period", summary.period), ("Baseline", summary.baseline)):
            status = " (provisional)" if item.is_provisional else ""
            lines.append(
                f"{label} ({format_period(item)}): KES {item.totals.total_revenue:,.2f}{status}"
            )
        change = summary.change
        lines.append(f"Change: KES {change:+,.2f}" if change else "Change: KES 0.00")
        # A comparison has two date ranges. Keep the shared branch for follow-ups.
        return "\n".join(lines), ConversationContext(branch_id=summary.period.branch.id)
    if not isinstance(summary, RevenueSummary):
        return UNAVAILABLE_REPLY, None
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
    context = ConversationContext(
        branch_id=summary.branch.id,
        period=RevenuePeriod(start_date=summary.start_date, end_date=summary.end_date),
    )
    return "\n".join(lines), context


async def deliver_reply(
    http: httpx.AsyncClient, settings: WhatsAppSettings, message: Message, answer: str
) -> bool:
    # Connect and pool failures happen before a request reaches Meta. A write
    # or read failure can mean Meta accepted the reply, so stop on those.
    safe_failures = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
    for delay in (0, 0.5, 1):
        if delay:
            await asyncio.sleep(delay)
        if time.time() >= message.timestamp + REPLY_WINDOW_SECONDS:
            return False
        try:
            await send_reply(
                http, settings, recipient=message.sender, message_id=message.id, text=answer
            )
        except safe_failures as error:
            logger.warning("WhatsApp connection failed before delivery (%s)", type(error).__name__)
        except httpx.HTTPStatusError as error:
            logger.warning("WhatsApp reply rejected (HTTP %s)", error.response.status_code)
            return False
        except httpx.RequestError as error:
            logger.warning("WhatsApp reply outcome unknown (%s)", type(error).__name__)
            return False
        else:
            return True
    return False


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
                        inbox.finish_reply(message, sent=False)
                    continue

                try:
                    sent_date = datetime.fromtimestamp(message.timestamp, NAIROBI).date()
                    client = RevenueClient(branches, http, clock=lambda: sent_date)
                    previous = inbox.get_context(message)
                    async with asyncio.timeout(75):
                        result = await run_question(agent, message.body, client, context=previous)
                    tool_returns = [
                        part
                        for exchange in result.new_messages()
                        for part in exchange.parts
                        if isinstance(part, ToolReturnPart)
                        and part.tool_name in {"get_revenue", "compare_revenue"}
                    ]
                    answer, context = render_answer(tool_returns, branches)
                except Exception as error:
                    logger.warning("Revenue agent request failed (%s)", type(error).__name__)
                    answer = UNAVAILABLE_REPLY
                    context = None

                if not inbox.reserve_reply(message.id):
                    continue
                sent = False
                try:
                    sent = await deliver_reply(http, settings, message, answer)
                finally:
                    inbox.finish_reply(message, sent=sent, context=context)
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
