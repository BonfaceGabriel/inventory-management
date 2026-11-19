import asyncio
import hmac
import logging
import os
import sqlite3
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import TypeAdapter, ValidationError
from pydantic_ai.models import Model
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from .agent import build_agent, run_question
from .client import RevenueClient
from .inbox import Inbox, Message
from .models import BranchConfig
from .whatsapp import TEXT_LIMIT, WebhookEvent, WhatsAppSettings, send_reply, valid_signature

logger = logging.getLogger(__name__)
MAX_WEBHOOK_BYTES = 1024 * 1024
UNAVAILABLE_REPLY = "I couldn't get a verified revenue answer right now. Please try again."


def create_app(
    settings: WhatsAppSettings,
    branches: list[BranchConfig],
    model: str | Model = "openai:gpt-5-mini",
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Starlette:
    agent = build_agent(model)
    inbox = Inbox(settings.inbox_path)
    ready = asyncio.Event()

    async def work(http: httpx.AsyncClient, client: RevenueClient) -> None:
        while True:
            try:
                ready.clear()
                message = inbox.next_message()
                if message is None:
                    await ready.wait()
                    continue
                if message.sender not in settings.allowed_senders:
                    if inbox.reserve_reply(message.id):
                        inbox.finish_reply(message.id, sent=False)
                    continue

                try:
                    async with asyncio.timeout(75):
                        result = await run_question(agent, message.body, client)
                    answer = result.output.strip() or UNAVAILABLE_REPLY
                except Exception as error:
                    logger.warning("Revenue agent request failed (%s)", type(error).__name__)
                    answer = UNAVAILABLE_REPLY

                if not inbox.reserve_reply(message.id):
                    continue
                sent = False
                try:
                    await send_reply(
                        http, settings, recipient=message.sender, message_id=message.id, text=answer
                    )
                    sent = True
                except httpx.HTTPStatusError as error:
                    logger.warning("WhatsApp reply rejected (HTTP %s)", error.response.status_code)
                except httpx.RequestError as error:
                    logger.warning("WhatsApp reply outcome unknown (%s)", type(error).__name__)
                finally:
                    inbox.finish_reply(message.id, sent=sent)
            except sqlite3.Error:
                logger.warning("WhatsApp inbox unavailable")
                await asyncio.sleep(1)

    @asynccontextmanager
    async def lifespan(_app):
        async with httpx.AsyncClient(transport=transport) as http:
            client = RevenueClient(branches, http)
            worker = asyncio.create_task(work(http, client))
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
    return create_app(settings, branches, os.getenv("BI_MODEL", "openai:gpt-5-mini"))
