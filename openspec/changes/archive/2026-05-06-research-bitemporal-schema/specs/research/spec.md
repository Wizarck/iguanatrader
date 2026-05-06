## ADDED Requirements

### Requirement: `research_facts` persists with dual-axis bitemporal timestamps

The system SHALL persist every research fact with four timestamp columns: `effective_from` (NOT NULL, when the fact is true in the world), `effective_to` (NULL when still effective; SET when superseded), `recorded_from` (NOT NULL, when iguanatrader learned the fact), `recorded_to` (NULL when still believed; SET when a fact revision arrives). The schema SHALL support point-in-time retrieval of "what did we know about symbol X at time T" via the predicate `effective_from <= :at AND (effective_to IS NULL OR effective_to > :at) AND recorded_from <= :at AND (recorded_to IS NULL OR recorded_to > :at)`.

#### Scenario: Point-in-time query returns only facts visible at the requested time

- **GIVEN** a `research_facts` row with `effective_from=2024-04-25T00:00Z`, `recorded_from=2024-04-26T10:00Z`, both `_to` columns NULL
- **WHEN** the repository's `as_of(symbol="AAPL", at="2024-04-25T12:00Z")` is invoked
- **THEN** the row is NOT returned (recorded_from is after the requested knowledge time)
- **AND** the same query at `at="2024-04-27T00:00Z"` returns the row

#### Scenario: Fact revision creates a new row + supersedes the old one

- **GIVEN** a fact row R1 inserted at `recorded_from=T1` with `recorded_to=NULL`
- **WHEN** a corrected value arrives at time T2 and the repository's `supersede_fact(R1.id, at=T2)` is invoked, then `insert_fact(...)` lands a new row R2 with `recorded_from=T2`
- **THEN** R1's `recorded_to` equals T2 (set via the narrow trigger exception)
- **AND** the L2 append-only trigger blocks any other UPDATE on R1 (e.g., changing `value_numeric` raises)
- **AND** `as_of(symbol, at=T1.5)` returns R1; `as_of(symbol, at=T2.5)` returns R2

### Requirement: `research_facts` rejects inserts missing provenance metadata

The system SHALL refuse to insert a `research_facts` row that lacks any of `source_id`, `source_url` (non-empty), `retrieval_method ∈ {api, scrape, manual, llm}`, `retrieved_at`. The DB SHALL enforce this via NOT NULL columns + CHECK constraints. The `ResearchRepository.insert_fact(...)` method SHALL catch driver `IntegrityError` and re-raise as `MissingProvenanceError` (an `IguanaError` subclass with `default_status=422`, `type_uri="urn:iguanatrader:error:missing-provenance"`).

#### Scenario: Insert with NULL source_id fails

- **GIVEN** a `ResearchFactDraft` with `source_id=None`
- **WHEN** `ResearchRepository.insert_fact(draft)` is invoked
- **THEN** the SQLAlchemy flush raises `IntegrityError` (NOT NULL violation)
- **AND** the repository catches the error and raises `MissingProvenanceError(detail="research_facts.source_id is required")`
- **AND** when raised inside a route, the slice-5 global handler renders RFC 7807 422 with `type="urn:iguanatrader:error:missing-provenance"`

#### Scenario: Insert with invalid retrieval_method fails

- **GIVEN** a draft with `retrieval_method="screenshot"` (not in the allowed enum)
- **WHEN** `insert_fact(draft)` is invoked
- **THEN** the CHECK constraint `retrieval_method IN ('api','scrape','manual','llm')` rejects the row
- **AND** `MissingProvenanceError` is raised with `detail` referencing the invalid retrieval_method

#### Scenario: Insert with no value field at all fails

- **GIVEN** a draft with `value_numeric=None AND value_text=None AND value_jsonb=None`
- **WHEN** `insert_fact(draft)` is invoked
- **THEN** the CHECK constraint `value_numeric IS NOT NULL OR value_text IS NOT NULL OR value_jsonb IS NOT NULL` rejects the row
- **AND** `MissingProvenanceError` is raised

### Requirement: `research_facts` payload storage uses hybrid 16KB threshold with sha256 integrity

