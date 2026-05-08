# Proposal: r6-hindsight-integration

> **Closes original MVP plan slice 19 of 20**. Ships Hindsight (semantic-recall narrative bank) as a complement to SQL bitemporal facts:
> - **FR80 retain**: ALWAYS-ON write of brief summaries via bus-bridge follow-up on `ResearchBriefSynthesized` event.
> - **FR81 recall**: TOGGLABLE per-tenant read of narrative context, gated by `tenants.feature_flags.hindsight_recall_enabled` (default OFF).
>
> SQL bitemporal stays source-of-truth for citation chain (NFR-O8) + provenance + audit. Hindsight is purely additive narrative.

## Why

R5 brief synthesis ships the structured-citations path (`ResearchFact` rows with `[fact:<uuid>]` markers). What it cannot capture is **soft narrative context** across briefs over time — recurring themes, lessons from past mistakes, semantic similarity to historical decisions. Per ADR-016 + FR80/FR81, Hindsight is the right complement: a memory bank with two operations:

- **`retain(bank, kind, content, metadata)`**: write a narrative chunk. Always-on so the bank builds from day 1.
- **`recall(bank, query, limit, timeout_ms)`**: read top-N relevant narrative chunks for a symbol/topic. Off by default; tenant opts in once recommended (≥12 months of operation per the design rationale).

Without R6, FR80/FR81 + NFR-I8 are unstubbed, the per-tenant feature toggle has no UI surface, and brief synthesis cannot benefit from cross-time narrative recall when the operator wants it.

## What

Pure additive on R5 + new infra package:

### 1. `HindsightPort` Protocol + 3 adapters

`apps/api/src/iguanatrader/contexts/research/hindsight/`:

- `__init__.py` — declares 3 error classes (`HindsightUnavailable`, `HindsightTimeout`, `HindsightWriteFailed`).
- `port.py` — `HindsightPort` Protocol with two async methods.
- `http_adapter.py` — `HttpHindsightAdapter` (production; `httpx.AsyncClient` + JSON-RPC-ish POST to `IGUANATRADER_HINDSIGHT_URL`).
- `in_memory.py` — `InMemoryHindsightAdapter` (tests/dev; dict-backed; deterministic).

```python
class HindsightPort(Protocol):
    async def recall(
        self, *, bank: str, query: str, limit: int = 20, timeout_ms: int = 2000,
    ) -> list[str]: ...

    async def retain(
        self, *, bank: str, kind: str, content: str, metadata: dict[str, Any],
    ) -> None: ...
```

### 2. Bus-bridge: always-on retain (FR80)

`HindsightRetainHandler` (`hindsight/retain_handler.py`) — subscribes `ResearchBriefSynthesized` event; on each emission re-queries the brief + persists the thesis to the `iguanatrader-research-<tenant_id>` bank via `hindsight.retain(...)`. Same shape as K1+P1 followup bridges. **5th canonical instance of bus-bridge follow-up pattern.**

### 3. R5 surface modifications (additive only)

- `BriefService.__init__` accepts new optional `hindsight: HindsightPort | None = None`.
- `BriefService.refresh()` reads `tenants.feature_flags.hindsight_recall_enabled` for the current tenant; if truthy AND `hindsight is not None`, calls `await hindsight.recall(...)` with timeout + graceful fallback (logs `research.hindsight.recall_failed` and uses `[]`); passes the narrative context list into `Synthesizer.synthesize`.
- `Synthesizer.synthesize()` accepts new optional `narrative_context: list[str] | None = None`. If non-empty, prefixes the LLM prompt with a "Hindsight narrative" block. Existing tests pass it as `None` and behave identically.

Both signature changes are pure additive — no archive callers break.

### 4. Settings backend (toggle plumbing)

