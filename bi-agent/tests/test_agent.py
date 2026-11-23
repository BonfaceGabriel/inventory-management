from datetime import date
from decimal import Decimal

import httpx
import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from whatsapp_bi.agent import build_agent, run_question
from whatsapp_bi.client import RevenueClient
from whatsapp_bi.models import BranchConfig, RevenuePeriod, RevenueTrend

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
            "get_revenue", "compare_revenue", "get_sales", "get_reconciliation",
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
