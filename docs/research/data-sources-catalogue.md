---
type: research
project: iguanatrader
created: 2026-04-28
updated: 2026-04-28
scope: free-and-low-cost-data-sources-for-us-equities-knowledge-repository
sources_researched: 60
---

# Data Sources Catalogue — iguanatrader

> Research artifact. Surveys free / low-cost data sources for the per-ticker knowledge repository (fundamentals, macro, news/sentiment, catalysts, ratings, insider/institutional, technicals, sector, ESG, PESTEL). US equities focus (IBKR broker). Watchlist 5–50 tickers; secondary universe SP500 + Russell 2000.

> **Constraints recap.** Provenance non-negotiable (source URL + retrieval timestamp + method per fact). Show-your-work for calculations. Backtest determinism → prefer point-in-time. Web scraping fallback ladder available: WebFetch → Playwright → Camoufox MCP.

> **Verification posture.** Numbers/limits below were verified via WebSearch against vendor pages and recent (2025–2026) third-party reviews. Anywhere a number could not be pinned to a vendor docs URL with high confidence, this file says so explicitly. Treat all rate limits as “verify in code” at integration time — vendors change them silently.

## 0 Executive summary

### 0.1 MVP recommendations matrix (one source per category, free unless noted)

| Category | Primary (MVP) | Secondary / fallback | Why primary |
|---|---|---|---|
| 1 SEC filings | **SEC EDGAR official APIs** + `edgartools` lib | `sec-edgar-downloader` for raw text | Free, no key, point-in-time, MIT lib |
| 2 Macro | **FRED** (`fredapi`), **BLS** (key), **BEA** (key) | World Bank `wbgapi`; OECD/IMF/ECB SDMX as needed | Free, mature Python libs, US-relevant |
| 3 Fundamentals | **EDGAR XBRL CompanyFacts** (canonical) + **`yfinance`** (current snapshot only) | FMP free tier (5y history), Finnhub free tier | EDGAR is the only point-in-time source; yfinance for ratios convenience |
| 4 News + sentiment | **GDELT DOC 2.0** (free, no key) + **Finnhub** free tier | Marketaux 100/day; NewsAPI 100/day delayed; Tiingo News (paid only) | GDELT global coverage + Finnhub built-in sentiment |
| 5 Calendars/catalysts | **Finnhub earnings/economic calendar** (free), **openFDA** (free), **FOMC dates** (`alfred.stlouisfed.org`) | yfinance earnings dates; SEC 8-K stream for M&A | Free, structured, no scraping |
| 6 Insider / institutional | **EDGAR Form 4 / 13F via `edgartools`** | OpenInsider scrape (Playwright) for aggregated screens | Authoritative + free |
| 7 Analyst ratings | **`yfinance` recommendations** + **Finnhub** consensus | Finviz scrape (TOS-grey, Playwright) | Free; Zacks paid |
| 8 ESG | **`yfinance` sustainability** (Sustainalytics/Morningstar via Yahoo) | MSCI ESG public letter-grade tool (scrape) | Free aggregation; SEC climate rule withdrawn |
| 9 Sector / industry | **GICS via SP500/Russell constituents** (Wikipedia + ETF holdings); **SPDR sector ETFs** | yfinance sector field; OpenBB classification | Free, human-readable |
| 10 Technicals | **Existing parquet bars cache + `pandas-ta` / TA-Lib** | vectorbt for backtesting | Already in stack |
| 11 PESTEL / geopolitics | **GDELT events (BigQuery)**, **WGI** (World Bank), **V-Dem** | ACLED (registration), Fragile States Index | Free academic + bulk |
| 12 Aggregator (optional) | **OpenBB Platform** (AGPL-3.0 — see warning §12) | direct provider libs only | One adapter for ~100 sources |

### 0.2 Top-line judgments

1. **EDGAR is the spine.** It is the only fully-free, fully-point-in-time (revisions tracked), high-coverage US equities fundamentals source. Build the knowledge repo around `edgartools` first; everything else is enrichment.
2. **yfinance is unavoidable but compromised.** Free, comprehensive, but (a) operates in Yahoo TOS grey area, (b) frequently breaks when Yahoo changes their internal endpoints, (c) is **not** point-in-time (always returns latest snapshot). Use it for current ratios, sector tags, ESG aggregates, analyst recommendations — never as historical truth.
3. **GDELT > NewsAPI for coverage; Finnhub > both for stock-tagged sentiment.** GDELT is free, no-key, global, with built-in sentiment tone. Finnhub adds proper ticker tagging.
4. **OpenBB is tempting but watch the licence.** AGPL-3.0 is incompatible with iguanatrader's Apache-2.0 + CC-BY-4.0 stance for any redistributed binary. Either keep OpenBB strictly server-side (AGPL ≠ blocking for self-hosted research tools you don't redistribute) or use the underlying providers directly.
5. **Paid only when free demonstrably fails.** The €50/mo budget is more than enough for: a paid Polygon Stocks Starter ($29) for clean intraday + news, or Finnhub Personal ($9.99) — both unlock comprehensive coverage. But MVP can ship with €0 spend.

### 0.3 Cost matrix snapshot (USD, monthly)

| Source | Free tier | Recommended paid tier | Cost |
|---|---|---|---|
| SEC EDGAR | unlimited | n/a | $0 |
| FRED / BLS / BEA / World Bank / OECD / IMF / BIS / ECB | unlimited (with keys) | n/a | $0 |
| yfinance (Yahoo) | unlimited but unstable | n/a | $0 |
| FMP | 250 calls/day, 5y history | Starter (300 calls/min, full history) | ~$22 |
| Alpha Vantage | 25 calls/day | Premium 75/min | $50 |
| Finnhub | 60/min, US only | Personal (300/min, fundamentals++) | $9.99 |
| Polygon | 5 calls/min, 2y data | Stocks Starter (unlimited) | $29 |
| Twelve Data | 800 credits/day | Grow plan | $29 |
| EODHD | 20/day demo | All-in-One | $79.99 |
| Marketaux | 100/day | Standard | $49 |
| NewsAPI.org | 100/day delayed 24h | Business | $449 |
| GDELT | unlimited (rate-limit-friendly) | n/a | $0 |
| OpenFDA | 1k/day no key, 120k/day with free key | n/a | $0 |
| ACLED | unlimited (academic) | n/a | $0 |

---

## 1 SEC EDGAR — official US filings

### 1.1 SEC EDGAR REST APIs (data.sec.gov)

- **Name**: SEC EDGAR APIs
- **URL**: `https://www.sec.gov/search-filings/edgar-application-programming-interfaces` ; data hosts at `https://data.sec.gov/`
- **Provider**: U.S. Securities and Exchange Commission (federal government)
- **License/TOS**: Public-domain US gov data; fair-use access policy at `https://www.sec.gov/os/accessing-edgar-data` and `https://www.sec.gov/about/developer-resources`
- **Auth**: No API key. **MUST** send a `User-Agent` header identifying the requester + contact email. Missing UA → 403 Forbidden.
- **Rate limits**: SEC fair-use cap is **10 requests/second per IP** aggregate across all SEC hosts. Exceed → HTTP 429; persistent abuse → IP block.
- **Coverage**: Every US public registrant since EDGAR digitisation (~1993–1996 depending on form). 10-K, 10-Q, 8-K, S-1, 13F-HR, 13D/G, Form 3/4/5, DEF 14A, 20-F, 40-F, N-CSR, N-PORT, 144, etc. — 500+ form types.
- **Historical depth**: Filings from 1993 onward (some earlier paper filings scanned but not XBRL-tagged).
- **Point-in-time**: **Yes — the gold standard.** Filings are immutable once accepted; amendments are separate filings (10-K/A). XBRL CompanyFacts API includes accession numbers and filed dates so you can reconstruct what-was-known-when.
- **Format**: HTML / TXT / XBRL (XML) for documents; JSON via `data.sec.gov` for company submissions, company facts, frames.
- **Key endpoints**:
  - `https://data.sec.gov/submissions/CIK##########.json` — filing history per company (10-digit zero-padded CIK).
  - `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` — every XBRL-tagged fact a company has ever filed (revenues, assets, EPS …) in one JSON response. Includes accession + filing date per data point.
  - `https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/{tag}.json` — single-concept time series.
  - `https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/CY####Q#.json` — cross-sectional snapshot of a tag for a period (perfect for industry comps).
