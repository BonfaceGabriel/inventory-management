from datetime import date

import httpx
import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from whatsapp_bi.agent import build_agent, run_question
from whatsapp_bi.client import RevenueClient
from whatsapp_bi.models import BranchConfig
from whatsapp_bi.web import render_answer


@pytest.mark.parametrize(
    ("view", "fields", "expected"),
    [
        (
            "merchandise",
            {
                "total_fulfilled": "800.00", "previous_day_total": "400.00",
                "items": [{
                    "code": "TS", "name": "T-shirt", "units_sold": 2, "sales_value": "800.00",
                    "remaining_units": 5, "remaining_catalog_value": "2500.00",
                }],
            },
            ["Previous day (2026-06-16): KES 400.00", "+100.00%", "sold 2 (KES 800.00), remaining 5 (KES 2,500.00)"],
        ),
        (
            "stock",
            {
                "total_stock_value_at_cost": "4200.00", "out_of_stock_count": 8, "low_stock_count": 1,
                "items": [{"code": "low", "name": "Low", "quantity": 3, "reorder_level": 10, "status": "LOW_STOCK"}],
            },
            ["Stock value at cost: KES 4,200.00", "Out of stock: 8 | Low stock: 1", "Low: 3 remaining"],
        ),
    ],
)
async def test_inventory_tool_and_whatsapp_answer(view, fields, expected):
    day = "2026-06-17"
    branch = BranchConfig(
        id="kitengela", name="Kitengela", base_url="https://kitengela.example/api/v1", token_env="TOKEN",
    )
    results = []

    def http_handler(request):
        assert request.url.path == "/api/v1/agent/inventory/"
        assert dict(request.url.params) == {"view": view, "start_date": day, "end_date": day, "page": "2"}
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={
            "schema_version": 1, "branch": {"id": branch.id, "name": branch.name},
            "start_date": day, "end_date": day, "generated_at": f"{day}T08:00:00Z",
            "is_provisional": True, "timezone": "Africa/Nairobi", "currency": "KES",
            "page": 2, "page_count": 2, **fields,
        })

    def model(messages, _info):
        returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        if returns:
            results.extend(returns)
            return ModelResponse(parts=[TextPart("This model text is replaced by the verified report.")])
        args = {"branch": branch.name}
        if view == "merchandise":
            args = {"query": {**args, "start_date": day, "end_date": day}}
        return ModelResponse(parts=[ToolCallPart(f"get_{view}", {**args, "page": 2})])

    async with httpx.AsyncClient(transport=httpx.MockTransport(http_handler)) as http:
        client = RevenueClient([branch], http, token_lookup=lambda _: "test-token", clock=lambda: date.fromisoformat(day))
        await run_question(build_agent(FunctionModel(model)), f"Kitengela {view} page 2", client)
    answer, context = render_answer(results, [branch])
    assert context.metric == view
    assert "Page 2 of 2." in answer
    assert all(fragment in answer for fragment in expected)
