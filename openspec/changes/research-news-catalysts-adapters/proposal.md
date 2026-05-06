## Why

Wave 3 of the iguanatrader MVP fans out four parallel research slices on top of the bitemporal fabric landed by R1 (`research-bitemporal-schema`, archived 2026-05-06). R3 owns the **Tier-B (snapshot collected) + Tier-C (bootstrap) source adapters** — the news / catalyst / governance / bars universe that complements R2's Tier-A native-PiT adapters (EDGAR, FRED, BLS, BEA) and R4's OpenBB sidecar isolation. Without R3, the synthesis layer (R5) has no news headlines, no FDA approvals, no insider screens, no governance baselines, no historical bars to feed methodologies — every brief would be EDGAR + FRED only and the "complete catalyst surface" promise of FR61–FR67 + FR77–FR79 would fail. Now is the right time because R1 is archived, the `SourcePort` Protocol is stable, and the 7-table research schema (`research_sources`, `symbol_universe`, `watchlist_configs`, `research_facts`, `research_briefs`, `corporate_events`, `analyst_ratings`) is ready to absorb adapter writes. R3 also ships the **4-tier scrape ladder** (ADR-017) that R2's Finviz scrape path and any future scrape-dependent slice will reuse.

## What Changes

- **9 source adapters** under `apps/api/src/iguanatrader/contexts/research/sources/` — each implements R1's `SourcePort` Protocol and persists facts via `ResearchRepository.insert_fact(draft)`. All inserts carry `source_id` referencing a row in `research_sources` with the canonical `pit_class` ('B' or 'C') per data-model §3.7. The `pit_class` value drives FR75 feature-availability gating in R5.
  - **Tier-1 webfetch (5 adapters)**: `finnhub.py` (news + sentiment + earnings calendar — FR61, FR62), `gdelt.py` (events / PESTEL signals — FR67), `openfda.py` (drug approvals — FR62), `wgi_world_bank.py` (governance indicators — FR67, FR77), `vdem.py` (democracy index — FR67, FR77).
  - **Tier-2 Playwright (2 adapters)**: `openinsider.py` (aggregated insider screens — FR63), `finviz_scrape.py` (analyst-rating screener + valuation overlays — FR64, FR77).
  - **Bars adapters (2 adapters)**: `ibkr_bars.py` (historical OHLCV via `ib_async`, primary — FR66), `yahoo_bars_fallback.py` (yfinance, fallback when IBKR unavailable — FR66).
  - **ESG single-source adapter** (best-effort): `yfinance_sustainability.py` (Sustainalytics-via-Yahoo — FR65). Persisted with explicit `metadata.is_esg_aggregate=true` flag so R5's feature_provider can identify ESG facts and the **CI assertion `test_no_esg_in_backtest`** can grep backtest feature builders to enforce FR75's ESG ban in backtest features.
- **4-tier scrape ladder** under `apps/api/src/iguanatrader/contexts/research/scraping/` per ADR-017 — `tier1_webfetch.py` (httpx + BS4), `tier2_playwright.py` (Chromium headless), `tier3_camoufox.py` (Firefox stealth via Camoufox MCP), `tier4_captcha.py` (Camoufox + paid 2Captcha solver, opt-in via per-tenant `scrape_tier_max ≤ 3` to disable). Each adapter declares its default tier + allowed fallbacks; the ladder escalates only when the previous tier raises `ScrapeBlockedError`. Cross-cutting helpers: `robots_check.py` (validates `robots.txt` programmatically per FR79 via `urllib.robotparser` + 24h cache) + `user_agent.py` (rotation pool with iguanatrader-identifying UA per FR79: `iguanatrader/<version> (+arturo6ramirez@gmail.com)`).
- **Rate-limiting + politeness**: per-source token-bucket limiters configured from `research_sources.metadata.rate_limit_config`; defaults — Finnhub free tier 60 req/min, GDELT 15-min refresh window, OpenFDA no auth + soft 240 req/min courtesy, OpenInsider 1 req/3s (FR79 floor), Finviz 1 req/3s + 30-min stale-while-revalidate cache to mitigate DOM brittleness.
- **`research_sources` catalogue rows** seeded by migration `0004_research_sources_tier_b_c.py` for the 9 source_ids: `finnhub`, `gdelt`, `openfda`, `openinsider`, `finviz_scrape`, `wgi_world_bank`, `vdem`, `ibkr_bars`, `yahoo_bars_fallback`, `yfinance_sustainability`. Each row carries `tier` (scrape ladder 1–4) + `pit_class` ('B' or 'C') + `enabled=true` + `metadata` JSONB with rate-limit config + retention hints.
- **Integration test** `apps/api/tests/integration/test_news_ingestion.py` — round-trip: GDELT API mock → fact lands in `research_facts` with correct `pit_class='B'` provenance; Finnhub news mock → second fact lands; both queryable via `as_of(symbol, at)` with bitemporal correctness. **Unit test** `apps/api/tests/unit/contexts/research/test_scrape_ladder.py` — given a tier-1 `ScrapeBlockedError`, ladder escalates to tier-2; given tier-3 success, no tier-4 attempt; tier-4 short-circuits when `scrape_tier_max=3`.
- **CI assertion** `apps/api/tests/unit/test_no_esg_in_backtest.py` — greps every Python file under `apps/api/src/iguanatrader/contexts/trading/` for ESG column reads (`esg.aggregate`, `is_esg_aggregate`, `value_esg_*`) — fails the build if any backtest feature builder references ESG facts. Implements FR75 enforcement at the test level since R3 ships before R5's feature_provider where the runtime gate also lives.
- **No R5 synthesis, no UI, no CLI** — R3 only plants adapters + ladder + sources catalogue rows. Route stubs remain 501 (R1 owns them).

