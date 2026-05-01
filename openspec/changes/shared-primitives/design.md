## Context

Slice 1 (`bootstrap-monorepo`) landed the monorepo skeleton + tooling baseline (PR #22, merged 2026-04-30) but `apps/api/src/iguanatrader/` is empty. Slice 2 (`shared-primitives`) is the FIRST slice to put Python code under `apps/api/src/iguanatrader/`. The architecture decisions doc ([docs/architecture-decisions.md](../../../docs/architecture-decisions.md)) commits to:

- **DDD bounded contexts** with a shared kernel for cross-cutting primitives.
- **MessageBus pattern** (Nautilus-inspired, single-loop asyncio) for intra-process event routing — avoids the explicit-callback-graph spaghetti of v0 and decouples engines.
- **Port/Adapter (hexagonal)** pattern: each context defines `Port` interfaces; adapters live at the edge.
- **Multi-tenant from day 1** via `tenant_id` ContextVar injected into SQLAlchemy session listeners (NFR-SC1).
- **Append-only event sourcing** for audit-critical tables (NFR-SC2) — implementation lands slice 3, but the kernel-level error types this layer raises must exist now.
- **Decimal-only money math** (no float) — non-negotiable per AGENTS.md §4 hard rule.
- **Resilience pattern** for live adapters: HeartbeatMixin + canonical backoff `[3, 6, 12, 24, 48]` (NFR-P8/R7/I2/I5).

Every downstream slice (3-20) imports from `shared/`. Get this wrong and we re-litigate it 20 times.

## Goals / Non-Goals

**Goals:**

- Pure-stdlib kernel (no runtime deps beyond what's already pinned for the project).
- 100% type coverage under `mypy --strict`.
- Property-based invariant tests for the four primitives where ad-hoc unit tests under-test the contract: MessageBus FIFO ordering, Decimal arithmetic precision, HeartbeatMixin idempotency, backoff monotonicity.
- Zero domain knowledge — `shared/` MUST NOT import from `contexts/`, `api/`, `cli/`, `persistence/`, or any future bounded-context module.
- Stable public API: anything exported here will be consumed by 18 downstream slices. Breaking changes after this slice ships require a new openspec change.

**Non-Goals:**

- Concrete persistence (SQLAlchemy session factory, Alembic migrations, listeners) — slice 3.
- HTTP layer (FastAPI app factory, RFC 7807 exception handler wiring) — slice 5.
- Concrete Port subclasses (`BrokerPort`, `StrategyPort`, `SourcePort`) — slices T1/R1.
- Cross-process distributed messaging (Redis, NATS, Kafka). The MessageBus is in-process only; that's the architecture decision per ADR.
- Observability (structlog config, OTEL) — slice O1. We declare the structlog event-name convention here but the config lives in O1.

## Decisions

### D1. MessageBus: in-process asyncio + FIFO-per-subscriber + opt-in idempotency

**Decision**: `MessageBus.publish(event)` enqueues to `asyncio.Queue` per subscriber; subscribers consume in declared order; opt-in `idempotency_key` on events allows duplicate suppression within a configurable window.

**Why**:
- Single-loop asyncio (per architecture decision) means no thread-safety concerns; `asyncio.Queue` gives FIFO for free.
- Per-subscriber queue (not single global queue) lets slow subscribers fall behind without blocking fast ones — but each subscriber sees a stable order.
- Idempotency is opt-in because most events (price updates, equity snapshots) are naturally idempotent or not worth deduplicating; the cost is tracking a key set per subscriber, only paid when needed.

**Alternatives considered**:
- *Synchronous fan-out (call subscribers in publish())*: rejected — back-pressure becomes the publisher's problem and a slow subscriber stalls trading.
- *Single global queue with subscriber routing*: rejected — head-of-line blocking; one slow subscriber starves all others.
- *Redis pub/sub from day 1*: rejected — architecture commits to single-process for MVP; adding Redis adds operational surface without value.

### D2. BaseRepository: session via ContextVar, never via DI parameter

**Decision**: `BaseRepository` reads its `AsyncSession` from a `session_var: ContextVar[AsyncSession]`; constructor takes no session. `tenant_id_var: ContextVar[UUID | None]` is a separate ContextVar set by the auth dependency (slice 4) and read by the SQLAlchemy listener (slice 3) to inject `WHERE tenant_id = :ctx_tenant`.

**Why**:
- ContextVar propagates across `await` points natively in asyncio — no thread-local hacks, no manual passing through every call.
- Slice 3 will register an event listener on `Session.do_orm_execute` that reads `tenant_id_var` and rewrites the query. If session is also a ContextVar, the listener can resolve both without DI gymnastics.
- Tests can override the ContextVar directly (`token = session_var.set(test_session); try: ...; finally: session_var.reset(token)`) — clean teardown.

**Alternatives considered**:
- *Pass session as constructor arg*: rejected — every service method ends up threading `session` through, and the SQLAlchemy listener can't resolve it lazily.
- *Global module-level session*: rejected — kills test isolation; can't run two tenants in parallel.

### D3. Money type: `Decimal` subclass with explicit currency + precision per ISO 4217

**Decision**: `Money(amount: Decimal, currency: str)` value object — frozen dataclass; arithmetic ops between same-currency only (raises `CurrencyMismatchError` otherwise); `quantize` uses `ROUND_HALF_EVEN` (banker's rounding) at currency-specific precision (USD=2, JPY=0, BTC=8).

**Why**:
- Float for money is a bug factory — IEEE 754 can't represent `0.1 + 0.2` exactly.
- Currency-tagged Money prevents the "added USD to EUR" silent bug.
- Banker's rounding minimizes statistical bias vs `ROUND_HALF_UP`.

**Alternatives considered**:
- *Plain `Decimal` + convention "always USD"*: rejected — IBKR multi-currency accounts are a real thing; ESG/research mostly USD but not enforceable in types.
- *Third-party `py-moneyed` library*: rejected — adds a runtime dep for ~80 lines of code we'd otherwise own; lock-in risk.

### D4. IguanaError hierarchy maps 1:1 to RFC 7807 Problem Details

**Decision**: Single root `IguanaError(Exception)` with `type: str` (URI), `title: str`, `status: int`, `detail: str | None`, `instance: str | None` attributes. Subclasses: `ValidationError` (400), `AuthError` (401), `ForbiddenError` (403), `NotFoundError` (404), `ConflictError` (409), `RateLimitError` (429), `IntegrationError` (502 — IBKR, Telegram, etc. failed), `InternalError` (500). Slice 5 wires the FastAPI exception handler that serializes to RFC 7807.

**Why**:
- One exception → one HTTP problem document, no manual mapping in handlers.
- `type` URI is the stable contract for clients; subclass names can refactor without breaking API consumers.

**Alternatives considered**:
- *Per-context error hierarchies (TradingError, ResearchError)*: rejected — leads to duplicate error subtypes (NotFoundError in every context); shared kernel is the right home for cross-cutting types.

### D5. Time helpers: UTC-only, ISO 8601 strict

**Decision**: `now()` returns `datetime` with `tzinfo=UTC` (no naive datetimes anywhere); `parse_iso8601(s)` raises `ValidationError` on naive input or non-ISO strings; `format_iso8601(dt)` always emits `YYYY-MM-DDTHH:MM:SS.ffffffZ` (microsecond precision, `Z` suffix not `+00:00` — agreed format from feedback memory).

**Why**:
- AGENTS.md §4 hard rule + memory feedback: ISO 8601 single format everywhere.
- Mixing naive + aware datetimes is the #1 source of timezone bugs in Python services.

**Alternatives considered**:
- *Allow naive datetimes "when context implies UTC"*: rejected — too easy to leak through tests where context is tacit.

### D6. HeartbeatMixin: state machine with idempotent transitions

**Decision**: Mixin defines abstract `async def _send_heartbeat() -> None` and `async def _on_disconnect() -> None`; concrete state `{CONNECTED, RECONNECTING, DISCONNECTED}`; transitions are idempotent (calling `mark_connected()` twice is a no-op); reconnection uses the canonical backoff sequence `[3, 6, 12, 24, 48]` from `backoff.py`.

**Why**:
- IBKRAdapter, TelegramChannel, HermesChannel will all need the same logic — implementing it three times means three subtly different bugs.
- Idempotent transitions allow heartbeat libraries with at-least-once delivery semantics.

**Alternatives considered**:
- *Per-adapter heartbeat logic*: rejected — codifies the divergence we're trying to prevent.

### D7. Backoff: pure function returning iterator + jitter optional

**Decision**: `backoff_seconds(attempt: int) -> int` returns the canonical sequence indexed by attempt, capped at the last value (attempt ≥5 returns 48). `with_jitter=True` adds ±20% uniform jitter for thundering-herd avoidance.

**Why**:
- Pure function = trivially testable + property-test the monotonicity invariant.
- Sequence is per ADR (NFR-R7); not a tunable surface.

**Alternatives considered**:
- *Configurable sequence per adapter*: rejected — premature flexibility; IBKR + Telegram + Hermes all use the same sequence per the resilience ADR.

### D8. Port abstract base = `Protocol` (PEP 544 structural typing)

**Decision**: `Port` and concrete subtypes (added in T1/R1) are `typing.Protocol` classes — duck-typed structural interfaces — not ABCs. Adapters don't need to inherit; `mypy --strict` enforces conformance.

**Why**:
- Protocols don't force inheritance, which keeps adapters honest about their dependencies (the adapter's job is to satisfy the contract, not advertise it).
- `mypy --strict` catches missing methods at type-check time anyway.

**Alternatives considered**:
- *abc.ABC*: rejected — runtime overhead + forces inheritance; structural typing is the modern Python idiom for interfaces.

## Risks / Trade-offs

- **Risk**: kernel API churn after slice 2 ships breaks 18 downstream slices. → **Mitigation**: every public symbol gets a property test or scenario in `specs/shared-kernel/spec.md`; changing it requires a new openspec change. Treat `shared/` as semver-locked from this slice forward.
- **Risk**: MessageBus FIFO-per-subscriber works in-process but masks distributed-systems gotchas (we'll feel them when we add Redis/NATS in v2). → **Mitigation**: explicit Non-Goal in this design; `messagebus.py` docstring warns. Distributed messaging will be a new openspec change with its own ADR.
- **Risk**: `tenant_id_var` set in middleware but accessed in a background task that doesn't inherit the context. → **Mitigation**: `kernel.py` exposes `with_tenant_context(tenant_id)` async context manager + `propagate_tenant_to(coro)` helper for `asyncio.create_task` callers; docstring + slice 3 integration test enforce.
- **Risk**: HeartbeatMixin + backoff logic gets reimplemented per-adapter anyway because "this case is special". → **Mitigation**: explicit slice review: if an adapter wants to bypass the mixin, it requires an ADR. The property test pinning idempotency is the contract.
- **Trade-off**: Protocol-based ports give no runtime checking. If an adapter ships a typo'd method name and tests don't exercise it, prod will hit `AttributeError`. → Accepted: `mypy --strict` runs in CI, and integration tests per adapter (T2, etc.) exercise the full Port surface.

## Migration Plan

N/A — this is the first source code under `apps/api/src/iguanatrader/`. No existing behavior to migrate from.

**Rollback**: revert the squash-merge commit; slice 3+ haven't started; no consumer code depends on `shared/` until slice 3 (`persistence-tenant-enforcement`) lands.

## Open Questions

None blocking. Items deferred to future slices and explicitly out-of-scope:

- Concrete `BrokerPort` / `StrategyPort` / `SourcePort` shapes — slices T1/R1 land them as Protocol extensions of the abstract `Port`.
- structlog config (handlers, processors) — slice O1.
- Whether to expose a sync façade for the MessageBus for places where async-everywhere is awkward — slice T4 (the trading daemon) can revisit if it bites.
