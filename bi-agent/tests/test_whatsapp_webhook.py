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

from whatsapp_bi.inbox import Inbox, Message
from whatsapp_bi.models import NAIROBI, BranchConfig
from whatsapp_bi.web import MAX_WEBHOOK_BYTES, UNAVAILABLE_REPLY, create_app
from whatsapp_bi.whatsapp import WhatsAppSettings

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


@pytest.mark.parametrize("baseline_available", [True, False])
def test_signed_comparison_uses_both_verified_periods(pilot, baseline_available):
    question = "Compare Kitengela revenue on 17 November 2026 with 16 November 2026"
    baseline_day = "2026-11-16"
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
        amount = {DAY: "250.10", baseline_day: "200.05"}[day]
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

    def respond(messages, _info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("Revenue changed by KES 999,999.00.")])
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

    assert dates == [DAY, baseline_day]
    expected = (
        "Kitengela\nPeriod (2026-11-17): KES 250.10\n"
        "Baseline (2026-11-16): KES 200.05\nChange: KES +50.05"
    )
    assert answers == [expected if baseline_available else UNAVAILABLE_REPLY]


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
        assert connection.execute("SELECT state FROM inbox").fetchone() == ("failed",)



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