## Capabilities

### New Capabilities

(none — `research` capability already exists; this slice adds delta requirements.)

### Modified Capabilities

- `research`: extends R1's bitemporal-schema capability with **9 Tier-B/C source adapters**, the **4-tier scrape ladder**, **politeness primitives** (`robots_check` + `user_agent` rotation), and the **ESG-ban-in-backtest CI assertion**. R1 shipped the schema + ports + repository + route stubs; R3 lands concrete `SourcePort` implementations + scraping infrastructure. No requirement from R1 is removed or changed in shape — only ADDED requirements per OpenSpec delta semantics.

## Impact

- **Affected code (R3-owned, write-allowed)**:
  - `apps/api/src/iguanatrader/contexts/research/sources/{finnhub,gdelt,openfda,openinsider,finviz_scrape,wgi_world_bank,vdem,ibkr_bars,yahoo_bars_fallback,yfinance_sustainability}.py` (NEW × 10).
  - `apps/api/src/iguanatrader/contexts/research/scraping/{__init__,tier1_webfetch,tier2_playwright,tier3_camoufox,tier4_captcha,robots_check,user_agent,errors,ladder}.py` (NEW × 9).
  - `apps/api/src/iguanatrader/migrations/versions/0004_research_sources_tier_b_c.py` (NEW) — seeds the 10 catalogue rows; reversible (deletes them in `downgrade()`); `down_revision = "0003"` chained from R1's migration.
  - `apps/api/tests/integration/test_news_ingestion.py` (NEW).
  - `apps/api/tests/unit/contexts/research/test_scrape_ladder.py` (NEW).
  - `apps/api/tests/unit/contexts/research/test_sources_*.py` (NEW × 9 — one per adapter, mocking the underlying HTTP / library client).
  - `apps/api/tests/unit/test_no_esg_in_backtest.py` (NEW) — repo-wide grep CI assertion.
  - `apps/api/README.md` — append "Research adapters (R3)" subsection cross-referencing the 9 adapters + scrape ladder.
  - `docs/gotchas.md` — append slice-specific entries (rate-limit gotchas, Finviz DOM brittleness, GDELT 15-min refresh, ESG metadata flag).
- **Affected code (read-only consumed from R1, slice 2/3/5)**:
  - `iguanatrader.contexts.research.ports.SourcePort` + `ResearchFactDraft` (R1).
  - `iguanatrader.contexts.research.repository.ResearchRepository.insert_fact` (R1).
  - `iguanatrader.contexts.research.errors.MissingProvenanceError` (R1 — slice-local; raised inside adapters when provenance is incomplete).
  - `iguanatrader.shared.kernel.HeartbeatMixin` + `iguanatrader.shared.backoff` (slice 2 — IBKR bars adapter inherits to survive transient TWS disconnects).
  - `iguanatrader.persistence.session::session_var` (slice 3).
  - `iguanatrader.shared.errors.IguanaError` hierarchy (slice 2 — `ScrapeBlockedError` + `RateLimitedError` extend per slice-local `contexts/research/scraping/errors.py`).
