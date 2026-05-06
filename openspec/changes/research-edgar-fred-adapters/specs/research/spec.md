## ADDED Requirements

### Requirement: Tier-A source adapters MUST implement `SourcePort` and persist `tier='A'` on every fact

The system SHALL provide four Tier-A native point-in-time source adapters — `SECEdgarSource`, `FREDSource`, `BLSSource`, `BEASource` — each inheriting from `TierASourceAdapter` (which itself satisfies the `SourcePort` Protocol from R1). Every `ResearchFactDraft` emitted by any of the four adapters SHALL carry `tier = 'A'` and `retrieval_method = 'api'`. The base class SHALL set these fields in its `_make_draft(...)` helper so concrete adapters cannot accidentally omit them.

#### Scenario: SEC EDGAR adapter emits drafts with tier='A'

- **GIVEN** a `SECEdgarSource()` configured with a valid `SEC_EDGAR_USER_AGENT`
- **WHEN** `await source.fetch(symbol="AAPL", since=datetime(2024, 1, 1, tzinfo=UTC))` is iterated
- **THEN** every yielded `ResearchFactDraft` has `tier == "A"`
- **AND** every draft has `retrieval_method == "api"`
- **AND** every draft has `source_id == "sec_edgar"`

#### Scenario: FRED, BLS, BEA adapters all emit tier='A'

- **GIVEN** a `FREDSource()`, `BLSSource()`, `BEASource()` each correctly initialised
- **WHEN** each is iterated for a known series
- **THEN** every emitted draft has `tier == "A"` and `retrieval_method == "api"`
- **AND** the `source_id` field equals `"fred"`, `"bls"`, `"bea"` respectively

### Requirement: Tier-A adapters MUST populate `effective_from/to` from the source's native point-in-time semantics

Each adapter SHALL map source-specific timestamps to `ResearchFactDraft.effective_from` and `effective_to` according to the source's documented PiT semantics. SEC EDGAR filings: `effective_from = filingDate at 00:00:00Z`, `effective_to = NULL`. SEC EDGAR Form 4 transactions: `effective_from = transaction_date` (NOT filingDate), `effective_to = NULL`. FRED observations: `effective_from = observation.date`, `effective_to = observation.realtime_end if != "9999-12-31" else NULL`. BLS observations: `effective_from = period_start`, `effective_to = period_end`. BEA NIPA observations: `effective_from = period_start`, `effective_to = period_end` (inclusive end-of-period). The `recorded_from` field SHALL reflect when iguanatrader observed the fact: for SEC `recorded_from = utc_now()`; for FRED `recorded_from = observation.realtime_start` (ALFRED vintage publication); for BLS `recorded_from` = release-calendar lookup; for BEA `recorded_from` = release schedule lookup or `NoteRef`-derived date.

#### Scenario: SEC 10-K filing carries filingDate as effective_from

- **GIVEN** an EDGAR submissions API response with a 10-K filing with `filingDate = "2024-11-01"` and accession `0000320193-24-000123`
- **WHEN** the adapter processes the filing
- **THEN** the emitted draft's `effective_from` equals `2024-11-01T00:00:00Z`
- **AND** `effective_to` equals `NULL`
- **AND** `fact_kind` equals `"sec_filing.10-K"`

#### Scenario: SEC Form 4 transaction uses transaction_date, not filing_date

- **GIVEN** a Form 4 filing on 2024-11-05 reporting a transaction with `transactionDate = "2024-11-01"`
- **WHEN** the adapter parses the Form 4 XML
- **THEN** the emitted draft's `effective_from` equals `2024-11-01T00:00:00Z` (the transaction date)
- **AND** the draft's `value_jsonb` includes `{"reporting_owner": ..., "transaction_date": "2024-11-01", "shares": ..., "price": ...}`
- **AND** `recorded_from` equals approximately `utc_now()` at adapter run time

#### Scenario: FRED ALFRED revision creates a new fact with new recorded_from

