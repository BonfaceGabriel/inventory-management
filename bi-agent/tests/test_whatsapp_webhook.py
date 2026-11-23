import argparse
import asyncio
import hmac
import json
import sqlite3
import time
from datetime import datetime, timedelta
from threading import Event

import httpx
import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from starlette.testclient import TestClient

from whatsapp_bi.__main__ import execute
from whatsapp_bi.agent import RECONCILIATION_DATE_REQUIRED
from whatsapp_bi.branch_directory import BranchDirectory
from whatsapp_bi.inbox import CONTEXT_SECONDS, Inbox, Message
from whatsapp_bi.models import NAIROBI, BranchConfig, ConversationContext
from whatsapp_bi.web import MAX_WEBHOOK_BYTES, UNAVAILABLE_REPLY, create_app
from whatsapp_bi.whatsapp import TEXT_LIMIT, WhatsAppSettings

PHONE_ID = "12345678"
SENDER = "15555550100"
OTHER_SENDER = "15555550101"
QUESTION = "What was Kitengela's revenue on 17 November 2026?"
ANSWER = (
    "Kitengela — 2026-11-17\n"
    "Paybill: KES 100.00\n"
    "PDQ: KES 0.00\n"
    "Till: KES 150.00\n"
    "Total revenue: KES 250.00"
)
DAY = "2026-11-17"
PATH = "/webhooks/whatsapp/"


def message(message_id, *, sender=SENDER, kind="text"):
    return {
        "id": message_id,
        "from": sender,
        "timestamp": str(int(time.time())),
        "type": kind,
        "text": {"body": QUESTION},
    }


def change(messages, *, phone=PHONE_ID):
    return {
        "field": "messages",
        "value": {"metadata": {"phone_number_id": phone}, "messages": messages},
    }


def payload(*changes):
    return json.dumps(
        {"object": "whatsapp_business_account", "entry": [{"changes": changes}]}
    ).encode()


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    monkeypatch.setenv("KITENGELA_TEST_TOKEN", "branch-token")
    settings = WhatsAppSettings(
        phone_number_id=PHONE_ID,
        allowed_senders={SENDER},
        app_secret="app-secret",
        verify_token="verify-token",
        access_token="graph-token",
        inbox_path=tmp_path / "inbox.sqlite3",
    )
    branches = [
        BranchConfig(
            id="kitengela",
            name="Kitengela",
            base_url="https://kitengela.example/api/v1/",
            token_env="KITENGELA_TEST_TOKEN",
        )
    ]
    return settings, branches


def signed_post(client, body, key=b"app-secret"):
    signature = hmac.digest(key, body, "sha256").hex()
    return client.post(PATH, content=body, headers={"X-Hub-Signature-256": f"sha256={signature}"})


def test_webhook_verification_and_authentication(pilot):
    def unused(_request):
        pytest.fail("No external service should be called")

    with TestClient(create_app(*pilot, transport=httpx.MockTransport(unused))) as client:
        assert client.get("/health/").text == "ok"
        query = {
            "hub.mode": "subscribe",
            "hub.challenge": "0123456789",
            "hub.verify_token": "verify-token",
        }
        valid = client.get(PATH, params=query)
        assert valid.status_code == 200 and valid.text == "0123456789"
        assert client.get(PATH, params={**query, "hub.verify_token": "bad"}).status_code == 403
        body = payload(change([message("valid-id")]))
        assert client.post(PATH, content=body).status_code == 403
        assert signed_post(client, body, b"wrong-secret").status_code == 403
        assert signed_post(client, b"not json").status_code == 400
        assert signed_post(client, b"x" * (MAX_WEBHOOK_BYTES + 1)).status_code == 413
    assert Inbox(pilot[0].inbox_path).next_message() is None


@pytest.mark.parametrize("connect_failure", [False, True])
def test_signed_message_calls_revenue_and_sends_one_reply_after_retries(pilot, connect_failure):
    requests = []
    replied = Event()
    totals = {
        "paybill": "100.00",
        "pdq": "0.00",
        "till": "150.00",
        "total_revenue": "250.00",
        "transaction_count": 2,
    }

    def transport(request):
        requests.append(request)
        if request.url.host == "kitengela.example":
            assert request.url.path == "/api/v1/agent/revenue/"
            assert dict(request.url.params) == {"start_date": DAY, "end_date": DAY}
            assert request.headers["Authorization"] == "Bearer branch-token"
            return httpx.Response(
                200,
                json={
                    "schema_version": 1,
                    "branch": {"id": "kitengela", "name": "Kitengela"},
                    "start_date": DAY,
                    "end_date": DAY,
                    "timezone": "Africa/Nairobi",
                    "currency": "KES",
                    "generated_at": "2026-11-18T08:00:00Z",
                    "is_provisional": False,
                    "totals": totals,
                    "daily": [{"date": DAY, **totals}],
                },
            )
        assert request.url.host == "graph.facebook.com"
        assert request.url.path == f"/v27.0/{PHONE_ID}/messages"
        assert request.headers["Authorization"] == "Bearer graph-token"
        assert json.loads(request.content) == {
            "messaging_product": "whatsapp",
            "to": SENDER,
            "context": {"message_id": "incoming-id"},
            "type": "text",
            "text": {"body": ANSWER},
        }
        if connect_failure and len(requests) == 2:
            raise httpx.ConnectError("not yet connected", request=request)
        replied.set()
        return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})

    def respond(messages, _info):
        for part in messages[-1].parts:
            if isinstance(part, ToolReturnPart):
                assert part.content.totals.model_dump(mode="json") == totals
                return ModelResponse(parts=[TextPart("The total was KES 999,999.00.")])
        assert any(getattr(part, "content", None) == QUESTION for part in messages[-1].parts)
        return ModelResponse(parts=[ToolCallPart("get_revenue", {
            "branch": "Kitengela", "start_date": DAY, "end_date": DAY,
        })])

    body = payload(
        change([message("unauthorized", sender=OTHER_SENDER), message("image", kind="image")]),
        change([message("other-phone")], phone="112233"),
        {"field": "messages", "value": {"statuses": [{"id": "outbound-id"}]}},
        change([message("incoming-id")]),
    )
    for _ in range(2):
        app = create_app(*pilot, FunctionModel(respond), transport=httpx.MockTransport(transport))
        with TestClient(app) as client:
            assert signed_post(client, body).status_code == 200
            assert signed_post(client, body).status_code == 200
            assert replied.wait(3)

    assert [request.url.host for request in requests] == [
        "kitengela.example", *(["graph.facebook.com"] * (1 + connect_failure)),
    ]
    with sqlite3.connect(pilot[0].inbox_path) as connection:
        rows = connection.execute("SELECT message_id, sender, body, state FROM inbox").fetchall()
    assert rows == [("incoming-id", None, None, "sent")]


