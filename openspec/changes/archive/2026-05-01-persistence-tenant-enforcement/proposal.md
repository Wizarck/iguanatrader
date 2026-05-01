## Why

iguanatrader's MVP requires a persistence foundation that enforces tenant isolation **from the very first migration** — not bolted on later. Wave 0 slice 3 plants the SQLAlchemy 2.x async session, the Alembic env, the global event listeners that make `tenant_id` filtering and append-only invariants impossible to bypass, plus the only three mutable tables in the entire app (`tenants`, `users`, `authorized_senders`). Every downstream slice that creates a `migrations/000N_*.py` file or a `BaseRepository` consumer reads from this layer; deferring the listeners or letting individual contexts re-implement tenant injection would re-create the multi-tenancy escape hatch we are explicitly designing out per NFR-SC1/SC2.

## What Changes

- **Persistence module** (`apps/api/src/iguanatrader/persistence/`):
  - `base.py` — declarative `Base = DeclarativeBase` with naming convention (`pk`, `fk`, `uq`, `ix`, `ck`) so Alembic autogenerate produces stable, named-constraint diffs across machines and migrations.
  - `session.py` — async engine + `async_sessionmaker` factory; SQLite (WAL + JSON1 verify on boot) for MVP, Postgres-ready engine adapter (NUMERIC(18,8), JSONB native) for v1.5.
  - `tenant_listener.py` — global SQLAlchemy `before_compile` (Select) and `before_flush` (Insert) listener that reads `tenant_id_var` from `shared/contextvars.py` and (a) injects `WHERE tenant_id = :current_tenant` into every Select against tagged tables, (b) sets `tenant_id` on every Insert. Tables marked `__tenant_scoped__ = False` (e.g. `research_sources` shared catalogue) opt out explicitly.
  - `append_only_listener.py` — global `before_flush` listener that raises `AppendOnlyViolationError` (subclass of `IguanaError` → IntegrityError at the DB layer) on UPDATE/DELETE against tables marked `__tablename_is_append_only__ = True`.
- **Alembic infrastructure** (`apps/api/src/iguanatrader/migrations/`):
  - `env.py` — async-aware Alembic env with `target_metadata = Base.metadata`, `compare_type=True`, `render_as_batch=True` for SQLite ALTER compatibility, and project naming-convention propagation.
  - `script.py.mako` — template enforcing UTC timestamps + ISO 8601 in revision headers.
  - `versions/0001_initial_schema.py` — first migration: `tenants` (with `feature_flags JSONB` column populated from FR81 allowlist defaults), `users` (with Argon2id `password_hash`, `role CHECK IN ('admin','user')`), `authorized_senders` (with `channel CHECK IN ('telegram','whatsapp')` + uniqueness on `(tenant_id, channel, external_id)`).
- **Boot-time JSON1 verify** — exported helper `verify_json1_extension()` callable from FastAPI lifespan in slice 5; raises `JSON1NotAvailableError` with explicit remediation message ("recompile Python with `--enable-loadable-sqlite-extensions` or use Python 3.11+ official build") if `SELECT json('{}')` fails on a fresh connection.
- **Integration tests** (`apps/api/tests/integration/persistence/`):
  - `test_tenant_isolation.py` — open two sessions with different `tenant_id_var` values; cross-tenant `Select` returns empty; Insert without `tenant_id_var` set raises `TenantContextMissingError`.
  - `test_append_only_invariant.py` — Insert into append-only table OK; UPDATE / DELETE raises `AppendOnlyViolationError` (verified at flush time and at SQLite IntegrityError layer).
  - `test_json1_boot_check.py` — happy path on Python 3.11+; mock-failure path validates remediation message text.
  - `test_alembic_roundtrip.py` — `alembic upgrade head` then `alembic downgrade base` on temp SQLite reaches identical empty schema (validates `down_revision` correctness).
- **Property tests** (`apps/api/tests/property/persistence/`):
  - `test_tenant_filter_invariant.py` — Hypothesis: for any sequence of Inserts under arbitrary `tenant_id_var` values, a Select under tenant X returns ONLY rows where `tenant_id == X`.

## Capabilities

### New Capabilities

- `persistence-layer`: SQLAlchemy 2.x async session + Alembic env + global event listeners enforcing tenant isolation (NFR-SC1) and append-only invariants (NFR-SC2) for all bounded contexts that follow. Includes the first migration (tenants/users/authorized_senders), naming convention, and JSON1 boot verify.

