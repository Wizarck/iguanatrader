## 1. Setup & dependencies

- [ ] 1.1 Add `sqlalchemy[asyncio]>=2.0,<3.0`, `alembic>=1.13,<2.0`, `aiosqlite>=0.19,<1.0` to `pyproject.toml` runtime deps under `[tool.poetry.dependencies]` (apps/api).
- [ ] 1.2 Add `asyncpg>=0.29,<1.0` under `[tool.poetry.extras] postgres = ["asyncpg"]` (v1.5 readiness; not installed by default).
- [ ] 1.3 Run `poetry lock --no-update && poetry install` and commit `poetry.lock`.
- [ ] 1.4 Verify `python -c "import sqlalchemy; print(sqlalchemy.__version__)"` reports ≥2.0 and `python -c "import sqlite3; print(sqlite3.sqlite_version)"` reports ≥3.38 (JSON1 included).

## 2. Persistence base + naming convention

- [ ] 2.1 Create `apps/api/src/iguanatrader/persistence/__init__.py` with re-exports for everything published (`Base`, `engine_factory`, `session_factory`, `verify_json1_extension`, all error classes).
- [ ] 2.2 Create `apps/api/src/iguanatrader/persistence/base.py`: define `NAMING_CONVENTION` dict per design D4, `metadata = MetaData(naming_convention=NAMING_CONVENTION)`, `Base = DeclarativeBase` with that metadata. Export class attrs documented by docstring: `__tenant_scoped__: bool = True` (default), `__tablename_is_append_only__: bool = False` (default).
- [ ] 2.3 Add unit test `apps/api/tests/unit/persistence/test_naming_convention.py` that asserts a sample table's PK/FK/UQ/IX names match the `pk_<table>`, `fk_<table>_<col>_<reftable>`, `uq_<table>_<col>`, `ix_<column_label>` patterns.

## 3. Errors module

- [ ] 3.1 Create `apps/api/src/iguanatrader/persistence/errors.py` with the four classes from design D9 (`TenantContextMissingError`, `TenantContextMismatchError`, `AppendOnlyViolationError`, `JSON1NotAvailableError`), each subclassing the right `shared.errors.IguanaError` parent and setting RFC 7807 status codes.
- [ ] 3.2 Add unit test `apps/api/tests/unit/persistence/test_errors.py` covering: each error's `to_problem_dict()` returns the right status; each error subclass-inherits from `IguanaError`.

## 4. Async engine + session factory

- [ ] 4.1 Create `apps/api/src/iguanatrader/persistence/session.py` with `engine_factory(url: str) -> AsyncEngine` and `session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]`. Both pure factories — no module-level state.
- [ ] 4.2 In `engine_factory`, register `event.listen(engine.sync_engine, "connect", _sqlite_pragmas)` that runs `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=30000;` ONLY if the URL starts with `sqlite`.
- [ ] 4.3 Use `async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)` per design D5.
- [ ] 4.4 Add unit test `apps/api/tests/unit/persistence/test_session_factory.py`: factory returns a callable; `expire_on_commit=False`; SQLite PRAGMAs are set (verify via `await conn.exec_driver_sql("PRAGMA foreign_keys")` returning `(1,)`).

## 5. Tenant filter listener

- [ ] 5.1 Create `apps/api/src/iguanatrader/persistence/tenant_listener.py` with private `_inject_tenant_filter(query, **kw)` and public `register_tenant_listeners()`.
- [ ] 5.2 Implement `_inject_tenant_filter` per design D1: walk the FROM clause; for each ORM-mapped table where `__tenant_scoped__` is True (default), `.where(table.c.tenant_id == bindparam("current_tenant", _read_tenant_var()))`. Read `tenant_id_var.get()`; if `LookupError`, raise `TenantContextMissingError`.
- [ ] 5.3 Implement `_stamp_tenant_on_inserts(session, flush_context, instances)` per design D2: iterate `session.new`; for each tenant-scoped instance with `tenant_id is None` set from `tenant_id_var.get()`; for explicit non-matching `tenant_id`, raise `TenantContextMismatchError`.
- [ ] 5.4 Public `register_tenant_listeners()` wires both listeners via `event.listen(Select, "before_compile", _inject_tenant_filter, retval=True)` and `event.listen(Session, "before_flush", _stamp_tenant_on_inserts)` (using the sync `Session` class that `AsyncSession` proxies).

## 6. Append-only listener

