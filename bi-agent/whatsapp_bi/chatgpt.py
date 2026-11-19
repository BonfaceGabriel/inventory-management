import asyncio
import json
import os
import tempfile
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import httpx2
from pydantic import TypeAdapter, ValidationError
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai_chatgpt import (
    OpenAIChatGPTCredentialSource,
    OpenAIChatGPTCredentials,
    OpenAIChatGPTOAuthFlow,
    OpenAIChatGPTProvider,
)

PROVIDER = "openai-chatgpt"
CREDENTIALS = TypeAdapter(OpenAIChatGPTCredentials)


class ChatGPTSession(OpenAIChatGPTCredentialSource):
    """Persist one user's rotating ChatGPT grant in a private directory."""

    def __init__(self):
        default = Path.home() / ".local" / "state" / "whatsapp-bi" / "chatgpt"
        self.directory = Path(os.getenv("BI_CHATGPT_STATE_DIR", str(default))).expanduser()
        self.credentials_path = self.directory / "session.json"

    def prepare(self) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.stat().st_uid != os.getuid() or self.directory.stat().st_mode & 0o077:
            raise ValueError("Use a ChatGPT session directory owned by this user with mode 0700.")

    def _write(self, path: Path, content: bytes) -> None:
        self.prepare()
        with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as temporary:
            temp_path = Path(temporary.name)
            try:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                os.replace(temp_path, path)
            finally:
                temp_path.unlink(missing_ok=True)

    def host_id(self) -> str:
        self.prepare()
        path = self.directory / "host-id"
        if not path.exists():
            self._write(path, uuid4().urn.encode())
        return path.read_text().strip()

    async def load(self) -> OpenAIChatGPTCredentials:
        self.prepare()
        if not self.credentials_path.exists():
            raise FileNotFoundError("Run whatsapp-bi chatgpt-login first.")
        info = self.credentials_path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Use a ChatGPT session file owned by this user with mode 0600.")
        try:
            return CREDENTIALS.validate_json(self.credentials_path.read_bytes())
        except ValidationError:
            raise ValueError("The ChatGPT session is invalid. Sign in again or use a new state directory.") from None

    async def save(self, credentials: OpenAIChatGPTCredentials) -> None:
        self._write(self.credentials_path, json.dumps(asdict(credentials)).encode())


class ChatGPTTransport(httpx2.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        # The plan route requires custom functions to be in a namespace.
        # Pydantic AI round-trips that namespace on the returned tool call.
        if request.method == "POST" and request.url == "https://api.openai.com/v1/responses":
            payload = json.loads(await request.aread())
            tools = payload.get("tools") or []
            functions = [tool for tool in tools if tool["type"] == "function"]
            if functions:
                payload["tools"] = [tool for tool in tools if tool["type"] != "function"] + [
                    {
                        "type": "namespace",
                        "name": "inventory",
                        "description": "Read verified inventory revenue.",
                        "tools": functions,
                    }
                ]
                headers = request.headers.copy()
                headers.pop("content-length", None)
                request = httpx2.Request(
                    request.method, request.url, headers=headers, json=payload,
                    extensions=request.extensions,
                )
        return await super().handle_async_request(request)


@asynccontextmanager
async def configured_model():
    selection = os.getenv("BI_MODEL", "openai:gpt-5-mini")
    prefix, _, name = selection.partition(":")
    if prefix != PROVIDER:
        yield selection
        return
    session = ChatGPTSession()
    if not session.credentials_path.is_file():
        raise ValueError("Run whatsapp-bi chatgpt-login before selecting a ChatGPT model.")
    if not name:
        raise ValueError("Select a model listed by whatsapp-bi chatgpt-models.")
    credentials = await session.load()
    if not credentials.plan_usage_granted:
        raise ValueError("Run whatsapp-bi chatgpt-login and approve ChatGPT plan usage.")
    async with httpx2.AsyncClient(transport=ChatGPTTransport()) as http:
        provider = OpenAIChatGPTProvider(credential_source=session, http_client=http)
        yield OpenAIResponsesModel(name, provider=provider)


async def chatgpt_login(port: int) -> None:
    session = ChatGPTSession()
    try:
        previous = await session.load()
    except FileNotFoundError:
        previous = None
    flow = OpenAIChatGPTOAuthFlow(
        app_name="WhatsApp BI",
        host_id=session.host_id(),
        client_id=previous.client_id if previous else None,
        redirect_uri=f"http://127.0.0.1:{port}/auth/callback",
    )
    params = {"prompt": "consent"} if previous and not previous.plan_usage_granted else None
    print("Open this URL on this computer and approve ChatGPT plan usage.", flush=True)
    print(flow.authorization_url(extra_params=params), flush=True)
    async with asyncio.timeout(180):
        credentials = await flow.exchange_code_from_callback()
    await session.save(credentials)
    if not credentials.plan_usage_granted:
        raise ValueError("ChatGPT sign-in completed without permission to use your plan.")
    print("ChatGPT plan connected. Run whatsapp-bi chatgpt-models to list available models.")


async def chatgpt_models() -> None:
    async with OpenAIChatGPTProvider(credential_source=ChatGPTSession()) as provider:
        catalog = await provider.client.get("/models", cast_to=dict)
    for model in catalog["models"]:
        if model.get("visibility") == "list":
            print(f"{PROVIDER}:{model['slug']}")