@pytest.mark.parametrize(
    "baseline_day, baseline_available, resolves_follow_up",
    [
        ("2026-11-16", True, True),
        ("2026-11-16", False, False),
        ("2026-10-16", True, False),
    ],
)
def test_signed_comparison_and_day_only_follow_up(
    pilot, monkeypatch, baseline_day, baseline_available, resolves_follow_up
):
    now = datetime(2026, 11, 23, 10, tzinfo=NAIROBI).timestamp()
    monkeypatch.setattr("whatsapp_bi.inbox.time.time", lambda: now)
    question = f"Compare Kitengela revenue on {DAY} with {baseline_day}"
    follow_up = "what of 18th?"
    follow_up_day = "2026-11-18"
    resolved_question = f"Show revenue for kitengela on {follow_up_day}."
    dates = []
    answers = []
    replied = Event()

    def transport(request):
        if request.url.host == "graph.facebook.com":
            answers.append(json.loads(request.content)["text"]["body"])
            replied.set()
            return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})
        day = request.url.params["start_date"]
        assert request.url.params["end_date"] == day
        assert request.headers["Authorization"] == "Bearer branch-token"
        dates.append(day)
        if day == baseline_day and not baseline_available:
            return httpx.Response(503)
        amount = {DAY: "250.10", baseline_day: "200.05", follow_up_day: "350.00"}[day]
        totals = {
            "paybill": amount, "pdq": "0.00", "till": "0.00",
            "total_revenue": amount, "transaction_count": 1,
        }
        return httpx.Response(200, json={
            "schema_version": 1, "branch": {"id": "kitengela", "name": "Kitengela"},
            "start_date": day, "end_date": day, "timezone": "Africa/Nairobi",
            "currency": "KES", "generated_at": "2026-11-18T08:00:00Z",
            "is_provisional": False, "totals": totals, "daily": [{"date": day, **totals}],
        })

    def respond(messages, info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("Revenue changed by KES 999,999.00.")])
        prompts = [getattr(part, "content", None) for part in messages[-1].parts]
        if resolved_question in prompts:
            assert resolves_follow_up
            return ModelResponse(parts=[ToolCallPart("get_revenue", {
                "branch": "kitengela", "start_date": follow_up_day, "end_date": follow_up_day,
            })])
        if follow_up in prompts:
            assert not resolves_follow_up
            if baseline_available:
                assert "ask for the full date" in info.instructions
            return ModelResponse(parts=[TextPart("Which full date?")])
        assert question in prompts
        return ModelResponse(parts=[ToolCallPart("compare_revenue", {
            "branch": "Kitengela",
            "period": {"start_date": DAY, "end_date": DAY},
            "baseline": {"start_date": baseline_day, "end_date": baseline_day},
        })])

    incoming = message("comparison-id")
    incoming["text"]["body"] = question
    app = create_app(*pilot, FunctionModel(respond), transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        assert signed_post(client, payload(change([incoming]))).status_code == 200
        assert replied.wait(3)
        replied.clear()
        next_message = message("day-only-follow-up")
        next_message["text"]["body"] = follow_up
        assert signed_post(client, payload(change([next_message]))).status_code == 200
        assert replied.wait(3)

    assert dates == [DAY, baseline_day] + ([follow_up_day] if resolves_follow_up else [])
    expected = (
        "Kitengela\nPeriod (2026-11-17): KES 250.10\n"
        f"Baseline ({baseline_day}): KES 200.05\nChange: KES +50.05"
    )
    assert answers[0] == (expected if baseline_available else UNAVAILABLE_REPLY)
    if not resolves_follow_up:
        assert answers[1] == "Ask for revenue, sales, or reconciliation for one branch and include the date. Branches: Kitengela."
    else:
        assert answers[1].startswith(f"Kitengela — {follow_up_day}\n")
        assert answers[1].endswith("Total revenue: KES 350.00")


@pytest.mark.parametrize("breakdown, gateways", [("daily", False), ("daily", True), ("trend", False)])
def test_whatsapp_revenue_view_preserves_full_total_and_requested_details(pilot, monkeypatch, breakdown, gateways):
    end = datetime(2026, 11, 23, 10, tzinfo=NAIROBI)
    monkeypatch.setattr("whatsapp_bi.inbox.time.time", end.timestamp)
    start = (end - timedelta(days=39)).date()
    view = "trend" if breakdown == "trend" else "by day"
    question = f"Show Kitengela's revenue {view} from 15 October through 23 November."
    initial_question = "Show Kitengela's revenue from 15 October through 23 November."
    gateway_follow_up = "break it down by gateway and by day"
    answers = []
    done = Event()

    def amounts(total):
        till = 25 if total else 0
        return {
            "paybill": f"{total - till}.00", "pdq": "0.00", "till": f"{till}.00",
            "total_revenue": f"{total}.00", "transaction_count": int(total > 0),
        }

    def transport(request):
        if request.url.host == "graph.facebook.com":
            answers.append(json.loads(request.content)["text"]["body"])
            done.set()
            return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})
        assert dict(request.url.params) == {
            "start_date": start.isoformat(), "end_date": end.date().isoformat(),
        }
        assert request.headers["Authorization"] == "Bearer branch-token"
        return httpx.Response(200, json={
            "schema_version": 1, "branch": {"id": "kitengela", "name": "Kitengela"},
            "start_date": start.isoformat(), "end_date": end.date().isoformat(),
            "timezone": "Africa/Nairobi", "currency": "KES", "generated_at": end.isoformat(),
            "is_provisional": True, "totals": {
                **amounts(1575), "paybill": "1225.00", "till": "350.00", "transaction_count": 14,
            },
            "daily": [
                {"date": (start + timedelta(days=index)).isoformat(),
                 **amounts(0 if index < 26 else 100 if index < 33 else 125)}
                for index in range(40)
            ],
        })

    def respond(messages, info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("The change was 999%.")])
        prompt = messages[-1].parts[0].content
        if prompt == gateway_follow_up:
            assert "branch ID kitengela" in info.instructions
            assert f"Its date range was {start} through {end.date()}." in info.instructions
        assert "breakdown" in next(
            tool.parameters_json_schema["properties"] for tool in info.function_tools
            if tool.name == "get_revenue"
        )
        return ModelResponse(parts=[ToolCallPart("get_revenue", {
            "branch": "Kitengela", "start_date": start.isoformat(),
            "end_date": end.date().isoformat(),
            "breakdown": "total" if prompt == initial_question else breakdown,
            "include_daily_gateways": prompt == gateway_follow_up,
        })])

    incoming = message("daily-breakdown")
    incoming["text"]["body"] = gateway_follow_up if gateways else question
    app = create_app(*pilot, FunctionModel(respond), transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        if gateways:
            first = message("initial-total")
            first["text"]["body"] = initial_question
            assert signed_post(client, payload(change([first]))).status_code == 200
            assert done.wait(3)
            assert "Paybill: KES 1,225.00" in answers[0]
            done.clear()
        assert signed_post(client, payload(change([incoming]))).status_code == 200
        assert done.wait(3)

    assert len(answers) == (2 if gateways else 1)
    answer = answers[-1]
    assert len(answer) < TEXT_LIMIT
    assert "Kitengela — daily revenue (2026-10-15 to 2026-11-23)" in answer
    assert "Total revenue: KES 1,575.00" in answer
    assert "Includes provisional revenue for 2026-11-23." in answer
    assert "Showing the most recent 31 of 40 days." in answer
    assert "2026-10-23:" not in answer
    if gateways:
        assert "Period gateways (KES): Paybill 1,225.00 | PDQ 0.00 | Till 350.00" in answer
        assert "2026-11-23: Paybill 100.00 | PDQ 0.00 | Till 25.00 | Total 125.00" in answer
    else:
        assert "2026-10-24: KES 0.00" in answer
        assert "2026-11-23: KES 125.00" in answer
    if breakdown == "trend":
        assert "Last 7 days (2026-11-17 to 2026-11-23): KES 875.00" in answer
        assert "Previous 7 days (2026-11-10 to 2026-11-16): KES 700.00" in answer
        assert answer.endswith("Change: +25.00%")
    else:
        assert "Last 7 days" not in answer
        assert "Change:" not in answer


def test_whatsapp_monthly_revenue_compares_complete_months_and_labels_partial_months(pilot, monkeypatch):
    now = datetime(2026, 11, 23, 10, tzinfo=NAIROBI)
    monkeypatch.setattr("whatsapp_bi.inbox.time.time", now.timestamp)
    start = datetime(2026, 7, 31).date()
    end = (now - timedelta(days=1)).date()
    question = "Show Kitengela's month-to-month revenue from 31 July to 22 November 2026."
    done = Event()
    answers = []
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    totals_by_month = {7: 40, 8: 0, 9: 10, 10: 15, 11: 20}

    def amounts(total, count):
        return {
            "paybill": f"{total}.00", "pdq": "0.00", "till": "0.00",
            "total_revenue": f"{total}.00", "transaction_count": count,
        }

    def transport(request):
        if request.url.host == "graph.facebook.com":
            answers.append(json.loads(request.content)["text"]["body"])
            done.set()
            return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})
        assert dict(request.url.params) == {"start_date": str(start), "end_date": str(end)}
        assert request.headers["Authorization"] == "Bearer branch-token"
        return httpx.Response(200, json={
            "schema_version": 1, "branch": {"id": "kitengela", "name": "Kitengela"},
            "start_date": str(start), "end_date": str(end), "timezone": "Africa/Nairobi",
            "currency": "KES", "generated_at": now.isoformat(), "is_provisional": False,
            "totals": amounts(1245, 84),
            "daily": [
                {"date": str(day), **amounts(totals_by_month[day.month], int(bool(totals_by_month[day.month])))}
                for day in days
            ],
        })

    def respond(messages, info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("All months are complete.")])
        assert "Use breakdown=monthly" in info.instructions
        return ModelResponse(parts=[ToolCallPart("get_revenue", {
            "branch": "Kitengela", "start_date": str(start), "end_date": str(end), "breakdown": "monthly",
        })])

    incoming = message("monthly-breakdown")
    incoming["text"]["body"] = question
    app = create_app(*pilot, FunctionModel(respond), transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        assert signed_post(client, payload(change([incoming]))).status_code == 200
        assert done.wait(3)

    assert answers == [
        "Kitengela — monthly revenue (2026-07-31 to 2026-11-22)\n"
        "Total revenue: KES 1,245.00\n"
        "July 2026 (partial month, 2026-07-31): KES 40.00\n"
        "August 2026: KES 0.00\n"
        "September 2026: KES 300.00\n"
        "Change vs August 2026: KES +300.00. Percentage undefined because the previous total was KES 0.00.\n"
        "October 2026: KES 465.00\n"
        "Change vs September 2026: +55.00%\n"
        "November 2026 (incomplete current month, 2026-11-01 to 2026-11-22): KES 440.00"
    ]


@pytest.mark.parametrize("outcome", ["success", "incomplete", "wrong_date"])
def test_whatsapp_sales_total_and_follow_up_use_the_sales_endpoint(pilot, monkeypatch, outcome):
    now = datetime(2026, 11, 23, 13, tzinfo=NAIROBI)
    monkeypatch.setattr("whatsapp_bi.inbox.time.time", now.timestamp)
    today, yesterday = "2026-11-23", "2026-11-22"
    question = "What were Kitengela's sales on 23 November 2026?"
    followed_up = "What of 22nd?"
    dates = []
    answers = []
    done = Event()

    def transport(request):
        if request.url.host == "graph.facebook.com":
            answers.append(json.loads(request.content)["text"]["body"])
            done.set()
            return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})
        assert request.url.path == "/api/v1/agent/sales/"
        assert request.headers["Authorization"] == "Bearer branch-token"
        day = request.url.params["start_date"]
        assert request.url.params["end_date"] == day
        dates.append(day)
        if outcome == "incomplete":
            return httpx.Response(409, json={"code": "incomplete_fulfillment_history"})
        result_day = yesterday if outcome == "wrong_date" else day
        return httpx.Response(200, json={
            "schema_version": 1, "branch": {"id": "kitengela", "name": "Kitengela"},
            "start_date": result_day, "end_date": result_day, "timezone": "Africa/Nairobi",
            "currency": "KES", "generated_at": now.isoformat(),
            "is_provisional": day == today, "total_sales": "7625.00" if day == today else "0.00",
        })

    def respond(messages, info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("Paybill sales were KES 999,999.00.")])
        prompt = messages[-1].parts[0].content
        day = today
        if prompt != question:
            assert prompt == f"Show sales for kitengela on {yesterday}."
            assert "Its metric was sales." in info.instructions
            day = yesterday
        return ModelResponse(parts=[ToolCallPart("get_sales", {
            "branch": "kitengela", "start_date": day, "end_date": day,
        })])

    def ask(client, message_id, text):
        done.clear()
        incoming = message(message_id)
        incoming["text"]["body"] = text
        assert signed_post(client, payload(change([incoming]))).status_code == 200
        assert done.wait(3)

    app = create_app(*pilot, FunctionModel(respond), transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        ask(client, "initial-sales", question)
        if outcome == "success":
            ask(client, "sales-follow-up", followed_up)

    if outcome == "success":
        assert dates == [today, yesterday]
        assert answers == [
            "Kitengela — 2026-11-23\nTotal fulfilled sales: KES 7,625.00\nThis result is provisional.",
            "Kitengela — 2026-11-22\nTotal fulfilled sales: KES 0.00",
        ]
    elif outcome == "incomplete":
        assert answers == [
            "I couldn't verify sales for those dates from the fulfillment records. "
            "If an order was fulfilled over several days, try a range that includes all of them."
        ]
    else:
        assert answers == [UNAVAILABLE_REPLY]


def test_whatsapp_discovers_new_branch_without_a_restart(pilot, monkeypatch):
    now = datetime(2026, 11, 23, 13, tzinfo=NAIROBI)
    monkeypatch.setattr("whatsapp_bi.inbox.time.time", now.timestamp)
    monkeypatch.setenv("NEW_BRANCH_BI_TOKEN", "new-branch-token")
    monkeypatch.setenv("CENTRAL_BI_TOKEN", "central-token")
    settings, _ = pilot
    directory = BranchDirectory("https://central.example/api/v1/", "directory-token")
    branches_added = False
    directory_reads = []
    answers = []
    done = Event()
    day = now.date().isoformat()

    def transport(request):
        if request.url.host == "graph.facebook.com":
            answers.append(json.loads(request.content)["text"]["body"])
            done.set()
            return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})
        if request.url.path.endswith("/agent/branches/"):
            assert request.url.host == "central.example"
            assert request.headers["Authorization"] == "Bearer directory-token"
            directory_reads.append(branches_added)
            return httpx.Response(200, json={
                "local": {"id": "central", "name": "Central"},
                "remote": [{
                    "id": "new-branch", "name": "New Branch", "base_url": "https://new.example/api/v1/",
                }] if branches_added else [],
            })
        assert request.url.path == "/api/v1/agent/sales/"
        central = request.url.host == "central.example"
        assert request.headers["Authorization"] == ("Bearer central-token" if central else "Bearer new-branch-token")
        return httpx.Response(200, json={
            "schema_version": 1,
            "branch": {"id": "central", "name": "Central"} if central else {"id": "new-branch", "name": "New Branch"},
            "start_date": day, "end_date": day, "timezone": "Africa/Nairobi", "currency": "KES",
            "generated_at": now.isoformat(), "is_provisional": True, "total_sales": "10.00",
        })

    def respond(messages, info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("Verified")])
        assert ("New Branch" in info.instructions) == branches_added
        return ModelResponse(parts=[ToolCallPart("get_sales", {
            "branch": "new-branch" if branches_added else "central", "start_date": day, "end_date": day,
        })])

    app = create_app(settings, model=FunctionModel(respond), directory=directory, transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        for i, name in enumerate(("Central", "New Branch")):
            branches_added = i > 0
            done.clear()
            incoming = message(f"directory-{i}")
            incoming["text"]["body"] = f"Show {name}'s sales today"
            assert signed_post(client, payload(change([incoming]))).status_code == 200
            assert done.wait(3)
            assert answers[i].startswith(f"{name} — {day}")
    assert directory_reads == [False, True]


@pytest.mark.parametrize("view", ["merchandise", "stock"])
def test_whatsapp_delivers_inventory_report(pilot, monkeypatch, view):
    now = datetime(2026, 11, 23, 13, tzinfo=NAIROBI)
    monkeypatch.setattr("whatsapp_bi.inbox.time.time", now.timestamp)
    day = now.date().isoformat()
    answers = []
    done = Event()

    def transport(request):
        if request.url.host == "graph.facebook.com":
            answers.append(json.loads(request.content)["text"]["body"])
            done.set()
            return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})
        assert request.url.path == "/api/v1/agent/inventory/"
        assert request.url.params["view"] == view
        if view == "stock":
            fields = {"total_stock_value_at_cost": "500.00", "low_stock_count": 0, "out_of_stock_count": 0}
        else:
            fields = {"total_fulfilled": "100.00", "previous_day_total": "0.00"}
        return httpx.Response(200, json={
            "schema_version": 1, "branch": {"id": "kitengela", "name": "Kitengela"},
            "start_date": day, "end_date": day, "timezone": "Africa/Nairobi", "currency": "KES",
            "generated_at": now.isoformat(), "is_provisional": True, "page": 1, "page_count": 1,
            "items": [], **fields,
        })

    def respond(messages, _info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("Invented figure")])
        args = {"branch": "kitengela"}
        if view == "merchandise":
            args = {"query": {**args, "start_date": day, "end_date": day}}
        return ModelResponse(parts=[ToolCallPart(f"get_{view}", args)])

    app = create_app(*pilot, FunctionModel(respond), transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        incoming = message(f"inventory-{view}")
        incoming["text"]["body"] = f"Kitengela {view} today"
        assert signed_post(client, payload(change([incoming]))).status_code == 200
        assert done.wait(3)
    expected = "Stock value at cost: KES 500.00" if view == "stock" else "Total fulfilled: KES 100.00"
    assert expected in answers[0]
    assert "Invented figure" not in answers[0]


@pytest.mark.parametrize("stock_count, changed", [(45, False), (96, False), (45, True)])
def test_whatsapp_sends_all_stock_alerts_by_default(pilot, monkeypatch, stock_count, changed):
    now = datetime(2026, 11, 23, 13, tzinfo=NAIROBI)
    monkeypatch.setattr("whatsapp_bi.inbox.time.time", now.timestamp)
    day = now.date().isoformat()
    items = [
        {
            "code": str(i), "name": f"Product {i:03d} with a long catalog name",
            "quantity": 0 if i % 2 == 0 else 2, "reorder_level": 5,
            "status": "OUT_OF_STOCK" if i % 2 == 0 else "LOW_STOCK",
        }
        for i in range(stock_count)
    ]
    page_count = (stock_count + 7) // 8
    answers = []
    pages = []
    done = Event()

    def transport(request):
        if request.url.host == "graph.facebook.com":
            body = json.loads(request.content)["text"]["body"]
            answers.append(body)
            if items[-1]["name"] in body or body == UNAVAILABLE_REPLY:
                done.set()
            return httpx.Response(200, json={"messages": [{"id": f"outbound-{len(answers)}"}]})
        assert request.url.path == "/api/v1/agent/inventory/"
        assert request.url.params["view"] == "stock"
        page = int(request.url.params["page"])
        pages.append(page)
        offset = 8 * (page - 1)
        return httpx.Response(200, json={
            "schema_version": 1, "branch": {"id": "kitengela", "name": "Kitengela"},
            "start_date": day, "end_date": day, "timezone": "Africa/Nairobi", "currency": "KES",
            "generated_at": now.isoformat(), "is_provisional": True, "page": page, "page_count": page_count,
            "total_stock_value_at_cost": "501.00" if changed and page == 2 else "500.00",
            "out_of_stock_count": (stock_count + 1) // 2, "low_stock_count": stock_count // 2,
            "items": items[offset:offset + 8],
        })

    def respond(messages, _info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("Invented figure")])
        return ModelResponse(parts=[ToolCallPart("get_stock", {"branch": "kitengela"})])

    app = create_app(*pilot, FunctionModel(respond), transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        incoming = message("full-stock")
        incoming["text"]["body"] = "Give me all Kitengela's low-stock and out-of-stock products"
        assert signed_post(client, payload(change([incoming]))).status_code == 200
        assert done.wait(3)

    if changed:
        assert pages == [1, 2]
        assert answers == [UNAVAILABLE_REPLY]
        return
    assert pages == list(range(1, page_count + 1))
    assert len(answers) == (1 if stock_count == 45 else 2)
    assert all(len(answer) <= TEXT_LIMIT for answer in answers)
    delivered = "\n".join(answers)
    assert "Page 1 of" not in delivered
    assert all(delivered.count(item["name"]) == 1 for item in items)
    if len(answers) > 1:
        assert answers[0].startswith("Part 1 of 2\n")
        assert answers[1].startswith("Part 2 of 2\n")


@pytest.mark.parametrize("baseline_status, baseline_amount, expected", [
    (200, "100.00", "Highest percentage growth: Kitengela."),
    (200, "0.00", "Percentage undefined because the previous total was KES 0.00."),
    (503, "100.00", "Kitengela: one or both periods unavailable."),
])
def test_whatsapp_compares_growth_across_branches(pilot, monkeypatch, baseline_status, baseline_amount, expected):
    now = datetime(2026, 11, 23, 13, tzinfo=NAIROBI)
    monkeypatch.setattr("whatsapp_bi.inbox.time.time", now.timestamp)
    settings, branches = pilot
    branches.append(BranchConfig(
        id="main-shop", name="Main Shop", base_url="https://main.example/api/v1/", token_env="KITENGELA_TEST_TOKEN",
    ))
    latest, previous = "2026-11-22", "2026-11-21"
    done = Event()
    answers = []
    reads = []

    def transport(request):
        if request.url.host == "graph.facebook.com":
            answers.append(json.loads(request.content)["text"]["body"])
            done.set()
            return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})
        assert request.url.path == "/api/v1/agent/sales/"
        day = request.url.params["start_date"]
        branch = branches[0] if request.url.host.startswith("kitengela") else branches[1]
        reads.append((branch.id, day))
        if branch.id == "kitengela" and day == previous and baseline_status != 200:
            return httpx.Response(baseline_status)
        amount = ("200.00" if day == latest else baseline_amount) if branch.id == "kitengela" else (
            "150.00" if day == latest else "100.00"
        )
        return httpx.Response(200, json={
            "schema_version": 1, "branch": {"id": branch.id, "name": branch.name},
            "start_date": day, "end_date": day, "timezone": "Africa/Nairobi", "currency": "KES",
            "generated_at": now.isoformat(), "is_provisional": False, "total_sales": amount,
        })

    def respond(messages, _info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("Invented leader")])
        return ModelResponse(parts=[ToolCallPart("get_branch_growth", {
            "metric": "sales",
            "period": {"start_date": latest, "end_date": latest},
            "baseline": {"start_date": previous, "end_date": previous},
        })])

    app = create_app(settings, branches, FunctionModel(respond), transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        incoming = message("growth")
        incoming["text"]["body"] = f"Which branch had the fastest sales growth on {latest} compared with {previous}?"
        assert signed_post(client, payload(change([incoming]))).status_code == 200
        assert done.wait(3)
    assert len(reads) == 4
    assert expected in answers[0]
    assert "Main Shop: KES 150.00 vs KES 100.00 (+50.00%)" in answers[0]
    assert ("Highest percentage growth:" in answers[0]) == (baseline_status == 200 and baseline_amount != "0.00")
    assert "Invented leader" not in answers[0]


@pytest.mark.parametrize("period, day, balanced", [
    ("today", "2026-11-23", True),
    ("today", "2026-11-23", False),
    ("Monday last week", "2026-11-16", True),
])
def test_whatsapp_displays_reconciliation_from_the_branch_report(pilot, monkeypatch, period, day, balanced):
    now = datetime(2026, 11, 23, 13, tzinfo=NAIROBI)
    monkeypatch.setattr("whatsapp_bi.inbox.time.time", now.timestamp)
    provisional = day == now.date().isoformat()
    y_value = "125.75" if balanced else "100.50"
    result_amount = "0.00" if balanced else "-25.25"
    status = "Balanced" if balanced else "Discrepancy"
    done = Event()
    answers = []

    def transport(request):
        if request.url.host == "graph.facebook.com":
            answers.append(json.loads(request.content)["text"]["body"])
            done.set()
            return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})
        assert request.url.path == "/api/v1/agent/reconciliation/"
        assert dict(request.url.params) == {"start_date": day, "end_date": day}
        assert request.headers["Authorization"] == "Bearer branch-token"
        return httpx.Response(200, json={
            "schema_version": 1, "branch": {"id": "kitengela", "name": "Kitengela"},
            "start_date": day, "end_date": day, "timezone": "Africa/Nairobi",
            "currency": "KES", "generated_at": now.isoformat(), "is_provisional": provisional,
            "x_value": "-125.75", "y_value": y_value, "result": result_amount,
            "is_balanced": balanced,
        })

    def respond(messages, _info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("The result is KES 999,999.00.")])
        return ModelResponse(parts=[ToolCallPart("get_reconciliation", {
            "branch": "Kitengela", "report_date": day,
        })])

    incoming = message("report-reconciliation")
    incoming["text"]["body"] = f"Was Kitengela's reconciliation balanced {period}?"
    app = create_app(*pilot, FunctionModel(respond), transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        assert signed_post(client, payload(change([incoming]))).status_code == 200
        assert done.wait(3)

    expected = (
        f"Kitengela — reconciliation for {day}\nStatus: {status}\n"
        f"X: KES -125.75\nY: KES {y_value}\nResult (X + Y): KES {result_amount}"
    )
    if provisional:
        expected += "\nThis result is provisional."
    assert answers == [expected]


@pytest.mark.parametrize("question", [
    "What was Kitengela’s reconciliation last week?",
    "Show Kitengela's reconciliation from 16 to 22 November.",
    "What was Kitengela's reconciliation for the last seven days?",
    "How did Kitengela reconcile from 2026-11-16 through 2026-11-22?",
])
def test_whatsapp_reconciliation_range_requests_one_date_without_looking_up_a_report(pilot, question):
    done = Event()
    answers = []

    def transport(request):
        assert request.url.host == "graph.facebook.com"
        answers.append(json.loads(request.content)["text"]["body"])
        done.set()
        return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})

    def unused(_messages, _info):
        pytest.fail("A clear reconciliation range should be handled before calling the model")

    incoming = message("reconciliation-range")
    incoming["text"]["body"] = question
    app = create_app(*pilot, FunctionModel(unused), transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        assert signed_post(client, payload(change([incoming]))).status_code == 200
        assert done.wait(3)
    assert answers == [RECONCILIATION_DATE_REQUIRED]


def test_follow_up_keeps_context_across_restart_and_isolates_senders(pilot, monkeypatch):
    now = int(datetime(2026, 11, 18, 9, tzinfo=NAIROBI).timestamp())
    monkeypatch.setattr("whatsapp_bi.inbox.time.time", lambda: now)
    settings, branches = pilot
    settings = settings.model_copy(update={"allowed_senders": {SENDER, OTHER_SENDER}})
    follow_up_day = "2026-11-16"
    follow_up = "What about 16 November?"
    previous_branch = "The previous verified answer in this chat was for branch ID kitengela."
    instructions = []
    requests = []
    replies = []
    replied = Event()
    totals = {
        "paybill": "100.00", "pdq": "0.00", "till": "150.00",
        "total_revenue": "250.00", "transaction_count": 2,
    }

    def transport(request):
        if request.url.host == "graph.facebook.com":
            outgoing = json.loads(request.content)
            replies.append((outgoing["to"], outgoing["text"]["body"]))
            replied.set()
            return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})
        day = request.url.params["start_date"]
        requests.append(day)
        assert request.url.params["end_date"] == day
        return httpx.Response(200, json={
            "schema_version": 1, "branch": {"id": "kitengela", "name": "Kitengela"},
            "start_date": day, "end_date": day, "timezone": "Africa/Nairobi",
            "currency": "KES", "generated_at": "2026-11-18T08:00:00Z",
            "is_provisional": False, "totals": totals, "daily": [{"date": day, **totals}],
        })

    def respond(messages, info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("Done.")])
        instructions.append(info.instructions)
        if any(getattr(part, "content", None) == QUESTION for part in messages[-1].parts):
            day = DAY
        elif previous_branch in info.instructions:
            day = follow_up_day
        else:
            return ModelResponse(parts=[TextPart("Which branch?")])
        return ModelResponse(parts=[ToolCallPart("get_revenue", {
            "branch": "Kitengela", "start_date": day, "end_date": day,
        })])

    def app():
        return create_app(settings, branches, FunctionModel(respond), transport=httpx.MockTransport(transport))

    def ask(client, message_id, sender, question):
        replied.clear()
        incoming = message(message_id, sender=sender)
        incoming["text"]["body"] = question
        assert signed_post(client, payload(change([incoming]))).status_code == 200
        assert replied.wait(3)

    with TestClient(app()) as client:
        ask(client, "initial", SENDER, QUESTION)
    with TestClient(app()) as client:
        ask(client, "other-sender", OTHER_SENDER, follow_up)
        ask(client, "follow-up", SENDER, follow_up)
        now += CONTEXT_SECONDS
        ask(client, "expired", SENDER, follow_up)

    assert requests == [DAY, follow_up_day]
    assert previous_branch not in instructions[0]
    assert previous_branch not in instructions[1]
    assert previous_branch in instructions[2]
    assert f"Its date range was {DAY} through {DAY}." in instructions[2]
    assert previous_branch not in instructions[3]
    clarification = "Ask for revenue, sales, or reconciliation for one branch and include the date. Branches: Kitengela."
    assert replies == [
        (SENDER, ANSWER),
        (OTHER_SENDER, clarification),
        (SENDER, ANSWER.replace(DAY, follow_up_day)),
        (SENDER, clarification),
    ]


