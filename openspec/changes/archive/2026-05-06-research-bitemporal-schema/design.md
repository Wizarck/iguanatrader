## Context

R1 lands the research bounded-context fabric that Waves 3-4 build on. State at R1 start:

- Slice 1 `bootstrap-monorepo` ✅ — monorepo skeleton, Apache+CC license, ADR-014 stub authored as a physical file in `docs/adr/`.
- Slice 2 `shared-primitives` ✅ — `IguanaError` hierarchy + `BaseRepository` (session injection via `contextvars`) + `time.utc_now` consumed by every fact insert.
- Slice 3 `persistence-tenant-enforcement` ✅ — Alembic env + `tenant_listener` (auto-injects `tenant_id` filter via `tenant_id_var`) + `append_only_listener` (L1 ORM enforcement reading `__tablename_is_append_only__`). Migration `0001` shipped tenants/users/authorized_senders.
- Slice 4 `auth-jwt-cookie` ✅ — auth surface; consumes nothing from research.
- Slice 5 `api-foundation-rfc7807` ✅ — dynamic route/SSE/CLI discovery + global RFC 7807 handler + `Exception` fallback that wraps `NotImplementedError` → `InternalError` 500. **R1's route stubs override this**: each handler raises a NEW `NotImplementedError` subclass (`StubNotImplementedError`) that the global handler renders as 501, not 500.

The challenge is **schema-design completeness, not implementation surface**. R1 ships ~7 ORM models + 1 migration + ports + DTOs + route stubs + 2 unit test modules. The schema decisions taken here are load-bearing for Wave 3 (R2/R3/R4 each ingest into `research_facts`; R5 reads from every research table to synthesise briefs); a wrong CHECK constraint or a missing NOT NULL would force a follow-up migration in every Wave 3 slice. ADR-014 already settled the bitemporal pattern + hybrid payload threshold; design here translates the ADR into the migration shape + ORM declarations + repository contract that the Wave 3 slices consume.

The dynamic-discovery contract from slice 5 means R1 adds files (`routes/research.py`, `dtos/research.py`, `migrations/versions/0002_research_tables.py`, `contexts/research/*`) without editing any shared registry. The only shared edit is the `IguanaError` hierarchy growing by one subclass (`MissingProvenanceError`), mirroring slice 5's D9 precedent (`BootstrapNotReadyError`).

## Goals / Non-Goals

**Goals:**
- Land 7 tables in migration `0002` matching data-model §3.7 verbatim (column names, types, CHECK constraints, indexes, FK cascade rules) so Wave 3 slices have a stable schema to write against.
- Enforce provenance at the DB level (CHECK + NOT NULL on `source_id`/`source_url`/`retrieval_method`/`retrieved_at` for `research_facts` + `corporate_events` + `analyst_ratings`) so any adapter (R2/R3/R4) attempting an incomplete insert is rejected before reaching the ORM session — driver `IntegrityError` lifted to `MissingProvenanceError` at the repository boundary.
- Implement the bitemporal `as_of(symbol, at_time)` query helper on `ResearchRepository` so R5 has a single canonical PiT entrypoint instead of every methodology re-rolling the temporal predicate.
- Land DTO + route stubs that R5 mutates in-place (no rename, no signature change) so R5's PR has a small surface area.
- Plant the `SourcePort` Protocol so R2/R3/R4 each implement against a stable interface.

**Non-Goals:**
- No source adapter implementations — R2/R3/R4 own those (in parallel after R1).
- No LLM synthesis, citation resolver, audit-trail renderer, or methodology framework — R5 owns those.
- No SvelteKit components (`BriefHeader`, `FactTimeline`, etc.) — R5.
- No filesystem cache directory creation; the column `raw_payload_path` exists but R2's first ingest provisions `data/research_cache/<source_id>/<yyyy-mm>/`.
- No monthly sha256 integrity check job — v2 follow-up per data-model §7b.3 closing note.
- No new external dependencies — everything used (SQLAlchemy, Alembic, Pydantic v2, structlog) is already in slice 1's `pyproject.toml`.
- No Hindsight bridge (`hindsight_bank_refs`) — R6.

## Decisions

### D1. Bitemporal schema uses dual TIMESTAMPTZ axes (`effective_from/to` × `recorded_from/to`) — NOT a single audit timestamp + history table

