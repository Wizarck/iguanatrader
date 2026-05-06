## Context

R2 lands the four Tier-A native point-in-time source adapters that feed the bitemporal `research_facts` table. State at R2 start:

- Slice R1 `research-bitemporal-schema` ✅ (archived 2026-05-06) — 7 research tables; `SourcePort` Protocol; `ResearchFactDraft` dataclass with `with_payload(bytes)` storage-tier dispatch; `ResearchRepository.insert_fact(draft)` with provenance enforcement + hybrid-payload write + driver-error lifting; `ResearchRepository.supersede_fact(old_id, at)` for the narrow `recorded_to` UPDATE that the L2 trigger permits; `MissingProvenanceError` defence-in-depth backstop.
- Slice 2 `shared-primitives` ✅ — `httpx`-based HTTP primitives, `exponential_backoff([3,6,12,24,48])`, `Decimal` money type, `IguanaError` hierarchy, structlog config.
- Wave 3 parallel siblings (R3/R4/R5) consume the same `SourcePort` contract; R2 must NOT touch shared infra (no edits to `shared/errors.py`, `routes/__init__.py`, `cli/main.py`, etc.) per the slice-5 anti-collision contract — each adapter is a new file under `contexts/research/sources/`.

The challenge is **API-correctness + idempotency, not architecture**. Each of the four sources has a different rate-limit contract, a different auth requirement, and a different point-in-time semantic — getting any of these wrong silently corrupts the bitemporal corpus that R5 depends on. EDGAR rejects requests without a `User-Agent` header containing a contact email; FRED's vintage-aware mode (ALFRED) requires a specific `realtime_start`/`realtime_end` parameter pair; BLS's free unregistered tier is too thin for production use; BEA returns multiple revisions for the same quarter and each must land as a separate fact, not an overwrite. The adapter base class concentrates these concerns so each concrete adapter only encodes its source-specific endpoints + parsing.

The R1 `ResearchRepository.insert_fact(draft)` already handles provenance + hybrid payload + filesystem write; R2 produces drafts and feeds them in. R2 owns the source-side intelligence: rate-limit governance, dedupe, and the PiT timestamp mapping. The repository is the boundary; below it R1's enforcement holds; above it R2 produces well-formed drafts.

## Goals / Non-Goals

**Goals:**
- Land four working Tier-A adapters (EDGAR, FRED, BLS, BEA) implementing `SourcePort` so R5's scheduler can invoke them on a cadence to populate `research_facts`.
- Encode each source's PiT semantics correctly into `effective_from` (when the fact is true in the world) and `recorded_from` (when iguanatrader observed it), with revision tracking via `supersede_fact` for ALFRED + BEA.
- Make every adapter idempotent at the source layer via `dedupe_key`: re-running an adapter on the same window produces zero new rows.
- Honour each source's published rate limits — no source is blacklisted during R2 development or CI.
- Ship a `TierASourceAdapter` base class so R3/R4 author Tier-B/C adapters with a stable interface (R3 will subclass `TierBSourceAdapter` with snapshot semantics; the L1 abstraction lives in R3 — R2 ships only the Tier-A specialisation).
- Defer all scheduling, CLI surface, and LLM synthesis — adapters are pure functions of `(symbol_or_series, since) → list[ResearchFactDraft]`.

**Non-Goals:**
- No scheduler / APScheduler integration — O2 owns that.
- No CLI surface — first cut in R5 (`iguanatrader research ingest <source>`).
- No web routes / SSE — adapters are background workers.
- No Tier-B/C adapters (Finnhub, GDELT, OpenFDA, OpenInsider, Finviz, WGI, V-Dem, IBKR-bars, Yahoo-bars) — R3/R4.
- No LLM-driven extraction (e.g., reading 10-K MD&A sections via Claude) — R2 captures the structured XBRL + raw filing metadata; semantic extraction is R5.
- No backfill scripts — re-running each adapter from `since=None` walks the source's historical surface; R5 will surface a "backfill window" CLI as needed.
- No new shared-kernel dependencies — `httpx`, `tenacity`, `structlog` already present.

