## Why

Slice 2/20 of iguanatrader Wave 0 sequential foundation per [docs/openspec-slice.md §2](../../../docs/openspec-slice.md). Slice 1 (`bootstrap-monorepo`) merged 2026-04-30 (PR #22) leaving the monorepo skeleton + tooling baseline; nothing under `apps/api/src/iguanatrader/` yet. Every downstream bounded context (`research`, `trading`, `risk`, `approval`, `observability`, `orchestration`) needs a small, dependency-free **shared kernel** to build on: a deterministic in-process MessageBus, a session-injecting BaseRepository, money-safe Decimal types, a tenant_id ContextVar, an error hierarchy, UTC time helpers, a HeartbeatMixin for live adapters, and a canonical exponential-backoff helper. Without these primitives, each context would re-implement them divergently and break NFR-O2 (event ordering), NFR-SC1 (tenant isolation), NFR-P8/R7/I2/I5 (resilience), and the no-float money rule.

This slice plants ONLY the kernel. It is consumed by slices 3-20 and never edited again except to add new kernel-level primitives.

## What Changes

- Add `apps/api/src/iguanatrader/shared/` package with 10 modules: `messagebus.py`, `kernel.py`, `types.py`, `contextvars.py`, `errors.py`, `time.py`, `decimal_utils.py`, `heartbeat.py`, `backoff.py`, `ports.py`.
- Add `apps/api/tests/property/` with 4 Hypothesis-based property tests (message ordering FIFO per subscriber, decimal arithmetic precision, heartbeat idempotency, backoff monotonicity).
- Add `apps/api/tests/unit/shared/` with per-module unit tests (errors hierarchy, types/value-objects, time UTC enforcement, contextvars tenant scoping).
- Wire `mypy --strict` clean across `apps/api/src/iguanatrader/shared/*` (slice 1 already configured the strict baseline).
- Add Hypothesis to dev dependencies in `pyproject.toml` if not already present from slice 1.

No public API surface yet (no routes, no SSE, no CLI — those land in slice 5 `api-foundation-rfc7807`). No persistence (slice 3 `persistence-tenant-enforcement` lands Alembic + SQLAlchemy listeners). No domain references (this is pure kernel).

## Capabilities

### New Capabilities

- `shared-kernel`: Pure, dependency-free primitives consumed by every bounded context — MessageBus with FIFO-per-subscriber + opt-in idempotency (NFR-O2), BaseRepository with `contextvars`-injected tenant scope (NFR-SC1), `Money` Decimal value object (no float for money), `tenant_id` ContextVar holder, `IguanaError` hierarchy + RFC 7807 Problem Details base, UTC-only datetime helpers with ISO 8601 enforcement, `HeartbeatMixin` for live adapters (NFR-P8/R7/I2/I5), canonical exponential backoff `[3, 6, 12, 24, 48]` seconds (NFR-R7), and abstract `Port` base for the Port/Adapter pattern.

### Modified Capabilities

None. This is the first capability spec for iguanatrader.

## Impact

- **Affected code**: net-new `apps/api/src/iguanatrader/shared/*` (10 modules) + net-new `apps/api/tests/property/*` (4 tests) + net-new `apps/api/tests/unit/shared/*` (per-module unit tests).
- **Affected APIs**: none yet (consumers land in slices 3+).
- **Dependencies**: ensure `hypothesis` is in `[tool.poetry.group.dev.dependencies]`. No new runtime deps; everything in the shared kernel uses stdlib (`decimal`, `contextvars`, `dataclasses`, `enum`, `datetime`, `asyncio`).
- **Systems**: no infra impact. Pure-library slice.
- **Prerequisites** (from [docs/openspec-slice.md §2 dependency column](../../../docs/openspec-slice.md)):
  - `bootstrap-monorepo` (slice 1) ✅ merged 2026-04-30 PR #22.
- **Capability coverage** (from slice plan FRs column): foundation NFRs only — NFR-O2 (event ordering), NFR-P8 (heartbeat for live adapters), NFR-R7 (backoff), NFR-I2/I5 (resilience patterns), NFR-SC1 (tenant isolation primitive).
