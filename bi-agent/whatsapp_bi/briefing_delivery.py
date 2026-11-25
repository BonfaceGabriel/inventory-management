import asyncio
import logging
import os
import sqlite3
from datetime import date, datetime, time, timedelta
from hashlib import sha256

import httpx
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from .branch_directory import BranchDirectory, BranchDiscoveryError
from .briefing import BriefingDocument, build_briefing
from .briefing_pdf import render_briefing_pdf
from .client import RevenueClient
from .inbox import Inbox
from .models import NAIROBI
from .whatsapp import PHONE_NUMBER, WhatsAppSettings, describe_reply_rejection

logger = logging.getLogger(__name__)
BRIEFING_TIME = time(23, 59, 59)
RESTART_GRACE = timedelta(minutes=10)


class BriefingDeliveryError(ValueError):
    """An operator-facing scheduled briefing error."""


class BriefingDeliverySettings(BaseModel):
    recipient: PHONE_NUMBER
    template: str = Field(pattern=r"^[a-z0-9_]+$", max_length=512)
    language: str = Field(default="en_US", pattern=r"^[a-z]{2,3}(?:_[A-Z]{2})?$")

    @classmethod
    def from_env(cls) -> "BriefingDeliverySettings":
        try:
            return cls(
                recipient=os.getenv("WHATSAPP_BRIEFING_RECIPIENT", "").strip(),
                template=os.getenv("WHATSAPP_BRIEFING_TEMPLATE", "").strip(),
                language=os.getenv("WHATSAPP_BRIEFING_LANGUAGE", "en_US").strip(),
            )
        except ValidationError:
            raise BriefingDeliveryError("Check the WhatsApp briefing recipient, template name and language.") from None

    @classmethod
    def scheduled_from_env(cls) -> "BriefingDeliverySettings | None":
        try:
            enabled = TypeAdapter(bool).validate_python(os.getenv("WHATSAPP_BRIEFING_ENABLED", "false"))
        except ValidationError:
            raise BriefingDeliveryError("Set WHATSAPP_BRIEFING_ENABLED to true or false.") from None
        return cls.from_env() if enabled else None

    def verify_recipient(self, whatsapp: WhatsAppSettings) -> None:
        if self.recipient not in whatsapp.allowed_senders:
            raise BriefingDeliveryError("The briefing recipient must be in WHATSAPP_ALLOWED_SENDERS.")


def due_briefing_day(now: datetime) -> date | None:
    now = now.astimezone(NAIROBI)
    slot = datetime.combine(now.date(), BRIEFING_TIME, NAIROBI)
    if now < slot:
        slot -= timedelta(days=1)
    return slot.date() if now - slot < RESTART_GRACE else None


def next_briefing_time(now: datetime) -> datetime:
    now = now.astimezone(NAIROBI)
    slot = datetime.combine(now.date(), BRIEFING_TIME, NAIROBI)
    return slot if slot > now else slot + timedelta(days=1)