## Decisions

### D1. Concrete adapters use thin `httpx`-based clients, NOT `edgartools` / `fredapi` / `bls-api-py` libraries

**Decision**: each adapter is a hand-rolled `httpx.AsyncClient` consumer with explicit URL builders, response parsers, and error mappers. No third-party SDK wrappers.

**Alternatives considered**:
- **`edgartools`** (Apache-2.0, ~MIT-equivalent for SEC filings) — comprehensive, well-maintained, but pulls in `pandas` + `pyrate-limiter` + a heavy XBRL parser as transitive deps; the SEC submissions JSON API + the XBRL company-facts API are both directly callable in ~200 LOC of httpx code; the library's surface is broader than R2 needs (it does form-by-form parsing + filing-text extraction; we only need filing metadata + structured XBRL facts).
- **`fredapi`** (BSD) — thin wrapper around the FRED API, fine, but doesn't expose ALFRED vintage semantics first-class; we'd be re-rolling the vintage logic anyway.
- **`bls-api-py`** + community BEA wrappers — abandoned / single-author; not appropriate for production.

**Rationale**: each official API is small enough that a thin httpx client is faster to read, audit (license-boundary CI cares about transitive deps), and adapt to the precise `ResearchFactDraft` shape than wrapping a library that introduces its own data model. The four adapters together come in under 1500 LOC. If a future v2 needs richer extraction (e.g., XBRL footnotes, BLS news releases), a library can be adopted then.

### D2. Each adapter inherits from `TierASourceAdapter(SourcePort)` — shared HTTP, retry, rate-limit, dedupe, structlog

**Decision**: a single abstract base class in `sources/base.py` provides:
- `_client: httpx.AsyncClient` lazily constructed with `User-Agent` defaulting to `f"iguanatrader/{__version__} contact:{ops_email}"` (overridden for EDGAR with the env-var value).
- `_rate_limiter: TokenBucket` initialised from a class attribute `rate_limit_per_second: float` (overridden per source: EDGAR=10.0, FRED=2.0, BLS=0.0058 (500/day), BEA=1.66 (100/min)).
- `async def _request(method, url, **kwargs) -> httpx.Response` wrapping `_rate_limiter.acquire()` + `tenacity.retry` with `exponential_backoff([3,6,12,24,48])` on 5xx + connection errors. 4xx (excl. 429) are permanent skip — adapter logs `research.<source>.permanent_skip` and continues; 429 honours `Retry-After` header per source guidance.
- `_emit(draft: ResearchFactDraft) -> None` — calls `repository.insert_fact(draft)`, catches `IntegrityError` from `dedupe_key` unique violation → logs `research.<source>.skipped_duplicate` and continues (no re-raise; idempotent).
- `_make_draft(...)` helper that fills in `tier='A'`, `retrieval_method='api'`, `retrieved_at=time.utc_now()`, `source_url`, `source_id` deterministically.
- Subclasses implement `async def fetch(symbol, since) -> AsyncIterable[ResearchFactDraft]` (or a series-based variant for FRED/BLS/BEA which take `series_id`).

**Alternatives considered**:
- **No base class — each adapter is independent**: trades 200 LOC of base class for 800 LOC of duplication across four adapters; rate-limit + retry semantics drift; CI cannot share a single rate-limit invariant test. Rejected.
- **Mixin instead of ABC**: works in Python but loses the `Protocol` runtime check; ABC + `@abstractmethod` makes "did you forget `fetch`?" surface at instantiation. Marginal preference for ABC.

**Rationale**: the four adapters share 80% of their plumbing. Concentrating in a base class keeps each concrete adapter a < 300-LOC focus on the source-specific endpoints + parsing.

