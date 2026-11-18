# WhatsApp BI agent: first real-data capability

This first slice answers branch revenue questions using a dedicated authenticated
inventory API. The runtime has no sample-data mode and never falls back to fixtures.
WhatsApp transport, charts, sales, briefing schedules and cross-branch totals are
later slices. The existing learning scripts can stay alongside this package.

Current status: local API/client/framework tests are implemented. An authenticated
production read requires deploying the accompanying backend endpoint and supplying
branch credentials. No production deployment or live model run has been performed.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
cp branches.example.json branches.json
cp .env.example .env
```

Set MAIN_SHOP_BI_TOKEN and KITENGELA_BI_TOKEN in .env to the respective backend's
BI_AGENT_API_KEY, using your local editor. Set OPENAI_API_KEY for natural-language
requests. Neither branch tokens nor URLs come from the model; configuration controls
the destinations. Branch IDs and display names are accepted case-insensitively.
Add a branch by adding its entry and token, without editing tool code.

The backend PR adds `GET /api/v1/agent/revenue/`. It uses a dedicated read-only
credential, not the existing generic bi/execute endpoint.

First verify the API without an LLM call:

```bash
python -m whatsapp_bi revenue --branch Kitengela --start 2026-11-17 --end 2026-11-17
```

Compare these gateway totals with the branch's recorded receipts. Then ask:

```bash
python -m whatsapp_bi ask "What was Kitengela's revenue yesterday?" --trace
```

The revenue command exits nonzero on unavailable data. `--trace` shows tool arguments
and aggregated results, never HTTP authorization headers. The agent's default model
is openai:gpt-5-mini; override BI_MODEL in .env. Each agent run is bounded to six model
requests and four tool calls. This CLI is one-shot; it does not yet retain conversation
history or accept inbound WhatsApp messages.

## The decisions that matter

1. **Django owns the metric.** It sums recorded receipts using decimal arithmetic and
   Nairobi date boundaries, excluding synthetic combined-order parents and exact
   internal transfers. The agent does not generate SQL or decide accounting rules.
2. **The model interprets intent.** Pydantic validates branch/date arguments before
   execution. A dependency-injected RevenueClient makes authenticated GET requests.
3. **The client checks evidence.** Responses must match the branch and dates, include
   all daily rows, and reconcile daily and gateway sums. Outages and malformed data
   yield structured problems, never invented zeros.
4. **Small context.** The client verifies the full daily report, while the model
   receives a compact typed summary. A year-long total doesn't need a year of rows
   in the model context. The daily rows remain available for later chart work.
5. **Trace before trusting.** A completed backend query with zero recorded receipts
   is different from a failed query. The current day is provisional. Today's
   calendar context is recomputed for each agent run.

## Code map

| File | Responsibility | Pydantic AI concept |
|---|---|---|
| whatsapp_bi/models.py | Query/result/config contracts and consistency checks | Pydantic validation and model inheritance |
| whatsapp_bi/client.py | Branch routing and authenticated HTTP reads | Runtime dependency |
| whatsapp_bi/agent.py | One tool, instructions and per-run calendar context | Agent, RunContext, @agent.tool, @agent.instructions |
| whatsapp_bi/__main__.py | Direct verification, question execution and traces | await agent.run, usage limits, message inspection |

The backend returns actual recorded receipts, not fulfillment values. Revenue
includes Paybill, PDQ and Till only. Shared Till/Merch payment relay means adding
branch revenues is not a supported company-wide total yet. Do not sum them blindly.

## Tests

```bash
python -m pytest -q
```

Tests use isolated HTTP fixtures and a FunctionModel to verify framework wiring
without charging a model API or calling production. Fixtures exist only under tests.
These tests do not claim to validate a real model's natural-language behavior;
live model evaluation follows the first authenticated data check.

If you receive not_deployed, install the backend endpoint first. Authentication
failures require matching per-branch credentials. No credentials are printed in
error messages. Backend health currently reports an existing Celery inspect error;
verify the actual revenue endpoint independently rather than treating that health
status as proof that the database is unavailable.
