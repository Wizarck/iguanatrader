## ADDED Requirements

### Requirement: System ships nine Tier-B and Tier-C source adapters implementing `SourcePort`

The system SHALL ship nine concrete `SourcePort` implementations under `apps/api/src/iguanatrader/contexts/research/sources/` covering: Finnhub news + sentiment + earnings + recommendations (`finnhub.py`); GDELT 2.0 DOC API + BigQuery events (`gdelt.py`); OpenFDA drug events / labels / enforcement (`openfda.py`); OpenInsider aggregated insider screens via Tier-2 scrape (`openinsider.py`); Finviz analyst-rating + valuation screener via Tier-2 scrape (`finviz_scrape.py`); World Bank WGI governance indicators (`wgi_world_bank.py`); V-Dem democracy index bulk dataset (`vdem.py`); IBKR historical bars via `ib_async` (`ibkr_bars.py`); Yahoo Finance bars fallback (`yahoo_bars_fallback.py`); plus Yahoo `yfinance.sustainability` ESG single-source adapter (`yfinance_sustainability.py`). Each adapter SHALL persist facts via R1's `ResearchRepository.insert_fact(draft)` with full provenance (`source_id`, `source_url`, `retrieval_method ∈ {api, scrape, manual, llm}`, `retrieved_at`). Each adapter SHALL set `effective_from` to the source's published-at timestamp (or earliest applicable point-in-time) and `recorded_from` to `iguanatrader.shared.time.utc_now()`.

#### Scenario: Finnhub adapter ingests news headlines with full provenance

- **GIVEN** a `FinnhubSource()` instance and a mock `httpx.AsyncClient.get` returning a canned `/news?symbol=AAPL&from=...&to=...` response with 3 articles
- **WHEN** `FinnhubSource().fetch(symbol="AAPL", since=T0)` is iterated and each draft is passed to `repo.insert_fact(draft)`
- **THEN** 3 rows are persisted in `research_facts`
- **AND** every row carries `source_id="finnhub"`, `retrieval_method="api"`, `source_url` containing the full Finnhub query string, `retrieved_at` equal to `utc_now()` at fetch time
- **AND** `fact_kind="news.headline"` for each row
- **AND** `effective_from` equals the article's `datetime` field; `recorded_from` equals `retrieved_at`
- **AND** the `research_sources` row for `id="finnhub"` has `pit_class='B'` (snapshot)

#### Scenario: GDELT BigQuery dry_run aborts when monthly bytes scanned would exceed 90 GB

- **GIVEN** `research_sources.metadata.bigquery_bytes_scanned_mtd = 80 * 1024**3` and a candidate query whose dry_run estimate is `15 * 1024**3` bytes
- **WHEN** `GDELTSource().fetch(...)` invokes the BigQuery historical-events path
- **THEN** the adapter detects estimated_total_bytes (80 + 15 GB > 90 GB cap)
- **AND** raises `SourceUnavailableError(source_id="gdelt", cause="monthly_budget_exceeded")` before issuing the actual query
- **AND** emits structlog `research.gdelt.quota_alert` with `mtd_gb=80`, `estimate_gb=15`, `cap_gb=90`

#### Scenario: IBKR bars adapter respects HMDS 60-requests-per-10-minutes pacing

- **GIVEN** an `IBKRBarsSource()` instance and 65 sequential `fetch(symbol_i, since)` calls within 5 minutes
- **WHEN** the adapter awaits the per-instance token bucket before each `reqHistoricalDataAsync` call
- **THEN** the first 60 calls succeed within the 5-minute window
- **AND** the 61st call awaits until a token refills (1 token per 10 seconds, so ~10 seconds wait)
- **AND** if IBKR responds with an HMDS pacing-violation error, the adapter sleeps 600s and emits structlog `research.ibkr_bars.pacing_violation`

### Requirement: System ships a 4-tier scrape ladder with escalation, capping, and cost gating

