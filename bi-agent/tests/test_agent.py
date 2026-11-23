from datetime import date
from decimal import Decimal

import httpx
import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from whatsapp_bi.agent import build_agent, run_question
from whatsapp_bi.client import RevenueClient
from whatsapp_bi.models import BranchConfig, ConversationContext, RevenuePeriod, RevenueProblem, RevenueTrend
from whatsapp_bi.web import render_answer

models.ALLOW_MODEL_REQUESTS = False


async def test_agent_calls_authenticated_client_with_typed_dependencies():
    received = []

    def http_handler(request):
        received.append(request)
        return httpx.Response(
            200,
            json={
                "schema_version": 1,
                "branch": {"id": "kitengela", "name": "Kitengela"},
                "start_date": "2026-06-16",
                "end_date": "2026-06-16",
                "timezone": "Africa/Nairobi",
                "currency": "KES",
                "generated_at": "2026-06-17T08:00:00Z",
                "is_provisional": False,
                "totals": {
                    "paybill": "100.00",
                    "pdq": "200.00",
                    "till": "300.00",
                    "total_revenue": "600.00",
                    "transaction_count": 3,
                },
                "daily": [
                    {
                        "date": "2026-06-16",
                        "paybill": "100.00",
                        "pdq": "200.00",
                        "till": "300.00",
                        "total_revenue": "600.00",
                        "transaction_count": 3,
                    }
                ],
            },
        )

    def model(messages, info):
        results = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if results:
            result = results[-1].content
            assert str(result.totals.total_revenue) == "600.00"
            assert not hasattr(result, "daily")
            return ModelResponse(
                parts=[TextPart("Kitengela, 16 June 2026: KES 600.00.")]
            )
        assert {tool.name for tool in info.function_tools} == {
            "get_revenue", "compare_revenue", "get_sales", "get_reconciliation", "get_top_products",
        }
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "get_revenue",
                    {
                        "branch": "Kitengela",
                        "start_date": "2026-06-16",
                        "end_date": "2026-06-16",
                    },
                )
            ]
        )

    branch = BranchConfig(
        id="kitengela",
        name="Kitengela",
        base_url="https://kitengela.example/api/v1/",
        token_env="TOKEN",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(http_handler)) as http:
        client = RevenueClient(
            [branch],
            http,
            token_lookup=lambda _: "test-secret",
            clock=lambda: date(2026, 6, 17),
        )
        agent = build_agent(FunctionModel(model))
        result = await agent.run("What was Kitengela's revenue yesterday?", deps=client)
    assert result.output.endswith("KES 600.00.")
    assert len(received) == 1
    assert received[0].headers["Authorization"] == "Bearer test-secret"


async def test_agent_defines_last_week_and_rolling_windows_separately():
    def model(_messages, info):
        assert "previous Monday through Sunday, 2026-11-16 through 2026-11-22" in info.instructions
        assert "last seven completed reporting days, 2026-11-18 through 2026-11-24" in info.instructions
        assert "Last 7 days including today means 2026-11-19 through 2026-11-25" in info.instructions
        return ModelResponse(parts=[TextPart("Done.")])

    branch = BranchConfig(
        id="kitengela", name="Kitengela", base_url="https://kitengela.example/api/v1/", token_env="TOKEN",
    )
    async with httpx.AsyncClient() as http:
        client = RevenueClient([branch], http, clock=lambda: date(2026, 11, 25))
        await build_agent(FunctionModel(model)).run("What was Kitengela's revenue last week?", deps=client)