- **Bulk**: `https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip` (mirrors the per-CIK JSON for the whole universe). Refreshed nightly.
- **Pros**:
  - Authoritative; legally definitive source of truth for fundamentals.
  - True point-in-time. Accession numbers + filing timestamps embedded.
  - Free, no key, no quota beyond fair-use rps cap.
  - Stable URL scheme — excellent for long-term provenance citations.
- **Cons**:
  - XBRL is ugly; tag heterogeneity across filers requires concept normalisation (use `edgartools` or pre-built mappings).
  - 8-K M&A / FDA-trial detail lives in free-form prose — needs LLM extraction.
  - No real-time push; you poll. (Submission feed RSS exists but for filings, not events.)
- **Recommendation**: **MVP — core spine of the knowledge repo.**
- **Provenance integrity**: Excellent. URLs of the form `https://www.sec.gov/Archives/edgar/data/<CIK>/<accession-no-dashes>/<filename>` are immutable and citable forever.

### 1.2 Python libraries — comparison

| Library | Stars | License | Last release | Best for |
|---|---|---|---|---|
| **`edgartools`** ([dgunning/edgartools](https://github.com/dgunning/edgartools)) | 2.1k | MIT | v5.30.0 (2026-04-15) | **Recommended.** Typed Python objects per filing, XBRL→pandas, Form 4 / 13F parsing, MCP server included. Industry-aware concept mapping (32k filings ingested). |
| `sec-edgar-downloader` ([jadchaar](https://github.com/jadchaar/sec-edgar-downloader)) | 678 | MIT | v5.1.0 (2026-02-02) | Simple bulk download by ticker/CIK. No parsing. Good for "give me every 10-K text". |
| `sec-edgar-api` ([jadchaar](https://github.com/jadchaar/sec-edgar-api)) | smaller | MIT | active | Thin wrapper around `data.sec.gov`. |
| `python-edgar` / `sec-edgar` (older) | varies | MIT/Apache | semi-active | Older, less actively maintained — skip. |
| `sec-api-python` ([SEC-API-io](https://github.com/janlukasschroeder/sec-api-python)) | active | commercial | ongoing | **Paid SaaS wrapper** (sec-api.io). Real-time stream, full-text search across 20M filings, 500+ form types, up to 40 files/sec. Free key with limited quota; paid plans from ~$100/mo. Useful only if real-time alerting becomes a v1.5+ requirement. |

**Verdict.** Pin `edgartools` as the MVP integration point. Wrap it behind iguanatrader's source-abstraction layer so we can later swap to direct REST or sec-api.io if we need streaming.

---

## 2 Macro / economic indicators

All sources below are free, US-government or international-organisation hosted, and most have mature Python wrappers. None are point-in-time-aware out of the box except FRED/ALFRED (where ALFRED is the point-in-time variant) — for backtesting, prefer ALFRED-via-`fredapi` over plain FRED queries.

### 2.1 FRED — Federal Reserve Bank of St. Louis

- **URL**: `https://fred.stlouisfed.org/docs/api/fred/`
- **License/TOS**: `https://fred.stlouisfed.org/docs/api/terms_of_use.html` — free, attribution required, no redistribution of bulk dumps.
- **Auth**: Free 32-char API key (instant signup at `https://fred.stlouisfed.org/docs/api/api_key.html`).
- **Rate limits**: Vendor docs are vague ("rate limited; contact us if you need more"). Community-confirmed practical limit: **~120 requests/minute** (referenced in `fredr` R-package source and multiple Python wrappers). HTTP 429 on excess.
- **Coverage**: 800k+ economic time series (US-centric: GDP, CPI, unemployment, yield curves, money supply, regional Fed indicators; also IMF / OECD / Eurostat re-publications).
- **Historical depth**: Series-dependent; many go back to 1947+ (some to the 1800s).
- **Point-in-time**: **Yes via ALFRED** (Archival FRED). Same API, prefix `vintage_dates` parameter or use ALFRED-specific calls. Critical for bias-free backtesting of macro regime models.
- **Format**: JSON or XML.
- **Python lib**: `fredapi` ([mortada/fredapi](https://github.com/mortada/fredapi)) — Apache-2.0 / BSD-style, latest 0.5.2. Includes ALFRED helpers for vintage data. `pyfredapi` is a more modern alternative.
- **Pros**: Best macro source for US; mature; free; ALFRED gives point-in-time.
- **Cons**: International series sometimes lag the original publisher.
- **FOMC dates**: ALFRED release calendar at `https://alfred.stlouisfed.org/release/downloaddates?rid=101` gives all FOMC press release release dates programmatically — use this to build the FOMC catalyst calendar.
- **Recommendation**: **MVP.**

### 2.2 BLS — Bureau of Labor Statistics

- **URL**: `https://www.bls.gov/developers/`
- **License**: Free, public-domain US gov data.
- **Auth**: Free key (registration required for v2). Email + org name only.
- **Rate limits**: v2 registered → **500 queries/day**, 50 series per request, up to 20 years per series. v1 unregistered → 25 queries/day, 10 series, 10 years.
- **Coverage**: CPI, PPI, unemployment, JOLTS, employment cost index, productivity, earnings, regional. US labour-market gold standard.
- **Point-in-time**: No native vintage support; revisions are not retained via the API — you must snapshot.
- **Format**: JSON.
- **Python**: official `requests` patterns documented; community lib `blsAPI` (R; Python use direct `requests`).
- **Recommendation**: **MVP** for inflation/employment macro features.

### 2.3 BEA — Bureau of Economic Analysis

- **URL**: `https://apps.bea.gov/api/`
- **License**: Free public-domain.
- **Auth**: Free key (`https://apps.bea.gov/API/signup/index.cfm`), instant email.
- **Rate limits**: **100 requests/min, 100 MB/min, 30 errors/min** per key. Exceed → HTTP 429 + 1-hour timeout.
- **Coverage**: GDP, NIPA, regional (state/MSA), industry, international transactions, trade.
- **Format**: JSON or XML.
- **Recommendation**: MVP for GDP / sector accounts (industry-rotation features).

### 2.4 World Bank Open Data

- **URL**: `https://data.worldbank.org/` ; Indicators API at `https://api.worldbank.org/v2/`
- **License**: CC-BY-4.0 (most series). Excellent for redistribution.
- **Auth**: None.
- **Rate limits**: No published hard limit. Be polite (~1 rps); the libraries below auto-chunk.
- **Python libs**:
  - **`wbgapi`** ([tgherzog/wbgapi](https://github.com/tgherzog/wbgapi)) — MIT, modern, pythonic, World Bank's own staff endorsement.
  - `wbdata` — older but stable.
- **Coverage**: 16k+ indicators, 200+ countries. Global development / governance / WGI.
- **Recommendation**: v1.5+ (international macro, WGI for PESTEL).

### 2.5 OECD

- **URL**: `https://data.oecd.org/api/` ; SDMX endpoint `https://sdmx.oecd.org/public/rest/`
- **Note**: Old `stats.oecd.org` decommissioned 2024-07-01 — many tutorials online reference dead URLs.
- **License**: OECD Terms (free; attribution; no commercial redistribution of bulk).
- **Auth**: None.
- **Rate limits**: Not published; OECD asks for "responsible use".
- **Format**: SDMX-JSON / XML / CSV.
- **Python**: `pandasdmx` / `sdmx1` — works against any SDMX provider.
- **Recommendation**: v2 (international comparisons; not core for US-only watchlist).

### 2.6 BIS — Bank for International Settlements

- **URL**: `https://data.bis.org/` ; SDMX `https://stats.bis.org/api-doc/v1/`
- **License**: BIS Terms (free, attribution).
- **Auth**: None.
- **Rate limits**: Not formally published.
- **Coverage**: Cross-border banking, debt securities, derivatives, property prices, FX, central-bank policy rates. Bulk download available at `https://data.bis.org/bulkdownload`.
- **Recommendation**: v2 (useful for credit-cycle macro features later).

### 2.7 ECB — European Central Bank Data Portal

- **URL**: `https://data.ecb.europa.eu/help/api/overview` ; SDMX 2.1 RESTful.
- **License**: Free, attribution.
- **Rate limits**: Not formally published.
- **Recommendation**: v2 (Eurozone — relevant only for international v2 expansion).

### 2.8 IMF

- **URL**: `https://data.imf.org/en/Resource-Pages/IMF-API` ; SDMX 2.1 / 3.0.
- **License**: Free.
- **Rate limits**: Community-reported **10 calls / 5 seconds**; max 3000 series per response.
- **Recommendation**: v2.

### 2.9 Macro consolidation table

| Source | US-relevance | Free | Auth | Lib | Point-in-time | MVP? |
|---|---|---|---|---|---|---|
| FRED | High | Yes | Free key | `fredapi` | Yes (ALFRED) | MVP |
| BLS | High | Yes | Free key | direct REST | No | MVP |
| BEA | High | Yes | Free key | direct REST | No | MVP |
| World Bank | Medium | Yes | None | `wbgapi` | No | v1.5+ |
| OECD | Medium | Yes | None | `pandasdmx` | No | v2 |
| BIS | Low (US) | Yes | None | direct SDMX | No | v2 |
| ECB | Low (US) | Yes | None | direct SDMX | No | v2 |
| IMF | Low (US) | Yes | None | `imf.data` (R) / direct | No | v2 |

---

## 3 Fundamentals (current snapshot + ratios)

> EDGAR XBRL CompanyFacts (§1.1) is the **canonical** historical fundamentals source for iguanatrader. Everything below is for current-snapshot convenience or as fallback when a filer's XBRL is messy. None of the providers below are reliably point-in-time on the free tier.

### 3.1 yfinance (Yahoo Finance unofficial)

- **URL**: `https://github.com/ranaroussi/yfinance`
- **Provider**: Ran Aroussi (open source); data is from Yahoo Finance.
- **License**: Apache-2.0 (the library). Underlying Yahoo data is governed by Yahoo's TOS — see TOS warnings below.
- **Auth**: None.
- **Rate limits**: Not officially capped, but Yahoo aggressively rate-limits / soft-bans IPs that scrape too fast. Use exponential backoff; consider a rotating proxy if scaling beyond ~50 tickers/min.
- **Coverage**: Quotes, OHLCV, financials (annual + quarterly), balance sheet, cash flow, earnings, recommendations, calendar, holders, ESG sustainability scores (Sustainalytics via Yahoo), options chains, news headlines, sector/industry tags, fast info.
- **Historical depth**: Prices back to 1970s for some tickers. Financials usually 4–8 quarters / 4 years.
- **Point-in-time**: **No.** Always returns "as of now" snapshot. Fundamentals returned are restated values, not as-reported.
- **Format**: pandas DataFrame.
- **GitHub**: 23.2k stars, Apache-2.0, latest v1.3.0 (2026-04-16) — actively maintained but breaks ~3–6×/year when Yahoo changes endpoints.
- **TOS posture**: Yahoo's Terms of Service forbid republication of their data. yfinance authors say "research/educational use only; not affiliated/endorsed by Yahoo". This is the canonical web-scraping grey-area library — heavily used industry-wide despite the friction. iguanatrader is a personal research tool, so personal use is defensible; **do not redistribute Yahoo-derived data products** if iguanatrader ever goes commercial.
- **Pros**: Free, comprehensive, single-call convenience, large community.
- **Cons**: Unstable, no point-in-time, TOS grey, sometimes silent data errors.
- **Recommendation**: **MVP for current-snapshot enrichment** (sector tag, current ratios, recommendations, ESG, options chain). Never as historical truth.

### 3.2 Financial Modeling Prep (FMP)

- **URL**: `https://site.financialmodelingprep.com/`
- **License**: Per `https://site.financialmodelingprep.com/terms-of-service`. Free tier non-commercial.
- **Auth**: Free key.
- **Rate limits (Basic free)**: **250 calls/day**; EOD only; ~5 years history; 500 MB/30-day rolling bandwidth cap.
- **Paid Starter**: ~$22/mo; 300 calls/min, full history.
- **Coverage**: 150+ endpoints; income statement, balance sheet, cash flow (annual/quarterly/TTM), key metrics, ratios, enterprise values, segments, executives, 13F, earnings calendar.
- **Point-in-time**: Restated by default. Has "as-reported" endpoints (paid).
- **Recommendation**: v1.5+ if EDGAR XBRL parsing proves too painful. Otherwise skip — EDGAR is free and authoritative.

### 3.3 Alpha Vantage

- **URL**: `https://www.alphavantage.co/`
- **License**: Free non-commercial; commercial requires premium.
- **Auth**: Free key.
- **Rate limits (free)**: **25 requests/day**, 5/min. Hard cap. Premium tiers from $50/mo unlock to 75/min and beyond.
- **Coverage**: Quotes, fundamentals (overview/income/balance/cash flow), technicals, news (paid), forex, crypto.
- **Point-in-time**: No.
- **Python**: `alpha_vantage` ([RomelTorres/alpha_vantage](https://github.com/RomelTorres/alpha_vantage)) — MIT.
- **Verdict**: 25/day free is too tight for a 50-ticker watchlist daily refresh. **Skip** unless you specifically need a feature only AV provides (e.g. their economic indicators wrapper).

### 3.4 Twelve Data

- **URL**: `https://twelvedata.com/`
- **Free tier**: **8 credits/min, 800/day**. Income statement = 100 credits per call → effectively ~8 fundamentals calls/day.
- **Coverage**: Equities, FX, crypto, fundamentals.
- **Point-in-time**: No.
- **Verdict**: Skip for fundamentals (too expensive in credits). Could be useful for intraday WebSocket if iguanatrader needs that later.

### 3.5 Polygon.io

- **URL**: `https://polygon.io/`
- **Free tier**: **5 req/min**, 2 years of historical daily data, end-of-day only, 15-min delayed quotes.
- **Stocks Starter**: $29/mo — unlimited rate, full history.
- **Coverage**: US-only, but excellent intraday quality. Aggregates, trades, quotes, news (free tier includes news with 5/min cap), splits, dividends, ticker reference.
- **Point-in-time**: News + reference are timestamped; financials via their `vX/reference/financials` are filing-dated → **partial point-in-time**.
- **Python**: `polygon-api-client` (Polygon official, MIT).
- **Recommendation**: **Paid Starter ($29) is the single best price/quality upgrade** if you need clean intraday US data. For MVP free tier — skip.

### 3.6 Finnhub

- **URL**: `https://finnhub.io/`
- **Free tier**: **60 calls/min** (30/sec internal cap); US stocks; basic fundamentals; SEC filings; company news; built-in news sentiment; earnings calendar; economic calendar; up to 50 WebSocket symbols.
- **Personal**: $9.99/mo unlocks deeper fundamentals + global.
- **Python**: `finnhub-python` ([Finnhub-Stock-API/finnhub-python](https://github.com/Finnhub-Stock-API/finnhub-python)) — Apache-2.0.
- **Point-in-time**: No.
- **Recommendation**: **MVP for news + sentiment + earnings calendar**. Free tier is the most generous in this category.

### 3.7 EODHD

- **URL**: `https://eodhd.com/`
- **Free tier**: 20 calls/day (after registration); demo key for 5 specific tickers (AAPL.US, TSLA.US, VTI.US, AMZN.US, BTC-USD.CC, EURUSD.FOREX) with no limits.
- **All-In-One**: $79.99/mo.
- **Coverage**: Strong fundamentals depth (30+ years for major US, 10y for minor; 70+ exchanges).
- **Recommendation**: Skip for MVP. Useful if iguanatrader expands to non-US (v2).

### 3.8 Stooq

- **URL**: `https://stooq.com/db/h/`
- **Free**: bulk CSV downloads. **No API.** Since 2020-12-10, captcha required for the manual download UI → fully automated daily fetches no longer reliable.
- **Recommendation**: Useful only as a one-shot bootstrap to seed historical OHLCV. Not part of the live pipeline.

### 3.9 Fundamentals consolidation table

| Source | Free tier daily-watchlist (50 tickers) feasible? | History | Point-in-time? | MVP? |
|---|---|---|---|---|
| EDGAR XBRL | Yes (10 rps) | 1993+ | **Yes** | **Yes (canonical)** |
| yfinance | Yes (best-effort) | varies | No | Yes (snapshot only) |
| FMP free | Marginal (250/day) | 5 y | No | Backup |
| Finnhub free | Yes (60/min) | varies | No | Yes (news/calendar) |
| Polygon free | No (5/min) | 2 y | Partial | No (paid Starter is great) |
| Alpha Vantage free | No (25/day) | varies | No | Skip |
| Twelve Data free | Marginal | varies | No | Skip |
| EODHD free | No (20/day) | 30 y (paid) | No | v2 |

---

## 4 News + sentiment

### 4.1 GDELT Project (Global Database of Events, Language, and Tone)

- **URL**: `https://www.gdeltproject.org/` ; DOC 2.0 API at `https://api.gdeltproject.org/api/v2/doc/doc`
- **Provider**: GDELT Project (academic / Google supported).
- **License**: CC-BY-4.0 (data are free for use including commercial; attribution required).
- **Auth**: **None.**
- **Rate limits**: Soft (vendor reserves the right to rate-limit; in practice, ~1 req/sec is fine for DOC 2.0; bulk via Google BigQuery has BigQuery's standard quotas).
- **Coverage**: Worldwide news, broadcast, web in 100+ languages, since 2015 for GDELT 2.0; events DB back to 1979. **3.6 TB GKG dataset**.
- **Endpoints**:
  - DOC 2.0: full-text article search (last ~3 months guaranteed).
  - GKG 2.0 (Global Knowledge Graph): tone/themes/entities; available in BigQuery `gdelt-bq.gdeltv2.gkg`.
  - Events 2.0: CAMEO-coded events; available in BigQuery.
- **Point-in-time**: **Yes** — every article has its publish timestamp; GDELT updates every 15 minutes.
- **Format**: JSON / CSV / BigQuery.
- **Python lib**: `gdelt-doc-api` ([alex9smith](https://github.com/alex9smith/gdelt-doc-api)) for DOC 2.0; `gdelt` PyPI lib for older Events 1.0.
- **Pros**: Massive scale, free, no key, multilingual, sentiment tone built in (Goldstein scale + tone score).
- **Cons**: Article-tagging is geographic/event-based, not ticker-based — you need a name→entity map. Heavy compute for full GKG analysis (use BigQuery, not local).
- **Recommendation**: **MVP for global news / geopolitics / PESTEL signals.** Pair with Finnhub for ticker-tagged stock-specific news.
- **Provenance**: Excellent — every record has source URL + timestamp.

### 4.2 Finnhub News + Sentiment

- See §3.6. News endpoints `/company-news` (free) return article URL + headline + summary + datetime + ticker tag + sentiment score (`bullish`/`bearish`/`neutral` + numeric). 60 req/min free.
- **Point-in-time**: Yes (article timestamps).
- **Recommendation**: **MVP**. Best free ticker-tagged sentiment for US equities.

### 4.3 Marketaux

- **URL**: `https://www.marketaux.com/`
- **Free**: 100 req/day; full sentiment analysis included.
- **Paid**: from $49/mo.
- **Coverage**: 5000+ sources, 30+ languages, entity-level sentiment.
- **Recommendation**: Backup. 100/day caps it for a 5–10 ticker pilot but not a 50-ticker daily refresh.

### 4.4 NewsAPI.org

- **URL**: `https://newsapi.org/`
- **Free Developer**: **100 req/day, articles delayed 24 hours, non-commercial.**
- **Business**: $449/mo.
- **Recommendation**: Skip — 24-h delay is fatal for catalyst monitoring; price gap to commercial is enormous.

### 4.5 GNews

- **URL**: `https://gnews.io/`
- **Free**: 100 req/day, max 1 req/sec, dev/test only (no commercial).
- **Recommendation**: Skip; same shape as NewsAPI but more restrictive licence.

### 4.6 Tiingo News

- **URL**: `https://www.tiingo.com/`
- **Free tier**: News API **not included**. Free covers limited prices and 5 y of fundamentals.
- **Paid**: from $10/mo for power, news add-on.
- **Recommendation**: v1.5+ if Finnhub coverage proves insufficient.

### 4.7 Polygon News

- See §3.5. Free tier news endpoint shares the 5/min cap. Paid Starter unlocks unlimited.
- **Recommendation**: Bundled in if you take the paid Polygon Starter.

### 4.8 Common Crawl

- **URL**: `https://commoncrawl.org/`
- **License**: Free, public-domain index; raw WARCs on AWS S3.
- **Auth**: None for public S3 / index.
- **Rate limits**: None on S3 (egress costs apply if requestor pays out).
- **Format**: WARC + CDXJ index.
- **Use case**: Historical news archive backfills (find articles about a ticker before a known event). Heavy compute — best run as Athena over the CDX index, not via Python loops.
- **Recommendation**: v2+ research backfill only. Not for live pipeline.

### 4.9 Perplexity API (already in stack)

- Use for on-demand summarisation / fact-extraction with grounded citations. Not a primary news source — a layer on top of the above.

### 4.10 News consolidation table

| Source | Free | Sentiment | Ticker-tagged | Point-in-time | MVP? |
|---|---|---|---|---|---|
| GDELT DOC 2.0 | Unlimited | Yes (tone) | Geographic / entity | Yes | **Yes (global)** |
| GDELT GKG via BigQuery | $$ for compute | Yes | Themes | Yes | v1.5+ |
| Finnhub | 60/min | Yes | **Yes (US)** | Yes | **Yes (US)** |
| Marketaux | 100/day | Yes | Yes | Yes | Backup |
| NewsAPI.org | 100/day delayed 24h | No | No | No (delayed) | Skip |
| GNews | 100/day | No | No | Yes | Skip |
| Tiingo News | Paid | Yes | Yes | Yes | v1.5+ |
| Polygon News | 5/min free | No (basic) | Yes | Yes | Paid only |
| Common Crawl | Free + compute | No | No | Yes | v2 backfill |

---

## 5 Calendars + catalysts

### 5.1 Earnings calendar

- **Finnhub** `/calendar/earnings` — free 60/min, includes EPS estimate vs actual, revenue estimate, fiscal period. **MVP.**
- **yfinance** `Ticker.calendar` and `Ticker.earnings_dates` — free, snapshot.
- **Investing.com** earnings calendar — scrapeable but Cloudflare-protected; need Playwright + curl_cffi or Camoufox MCP. TOS forbids automated extraction; use only as last-resort backup.

### 5.2 FDA drug approvals

- **openFDA**: `https://api.fda.gov/`
- **License**: Public-domain US gov.
- **Auth**: Optional free key (raises quotas).
- **Rate limits**:
  - **Without key**: 240 req/min, 1,000 req/day per IP.
  - **With free key**: 240 req/min, **120,000 req/day** per key.
- **Coverage**: Drug approvals (drugsfda), adverse events (FAERS), recalls, device approvals (510k).
- **Recommendation**: **MVP** for biotech / pharma watchlist tickers.

### 5.3 FOMC meeting calendar

- Source: `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm` (HTML scrape) or **ALFRED release dates** at `https://alfred.stlouisfed.org/release/downloaddates?rid=101` (CSV download — preferred).
- 2026 dates (verified): Jan 27–28, Mar 17–18, Apr 28–29, Jun 16–17, Jul 28–29, Sep 15–16, Oct 27–28, Dec 8–9.
- **Recommendation**: MVP. Pre-load via ALFRED CSV; refresh annually.

### 5.4 Economic releases calendar

- **FRED releases**: `https://fred.stlouisfed.org/releases` — JSON-able via `/fred/releases/dates` API.
- **Trading Economics**: free trial only (100k data points, 100 requests). Full API is paid.
- **Finnhub** `/calendar/economic` — free, US-focused.
- **Recommendation**: FRED + Finnhub for MVP.

### 5.5 Ex-dividend / splits

- yfinance, Polygon (paid), or EDGAR (S-1, 8-K filings reference). yfinance is easiest for MVP.

### 5.6 M&A announcements

- SEC 8-K filings (Item 1.01 Material Definitive Agreement, 2.01 Acquisition/Disposition). Polled hourly via EDGAR submissions feed → **MVP**.

---

## 6 Insider + institutional activity

### 6.1 SEC Form 4 (insider transactions)

- Filed within 2 business days of trade per Section 16(a).
- Access: `edgartools` provides parsed Form 4 transaction objects (ticker, insider, role, transaction code, shares, price). Free, point-in-time.
- **MVP.**

### 6.2 SEC 13F-HR (institutional holdings ≥ $100 M AUM)

- Filed quarterly, within 45 days of quarter-end. **Lookahead bias warning**: 13F is delayed → for backtesting, the holdings as filed at T are *not* the holdings as of T but as of (T − up to 45d).
- Access: `edgartools` parses 13F holdings into pandas. Free.
- **MVP.**

### 6.3 OpenInsider

- **URL**: `http://openinsider.com/`
- **License**: Unclear — site has no formal terms; data is republication of EDGAR Form 4 with screening UI.
- **Auth**: None.
- **Format**: HTML (must scrape). Updates 06:00–22:00 ET Mon–Fri.
- **Scrape posture**: No `robots.txt` block on screener pages last-checked. Python community libs:
  - `openinsiderData` ([sd3v](https://github.com/sd3v/openinsiderData)) — full DB scraper.
  - `open-insider-trades` ([soemyatmyat](https://github.com/soemyatmyat/open-insider-trades)) — REST wrapper.
- **Use case**: Pre-aggregated screens (cluster buys, executive purchases > $X) save you the join work vs raw Form 4.
- **Recommendation**: v1.5+ enrichment. MVP can compute the same screens directly from EDGAR Form 4 via `edgartools`.

### 6.4 WhaleWisdom

- **URL**: `https://whalewisdom.com/`
- **Free tier**: Last 2 years of 13F data via web UI; API requires account.
- **API limits**: 20 req/min; non-subscribers get last 8 quarters; subscribers (~$25/mo+) full history.
- **Recommendation**: Skip — `edgartools` covers 13F directly.

---

## 7 Analyst ratings

### 7.1 Yahoo Finance / yfinance

- `Ticker.recommendations`, `Ticker.recommendations_summary`, `Ticker.upgrades_downgrades`, `Ticker.analyst_price_targets` (latest) — free.
- Snapshot only. TOS grey (see §3.1).
- **MVP.**

### 7.2 Finnhub `/stock/recommendation`

- Free 60/min. Returns Strong Buy / Buy / Hold / Sell / Strong Sell counts per period + price targets.
- **MVP secondary** for cross-validation against Yahoo.

### 7.3 Finviz

- **URL**: `https://finviz.com/`
- **License**: TOS forbids automated scraping for redistribution. "Reselling information is not permitted."
- **Auth**: None for screener; Elite paid for export.
- **Python lib**: `finviz` ([mariostoev/finviz](https://github.com/mariostoev/finviz)) — Apache-2.0; explicitly notes use is at user's own risk re Finviz TOS.
- **Use case**: Aggregated analyst price targets per ticker; comprehensive screener.
- **Posture**: Personal-research scraping at low rate (≤1 req/3s) is the community norm; commercial redistribution is not allowed.
- **Recommendation**: v1.5+. MVP can live without it.

### 7.4 Zacks

- Free site for individual rank lookup; API is paid (via Intrinio or Nasdaq Data Link, ~$200+/mo).
- **Recommendation**: Skip.

### 7.5 OpenBB analyst module

- Aggregates Yahoo + Finnhub + others under a single OpenBB call. See §12.
- **Recommendation**: If we adopt OpenBB as adapter layer, use this; otherwise direct calls.

---

## 8 ESG data

> **Important regulatory note (as of 2026-04-28).** The SEC's 2024 Climate-Related Disclosures rule (S7-10-22) was paused by the courts and the SEC announced 2025-03-27 it would end its defence (press release `https://www.sec.gov/newsroom/press-releases/2025-58`). Federal mandatory climate disclosure is therefore **NOT in force**. California SB-253/261 and EU CSRD remain. Plan ESG features around voluntary disclosures + third-party scoring.

### 8.1 Yahoo Finance ESG (`yfinance.Ticker.sustainability`)

- Free, scraped via yfinance. Underlying scores compiled by **Sustainalytics** (Morningstar-owned), publicly available on Yahoo Finance product pages per Davis Polk client update.
- Returns: total ESG risk, environment / social / governance subscores, controversy level, peer percentile, involvement flags (alcohol, tobacco, weapons, gambling …).
- **Recommendation**: **MVP.** Best free ESG signal.

### 8.2 MSCI ESG Ratings & Climate Search Tool

- **URL**: `https://www.msci.com/our-solutions/esg-investing/esg-ratings-climate-search-tool`
- **Free**: Public letter grade (AAA–CCC) per company, no registration. Scrape-only (no API).
- **Recommendation**: Enrichment via Playwright; one-shot per ticker per quarter. v1.5+.

### 8.3 ESGScraper (Python)

- PyPI package `ESGScraper`: scrapes Yahoo, MSCI, CSR Hub, S&P Global, Sustainalytics into a unified frame.
- Beware all targeted sites' TOS; use sparingly.
- **Recommendation**: v1.5+ research only.

### 8.4 Sustainalytics direct

- Paid (typically institutional, $$$). Skip.

### 8.5 SEC sustainability disclosures

- Currently voluntary. Filers may include Sustainability Reports as exhibits to 10-K. Search EDGAR for keyword "sustainability" / "climate" within 10-K text via `edgartools`.
- **Recommendation**: v2 — LLM-extract narrative climate-risk disclosures from 10-K Item 1A.

---

## 9 Sector / industry classification

### 9.1 GICS

- **URL**: `https://www.msci.com/indexes/index-resources/gics`
- **Structure**: 11 Sectors → 25 Industry Groups → 74 Industries → 163 Sub-Industries (eff. March 2023).
- **Free**: Methodology PDF and structure XLSX downloadable from MSCI.
- **Per-ticker mapping**: Full GICS Direct (44k companies) is paid. Free workaround:
  - SP500 constituents with GICS sector via Wikipedia (`https://en.wikipedia.org/wiki/List_of_S%26P_500_companies`) — scrapable, refreshed by SP regularly.
  - yfinance `Ticker.info["sector"]` and `["industry"]` — free, GICS-aligned but not authoritative codes.
- **Recommendation**: MVP — use yfinance sector tag + Wikipedia SP500 GICS as cross-check.

### 9.2 SPDR Select Sector ETFs (sector proxies)

- 11 ETFs (XLK, XLF, XLV, XLE, XLY, XLP, XLI, XLB, XLU, XLRE, XLC) covering all GICS sectors.
- Holdings published daily by State Street: `https://www.ssga.com/` (CSV download per fund).
- Use as: sector return benchmark, sector momentum, sector rotation backtest universe.
- **MVP** — scrape SSGA daily holdings CSVs.

### 9.3 Russell / SP indices constituents

- iShares IWM (Russell 2000) holdings CSV: free from `https://www.ishares.com/`.
- SP500 constituents: free via Wikipedia (with GICS codes) or via Vanguard/SPDR ETF holdings.

---

## 10 Technical indicator data

Already covered by iguanatrader's parquet bars cache + computation libs. No new data source needed.

- **TA-Lib** (C library + Python bindings) — BSD; gold standard for ~150 indicators. Install painful on Windows; consider `pandas-ta` instead.
- **`pandas-ta`** — MIT; pure Python, 130+ indicators, pandas extension.
- **`vectorbt`** — Apache-2.0 + Commons Clause (NOT pure FOSS for resale); fast vectorised backtesting + indicators. Free version is "maintained, not developed"; new features in paid VectorBT PRO.
- **Recommendation**: Use `pandas-ta` for indicators; `vectorbt` open-source edition for backtesting (acceptable for personal research; if iguanatrader ever ships as a product, re-evaluate the Commons Clause).

---

## 11 PESTEL / geopolitics

### 11.1 GDELT — see §4.1

The single most powerful free geopolitical-events source. Use Events 2.0 (CAMEO-coded conflict / cooperation events) for country-level instability scores.

### 11.2 ACLED — Armed Conflict Location & Event Data

- **URL**: `https://acleddata.com/`
- **License**: Free for non-commercial / academic / journalism (`acleddata.com/terms-of-use-and-attribution-policy`). Commercial usage requires a paid licence.
- **Auth**: Free account → API key.
- **Rate limits**: Pagination recommended (5000 rows/call). No formal RPM cap published.
- **Coverage**: Real-time political violence events globally, 1997+ for Africa, varying start dates elsewhere.
- **Recommendation**: v1.5+ for non-US PESTEL. For a US-focused MVP, GDELT is sufficient.

### 11.3 V-Dem (Varieties of Democracy)

- **URL**: `https://www.v-dem.net/data/`
- **License**: CC-BY-NC. Free download (CSV/Stata/RDS).
- **Auth**: None.
- **Coverage**: 531 indicators × 251 indices × ~200 countries × ~1789–present.
- **Python**: No native lib; load CSV directly. R packages `vdemdata`, `vdem` exist.
- **Recommendation**: v2 (annual one-shot download).

### 11.4 Fragile States Index (Fund for Peace)

- **URL**: `https://fragilestatesindex.org/`
- **License**: Per FFP terms; free for non-commercial use.
- **Format**: Annual Excel. Mendeley mirror covers 2006–2024.
- **Recommendation**: v2 (annual snapshot).

### 11.5 World Bank Worldwide Governance Indicators (WGI)

- **URL**: `https://www.worldbank.org/en/publication/worldwide-governance-indicators`
- **License**: CC-BY-4.0.
- **Coverage**: 6 indicators × 200+ economies × 1996–2024.
- **Access**: Via World Bank API (`wbgapi`) or DataBank export.
- **Recommendation**: v1.5+ via `wbgapi`.

---

## 12 Aggregator + key Python ecosystem repos

### 12.1 OpenBB Platform — adapter layer (with licence caveat)

- **URL**: `https://github.com/OpenBB-finance/OpenBB`
- **Stars**: 66.7k (2026-04). **License: AGPL-3.0** (changed from MIT in 2024 — confirmed at `https://openbb.co/blog/license-change-openbb-platform-goes-agpl`).
- **What it provides**: Single Python API over ~100 providers (Yahoo, FRED, FMP, SEC, Alpha Vantage, Finnhub, Polygon, Tiingo, Intrinio, Benzinga, etc.) with standardised schemas.
- **Latest**: ODP Desktop 2026-04-25; Python platform 4.7.1 (2026-03-09).
- **AGPL implication for iguanatrader**: AGPL is "GPL with the SaaS loophole closed". If iguanatrader **uses OpenBB only as a personal research tool** (no public hosting, no redistribution of binaries), AGPL imposes no incremental obligations vs GPL. But:
  - If iguanatrader is later open-sourced under Apache-2.0 / CC-BY-4.0, importing OpenBB would force the **whole iguanatrader codebase** to go AGPL — incompatible.
  - Mitigation: keep OpenBB strictly behind a process boundary (subprocess / REST microservice), or use OpenBB only in a separate research notebook outside the iguanatrader package.
- **Recommendation**: **Open question for Arturo (see §14).** Do not adopt as the default integration; prefer direct provider libraries.

### 12.2 awesome-quant ([wilsonfreitas](https://github.com/wilsonfreitas/awesome-quant))

- ~25k stars, MIT-listed, weekly-updated curated list. Use as the source-of-truth for "what library should I look at for X".

### 12.3 Microsoft Qlib

- **URL**: `https://github.com/microsoft/qlib` — 41.4k stars, MIT, latest v0.9.7 (2025-08-15).
- AI-oriented end-to-end pipeline: data → models → backtest → portfolio → execution. Bundled with RD-Agent (LLM-driven factor discovery).
- **Recommendation**: v1.5+ research, not core. The data layer assumes you provide bars; doesn't replace any of the sources above.

### 12.4 Backtesting frameworks

| Lib | Stars | License | Status | Verdict |
|---|---|---|---|---|
| `vectorbt` (open) | 7.3k | Apache-2.0 + **Commons Clause** | Maintained, not new dev (PRO is paid) | **Top pick** if Commons Clause is OK for personal use |
| `vectorbt PRO` | n/a | Commercial | Active | Skip unless serious |
| `backtrader` (mementum) | ~13–14k | GPL-3.0 | Community PRs trickling in 2026 | Mature but stagnant; **GPL infects iguanatrader if linked** |
| `zipline-reloaded` (stefan-jansen) | ~1.5k | Apache-2.0 | Active maintenance fork | Pipeline API still uniquely expressive; heavier dependency |
| `nautilus_trader` | ~3k | LGPL | Very active 2025–26 | Modern; consider for live execution |
| `bt` (by Philippe Morissette) | ~2k | MIT | Stable | Lightweight |

**iguanatrader licence-fit**: Since project is Apache-2.0 + CC, prefer Apache/MIT-licensed libs. `vectorbt` open is Apache-2.0 with Commons Clause (non-FOSS for "primary sale"; fine if iguanatrader is research/personal). `backtrader` GPL → keep at process boundary or skip.

### 12.5 Portfolio analytics

- **`quantstats`** (`ranaroussi`) — Apache-2.0; tearsheet generation; latest 2026-01-13. **MVP.**
- **`pyfolio-reloaded`** (`stefan-jansen`) — Apache-2.0 fork of dead Quantopian pyfolio. Active.
- **`empyrical-reloaded`** — Apache-2.0; risk metrics primitives.

### 12.6 Provider client libraries (recommended pins)

| Lib | License | Last activity | Use |
|---|---|---|---|
| `edgartools` | MIT | active 2026 | SEC EDGAR primary |
| `sec-edgar-downloader` | MIT | active 2026 | SEC raw downloads |
| `yfinance` | Apache-2.0 | active 2026 (volatile) | Yahoo snapshot |
| `fredapi` | Apache-2.0/BSD | active | FRED + ALFRED |
| `finnhub-python` | Apache-2.0 | active | Finnhub |
| `alpha_vantage` | MIT | semi-active | only if AV used |
| `polygon-api-client` | MIT | active | Polygon |
| `wbgapi` | MIT | active | World Bank |
| `gdelt-doc-api` | MIT | active | GDELT DOC 2.0 |
| `pandas-ta` | MIT | semi-maintained | Indicators |
| `quantstats` | Apache-2.0 | active | Tearsheets |

---

## 13 Web scraping notes — TOS posture per source

> Ladder reminder: **WebFetch** (no-JS HTML) → **Playwright** (JS rendering, Chromium) → **Camoufox MCP** (anti-bot stealth Firefox; already in iguanatrader stack).

| Source | Scrape required? | TOS posture | Recommended tool |
|---|---|---|---|
| SEC EDGAR | No (REST API) | Public-domain | `edgartools` |
| FRED / BLS / BEA / WB / OECD / IMF / BIS / ECB | No (APIs) | Free / attribution | direct libs |
| Yahoo Finance (yfinance) | Effectively yes (yfinance scrapes Yahoo's internal endpoints) | **Grey area** — Yahoo TOS forbids automated extraction; community tolerates personal use; do NOT redistribute | `yfinance` (which does it for you) |
| Finnhub | No (REST API) | Permitted under free TOS | `finnhub-python` |
| Polygon | No (REST API) | Permitted | `polygon-api-client` |
| openFDA | No (REST API) | Public-domain | direct REST |
| OpenInsider | Yes (HTML) | No formal TOS; data is public-domain Form 4 republished. Personal scraping at low rate appears tolerated. Don't republish. | WebFetch + parser; Playwright if needed |
| Investing.com (earnings cal) | Yes (Cloudflare-protected) | TOS forbids scraping. **Use only if no alternative.** | Camoufox MCP (stealth needed) |
| Finviz | Yes (HTML) | TOS forbids automated extraction & redistribution. Personal-research scraping common; legally grey. | WebFetch + parser; rate-limit ≤ 1 req/3s |
| Yahoo ESG (via yfinance) | Same as yfinance | Same grey area | `yfinance` |
| MSCI ESG public tool | Yes (HTML) | No formal API; public letter grade | Playwright |
| SP500 / Russell constituents (Wikipedia) | Yes (HTML) | CC-BY-SA — attribution required | WebFetch |
| SPDR sector ETF holdings (SSGA) | Yes (CSV download) | SSGA TOS allows personal use | WebFetch (direct CSV URL) |
| Stooq | Yes (CSV with captcha) | Captcha since 2020 → automation broken | One-shot manual bootstrap only |
| GDELT | No (APIs + BigQuery) | CC-BY-4.0 | `gdelt-doc-api`, `google-cloud-bigquery` |
| ACLED | No (REST API) | Free non-commercial | direct REST |
| V-Dem / Fragile States / WGI | No (CSV download) | Free per their licences | `requests` + pandas |

**Iguanatrader scraping policy** (proposal):
1. Always send a `User-Agent` identifying iguanatrader + a contact email.
2. Respect `robots.txt` — programmatic check before scraping.
3. Default rate: 1 req/3s for HTML scrapes; 10 req/s only for documented permissive APIs (EDGAR).
4. Cache aggressively (parquet/SQLite) — every scraped value carries `retrieved_at` + `source_url` + `method` (api|scrape|manual|llm).
5. Never redistribute scraped data outside iguanatrader's research boundary; emit only derived metrics.

---

## 14 Open questions for Arturo

1. **OpenBB adoption?** AGPL-3.0 means we can't link it into an Apache-2.0 + CC iguanatrader package without copyleft-infecting the project. Options:
   - (a) Skip OpenBB; integrate providers directly via 6–8 small adapters.
   - (b) Use OpenBB **only in a sidecar process** (subprocess / FastAPI service running locally) and consume it via HTTP from iguanatrader-proper. Preserves licence boundary.
   - (c) Drop the open-source ambition; accept AGPL on iguanatrader.
   Recommendation: (a) for MVP; (b) if we hit too many one-off integrations.

2. **Paid tiers worth it (€50/mo budget)?** Highest-leverage spends, in order:
   - **Polygon Stocks Starter — $29/mo** — single best upgrade if we want clean intraday + unlimited rate. Replaces yfinance grey-area dependency for prices.
   - **Finnhub Personal — $9.99/mo** — unlocks deeper fundamentals + more sentiment quota. Already very generous on free tier.
   - **FMP Starter — $22/mo** — only if EDGAR XBRL parsing proves too painful for ratios/segments.
   Total of all three = $61 ≈ €56. Pick one or two. **Strong recommendation: start MVP at €0; add Polygon Starter at first real friction with yfinance.**

3. **Point-in-time strategy.** EDGAR XBRL + ALFRED give us PiT for fundamentals + macro. But Yahoo / Finnhub / Polygon free / yfinance are all current-snapshot. Backtest framework must explicitly model leakage when these are used. Decision needed: ban these from backtest features and only allow them in live-trading features? Or accept leakage with documentation?

4. **Knowledge repo schema.** Per-ticker, per-fact, with `(source, retrieval_at, method, value, raw_payload_pointer)`. Should fact-storage be:
   - (a) Append-only event log (Kafka-style) → reproducible at any historical T.
   - (b) Bitemporal table (SQL `effective_from`/`effective_to` × `recorded_from`/`recorded_to`) → simpler queries, harder writes.
   This decision is the biggest architectural one for the data layer; deserves its own ADR.

5. **GDELT BigQuery cost ceiling.** Free-tier BigQuery is 1 TB/mo of query. The full GKG is 3.6 TB. A naive full-table scan kills the free tier. Decision: do we partition queries by date and stay under the cap, or accept ~$5–20/mo BigQuery spend for unrestricted GKG?

6. **OpenInsider vs raw Form 4.** Both give the same data. OpenInsider saves ~3 hours of join/aggregation work. Are we OK accepting a scraped HTML source for an enrichment we could compute ourselves from EDGAR?

7. **ESG signal seriousness.** With SEC climate rule withdrawn (2025-03), the only structured ESG signal is Sustainalytics-via-Yahoo (free, scraped). Is this enough to publish ESG features, or should ESG be deferred to v2?

---

## 15 Final consolidation — source × category × MVP × cost

| # | Source | SEC | Macro | Funda | News | Cal | Insider | Ratings | ESG | Sector | PESTEL | MVP | $/mo |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|---|
| 1 | SEC EDGAR (official + `edgartools`) | ● | | ● | | ● | ● | | ● | | | ● | $0 |
| 2 | FRED + ALFRED | | ● | | | ● | | | | | | ● | $0 |
| 3 | BLS | | ● | | | ● | | | | | | ● | $0 |
| 4 | BEA | | ● | | | | | | | | | ● | $0 |
| 5 | World Bank (`wbgapi`) | | ● | | | | | | | | ● | v1.5 | $0 |
| 6 | OECD / IMF / BIS / ECB | | ● | | | | | | | | | v2 | $0 |
| 7 | yfinance | | | ● | | ● | | ● | ● | ● | | ● (snapshot) | $0 |
| 8 | Finnhub free | | ● | ● | ● | ● | ● | ● | | | | ● | $0 |
| 9 | Polygon free | | | ● | ● | | | | | | | Skip free; ★paid | $29 |
| 10 | FMP free | | | ● | | ● | | | | | | Backup | $0 |
| 11 | Alpha Vantage free | | ● | ● | | | | | | | | Skip | $0 |
| 12 | Twelve Data free | | | ● | | | | | | | | Skip | $0 |
| 13 | EODHD free | | | ● | | | | | | | | v2 | $0 |
| 14 | Stooq | | | ● | | | | | | | | One-shot bootstrap | $0 |
| 15 | GDELT DOC 2.0 | | | | ● | | | | | | ● | ● | $0 |
| 16 | GDELT GKG (BigQuery) | | | | ● | | | | | | ● | v1.5 | ~$0–20 |
| 17 | Marketaux | | | | ● | | | | | | | Backup | $0 |
| 18 | NewsAPI.org | | | | ● | | | | | | | Skip | $0 |
| 19 | GNews | | | | ● | | | | | | | Skip | $0 |
| 20 | Tiingo News | | | | ● | | | | | | | v1.5+ | $10+ |
| 21 | Common Crawl | | | | ● | | | | | | | v2 | $0 |
| 22 | openFDA | | | | | ● | | | | | | ● | $0 |
| 23 | FOMC dates (ALFRED) | | ● | | | ● | | | | | | ● | $0 |
| 24 | Trading Economics | | ● | | | ● | | | | | | Skip free | $0 |
| 25 | Investing.com (scrape) | | | | | ● | | | | | | Backup-of-last-resort | $0 |
| 26 | OpenInsider | | | | | | ● | | | | | v1.5 | $0 |
| 27 | WhaleWisdom | | | | | | ● | | | | | Skip | $0 |
| 28 | Finviz (scrape) | | | ● | | | | ● | | ● | | v1.5 | $0 |
| 29 | Zacks | | | | | | | ● | | | | Skip | paid |
| 30 | OpenBB Platform | aggregator (covers many) | | | | | | | | | | **Open Q (§14)** | $0 |
| 31 | MSCI ESG public | | | | | | | | ● | | | v1.5 | $0 |
| 32 | Sustainalytics (paid) | | | | | | | | ● | | | Skip | $$$ |
| 33 | SP500 Wikipedia + SPDR ETFs | | | | | | | | | ● | | ● | $0 |
| 34 | iShares IWM holdings | | | | | | | | | ● | | ● | $0 |
| 35 | ACLED | | | | | | | | | | ● | v1.5 (academic) | $0 |
| 36 | V-Dem | | | | | | | | | | ● | v2 | $0 |
| 37 | Fragile States Index | | | | | | | | | | ● | v2 | $0 |
| 38 | World Bank WGI | | | | | | | | | | ● | v1.5 | $0 |

**MVP integration shortlist (10 sources, $0/mo):**
1. SEC EDGAR (`edgartools`)
2. FRED + ALFRED (`fredapi`)
3. BLS (free key + direct REST)
4. BEA (free key + direct REST)
5. yfinance (snapshot enrichment only — flagged in metadata)
6. Finnhub free (news, sentiment, calendar, ratings)
7. GDELT DOC 2.0 (`gdelt-doc-api`)
8. openFDA (direct REST)
9. SPDR sector ETFs holdings + SP500 GICS via Wikipedia (sector context)
10. ALFRED FOMC release calendar (CSV)

**v1.5 additions:** OpenInsider, Finviz, MSCI ESG public, World Bank WGI, GDELT GKG via BigQuery.

**Suggested first paid upgrade (if budget unlocked):** Polygon Stocks Starter $29/mo — replaces yfinance for price/news with a clean licensed source.

---

## 16 References (selected canonical URLs)

- SEC EDGAR APIs: `https://www.sec.gov/search-filings/edgar-application-programming-interfaces`
- SEC fair-use: `https://www.sec.gov/os/accessing-edgar-data`
- edgartools docs: `https://edgartools.readthedocs.io/`
- FRED docs: `https://fred.stlouisfed.org/docs/api/fred/`
- FRED API ToS: `https://fred.stlouisfed.org/docs/api/terms_of_use.html`
- BLS API features: `https://www.bls.gov/bls/api_features.htm`
- BEA API signup: `https://apps.bea.gov/API/signup/index.cfm`
- BEA API user guide: `https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf`
- World Bank Data Help: `https://datahelpdesk.worldbank.org/`
- OECD Data API: `https://data.oecd.org/api/`
- BIS Data Portal: `https://data.bis.org/`
- ECB Data Portal API overview: `https://data.ecb.europa.eu/help/api/overview`
- IMF SDMX Central: `https://sdmxcentral.imf.org/`
- yfinance: `https://github.com/ranaroussi/yfinance`
- FMP pricing: `https://site.financialmodelingprep.com/pricing-plans`
- Alpha Vantage premium: `https://www.alphavantage.co/premium/`
- Twelve Data pricing: `https://twelvedata.com/pricing`
- Polygon pricing: `https://polygon.io/pricing`
- Finnhub rate limits: `https://finnhub.io/docs/api/rate-limit`
- EODHD pricing: `https://eodhd.com/pricing`
- Stooq DB: `https://stooq.com/db/h/`
- GDELT data: `https://www.gdeltproject.org/data.html`
- GDELT DOC 2.0 announcement: `https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/`
- NewsAPI pricing: `https://newsapi.org/pricing`
- Marketaux pricing: `https://www.marketaux.com/pricing`
- GNews pricing: `https://gnews.io/pricing`
- Common Crawl: `https://commoncrawl.org/`
- openFDA auth: `https://open.fda.gov/apis/authentication/`
- FOMC calendar: `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm`
- ALFRED FOMC release: `https://alfred.stlouisfed.org/release/downloaddates?rid=101`
- OpenInsider: `http://openinsider.com/`
- WhaleWisdom API help: `https://whalewisdom.com/help/api`
- MSCI GICS: `https://www.msci.com/indexes/index-resources/gics`
- SSGA Sector SPDRs: `https://www.ssga.com/us/en/intermediary/capabilities/equities/sector-investing/select-sector-etfs`
- ACLED: `https://acleddata.com/`
- V-Dem: `https://www.v-dem.net/data/`
- Fragile States Index: `https://fragilestatesindex.org/`
- WGI: `https://www.worldbank.org/en/publication/worldwide-governance-indicators`
- OpenBB GitHub: `https://github.com/OpenBB-finance/OpenBB`
- OpenBB licence change: `https://openbb.co/blog/license-change-openbb-platform-goes-agpl`
- awesome-quant: `https://github.com/wilsonfreitas/awesome-quant`
- Microsoft Qlib: `https://github.com/microsoft/qlib`
- vectorbt: `https://github.com/polakowo/vectorbt`
- backtrader: `https://github.com/mementum/backtrader`
- zipline-reloaded: `https://github.com/stefan-jansen/zipline-reloaded`
- quantstats: `https://github.com/ranaroussi/quantstats`
- pandas-ta: `https://pypi.org/project/pandas-ta/`
- SEC climate rule end-of-defence (2025-03-27): `https://www.sec.gov/newsroom/press-releases/2025-58`