The system SHALL provide `apps/api/src/iguanatrader/contexts/research/scraping/ladder.py` exposing `class ScrapeLadder` whose `fetch(url, *, default_tier, allowed_tiers, tenant_max, requires_robots_check, tenant_id)` orchestrates four tiers: Tier 1 plain HTTPS via httpx (`tier1_webfetch.py`); Tier 2 Chromium via Playwright (`tier2_playwright.py`); Tier 3 Firefox stealth via Camoufox MCP (`tier3_camoufox.py`); Tier 4 Camoufox + 2Captcha solver (`tier4_captcha.py`). Escalation rules: `ScrapeBlockedError` (HTTP 403, challenge-page regex, captcha-required) escalates to the next tier within `allowed_tiers ∩ [next_tier .. min(4, tenant_max)]`; `RateLimitedError` (HTTP 429 / 503 with `Retry-After`) sleeps then retries the same tier (max 3 retries) before escalating. Tier 4 SHALL be gated by both (a) `tenant_max == 4` (per-tenant feature flag, default 3) and (b) presence of `IGUANA_2CAPTCHA_API_KEY` env var; missing either causes the ladder to raise `ScrapeBlockedError(tier_capped=True)` instead of attempting Tier 4.

#### Scenario: Tier 1 success returns body without escalation

- **GIVEN** `ScrapeLadder.fetch(url="https://api.example.com/data", default_tier=1, allowed_tiers=(1,2,3,4), tenant_max=3, requires_robots_check=False, tenant_id=T)` and the Tier-1 `fetch_tier1` returns body B
- **WHEN** the ladder runs
- **THEN** the ladder returns B
- **AND** does NOT invoke Tier 2, 3, or 4
- **AND** emits structlog `research.scraping.tier_attempted` with `tier=1, outcome="success"`

#### Scenario: Tier 1 challenge-page escalates to Tier 2

- **GIVEN** the same call and Tier 1 raises `ScrapeBlockedError(tier_attempted=1, block_reason="challenge_page")`
- **WHEN** the ladder catches the error
- **THEN** the ladder invokes Tier 2 (`fetch_tier2`)
- **AND** if Tier 2 returns body B', the ladder returns B'
- **AND** emits two structlog `research.scraping.tier_attempted` events (tier=1 outcome="blocked", tier=2 outcome="success")

#### Scenario: Tier 3 captcha + tenant_max=3 raises tier_capped without invoking Tier 4

- **GIVEN** `tenant_max=3` and Tier 3 raises `ScrapeBlockedError(tier_attempted=3, block_reason="captcha_required")`
- **WHEN** the ladder evaluates the next escalation
- **THEN** the ladder raises `ScrapeBlockedError(tier_attempted=3, block_reason="captcha_required", tier_capped=True)`
- **AND** does NOT call `fetch_tier4`
- **AND** emits structlog `research.scraping.tier_capped` with `tenant_id=T, source_url=...`

#### Scenario: Tier 4 with valid 2Captcha key solves and records cost

- **GIVEN** `tenant_max=4`, env var `IGUANA_2CAPTCHA_API_KEY` set, Tier 3 raises captcha, and the per-tenant Tier-4 daily budget has not been exhausted
- **WHEN** the ladder invokes Tier 4
- **THEN** Tier 4 invokes the 2Captcha API (mocked in tests), receives a solved token, re-submits via the Camoufox session, and returns body B
- **AND** an `api_cost_events` row is inserted with `cost_usd=0.003`, `provider='2captcha'`, `tenant_id=T`
- **AND** structlog `research.scraping.tier_attempted` with `tier=4, outcome="success", cost_usd=0.003`

#### Scenario: RateLimitedError sleeps and retries same tier

- **GIVEN** Tier 1 raises `RateLimitedError(retry_after_seconds=2)` on first call, then returns body B on the second call
- **WHEN** the ladder runs
- **THEN** the ladder awaits 2 seconds (asyncio.sleep)
- **AND** retries Tier 1 (NOT Tier 2)
- **AND** returns B
- **AND** emits two structlog `research.scraping.tier_attempted` events both at tier=1 (first outcome="rate_limited", second outcome="success")

### Requirement: System enforces FR79 politeness primitives — User-Agent rotation + robots.txt + rate-limit floor

