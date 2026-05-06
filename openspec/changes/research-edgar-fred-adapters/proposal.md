## Why

iguanatrader's research differentiator (Gate A amendment 2026-04-28, ADR-014) only delivers value once real Tier-A facts are flowing into the bitemporal `research_facts` table that R1 just landed. The four government-grade native point-in-time sources — SEC EDGAR (filings), FRED (macro), BLS (employment), BEA (GDP) — together cover the regulatory + macroeconomic backbone of every methodology that R5 will synthesise (3-pillar, CANSLIM, Magic Formula, QARP, Multi-factor). They are Tier-A precisely because each source publishes timestamps that map cleanly to `effective_from/to` (the date a 10-K is filed, the FRED vintage date, the BLS reference period) so the bitemporal queries from R1 return real answers instead of empty result sets. Now is the right time because R1 archived on 2026-05-06 and Wave 3 fan-out (R2/R3/R4/R5) is gated on adapters landing — without R2 the synthesis layer in R5 has no Tier-A corpus to cite + the citation chain (NFR-O8) cannot be exercised end-to-end. R3 (Tier-B/C) intentionally lands in parallel; it depends on the same `SourcePort` contract but covers different sources with different freshness semantics.

## What Changes

- **Tier-A `SourceAdapter` base class** — `apps/api/src/iguanatrader/contexts/research/sources/base.py` plants an abstract base implementing `SourcePort` (from R1) with shared concerns: rate-limit-aware HTTP client (httpx with token-bucket throttling), structured error mapping (4xx → permanent skip, 5xx → backoff), structlog event emission (`research.<source>.<action>`), `dedupe_key` builder for idempotency, and the `tier='A'` enforcement (every adapter sets `tier='A'` on every emitted `ResearchFactDraft`). All four concrete adapters inherit from this base.
- **SEC EDGAR adapter** (`sec_edgar.py`) — pulls Form 4 (insider transactions), 10-K (annual), 10-Q (quarterly), 8-K (material events), 13F-HR (institutional holdings). Uses the JSON submissions API + XBRL financial-data API (`data.sec.gov/api/xbrl/`). Honours SEC's mandatory `User-Agent: <company> <email>` header (no key, but rejection on missing UA) + 10 req/sec rate limit. PiT mapping: `effective_from = filing_date`, `recorded_from = retrieved_at`, `dedupe_key = "sec_edgar:<accession_number>"`.
- **FRED adapter** (`fred.py`) — pulls macro time series (CPI, unemployment, fed funds rate, M2, etc.) via series_id-based queries against `api.stlouisfed.org/fred/series/observations`. ALFRED variant (vintage-aware) preserves original publication vintages so revisions land as new facts (`recorded_from` = vintage release date) instead of overwriting prior values. Requires API key (free tier 120 req/min). PiT mapping: `effective_from = observation_date`, `recorded_from = realtime_start` (ALFRED vintage).
- **BLS adapter** (`bls.py`) — pulls employment + inflation series (CES, CPS, CPI-U, PPI) via `api.bls.gov/publicAPI/v2/timeseries/data/`. Free unregistered tier limited to 25 queries/day (no historical pre-1990); registered tier (free, requires email signup) is 500 queries/day with full history. Adapter assumes registered tier — API key required at startup. PiT mapping: `effective_from = period_start`, `recorded_from = release_date` (BLS publishes a calendar of release dates per series).
- **BEA adapter** (`bea.py`) — pulls GDP + national accounts (NIPA tables) via `apps.bea.gov/api/data/`. Free API key (registration required). Quarterly GDP gets advance/second/third estimates plus annual/comprehensive revisions — each revision lands as a new fact with the same `effective_from` (reference quarter end) but a later `recorded_from` (release date), driving the bitemporal "what we believed about Q1 GDP at time T" semantics. Rate limit: 100 req/min, 100 MB/day, 30 errors/min.
- **Idempotency via `research_sources.dedupe_key`** — each adapter builds a deterministic key (`<source>:<filing_id>` for EDGAR, `<source>:<series_id>:<observation_date>:<vintage>` for FRED/ALFRED, `<source>:<series_id>:<period>:<release_date>` for BLS, `<source>:<dataset>:<table>:<frequency>:<period>:<release_date>` for BEA). On insert, the repository resolves the dedupe key against `research_sources.dedupe_index` (a JSONB → fact_id mapping, lazy-populated); a hit short-circuits to no-op + emits `research.<source>.skipped_duplicate`. Re-running an adapter the day after a fresh ingest is a no-op.
- **Integration tests** (`tests/integration/test_edgar_ingestion.py`, `test_fred_ingestion.py`) using VCR.py-recorded fixtures (committed under `tests/fixtures/vcr/`) — happy path plus idempotency assertion (run adapter twice → second run inserts zero rows). BLS + BEA covered in shorter unit tests with pytest-httpx mocking; full integration test deferred to R5 once a downstream consumer exists.
- **No scraping, no Tier-B/C** — all four sources are public APIs. R3 owns Finnhub/GDELT/OpenFDA/OpenInsider/Finviz/WGI/V-Dem/IBKR-bars/Yahoo-bars (Tier-B + Tier-C) including the 4-tier scrape ladder.