class BriefingDelivery:
    def __init__(self, whatsapp: WhatsAppSettings, config: BriefingDeliverySettings, inbox: Inbox):
        config.verify_recipient(whatsapp)
        self.config = config
        self.inbox = inbox
        self.recipient_key = sha256(config.recipient.encode()).hexdigest()
        self.graph_url = f"https://graph.facebook.com/{whatsapp.graph_version}/{whatsapp.phone_number_id}"
        self.headers = {"Authorization": f"Bearer {whatsapp.access_token.get_secret_value()}"}

    async def _upload_pdf(self, http: httpx.AsyncClient, filename: str, content: bytes) -> str:
        try:
            response = await http.post(
                f"{self.graph_url}/media", headers=self.headers,
                data={"messaging_product": "whatsapp", "type": "application/pdf"},
                files={"file": (filename, content, "application/pdf")},
                timeout=30.0, follow_redirects=False,
            )
            response.raise_for_status()
            media_id = response.json().get("id")
        except httpx.HTTPStatusError as error:
            raise BriefingDeliveryError(f"Briefing PDF upload failed. {describe_reply_rejection(error.response)}") from None
        except (httpx.RequestError, AttributeError, ValueError):
            raise BriefingDeliveryError("Briefing PDF upload failed before sending the message.") from None
        if not isinstance(media_id, str) or not media_id:
            raise BriefingDeliveryError("Meta did not return a PDF media ID.")
        return media_id

    def _message(self, report: BriefingDocument, media_id: str, filename: str) -> dict:
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self.config.recipient,
            "type": "template",
            "template": {
                "name": self.config.template,
                "language": {"code": self.config.language},
                "components": [
                    {"type": "header", "parameters": [{
                        "type": "document", "document": {"id": media_id, "filename": filename},
                    }]},
                    {"type": "body", "parameters": [
                        {"type": "text", "text": value} for value in report.chat_values
                    ]},
                ],
            },
        }

    async def deliver(self, client: RevenueClient, day: date, *, retry_rejected: bool = False) -> str:
        report_date = day.isoformat()
        state = self.inbox.briefing_state(report_date, self.recipient_key)
        if state is not None and (state != "rejected" or not retry_rejected):
            return state

        report = await build_briefing(client, day)
        filename = f"inventory-briefing-{report_date}.pdf"
        content = await asyncio.to_thread(render_briefing_pdf, report)
        media_id = await self._upload_pdf(client.http, filename, content)
        if not self.inbox.reserve_briefing(report_date, self.recipient_key, retry_rejected=retry_rejected):
            return self.inbox.briefing_state(report_date, self.recipient_key) or "sending"

        # Reserve before the send. A timeout or process exit can leave delivery
        # uncertain, so these attempts must never be replayed automatically.
        state = "unknown"
        try:
            response = await client.http.post(
                f"{self.graph_url}/messages", headers=self.headers,
                json=self._message(report, media_id, filename),
                timeout=15.0, follow_redirects=False,
            )
            response.raise_for_status()
            message_id = response.json()["messages"][0]["id"]
            if not isinstance(message_id, str) or not message_id:
                raise ValueError("Missing message ID")
            state = "sent"
        except httpx.HTTPStatusError as error:
            if 400 <= error.response.status_code < 500:
                state = "rejected"
            raise BriefingDeliveryError(describe_reply_rejection(error.response)) from None
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            state = "rejected"
            raise BriefingDeliveryError("Could not connect to Meta before sending the briefing.") from None
        except (httpx.RequestError, ValueError, KeyError, TypeError, IndexError):
            raise BriefingDeliveryError("The briefing delivery outcome is unknown. Check WhatsApp before another send.") from None
        finally:
            self.inbox.finish_briefing(report_date, self.recipient_key, state)
        return state

    async def run(self, directory: BranchDirectory, http: httpx.AsyncClient) -> None:
        while True:
            now = datetime.now(NAIROBI)
            day = due_briefing_day(now)
            if day is not None:
                try:
                    if self.inbox.briefing_state(day.isoformat(), self.recipient_key) is None:
                        midnight = datetime.combine(day + timedelta(days=1), time.min, NAIROBI)
                        await asyncio.sleep(max(0, (midnight - now).total_seconds()))
                        async with asyncio.timeout(180):
                            client = RevenueClient(await directory.load(http), http)
                            outcome = await self.deliver(client, day)
                        logger.info("Scheduled briefing %s: %s", day, outcome)
                except (sqlite3.Error, TimeoutError, ValueError) as error:
                    logger.warning("Scheduled briefing %s could not finish: %s", day, type(error).__name__)
                    if isinstance(error, (BriefingDeliveryError, BranchDiscoveryError)):
                        logger.warning("%s", error)
                    await asyncio.sleep(30)
                    continue
            now = datetime.now(NAIROBI)
            await asyncio.sleep((next_briefing_time(now) - now).total_seconds())
