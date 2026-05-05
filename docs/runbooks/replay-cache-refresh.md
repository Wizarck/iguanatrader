# Runbook — Replay-Cache Refresh

**Owner**: slice O1 (`observability-cost-meter`).

**When to run**: Recorded LLM responses under `apps/api/tests/fixtures/replay_cache/` no longer match the production behaviour (model-version bump, prompt-template change, vendor schema drift). Symptom: `test_replay_cache.py::test_deterministic_across_runs` passes but a downstream test that uses the same scenario fails because the recorded payload has the wrong shape.

## Prerequisites

- Real LLM credentials available in the environment (Anthropic / OpenAI / Perplexity API keys per the slice that owns the scenario — slice R5 for research briefs, slice P1 for proposal authoring).
- Operator awareness that **record mode consumes real LLM budget**: each scenario fired against the real provider draws from `tenants.feature_flags["llm_budget_usd"]` (or the dev sandbox tenant). Refreshing 20 scenarios at $0.05 each = $1; refreshing 200 fixtures × Sonnet pricing can exceed $50 quickly.
- Nothing else is running against the dev tenant at the same time (otherwise `WARN_80` may fire mid-refresh, downgrading the model and producing a non-canonical fixture).

## Procedure

### 1. Snapshot the current fixture state

```sh
git status apps/api/tests/fixtures/replay_cache/
# Expect clean working tree — refresh diffs land as one commit.
```

### 2. Set the record mode env vars

```sh
export IGUANATRADER_LLM_REPLAY_RECORD=1
# Do NOT also set IGUANATRADER_LLM_REPLAY=1 — record mode supersedes
# replay mode by writing fresh fixtures from real responses.
```

### 3. Run the targeted test scenario

For a single scenario:

```sh
poetry run pytest \
  apps/api/tests/integration/test_replay_cache.py::test_hit_returns_recorded_response \
  -v
```

For an entire test module that exercises multiple scenarios:

```sh
poetry run pytest \
  apps/api/tests/integration/test_research_brief_synthesis.py \
  -v
```

The record-mode SDK adapters (slice R5+) call the real LLM, capture the response, and write the simplified triple (`tokens_input`, `tokens_output`, `content`) to `apps/api/tests/fixtures/replay_cache/<scenario>.json`.

### 4. Verify the new fixtures

```sh
git diff apps/api/tests/fixtures/replay_cache/
```

Sanity-check each diff:

- `tokens_input` / `tokens_output` are non-zero integers.
- `content` is non-empty + matches the expected response shape (e.g., the research-brief schema for `scenario_research_brief_aapl`).

### 5. Re-run in replay mode to confirm determinism

```sh
unset IGUANATRADER_LLM_REPLAY_RECORD
export IGUANATRADER_LLM_REPLAY=1

poetry run pytest \
  apps/api/tests/integration/test_replay_cache.py \
  apps/api/tests/integration/test_research_brief_synthesis.py
```

All tests must pass without hitting the real LLM. If any test fails, the fixture shape is wrong — revert + retry with a smaller scenario set.

### 6. Commit + cross-reference

```sh
git add apps/api/tests/fixtures/replay_cache/
git commit -m "chore(test): refresh replay-cache fixtures for slice <X>"
```

Reference the slice that owns the scenario in the commit body so downstream maintainers can find the LLM-call site.

## Budget caveat

A full refresh against Anthropic Claude 3.5 Sonnet at $3 / 1 M input + $15 / 1 M output tokens, assuming 100 scenarios × 5 K input + 1 K output tokens per scenario, costs:

```
100 × (5_000 / 1_000_000 × $3 + 1_000 / 1_000_000 × $15)
= 100 × ($0.015 + $0.015)
= $3.00
```

Budget the refresh accordingly; if the dev tenant cap is the default `$50/month`, a refresh consumes ~6% of monthly budget. Operators with smaller dev caps should run the `iguanatrader admin set-budget` CLI (slice O2) to bump the cap before the refresh.

## Rollback

If the refreshed fixtures cause downstream test failures:

```sh
git checkout HEAD -- apps/api/tests/fixtures/replay_cache/
```

The previous commit's fixtures are restored; the test suite reverts to the prior recorded responses. Investigate the schema drift before retrying.

## Cross-references

- `docs/gotchas.md` #60 — cost meter callsite enforcement.
- `apps/api/src/iguanatrader/contexts/observability/replay_cache.py` — implementation.
- `openspec/changes/observability-cost-meter/design.md` D5 — design rationale.
