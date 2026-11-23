from datetime import date

import httpx
from pydantic_ai import models
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from whatsapp_bi.agent import build_agent
from whatsapp_bi.client import RevenueClient
from whatsapp_bi.models import BranchConfig

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
        assert {tool.name for tool in info.function_tools} == {"get_revenue", "compare_revenue"}
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