The system SHALL dispatch raw payload storage based on size: payloads strictly less than 16384 bytes SHALL be stored inline in `raw_payload_inline` (JSONB / TEXT); payloads of 16384 bytes or more SHALL be written to filesystem under `data/research_cache/<source_id>/<yyyy-mm>/<sha256>.<ext>` with the relative path persisted in `raw_payload_path`, sha256 hex in `raw_payload_sha256` (CHAR(64), mandatory when `raw_payload_path` is set), and byte count in `raw_payload_size_bytes`. The DB SHALL enforce: (a) XOR exactly-one-set: `(raw_payload_inline IS NULL) <> (raw_payload_path IS NULL)`; (b) sha256 mandatory when filesystem: `raw_payload_path IS NULL OR raw_payload_sha256 IS NOT NULL`; (c) size-tier consistency: payloads ≥ 16384 bytes MUST use filesystem.

#### Scenario: Small payload stored inline

- **GIVEN** a payload of 8000 bytes (a typical EDGAR XBRL row)
- **WHEN** `insert_fact(draft)` is invoked with this payload
- **THEN** `raw_payload_inline` is populated with the JSON-encoded payload
- **AND** `raw_payload_path`, `raw_payload_sha256` are NULL
- **AND** `raw_payload_size_bytes = 8000`
- **AND** no file is written to `data/research_cache/`

#### Scenario: Large payload offloaded to filesystem

- **GIVEN** a payload of 32000 bytes (a typical Finviz scraped HTML page)
- **WHEN** `insert_fact(draft)` is invoked
- **THEN** the repository computes sha256, writes the payload to `data/research_cache/<source_id>/<yyyy-mm>/<sha256>.json` (creating parent dirs as needed)
- **AND** `raw_payload_path` is the relative path; `raw_payload_inline` is NULL
- **AND** `raw_payload_sha256` is the 64-char hex digest; `raw_payload_size_bytes = 32000`
- **AND** re-reading `raw_payload_path` yields a file whose sha256 equals the stored value

#### Scenario: Mis-sized payload (≥16KB but inline) rejected

- **GIVEN** a hand-crafted insert that sets `raw_payload_inline` to a 20000-byte JSONB AND `raw_payload_size_bytes = 20000`
- **WHEN** the flush executes
- **THEN** the CHECK constraint `raw_payload_size_bytes IS NULL OR raw_payload_size_bytes < 16384 OR raw_payload_path IS NOT NULL` rejects the row

### Requirement: `research_facts`, `research_briefs`, `corporate_events`, `analyst_ratings` are append-only at L1 + L2

The system SHALL set `__tablename_is_append_only__ = True` on the four ORM models so the slice-3 ORM listener (L1) raises `AppendOnlyViolationError` on any session.dirty / session.deleted instance. The migration `0002_research_tables` SHALL also emit per-table BEFORE UPDATE / BEFORE DELETE triggers (L2) that abort raw-SQL mutations. The `research_facts` table SHALL have a narrow exception in its UPDATE trigger: a single-column transition `recorded_to: NULL → :ts` is permitted; every other UPDATE pattern aborts.

#### Scenario: ORM UPDATE on research_facts blocked by L1

- **GIVEN** a persisted `ResearchFact` instance loaded into a session
- **WHEN** a caller mutates `instance.value_numeric = 99` and calls `session.flush()`
- **THEN** the slice-3 `before_flush` listener detects the dirty instance
- **AND** raises `AppendOnlyViolationError("UPDATE on research_facts refused: ...")` before reaching the driver

#### Scenario: Raw SQL DELETE on research_briefs blocked by L2

- **GIVEN** a persisted `research_briefs` row
- **WHEN** a caller executes `session.execute(text("DELETE FROM research_briefs WHERE id = :id"), {"id": ...})`
- **THEN** the L2 BEFORE DELETE trigger fires
- **AND** the driver raises an error indicating the trigger aborted the operation

#### Scenario: Narrow `recorded_to` supersession permitted