### D3. SEC EDGAR — submissions API for filing metadata, XBRL company-facts API for structured numbers, raw filing fetch for ≥16KB payloads

**Decision**: EDGAR adapter exposes `fetch(symbol, since)` that:
1. Resolves CIK from ticker via the company-tickers JSON (`https://www.sec.gov/files/company_tickers.json`) — cached in-memory for the adapter lifetime.
2. Calls `https://data.sec.gov/submissions/CIK<10-digit-cik>.json` to get the recent-filings list (last 1000 filings; rolls through `files[]` array for older).
3. For each filing whose `filingDate >= since`, builds a `ResearchFactDraft` with:
   - `fact_kind = "sec_filing.<form_type>"` (e.g., `sec_filing.10-K`, `sec_filing.form_4`).
   - `effective_from = filingDate` (T00:00:00Z UTC) — the day the filing became public.
   - `effective_to = NULL` (filings are never superseded; an amendment is a new filing with `form_type` ending in `/A`).
   - `recorded_from = utc_now()`, `recorded_to = NULL`.
   - `value_jsonb = {accession_number, form_type, period_of_report, primary_document, primary_doc_description, file_number, items}`.
   - `source_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_document}"`.
   - `dedupe_key = f"sec_edgar:{accession_number}"`.
4. For 10-K and 10-Q only: also fetches `https://data.sec.gov/api/xbrl/companyfacts/CIK<cik>.json` (XBRL structured data) and emits one draft per `(taxonomy, concept, fiscal_period)` tuple newer than `since` with `fact_kind = "sec_xbrl.<concept>"`, `value_numeric = <reported value>`, `dedupe_key = f"sec_edgar:xbrl:{cik}:{concept}:{end_date}:{form_type}"`.
5. Form 4 insider-transaction parsing: fetches the filing's primary XML doc, extracts `<transactionAmounts>` + `<transactionPricePerShare>` per non-derivative transaction, emits one draft per transaction with `fact_kind = "sec_form4.transaction"`, `value_jsonb = {reporting_owner, transaction_date, shares, price, post_transaction_shares}`, `effective_from = transaction_date` (NOT filing_date — Form 4 reports a past transaction).

**Rate limit**: SEC publishes 10 req/sec global per IP. Adapter sets `rate_limit_per_second = 10.0` (with 100 ms slack to stay under). On 429: respect `Retry-After` (SEC issues 600s temporary blocks for sustained violations — that is a hard fail, log + skip).

**User-Agent**: SEC's [Fair Access policy](https://www.sec.gov/os/accessing-edgar-data) mandates a `User-Agent` header with company name + contact email. Missing UA → 403 with HTML body. Adapter reads `SEC_EDGAR_USER_AGENT` from env at init; raises `ConfigError` if absent or doesn't match regex `^.+ .+@.+\..+$`. Document in `docs/getting-started.md`.

**Alternatives considered**:
- **Use `edgartools.Company().get_filings()`** — see D1.
- **Skip XBRL, only filing metadata** — loses structured fundamentals (revenue, net income, EPS) which are exactly the inputs CANSLIM + Magic Formula need. Rejected.
- **Fetch full filing HTML/PDF text** — payloads in the multi-MB range; R2 ships only structured metadata + XBRL numbers; full-text retrieval lands when a methodology requires it (not in MVP).

### D4. FRED — ALFRED-aware vintage handling, revisions land as new facts via `supersede_fact`

