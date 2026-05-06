## Why

The Research & Intelligence domain (Gate A amendment 2026-04-28, ADR-014) is the cornerstone differentiator of iguanatrader: a **bitemporal knowledge repository per-symbol with provenance + show-your-work** that lets the platform answer "what did we know about AAPL on 2024-06-15?" with full citation chain and retrieves the audit trail behind every numeric claim. Wave 3 ships four parallel slices that each plant adapters or synthesis on top of this fabric (R2 EDGAR/FRED, R3 news/catalysts, R4 OpenBB sidecar, R5 brief synthesis); without R1 landing first, every Wave 3 slice would either invent its own schema or stub the persistence layer and conflict on the migration number. R1 is the structural foundation — schema + ports + DTO/route stubs — so each Wave 3 track plugs in without touching shared files. Now is the right time because slice 5 (`api-foundation-rfc7807`) just merged and Wave 1 dependencies are satisfied; deferring would block the 4-way Wave 3 fan-out planned for the same sprint.

## What Changes

- **Bitemporal `research_facts` table** — append-only, dual-axis temporal model (`effective_from/effective_to` × `recorded_from/recorded_to` per ADR-014) with hybrid payload storage (inline JSONB ≤16KB / filesystem path ≥16KB) and full provenance enforcement via DB CHECK + NOT NULL constraints. Append-only at L1 (ORM listener from slice 3) AND L2 (per-table SQL trigger in this migration).
- **Versioned `research_briefs` table** — append-only, monotonically increasing `version` per `(tenant_id, symbol_universe_id)` with `citations` + `audit_trail` JSON columns enforcing show-your-work (FR70, NFR-O8). Refresh creates a new row; old versions retained indefinitely for audit replay (FR73).
- **Catalogue tables** — `research_sources` (cross-tenant catalogue, `__tenant_scoped__ = False`, exception to global tenant rule per data-model §3.7), `symbol_universe` (per-tenant, mutable), `watchlist_configs` (per-tenant, mutable, references methodology + brief refresh schedule), `corporate_events` (append-only, FR62), `analyst_ratings` (append-only, FR64). Total: 7 tables in migration `0002_research_tables`.
- **Bounded-context skeleton** — `apps/api/src/iguanatrader/contexts/research/{__init__,models,ports,repository,events}.py` plant the SQLAlchemy ORM models matching the migration, the `SourcePort` Protocol (consumed by R2/R3/R4 adapters), the `ResearchRepository` (extends `BaseRepository` from shared kernel for session injection + bitemporal point-in-time query helpers), and the bus event declarations (`ResearchFactIngested`, `ResearchBriefSynthesized`).
- **DTO stubs** — `apps/api/src/iguanatrader/api/dtos/research.py` defines the Pydantic v2 response models that R5 will return (`BriefResponse`, `FactResponse`, `CitationDetail`, `AuditTrailEntry`). R5 imports these unchanged; R1 lands them so the OpenAPI schema is stable across the Wave 3 fan-out.
- **Route stubs returning 501** — `apps/api/src/iguanatrader/api/routes/research.py` exports a `router: APIRouter` (dynamic discovery from slice 5) with the four endpoints R5 will fill (`GET /research/briefs/{symbol}`, `GET /research/briefs/{brief_id}/audit-trail`, `GET /research/facts/{symbol}`, `POST /research/briefs/{symbol}/refresh`). Each handler raises `NotImplementedError` which the slice-5 global `Exception` handler renders as 501 Problem with `type="urn:iguanatrader:error:not-implemented"`. The shape is wired; the synthesis lands in R5.
- **Tests** — `tests/unit/contexts/research/test_bitemporal_queries.py` exercises point-in-time retrieval against an in-memory SQLite session (asserts a fact recorded later cannot be observed at an earlier knowledge time); `tests/unit/contexts/research/test_provenance_enforcement.py` asserts every CHECK + NOT NULL guard rejects incomplete inserts (raises `IntegrityError` from the driver, lifted to `MissingProvenanceError` at the repository boundary).
- **No adapters, no synthesis, no UI** — R2/R3/R4 plant adapters; R5 plants synthesis + UI components; W1 has the route registry already (auto-discovery picks up `routes/research.py` without edits).

## Capabilities

### New Capabilities

- `research`: bitemporal knowledge repository for per-symbol facts with mandatory provenance metadata (source_id + source_url + retrieval_method + retrieved_at) enforced at the DB level. Hybrid payload storage (inline JSONB ≤16KB / filesystem ≥16KB with sha256 integrity). Versioned immutable briefs with citation chain + audit-trail show-your-work. Cross-tenant `research_sources` catalogue + per-tenant `symbol_universe`/`watchlist_configs`/`research_facts`/`research_briefs`/`corporate_events`/`analyst_ratings`. Route stubs return 501 until R5 ships synthesis.

### Modified Capabilities

(none — `api-foundation` from slice 5 stays as-is; R1 only consumes the dynamic-discovery contract.)

## Impact