- **WHEN** `ResearchRepository.supersede_fact(old_id, at=T)` issues `UPDATE research_facts SET recorded_to = :at WHERE id = :old_id AND recorded_to IS NULL`
- **THEN** the L2 trigger's `WHEN OLD.recorded_to IS NULL AND NEW.recorded_to IS NOT NULL` branch permits the UPDATE
- **AND** any other UPDATE pattern (e.g., changing `value_numeric` or attempting to clear `recorded_to`) aborts with the trigger error

### Requirement: `research_briefs` are versioned per-symbol per-tenant with monotonic `version`

The system SHALL persist each `research_briefs` row with `version INTEGER NOT NULL CHECK (version >= 1)` and SHALL enforce uniqueness of `(tenant_id, symbol_universe_id, version)` via a unique index `uq_research_briefs_tenant_id_symbol_universe_id_version`. New brief insertion SHALL compute `version = 1 + COALESCE(MAX(version) FILTERED by tenant_id + symbol_universe_id, 0)`. The `created_at` field SHALL drive vigent-brief lookup via `ORDER BY created_at DESC LIMIT 1`.

#### Scenario: First brief for a symbol gets version 1

- **GIVEN** a tenant with no existing `research_briefs` rows for `symbol_universe_id=:sid`
- **WHEN** `ResearchRepository.insert_brief(...)` is invoked
- **THEN** the inserted row has `version = 1`

#### Scenario: Refreshed brief gets version N+1

- **GIVEN** a tenant with three existing briefs for `:sid` at versions 1, 2, 3
- **WHEN** `insert_brief(...)` is invoked again
- **THEN** the new row has `version = 4`
- **AND** `latest_brief(symbol)` returns the version-4 row (most recent `created_at`)

### Requirement: Research route stubs render 501 RFC 7807 until R5 ships

The system SHALL expose `routes/research.py` with `router: APIRouter` carrying four endpoints (auto-mounted at `/api/v1/research/*` via slice-5 dynamic discovery): `GET /research/briefs/{symbol}`, `GET /research/briefs/{brief_id}/audit-trail`, `GET /research/facts/{symbol}`, `POST /research/briefs/{symbol}/refresh`. Each handler SHALL `raise StubNotImplementedError(detail="...")` referencing R5. The slice-5 global `IguanaError` handler SHALL render the response as 501 with `type="urn:iguanatrader:error:not-implemented"` and `media_type="application/problem+json"`.

#### Scenario: GET /research/briefs/{symbol} returns 501 in R1

- **WHEN** `GET /api/v1/research/briefs/AAPL` is invoked against an R1-deployed app
- **THEN** the response is `501 Not Implemented`
- **AND** `Content-Type: application/problem+json`
- **AND** the body's `type` field equals `urn:iguanatrader:error:not-implemented`
- **AND** the body's `detail` references R5 (e.g., "GET /research/briefs/{symbol} ships in slice R5 (research-brief-synthesis)")
- **AND** the structlog event `api.research.stub_called` is emitted with `endpoint="GET /research/briefs/{symbol}"`

#### Scenario: OpenAPI schema exposes the response model

- **WHEN** the OpenAPI schema for `GET /api/v1/research/briefs/{symbol}` is generated
- **THEN** the `responses["200"]["content"]["application/json"]["schema"]` references the `BriefResponse` Pydantic model from `dtos/research.py`
- **AND** the regenerated `packages/shared-types/src/index.ts` exports a `BriefResponse` interface with the canonical fields (`thesis_text`, `score_overall`, `citations`, `audit_trail`, etc.)

### Requirement: `research_sources` is a cross-tenant catalogue with no `tenant_id` column

The system SHALL persist `research_sources` as a cross-tenant catalogue (one row per source adapter, e.g. `sec_edgar`, `fred`, `finnhub`). The ORM model SHALL set `__tenant_scoped__ = False` so the slice-3 tenant listener does NOT inject a `tenant_id` filter on queries. The schema SHALL NOT include a `tenant_id` column. The catalogue SHALL be readable by every tenant.

#### Scenario: Cross-tenant source lookup succeeds without tenant context

- **GIVEN** a `tenant_id_var` set to tenant T1
- **WHEN** the repository queries `SELECT * FROM research_sources WHERE id = 'sec_edgar'`
- **THEN** the row is returned (no `tenant_id` filter is injected)
- **AND** the same query under tenant T2 returns the same row