- **GIVEN** a FRED CPI observation for `2024-04-01` initially published `2024-05-15` (`realtime_start = "2024-05-15"`)
- **AND** a revised observation published `2024-06-15` (`realtime_start = "2024-06-15"`) for the same observation date
- **WHEN** the adapter ingests both vintages
- **THEN** two `research_facts` rows exist for `(symbol, fact_kind="fred.CPIAUCSL", effective_from=2024-04-01)`
- **AND** the first row's `recorded_from = 2024-05-15`, `recorded_to = 2024-06-15` (set via `supersede_fact`)
- **AND** the second row's `recorded_from = 2024-06-15`, `recorded_to = NULL`
- **AND** `as_of(symbol="USD-CPI", at="2024-05-20")` returns the first row; `as_of(at="2024-06-20")` returns the second

### Requirement: Tier-A adapters MUST be idempotent via `dedupe_key`

Each emitted `ResearchFactDraft` SHALL carry a deterministic `dedupe_key` constructed from source-specific natural keys: SEC EDGAR filings → `f"sec_edgar:{accession_number}"`; SEC EDGAR XBRL facts → `f"sec_edgar:xbrl:{cik}:{concept}:{end_date}:{form_type}"`; SEC Form 4 transactions → `f"sec_edgar:form4:{accession_number}:{transaction_index}"`; FRED observations → `f"fred:{series_id}:{observation_date}:{realtime_start}"`; BLS observations → `f"bls:{series_id}:{year}:{period}:{recorded_from_date}"`; BEA observations → `f"bea:{dataset}:{table}:{frequency}:{period}:{recorded_from_date}"`. The repository SHALL enforce uniqueness via a partial unique index on `(tenant_id, dedupe_key) WHERE dedupe_key IS NOT NULL` (added in migration `0004_research_dedupe_index.py`). Re-running an adapter on the same window SHALL insert zero new rows and SHALL emit `research.<source>.skipped_duplicate` for each pre-existing key.

#### Scenario: Re-running EDGAR adapter on same window is a no-op

- **GIVEN** `SECEdgarSource()` has run for `symbol="AAPL"`, `since=2024-01-01` and inserted N facts
- **WHEN** the same adapter is invoked a second time with identical parameters
- **THEN** zero new rows are inserted into `research_facts`
- **AND** the adapter emits N `research.sec_edgar.skipped_duplicate` structlog events
- **AND** the adapter completes without raising

#### Scenario: Two concurrent EDGAR ingests for the same accession do not double-insert

- **GIVEN** two coroutine tasks both invoke `SECEdgarSource().fetch("AAPL", since)` concurrently and both produce a draft for accession `0000320193-24-000123`
- **WHEN** both call `repository.insert_fact(draft)` (or the dedupe wrapper) at the same time
- **THEN** exactly one row is inserted (unique-index violation on the second is caught and converted to skip)
- **AND** the second task emits `research.sec_edgar.skipped_duplicate` with the duplicate `dedupe_key`

#### Scenario: FRED dedupe key includes vintage so revisions still insert

- **GIVEN** a FRED observation for `2024-04-01` with `realtime_start = "2024-05-15"` already persisted (`dedupe_key = "fred:CPIAUCSL:2024-04-01:2024-05-15"`)
- **WHEN** the adapter encounters the revision with `realtime_start = "2024-06-15"`
- **THEN** the new draft has `dedupe_key = "fred:CPIAUCSL:2024-04-01:2024-06-15"` (different)
- **AND** `repository.insert_fact(...)` proceeds with the supersede + insert flow (revision is NOT skipped)

### Requirement: Tier-A adapters MUST honour each source's published rate limits and authentication contract

Each adapter SHALL throttle outgoing requests to stay within the source's documented rate limit: SEC EDGAR ≤10 req/sec (token bucket initialised at 10.0 req/s with 100ms slack); FRED ≤120 req/min (≈2.0 req/s); BLS registered tier ≤500 req/day (≈0.0058 req/s); BEA ≤100 req/min (≈1.66 req/s) with secondary cap of 100 MB/day enforced by structlog-tracked response-bytes counter that raises `RateLimitedError` at threshold. Each adapter SHALL fail-fast at construction if the required auth credential is missing: SEC EDGAR requires `SEC_EDGAR_USER_AGENT` env var matching `^.+ .+@.+\..+$` (mandatory header per SEC Fair Access policy); FRED requires `FRED_API_KEY`; BLS requires `BLS_API_KEY` (registered tier); BEA requires `BEA_API_KEY` (UserID). Missing or malformed credentials SHALL raise `ConfigError(IguanaError)` at adapter `__init__` (not on first request) so misconfiguration surfaces at scheduler startup.