- `apps/api/src/iguanatrader/api/routes/settings.py` (NEW) — `GET /settings/feature-flags` returns the current `tenants.feature_flags` dict; `PUT /settings/feature-flags` whitelists known keys (`hindsight_recall_enabled` is the only v1 key) + persists.
- `apps/api/src/iguanatrader/cli/settings.py` (NEW) — `iguanatrader settings feature-flag get` / `iguanatrader settings feature-flag set hindsight_recall_enabled=true`.

### 5. Daemon wiring

`cli/trading.py` `_run_daemon` constructs `HttpHindsightAdapter` (from env), `HindsightRetainHandler(hindsight=..., repo=...)`, and registers the subscription on the bus. Pure additive after the existing approval+market-data wiring block.

### 6. Tests

- `tests/unit/contexts/research/hindsight/test_in_memory.py` — 3 tests on the fake.
- `tests/unit/contexts/research/hindsight/test_retain_handler.py` — bus-bridge wiring tests.
- `tests/integration/test_hindsight_recall_gated.py` — `BriefService.refresh` with feature flag ON + OFF.
- `tests/integration/test_hindsight_retain_always_on.py` — emit `ResearchBriefSynthesized` → assert `hindsight.retain()` invoked.
- `tests/unit/api/routes/test_settings_routes.py` — GET/PUT happy path + whitelist.
- `tests/unit/cli/test_settings_cli.py` — CLI smoke.

## Out of scope

- **Web Settings page** (Svelte `/settings/+page.svelte` toggle UI) — moved to slice `research-frontend-components` so the frontend skill stays in one slice.
- **Migration `0008_tenants_feature_flags.py`** — `tenants.feature_flags` column already exists from slice 3 (`persistence-tenant-enforcement`). No-op skipped.
- **Prompt-cache observability for Hindsight calls** — generic NFR-I3 instrumentation lives in observability slice; not slice-specific.
- **Auto-recommendation of when to flip the flag** — the design rationale (≥12 months operation) is documented; heuristic-driven prompt to operator is v2.

## Acceptance criteria

1. `HindsightPort` Protocol declared; 2 production-eligible adapters (Http + InMemory) implement it; mypy --strict clean.
2. `HindsightRetainHandler` registers a `ResearchBriefSynthesized` subscription; on emission, calls `hindsight.retain()` with the brief thesis. Failures logged + swallowed (FR80 graceful).
3. `BriefService.refresh` with feature flag ON + `hindsight is not None` → calls `recall()` and passes context to synthesizer; flag OFF or `hindsight is None` → no recall call (existing behavior).
4. `Synthesizer.synthesize` with `narrative_context=None` is bit-for-bit identical to current behavior; with non-empty list, prompt includes the narrative block.
5. `GET/PUT /settings/feature-flags` happy path + `hindsight_recall_enabled=true|false` toggle persists.
6. `iguanatrader settings feature-flag get/set` CLI works.
7. Integration tests for recall-gated + retain-always-on both pass.
8. mypy --strict + ruff + black + pre-commit + CI all green.

## Pattern usage

- **Bus-bridge follow-up #5** (after T4 keystone + K1-followup + P1-followup + T4-followup-market-data internal wiring): `ResearchBriefSynthesized` → handler → external write. Promote to ai-playbook v0.11.1 alongside the other 4 instances.
- **Skeleton-then-fill #4** (after R5 → T4 → T1+T4 → R5+R6): R5 declared `BriefService.__init__` with extension points; R6 fills the optional hindsight slot.
- **Protocol+InTreeFake+DeferredProductionInstall #2** (after T4-followup-market-data): both production + test adapters ship in this slice; no deferral.

## Blast radius

Three archive surfaces touched (all additive, all backwards-compatible):

- `BriefService.__init__`: new optional kwarg `hindsight` (default `None`).
- `BriefService.refresh`: branched call path gated by feature flag + non-None hindsight.
- `Synthesizer.synthesize`: new optional kwarg `narrative_context` (default `None`).

Existing R5 tests inject `hindsight=None` (default) and behave identically.

## Estimated effort

~8-10h, ~700 LoC (~350 src + ~330 tests + ~40 retro/openspec).