def test_failed_reply_does_not_replace_the_last_verified_context(tmp_path):
    inbox = Inbox(tmp_path / "inbox.sqlite3")
    now = int(time.time())
    successful = Message("sent", SENDER, now - 2, QUESTION)
    failed = Message("failed", SENDER, now - 1, "What about Main Shop?")
    follow_up = Message("next", SENDER, now, "What about yesterday?")
    verified = ConversationContext(branch_id="kitengela")

    inbox.enqueue([successful, failed])
    assert inbox.reserve_reply(successful.id)
    inbox.finish_reply(successful, sent=True, context=verified)
    assert inbox.reserve_reply(failed.id)
    inbox.finish_reply(failed, sent=False, context=ConversationContext(branch_id="main-shop"))

    assert inbox.get_context(follow_up) == verified


def test_status_and_migration_preserve_the_existing_inbox(tmp_path):
    path = tmp_path / "previous-inbox.sqlite3"
    now = int(time.time())
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE inbox (message_id TEXT PRIMARY KEY, sender TEXT,
            timestamp INTEGER NOT NULL, body TEXT, state TEXT NOT NULL DEFAULT 'pending')"""
        )
        connection.execute("INSERT INTO inbox VALUES (?, NULL, ?, NULL, 'sent')", ("previous", now))

    assert Inbox.recent_statuses(path) == [(now, "sent", None)]
    with sqlite3.connect(path) as connection:
        assert "failure_reason" not in {row[1] for row in connection.execute("PRAGMA table_info(inbox)")}

    Inbox(path)
    Inbox(path)
    assert Inbox.recent_statuses(path) == [(now, "sent", None)]


def test_processes_saved_message_after_restart_without_replaying_uncertain_delivery(pilot):
    inbox = Inbox(pilot[0].inbox_path)
    inbox.enqueue([Message("saved-id", SENDER, int(time.time()), QUESTION)])
    attempted = Event()
    requests = []

    def transport(request):
        requests.append(request)
        attempted.set()
        raise httpx.ReadTimeout("outcome unknown", request=request)

    def respond(_messages, _info):
        return ModelResponse(parts=[TextPart(ANSWER)])

    body = payload(change([message("saved-id")]))
    for _ in range(2):
        app = create_app(*pilot, FunctionModel(respond), transport=httpx.MockTransport(transport))
        with TestClient(app) as client:
            assert attempted.wait(3)
            assert signed_post(client, body).status_code == 200
    assert len(requests) == 1
    with sqlite3.connect(pilot[0].inbox_path) as connection:
        state, reason = connection.execute("SELECT state, failure_reason FROM inbox").fetchone()
    assert state == "failed"
    assert "Delivery outcome is unknown" in reason


@pytest.mark.parametrize("status, meta_code", [(401, None), (400, 190)])
def test_meta_auth_failure_is_recorded_without_leaking_response(
    pilot, monkeypatch, capsys, caplog, status, meta_code
):
    attempted = Event()
    requests = []

    def transport(request):
        requests.append(request)
        attempted.set()
        if meta_code is None:
            return httpx.Response(status, text="raw-secret-text")
        return httpx.Response(status, json={"error": {
            "code": meta_code, "error_subcode": 463, "message": "raw-secret-text",
        }})

    def respond(_messages, _info):
        return ModelResponse(parts=[TextPart("Which date?")])

    settings, branches = pilot
    app = create_app(settings, branches, FunctionModel(respond), transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        assert signed_post(client, payload(change([message("auth-failure")]))).status_code == 200
        assert attempted.wait(3)

    assert len(requests) == 1
    monkeypatch.setenv("WHATSAPP_INBOX_PATH", str(settings.inbox_path))
    assert asyncio.run(execute(argparse.Namespace(command="whatsapp-status"))) == 0
    output = capsys.readouterr().out
    assert "failed — Meta rejected the WhatsApp access token" in output
    assert f"HTTP {status}" in output
    assert "WHATSAPP_ACCESS_TOKEN" in output
    assert "WhatsApp reply failed. Meta rejected the WhatsApp access token" in caplog.text
    if meta_code is not None:
        assert "Meta code 190, subcode 463" in output
    for private in ("raw-secret-text", "graph-token", SENDER, QUESTION):
        assert private not in output
        assert private not in caplog.text


@pytest.mark.parametrize(
    "branch, start, end, feedback",
    [
        ("Unknown", "2026-11-17", "2026-11-17", "I couldn't match that branch. Available branches: Kitengela."),
        ("Kitengela", "2026-11-18", "2026-11-17", "The end date is before the start date."),
        ("Kitengela", "2026-11-31", "2026-11-31", "I couldn't read those dates."),
        ("Kitengela", "2024-11-17", "2026-11-17", "That date range is too long."),
        ("Kitengela", "2026-11-24", "2026-11-24", "Use dates up to today in Nairobi"),
    ],
)
def test_invalid_query_gets_an_actionable_whatsapp_reply(pilot, monkeypatch, branch, start, end, feedback):
    now = datetime(2026, 11, 23, 10, tzinfo=NAIROBI).timestamp()
    monkeypatch.setattr("whatsapp_bi.inbox.time.time", lambda: now)
    done = Event()
    answers = []

    def transport(request):
        assert request.url.host == "graph.facebook.com"
        answers.append(json.loads(request.content)["text"]["body"])
        done.set()
        return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})

    def respond(messages, _info):
        # Exhaust the tool retry budget for the too-long case to test both paths.
        if start != "2024-11-17" and any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("The total was KES 999,999.00.")])
        return ModelResponse(parts=[ToolCallPart("get_revenue", {
            "branch": branch, "start_date": start, "end_date": end,
        })])

    app = create_app(*pilot, FunctionModel(respond), transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        assert signed_post(client, payload(change([message("bad-query")]))).status_code == 200
        assert done.wait(3)
    answer, = answers
    assert feedback in answer
    assert "KES" not in answer



def test_relative_date_uses_nairobi_send_date_and_unverified_text_is_discarded(pilot, monkeypatch):
    sent_at = datetime(2026, 11, 17, 23, 55, tzinfo=NAIROBI)
    processed_at = sent_at + timedelta(minutes=10)
    monkeypatch.setattr("whatsapp_bi.inbox.time.time", lambda: processed_at.timestamp())
    delivered = Event()
    instructions = []
    requests = []

    def respond(_messages, info):
        instructions.append(info.instructions)
        return ModelResponse(parts=[TextPart("Yesterday's revenue was KES 999,999.00.")])

    def transport(request):
        requests.append(request)
        delivered.set()
        return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})

    incoming = message("near-midnight")
    incoming["timestamp"] = str(int(sent_at.timestamp()))
    incoming["text"]["body"] = "What was Kitengela's revenue yesterday?"
    app = create_app(*pilot, FunctionModel(respond), transport=httpx.MockTransport(transport))
    with TestClient(app) as client:
        assert signed_post(client, payload(change([incoming]))).status_code == 200
        assert delivered.wait(3)

    assert "Today in Africa/Nairobi is 2026-11-17" in instructions[0]
    assert "Yesterday is 2026-11-16" in instructions[0]
    assert [request.url.host for request in requests] == ["graph.facebook.com"]
    body = json.loads(requests[0].content)["text"]["body"]
    assert body == "Ask for revenue, sales, or reconciliation for one branch and include the date. Branches: Kitengela."