- **Affected APIs**: none — R3 adds NO routes, NO SSE streams, NO CLI commands. Adapters are invoked by R5's scheduler (after R3+R5 land) or by integration tests.
- **Affected dependencies** — added to root `pyproject.toml` under `[tool.poetry.group.research]` (out-of-tree from API hot path):
  - `playwright>=1.42` + Chromium browser binary (Tier-2 ladder; CI installs via `playwright install chromium`).
  - `httpx[http2]>=0.27` (already present from slice 1; HTTP/2 enables Finnhub keep-alive efficiency).
  - `beautifulsoup4>=4.12` (Tier-1 HTML parsing for Finviz fallback paths; also used by `robots_check`).
  - `lxml>=5.0` (BS4 parser backend).
  - `yfinance>=0.2.40` (Yahoo bars fallback + ESG sustainability — pinned to a known-stable minor; documented as "Yahoo undocumented internal API; tolerate breakage" gotcha).
  - `ib_async>=1.0.3` (IBKR bars; same dep T2 will pull — declared once at root).
  - `tenacity>=8.2` (per-source backoff orchestration; complements `iguanatrader.shared.backoff`).
  - Camoufox MCP client (Tier-3) — invoked via subprocess to the existing project MCP server; **NOT** a Python dep.
  - 2Captcha (Tier-4) — `2captcha-python>=1.5` BUT **gated by feature flag** `scrape_tier_max=4`; default tenant config caps at tier 3 → dependency only loads if tier 4 ever fires. Per-call cost ~$0.003 documented in observability.
  - GDELT BigQuery client — `google-cloud-bigquery>=3.20` (R3's only Google-cloud dependency; out-of-tree group; FR67 partitioned-by-date+ticker query stays under 100 GB/mo free tier per ADR caveat #4).
- **Prerequisites**:
  - `research-bitemporal-schema` (R1, archived 2026-05-06) — `SourcePort`, `ResearchRepository`, `ResearchFactDraft`, error hierarchy.
  - Transitively: `shared-primitives` (slice 2 — `HeartbeatMixin`, `backoff`, `IguanaError`), `persistence-tenant-enforcement` (slice 3 — Alembic env, `session_var`), `api-foundation-rfc7807` (slice 5 — error renderer for any future R3-raised exceptions surfaced through routes).
- **Capability coverage** (per `docs/openspec-slice.md` row R3):
  - **FR61** — News + sentiment via GDELT DOC 2.0 + Finnhub free tier with ticker-tagged sentiment scoring → `gdelt.py` + `finnhub.py`.
  - **FR62** — Calendars + catalysts (earnings dates, FDA approvals, FOMC schedule, ex-dividend, splits, M&A) → `finnhub.py` (earnings calendar) + `openfda.py` (drug approvals) + `gdelt.py` (M&A signals from event stream). `corporate_events` table fed.
  - **FR63** — Insider transactions → SEC Form 4 is **R2's** scope; R3 owns OpenInsider aggregated screens (top buyers/sellers across universe) via `openinsider.py` (Tier-2 scrape).
  - **FR64** — Analyst ratings → `finnhub.py` (consensus) + `finviz_scrape.py` (Tier-2 ratings screener); `yfinance` recommendations also routed via `yfinance_sustainability.py` companion path (R3 keeps yfinance to a single adapter for AGPL-boundary clarity — OpenBB-isolated yfinance is R4's scope).
  - **FR65** — ESG aggregate scores → `yfinance_sustainability.py` (best-effort, single-source caveat documented in `metadata.is_esg_aggregate=true` flag); CI assertion `test_no_esg_in_backtest` enforces FR75 ban on ESG in backtest features.
  - **FR66** — Historical bars → `ibkr_bars.py` (primary) + `yahoo_bars_fallback.py` (fallback). Local parquet cache lives under `data/research_cache/<source_id>/<yyyy-mm>/` per R1's hybrid-payload scheme.
  - **FR67** — Geopolitics / PESTEL → `gdelt.py` (events, BigQuery partitioned by date+ticker) + `wgi_world_bank.py` (governance) + `vdem.py` (democracy index academic dataset).
  - **FR75** — Tier-based feature availability ENFORCEMENT for the ESG ban in backtest features → `test_no_esg_in_backtest.py` CI assertion. The runtime FR75 gate (Tier-A/B/C history-availability check) lives in R5's `feature_provider`; R3 only enforces the ESG carve-out.
  - **FR77** — 4-tier scrape ladder → `scraping/{tier1_webfetch,tier2_playwright,tier3_camoufox,tier4_captcha}.py` + `ladder.py` orchestrator + `errors.py` (ScrapeBlockedError/RateLimitedError).
  - **FR78** — No external redistribution — covered by `data/research_cache/` already gitignored from slice 1 + `THIRD_PARTY_NOTICES.md` updated to attribute the 9 source providers; R3 adds attribution lines but does NOT export raw data anywhere.
  - **FR79** — Identifying User-Agent + robots.txt + 1 req/3s minimum → `user_agent.py` (UA pool with iguanatrader identifier) + `robots_check.py` (urllib.robotparser + 24h cache) + per-source rate limiters configured ≥ 1 req/3s for all scrape paths.
- **Out of scope** (per `docs/openspec-slice.md` row R3 + Wave 3 boundaries):
  - SEC EDGAR / Form 4 / 10-K / FRED / BLS / BEA → R2 (`research-edgar-fred-adapters`).
  - OpenBB Platform integration (yfinance via OpenBB sidecar, AGPL boundary) → R4 (`openbb-sidecar-container`). R3's `yfinance_sustainability.py` is a **best-effort single-source ESG path** that does NOT touch the OpenBB sidecar; it imports `yfinance` directly inside the Apache+CC monolith — acceptable per ADR-015 because yfinance itself is Apache-2.0 (only OpenBB Platform is AGPL).
  - LLM synthesis, methodology profiles, citation resolver, audit-trail renderer, feature_provider runtime tier-gate → R5 (`research-brief-synthesis`).
  - SvelteKit research pages + components → R5 + W1.
  - CLI subcommands (`refresh-source <id>`, `health-check`) → deferred to R5 + O2 orchestration.
  - SSE research stream → R5.
  - Hindsight bridge → R6.
  - Monthly sha256 integrity check on `data/research_cache/` payloads → v2 follow-up.
  - Paid Camoufox+captcha tier 4 invocation in production by default — shipped behind a per-tenant feature flag (`scrape_tier_max`); MVP default is tier 3.