#### Scenario: SEC EDGAR adapter rejects missing User-Agent at init

- **GIVEN** the environment has no `SEC_EDGAR_USER_AGENT` variable set
- **WHEN** `SECEdgarSource()` is constructed
- **THEN** a `ConfigError` is raised
- **AND** the error message references the SEC Fair Access policy
- **AND** no HTTP request is made

#### Scenario: SEC EDGAR adapter rejects malformed User-Agent at init

- **GIVEN** `SEC_EDGAR_USER_AGENT="iguanatrader"` (no email)
- **WHEN** `SECEdgarSource()` is constructed
- **THEN** a `ConfigError` is raised
- **AND** the error message references the required format `"<company-name> <contact-email>"`

#### Scenario: FRED, BLS, BEA adapters reject missing API keys at init

- **GIVEN** any of `FRED_API_KEY`, `BLS_API_KEY`, `BEA_API_KEY` is unset
- **WHEN** the corresponding adapter (`FREDSource`, `BLSSource`, `BEASource`) is constructed
- **THEN** a `ConfigError` is raised at `__init__`
- **AND** no HTTP request is made
- **AND** the error names the missing env var

#### Scenario: BLS adapter rejects unregistered-tier responses

- **GIVEN** a BLS response with HTTP 200 + body `{"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold exceeded"]}`
- **WHEN** the adapter processes the response
- **THEN** the adapter raises `RateLimitedError(IguanaError, default_status=429)`
- **AND** the error detail includes the BLS-provided message
- **AND** zero `ResearchFactDraft` rows are emitted

#### Scenario: SEC EDGAR adapter token bucket throttles to ≤10 req/sec

- **GIVEN** `SECEdgarSource()` initialised
- **WHEN** the adapter is asked to fetch 100 filings in tight succession
- **THEN** the elapsed wall-clock time for the 100 requests is ≥10.0 seconds (10 req/s steady-state)
- **AND** no 429 responses are received from SEC

### Requirement: Tier-A adapters MUST handle transient failures with the canonical exponential backoff and skip permanent 4xx errors

The base `TierASourceAdapter._request(...)` method SHALL wrap each HTTP call with `tenacity.retry` configured to use the canonical `exponential_backoff([3, 6, 12, 24, 48])` sequence from `iguanatrader.shared.backoff`. Retry SHALL trigger on `httpx.ConnectError`, `httpx.ReadTimeout`, HTTP 5xx, and HTTP 429 (with `Retry-After` honoured when present). After 5 retries on transient failures the adapter SHALL log `research.<source>.gave_up` and raise `SourceUnavailableError(IguanaError, default_status=503)`. Permanent 4xx errors (400, 401, 403, 404, 410, 422) SHALL NOT be retried; the adapter SHALL log `research.<source>.permanent_skip` with the status code + URL + identifier and continue to the next item — `fetch(...)` yields nothing for the failed item but does not raise.

#### Scenario: 5xx triggers exponential backoff with [3,6,12,24,48] sequence

- **GIVEN** the FRED API is returning 503 for the next 4 requests, then 200
- **WHEN** the adapter calls `_request("GET", url)`
- **THEN** the adapter retries 4 times with sleep durations 3, 6, 12, 24 seconds (within 100ms tolerance)
- **AND** the 5th attempt succeeds and returns the response
- **AND** structlog event `research.fred.retry` is emitted on each retry with `attempt` and `wait_seconds`

#### Scenario: 404 on a single ticker yields nothing for that ticker but does not stop the adapter