- **Affected code (R1-owned, write-allowed)**:
  - `apps/api/src/iguanatrader/contexts/research/__init__.py` (NEW) — bounded-context package marker; re-exports public surface (`SourcePort`, `ResearchRepository`, event classes).
  - `apps/api/src/iguanatrader/contexts/research/models.py` (NEW) — 7 ORM models (`ResearchSource`, `SymbolUniverse`, `WatchlistConfig`, `ResearchFact`, `ResearchBrief`, `CorporateEvent`, `AnalystRating`) with `__tablename_is_append_only__` flags + `__tenant_scoped__` overrides.
  - `apps/api/src/iguanatrader/contexts/research/ports.py` (NEW) — `SourcePort` Protocol declaring `fetch(symbol, since) -> list[ResearchFactDraft]`; `ResearchFactDraft` dataclass for adapter→repository handoff.
  - `apps/api/src/iguanatrader/contexts/research/repository.py` (NEW) — `ResearchRepository(BaseRepository)` with bitemporal `as_of(symbol, at_time)` helper + `insert_fact(draft)` that lifts driver `IntegrityError` to `MissingProvenanceError`.
  - `apps/api/src/iguanatrader/contexts/research/events.py` (NEW) — bus event declarations (`ResearchFactIngested`, `ResearchBriefSynthesized` payloads).
  - `apps/api/src/iguanatrader/migrations/versions/0002_research_tables.py` (NEW) — 7-table Alembic migration with `down_revision = '0001'`, append-only triggers (L2) on `research_facts` + `research_briefs` + `corporate_events` + `analyst_ratings`, hybrid-payload XOR CHECK constraint, all temporal CHECK constraints from data-model §3.7. Reversible (`downgrade()` drops in FK-safe order).
  - `apps/api/src/iguanatrader/api/dtos/research.py` (NEW) — Pydantic v2 response models (read by R5; landed here for OpenAPI stability across Wave 3).
  - `apps/api/src/iguanatrader/api/routes/research.py` (NEW) — `router: APIRouter` with 4 endpoints raising `NotImplementedError` (rendered as 501 via slice-5 global handler). R5 replaces handlers in-place.
  - `apps/api/tests/unit/contexts/research/__init__.py` (NEW) — package marker.
  - `apps/api/tests/unit/contexts/research/test_bitemporal_queries.py` (NEW) — point-in-time retrieval correctness.
  - `apps/api/tests/unit/contexts/research/test_provenance_enforcement.py` (NEW) — CHECK/NOT NULL guard coverage + repository error lifting.
- **Affected code (slice-2/3/5-owned, read-only consumed)**:
  - `iguanatrader.shared.errors.IguanaError` hierarchy + `MissingProvenanceError(IguanaError)` (NEW subclass added to slice 2's hierarchy by R1 — single addition, mirrors slice-5 D9 precedent).
  - `iguanatrader.persistence.base.Base` + `__tenant_scoped__` / `__tablename_is_append_only__` class attributes.
  - `iguanatrader.persistence.append_only_listener` (L1 ORM-level enforcement; R1 trips it on `UPDATE research_facts SET ...`).
  - `iguanatrader.api.routes.__init__::register_routers` (slice-5 dynamic discovery; R1 adds a file, no edits to `__init__.py`).
  - `iguanatrader.api.errors._render_internal` (slice-5 fallback handler; renders R1's `NotImplementedError` raises as 501 Problem).
  - `iguanatrader.shared.kernel.BaseRepository` (slice-2 session-injection contract).
- **Affected APIs**: 4 new endpoints under `/api/v1/research/*` returning 501 Problem until R5. OpenAPI `/openapi.json` exposes the response models (typegen pipeline regenerates `packages/shared-types/src/index.ts` on first push).
- **Affected dependencies**: none — all primitives (SQLAlchemy 2.x, Alembic, Pydantic v2, structlog) already in root `pyproject.toml` since slice 1. No filesystem-cache directory creation in this slice (the `data/research_cache/` tree is provisioned by R2's first write — R1 stops at the schema + path column).
- **Prerequisites**:
  - `api-foundation-rfc7807` (slice 5, archived 2026-05-05) — provides the dynamic route discovery + RFC 7807 global handler that the route stubs rely on.
  - Transitively `persistence-tenant-enforcement` (slice 3) — provides Alembic env + tenant listener + append-only L1 listener.
  - Transitively `shared-primitives` (slice 2) — provides `IguanaError` + `BaseRepository` + `time.utc_now`.
- **Capability coverage** (per `docs/openspec-slice.md` row R1): FR68 (bitemporal effective×knowledge axes), FR69 (provenance NOT NULL + CHECK enforcement), FR70 (audit_trail JSON column on `research_briefs`), FR73 (versioned immutable briefs); +NFR-O8 (citation chain integrity at the schema level — `citations` JSONB column NOT NULL, broken-citation detection deferred to R5 render path).
- **Out of scope** (per `docs/openspec-slice.md` row R1):
  - Source adapters (`SECEdgarSource`, `FREDSource`, etc.) — R2/R3/R4.
  - LLM synthesis pipeline (`Synthesizer`, `CitationResolver`, `AuditTrail`) — R5.
  - SvelteKit research pages + components (`BriefHeader`, `FactTimeline`, etc.) — R5.
  - CLI subcommands (`refresh-brief`, `audit`) — R5.
  - SSE research stream — R5.
  - Hindsight bridge (`hindsight_bank_refs` table) — R6.
  - Filesystem cache tree creation under `data/research_cache/` — first writer (R2) provisions on demand.
  - Monthly sha256 integrity check job — out of MVP, v2 follow-up.
