## Context

R3 lands the Tier-B (snapshot collected) + Tier-C (bootstrap) source adapters that feed iguanatrader's research bounded context with news, catalysts, governance, and bars. State at R3 start:

- Slices 1–5 ✅ (foundation merged).
- R1 `research-bitemporal-schema` ✅ (archived 2026-05-06) — `SourcePort` Protocol, `ResearchFactDraft` dataclass with `with_payload()` storage-tier dispatch, `ResearchRepository.insert_fact()` with provenance enforcement + sha256 integrity, the 7-table research schema (migrations `0003`), 4 timestamp columns for bitemporal queries.
- R2 `research-edgar-fred-adapters` — Tier-A (native PiT) adapters; in flight in parallel; R3 must not collide on shared infra (no scrape ladder, no rate-limiter — those are R3's net-new contribution; R2 only uses `httpx` directly with rate-limit constants per source).

Wave 3 anti-collision contract: each slice writes only under its bounded subtree. R3 owns `contexts/research/sources/<R3-source>.py`, `contexts/research/scraping/*`, `migrations/versions/0004_*.py`, and tests under `tests/{unit,integration}/contexts/research/test_<R3-thing>.py`. Shared registry files (`api/routes/__init__.py`, `cli/main.py`, `migrations/env.py`) are NOT touched. R2 owns its own source files (`sec_edgar.py`, `fred.py`, `bls.py`, `bea.py`) — disjoint from R3's source list.

The challenge is **adapter heterogeneity + scraping resilience**. The 9 R3 sources span four interaction styles (REST/JSON, BigQuery, scraped HTML, broker library) and each has its own quirks (Finnhub free-tier 60 req/min hard ceiling; GDELT 15-min refresh window with BigQuery free-tier 100 GB/mo budget; OpenFDA no auth but soft rate; OpenInsider DOM brittleness; Finviz aggressive bot detection that escalates the ladder; IBKR ib_async heartbeat; yfinance undocumented internal API; Camoufox stealth headless Firefox; 2Captcha paid solver gated by feature flag). The design must give each adapter an isolated failure surface (one source down does NOT cascade) while sharing the politeness primitives (UA, robots, rate-limit) so FR79 is enforced once at the ladder layer rather than re-implemented in nine places.

ADR-017 already settled the four-tier ladder topology + opt-in tier-4 economics. ADR-014 settled the bitemporal `research_facts` shape that all adapters write into. ADR-016 documented the research-domain split with backtest-skip. R3 translates these ADRs into concrete adapter classes + scrape ladder code paths + the FR75 ESG-ban CI assertion.

## Goals / Non-Goals

**Goals:**

- Land 9 `SourcePort` implementations under `contexts/research/sources/` that each (a) fetch from their respective API/page/library, (b) construct `ResearchFactDraft` instances with full provenance metadata, (c) call `ResearchRepository.insert_fact(draft)` for each fact, (d) emit structlog event `research.<source>.ingested` with `count`, `symbol`, `since` keys, and (e) survive transient failures via `tenacity.retry` with the canonical backoff `[3, 6, 12, 24, 48]` from slice 2.
- Land the 4-tier scrape ladder under `contexts/research/scraping/` with explicit escalation semantics (tier-N raises `ScrapeBlockedError` → ladder tries tier-N+1; `RateLimitedError` → ladder backs off + retries same tier).
- Enforce FR79 politeness (User-Agent identification + robots.txt + 1 req/3s scrape floor) ONCE at the ladder layer; adapters declare per-source rate limits in `research_sources.metadata.rate_limit_config` and the ladder reads them.
- Enforce FR75 ESG ban in backtest features at CI time via `test_no_esg_in_backtest.py` (repo grep) — runtime gate is R5's responsibility.
- Idempotent ingestion via `research_sources.dedupe_key` semantics encoded in adapter pre-checks (e.g. Finnhub news `uuid`, OpenInsider `(filer_cik, transaction_date, transaction_type)`, GDELT `gkg_id`).
- Stable cost envelope: GDELT BigQuery query templates partitioned by `DATE(_PARTITIONTIME) >= :since AND _PARTITIONTIME < :now` + filtered by ticker first to keep monthly bytes-scanned under 100 GB free-tier per ADR caveat.

**Non-Goals:**

- Tier-A native-PiT adapters (R2).
- OpenBB Platform sidecar (R4).
- LLM synthesis, methodology profiles, brief render — R5.
- Runtime feature_provider tier-gate (Tier-A/B/C history availability check at query time) — R5. R3 only ships the CI grep for the ESG carve-out.
- CLI / SSE / routes / UI — none of these in R3.
- Production tier-4 (paid captcha) invocation — shipped behind feature flag, default OFF.
- ESG history beyond the single-source `yfinance.sustainability` snapshot — explicitly best-effort + flagged.
- Robots.txt enforcement at the API source level (Finnhub / OpenFDA / GDELT BigQuery / WGI / V-Dem) — robots.txt only applies to scraped HTML paths (OpenInsider, Finviz). API sources rely on each provider's published rate limits + auth.

## Decisions

### D1. Per-adapter inventory — source URL/API, ladder tier, PiT class, rate-limit strategy

Authoritative table for the 9 adapters R3 ships. Each row identifies the source, where it lives, how the ladder reaches it, and how `pit_class` slots into FR75 gating.

| # | source_id (`research_sources.id`) | Adapter file | Endpoint / library | Scrape ladder tier (FR77) | `pit_class` (FR75) | Rate-limit strategy | Idempotency key |
|---|---|---|---|---|---|---|---|
| 1 | `finnhub` | `sources/finnhub.py` | `https://finnhub.io/api/v1/{news,calendar/earnings,stock/recommendation}` (REST/JSON, free tier) | Tier 1 (webfetch) | B (snapshot) | Token bucket 60 req/min hard, 1 req/sec soft; backoff `[3,6,12,24,48]` on 429 | `news.uuid` / `(symbol, period)` for earnings calendar |
| 2 | `gdelt` | `sources/gdelt.py` | GDELT 2.0 DOC API (REST/JSON) for headlines + Google BigQuery `gdelt-bq.events.events` for events | Tier 1 (webfetch + BigQuery client) | B (snapshot, 15-min refresh) | DOC API: 1 req/3s; BigQuery: monthly budget 80 GB scanned with circuit breaker at 90 GB; partition pruning mandatory | `gkg_id` (DOC) / `globaleventid` (events) |
| 3 | `openfda` | `sources/openfda.py` | `https://api.fda.gov/drug/{event,label,enforcement}` (REST/JSON, no auth) | Tier 1 (webfetch) | B (snapshot) | 240 req/min courtesy floor; respect 429 with `Retry-After`; backoff `[3,6,12,24,48]` | `report_number` (drug events) / `recall_number` |
| 4 | `openinsider` | `sources/openinsider.py` | `http://openinsider.com/screener?...` (HTML scrape) | Tier 2 (Playwright) — Tier 1 attempted first; aggressive Cloudflare on screener pages forces Tier 2 majority | B (snapshot) | 1 req/3s (FR79 floor); 30-min stale-while-revalidate cache | `(filer_cik, transaction_date, transaction_type, shares)` SHA-1 → matches DOM cell content |
| 5 | `finviz_scrape` | `sources/finviz_scrape.py` | `https://finviz.com/screener.ashx?...&v=152` (HTML scrape; v=152 is the analyst-rating screener layout) | Tier 2 (Playwright) — falls through to Tier 3 Camoufox when Cloudflare challenges; per-tenant Tier-4 only when `scrape_tier_max=4` | B (snapshot) | 1 req/3s; 30-min cache; circuit breaker after 5 consecutive Cloudflare 403s in 1h | `(symbol, retrieved_at::date)` for screener snapshots |
| 6 | `wgi_world_bank` | `sources/wgi_world_bank.py` | `https://api.worldbank.org/v2/country/{code}/indicator/{WGI_indicator}?format=json` (REST/JSON) | Tier 1 (webfetch) | C (bootstrap — annual cadence, single value per (country, indicator, year)) | 5 req/sec courtesy; idempotent by URL | `(country, indicator, year)` |
| 7 | `vdem` | `sources/vdem.py` | V-Dem v14 dataset CSV bulk download from `https://v-dem.net/data/the-v-dem-dataset/` (one-shot file pull, NOT a per-call API) | Tier 1 (webfetch — bulk download cached locally) | C (bootstrap — one-shot; refreshed annually when V-Dem publishes new version) | One download per release; sha256 verified against published checksum file | `(country, year, indicator_code)` |
| 8 | `ibkr_bars` | `sources/ibkr_bars.py` | `ib_async` library → IB TWS / Gateway `reqHistoricalData` | N/A (broker library, not scrape) | B (snapshot — broker session-bound; rebar on reconnect) | IBKR HMDS pacing: max 60 historical requests / 10 min; `HeartbeatMixin` from slice 2; backoff `[3,6,12,24,48]` on disconnect | `(symbol, timeframe, bar_start)` |
| 9 | `yahoo_bars_fallback` | `sources/yahoo_bars_fallback.py` | `yfinance.Ticker(symbol).history(...)` (Apache-2.0 lib; uses Yahoo undocumented internal API) | N/A (library — but Yahoo throttles; treat as Tier 1 for backoff purposes) | B (snapshot) | 2000 req/hour soft; circuit breaker after 5 consecutive empty responses | `(symbol, timeframe, bar_start)` |
| 10 | `yfinance_sustainability` | `sources/yfinance_sustainability.py` | `yfinance.Ticker(symbol).sustainability` (Sustainalytics-via-Yahoo, single DataFrame) | N/A (library — but rate-limited under Yahoo umbrella with `yahoo_bars_fallback`) | B (snapshot — `metadata.is_esg_aggregate=true` flag set) | Shares Yahoo budget with #9 (2000 req/hour combined); 24h cache | `(symbol, retrieved_at::date)` |

(Total: 9 distinct functional adapters across 10 source_ids — `yfinance_sustainability` is a separate source_id from `yahoo_bars_fallback` per FR65 explicit single-source documentation, but they share a Yahoo client + rate budget.)

### D2. 4-tier scrape ladder — escalation semantics + per-tenant cap

**Decision**: `contexts/research/scraping/ladder.py` exposes `ScrapeLadder.fetch(url, *, default_tier, allowed_tiers, tenant_max)` returning the response payload (text or DOM-as-string). Escalation rules:

- Tier 1 → Tier 2 only when Tier 1 raises `ScrapeBlockedError` (HTTP 403 from a known anti-bot signature: Cloudflare, Akamai, PerimeterX) OR returns a body whose first 4KB matches a "challenge page" regex catalogue. Tier 1 raises `RateLimitedError` (HTTP 429 / 503 with `Retry-After`) does NOT escalate; it sleeps + retries same tier with the canonical backoff.
- Tier 2 → Tier 3: same rules as 1→2 but observed at the Chromium browser level (Cloudflare 5-second challenge survived ≠ blocked; persistent CAPTCHA prompt = blocked).
- Tier 3 → Tier 4: ONLY when (a) `tenant_max == 4`, (b) Tier 3 raises `ScrapeBlockedError` with reason `captcha_required`, and (c) the per-tenant 2Captcha balance check passes (cached for 5 minutes). Tier 4 invokes `2captcha-python` to solve the challenge then re-submits via Tier 3's Camoufox session. Each Tier 4 solve increments `api_cost_events` (slice O1) with `cost_usd=0.003` + `provider='2captcha'`.
- `tenant_max < 4` (default = 3) short-circuits before Tier 4. Adapter receives `ScrapeBlockedError(tier_capped=true)` and the per-source circuit breaker increments `consecutive_failures`; after 5 failures in 1 hour the source is marked `enabled=false` for 24h with a structlog event `research.<source>.disabled_circuit_breaker`.

**Alternatives considered**:

- **Always start at Tier 3** (Camoufox for everything): expensive (Firefox cold-start ~2s vs httpx ~10ms), wasteful for sources that respond fine to Tier 1 (WGI, OpenFDA, Finnhub). Rejected.
- **Skip Tier 2 entirely and jump from 1 → 3**: loses the cheaper-than-Camoufox option (Playwright/Chromium often suffices for JS-rendered SPAs without anti-bot). Rejected.
- **No tier 4 at all (paid solver)**: per ADR-017 caveat, two sources (Finviz under aggressive challenge, OpenInsider during DDoS waves) have historically required CAPTCHA solve to recover. Skipping Tier 4 would force human intervention. Rejected — keep behind feature flag.

**Rationale**: ADR-017 settled the topology; this design names the escalation triggers + the cap mechanism. The tier numbering is orthogonal to `pit_class` (D1 column) — the ladder is about *how* we reached the source, not the PiT semantics of the data.

### D3. `robots_check.py` + `user_agent.py` — politeness primitives shared across adapters

**Decision**: `scraping/robots_check.py` exposes `def is_allowed(url: str, user_agent: str) -> bool` using `urllib.robotparser.RobotFileParser` with a 24-hour in-memory cache keyed on the netloc. Cache miss → fetch `https://<netloc>/robots.txt` via Tier 1 webfetch (recursive call short-circuit: robots.txt fetches never trigger ladder escalation). On fetch failure (404, timeout, malformed): fail-open with structlog warning `research.scraping.robots_unavailable` + `netloc=<x>` — best practice is "absent robots = permitted" but we log to surface unintended scrapes.

`scraping/user_agent.py` exposes `def next_ua() -> str` returning a UA from a 5-string round-robin pool: each string starts with `iguanatrader/<version> (+arturo6ramirez@gmail.com)` (per FR79 mandatory identifier) followed by a varied suffix (`Mozilla/5.0 (compatible; ...)`, `Chrome/...`, etc.) so that sources tracking the iguanatrader UA still see it but the trailing fingerprint varies. Pool defined as a module constant; `__version__` read from `iguanatrader.__about__`.

The ladder calls `is_allowed(url, ua)` BEFORE Tier 1 fetch on any URL flagged `requires_robots_check=true` (default for HTML scrape paths: OpenInsider, Finviz, V-Dem download page). API endpoints (Finnhub, OpenFDA, WGI, GDELT DOC API) skip the check — they rely on documented API ToS instead. Rationale: robots.txt is a scraping convention; provider APIs publish their own ToS independently.

**Alternatives considered**:

- **One UA, no rotation**: simpler, but FR79 wording ("identifying User-Agent") allows varied suffixes; rotation lowers fingerprint collision risk on Tier-2 paths without dropping the iguanatrader identifier. Accepted compromise.
- **No robots check at all** (rely on per-source manual ToS review): slow audit + violates FR79. Rejected.
- **Re-fetch robots.txt every request**: wasteful + many providers serve stable robots.txt for years. 24h cache is the established convention.

**Rationale**: FR79 is explicit; the ladder centralises enforcement so adapters do not have to remember.

### D4. ESG handling — single-source `yfinance.sustainability` + `is_esg_aggregate` metadata flag + CI grep enforcement of FR75 ban in backtest features

**Decision**: ESG data is intentionally a **single-source best-effort** path. `sources/yfinance_sustainability.py` calls `yf.Ticker(symbol).sustainability` (returns a pandas DataFrame of Sustainalytics scores via Yahoo). Each non-NaN cell becomes a `ResearchFactDraft` with:

- `fact_kind="esg.aggregate"` (using the existing `research_facts.fact_kind` enum-like text per data-model §3.7).
- `value_numeric` = the score.
- `unit` = the score type (`peerEsgScorePerformance`, `socialScore`, `governanceScore`, etc.).
- `metadata` JSONB carries `{"is_esg_aggregate": true, "single_source_caveat": "yfinance.sustainability — Sustainalytics-via-Yahoo; not independently verified; may regress on yfinance API changes"}`.
- `pit_class='B'` on `research_sources` row (snapshot collected; no historical ESG via this adapter — Yahoo only exposes current values).

The CI assertion `apps/api/tests/unit/test_no_esg_in_backtest.py` greps every Python file under `apps/api/src/iguanatrader/contexts/trading/` (recursive) for the regex pattern `(esg\.aggregate|is_esg_aggregate|fact_kind\s*==\s*['"]esg|esg_score)` — any match fails the test with a clear error message naming the offending file + line. Rationale: FR75 mandates Tier-A (native PiT) for backtest features only; ESG is Tier-B + best-effort + may regress; backtests must not depend on it. The runtime gate (R5's feature_provider) will also reject ESG queries when `is_backtest_context=true`, but R3 ships the CI gate now to prevent T2/T3 (parallel Wave 3 trading slices) from accidentally writing ESG-dependent strategies.

**Alternatives considered**:

- **Multi-source ESG aggregation** (Refinitiv + S&P + Sustainalytics direct): each provider charges $20K+/yr for API access. Rejected — out of MVP budget; single-source caveat is honest.
- **No ESG at all**: FR65 explicitly mandates best-effort ESG via yfinance.sustainability. Rejected — would violate the FR.
- **Runtime gate only** (no CI grep): a backtest writer in T3 could ship ESG-dependent strategy then discover at first backtest run that R5 rejects. CI grep catches at PR time + costs nothing. Accepted.
- **Whitelist of `contexts/trading/*` files via marker comment** (`# esg-allowed: live-only`): clever but invites misuse. Rejected — full ban in backtest is simpler.

**Rationale**: FR75 + FR65 together demand "best-effort ESG, never in backtest features". CI grep + metadata flag + `pit_class='B'` together implement all three properties.

### D5. Failure handling — source-down semantics differ between live ingest and backtest replay

**Decision**: When an adapter raises (network error, parse error, rate-limit-exhausted-then-still-blocked, IBKR disconnected past backoff window), the **live ingest path** SHOULD log + skip + continue. The adapter's `fetch()` swallows recoverable errors after the canonical backoff is exhausted, emits structlog `research.<source>.ingest_failed` with `error_class`, `symbol`, `since`, `tier_reached`, and returns an empty iterable. The R5 scheduler (when it lands) treats empty as "no new facts this tick" — no cascading failure. The `research_sources.last_error_at` is updated; after 5 consecutive failures in 1 hour, the source is marked `enabled=false` for 24h (per D2 circuit breaker).

The **backtest replay path** does NOT call adapters — it queries `research_facts` historically. Because facts are bitemporal and append-only, a source being down at replay time does NOT affect replay correctness; the replay only sees facts that were recorded with `recorded_from <= replay_at_time`. This contrasts with live ingest where source-down means "we may miss facts going forward" (FR75 Tier-B/C handle "no history yet" via R5's runtime gate; for backtest, the bitemporal axes naturally exclude facts not-yet-known at replay time).

**Alternatives considered**:

- **Hard-fail on source-down in live ingest** (raise instead of skip): cascades into the R5 brief refresh job and brings the whole research pipeline down for one source's transient outage. Rejected — FR-implied resilience.
- **Retry indefinitely until source returns**: blocks the scheduler tick. Rejected.
- **Fall back to a sibling source on failure** (e.g. Finnhub down → use yfinance recommendations): blurs `source_id` provenance. Rejected — every fact must cite ONE source.

**Rationale**: append-only bitemporal facts decouple live ingest reliability from backtest replay correctness; live ingest only needs "skip + recover", backtest only needs "query as_of".

### D6. Idempotency — adapter pre-checks against `research_sources.metadata.dedupe_strategy`

**Decision**: Each adapter computes a `dedupe_key` per fact (per D1's last column) and consults the repository's `as_of(symbol, at=now)` query filtered by `metadata->>'dedupe_key' = :key` BEFORE inserting. On match: skip + emit structlog `research.<source>.deduped`. On miss: insert. The `dedupe_key` is stored in `research_facts.metadata.dedupe_key` so subsequent runs can detect repeats without re-fetching the source's identifier scheme.

This is a **best-effort** dedupe, not a hard constraint at the DB level. Race conditions (two concurrent ingest workers) could insert duplicates; the bitemporal model tolerates this (both rows have valid `recorded_from`; both citations would resolve to "same fact value at time T" — acceptable for MVP). Hard de-dup via unique index on `metadata->>'dedupe_key'` is a v2 follow-up.

**Alternatives considered**:

- **Unique index on `(source_id, dedupe_key)` in migration**: blocks the bitemporal supersession pattern (a corrected fact arriving from the same source with the same key SHOULD insert as a revision, not be rejected). Rejected.
- **No dedupe at all**: GDELT/Finnhub/OpenFDA can re-emit the same article over multiple polling windows; storage bloat + brief noise. Rejected.

**Rationale**: app-level pre-check is cheap (one indexed query per fact) and covers the common case; the bitemporal model gives us correctness for the rest.

### D7. Migration `0004` — only `research_sources` catalogue rows; NO new schema

**Decision**: Migration `0004_research_sources_tier_b_c.py` only INSERTs 10 rows into `research_sources` (the catalogue table seeded as empty by R1's migration `0003`). It does NOT create new tables, does NOT alter existing columns. Each row carries `(id, display_name, tier, pit_class, enabled, metadata, created_at, updated_at)` matching data-model §3.7.

Reversibility: `downgrade()` deletes the 10 rows by `id IN (...)`. The unique-constraint exception (a row may have been mutated post-insert by ops) is handled by `ON DELETE` ignore-not-found semantics — log warning, continue.

**Alternatives considered**:

- **Add new columns** (`scrape_tier_max`, `circuit_breaker_state`, `last_consecutive_failures`): tempting, but those are runtime state, not catalogue. Live in `research_sources.metadata` JSONB instead per data-model §3.7's design. Rejected.
- **Move `metadata.rate_limit_config` to a sibling table** (`research_source_rate_limits`): over-engineered for MVP; JSONB is queryable + flexible. Rejected.
- **Skip migration entirely** (insert rows from a startup hook): violates the "schema is committed" invariant + breaks reproducibility. Rejected.

**Rationale**: minimum-cost migration; Wave 3 R2 + R4 will each ship their own catalogue migration (`0005_*` for R2, `0006_*` for R4) with non-overlapping `source_id`s.

## Risks / Trade-offs

- **[Risk] Finviz / OpenInsider DOM brittleness — selectors break on every redesign** → adapter raises `ParseError` mid-ingest, no facts that polling cycle. **Mitigation**: each scrape adapter uses **multi-fallback selectors** (XPath → CSS class → text-content match) via a `try` cascade; structlog event `research.<source>.parse_fallback_used` with `selector_index` lets ops detect drift early. Gotcha #44 documents the maintenance burden.
- **[Risk] GDELT BigQuery monthly free-tier ceiling (100 GB scanned)** exceeded on a heavy refresh week → billing surprise. **Mitigation**: per-tenant quota tracker in `research_sources.metadata.bigquery_bytes_scanned_mtd` updated by every query; circuit breaker at 80 GB scanned (warn) + 90 GB (halt) with structlog event `research.gdelt.quota_alert`. Adapter SHALL use `--dry_run` BigQuery feature to estimate bytes BEFORE executing; abort if estimate would push over 90 GB.
- **[Risk] Finnhub free-tier 60 req/min hard ceiling** during burst polling for many symbols → `RateLimitedError` cascade. **Mitigation**: token bucket initialised at startup with capacity 60, refill 1/sec; adapter awaits the bucket before each call; staggered polling across symbols (don't burst all at top-of-minute).
- **[Risk] OpenFDA no auth, soft rate** — provider could tighten without notice → silent slowdown. **Mitigation**: monitor average latency; if p95 > 10s for 1h, mark `last_error_at` + alert via cost dashboard publisher (slice O1).
- **[Risk] yfinance undocumented internal API regression** — Yahoo periodically changes the JSON shape, breaking yfinance for hours-to-days. **Mitigation**: adapter wraps yfinance calls in `try/except (KeyError, AttributeError, JSONDecodeError)` → emit structlog `research.yahoo.shape_regression` + raise `SourceUnavailableError`; circuit breaker disables source for 24h to avoid log spam. Gotcha #45 documents this.
- **[Risk] IBKR HMDS pacing violation** (61st historical request in 10min window) → IBKR rejects all subsequent for the rest of the window. **Mitigation**: token bucket capacity 60 / refill 1 per 10s; adapter awaits before each `reqHistoricalData`; on rejection, immediate cooldown 600s (full window) + structlog `research.ibkr_bars.pacing_violation`.
- **[Risk] Tier-3 Camoufox stealth fails on a hardened source** (e.g. Finviz's enterprise Cloudflare) → ladder cannot recover without Tier-4. **Mitigation**: per-tenant `scrape_tier_max` setting; ops can flip to 4 manually for one tenant (`UPDATE research_sources SET metadata = jsonb_set(metadata, '{scrape_tier_max}', '4') WHERE id = 'finviz_scrape'`) at the cost of paid-solver invocations. Default stays 3.
- **[Risk] Tier-4 paid solver cost runaway** if a source enters a degenerate state where every page needs CAPTCHA solve. **Mitigation**: per-tenant daily Tier-4 budget cap `metadata.scrape_tier4_daily_usd_max=0.50` (≈ 165 solves/day); on cap-hit, ladder degrades to "raise + skip" (D5) rather than continue solving. Cost dashboard publisher emits per-day alert.
- **[Risk] ESG CI grep false positives** (e.g. unrelated `esg_score` substring inside a strategy comment) → blocks PR merges. **Mitigation**: the grep regex is anchored to actual code patterns (function calls, dict keys, fact_kind comparisons); comments + docstrings are stripped before match via `tokenize` module. False-positive escape hatch: file-level pragma `# noqa: esg-ban-allow-context: <reason>` documented in test docstring; PR review must approve the pragma.
- **[Risk] V-Dem dataset bulk download (~2 GB CSV)** — first-time install latency + storage. **Mitigation**: dataset is downloaded lazily on first `vdem.fetch()` call; cached under `data/research_cache/vdem/v14/<sha256>.csv.gz` (compressed); subsequent calls hit cache + parse on demand. Re-download triggered only when V-Dem publishes new annual release.
- **[Trade-off] Single-source ESG is honest but limiting** — R5 briefs that lean on ESG can only carry a Sustainalytics caveat; R5 must surface the `single_source_caveat` from `metadata` in the citation chain. Documented in R5's prerequisites.
- **[Trade-off] Robots.txt fail-open warning** — if `robots.txt` is unreachable, we proceed; this favours availability over conservativeness. Acceptable for MVP; a stricter "fail-closed" mode could be exposed as `metadata.robots_strict=true` in v2.
- **[Trade-off] BigQuery client adds Google Cloud SDK dependency tree** (~50 MB transitive). Confined to `[tool.poetry.group.research]` extras — production live trader doesn't need it; CI installs for tests.

## Migration Plan

R3 ships:

1. New adapter modules under `contexts/research/sources/` and `contexts/research/scraping/`.
2. New tests under `tests/{unit,integration}/contexts/research/`.
3. Migration `0004_research_sources_tier_b_c.py` with `down_revision="0003"` (R1's last migration). Inserts 10 catalogue rows; reversible via DELETE.
4. New deps in `pyproject.toml` `[tool.poetry.group.research]` (Playwright, BigQuery client, yfinance, ib_async, tenacity, 2captcha-python).
5. CI workflow update — add `playwright install chromium` to the test job.

Deployment path:

1. Merge R3 to main.
2. CI runs `playwright install chromium` once + caches the browser binary.
3. Production paper / live deployments run `alembic upgrade head` → 10 rows seeded into `research_sources`.
4. R5 (later) wires the scheduler that calls each adapter on its configured cadence.

Rollback = revert PR + `alembic downgrade -1` (deletes the 10 rows). No state outside the catalogue rows is created by R3 itself; `data/research_cache/` may have accumulated payloads (R1's repository writes; R3's adapters route into `insert_fact()`) but those are harmless on rollback (orphaned files, no schema dependency).

## Open Questions

- **Q**: Should `gdelt.py` use the DOC 2.0 REST API only, or both REST + BigQuery? **Tentative answer**: both — DOC API for headlines polling (Tier-1 webfetch, real-time-ish) + BigQuery for historical events backfill (one-shot bootstrap, cheaper to scan than to poll for years). The two ingestion paths emit facts with the same `source_id='gdelt'` but different `fact_kind` (`news.headline` vs `pestel.event`).
- **Q**: Does V-Dem's annual cadence justify shipping it as `pit_class='C'` (bootstrap) rather than 'B' (snapshot)? **Tentative answer**: yes — V-Dem releases one CSV per year; queries during the year return the same answer; one-shot at bootstrap matches 'C' semantics per data-model §3.7 + FR75. WGI is similar but updated more frequently (annual but with mid-year corrections); kept as 'C' for simplicity, document caveat.
- **Q**: Should the Yahoo-shared rate budget (`yahoo_bars_fallback` + `yfinance_sustainability`) live in a single client or two? **Tentative answer**: single shared client `iguanatrader.contexts.research.scraping._yahoo_client.py` with one token bucket; both adapter modules import it. Avoids double-spending the budget.
- **Q**: Does the 2Captcha integration need an `OPS_INTEGRATION` setting beyond an env var? **Tentative answer**: not in R3 — env var `IGUANA_2CAPTCHA_API_KEY` checked at adapter import time; missing → tier-4 unavailable; structlog warning at boot. Settings UI for this is R6's `feature_flags` scope.
- **Q**: Should adapters emit a per-fact `confidence` score (R1's optional column) for Tier-B sources? **Tentative answer**: only where the source publishes one — Finnhub sentiment carries a polarity value (mapped to `confidence`), GDELT tone score (mapped), V-Dem indicators carry a separate `confidence` column in their CSV; adapters propagate when present, leave NULL otherwise. Documented per-adapter inline.