**Decision**: `research_facts` carries four timestamp columns: `effective_from` (NOT NULL, when fact is true in world), `effective_to` (NULL = still effective), `recorded_from` (NOT NULL, when iguanatrader learned it), `recorded_to` (NULL = still believed). Point-in-time queries filter `effective_from <= :at AND (effective_to IS NULL OR effective_to > :at) AND recorded_from <= :at AND (recorded_to IS NULL OR recorded_to > :at)`. Fact revisions insert a NEW row with new `recorded_from` and `UPDATE` the previous row's `recorded_to` to the same timestamp — but the L1 + L2 append-only constraints would block this UPDATE; therefore `recorded_to` is mutated via a **scoped exception**: the repository's `supersede_fact(old_id, at)` method emits a raw SQL `UPDATE` that the L2 trigger explicitly allows ONLY for the `recorded_to` column (trigger `WHEN OLD.recorded_to IS NULL AND NEW.recorded_to IS NOT NULL` permits; everything else raises). Documented as gotcha #31.

**Alternatives considered**:
- **Single `as_of` timestamp + separate history table**: simpler ORM, but requires JOINs for every PiT query; bitemporal queries become two-step (query history + filter). Rejected — query plan is hot path for R5 brief synthesis; ADR-014 already settled on the dual-axis pattern.
- **JSONB array of `{value, effective_from, effective_to, recorded_from}` per (symbol, fact_kind)**: collapses revisions into one row, but breaks tenant filtering granularity + breaks the `recorded_from` index hot path. Rejected.
- **Strictly append-only with no `recorded_to` mutation** (insert new row, leave old row's `recorded_to` NULL forever): breaks the "what we believed at time T" semantics — both rows would appear as currently-believed. Rejected.

**Rationale**: ADR-014 is canonical. The dual-axis pattern is what makes "what did we know about AAPL on 2024-06-15?" answerable in one indexed scan. The narrow trigger exception for `recorded_to` is the minimum-cost path to preserve append-only-everywhere-else.

### D2. Provenance enforcement combines NOT NULL + CHECK + repository-level error lifting

**Decision**: `research_facts.source_id`, `source_url`, `retrieval_method`, `retrieved_at` are all `NOT NULL`. CHECK constraints add: `source_url != ''` (length > 0), `retrieval_method IN ('api','scrape','manual','llm')`, `effective_from <= COALESCE(effective_to, '9999-12-31')`, `recorded_from <= COALESCE(recorded_to, '9999-12-31')`, `value_numeric IS NOT NULL OR value_text IS NOT NULL OR value_jsonb IS NOT NULL` (at least one value). Same NOT NULL set on `corporate_events` + `analyst_ratings`. The repository's `insert_fact(draft)` wraps the SQLAlchemy flush in `try/except IntegrityError` and re-raises as `MissingProvenanceError(detail="...")` — slice 5's global handler then renders RFC 7807 422 + `urn:iguanatrader:error:missing-provenance`.

**Alternatives considered**:
- **Application-level validation only** (Pydantic on the `ResearchFactDraft` dataclass): catches typos at adapter boundary, but a misbehaving adapter that bypasses the dataclass (raw SQL insert, e.g. for performance) would slip past. Rejected — defence-in-depth required by FR69 + NFR-O8.
- **DB CHECK only, no repository lifting**: callers see the raw `IntegrityError` from the driver; structlog event is on the wrong layer. Rejected.
- **Add a `provenance_complete: bool` materialised column updated by trigger**: redundant given the NOT NULL + CHECK already guarantee it. Rejected.

**Rationale**: three layers (Pydantic at adapter, NOT NULL + CHECK at DB, repository error lifting at boundary) cost very little (a couple of CHECK clauses + an `except` block) and give every Wave 3 slice the same error semantics for free.

### D3. Hybrid payload storage with 16KB threshold + XOR CHECK + sha256 integrity (per ADR-014 §7b.3)

**Decision**: `research_facts` carries four payload columns:
- `raw_payload_inline` (JSONB / TEXT, NULL) — used when payload < 16KB.
- `raw_payload_path` (TEXT, NULL) — used when payload ≥ 16KB; relative path under `data/research_cache/<source_id>/<yyyy-mm>/<sha256>.<ext>`.
- `raw_payload_sha256` (CHAR(64), NULL) — sha256 hex; mandatory when `raw_payload_path` is set.
- `raw_payload_size_bytes` (INTEGER, NULL CHECK >= 0).

CHECK constraints:
- `(raw_payload_inline IS NULL) <> (raw_payload_path IS NULL)` — XOR exactly one set.
- `raw_payload_path IS NULL OR raw_payload_sha256 IS NOT NULL` — sha256 mandatory when filesystem.
- `raw_payload_size_bytes IS NULL OR raw_payload_size_bytes < 16384 OR raw_payload_path IS NOT NULL` — size > 16KB must use filesystem.

The repository's `insert_fact(draft)` chooses the storage tier based on `len(payload_bytes)`: < 16KB → inline JSONB; ≥ 16KB → write file under `data/research_cache/<source_id>/<yyyy-mm>/` (mkdir -p), persist path + sha256 + size. R1 ships the dispatch logic + path computation; the actual filesystem write IS exercised in unit tests (uses `tmp_path` fixture) but no `data/research_cache/` directory is created in the repo (production directory is created on first R2 write).

**Alternatives considered**:
- **All inline JSONB** (no filesystem tier): SQLite 4MB row default + LangChain raw HTML payloads (Finviz, GDELT) routinely exceed inline limits. Rejected per ADR-014.
- **All filesystem** (no inline): every fact roundtrips disk I/O even for sub-KB numbers. Rejected — slows the hot path of fundamental ingestion.
- **8KB threshold** (more aggressive offload): cuts off too many small XBRL JSON payloads that benefit from inline JSONB query. ADR-014 settled on 16KB after measuring sample EDGAR/Finnhub corpora.
- **Compress inline payloads** (zlib / zstd): adds CPU + breaks JSONB queryability. Rejected.

**Rationale**: ADR-014 §7b.3 settled the threshold + integrity hash + path scheme. R1 implements verbatim. Monthly integrity check job is v2; R1 lands the column so the v2 check can run without schema migration.

### D4. Append-only enforced at L1 (ORM listener) AND L2 (per-table triggers in the migration)

**Decision**: `ResearchFact`, `ResearchBrief`, `CorporateEvent`, `AnalystRating` set `__tablename_is_append_only__ = True` at the ORM (L1 catches all ORM-driven mutations via slice-3 listener). Migration `0002` ALSO emits per-table BEFORE UPDATE / BEFORE DELETE triggers (`RAISE(FAIL, 'append-only')` on SQLite; equivalent for Postgres v1.5) — L2 catches raw SQL bypasses. Exception (per D1): the trigger on `research_facts` permits `UPDATE ... SET recorded_to = :ts` when `OLD.recorded_to IS NULL AND NEW.recorded_to IS NOT NULL` (single-direction, single-column transition). All other UPDATE/DELETE patterns abort.

**Alternatives considered**:
- **L1 only** (rely on ORM listener): a future slice using raw SQL (perf hot path, bulk import) would silently bypass append-only. Rejected — slice 3 D3 mandated two-layer enforcement.
- **L2 only** (rely on triggers): ORM-driven UPDATEs would surface as confusing `OperationalError` from the driver; L1's `AppendOnlyViolationError` is the cleaner Python-side error. Rejected — keep both.
- **No `recorded_to` mutation exception** (force "supersession via marker row"): doubles row count + breaks the canonical bitemporal query. Rejected.

**Rationale**: defence-in-depth as established in slice 3; bitemporal `recorded_to` is the documented exception per ADR-014.

### D5. Versioned immutable `research_briefs` — `version` is a per-`(tenant_id, symbol_universe_id)` monotonic counter, NOT a global serial

**Decision**: `research_briefs.version INTEGER NOT NULL CHECK (version >= 1)` with unique index `uq_research_briefs_tenant_id_symbol_universe_id_version`. New brief insertion: `version = 1 + COALESCE((SELECT MAX(version) FROM research_briefs WHERE tenant_id = :tid AND symbol_universe_id = :sid), 0)`. Race condition between two concurrent refreshes for the same symbol resolved by the unique constraint — the loser retries. R5's `BriefService.refresh()` will catch `IntegrityError` on the unique violation, increment, retry (max 3 attempts).

**Alternatives considered**:
- **Global monotonic counter via `Sequence`**: works on Postgres, ugly on SQLite (which has only `AUTOINCREMENT`). Rejected for portability.
- **`created_at DESC LIMIT 1` instead of explicit version**: no per-symbol uniqueness guarantee; concurrent refreshes both succeed at "current". Rejected.
- **UUID-only, no version** (clients sort by `created_at`): breaks the data-model §3.7 spec (which mandates `version` field) + breaks "v3 of AAPL brief" CLI semantics. Rejected.

**Rationale**: per-symbol monotonicity is what FR73 asks for. The unique constraint + retry-on-violation is the standard pattern.

### D6. Route stubs raise `StubNotImplementedError` (subclass of `IguanaError`) rendering 501, NOT generic `NotImplementedError` lifted to 500

**Decision**: introduce `StubNotImplementedError(IguanaError)` in `iguanatrader.shared.errors` with `default_status=501`, `default_title="Endpoint Not Yet Implemented"`, `type_uri="urn:iguanatrader:error:not-implemented"`. R1's `routes/research.py` handlers each `raise StubNotImplementedError(detail="GET /research/briefs/{symbol} ships in slice R5 (research-brief-synthesis)")`. Slice 5's `IguanaError` handler (registered first per slice-5 D10) renders 501 Problem with the canonical urn type URI. R5 replaces the body of each handler in-place; the route signature does not change.

**Alternatives considered**:
- **Generic `raise NotImplementedError(...)`**: slice 5's `_render_internal` fallback wraps as `InternalError` 500 — wrong status code (501 is "the server does not support the functionality required to fulfil the request"; 500 is "unexpected"). Rejected.
- **Return a hardcoded 501 `JSONResponse`**: bypasses the global handler + diverges from slice-5 D3 ("routes raise, the handler renders"). Rejected.
- **Don't ship route stubs at all** (R5 adds the file when it ships): then R5 also adds the OpenAPI surface, which means the `/openapi.json` shape shifts mid-Wave-3 — frontend `shared-types` regen happens once at R5 instead of once at R1, but consumers (W1+) lose the early stable surface. Rejected — consistency with slice-5 anti-collision pattern wins.

**Rationale**: 501 is the canonical "stub" status. Using a typed `IguanaError` subclass keeps the rendering uniform with every other error path in the system + gives operators a queryable structlog event when the stub fires (`api.research.stub_called`).

### D7. `ResearchRepository(BaseRepository)` extends slice-2 BaseRepository — session injection via `contextvars`, NOT explicit session passing

**Decision**: `ResearchRepository` inherits from `iguanatrader.shared.kernel.BaseRepository` (slice 2). Constructor takes no `session` argument; methods read the active session from `iguanatrader.persistence.session::session_var` (set by FastAPI dep `get_db_session` from slice 3). The repository exposes:
- `as_of(symbol: str, at: datetime) -> list[ResearchFact]` — bitemporal PiT query for a single symbol.
- `insert_fact(draft: ResearchFactDraft) -> ResearchFact` — provenance-validating insert with hybrid-payload dispatch + driver-error lifting.
- `supersede_fact(old_id: UUID, at: datetime) -> None` — sets `recorded_to` on the prior row (raw SQL; passes the L2 trigger exception).
- `latest_brief(symbol: str) -> ResearchBrief | None` — `ORDER BY created_at DESC LIMIT 1` per-symbol-per-tenant.
- `insert_brief(...)` and methodology-specific helpers — stub signature only; bodies raise `StubNotImplementedError` until R5.

**Alternatives considered**:
- **Plain functions with `session: AsyncSession` arg**: works but breaks the slice-2 contract; every adapter would have to thread the session manually + mocking becomes harder. Rejected.
- **Class with explicit session in constructor**: `__init__(self, session)`; tests construct with a fixture session. Slightly more explicit, but breaks `tenant_id_var` scoping (slice-3 tenant listener reads `tenant_id_var.get()` from contextvar; not from the session). Rejected — session-via-contextvar is the established pattern in slice 3.

**Rationale**: consistency with slice-2 `BaseRepository` + slice-3 listeners. Wave 3 slices construct `ResearchRepository()` (no args) and call methods.

## Risks / Trade-offs

- **[Risk] Bitemporal `recorded_to` mutation exception in the L2 trigger is subtle** → a future contributor adding an UPDATE on `recorded_to` from a column other than NULL → not-NULL transition would silently fail or worse, succeed. **Mitigation**: gotcha #31 documents the trigger exception; integration test `test_recorded_to_supersession.py` (deferred to R5 — first concrete consumer) asserts the trigger blocks every other UPDATE pattern. R1's unit test asserts the trigger DDL is present in the migration's `upgrade()` output.
- **[Risk] CHECK constraint for hybrid payload XOR drifts from data-model §7b.3** → if R2 mistakenly populates BOTH inline + path, the constraint rejects but the error path is confusing. **Mitigation**: `ResearchFactDraft.with_payload(payload_bytes)` factory method computes the storage tier deterministically (size-based dispatch); adapters never set both fields manually.
- **[Risk] `data/research_cache/` directory not yet provisioned at R1 ship** → R2's first write may fail with `FileNotFoundError`. **Mitigation**: `_persist_payload_to_filesystem(...)` in `ResearchRepository` calls `path.parent.mkdir(parents=True, exist_ok=True)` before writing — `data/research_cache/` is created on first use, not at deploy time. Document in `docs/gotchas.md` #32.
- **[Risk] Concurrent brief refresh race** → two synthesis jobs for the same `(tenant, symbol)` both compute `version = MAX+1`, both insert, one fails on the unique constraint. **Mitigation**: per D5, repository retries up to 3 times with `IntegrityError` catch + recompute. R5 will finalize this; R1 only ships the unique constraint, the `insert_brief` stub, and the test for the constraint shape.
- **[Trade-off] Append-only L2 trigger DDL must be hand-written per dialect** (SQLite uses `RAISE(FAIL, ...)`; Postgres v1.5 uses `RAISE EXCEPTION`). **Mitigation**: `0002_research_tables.py` includes both via `op.execute()` guarded by `op.get_bind().dialect.name`. Test asserts the trigger fires on SQLite (the MVP DB); Postgres branch is exercised in v1.5 milestone.
- **[Trade-off] DTO stubs in `dtos/research.py` may be re-shaped by R5** if synthesis discovers a missing field. **Mitigation**: model R5's known requirements from PRD FR70-FR75 + data-model §3.7 verbatim — `BriefResponse` includes `thesis_text`, `score_overall`, `citations`, `audit_trail` so R5 needs zero structural changes. If R5 needs a new field, the OpenAPI schema regenerates the typegen — additive change is cheap.
- **[Trade-off] `MissingProvenanceError` adds one more `IguanaError` subclass** — slice 5 D9 set the precedent (`BootstrapNotReadyError`); same justification: post-hoc rectification of a slice-2 omission rather than gratuitous addition. Document inline in `shared/errors.py`.

## Migration Plan

R1 has no live deployment to migrate from. Deployment path:

1. Merge R1 to main.
2. CI fires the `openapi-types.yml` workflow; bot commit regenerates `packages/shared-types/src/index.ts` with the `BriefResponse`, `FactResponse`, etc. interfaces.
3. R2/R3/R4 each branch from main, implement adapters against `SourcePort` + insert via `ResearchRepository.insert_fact(draft)` — no schema edits.
4. R5 branches from main (after R2/R3/R4 mocks are sufficient), replaces route handler bodies in `routes/research.py` (signatures unchanged), implements `Synthesizer` + `CitationResolver` against the existing models + DTOs.
5. Wave 3 slices land in any order; the only shared file Wave 3 modifies is the OpenAPI schema (re-generated each CI run).

Rollback = revert PR + Alembic `downgrade -1` (drops the 7 tables + triggers in FK-safe order). Filesystem cache directory is empty at R1 ship (no data to lose); R2's first write provisions it, after which rollback would orphan the cache files. R1 itself has zero rollback risk.

## Open Questions

- **Q**: Should `ResearchFact.value_jsonb` use `JSONB` on Postgres / `TEXT with JSON1` on SQLite, or just `JSON` (cross-dialect SQLAlchemy)? **Tentative answer**: `JSON` — slice 1 already standardised on this for `tenants.feature_flags` and slice 3 verifies JSON1 at boot. Documented in models.py docstring with a v2 note that Postgres `JSONB` is preferred for query performance.
- **Q**: Does `corporate_events.payload` need a CHECK on `event_kind`-specific shape? **Tentative answer**: no for R1 — Pydantic validates at the adapter (R2/R3) layer; the JSONB column is opaque at the DB level. Adding per-kind CHECKs would force schema changes when new kinds are added; the trade-off favors flexibility.
- **Q**: Should `ResearchRepository.as_of(...)` accept a list of symbols for batch PiT? **Tentative answer**: not in R1 — single-symbol is the R5 hot path (per-symbol brief synthesis); batch can be added when R5 surfaces a multi-symbol use case (e.g., portfolio-wide brief comparison).
