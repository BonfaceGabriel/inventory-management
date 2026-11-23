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
    resolved_question = f"What was revenue for kitengela on {follow_up_day}?"
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
        assert answers[1] == "Ask for one branch's revenue and include a date or date range. Branches: Kitengela."
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
    clarification = "Ask for one branch's revenue and include a date or date range. Branches: Kitengela."
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
    assert body == "Ask for one branch's revenue and include a date or date range. Branches: Kitengela."
