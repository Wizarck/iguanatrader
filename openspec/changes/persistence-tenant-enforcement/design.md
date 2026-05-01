## Context

Wave 0 slice 3 plants the persistence layer — the **only** place in iguanatrader where SQL is emitted, where Alembic migrations live, and where multi-tenancy isolation is enforced. Slice 2 (`shared-primitives`, merged 2026-05-01 PR #41) shipped `tenant_id_var: ContextVar[UUID | None]`, `session_var: ContextVar[Any | None]`, the `IguanaError` hierarchy, and `BaseRepository` (which reads `session_var`). Slice 3 must (a) wire SQLAlchemy 2.x async + Alembic on top of those primitives, (b) enforce tenant isolation and append-only invariants **globally** so individual contexts cannot bypass them, and (c) ship the first migration containing only the three cross-cutting mutable tables (`tenants`, `users`, `authorized_senders`) — every bounded-context table belongs to its own slice's migration.

Constraints:

- **NFR-SC1** (`docs/prd.md` line 1036): "Schema multi-tenant ready desde día 1; `tenant_id` en cada tabla del SQLite/Postgres, todas las queries filtradas." → tenant filtering MUST be impossible to forget; centralised in a global event listener, not boilerplate per query.
- **NFR-SC2** (`docs/prd.md` line 1037): "Migración SQLite → Postgres con mismo schema sin pérdida de data." → naming convention + portable types (UUID/CHAR(36), JSONB/TEXT, NUMERIC(18,8), TIMESTAMPTZ).
- **AGENTS.md hard rules** (universal norms inherited via `.ai-playbook/specs/*` + project-specific):
  - No float for money — already enforced by slice 2's `Money` type; persistence emits `NUMERIC(18,8)` not `REAL`.
  - All datetimes ISO 8601 UTC strict — Alembic `script.py.mako` template enforces UTC ISO 8601 in revision headers.
  - structlog event names `<context>.<entity>.<action>` with `context = "persistence"`.
- **Anti-collision contract** (`docs/openspec-slice.md` §3): this slice owns `apps/api/src/iguanatrader/persistence/*` + `apps/api/src/iguanatrader/migrations/env.py` + `migrations/versions/0001_initial_schema.py`. No other slice will edit these files; subsequent migrations only add `versions/000N_*.py`.
- **Profile A active** (release-management.md §4.5): PR description MUST carry the AI-reviewer signoff; CodeRabbit + L1 (in-session) + L2 (workflow shipped in PR #52).

Stakeholder: Arturo (single-tenant MVP today). v2 SaaS — many tenants — emerges after the MVP hits paper-trading parity; the listeners planted now MUST work correctly when the second tenant arrives without requiring a re-architecture.

## Goals / Non-Goals

**Goals:**

- Tenant isolation enforced **globally** at the SQLAlchemy compilation/flush layer; impossible to forget, impossible to bypass via ORM code (raw SQL bypass is documented as a separate failure mode caught at the database trigger layer for append-only tables only — tenant filter on raw SQL is the caller's responsibility).
- Append-only invariant for tables marked `__tablename_is_append_only__ = True` enforced at flush time + reinforced at the SQLite/Postgres trigger layer.
- Alembic env that runs `alembic upgrade head` cleanly on a fresh SQLite database AND a fresh Postgres database with no schema-level differences (modulo type renderings).
- First migration creates exactly three tables (`tenants`, `users`, `authorized_senders`) with named constraints conforming to the project naming convention; reversible via `alembic downgrade base`.
- JSON1 SQLite extension verified at boot with an explicit, actionable remediation message when missing.
- Property-test coverage of the tenant filter invariant (Hypothesis); ≥80% line coverage of `apps/api/src/iguanatrader/persistence/*` per NFR-M1.

**Non-Goals:**

- HTTP layer / FastAPI app factory / lifespan wiring — slice 5 (`api-foundation-rfc7807`) calls `verify_json1_extension()` + `RFC 7807` translation of `IguanaError`.
- Auth flow / `get_current_user` / JWT cookie issuance — slice 4 (`auth-jwt-cookie`) uses `users` and `authorized_senders` tables and is responsible for setting `tenant_id_var` from the JWT subject claim.
- Bounded-context tables (`research_facts`, `trade_proposals`, `risk_evaluations`, `approval_requests`, `api_cost_events`, etc.) and their migrations.
- Postgres production wiring + litestream backup orchestration; slice 1 already declared the docker-compose service.
- Hindsight feature-flag toggle UI/API — slice R6 reads `tenants.feature_flags['hindsight_recall_enabled']`; slice 3 only ships the column with default `'{}'`.
- Cross-tenant raw-SQL read safety; the contract is "use the ORM; raw SQL is opt-in privilege". Documented in `gotchas.md`.

## Decisions

### D1 — Tenant filter via SQLAlchemy `before_compile` event on `Select`

**Decision:** Register a global event listener on `Select.__visit_name__ == "select"` (more precisely, `event.listen(Select, "before_compile", _inject_tenant_filter, retval=True)`) that walks the FROM clause, finds every ORM-mapped table that does NOT carry `__tenant_scoped__ = False`, and adds `where(table.c.tenant_id == bindparam("current_tenant", _read_tenant_var()))`.

**Alternatives considered:**

- (A) Force every repository to call `.filter(Model.tenant_id == ...)` explicitly. Rejected: violates NFR-SC1's "impossible to forget" intent; one missed call leaks data across tenants forever.
- (B) Postgres Row-Level Security (RLS) policies. Rejected for MVP: SQLite has no RLS; would only kick in at v1.5 Postgres migration, leaving the MVP unprotected for ~6 months. RLS is a candidate for v1.5 as defence-in-depth on top of the listener, not as a replacement.
- (C) Custom session class with `session.query()` override. Rejected: doesn't catch `session.execute(select(...))` which is the SQLAlchemy 2.x idiomatic path. The `before_compile` hook catches both.

**Rationale:** centralised, hard to bypass, works on both SQLite and Postgres, costs one event-handler call per query (negligible). The listener's read of `tenant_id_var` is async-safe because `ContextVar` propagates correctly across `asyncio.create_task` boundaries (asyncio.Task captures the context at creation time).

### D2 — Insert-time tenant stamping via `before_flush`

**Decision:** Register `event.listen(AsyncSession.sync_session_class, "before_flush", _stamp_tenant_on_inserts)`. The handler iterates `session.new`, and for each instance whose mapped class has `tenant_id` and is NOT `__tenant_scoped__ = False`:

- If `instance.tenant_id is None`: set it to `tenant_id_var.get()`. Raise `TenantContextMissingError` if the var is unset.
- If `instance.tenant_id is not None and instance.tenant_id != tenant_id_var.get()`: raise `TenantContextMismatchError` (RFC 7807 status 403). This catches accidental cross-tenant writes from buggy code paths that pass an attacker-controlled `tenant_id`.

**Alternatives considered:** column `default=lambda: tenant_id_var.get()`. Rejected: column defaults run at INSERT bind time; we cannot raise a typed `IguanaError` from a column default (would surface as opaque `TypeError`/`OperationalError`).

### D3 — Append-only enforcement with two layers (ORM + trigger)

**Decision:** Two layers of defence:

- **L1 (ORM, this slice):** `before_flush` listener iterates `session.dirty` and `session.deleted`, raises `AppendOnlyViolationError` for any instance whose class declares `__tablename_is_append_only__ = True`. Catches all ORM-driven mutations.
- **L2 (DB, this slice):** Each migration that creates an append-only table SHALL also create a `BEFORE UPDATE` and `BEFORE DELETE` trigger that issues `RAISE(FAIL, '<table> is append-only')` on SQLite, or `BEFORE UPDATE OR DELETE` trigger raising `EXCEPTION` on Postgres v1.5. The first migration (0001) does NOT create such triggers because none of its tables (tenants, users, authorized_senders) are append-only — those are mutable. Subsequent slices that introduce append-only tables (e.g. `audit_log`, `kill_switch_events`, `approval_decisions`) own their trigger SQL.

**Why both:** L1 catches typed `IguanaError` early with good ergonomics. L2 catches the residual case of `session.execute(text("UPDATE ..."))` raw SQL that bypasses the ORM. Skipping L2 leaves a known escape hatch for any code path that drops to raw SQL.

**Alternative considered:** SQLAlchemy `mapper.mutating` opt-in interceptor. Rejected: same blind spot as L1 alone — raw SQL still bypasses.

### D4 — Naming convention for autogenerate stability

**Decision:** Apply this naming convention on `MetaData`:

```python
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING_CONVENTION)
Base = DeclarativeBase(metadata=metadata)
```

**Why:** without explicit naming, autogenerate produces SHA-suffixed constraint names that differ across machines and Postgres/SQLite; diffs become noisy and migrations become un-reviewable. With this convention, `alembic revision --autogenerate` produces deterministic, reviewable diffs across machines and engines.

### D5 — Async stack: SQLAlchemy 2.x `AsyncSession` + `async_sessionmaker` + `aiosqlite`

**Decision:** Production stack is `create_async_engine("sqlite+aiosqlite:///./data/iguanatrader.db", echo=False, connect_args={"timeout": 30})` for MVP and `create_async_engine("postgresql+asyncpg://...")` for v1.5. Sessions via `async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)`. The `expire_on_commit=False` choice is deliberate: in async code, accessing an attribute after commit triggers an implicit refresh which is async — easy to forget the `await`. With `expire_on_commit=False` the commit returns and instances stay usable; the trade-off (stale data after commit if another writer touched the row) is irrelevant in MVP single-writer.

**SQLite-specific PRAGMA on connect:** `PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 30000;` — set via `event.listen(engine.sync_engine, "connect", _sqlite_pragmas)`. Foreign-key enforcement is OFF by default in SQLite; without `PRAGMA foreign_keys = ON` the FK constraints in the schema are decorative.

### D6 — Alembic env: async-aware + naming-convention propagation + `render_as_batch`

**Decision:** `migrations/env.py` follows the official SQLAlchemy 2.x async Alembic recipe with these specifics:

- `target_metadata = Base.metadata` (so naming convention is respected by autogenerate).
- `compare_type = True` (catches type changes that Alembic 1.x defaults to ignoring).
- `render_as_batch = True` for SQLite (works around SQLite's lack of `ALTER TABLE DROP COLUMN` pre-3.35 by emitting copy-and-rename).
- `transaction_per_migration = True` (each migration in its own transaction; partial failures don't leave a half-applied state).

### D7 — JSON1 verify at boot — explicit error with remediation

**Decision:** Export `async def verify_json1_extension(engine: AsyncEngine) -> None` from `persistence/__init__.py`. Implementation: `async with engine.connect() as conn: await conn.execute(text("SELECT json('{}')"))`. On `OperationalError`, raise `JSON1NotAvailableError` whose `__str__` includes:

- `sys.version_info` (the running Python version).
- `sqlite3.sqlite_version` (the bundled SQLite version Python sees).
- The two remediation paths from the spec.

**Why explicit:** A silent JSON1 failure surfaces as `OperationalError: no such function: json` at runtime, hours into operation, often with no clear pointer to "this is a build-time issue with your Python/SQLite combination". Failing fast at boot with a remediation string saves the operator a debugging session.

### D8 — `tenants.feature_flags` schema on SQLite — `JSON1 + TEXT`, on Postgres — `JSONB`

**Decision:** SQLAlchemy column declared as `Column("feature_flags", JSON, nullable=False, server_default=text("'{}'"))`. The dialect adapter renders `TEXT` on SQLite (queryable via JSON1 functions) and `JSONB` on Postgres (queryable via native operators). Application-level validation of allowed keys (the FR81 allowlist) lives in `contexts/research/feature_flags.py` (slice R6) — slice 3 only enforces the column shape + default.

**Alternative:** declare `JSONB` directly. Rejected: SQLite `JSONB` doesn't exist; SQLAlchemy would fall back to `TEXT` with a deprecation warning anyway. Using `JSON` makes the cross-dialect intent explicit.

### D9 — Errors hierarchy added in this slice

The following new error classes extend `shared.errors.IguanaError`:

- `TenantContextMissingError(ValidationError)` — RFC 7807 status 500. Raised when listener finds `tenant_id_var` unset on a tenant-scoped query/insert.
- `TenantContextMismatchError(ForbiddenError)` — RFC 7807 status 403. Raised on insert-time mismatch.
- `AppendOnlyViolationError(ConflictError)` — RFC 7807 status 409. Raised on UPDATE/DELETE against append-only.
- `JSON1NotAvailableError(InternalError)` — RFC 7807 status 500. Raised at boot.

These live in `apps/api/src/iguanatrader/persistence/errors.py` and re-export from `persistence/__init__.py`. They do NOT live in `shared/errors.py` because they are persistence-specific; `shared/` knows nothing about persistence per the slice 2 contract.

## Risks / Trade-offs

- **[Risk]** `before_compile` listener might miss queries built via `lambda_stmt` or other SQLAlchemy constructs that don't go through the standard `Select` compilation path. → **Mitigation:** the property test (`test_tenant_filter_invariant`) generates Inserts and Selects through the standard ORM path, which is the only path repositories will use; the contract is "use ORM Select; raw SQL is opt-in privilege documented in gotchas". Add a `lambda_stmt` integration test variant if/when a future slice introduces lambda usage.
- **[Risk]** `expire_on_commit=False` can mask stale-data bugs in v2 multi-writer scenarios. → **Mitigation:** documented in `gotchas.md`; revisit when the second tenant + concurrent writer arrives. MVP is single-writer per process, so the risk is theoretical today.
- **[Risk]** SQLite + WAL mode + multiple readers + one writer can deadlock under heavy load with the default `busy_timeout`. → **Mitigation:** `PRAGMA busy_timeout = 30000` (30s) per D5; if 30s is exceeded the operator sees the error and we know to migrate to Postgres. Monitored by NFR-O3 logs.
- **[Risk]** `transaction_per_migration = True` + a migration that creates AND populates a table can leave the table half-populated if a second migration depends on the first's data. → **Mitigation:** policy: data migrations are separate from schema migrations; data migrations are idempotent and re-runnable. Flagged for review in slice O1 where `audit_log` first ships.
- **[Trade-off]** Naming convention adds verbosity to the schema declaration but produces stable autogenerate diffs. We accept the verbosity; it's invisible to readers (constraints are rarely named explicitly in app code) and visible only at PR diff time where we want it visible.
- **[Trade-off]** The `before_flush` insert-time mismatch raise (D2 second branch) is a defence-in-depth check that adds one branch per insert. In hot insert paths (audit_log, equity_snapshots in later slices) this is one dict lookup per row — measured negligible in slice 2's `MessageBus` benchmarks.
- **[Trade-off]** L1 (ORM) + L2 (trigger) for append-only is two places that need to stay in sync: if a future slice adds an append-only table and forgets the trigger, the L2 escape hatch reappears. → Mitigation: a CI lint step (filed as Slice O1 followup, not this slice) that walks `Base.metadata.tables` for `__tablename_is_append_only__ = True` and asserts a corresponding `BEFORE UPDATE` trigger exists in the latest migration.

## Migration Plan

1. **Local dev**: `alembic upgrade head` runs in `make bootstrap` after this slice merges; bootstrap target already exists from slice 1, will gain a `db-upgrade` step in this slice's `Makefile.includes`.
2. **CI**: `pytest` with the integration tests + property test runs against an ephemeral SQLite (`tmp_path / "ig.db"`); no shared state.
3. **Production paper environment**: docker-compose's `db_init` service (added in slice 1) runs `alembic upgrade head` on container start before the api service boots.
4. **Rollback**: `alembic downgrade base` is reversible per the spec scenario `alembic downgrade base round-trips to empty`. In production, rollback means stopping the api, running `alembic downgrade -1`, restoring the previous container image. Litestream backup (slice 1) covers the data-loss case if rollback is required after writes have landed.
5. **v1.5 Postgres**: change connection string + run `alembic upgrade head` against fresh Postgres; the naming convention + portable types ensure the same DDL renders correctly. NFR-SC2 E2E test (lift SQLite snapshot, replay against Postgres, byte-identical row count) is owned by slice T4.

## Open Questions

(none blocking — the slice is well-scoped. The two slices-deferred items below are noted so future authors don't re-litigate them.)

- **(deferred to slice O1)** Append-only trigger CI lint that asserts every `__tablename_is_append_only__ = True` table has a corresponding trigger in its migration. Scope-creep for slice 3; slice O1 is the natural home because it ships the first append-only table (`audit_log`).
- **(deferred to v1.5)** Postgres RLS policies as defence-in-depth on top of the ORM listener. Out of scope for MVP; not even useful until the second tenant exists.
