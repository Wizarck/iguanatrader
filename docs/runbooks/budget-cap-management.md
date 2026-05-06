# Runbook — Budget Cap Management

**Owner**: slice O1 (`observability-cost-meter`).

**When to run**: A tenant is at WARN_80 (80% spent) or BLOCK_100 (100%); operator needs to inspect spend, raise the cap, or wait for next-month rollover.

## Inspect current spend

### Via the API (authenticated tenant)

```sh
# Replace with the slice-4 cookie + tenant
curl --cookie iguana_session=<token> \
     https://api.example.com/api/v1/costs/summary
```

Response (`CostSummaryDTO`):

```json
{
  "tenant_id": "...",
  "period_start": "2026-05-01T00:00:00Z",
  "period_end": "2026-06-01T00:00:00Z",
  "total_cost_usd": "47.85",
  "total_calls": 1284,
  "cached_calls": 312
}
```

### Via the API (per-provider breakdown)

```sh
curl --cookie iguana_session=<token> \
     https://api.example.com/api/v1/costs/by-provider
```

Returns `CostByProviderDTO` with per-row `(provider, cost_usd, call_count)`. Useful when one provider (e.g. opus for complex synthesis) is dominating spend.

### Via direct DB read (operator)

```sh
sqlite3 ./data/iguanatrader.db <<'SQL'
SELECT
  provider,
  model,
  COUNT(*) AS calls,
  SUM(cost_usd) AS spent_usd,
  SUM(CASE WHEN cached THEN 1 ELSE 0 END) AS cached_calls
FROM api_cost_events
WHERE tenant_id = ?
  AND created_at >= '2026-05-01T00:00:00Z'
GROUP BY provider, model
ORDER BY spent_usd DESC;
SQL
```

## Raise the cap (operator)

The default monthly cap is `$50/tenant`. Raise it via the slice O2 CLI when it lands:

```sh
poetry run iguanatrader admin set-budget <tenant-id> 200.00
```

Until slice O2 ships, edit directly:

```sh
sqlite3 ./data/iguanatrader.db <<'SQL'
UPDATE tenants
SET feature_flags = json_set(feature_flags, '$.llm_budget_usd', '200.00')
WHERE id = ?;
SQL
```

The next `check_budget` call (typically the next `route_llm` invocation) reads the new value. The in-process WARN_80 dedup cache is keyed by `(tenant_id, year, month)`, so:

- If the tenant was at BLOCK_100, the next routing decision succeeds.
- If the tenant was at WARN_80, the next routing decision still downgrades because the cap raise lifts the percentage below 80% — but the cache says "already warned this month", so no fresh `observability.budget.warning_threshold` event fires.
- The dedup cache is process-local; restarting the API resets it.

## Operational meaning of BLOCK_100

When `route_llm()` raises `BudgetExceededError`, the calling routine receives a 402 RFC 7807 response:

```json
{
  "type": "urn:iguanatrader:error:budget-exceeded",
  "title": "Budget Exceeded",
  "status": 402,
  "detail": "Tenant ... exceeded the monthly LLM budget cap..."
}
```

Routines (slice O2) should check `check_budget(tenant_id)` at routine entry and abort cleanly before any LLM spend if the state is BLOCK_100. The "best effort no-spend-after-block" is the contract — a routine that started at 95% spend may fire 1-2 LLM calls before the next gate runs (per design Risks).

## Auto-downgrade in practice

At WARN_80 (80% ≤ percent_used < 100%), `route_llm()` returns:

- `RESEARCH_BRIEF` → `claude-3-5-haiku` instead of `claude-3-5-sonnet` (per `_DOWNGRADE_TABLE`).
- `COMPLEX_SYNTHESIS` → `claude-3-5-sonnet` instead of `claude-3-opus`.
- Other task classes retain their canonical tier (Haiku and gpt-4o-mini have no cheaper rung).

Caller code does not need to handle the downgrade explicitly — the returned tier is the model the caller should pass to the LLM SDK. Quality may drop slightly on Haiku for synthesis tasks; operators raise the cap rather than chase quality regressions.

## Cross-references

- `docs/gotchas.md` #61 — default cap rationale.
- `docs/gotchas.md` #62 — process-local throttle (related topic for v2 multi-worker).
- `apps/api/src/iguanatrader/contexts/observability/budget.py` — implementation.
- `openspec/changes/observability-cost-meter/design.md` D4 — design rationale.