### Modified Capabilities

(none — slice 3 introduces a new capability; the `shared-kernel` capability from slice 2 is consumed unmodified via `shared/contextvars.py` and `shared/errors.py`.)

## Impact

**Affected code (write paths owned by this slice):**

- `apps/api/src/iguanatrader/persistence/{base,session,tenant_listener,append_only_listener,__init__}.py`
- `apps/api/src/iguanatrader/migrations/{env,script.py.mako,versions/0001_initial_schema}.py`
- `apps/api/tests/integration/persistence/{test_tenant_isolation,test_append_only_invariant,test_json1_boot_check,test_alembic_roundtrip}.py`
- `apps/api/tests/property/persistence/test_tenant_filter_invariant.py`
- `pyproject.toml` — add `sqlalchemy[asyncio]>=2.0`, `alembic>=1.13`, `aiosqlite>=0.19` to runtime deps; `asyncpg>=0.29` to optional `[postgres]` extra (v1.5 readiness; not installed by default).
- `apps/api/Makefile.includes` — `db-upgrade`, `db-downgrade`, `db-revision` targets calling `alembic` with the project env.

**Capability coverage (FRs/NFRs realised by this slice):**

- FR46 — append-only persistence for trades/orders/fills/positions/equity (the listener planted here is what subsequent migrations consume by tagging their tables `__tablename_is_append_only__ = True`).
- FR47 — config_changes append-only (same mechanism, consumed by slice O1).
- FR48 — approval_decisions append-only (same mechanism, consumed by slice P1).
- FR49 — `tenant_id` tagging on every persisted record (the `tenant_listener` is what enforces this globally; subsequent migrations only need to declare `tenant_id` columns + FKs).
- NFR-SC1 — multi-tenant ready from day 1 (cross-tenant read returns empty; cross-tenant insert impossible without `tenant_id_var` set).
- NFR-SC2 — SQLite ↔ Postgres parity preserved (engine adapter renders correct types; same listener wires for both backends).

**Prerequisites (per `docs/openspec-slice.md` §3 "Depends on"):**

- `shared-primitives` (slice 2, merged 2026-05-01 PR #41) — consumed: `shared.contextvars.tenant_id_var` + `shared.contextvars.session_var`, `shared.errors.IguanaError` + `shared.errors.IntegrationError`, `shared.time.now()`, `shared.kernel.BaseRepository`.

**Out of scope (deferred to later slices):**

- HTTP layer / FastAPI app factory / lifespan wiring — slice 5 (`api-foundation-rfc7807`) calls `verify_json1_extension()` from lifespan and exposes `RFC 7807` translation of `IguanaError` subclasses raised here.
- Auth flow (login / cookie / `get_current_user`) — slice 4 (`auth-jwt-cookie`) consumes the `users` + `authorized_senders` tables and is responsible for setting `tenant_id_var` from the JWT.
- All bounded-context tables (research_facts, trade_proposals, risk_evaluations, approval_requests, api_cost_events, etc.) — each context owns its own `migrations/000N_*.py` and tags its own tables `__tenant_scoped__` / `__tablename_is_append_only__`.
- Postgres production wiring + litestream backup orchestration — slice 1 (`bootstrap-monorepo`) planted the docker-compose service; slice 3 declares the dep but does not configure runtime.
- Hindsight feature flag toggle — slice R6 consumes `tenants.feature_flags['hindsight_recall_enabled']`; slice 3 only ships the column with default `'{}'`.

**Anti-collision contract:**

- `apps/api/src/iguanatrader/persistence/*` — exclusively owned by this slice; never edited by another slice except to add new persistence-layer primitives.
- `apps/api/src/iguanatrader/migrations/env.py` — owned by this slice; subsequent slices add `versions/000N_*.py` files only.
- `apps/api/src/iguanatrader/migrations/versions/0001_initial_schema.py` — owned by this slice; subsequent slices increment N and set `down_revision = '<previous N>'`.
- No edits to `apps/api/src/iguanatrader/shared/*` (owned by slice 2).
- No edits to `apps/api/src/iguanatrader/api/*` or `apps/api/src/iguanatrader/cli/*` (slices 5 and T4 own those).
