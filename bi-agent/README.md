# WhatsApp BI agent: first real-data capability

This first slice answers branch revenue questions using a dedicated authenticated
inventory API. The runtime has no sample-data mode and never falls back to fixtures.
The WhatsApp pilot sends one reply to an allowed sender for each incoming text.
Charts, sales, briefings, cross-branch totals and conversation history are later slices.

The Kitengela revenue API and the live agent agreed with the recorded gateway
figures for 17 November 2026. The webhook integration tests cover the WhatsApp
flow with simulated Meta requests and replies. A live WhatsApp round trip
requires configuring a Meta test number and an HTTPS callback.

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
requests and four tool calls. The CLI handles one question at a time. The webhook below
provides the WhatsApp transport.

## Use your ChatGPT Plus plan locally

Sign in with ChatGPT lets eligible Plus accounts authorize this agent to use
their plan allowance. Pydantic AI handles OAuth and refreshes the connection.
The Kitengela BI token still authenticates requests to the inventory API.
[OpenAI Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source)

From `bi-agent/`, after installing the package:

```bash
python -m whatsapp_bi chatgpt-login
python -m whatsapp_bi chatgpt-models
```

Open the printed sign-in URL in a browser on the same computer and approve
ChatGPT plan usage. Choose a model from the second command's output, then set
`BI_MODEL` in `bi-agent/.env` to that complete value, including the
`openai-chatgpt:` prefix. To test it with the existing Kitengela BI token:

```bash
python -m whatsapp_bi --config branches.example.json \
  ask "What was Kitengela's revenue on 17 November 2026?" --trace
```

The default session location is `~/.local/state/whatsapp-bi/chatgpt`. To run the
local WhatsApp container in this mode, mount that directory read-write at
`/data/chatgpt`, set `BI_CHATGPT_STATE_DIR=/data/chatgpt`, and make it owned by
the container's runtime UID. Keep the directory private and run one process per
session while testing, since refreshing rotates the token. Manage consent and
usage limits in [ChatGPT Settings](https://chatgpt.com/#settings).

The API-key model option remains available. Confirm eligibility for your
deployed use case before relying on the Plus session on Dokploy. OpenAI provides
deployment instructions for open-source apps on self-hosted VMs.
[OpenAI self-hosted VM guide](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)

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

## WhatsApp pilot with Docker

The webhook accepts a signed text event for the configured Meta phone number.
It saves the message in a SQLite inbox and immediately acknowledges the event.
A worker runs the same Pydantic AI agent as the CLI and replies to the original
message through Meta. Python formats the gateway figures from a verified tool
result. Each question needs a branch and a date or date range. Relative dates
use the date of the incoming message in Africa/Nairobi.

### Configure

1. In the Meta app dashboard, set up WhatsApp Cloud API, add your own number as
   a test recipient and save the sender's **Phone Number ID** and access token.
   Copy the app secret from the app settings. [Meta WhatsApp Cloud API](https://developers.facebook.com/documentation/business-messaging/whatsapp/overview)
2. In the agent's environment, keep `OPENAI_API_KEY` and `KITENGELA_BI_TOKEN`.
   Add the settings below. Generate a separate random verify token with
   `openssl rand -hex 32`.

| Environment variable | Value |
|---|---|
| `WHATSAPP_APP_SECRET` | Meta app secret used to verify signed events |
| `WHATSAPP_VERIFY_TOKEN` | Random value you also enter when registering the callback |
| `WHATSAPP_ACCESS_TOKEN` | Meta Cloud API access token |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta sender's Phone Number ID |
| `WHATSAPP_ALLOWED_SENDERS` | Comma-separated recipient numbers in international format, digits only |
| `WHATSAPP_GRAPH_VERSION` | Graph API version, defaults to `v27.0` |

Only add numbers permitted to see revenue for the configured branches. For a
Kitengela-only deployment, mount a copy of `branches.example.json` containing
only the Kitengela entry at `/app/branches.json`. The bundled file contains
both public branch URLs.

### Start the service

From `bi-agent/`, build and run the container with your local `.env`.

```bash
docker build -t whatsapp-bi-pilot .
docker run --rm --name whatsapp-bi-pilot --env-file .env \
  -p 127.0.0.1:8082:8000 -v whatsapp-bi-inbox:/data whatsapp-bi-pilot
```

Check `http://127.0.0.1:8082/health/` to confirm the local startup. Meta needs a
public HTTPS callback. For a VPS pilot, create a **separate Dokploy application**
for this image. Use `bi-agent/` as the Docker build context, route the HTTPS
domain to container port 8000, configure the same environment variables, and
attach a persistent volume at `/data` writable by UID 10001. Run one replica.
Keep the webhook verification query string out of proxy access logs.

### Test a real message

Enter `https://<agent-domain>/webhooks/whatsapp/` and the verify token in Meta's
webhook settings, then subscribe to the WhatsApp Business Account `messages`
field. From your allowlisted WhatsApp number, send
“What was Kitengela's revenue on 17 November 2026?” Check the reply against the
verified revenue totals. [Meta Webhooks](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/)

The inbox persists accepted questions across restarts. It clears the saved
sender and question when an outbound delivery starts and keeps the incoming ID
for deduplication. The worker retries pre-delivery connection failures twice
with a short delay. It records ambiguous delivery attempts without replaying
them because Meta may already have accepted the reply.