The system SHALL provide `apps/api/src/iguanatrader/contexts/research/scraping/user_agent.py` with `next_user_agent() -> str` returning UA strings from a 5-element round-robin pool, every string starting with `iguanatrader/<__version__> (+arturo6ramirez@gmail.com)` to satisfy FR79's "identifying User-Agent" mandate. The system SHALL provide `robots_check.py` with `is_robots_allowed(url, user_agent) -> bool` consulting `urllib.robotparser` with a 24-hour TTL cache keyed on netloc; on robots.txt fetch failure (404, timeout, malformed) the function SHALL fail-open, return `True`, and emit a structlog warning `research.scraping.robots_unavailable`. The `ScrapeLadder.fetch()` method SHALL invoke `is_robots_allowed` BEFORE any tier attempt when called with `requires_robots_check=True`; if disallowed, the ladder SHALL raise `ScrapeBlockedError(block_reason="robots_disallow")` without invoking any tier. Per-source rate limits SHALL be configured in `research_sources.metadata.rate_limit_config` and enforced ≥ 1 req / 3 s for any HTML scrape path (Tier 2 or higher).

#### Scenario: User-Agent pool rotates and identifies iguanatrader

- **WHEN** `next_user_agent()` is called five times in succession
- **THEN** five distinct strings are returned
- **AND** each string starts with `iguanatrader/` followed by the package version
- **AND** each string contains `+arturo6ramirez@gmail.com`
- **AND** the sixth call returns the same value as the first call (cycle)

#### Scenario: Robots-disallow blocks ladder before any tier

- **GIVEN** `robots.txt` for `example.com` contains `User-agent: iguanatrader\nDisallow: /private/`
- **WHEN** `ScrapeLadder.fetch(url="https://example.com/private/page", requires_robots_check=True, ...)` is invoked
- **THEN** the ladder calls `is_robots_allowed("https://example.com/private/page", ua)` and receives `False`
- **AND** raises `ScrapeBlockedError(block_reason="robots_disallow")` without invoking Tier 1
- **AND** does NOT emit any `research.scraping.tier_attempted` event

#### Scenario: Robots.txt unreachable fails open with warning

- **GIVEN** `robots.txt` for `example.com` returns HTTP 500 (server error)
- **WHEN** `is_robots_allowed("https://example.com/page", ua)` is invoked
- **THEN** the function returns `True` (fail-open)
- **AND** emits structlog `research.scraping.robots_unavailable` with `netloc="example.com"`, `reason="http_500"`

#### Scenario: 24-hour cache avoids re-fetching robots.txt

- **GIVEN** `is_robots_allowed("https://example.com/a", ua)` was called and fetched `robots.txt` (stored in TTL cache)
- **WHEN** `is_robots_allowed("https://example.com/b", ua)` is called within 24 hours
- **THEN** the function returns the answer from the cached `RobotFileParser` instance
- **AND** does NOT issue a second HTTP request to `https://example.com/robots.txt`

### Requirement: System enforces FR75 ESG-ban-in-backtest via CI grep assertion

The system SHALL provide `apps/api/tests/unit/test_no_esg_in_backtest.py` that walks `apps/api/src/iguanatrader/contexts/trading/` recursively, strips comments and docstrings via `tokenize`, and matches the regex `(esg\.aggregate|is_esg_aggregate|fact_kind\s*==\s*['"]esg|esg_score)` against every Python source file. Any match SHALL fail the test with a clear error message naming the file path and line number. A file-level pragma `# noqa: esg-ban-allow-context: <reason>` SHALL skip the file with a `warnings.warn` notice; the pragma's reason text SHALL be human-readable and is reviewed at PR time. ESG facts SHALL be persisted with `metadata.is_esg_aggregate=true` and `metadata.single_source_caveat="..."` so R5's runtime feature_provider can independently identify and gate them at query time.

#### Scenario: Backtest feature builder referencing esg.aggregate fails the build

- **GIVEN** a file `apps/api/src/iguanatrader/contexts/trading/strategies/_my_strategy.py` containing `if fact.fact_kind == "esg.aggregate": features.append(fact.value_numeric)`
- **WHEN** `pytest apps/api/tests/unit/test_no_esg_in_backtest.py` runs
- **THEN** the test fails with a message identifying `_my_strategy.py` + line number + the matched substring
- **AND** the failure message references FR75 + this requirement