**Decision**: FRED adapter exposes `fetch_series(series_id, since)` (R5 will register the relevant series IDs per methodology — R2 ships the mechanism, not the universe). Process:
1. Calls `https://api.stlouisfed.org/fred/series/observations?series_id=<id>&realtime_start=<since-iso>&realtime_end=9999-12-31&api_key=<key>&file_type=json` — ALFRED mode preserves all vintages.
2. For each observation in the response, builds a draft with:
   - `fact_kind = f"fred.{series_id}"`.
   - `effective_from = observation.date` (the period the observation refers to — e.g., 2024-04-01 for April CPI).
   - `effective_to = NULL` if `observation.realtime_end == "9999-12-31"`, else `observation.realtime_end`.
   - `recorded_from = observation.realtime_start` (the date FRED published this vintage).
   - `value_numeric = Decimal(observation.value)` if `observation.value != "."` (FRED uses `.` for missing data); else skip.
   - `dedupe_key = f"fred:{series_id}:{observation.date}:{observation.realtime_start}"`.
3. Revision detection: if a draft is built whose `(series_id, observation.date)` matches an existing fact with `recorded_to IS NULL`, the adapter:
   a. Calls `repository.supersede_fact(old_id, at=observation.realtime_start)` to close the prior vintage.
   b. Inserts the new draft as a fresh fact.
   This is the canonical bitemporal revision flow per R1 design D1.

**Rate limit**: FRED's documented limit is 120 req/min — adapter sets `rate_limit_per_second = 2.0`. Free API key required (registration: research.stlouisfed.org/docs/api/api_key.html).

**Alternatives considered**:
- **Non-ALFRED mode** (current-vintage only): loses the bitemporal revision history that is the entire point of R1's `recorded_from/to` axis. Rejected.
- **Pull all observations for a series in one shot, then filter `since`**: simpler, but FRED's ALFRED responses can be large (CPI back to 1947 with all revisions ≈ 50000 rows ≈ 4 MB). Server-side filtering via `realtime_start` is cheaper.

### D5. BLS — registered tier required, release-date-aware PiT mapping

**Decision**: BLS adapter exposes `fetch_series(series_id, since)`. Process:
1. POSTs to `https://api.bls.gov/publicAPI/v2/timeseries/data/` with body `{"seriesid": [<id>], "startyear": <since.year>, "endyear": <current_year>, "registrationkey": <key>}`.
2. For each `Results.series[0].data[]` row, builds a draft:
   - `fact_kind = f"bls.{series_id}"`.
   - `effective_from = period_start` derived from `(year, period)` — for monthly series `period="M04"` → `2024-04-01T00:00:00Z`; for quarterly `Q01` → quarter start; for annual `A01` → year start.
   - `effective_to = period_end`.
   - `recorded_from = bls_release_date_for(series_id, year, period)` — looked up against the BLS release-calendar JSON (cached); falls back to `period_end + 1 month` if calendar lookup fails (BLS publishes release schedules ~6 months ahead per series).
   - `value_numeric = Decimal(row.value)`.
   - `dedupe_key = f"bls:{series_id}:{year}:{period}:{recorded_from.date()}"`.
3. BLS revisions are rare; when a row's value differs from a previously-inserted fact's `value_numeric`, the adapter applies the same supersede flow as D4.

**Rate limit**: registered tier = 500 queries/day, 50 series per query, 20 years per query. Adapter sets `rate_limit_per_second = 0.0058` (500/86400). API key required — fail-fast at init if `BLS_API_KEY` env var missing.

**BLS gotcha**: unregistered tier returns 200 with `status="REQUEST_NOT_PROCESSED"` in the JSON body when limits exceeded — adapter checks `response_body["status"]` (not just HTTP status) and raises `RateLimitedError` if not `"REQUEST_SUCCEEDED"`. Document in `docs/gotchas.md`.

### D6. BEA — NIPA revision tracking, every quarterly release lands as its own fact

