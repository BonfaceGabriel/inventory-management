import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from whatsapp_bi.briefing import BriefingDocument
from whatsapp_bi.briefing_delivery import (
    BriefingDelivery,
    BriefingDeliveryError,
    BriefingDeliverySettings,
    due_briefing_day,
    next_briefing_time,
)
from whatsapp_bi.client import RevenueClient
from whatsapp_bi.inbox import Inbox
from whatsapp_bi.models import BranchConfig, NAIROBI
from whatsapp_bi.whatsapp import WhatsAppSettings


REPORT_DAY = date(2026, 11, 23)
RECIPIENT = "15555550123"
CHAT = ("2026-11-23", "KES 150.00", "Incomplete", "KES 20.00", "KES 850.00")


def test_schedule_uses_235959_nairobi_and_only_a_short_restart_window():
    before = datetime(2026, 11, 23, 20, 59, 58, tzinfo=UTC)
    on_time = datetime(2026, 11, 23, 20, 59, 59, tzinfo=UTC)
    after_restart = datetime(2026, 11, 24, 0, 5, tzinfo=NAIROBI)
    too_late = datetime(2026, 11, 24, 0, 10, tzinfo=NAIROBI)
    assert due_briefing_day(before) is None
    assert next_briefing_time(before) == on_time
    assert due_briefing_day(on_time) == REPORT_DAY
    assert due_briefing_day(after_restart) == REPORT_DAY
    assert due_briefing_day(too_late) is None
    assert next_briefing_time(after_restart) == datetime(2026, 11, 24, 23, 59, 59, tzinfo=NAIROBI)


@pytest.fixture
def pilot(tmp_path):
    whatsapp = WhatsAppSettings(
        app_secret="test-app-secret", verify_token="test-verify-token", access_token="test-meta-token",
        phone_number_id="444444", allowed_senders={RECIPIENT, "15555550124"},
        inbox_path=tmp_path / "inbox.sqlite3",
    )
    config = BriefingDeliverySettings(recipient=RECIPIENT, template="inventory_daily_briefing")
    return whatsapp, config


def test_schedule_defaults_off_and_only_targets_one_allowlisted_recipient(pilot, monkeypatch):
    monkeypatch.delenv("WHATSAPP_BRIEFING_ENABLED", raising=False)
    assert BriefingDeliverySettings.scheduled_from_env() is None
    whatsapp, _ = pilot
    config = BriefingDeliverySettings(recipient="15555550000", template="inventory_daily_briefing")
    with pytest.raises(BriefingDeliveryError, match="WHATSAPP_ALLOWED_SENDERS"):
        BriefingDelivery(whatsapp, config, Inbox(whatsapp.inbox_path))


async def test_schedule_dispatches_the_closed_report_day(pilot, monkeypatch):
    whatsapp, config = pilot
    sender = BriefingDelivery(whatsapp, config, Inbox(whatsapp.inbox_path))
    clock = datetime(2026, 11, 23, 23, 59, 58, tzinfo=NAIROBI)
    waits = []
    dispatched = []

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz):
            return clock.astimezone(tz)

    async def sleep(seconds):
        nonlocal clock
        waits.append(seconds)
        if len(waits) == 3:
            raise asyncio.CancelledError
        clock += timedelta(seconds=seconds)

    async def load(_http):
        return [BranchConfig(id="site", name="Site", base_url="https://example.com", token_env="TOKEN")]

    async def deliver(_client, day):
        dispatched.append((day, clock))
        return "sent"

    monkeypatch.setattr("whatsapp_bi.briefing_delivery.datetime", FrozenDateTime)
    monkeypatch.setattr("whatsapp_bi.briefing_delivery.asyncio", SimpleNamespace(sleep=sleep, timeout=asyncio.timeout))
    monkeypatch.setattr(sender, "deliver", deliver)
    async with httpx.AsyncClient() as http:
        with pytest.raises(asyncio.CancelledError):
            await sender.run(SimpleNamespace(load=load), http)
    assert waits == [1, 1, 86399]
    assert dispatched == [(REPORT_DAY, datetime(2026, 11, 24, 0, 0, tzinfo=NAIROBI))]


@pytest.mark.parametrize("scenario", ["success", "rejection", "unknown"])
async def test_pdf_template_summary_and_delivery_deduplication(pilot, monkeypatch, scenario):
    whatsapp, config = pilot
    calls = []

    async def build(_client, day):
        assert day == REPORT_DAY
        return BriefingDocument(
            day=day, chat_values=CHAT, branch_names=("Branch A",),
            text="*Daily briefing*\n\n*Branch A*\n\n*Revenue*\nRevenue by day, November\n▁▃█\n"
                 "*Stock*\nProduct A: 2 remaining (low stock)\n\n*All branches*\nStock at cost: KES 850.00",
        )

    monkeypatch.setattr("whatsapp_bi.briefing_delivery.build_briefing", build)
    sent = 0

    def mock_graph(request):
        nonlocal sent
        assert request.url.host == "graph.facebook.com"
        assert request.headers["Authorization"] == "Bearer test-meta-token"
        calls.append(request.url.path.rsplit("/", 1)[-1])
        if calls[-1] == "media":
            assert "multipart/form-data" in request.headers["Content-Type"]
            assert b"%PDF" in request.content
            assert b"inventory-briefing-2026-11-23.pdf" in request.content
            return httpx.Response(200, json={"id": "test-media-id"})
        sent += 1
        body = json.loads(request.content)
        assert body["to"] == RECIPIENT
        assert body["type"] == "template"
        assert body["template"]["name"] == config.template
        header, text = body["template"]["components"]
        assert header["parameters"][0]["document"]["id"] == "test-media-id"
        assert tuple(parameter["text"] for parameter in text["parameters"]) == CHAT
        if sent == 1 and scenario == "unknown":
            raise httpx.ReadTimeout("test", request=request)
        if sent == 1 and scenario == "rejection":
            return httpx.Response(400, json={"error": {"code": 132001}})
        return httpx.Response(200, json={"messages": [{"id": "test-message-id"}]})

    branch = BranchConfig(id="branch-a", name="Branch A", base_url="https://example.com/api/v1/", token_env="BI_TOKEN")
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_graph)) as http:
        client = RevenueClient([branch], http)
        sender = BriefingDelivery(whatsapp, config, Inbox(whatsapp.inbox_path))
        if scenario == "success":
            assert await sender.deliver(client, REPORT_DAY) == "sent"
        else:
            with pytest.raises(BriefingDeliveryError):
                await sender.deliver(client, REPORT_DAY)
        restarted = BriefingDelivery(whatsapp, config, Inbox(whatsapp.inbox_path))
        state = {"success": "sent", "unknown": "unknown", "rejection": "rejected"}[scenario]
        assert await restarted.deliver(client, REPORT_DAY) == state
        assert calls == ["media", "messages"]
        expected = "sent" if scenario == "rejection" else state
        assert await restarted.deliver(client, REPORT_DAY, retry_rejected=True) == expected
        assert calls == ["media", "messages"] * (2 if scenario == "rejection" else 1)
