# Read-only revenue API for the new BI agent

`GET /api/v1/agent/revenue/?start_date=2026-11-17&end_date=2026-11-17`

Authenticate with `Authorization: Bearer <BI_AGENT_API_KEY>`. The endpoint is
disabled when that setting is empty. This credential is separate from website
inventory keys, Android device keys and user JWTs, and is accepted only here.
POST and other mutating methods are unsupported. Responses have `Cache-Control: no-store`.

## Metric definition

- Revenue is recorded money received, using `Transaction.timestamp`.
- Paybill, PDQ and Till are explicit gateway types; Merchandise and unclassified
  gateways are excluded. A merchandise purchase paid on PDQ/Till is still money
  received on that gateway. Merchandise fulfillment is a separate metric.
- Count real combined-order child receipts once, exclude their synthetic parent.
- Cancelled orders remain receipts: cancelling fulfillment does not record a refund.
- Exclude the exact internal sender identity `7974481` and its organization-name
  prefix; a real phone containing those digits remains included.
- Dates and daily grouping use Africa/Nairobi. The requested range is inclusive;
  the SQL interval runs from start midnight to next-day midnight exclusively.
- Amounts are decimal strings, calculated with Decimal/SQL numeric sums.
- A successful database query includes every requested day. A day without recorded
  receipts has explicit zero totals. This is a report of database contents, not
  independent proof that every external SMS has been ingested.
- Today is marked provisional. Historical queries also reflect current database
  contents rather than immutable accounting snapshots.
- Each deployment answers for its configured `BRANCH_NAME`. Intra-instance
  Locations are not separate branches. This endpoint does not aggregate branches.
- Up to 366 days per call; reversed, missing, malformed and future dates fail validation.

## Response contract (version 1)

Top level: schema_version, branch {id,name}, start_date, end_date,
timezone='Africa/Nairobi', currency='KES', generated_at, is_provisional,
totals, daily. Totals contains paybill, pdq, till, total_revenue (all decimal
strings) and transaction_count. Each daily row adds date to the same fields.

The client verifies daily coverage, sums, branch identity and requested dates.
Authentication errors, failed requests and inconsistent payloads remain unavailable;
the client must not convert them to zero revenue.

## Dokploy rollout

1. Review and merge this endpoint change, then deploy it to each branch backend.
2. Set a new random `BI_AGENT_API_KEY` in each branch's Dokploy environment; use
   different keys for Main Shop and Kitengela. Compose forwards it to the web service.
   Redeploy web containers after setting the environment. No migration is required.
3. Confirm BRANCH_NAME is correct on each deployment.
4. Put the corresponding values in the agent's MAIN_SHOP_BI_TOKEN and
   KITENGELA_BI_TOKEN environment variables. Never commit tokens or include them in
   model prompts. Keep the branch URLs in the agent's branch configuration.
5. Run the agent CLI's direct revenue command for a completed day. Independently
   check gateway amounts against that day's receipts, then run a natural-language
   request with --trace. Live reads require deployed code and configured credentials.

Rollback: clear BI_AGENT_API_KEY to disable access, or revert this additive change.
Existing Telegram, fulfillment, payment ingestion, reporting and inventory APIs
retain their existing behavior. This does not repair the previously identified
generic bi/execute endpoint or the unrelated health-check bug.

## Validation

Targeted tests: `python manage.py test payments.tests.test_agent_revenue_api`.
Coverage includes authentication, method restriction, date bounds, monetary accuracy,
Nairobi day boundaries, zero days, internal sender exclusions, combined-order receipts,
cancelled receipts and today's provisional label. Local tests used SQLite; deployment
verification against the live PostgreSQL instances is still required.