## Capabilities

### New Capabilities

(none — `research` capability already exists, R1 created `openspec/specs/research/spec.md` on archive.)

### Modified Capabilities

- `research`: adds requirements for Tier-A adapter behaviour — every adapter MUST implement `SourcePort`, MUST persist `tier='A'`, MUST populate `effective_from/to` from source PiT semantics, MUST be idempotent via `dedupe_key`, MUST honour each source's rate limits + auth requirements (UA header for EDGAR, API key for FRED/BLS/BEA).

## Impact

- **Affected code (R2-owned, write-allowed)**:
  - `apps/api/src/iguanatrader/contexts/research/sources/__init__.py` (NEW) — package marker; no shared registry edited (each adapter is referenced from R5's scheduler when the time comes; R2 only ships the classes).
  - `apps/api/src/iguanatrader/contexts/research/sources/base.py` (NEW) — `TierASourceAdapter(SourcePort)` abstract base with shared HTTP client + rate limiter + error mapper + `tier='A'` enforcement.
  - `apps/api/src/iguanatrader/contexts/research/sources/sec_edgar.py` (NEW) — `SECEdgarSource(TierASourceAdapter)` with submissions + XBRL clients + Form 4/10-K/10-Q/8-K/13F-HR fact builders.
  - `apps/api/src/iguanatrader/contexts/research/sources/fred.py` (NEW) — `FREDSource(TierASourceAdapter)` with ALFRED-aware vintage handling.
  - `apps/api/src/iguanatrader/contexts/research/sources/bls.py` (NEW) — `BLSSource(TierASourceAdapter)` with registered-tier API key requirement.
  - `apps/api/src/iguanatrader/contexts/research/sources/bea.py` (NEW) — `BEASource(TierASourceAdapter)` with NIPA revision-tracking via per-vintage facts.
  - `apps/api/tests/integration/test_edgar_ingestion.py` (NEW) — happy path + idempotency + provenance assertion (every fact has `tier='A'` + populated `effective_from`).
  - `apps/api/tests/integration/test_fred_ingestion.py` (NEW) — same shape, plus ALFRED vintage assertion (revision creates new fact, prior fact's `recorded_to` updated via `supersede_fact`).
  - `apps/api/tests/unit/contexts/research/sources/test_bls_adapter.py`, `test_bea_adapter.py` (NEW) — unit tests with pytest-httpx mocking.
  - `apps/api/tests/property/test_dedupe_key_uniqueness.py` (NEW) — Hypothesis-driven property test asserting no two distinct source payloads collide on `dedupe_key`.
  - `apps/api/tests/fixtures/vcr/{edgar_aapl_form4,edgar_aapl_10k,fred_cpi}.yaml` (NEW) — committed VCR cassettes for deterministic CI.
- **Affected code (R1-owned, read-only consumed)**:
  - `iguanatrader.contexts.research.ports.SourcePort` + `ResearchFactDraft` — adapter contract.
  - `iguanatrader.contexts.research.repository.ResearchRepository.insert_fact(...)` — provenance-validating insert with hybrid-payload dispatch.
  - `iguanatrader.contexts.research.repository.ResearchRepository.supersede_fact(...)` — narrow `recorded_to` update for ALFRED/BEA revisions.
  - `iguanatrader.contexts.research.errors.MissingProvenanceError` — surfaces if an adapter forgets a provenance field (defence-in-depth backstop).
  - `iguanatrader.contexts.research.events.ResearchFactIngested` — emitted on every successful insert.
- **Affected code (slice-2-owned, read-only consumed)**:
  - `iguanatrader.shared.backoff.exponential_backoff` — canonical `[3, 6, 12, 24, 48]` sequence for retry on 5xx + transient network errors.
  - `iguanatrader.shared.time.utc_now` — every `recorded_from` timestamp.
  - `iguanatrader.shared.decimal_utils.Decimal` — money + ratio fields (no float per AGENTS.md §4).
- **Affected APIs**: none directly — adapters are background workers invoked by R5's scheduler. R5 will add a CLI command `iguanatrader research ingest <source> [--symbol <s>]` for manual smoke; R2 ships the adapter classes only.
- **Affected dependencies**: `httpx[http2]` (already in slice 1's `pyproject.toml`); `vcrpy` + `pytest-vcr` added under `[tool.poetry.group.dev.dependencies]` for cassette-based integration tests; `tenacity` (already present from slice 2's backoff helpers); no production deps added.
- **Affected configuration**: 4 new env vars per `secrets/.sops.yaml` schema — `SEC_EDGAR_USER_AGENT` (mandatory, format `"<company-name> <contact-email>"`), `FRED_API_KEY`, `BLS_API_KEY`, `BEA_API_KEY`. Fail-fast at adapter init if any missing (raises `ConfigError` from slice 2). Documented in `docs/getting-started.md` "Tier-A research keys" section (R2 appends).
- **Prerequisites**:
  - `research-bitemporal-schema` (R1, archived 2026-05-06) — provides `SourcePort`, `ResearchFactDraft`, `ResearchRepository`, all 7 research tables incl. `research_facts` + `research_sources` catalogue.
  - Transitively `shared-primitives` (slice 2) — `IguanaError`, `BaseRepository`, `time.utc_now`, backoff helpers.
  - Transitively `persistence-tenant-enforcement` (slice 3) — Alembic env + tenant + append-only listeners.
- **Capability coverage** (per `docs/openspec-slice.md` row R2): FR59 (SEC filings via official APIs with point-in-time filing-date semantics — Form 4/10-K/10-Q/8-K/13F-HR), FR60 (FRED + ALFRED + BLS + BEA macro indicators with vintage-aware PiT data — ALFRED preserves vintages, not revisions).
- **Out of scope** (explicit):
  - **Scraping** — no `requests-html`, no Playwright, no Camoufox. All four sources are official public APIs.
  - **Tier-B/C sources** — Finnhub, GDELT, OpenFDA, OpenInsider, Finviz, WGI, V-Dem, IBKR bars, Yahoo bars, OpenBB sidecar — all R3/R4.
  - **LLM synthesis / brief generation** — R5.
  - **Scheduler integration** — APScheduler routines that periodically invoke these adapters land in O2 (`orchestration-scheduler-routines`); R2 ships the adapter classes + a manual-invocation contract only.
  - **CLI command for manual ingest** — first cut lands in R5 (`iguanatrader research ingest <source>`); R2 verifies via integration tests + Python REPL.
  - **`edgartools` library wrapper** — FR59 mentions `edgartools` as a candidate; R2 evaluates and EITHER uses it (if license + footprint acceptable; current read: Apache-2.0, OK) OR rolls a thin httpx client. Decision recorded in design.md D1.
  - **Hindsight bridge** — R6.
  - **Filesystem cache directory provisioning** — R2 IS the first writer; provisions `data/research_cache/<source_id>/<yyyy-mm>/` lazily via `mkdir(parents=True, exist_ok=True)` in the repository (already implemented in R1).