- **GIVEN** an EDGAR ingest for symbols `["AAPL", "INVALID-TICKER", "MSFT"]`
- **AND** EDGAR returns 404 for `INVALID-TICKER`'s CIK lookup
- **WHEN** the adapter iterates the symbol list
- **THEN** facts for AAPL and MSFT are emitted normally
- **AND** no facts are emitted for `INVALID-TICKER`
- **AND** structlog event `research.sec_edgar.permanent_skip` is emitted with `status_code=404` and `symbol="INVALID-TICKER"`
- **AND** no exception propagates out of `fetch(...)`

#### Scenario: Sustained 5xx exhausts retries and surfaces SourceUnavailableError

- **GIVEN** the BLS API is returning 503 indefinitely
- **WHEN** the adapter is invoked
- **THEN** after 5 retry attempts (waits 3+6+12+24+48 ≈ 93 seconds) the adapter raises `SourceUnavailableError`
- **AND** structlog event `research.bls.gave_up` is emitted with `attempts=5` and the final error message
- **AND** the exception's `default_status` is 503 so a calling scheduler can pause the adapter

### Requirement: Tier-A adapters MUST NOT bypass the repository's provenance enforcement

Each adapter SHALL persist facts only via `ResearchRepository.insert_fact(draft)` (or the slice-local dedupe wrapper that delegates to it). Adapters SHALL NOT emit raw SQL `INSERT INTO research_facts` or use `session.execute(insert(ResearchFact).values(...))` — both bypass the repository's `MissingProvenanceError` lifting + the hybrid-payload dispatch. Every emitted draft SHALL populate `source_id`, `source_url`, `retrieval_method='api'`, `retrieved_at`. The base class `_make_draft(...)` SHALL set `retrieval_method='api'` + `retrieved_at=time.utc_now()` automatically; concrete adapters provide `source_id` (class attribute) and `source_url` (computed per fact).

#### Scenario: Adapter omitting source_url surfaces MissingProvenanceError

- **GIVEN** a hand-crafted draft with `source_url = ""` (empty string)
- **WHEN** the adapter (incorrectly) calls `repository.insert_fact(draft)`
- **THEN** the repository's CHECK on `source_url != ''` rejects via `IntegrityError`
- **AND** the repository lifts to `MissingProvenanceError`
- **AND** the adapter does NOT swallow the error (it propagates to the caller)

#### Scenario: All adapter-emitted drafts pass provenance validation in unit tests

- **GIVEN** the adapter test fixtures for SEC EDGAR, FRED, BLS, BEA
- **WHEN** every adapter is iterated against its VCR cassette (or pytest-httpx mock)
- **THEN** every emitted draft has non-empty `source_id`, `source_url`, `retrieval_method == "api"`, and `retrieved_at` within ±60s of test start
- **AND** every draft is successfully persisted via `repository.insert_fact(draft)` without `MissingProvenanceError`

### Requirement: Adapter test cassettes MUST scrub API keys and PII

VCR cassettes committed under `apps/api/tests/fixtures/vcr/` SHALL NOT contain any of: `api_key`, `registrationkey`, `UserID` query parameters; `Authorization` headers; the `User-Agent` header value (replaced with placeholder). The conftest's `vcr_config` SHALL configure `filter_query_parameters` and `filter_headers` accordingly. CI's gitleaks pre-commit SHALL scan cassette files in addition to source files.

#### Scenario: Committed cassette has scrubbed query parameters

- **GIVEN** a VCR cassette `tests/fixtures/vcr/fred_cpi.yaml`
- **WHEN** the cassette file is grep'd for the literal string `api_key=`
- **THEN** the only matches contain `api_key=DUMMY` or `api_key=[FILTERED]` (never a real key)
- **AND** running `gitleaks` against the cassette returns no findings

#### Scenario: Committed cassette has scrubbed headers

- **GIVEN** the same cassette
- **WHEN** the YAML is parsed
- **THEN** the `User-Agent` request header value is the literal placeholder `"iguanatrader/dev contact:dev@example.com"` (not the developer's real UA)
- **AND** the `Authorization` header is absent or set to `"[FILTERED]"`
