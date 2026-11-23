# WhatsApp BI agent: first real-data capability

This first slice answers branch revenue questions using a dedicated authenticated
inventory API. The runtime has no sample-data mode and never falls back to fixtures.
The WhatsApp pilot replies to allowed senders. A current stock question includes
all low-stock and out-of-stock products by default. Long replies arrive in
numbered messages. Ask for a specific page to see a smaller stock list.
It can compare two periods at the same branch, showing each total and the change in KES.
Within 30 minutes of a successfully answered question, the same sender can ask a follow-up
such as “What about 16 November?” The agent stores the prior branch and, for a
single-period answer, its date range. A follow-up fetches fresh data through the API.
After a comparison within one month, “What of the 18th?” retrieves a single day in
that month. If the comparison spans months, include the month in the follow-up.
Charts, sales, briefings and cross-branch totals are later slices.

The Kitengela revenue API and the live agent agreed with the recorded gateway
figures for 17 November 2026. The webhook integration tests cover the WhatsApp
flow with simulated Meta requests and replies. A live WhatsApp round trip
requires configuring a Meta test number and an HTTPS callback.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
cp .env.example .env
```

Set `BI_BRANCH_DISCOVERY_URL` to the central inventory backend's HTTPS API base
URL ending in `/api/v1/` and `BI_BRANCH_DISCOVERY_TOKEN` to that backend's
`BI_AGENT_API_KEY`. Deploy the central backend with `GET /api/v1/agent/branches/`
before updating the agent configuration. The directory uses the same branch
registry as cross-branch inventory (`PAYMENT_RELAY_TARGETS` on that backend).

Set `MAIN_SHOP_BI_TOKEN` and `KITENGELA_BI_TOKEN` to the respective backend's
`BI_AGENT_API_KEY`. For a newly registered branch, set the token named after its
branch ID, in uppercase with hyphens replaced by underscores, such as
`NEW_BRANCH_BI_TOKEN`. Use `python -m whatsapp_bi branches` to see discovered
branches and whether their credentials are set. Branch IDs and display names
are accepted case-insensitively. Set `OPENAI_API_KEY` for API-funded
natural-language requests, or configure the ChatGPT sign-in described below.

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

For a comparison, try `python -m whatsapp_bi ask "Compare Kitengela revenue on 17 November 2026 with 16 November 2026" --trace`.
`compare_revenue` validates both date ranges and calculates the change from the verified totals.

Ask for revenue “by day” to get the daily breakdown from `get_revenue`. The reply
shows the total for the full requested range and up to its most recent 31 days,
subject to WhatsApp's message limit. Ask for “by gateway and by day” to see Paybill,
PDQ, and Till within each date. Ask for a “revenue trend” to add the last seven days
versus the preceding seven when both windows are covered.

Ask for “month-to-month revenue” over a date range to see monthly totals and
comparisons between consecutive complete calendar months. The reply labels the
current month as incomplete and shows the exact dates for partial months.

Ask “What were Kitengela's sales on 23 November 2026?” to query the read-only
branch sales endpoint. The reply shows one fulfilled sales total for the
inclusive Nairobi dates, excluding merchandise fulfillment.
Ask for sales by day, the sales trend, or month-to-month sales for dated totals
and comparisons. Ask for best-selling products to get up to ten ranked by units
sold, with their fulfilled value in KES. If the existing fulfillment records
cannot verify the requested detail, the agent explains that it is unavailable.

Ask “Was Kitengela's reconciliation balanced on 23 November 2026?” for a branch's
status, X, Y, and result on one Nairobi reporting date. The branch's existing
`ReconciliationV2Service` calculates those figures and the agent displays them.

In Nairobi time, “last week” means the previous Monday through Sunday. “Last N days”
uses completed reporting days ending yesterday. Say “including today” to include the
provisional current day in that rolling window.

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
python -m whatsapp_bi ask "What was Kitengela's revenue on 17 November 2026?" --trace
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
| whatsapp_bi/agent.py | Revenue and comparison tools, instructions and per-run calendar context | Agent, RunContext, @agent.tool, @agent.instructions |
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

## Registration reporting and briefing preview

Ask WhatsApp how many registrations a branch completed over a period. The
report counts kits issued on marked transactions by their Nairobi issuance
date. Two kits on one transaction count as two registrations. The separate
registration margin is KES 200 per kit.

Run `python -m whatsapp_bi briefing-preview --date YYYY-MM-DD` in the agent
container to see the branch sections and compact revenue and sales charts. Each
chart shows one bar per day from the first of the month through the report date.
The seven-day comparison shows its own dates. The daily delivery time is
agreed as 23:59:59 Africa/Nairobi and still needs WhatsApp delivery setup.

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

Only add numbers permitted to see revenue for the discovered branches.

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

### Diagnose missing replies

Inside the bot container, run `python -m whatsapp_bi whatsapp-status` to see the
last ten inbox states and any recorded failure reasons. The output uses Nairobi
time and omits sender numbers, question text, and credentials. A `sent` status
means Meta accepted the reply. If Meta rejects the access token, replace
`WHATSAPP_ACCESS_TOKEN` in Dokploy, redeploy BI, and send a new test question.
The bot cannot notify the WhatsApp user while Meta is rejecting its sends.

When replies can be sent, the bot gives corrective feedback for unknown branches,
unreadable dates, reversed ranges, and requests beyond the supported range. If
verified figures are unavailable, it tells the user to retry.