- [ ] 6.1 Create `apps/api/src/iguanatrader/persistence/append_only_listener.py` with private `_block_append_only_mutations(session, flush_context, instances)` and public `register_append_only_listener()`.
- [ ] 6.2 Implement: iterate `session.dirty | session.deleted`; for each instance whose class has `__tablename_is_append_only__ = True`, raise `AppendOnlyViolationError(table=instance.__class__.__tablename__, op="UPDATE" or "DELETE")`.
- [ ] 6.3 `register_append_only_listener()` wires via `event.listen(Session, "before_flush", _block_append_only_mutations)`.

## 7. Listener registration boot helper

- [ ] 7.1 Add `register_global_listeners()` in `persistence/__init__.py` that calls both registrar functions in order. Document it as the single entry point slice 5's lifespan will call.

## 8. JSON1 boot verify

- [ ] 8.1 Create `apps/api/src/iguanatrader/persistence/json1_check.py` with `async def verify_json1_extension(engine: AsyncEngine) -> None` per design D7.
- [ ] 8.2 On `OperationalError`, raise `JSON1NotAvailableError` whose message includes `sys.version`, `sqlite3.sqlite_version`, and the two remediation paths.
- [ ] 8.3 On success, emit structlog event `persistence.startup.json1_verified` with `python_version`, `sqlite_version` fields (per AGENTS.md hard rule on event naming).

## 9. Alembic env

- [ ] 9.1 Create `apps/api/src/iguanatrader/migrations/__init__.py` (empty package marker).
- [ ] 9.2 Create `apps/api/src/iguanatrader/migrations/env.py` per design D6 — async-aware (offline + online modes), `target_metadata = Base.metadata`, `compare_type=True`, `render_as_batch=True`, `transaction_per_migration=True`. Read DB URL from env var `IGUANA_DATABASE_URL`, default `sqlite+aiosqlite:///./data/iguanatrader.db`.
- [ ] 9.3 Create `apps/api/src/iguanatrader/migrations/script.py.mako` with revision header that emits `# Created at: <UTC ISO 8601>` (per AGENTS.md hard rule).
- [ ] 9.4 Create `apps/api/alembic.ini` pointing `script_location = src/iguanatrader/migrations`, `sqlalchemy.url = sqlite+aiosqlite:///./data/iguanatrader.db` (overridable via env), `file_template = %%(rev)s_%%(slug)s`.

## 10. First migration: 0001_initial_schema

- [ ] 10.1 Create `apps/api/src/iguanatrader/migrations/versions/0001_initial_schema.py` with `revision = "0001"`, `down_revision = None`, `branch_labels = None`, `depends_on = None`. Header docstring naming the slice and date.
- [ ] 10.2 In `upgrade()`, create `tenants` table per data-model.md §3.1: id UUID PK, name TEXT NOT NULL, feature_flags JSON NOT NULL DEFAULT '{}', created_at/updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted_at TIMESTAMPTZ NULL.
- [ ] 10.3 Create `users` table: id UUID PK, tenant_id UUID NOT NULL FK→tenants(id) ON DELETE RESTRICT, email TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','user')), created_at/updated_at NOT NULL. Indexes `uq_users_tenant_id_email`, `ix_users_tenant_id`.
- [ ] 10.4 Create `authorized_senders` table: id UUID PK, tenant_id UUID NOT NULL FK→tenants(id) ON DELETE RESTRICT, channel TEXT NOT NULL CHECK(channel IN ('telegram','whatsapp')), external_id TEXT NOT NULL, display_name TEXT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE, created_at/updated_at NOT NULL. Index `uq_authorized_senders_tenant_id_channel_external_id`.
- [ ] 10.5 In `downgrade()`, drop tables in reverse FK order: `authorized_senders`, `users`, `tenants`.
- [ ] 10.6 Smoke test: `IGUANA_DATABASE_URL=sqlite+aiosqlite:///:memory: alembic upgrade head` succeeds; `alembic downgrade base` succeeds.

## 11. Makefile targets

- [ ] 11.1 Edit `apps/api/Makefile.includes` (created in slice 1) to add: `db-upgrade: poetry run alembic -c apps/api/alembic.ini upgrade head`, `db-downgrade: poetry run alembic -c apps/api/alembic.ini downgrade -1`, `db-revision: poetry run alembic -c apps/api/alembic.ini revision --autogenerate -m "$(MSG)"`, `db-current: poetry run alembic -c apps/api/alembic.ini current`.
- [ ] 11.2 Verify `make db-upgrade && make db-current` reports `0001 (head)`.

## 12. Integration tests — tenant isolation

