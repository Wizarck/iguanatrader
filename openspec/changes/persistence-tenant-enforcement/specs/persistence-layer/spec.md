## ADDED Requirements

### Requirement: Tenant-scoped Select queries SHALL be auto-filtered by `tenant_id`

When a SQLAlchemy `Select` is compiled against any ORM-mapped table that has NOT opted out via `__tenant_scoped__ = False`, the persistence layer SHALL inject `WHERE <table>.tenant_id = :current_tenant` into the compiled SQL, where `:current_tenant` is read from `shared.contextvars.tenant_id_var`. If `tenant_id_var` is unset at compile time, the layer SHALL raise `TenantContextMissingError` (subclass of `IguanaError`, RFC 7807 status 500) **before** the query reaches the database.

#### Scenario: Select against tenant-scoped table under tenant A returns only tenant A rows

- **GIVEN** a `users` table populated with one row owned by tenant A and one row owned by tenant B
- **WHEN** an async session under `tenant_id_var = A` executes `select(User)`
- **THEN** the result set contains exactly one row, owned by tenant A; the SQL emitted contains `WHERE users.tenant_id = ?` with the parameter equal to A

#### Scenario: Select with no tenant context raises before hitting the database

- **GIVEN** an async session with `tenant_id_var` unset (token never set in this `contextvars` chain)
- **WHEN** code attempts `await session.execute(select(User))`
- **THEN** `TenantContextMissingError` is raised; no SQL reaches the SQLite/Postgres driver (verified by mocking the driver and asserting zero calls)

#### Scenario: Tables marked `__tenant_scoped__ = False` are NOT filtered

- **GIVEN** a future `research_sources` table declared with `__tenant_scoped__ = False` (cross-tenant catalogue, per data-model §3.1)
- **WHEN** an async session under any tenant context executes `select(ResearchSource)`
- **THEN** the SQL emitted contains NO `WHERE tenant_id = ?` clause and returns all rows regardless of tenant

### Requirement: Inserts under tenant context SHALL stamp `tenant_id` automatically

When a new ORM instance of a tenant-scoped table is added to a session and flushed, the persistence layer SHALL set its `tenant_id` attribute to the current value of `tenant_id_var` if and only if the attribute is `None` at flush time. If the caller explicitly sets a `tenant_id` that does not match `tenant_id_var`, the layer SHALL raise `TenantContextMismatchError` (subclass of `IguanaError`, RFC 7807 status 403) and abort the flush.

#### Scenario: Insert without explicit tenant_id is stamped from context

- **GIVEN** an async session under `tenant_id_var = A`
- **WHEN** code executes `session.add(User(email="x@y", password_hash="...", role="user"))` and `await session.flush()`
- **THEN** the inserted row's `tenant_id` column equals A

#### Scenario: Insert with mismatched explicit tenant_id is rejected

- **GIVEN** an async session under `tenant_id_var = A`
- **WHEN** code executes `session.add(User(tenant_id=B, email=...))` and `await session.flush()`
- **THEN** `TenantContextMismatchError` is raised; the row is NOT persisted (subsequent `select(User)` returns no row matching that email)

### Requirement: Append-only tables SHALL reject UPDATE and DELETE at flush time

Tables declared with the class attribute `__tablename_is_append_only__ = True` SHALL refuse all UPDATE and DELETE operations. The persistence layer SHALL raise `AppendOnlyViolationError` (subclass of `IguanaError`, RFC 7807 status 409) **before** the SQL reaches the driver. As a defence-in-depth secondary guard, the underlying database SHALL also enforce the invariant via trigger or check constraint where the dialect supports it (SQLite: `CREATE TRIGGER ... BEFORE UPDATE ... RAISE(FAIL, ...)`; Postgres v1.5: `CREATE TRIGGER ... BEFORE UPDATE OR DELETE`).

#### Scenario: Insert into append-only table succeeds

- **GIVEN** an async session under `tenant_id_var = A` and a future append-only table `audit_log` (consumed by slice O1)
- **WHEN** code adds a new `AuditLog` row and flushes
- **THEN** the row is persisted; `select(AuditLog)` returns it

#### Scenario: UPDATE on append-only row raises before reaching the driver

- **GIVEN** an existing row in an append-only table
- **WHEN** code modifies an attribute on the loaded ORM instance and calls `await session.flush()`
- **THEN** `AppendOnlyViolationError` is raised; the row in the database is unchanged (verified by re-querying with a fresh session)

