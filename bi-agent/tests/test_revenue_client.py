from copy import deepcopy
from datetime import date
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError
from whatsapp_bi.client import RevenueClient
from whatsapp_bi.models import BranchConfig, RevenueProblem, RevenueQuery, RevenueReport


@pytest.fixture
def branch():
    return BranchConfig(
        id="kitengela",
        name="Kitengela",
        base_url="https://kitengela.example/api/v1/",
        token_env="KITENGELA_BI_TOKEN",
    )


@pytest.fixture
def query():
    return RevenueQuery(
        branch=" Kitengela ", start_date="2026-06-15", end_date="2026-06-16"
    )


@pytest.fixture
def payload():
    return {
        "schema_version": 1,
        "branch": {"id": "kitengela", "name": "Kitengela"},
        "start_date": "2026-06-15",
        "end_date": "2026-06-16",
        "timezone": "Africa/Nairobi",
        "currency": "KES",
        "generated_at": "2026-06-17T08:00:00+00:00",
        "is_provisional": False,
        "totals": {
            "paybill": "0.10",
            "pdq": "0.20",
            "till": "0.00",
            "total_revenue": "0.30",
            "transaction_count": 2,
        },
        "daily": [
            {
                "date": "2026-06-15",
                "paybill": "0.10",
                "pdq": "0.20",
                "till": "0.00",
                "total_revenue": "0.30",
                "transaction_count": 2,
            },
            {
                "date": "2026-06-16",
                "paybill": "0.00",
                "pdq": "0.00",
                "till": "0.00",
                "total_revenue": "0.00",
                "transaction_count": 0,
            },
        ],
    }


async def fetch(branch, query, handler, token="test-secret"):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = RevenueClient(
            [branch],
            http,
            token_lookup=lambda _: token,
            clock=lambda: date(2026, 6, 17),
        )
        return await client.get_revenue(query)


async def test_exact_contract_credentials_and_decimal_money(branch, query, payload):
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/v1/agent/revenue/"
        assert request.url.params == httpx.QueryParams(
            start_date="2026-06-15", end_date="2026-06-16"
        )
        assert request.headers["Authorization"] == "Bearer test-secret"
        return httpx.Response(200, json=payload)

    result = await fetch(branch, query, handler)
    assert isinstance(result, RevenueReport)
    assert result.totals.total_revenue == Decimal("0.30")
    assert result.daily[1].total_revenue == Decimal("0.00")


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "authentication_failed"),
        (403, "authentication_failed"),
        (404, "not_deployed"),
        (400, "invalid_request"),
        (500, "backend_unavailable"),
        (302, "backend_unavailable"),
    ],
)
async def test_errors_never_become_zero_revenue(branch, query, status, expected):
    result = await fetch(branch, query, lambda _: httpx.Response(status))
    assert isinstance(result, RevenueProblem)
    assert result.status == expected
    assert "test-secret" not in result.model_dump_json()


async def test_timeout_is_unavailable(branch, query):
    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    result = await fetch(branch, query, timeout)
    assert result.status == "backend_unavailable"


async def test_unknown_branch_and_missing_credentials_make_no_request(branch, query):
    def forbidden(_):
        pytest.fail("Should not perform an HTTP request")

    unknown = query.model_copy(update={"branch": "Atlantis"})
    assert (await fetch(branch, unknown, forbidden)).status == "unknown_branch"
    assert (
        await fetch(branch, query, forbidden, token=None)
    ).status == "authentication_failed"


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_day",
        "duplicate_day",
        "incorrect_sum",
        "wrong_count",
        "wrong_branch",
        "wrong_period",
        "bad_json",
    ],
)
async def test_inconsistent_backend_data_is_rejected(
    branch, query, payload, corruption
):
    data = deepcopy(payload)
    if corruption == "missing_day":
        data["daily"].pop()
    elif corruption == "duplicate_day":
        data["daily"][1]["date"] = "2026-06-15"
    elif corruption == "incorrect_sum":
        data["totals"]["total_revenue"] = "999.00"
    elif corruption == "wrong_count":
        data["totals"]["transaction_count"] = 99
    elif corruption == "wrong_branch":
        data["branch"]["id"] = "main-shop"
    elif corruption == "wrong_period":
        data["start_date"] = "2026-06-16"
        data["daily"] = data["daily"][1:]
        data["totals"] = {k: v for k, v in data["daily"][0].items() if k != "date"}
    response = (
        httpx.Response(200, content=b"not-json")
        if corruption == "bad_json"
        else httpx.Response(200, json=data)
    )
    assert (await fetch(branch, query, lambda _: response)).status == "invalid_response"


def test_branch_urls_and_query_limits():
    with pytest.raises(ValidationError):
        BranchConfig(
            id="x", name="x", base_url="http://remote.example/", token_env="TOKEN"
        )
    with pytest.raises(ValidationError):
        RevenueQuery(branch="x", start_date="2026-06-16", end_date="2026-06-15")
    with pytest.raises(ValidationError):
        RevenueQuery(branch="x", start_date="2024-01-01", end_date="2026-06-15")


async def test_future_date_is_not_silently_zero(branch):
    future = RevenueQuery(
        branch="Kitengela", start_date="2026-06-18", end_date="2026-06-18"
    )

    def forbidden(_):
        pytest.fail("Should not request future data")

    assert (await fetch(branch, future, forbidden)).status == "invalid_request"
