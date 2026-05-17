---
type: roadmap
project: iguanatrader
schema_version: 1
created: 2026-05-17
updated: 2026-05-17
purpose: Forward-looking slice plan for the Ingestion Wave — wiring the built-but-dormant research source adapters into production CLIs / scheduler so research_facts gets populated and briefs stop coming out partial=true.
---

# Roadmap — Ingestion Wave

Single source of truth for activating iguanatrader's research-fact ingestion pipeline. Each slice in the table corresponds to one source / one CLI / one set of credentials. When a slice starts, open the formal proposal via `/opsx:propose <slice-id>`.

**Track owner**: Arturo Ramírez.
**Scope**: bring every Tier-A / Tier-B / Tier-C source adapter from "built but never called" to "scheduled in production with operator-visible health". Result: briefs persist `partial=false` with real quant signals.

**Authoritative companion**: [`docs/runbooks/research-data-sources.md`](runbooks/research-data-sources.md) — operational reference per source (registration, env vars, rate limits). The runbook describes the *what*; this roadmap describes the *when + why* sequencing.

---

## Slice order

| ID | Slug | Status | Source(s) activated | Notes |
|----|------|--------|---------------------|-------|
| I0 | `research-ingest-cli-sec-edgar` | ✅ shipped 2026-05-17 (PR #203) | SEC EDGAR | Filings + XBRL companyfacts. NVDA real-data smoke test: 3720 facts persisted. |
| I1 | `research-ingest-cli-fred` | 🟡 next | FRED | Macro time-series + `--backfill 5y` flag for new symbols. ALFRED vintage-aware (revisions land as new facts). |
| I2 | `openbb-sidecar-in-mvp-compose` | ⏳ | OpenBB sidecar (YFinance default, free) | Activates value pillar (`forward_pe`, `pb_ratio`) + analyst ratings + ESG. AGPL boundary per ADR-015. |
| I3 | `research-ingest-cli-ibkr` | ⏳ | Interactive Brokers (TWS / Gateway) | Market snapshot (P/E forward, beta, market cap, dividend yield) + historical OHLCV (momentum pillar) + contract details (sector / industry → fills `symbol_universe`). Reuses already-running TWS paper client; free. |
| I4 | `research-ingest-cli-finnhub` | ⏳ | Finnhub (free 60 req/min) | News (30d window) + earnings calendar + analyst recommendations + insider transactions. |
| I5 | `research-transcripts-fool-scraper` | ⏳ | The Motley Fool (`fool.com/earnings/call-transcripts/`) | Web scraping for earnings call transcripts. ToS-aware, rate-limited, respects robots.txt. Closes the only meaningful gap vs FMP. |
| I6 | `research-edgartools-supplement` | ⏳ | SEC EDGAR (via `edgartools` lib) | Extracts 10-K Item 7 MD&A + Item 1A Risk Factors narrative text. Supplements the XBRL-only adapter from I0. |
| I7 | `research-ingest-scheduler` | ⏳ | All of the above | APScheduler driven by `watchlist_configs.brief_refresh_schedule` (daily / weekly). Async job tracking via `ingest_runs` table (pattern borrowed from `mcp-fred`). |

**Why this order**:

1. **I0 (SEC EDGAR) first** — public domain, no key, deepest historical fundamentals coverage (XBRL companyfacts goes back to ~2009). Sets the bitemporal pattern every subsequent adapter follows.
2. **I1 (FRED)** — macro context is needed before any pillar that uses regime / mean-reversion features. Backfill flag lets new symbols get historical macro on first onboard.
3. **I2 (OpenBB sidecar)** — activates the value pillar. Cheap: YFinance is free, no new keys, sidecar is already built. AGPL boundary already designed.
4. **I3 (IBKR)** promoted over Finnhub because:
   - Already-running TWS paper client (zero new infra).
   - Covers BOTH momentum pillar (historical OHLCV) AND remaining `symbol_universe` metadata gaps (sector / industry — currently NULL in DB).
   - Free for snapshot + historical + contract_details.
5. **I4 (Finnhub)** — fills the news-sentiment + analyst-rec gap that IBKR doesn't cover at free tier.
6. **I5 (transcripts scraping)** — riskiest (ToS / fragility / breakage on site redesign); last in the "data" tier so the rest doesn't depend on it.
7. **I6 (edgartools MD&A)** — narrative supplement; quality-of-brief improvement after quant pillars are live.
8. **I7 (scheduler)** — automates everything once the manual CLIs prove the data path end-to-end.

---

## Per-slice notes

### I1 — `research-ingest-cli-fred` (next)

**Goal**: `iguanatrader research ingest fred --series CPIAUCSL,UNRATE,DFF [--backfill 5y]` persists ALFRED-vintage-aware macro facts.

**Design**:

- CLI option `--series` accepts a comma-separated list of FRED series IDs.
- CLI option `--backfill <N>y` translates to `since = utc_now() - N*365d`. Default: no backfill (uses adapter's 1900-01-01 floor only when ingesting a fresh series for the first time).
- The adapter's `fetch_series` already supports `since` — pure plumbing through the CLI.
- Facts get `symbol_universe_id = NULL` (macro is global, not symbol-scoped — the column is nullable).
- Idempotent via existing `dedupe_key = f"fred:{series_id}:{date}:{realtime_start}"`.

**Dependencies**: `FRED_API_KEY` (already in `/opt/iguanatrader/.env` on cx43).

**Estimated**: ~150 LoC + 1 test.

### I2 — `openbb-sidecar-in-mvp-compose`

**Goal**: Stand up `apps/openbb-sidecar/` in the MVP compose stack and add a CLI that fetches fundamentals + ratings + ESG via the sidecar's HTTP endpoints.

**Design**:

- Add `openbb_sidecar` service to `docker-compose.mvp.yml` (image build from existing Dockerfile, port 8765 internal-only).
- New `OpenBBSidecarSource` adapter calls `http://openbb_sidecar:8765/v1/equity/fundamentals/{symbol}` etc.
- CLI: `iguanatrader research ingest openbb --symbol NVDA`.
- Default provider: YFinance (no key). Optional FMP / Polygon keys via OpenBB-recognized env vars passed through compose.

**Dependencies**: none for free path (YFinance default). FMP key optional for premium upgrade (see Future considerations §).

**Estimated**: ~200 LoC + 1 compose-config test.

### I3 — `research-ingest-cli-ibkr`

**Goal**: Reuse the live TWS connection to pull market snapshot + historical OHLCV + contract details into `research_facts`.

**Design**:

- New `IBKRSource` adapter under `apps/api/src/iguanatrader/contexts/research/sources/ibkr.py`. Uses the existing `ib_async`-based trading client; reads connection env (`IGUANATRADER_IBKR_HOST` / `_PORT`) already configured.
- Three sub-flows: `fetch_market_snapshot(symbol)` (tick types: P/E forward, beta, market cap, dividend yield, 52-week hi/lo), `fetch_historical_bars(symbol, duration, bar_size)` (daily for 5y default → seeds momentum), `fetch_contract_details(symbol)` (sector / industry → backfills `symbol_universe`).
- New migration seeds `research_sources` row for `ibkr` (pit_class='B' for snapshot, 'A' for historical with TWS-stamped timestamps).
- CLI: `iguanatrader research ingest ibkr --symbol NVDA [--include snapshot|historical|contract-details|all]`.

**Open question**: TWS must be running. For scheduler (I7), need IB Gateway headless mode — covered by [`docs/runbooks/ibkr-gateway-bringup.md`](runbooks/ibkr-gateway-bringup.md).

**Estimated**: ~350 LoC + 2 tests.

### I4 — `research-ingest-cli-finnhub`

**Goal**: `iguanatrader research ingest finnhub --symbol NVDA [--include news|earnings|insiders|all]` persists Finnhub free-tier data.

**Design**: adapter already exists at `apps/api/src/iguanatrader/contexts/research/sources/finnhub.py`. CLI is plumbing.

**Estimated**: ~150 LoC + 1 test.

### I5 — `research-transcripts-fool-scraper`

**Goal**: Earnings call transcripts via web scraping of `fool.com/earnings/call-transcripts/{year}/{month}/{day}/{slug}/`.

**Design**:

- New `MotleyFoolTranscriptSource` adapter. URL pattern is deterministic (year/month/day/company-ticker-qN-year-earnings-call-trans), but enumeration requires listing each symbol's transcript index page.
- Respects `robots.txt` (verify at adapter init), rate-limit 1 req per 3 seconds, polite UA with contact email.
- Stores transcript as `value_text` (full body) + `value_jsonb={"speakers": [...], "metadata": {...}}`. Large payloads (>16KB) auto-route to filesystem tier via `with_payload`.
- Adapter Tier-B (snapshot — published with delay; not backtest-safe at the publication time).

**Risks**:

- ToS fragility — Fool can change UI or block. Mitigation: implement as opt-in via env flag (`ENABLE_FOOL_SCRAPER`) so a single source going dark doesn't fail the whole pipeline.
- Webfetch ladder fallback (Playwright → Camoufox) if static scraping fails.

**Estimated**: ~350 LoC + 1 test with recorded HTTP fixtures.

### I6 — `research-edgartools-supplement`

**Goal**: Pull 10-K Item 7 (MD&A) + Item 1A (Risk Factors) prose text — closes the narrative gap our XBRL-only adapter leaves.

**Design**: thin wrapper around the `edgartools` library (free, no API key, MIT). Emits drafts with `value_text` = parsed section text, `fact_kind = sec_text.mdna` / `sec_text.risk_factors`.

**Estimated**: ~250 LoC + 1 test.

### I7 — `research-ingest-scheduler`

**Goal**: Automate I0–I6 per `watchlist_configs.brief_refresh_schedule`. Operator should not have to docker-exec the CLI by hand.

**Design**:

- APScheduler `AsyncIOScheduler` mounted in the FastAPI lifespan when `IGUANATRADER_SCHEDULER_ENABLED=true`.
- One job per `(tenant, symbol_universe, source)` triple, cron derived from `brief_refresh_schedule`.
- New `ingest_runs` table tracking each invocation (start, finish, rows_inserted, error, source). Pattern borrowed from `cfdude/mcp-fred`'s job_manager.
- Admin endpoints: `GET /api/v1/admin/ingest-runs`, `POST /api/v1/admin/ingest-runs/{id}/cancel`. Feeds the future Settings UI health-status overlay (per [runbook §5](runbooks/research-data-sources.md#5-future-settings-research-sources-ui)).

**Open question**: TWS connection lifecycle for IBKR scheduled jobs. Likely IB Gateway with autostart.

**Estimated**: ~400 LoC + 2 tests + 1 migration.

---

## Future paid options under consideration

These are NOT in the active roadmap — captured here so the decision to spend lands as an explicit slice when (and if) the free path proves insufficient.

| Option | Cost | What it unlocks | When to revisit |
|--------|------|------------------|------------------|
| **FMP Starter (Financial Modeling Prep)** | ~$15/mo | Earnings call transcripts (literal), analyst price targets, 30-year fundamentals history, insider trades, earnings calendar with consensus EPS. Plugs into OpenBB sidecar via `OPENBB_FMP_API_KEY` (no new adapter code). | If I5 (fool.com scraping) proves fragile in production, or if transcript coverage gaps in fool.com (some smaller tickers missing) become a real problem. |
| **IBKR Reuters Worldwide Fundamentals** | ~$5/mo (IBKR subscription) | Reuters-curated fundamentals XML via `reqFundamentalData` TWS call: company snapshot, financial statements, ratios, analyst estimates. Competitive with FMP but routed through the already-running TWS client. | If I3 (IBKR free snapshot/historical) leaves gaps in financial statements detail, or if Reuters' analyst estimates are materially better than what Finnhub + YFinance provide. |
| **IBKR Reuters real-time news (news tick 292)** | ~$1–5/mo | Real-time Reuters news bulletins via TWS news ticks. Live event-driven signal for the alerting flow. | If the LLM auto-explainer (slice A1) or risk-review (A2) shows latency-bound regret on news-driven moves — i.e. we miss windows because Finnhub's 30-day free-tier news isn't real-time. |
| **OpenBB premium providers** (Polygon ~$30/mo, Intrinio ~$50/mo) | $30–50+/mo | Real-time options chain (Polygon), institutional-grade fundamentals (Intrinio). | Only relevant if iguanatrader expands beyond fundamental-driven equity strategies (options trading, market-microstructure). Not on horizon. |

**Decision principle**: free first. Each paid option opens via a dedicated slice that quantifies *what specifically* we couldn't accomplish without it (concrete examples from journal entries or missed proposals), so the spend is justified by observed gaps rather than aspirational coverage.

---

## Related

- [`docs/runbooks/research-data-sources.md`](runbooks/research-data-sources.md) — per-source operational reference.
- [`docs/roadmap-llm-features.md`](roadmap-llm-features.md) — LLM features track (A0–A3, B). Depends on real `research_facts` content — this Ingestion Wave is its prerequisite.
- [ADR-015](adr/ADR-015-2026-04-28-openbb-sidecar-isolation.md) — OpenBB AGPL isolation rationale.