- [ ] 12.1 Create `apps/api/tests/integration/persistence/conftest.py` with fixtures: `db_url` (tmp_path SQLite), `engine` (calls `engine_factory`), `session_factory_fx`, `_register_listeners` autouse fixture.
- [ ] 12.2 Create `apps/api/tests/integration/persistence/test_tenant_isolation.py` covering all spec scenarios under `## Requirement: Tenant-scoped Select queries SHALL be auto-filtered by tenant_id`.
- [ ] 12.3 Add scenarios under `## Requirement: Inserts under tenant context SHALL stamp tenant_id automatically`.

## 13. Integration tests — append-only invariant

- [ ] 13.1 Create `apps/api/tests/integration/persistence/test_append_only_invariant.py` covering all spec scenarios. Define a test-only model `_AppendOnlyTestRow` with `__tablename_is_append_only__ = True` so the test does not depend on slice O1 shipping a real append-only table yet.
- [ ] 13.2 Include the raw-SQL bypass scenario: assert SQLite raises `IntegrityError` from a BEFORE UPDATE trigger when one is added in the test fixture (this validates the L2 mechanism we will use in slice O1).

## 14. Integration tests — JSON1 boot check + Alembic round-trip

- [ ] 14.1 Create `apps/api/tests/integration/persistence/test_json1_boot_check.py`: happy path verifies no raise + structlog event captured; mock-failure path patches `engine.connect` to raise `OperationalError("no such function: json")` and asserts message contents.
- [ ] 14.2 Create `apps/api/tests/integration/persistence/test_alembic_roundtrip.py`: programmatic `alembic.command.upgrade(config, "head")` then `alembic.command.downgrade(config, "base")` against a tmp_path SQLite; assert zero user tables remain; re-upgrade produces identical schema (introspection via `inspect(engine)`).

## 15. Property test — tenant filter invariant

- [ ] 15.1 Create `apps/api/tests/property/persistence/test_tenant_filter_invariant.py` with the Hypothesis strategy from the spec. Use `@settings(max_examples=50, deadline=2000)` and `asyncio.WindowsSelectorEventLoopPolicy` guard at module top (per slice 2 gotcha).
- [ ] 15.2 Strategy: `st.lists(st.tuples(uuid_strategy, st.sampled_from(["users", "authorized_senders"])), min_size=1, max_size=20)` → execute Inserts under each tenant; then for each unique tenant in the sequence, run `select(Model)` and assert all returned rows have `tenant_id == that_tenant`.

## 16. Documentation & gotchas

- [ ] 16.1 Append to `docs/gotchas.md` (created in slice 1): "Persistence — raw SQL bypasses ORM tenant filter; use ORM Select unless explicit privilege escalation is documented inline." Reference design D1 + spec.
- [ ] 16.2 Append: "Persistence — SQLite `PRAGMA foreign_keys = ON` is per-connection; the engine listener (D5) sets it on every connect. Without it, FK constraints are decorative."
- [ ] 16.3 Append: "Persistence — `expire_on_commit=False` means attribute access after commit returns cached values (no implicit refresh). Single-writer MVP is safe; multi-writer v2 will need explicit `await session.refresh(instance)` after commit."

## 17. Boundary check + structlog convention

- [ ] 17.1 Verify `apps/api/src/iguanatrader/persistence/*` does NOT import from `apps/api/src/iguanatrader/contexts/*` (no module exists yet, but ruff custom rule from slice 1 will check).
- [ ] 17.2 Grep all structlog log events in this slice match `persistence.<entity>.<action>` (e.g. `persistence.startup.json1_verified`, `persistence.tenant.context_missing`, `persistence.append_only.violation_blocked`).

## 18. Verification gate (CI-blocking before PR open)

- [ ] 18.1 `pytest apps/api/tests/unit/persistence apps/api/tests/integration/persistence apps/api/tests/property/persistence -v` passes.
- [ ] 18.2 `pytest --cov=iguanatrader.persistence --cov-report=term-missing apps/api/tests/{unit,integration,property}/persistence` reports ≥80% coverage on `apps/api/src/iguanatrader/persistence/*`.
- [ ] 18.3 `mypy --strict apps/api/src/iguanatrader/persistence apps/api/src/iguanatrader/migrations` clean.
- [ ] 18.4 `pre-commit run --from-ref origin/main --to-ref HEAD` passes (gitleaks + ruff + black + mypy + check-toml).
- [ ] 18.5 `make db-upgrade` then `make db-downgrade` round-trips on a tmp SQLite.