#### Scenario: Pragma escape allows context-specific override

- **GIVEN** a file with `# noqa: esg-ban-allow-context: live-only ESG signal in approval channel rendering` at the top
- **WHEN** the test runs
- **THEN** the file is skipped
- **AND** a `warnings.warn` notice is emitted with the file path + the pragma reason

#### Scenario: ESG facts ingested by R3 carry the metadata flag

- **GIVEN** `YFinanceSustainabilitySource().fetch(symbol="AAPL", since=T0)` is invoked and yfinance returns a non-empty sustainability DataFrame
- **WHEN** each draft is passed to `repo.insert_fact(draft)`
- **THEN** every persisted `research_facts.metadata` JSONB carries `is_esg_aggregate=true`
- **AND** the `single_source_caveat` field is non-empty
- **AND** the `research_sources.id="yfinance_sustainability"` row carries `pit_class='B'`
- **AND** `fact_kind="esg.aggregate"` for every persisted row

### Requirement: System persists 10 catalogue rows in `research_sources` with correct `pit_class` and scrape `tier`

The migration `0004_research_sources_tier_b_c.py` SHALL insert exactly 10 rows into `research_sources` covering source_ids: `finnhub`, `gdelt`, `openfda`, `openinsider`, `finviz_scrape`, `wgi_world_bank`, `vdem`, `ibkr_bars`, `yahoo_bars_fallback`, `yfinance_sustainability`. Each row SHALL carry `tier ∈ {1, 2}` corresponding to the scrape ladder tier (per data-model §3.7 + design D1) and `pit_class ∈ {'B', 'C'}` per FR75 semantics (B = snapshot collected, C = bootstrap). Each row's `metadata` JSONB SHALL include `rate_limit_config` (per-source caps), `dedupe_strategy` (per design D6), and `scrape_tier4_daily_usd_max=0.50`. The migration SHALL be reversible via `downgrade()` deleting the 10 rows by `id IN (...)`.

#### Scenario: Catalogue rows carry the documented pit_class

- **GIVEN** migration `0004` has been applied
- **WHEN** the application queries `SELECT id, pit_class, tier FROM research_sources WHERE id IN ('finnhub', 'gdelt', 'wgi_world_bank', 'vdem', 'yfinance_sustainability')`
- **THEN** `finnhub` returns `pit_class='B', tier=1`
- **AND** `gdelt` returns `pit_class='B', tier=1`
- **AND** `wgi_world_bank` returns `pit_class='C', tier=1`
- **AND** `vdem` returns `pit_class='C', tier=1`
- **AND** `yfinance_sustainability` returns `pit_class='B', tier=1`

#### Scenario: Migration reversibility removes only R3's rows

- **GIVEN** migration `0004` has been applied and 10 rows exist in `research_sources`
- **WHEN** `alembic downgrade -1` is invoked
- **THEN** all 10 R3-seeded rows are deleted
- **AND** any rows from R2's later migration (e.g. `sec_edgar`, `fred`, `bls`, `bea`) remain untouched
- **AND** subsequent `alembic upgrade head` re-inserts the 10 R3 rows idempotently

### Requirement: Adapters use idempotent dedupe keys to skip already-ingested facts

Each adapter SHALL compute a per-fact `dedupe_key` (per design D1 idempotency-key column) and consult `repo.as_of(symbol, at=now)` filtered by `metadata->>'dedupe_key' = :key` BEFORE inserting. On match, the adapter SHALL skip the insert and emit structlog `research.<source>.deduped` with `dedupe_key`, `symbol`. On miss, the adapter SHALL insert with `metadata.dedupe_key` populated. This is a best-effort dedupe at the application layer; the bitemporal model tolerates concurrent-write race duplicates (both rows have valid `recorded_from`).

#### Scenario: Finnhub re-poll skips already-ingested news

