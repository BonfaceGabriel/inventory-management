import hmac
import os
from pathlib import Path
from typing import Annotated

import httpx
from pydantic import BaseModel, Field, SecretStr, ValidationError

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

    @classmethod
    def from_env(cls) -> "WhatsAppSettings":
        try:
            return cls(
                app_secret=os.getenv("WHATSAPP_APP_SECRET", ""),
                verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN", ""),
                access_token=os.getenv("WHATSAPP_ACCESS_TOKEN", ""),
                phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
                allowed_senders=frozenset(
                    part.strip() for part in os.getenv("WHATSAPP_ALLOWED_SENDERS", "").split(",") if part.strip()
                ),
                graph_version=os.getenv("WHATSAPP_GRAPH_VERSION", "v27.0"),
                inbox_path=Path(os.getenv("WHATSAPP_INBOX_PATH", "whatsapp-inbox.sqlite3")),
            )
        except ValidationError as error:
            names = ", ".join(str(item["loc"][0]).upper() for item in error.errors(include_input=False))
            raise ValueError(f"Check WhatsApp settings: {names}") from None


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


def describe_reply_rejection(response: httpx.Response) -> str:
    status = response.status_code
    details = [f"HTTP {status}"]
    try:
        payload = response.json()
    except ValueError:
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    subcode = error.get("error_subcode") if isinstance(error, dict) else None
    if type(code) is int:
        details.append(f"Meta code {code}")
    if type(subcode) is int:
        details.append(f"subcode {subcode}")
    context = ", ".join(details)

    if status == 401 or code == 190:
        return (
            f"Meta rejected the WhatsApp access token ({context}). "
            "Check WHATSAPP_ACCESS_TOKEN in Dokploy, replace it if needed, and redeploy BI."
        )
    if status == 403:
        return f"Meta denied permission to send ({context}). Check the app, number, and messaging permissions."
    if status == 429:
        return f"Meta rate-limited the reply ({context}). Wait before sending another test message."
    return f"Meta rejected the reply ({context})."


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