@pytest.mark.parametrize(
    ("phrase", "period"),
    [
        ("the last 3 days", "2026-11-20 through 2026-11-22"),
        ("last 3 days including today", "2026-11-21 through 2026-11-23"),
        ("last 3 days of October", "last 3 days of October"),
    ],
)
async def test_agent_resolves_unqualified_rolling_days_from_nairobi_date(phrase, period):
    def model(messages, info):
        assert messages[-1].parts[0].content == f"Show Kitengela revenue for {period}."
        assert "Use breakdown=total for a revenue total over any date range" in info.instructions
        return ModelResponse(parts=[TextPart("Done.")])

    branch = BranchConfig(
        id="kitengela", name="Kitengela", base_url="https://kitengela.example/api/v1/", token_env="TOKEN",
    )
    async with httpx.AsyncClient() as http:
        client = RevenueClient([branch], http, clock=lambda: date(2026, 11, 23))
        await run_question(build_agent(FunctionModel(model)), f"Show Kitengela revenue for {phrase}.", client)


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [("112", "100", "12.00"), ("0", "100", "-100.00"), ("12", "0", None), ("0", "0", "0")],
)
def test_revenue_trend_uses_decimal_and_handles_zero_baselines(current, previous, expected):
    trend = RevenueTrend(
        latest=RevenuePeriod(start_date=date(2026, 11, 8), end_date=date(2026, 11, 14)),
        previous=RevenuePeriod(start_date=date(2026, 11, 1), end_date=date(2026, 11, 7)),
        latest_total=Decimal(current),
        previous_total=Decimal(previous),
    )
    assert trend.percent_change == (Decimal(expected) if expected is not None else None)
    assert trend.change == Decimal(current) - Decimal(previous)


async def test_reconciliation_tool_rejects_multi_day_follow_up_even_if_model_chooses_a_day():
    def model(messages, _info):
        returns = [part for part in messages[-1].parts if isinstance(part, ToolReturnPart)]
        if returns:
            problem = returns[0].content
            assert isinstance(problem, RevenueProblem)
            assert problem.status == "reconciliation_date_required"
            return ModelResponse(parts=[TextPart("Which date?")])
        return ModelResponse(parts=[ToolCallPart("get_reconciliation", {
            "branch": "kitengela", "report_date": "2026-11-16",
        })])

    def transport(_request):
        pytest.fail("A multi-day reconciliation should never request a branch report")

    branch = BranchConfig(
        id="kitengela", name="Kitengela", base_url="https://kitengela.example/api/v1/", token_env="TOKEN",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        client = RevenueClient([branch], http, clock=lambda: date(2026, 11, 23))
        result = await run_question(
            build_agent(FunctionModel(model)), "What about last week?", client,
            context=ConversationContext(branch_id="kitengela", metric="reconciliation"),
        )
    assert result.output == "Which date?"


@pytest.mark.parametrize("view", ["daily", "monthly", "products"])
async def test_fulfillment_tools_render_verified_totals_and_units(view):
    start, end = "2026-11-30", "2026-12-01"
    tool = "get_top_products" if view == "products" else "get_sales"

    def model(messages, _info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("KES 999,999.00.")])
        args = {"branch": "Kitengela", "start_date": start, "end_date": end}
        if view != "products":
            args["breakdown"] = view
        return ModelResponse(parts=[ToolCallPart(tool, args)])

    def transport(request):
        payload = {
            "schema_version": 1, "branch": {"id": "kitengela", "name": "Kitengela"},
            "start_date": start, "end_date": end, "timezone": "Africa/Nairobi", "currency": "KES",
            "generated_at": "2026-12-02T08:00:00Z", "is_provisional": False,
        }
        if view == "products":
            assert request.url.path == "/api/v1/agent/products/"
            payload["products"] = [{"name": "Product A", "code": "A", "units_sold": 4, "sales_value": "12.50"}]
        else:
            assert request.url.path == "/api/v1/agent/sales/"
            assert request.url.params["daily"] == "true"
            payload.update(total_sales="30.75", daily=[
                {"date": start, "total_sales": "10.25"}, {"date": end, "total_sales": "20.50"},
            ])
        return httpx.Response(200, json=payload)

    branch = BranchConfig(
        id="kitengela", name="Kitengela", base_url="https://kitengela.example/api/v1/", token_env="TOKEN",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        client = RevenueClient([branch], http, token_lookup=lambda _: "test-token", clock=lambda: date(2026, 12, 2))
        run = await run_question(build_agent(FunctionModel(model)), f"Show the {view} report", client)
    parts = [part for message in run.new_messages() for part in message.parts if isinstance(part, ToolReturnPart)]
    answer, _ = render_answer(parts, [branch])
    assert "999,999" not in answer
    if view == "products":
        assert "Product A: 4 units, KES 12.50" in answer
    elif view == "daily":
        assert f"{start}: KES 10.25" in answer
        assert "Total fulfilled sales: KES 30.75" in answer
    else:
        assert f"November 2026 (partial month, {start}): KES 10.25" in answer
        assert f"December 2026 (incomplete current month, {end}): KES 20.50" in answer