- **GIVEN** a `research_facts` row exists for Finnhub with a known dedupe key (the SHA-1 hex of `(symbol, source_url, news_id)`)
- **WHEN** `FinnhubSource().fetch(symbol="AAPL", since=earlier)` yields a draft whose computed dedupe key matches the existing row's
- **THEN** the adapter consults the repository, finds the existing row, and skips the insert
- **AND** emits structlog `research.finnhub.deduped` with the dedupe key and the symbol `AAPL` as fields
- **AND** no new row is added to `research_facts`

#### Scenario: OpenInsider new transaction passes dedupe and inserts

- **GIVEN** no existing `research_facts` row matches dedupe_key SHA-1 of `(filer_cik=12345, transaction_date=2026-05-01, transaction_type='P', shares=1000)`
- **WHEN** the OpenInsider adapter yields a draft for that transaction
- **THEN** `repo.insert_fact(draft)` lands a new row
- **AND** `research_facts.metadata->>'dedupe_key'` equals the SHA-1 hex digest

### Requirement: Adapter failure does not cascade — live ingest skips and continues

When an adapter encounters an unrecoverable error during `fetch()` (network error after backoff exhaustion, parse error after multi-fallback selector cascade, rate-limit-exhausted-then-still-blocked, IBKR disconnection past backoff window), the adapter SHALL emit structlog `research.<source>.ingest_failed` with `error_class`, `symbol`, `since`, `tier_reached` (if applicable), update `research_sources.last_error_at = utc_now()`, and return an empty iterable. After 5 consecutive failures within 1 hour, the adapter SHALL update `research_sources.enabled = false` and `metadata.disabled_until = utc_now() + 24h` and emit structlog `research.<source>.disabled_circuit_breaker`. The bitemporal `research_facts` table guarantees backtest replay correctness independently of live-ingest reliability — facts already-recorded with `recorded_from <= replay_at_time` remain queryable regardless of source health.

#### Scenario: Source down during fetch returns empty without raising

- **GIVEN** `OpenFDASource()` and the OpenFDA API returns HTTP 502 across all 5 backoff retries `[3, 6, 12, 24, 48]`
- **WHEN** the scheduler invokes `OpenFDASource().fetch(symbol="PFE", since=T0)` and iterates
- **THEN** the adapter emits structlog `research.openfda.ingest_failed` with `error_class="SourceUnavailableError"`, `symbol="PFE"`, `since=T0`, `tier_reached=1`
- **AND** `research_sources.last_error_at` is updated to `utc_now()`
- **AND** the iterable is empty (no facts yielded)
- **AND** no exception propagates to the caller

#### Scenario: Five consecutive failures trip circuit breaker

- **GIVEN** `OpenFDASource` has failed 4 times within the last hour (`metadata.consecutive_failures=4`)
- **WHEN** a 5th failure occurs
- **THEN** `research_sources.enabled` is set to `false`
- **AND** `metadata.disabled_until` is set to `utc_now() + 24h`
- **AND** structlog `research.openfda.disabled_circuit_breaker` is emitted with `consecutive_failures=5`

### Requirement: ESG and Yahoo bars adapters share a single Yahoo rate budget

The system SHALL provide `apps/api/src/iguanatrader/contexts/research/scraping/_yahoo_client.py` (slice-local, NOT a public scraping primitive) with a module-level token bucket of capacity 2000, refill 2000 per hour. Both `YahooBarsFallbackSource` and `YFinanceSustainabilitySource` SHALL acquire from this shared bucket before any yfinance call. This prevents the two adapters from collectively exceeding Yahoo's undocumented soft limit and triggering a service-wide ban that would affect both data domains (bars + ESG) simultaneously.

#### Scenario: Two Yahoo adapters share the same budget

- **GIVEN** the shared Yahoo budget has 1 token remaining
- **WHEN** `YahooBarsFallbackSource().fetch(symbol="MSFT", since=T0)` acquires 1 token (now 0)
- **AND** `YFinanceSustainabilitySource().fetch(symbol="MSFT", since=T0)` attempts to acquire
- **THEN** the second call awaits until the bucket refills (next refill tick)
- **AND** the budget is refilled to capacity 2000 hourly across both adapters
