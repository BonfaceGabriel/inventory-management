import json
import stat
from datetime import date
from decimal import Decimal

import httpx
import httpx2
import pytest
from pydantic_ai import models
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.providers.openai_chatgpt import OpenAIChatGPTCredentials

from whatsapp_bi.agent import build_agent, run_question
from whatsapp_bi.chatgpt import ChatGPTSession, configured_model
from whatsapp_bi.client import RevenueClient
from whatsapp_bi.models import BranchConfig, DailyRevenueBreakdown, RevenueComparison, RevenueSummary


@pytest.mark.parametrize("view", ["total", "daily", "comparison"])
async def test_subscription_model_sends_streaming_namespaced_tool_requests(
    monkeypatch, tmp_path, view
):
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
    period_day, baseline_day = "2026-11-17", "2026-11-16"
    period = {"start_date": period_day, "end_date": period_day}
    baseline = {"start_date": baseline_day, "end_date": baseline_day}
    arguments = {"branch": "Kitengela"}
    tool_name = "compare_revenue" if view == "comparison" else "get_revenue"
    if tool_name == "compare_revenue":
        arguments.update(period=period, baseline=baseline)
        question = "Compare Kitengela revenue for 17 November and 16 November 2026."
        answer = "Kitengela's revenue increased by KES 100.50."
    else:
        arguments.update(period)
        question = "What was Kitengela's revenue on 17 November 2026?"
        answer = "Kitengela received KES 250.00."
        if view == "daily":
            arguments["breakdown"] = "daily"
            question = "List Kitengela's daily revenue for 17 November 2026."
    tool = {
        "id": "fc_1", "type": "function_call", "status": "completed",
        "namespace": "inventory", "name": tool_name, "call_id": "call_1",
        "arguments": json.dumps(arguments),
    }
    text = {
        "id": "msg_2", "type": "message", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": answer, "annotations": []}],
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
        assert {function["name"] for function in namespace["tools"]} == {
            "get_revenue", "compare_revenue", "get_sales", "get_reconciliation", "get_top_products",
            "get_merchandise", "get_stock",
            "get_branch_growth",
            "get_registrations",
            "get_briefing",
        }
        if len(requests) == 2:
            output, = (item for item in body["input"] if item.get("type") == "function_call_output")
            assert output["call_id"] == tool["call_id"]
            result = json.loads(output["output"])
            if tool_name == "compare_revenue":
                assert result["period"]["totals"]["total_revenue"] == "250.00"
                assert result["baseline"]["totals"]["total_revenue"] == "149.50"
                assert result["change"] == "100.50"
            else:
                assert result["totals"] == totals
                if view == "daily":
                    assert result["days"] == [{"date": period_day, "total_revenue": "250.00"}]
                    assert result["trend"] is None
                else:
                    assert "days" not in result
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
                "type": "response.output_text.delta", "delta": answer,
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
    days = []

    def revenue_handler(request):
        assert request.url.host == "kitengela.example"
        assert request.headers["authorization"] == "Bearer fake-bi-token"
        day = request.url.params["start_date"]
        assert request.url.params["end_date"] == day
        days.append(day)
        daily_totals = totals if day == period_day else {
            **totals, "paybill": "0.00", "total_revenue": "149.50", "transaction_count": 1,
        }
        return httpx.Response(200, json={
            "schema_version": 1, "branch": {"id": "kitengela", "name": "Kitengela"},
            "start_date": day, "end_date": day,
            "timezone": "Africa/Nairobi", "currency": "KES",
            "generated_at": "2026-11-18T08:00:00Z", "is_provisional": False,
            "totals": daily_totals, "daily": [{"date": day, **daily_totals}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(revenue_handler)) as revenue_http:
        async with configured_model() as model, build_agent(model) as agent:
            client = RevenueClient([branch], revenue_http, clock=lambda: date(2026, 11, 18))
            run = await run_question(agent, question, client)
    returns = [part.content for message in run.new_messages() for part in message.parts
               if isinstance(part, ToolReturnPart)]
    result, = returns
    if tool_name == "compare_revenue":
        assert days == [period_day, baseline_day]
        assert isinstance(result, RevenueComparison)
        assert result.change == Decimal("100.50")
    else:
        assert days == [period_day]
        assert type(result) is (DailyRevenueBreakdown if view == "daily" else RevenueSummary)
        assert result.totals.model_dump(mode="json") == totals
    assert len(requests) == 2
    assert run.output == answer


async def test_session_rejects_permissive_credentials_file(monkeypatch, tmp_path):
    monkeypatch.setenv("BI_CHATGPT_STATE_DIR", str(tmp_path / "private"))
    session = ChatGPTSession()
    await session.save(OpenAIChatGPTCredentials(
        client_id="fake-client", access_token="fake", refresh_token="fake",
    ))
    session.credentials_path.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        await session.load()