#### Scenario: DELETE on append-only row raises before reaching the driver

- **GIVEN** an existing row in an append-only table
- **WHEN** code calls `await session.delete(instance)` and `await session.flush()`
- **THEN** `AppendOnlyViolationError` is raised; the row remains queryable

#### Scenario: Direct SQL UPDATE bypassing the ORM is caught by the database trigger

- **GIVEN** an existing row in an append-only table on SQLite
- **WHEN** code executes raw `await session.execute(text("UPDATE audit_log SET ... WHERE id = ?"))`
- **THEN** SQLite raises `sqlite3.IntegrityError` from the BEFORE UPDATE trigger; the row is unchanged

### Requirement: The first migration SHALL create the three cross-cutting mutable tables with named constraints

`migrations/versions/0001_initial_schema.py` SHALL create exactly three tables — `tenants`, `users`, `authorized_senders` — using the project naming convention so that all primary keys, foreign keys, unique constraints, and indexes have stable, deterministic names. The migration SHALL be reversible: `down_revision = None` and a `downgrade()` that drops the three tables in reverse FK order.

#### Scenario: `alembic upgrade head` from empty creates the three tables

- **GIVEN** a fresh empty SQLite database
- **WHEN** `alembic upgrade head` runs against it
- **THEN** the database contains exactly three user tables (`tenants`, `users`, `authorized_senders`) plus `alembic_version`; no other tables

#### Scenario: Constraints are named according to the project naming convention

- **WHEN** introspecting the post-migration schema
- **THEN** every primary key matches `pk_<table>`, every foreign key matches `fk_<table>_<column>_<reftable>`, every unique constraint matches `uq_<table>_<columns>`, and every index matches `ix_<table>_<columns>`

#### Scenario: `alembic downgrade base` round-trips to empty

- **GIVEN** a database at revision `0001_initial_schema`
- **WHEN** `alembic downgrade base` runs
- **THEN** the database contains zero user tables (only `alembic_version` with no rows); subsequent `alembic upgrade head` produces an identical schema

### Requirement: SQLite JSON1 extension SHALL be verified at startup with an explicit remediation message

The persistence layer SHALL expose a `verify_json1_extension(engine)` async helper that opens a connection from the engine and executes `SELECT json('{}')`. If the call raises (extension missing) or returns an unexpected value, the helper SHALL raise `JSON1NotAvailableError` (subclass of `IguanaError`, RFC 7807 status 500) whose message names the Python version detected, the SQLite version reported by `sqlite3.sqlite_version`, and the two supported remediation paths ("(a) install Python 3.11+ official build with bundled SQLite ≥3.38; (b) recompile your Python with `--enable-loadable-sqlite-extensions` and load the JSON1 module").

#### Scenario: JSON1 available — verification passes silently

- **GIVEN** Python 3.11+ official build (default install)
- **WHEN** `await verify_json1_extension(engine)` is called against a SQLite engine
- **THEN** the call returns `None` and emits a single structlog event `persistence.startup.json1_verified` with fields `python_version`, `sqlite_version`

#### Scenario: JSON1 missing — verification raises with explicit remediation

- **GIVEN** a mocked SQLite connection where `SELECT json('{}')` raises `OperationalError("no such function: json")`
- **WHEN** `await verify_json1_extension(engine)` is called
- **THEN** `JSON1NotAvailableError` is raised; the message contains the substring "Python 3.11+" and the substring "--enable-loadable-sqlite-extensions"

### Requirement: Property-based tenant filter invariant SHALL hold for arbitrary insert/select sequences

A Hypothesis-driven property test SHALL generate arbitrary sequences of (tenant_id, table_kind) Insert operations followed by Select operations under each tenant present in the sequence. The test SHALL assert that every Select under tenant X returns ONLY rows whose `tenant_id == X`. The strategy SHALL exercise at least 50 examples per CI run with `max_examples=50` and `deadline=2000ms`.

#### Scenario: Hypothesis finds no counterexample across 50 examples

- **GIVEN** the property test `test_tenant_filter_invariant`
- **WHEN** pytest runs it under CI
- **THEN** the test passes with no shrunken counterexample reported; the seed is recorded in the Hypothesis database for replayability
