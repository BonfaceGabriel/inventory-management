import json
import stat
from datetime import date

import httpx
import httpx2
import pytest
from pydantic_ai import models
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.providers.openai_chatgpt import OpenAIChatGPTCredentials

from whatsapp_bi.agent import build_agent, run_question
from whatsapp_bi.chatgpt import ChatGPTSession, configured_model
from whatsapp_bi.client import RevenueClient
from whatsapp_bi.models import BranchConfig, RevenueSummary


async def test_subscription_model_sends_streaming_namespaced_tool_requests(monkeypatch, tmp_path):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    monkeypatch.setenv("BI_MODEL", "openai-chatgpt:gpt-6.1-sol")
    monkeypatch.setenv("BI_CHATGPT_STATE_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("OPENAI_API_KEY", "unused-project-key")
    monkeypatch.setenv("KITENGELA_TEST_TOKEN", "fake-bi-token")

    session = ChatGPTSession()
    host = session.host_id()
    credentials = OpenAIChatGPTCredentials(
        client_id="fake-client", access_token="fake-oauth-token",
        refresh_token="fake-refresh-token", scope="chatgpt.tokens.use.direct",
    )
    await session.save(credentials)
    assert stat.S_IMODE(session.credentials_path.stat().st_mode) == 0o600
    assert await ChatGPTSession().load() == credentials
    assert ChatGPTSession().host_id() == host

    requests = []
    totals = {
        "paybill": "100.50", "pdq": "0.00", "till": "149.50",
        "total_revenue": "250.00", "transaction_count": 2,
    }
    tool = {
        "id": "fc_1", "type": "function_call", "status": "completed",
        "namespace": "inventory", "name": "get_revenue", "call_id": "call_1",
        "arguments": json.dumps({"branch": "Kitengela", "start_date": "2026-11-17", "end_date": "2026-11-17"}),
    }
    text = {
        "id": "msg_2", "type": "message", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": "Kitengela received KES 250.00.", "annotations": []}],
    }

    async def upstream(_transport, request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer fake-oauth-token"
        body = json.loads(await request.aread())
        requests.append(body)
        assert body["stream"] is True and body["store"] is False
        assert "previous_response_id" not in body
        namespace, = body["tools"]
        assert namespace["type"] == "namespace" and namespace["name"] == "inventory"
        assert [function["name"] for function in namespace["tools"]] == ["get_revenue"]
        if len(requests) == 2:
            assert any(item.get("type") == "function_call_output" for item in body["input"])
            assert any(item.get("type") == "function_call" and item.get("namespace") == "inventory"
                       for item in body["input"])
        item = tool if len(requests) == 1 else text
        response = {
            "id": f"resp_{len(requests)}", "object": "response", "created_at": 1795000000,
            "model": "gpt-6.1-sol", "status": "completed", "output": [item],
        }
        events = [{"type": "response.output_item.added", "item": item, "output_index": 0}]
        if item is text:
            events.append({
                "type": "response.output_text.delta", "delta": "Kitengela received KES 250.00.",
                "item_id": item["id"], "output_index": 0, "content_index": 0, "logprobs": [],
            })
        events.extend([
            {"type": "response.output_item.done", "item": item, "output_index": 0},
            {"type": "response.completed", "response": response},
        ])
        for sequence, event in enumerate(events):
            event["sequence_number"] = sequence
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"},
            text="".join(f"data: {json.dumps(event)}\n\n" for event in events),
        )

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", upstream)
    branch = BranchConfig(
        id="kitengela", name="Kitengela", base_url="https://kitengela.example/api/v1/",
        token_env="KITENGELA_TEST_TOKEN",
    )
    def revenue_handler(request):
        assert request.url.host == "kitengela.example"
        assert request.headers["authorization"] == "Bearer fake-bi-token"
        return httpx.Response(200, json={
            "schema_version": 1, "branch": {"id": "kitengela", "name": "Kitengela"},
            "start_date": "2026-11-17", "end_date": "2026-11-17",
            "timezone": "Africa/Nairobi", "currency": "KES",
            "generated_at": "2026-11-18T08:00:00Z", "is_provisional": False,
            "totals": totals, "daily": [{"date": "2026-11-17", **totals}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(revenue_handler)) as revenue_http:
        async with configured_model() as model, build_agent(model) as agent:
            client = RevenueClient([branch], revenue_http, clock=lambda: date(2026, 11, 18))
            run = await run_question(agent, "What was Kitengela's revenue on 17 November 2026?", client)
    returns = [part.content for message in run.new_messages() for part in message.parts
               if isinstance(part, ToolReturnPart)]
    assert len(returns) == 1 and isinstance(returns[0], RevenueSummary)
    assert returns[0].totals.model_dump(mode="json") == totals
    assert len(requests) == 2
    assert run.output == "Kitengela received KES 250.00."


async def test_session_rejects_permissive_credentials_file(monkeypatch, tmp_path):
    monkeypatch.setenv("BI_CHATGPT_STATE_DIR", str(tmp_path / "private"))
    session = ChatGPTSession()
    await session.save(OpenAIChatGPTCredentials(
        client_id="fake-client", access_token="fake", refresh_token="fake",
    ))
    session.credentials_path.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        await session.load()