**Decision**: BEA adapter exposes `fetch_dataset(dataset, table, frequency, year_range)` (e.g., `dataset="NIPA"`, `table="T10101"` for GDP, `frequency="Q"`). Process:
1. Calls `https://apps.bea.gov/api/data/?UserID=<key>&method=GetData&datasetname=NIPA&TableName=<table>&Frequency=<freq>&Year=<years>&ResultFormat=JSON`.
2. For each `Data[]` row, builds a draft:
   - `fact_kind = f"bea.{dataset}.{table}.{line_description}"`.
   - `effective_from = period_start` (e.g., Q1 2024 → 2024-01-01).
   - `effective_to = period_end` (e.g., Q1 2024 → 2024-03-31, inclusive end-of-quarter).
   - `recorded_from = parse_release_date(row.NoteRef or BEA_release_calendar)`. BEA's quarterly GDP gets advance (≈30 days post-quarter), second (≈60 days), third (≈90 days), and annual revisions; the release-date mapping is canonical via [BEA's release schedule](https://www.bea.gov/news/schedule).
   - `value_numeric = Decimal(row.DataValue)`.
   - `dedupe_key = f"bea:{dataset}:{table}:{frequency}:{period}:{recorded_from.date()}"`.
3. For comprehensive revisions (every 5 years BEA re-baselines NIPA), the adapter pulls the new vintage and supersedes ALL prior facts for affected `(table, period)` pairs — implemented as a batch `supersede_fact` loop in a single transaction.

**Rate limit**: BEA's [terms](https://apps.bea.gov/API/docs/index.htm) — 1000 req/min, 100 MB/day, 30 errors/min. Adapter sets `rate_limit_per_second = 1.66` (100/min, conservatively well below 1000/min). API key required (free, registration: apps.bea.gov/API/signup).

**BEA gotcha**: BEA returns numeric strings with embedded commas (`"23,456.7"`) — adapter strips commas before `Decimal(...)` parsing. Also returns `"…"` (ellipsis) for missing values; adapter skips these silently with structlog `research.bea.skipped_missing`.

### D7. Idempotency via `dedupe_key` + lazy unique-index resolution

**Decision**: each adapter computes a deterministic `dedupe_key` per draft (formats per D3-D6). On `repository.insert_fact(draft)`:
1. The repository (ALREADY shipped in R1 — but R2 extends with a 5-line dedupe lookup; this is the ONE narrow read-modify of R1's repository code, considered an additive extension via a new optional parameter `dedupe_key: str | None = None`) checks `SELECT 1 FROM research_facts WHERE dedupe_key = :key LIMIT 1` (uses an `idx_research_facts_dedupe_key` partial index added in R2's migration `0004_research_dedupe_index.py`).
2. If hit: returns existing fact, emits `research.<source>.skipped_duplicate`, no INSERT.
3. If miss: proceeds with R1's existing provenance + payload + insert path.

**Migration**: R2 ships `migrations/versions/0004_research_dedupe_index.py` adding a single column (`dedupe_key TEXT NULL`) + a partial unique index on `research_facts(tenant_id, dedupe_key) WHERE dedupe_key IS NOT NULL`. No data migration — existing rows (none, R1 just landed; R5 is the first heavy writer alongside R2) keep `dedupe_key=NULL` and the partial-index predicate excludes them.

**Alternatives considered**:
- **Adapter-side LRU cache only**: works for a single process within a single run, but two concurrent ingest jobs (e.g., scheduler invokes EDGAR for AAPL, manual CLI invokes EDGAR for AAPL) would both insert. Rejected — DB-level uniqueness is the canonical idempotency boundary.
- **Use `(source_id, value_jsonb hash)` instead of explicit `dedupe_key`**: hashing whole payloads is expensive + sensitive to FRED/BEA rounding differences across runs. Rejected.

**Rationale**: explicit `dedupe_key` is a one-line column addition + a partial index (cheap on SQLite, free on Postgres). The adapter encodes the source's natural primary key (accession_number for EDGAR, `(series, observation_date, vintage)` for FRED, etc.) which is also the right human-readable trace ID for debugging.

### D8. Failure handling: 4xx (excl. 429) = permanent skip + structlog + continue; 5xx + 429 + connection errors = exponential backoff per slice 2

**Decision**: the base class wraps `_request(...)` in `tenacity.retry(stop=stop_after_attempt(5), wait=wait_exponential_from_slice2)`. Retry triggers: `httpx.ConnectError`, `httpx.ReadTimeout`, `HTTPStatusError(5xx)`, `HTTPStatusError(429)`. Permanent skip: 4xx with status in {400, 401, 403, 404, 410, 422}. On permanent skip the adapter logs `research.<source>.permanent_skip` (with `status_code`, `url`, `cik_or_series_id`) and the `fetch(...)` iterator yields nothing for that item — the next iteration continues. After 5 retries on transient: log `research.<source>.gave_up` + raise `SourceUnavailableError(IguanaError, default_status=503)` so a calling scheduler can pause that adapter.

**Alternatives considered**:
- **Crash on first 4xx**: a single 404 for one delisted ticker would halt a daily ingest for the whole tenant. Rejected.
- **Retry 4xx too**: SEC's 403 (missing UA) would loop for 5 minutes before failing — caller has bad data, retrying doesn't help. Rejected.

## Risks / Trade-offs

- **[Risk] EDGAR's `User-Agent` requirement is silently enforced — missing UA returns HTML 403 not JSON** → an adapter run with default httpx UA gets HTML back, our JSON parser raises `ValueError`, structlog says "JSON decode failed". **Mitigation**: adapter init asserts `SEC_EDGAR_USER_AGENT` matches `^.+ .+@.+\..+$` regex; CI integration test runs against a VCR cassette captured with a valid UA + a separate unit test asserts the init-time validation rejects malformed UAs.
- **[Risk] BLS unregistered-tier silent rate-limit** — caller sees 200 OK with `status="REQUEST_NOT_PROCESSED"` in JSON body → adapter inserts zero rows silently. **Mitigation**: every BLS response body is checked for `status == "REQUEST_SUCCEEDED"`; non-success raises `RateLimitedError` with the BLS message. Init-time check that `BLS_API_KEY` is not empty.
- **[Risk] FRED ALFRED vintage parsing — `realtime_start` is the publication date but observations within the same vintage block share the same `realtime_start`** → adapter could double-emit if not careful. **Mitigation**: dedupe key includes `realtime_start` so even if a vintage block returns the same observation across two API calls, only one row is inserted.
- **[Risk] BEA quarterly revision flooding** — pulling NIPA T10101 from 1947 yields ~75 years × 4 quarters × 4 release vintages ≈ 1200 facts per series; bulk insert without batching can exceed SQLite's 1000-row default WAL checkpoint window. **Mitigation**: adapter inserts in batches of 200 per transaction with explicit `session.commit()`; structlog event `research.bea.batch_committed` per batch.
- **[Risk] Rate-limit token bucket coordination across multiple adapter instances** — if two scheduler tasks both invoke `SECEdgarSource()` in the same process, each has its own `_rate_limiter` and they'd jointly exceed 10 req/sec. **Mitigation**: token bucket lives at the class level (`SECEdgarSource._rate_limiter: ClassVar[TokenBucket]`), not per-instance, so all instances within one process share the budget. Cross-process coordination (multiple workers) is out of MVP — single-process scheduler for now. Documented as gotcha #44.
- **[Risk] VCR cassette PII / API-key leakage** — fixtures committed to the repo would include API keys in URL query strings. **Mitigation**: `vcr_config = {"filter_query_parameters": ["api_key", "registrationkey", "UserID"], "filter_headers": ["Authorization", "User-Agent"]}` configured in `conftest.py`; pre-commit gitleaks already scans cassette files. Manual review before first commit of cassettes.
- **[Trade-off] Hand-rolled httpx clients vs `edgartools` library** — D1 trades off ecosystem maturity for transitive-dep minimisation + license-boundary clarity. If a future R5 methodology needs richer XBRL extraction (e.g., footnote parsing), we may revisit.
- **[Trade-off] R2 narrowly modifies R1's `repository.insert_fact` to accept `dedupe_key: str | None = None`** — strictly speaking this is a cross-slice edit. **Mitigation**: it's purely additive (new optional keyword arg); R1's tests still pass; the slice-5 anti-collision contract permits additive changes to public APIs. Documented in `proposal.md` Impact + an explicit task. If reviewer pushback, the alternative is a `ResearchRepository.insert_fact_with_dedupe(...)` wrapper method co-located in `contexts/research/sources/base.py` that does the lookup before calling R1's untouched `insert_fact` — equivalent behaviour, zero R1 edits. R2 will go this route by default and only modify R1 if reviewers prefer.
- **[Trade-off] Release-date lookup for BLS/BEA depends on cached calendar JSON** — calendar JSON itself can change (BLS sometimes shifts release dates by a day). **Mitigation**: adapter fetches the calendar JSON daily (cached with TTL=24h); when a fact's `recorded_from` was estimated and the actual calendar later differs, R5's audit-trail render will surface the discrepancy. Not a correctness issue for MVP — the bitemporal `recorded_from` is "when iguanatrader observed", not "when BLS technically published".

## Migration Plan

R2 has no live deployment to migrate from. Deployment path:

1. Merge R2 to main after R1 is on main (R1 archived 2026-05-06; safe).
2. Migration `0004_research_dedupe_index.py` runs in CI's alembic-upgrade smoke; adds the partial index + nullable `dedupe_key` column. Reversible (`downgrade()` drops index + column).
3. CI fires the existing `openapi-types.yml` workflow — no OpenAPI surface changes (adapters are not routed), so the bot-commit is a no-op.
4. New env vars `SEC_EDGAR_USER_AGENT`, `FRED_API_KEY`, `BLS_API_KEY`, `BEA_API_KEY` are required for runtime; `secrets/dev.env.enc` template gets stub entries (committed encrypted; real values per developer). Adapter init raises `ConfigError` if missing — surfaced as fast-fail at scheduler startup once O2 wires them up.
5. R3/R4/R5 each branch from main and consume R2's adapters (R5) or land their own R3/R4 sources without conflict (each in `contexts/research/sources/<their-source>.py`).

Rollback = revert PR + alembic `downgrade -1` (drops the dedupe index + column; existing facts unaffected since `dedupe_key` is nullable). Adapter classes are pure-code deletes — no data to lose.

## Open Questions

- **Q**: Should the EDGAR adapter pre-emptively fetch full XBRL company-facts for every 10-K filing, or only on-demand when R5 requests a fundamentals brief? **Tentative answer**: pre-fetch for 10-K + 10-Q (high signal; bounded data — a single company-facts JSON is ~200KB-2MB; falls in the filesystem-tier per R1 D3); skip for 8-K (event-driven, no XBRL). Document in `docs/gotchas.md` once the corpus settles.
- **Q**: Does FRED's `realtime_start` semantics treat US Eastern publication time correctly? **Tentative answer**: FRED publishes in ET; adapter parses `realtime_start` as a date (not a datetime) and treats it as `T00:00:00 ET` then converts to UTC. Document in adapter docstring; cross-check first ingestion of CPI vs the FRED website's known release date.
- **Q**: Should BLS/BEA series IDs be hard-coded in the adapter or live in a config file? **Tentative answer**: not in R2 — adapters take `series_id` as a parameter; R5 will introduce `config/research_universes.yaml` mapping methodology → series IDs (e.g., CANSLIM → BLS unemployment + FRED yield curve). R2 ships the mechanism only.
- **Q**: VCR cassettes are committed; how often do we re-record? **Tentative answer**: cassettes are regenerated only when the source API contract changes (rare); CI uses cassettes for every test run; `make record-cassettes` regenerates against live APIs (requires real keys; not run in CI). Document in `apps/api/tests/integration/README.md`.
