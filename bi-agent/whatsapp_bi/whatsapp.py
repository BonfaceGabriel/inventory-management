import hmac
from pathlib import Path
from typing import Annotated

import httpx
from pydantic import BaseModel, Field, SecretStr

PHONE_NUMBER = Annotated[str, Field(pattern=r"^[1-9][0-9]{5,14}$")]
TEXT_LIMIT = 4096


class WhatsAppSettings(BaseModel):
    app_secret: SecretStr = Field(min_length=1)
    verify_token: SecretStr = Field(min_length=1)
    access_token: SecretStr = Field(min_length=1)
    phone_number_id: str = Field(pattern=r"^[0-9]+$")
    allowed_senders: frozenset[PHONE_NUMBER] = Field(min_length=1)
    graph_version: str = Field(default="v27.0", pattern=r"^v[0-9]+\.[0-9]+$")
    inbox_path: Path = Path("whatsapp-inbox.sqlite3")


class TextContent(BaseModel):
    body: str


class InboundMessage(BaseModel):
    id: str = Field(min_length=1, max_length=1024)
    sender: str | None = Field(default=None, alias="from")
    timestamp: int = Field(ge=0, le=2**63 - 1)
    type: str
    text: TextContent | None = None


class Metadata(BaseModel):
    phone_number_id: str


class ChangeValue(BaseModel):
    metadata: Metadata | None = None
    messages: list[InboundMessage] = Field(default_factory=list)


class Change(BaseModel):
    field: str
    value: ChangeValue


class Entry(BaseModel):
    changes: list[Change] = Field(default_factory=list)


class WebhookEvent(BaseModel):
    object: str
    entry: list[Entry] = Field(default_factory=list)


def valid_signature(body: bytes, signature: str, secret: SecretStr) -> bool:
    digest = hmac.digest(secret.get_secret_value().encode(), body, "sha256").hex()
    return hmac.compare_digest(signature.encode(), f"sha256={digest}".encode())


async def send_reply(
    http: httpx.AsyncClient,
    settings: WhatsAppSettings,
    *,
    recipient: str,
    message_id: str,
    text: str,
) -> None:
    if len(text) > TEXT_LIMIT:
        text = text[: TEXT_LIMIT - 1] + "…"
    response = await http.post(
        f"https://graph.facebook.com/{settings.graph_version}/{settings.phone_number_id}/messages",
        headers={"Authorization": f"Bearer {settings.access_token.get_secret_value()}"},
        json={
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "context": {"message_id": message_id},
            "text": {"body": text},
        },
        timeout=15.0,
        follow_redirects=False,
    )
    response.raise_for_status()
