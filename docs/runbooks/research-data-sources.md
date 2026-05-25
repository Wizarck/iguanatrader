# Runbook — Research Data Sources

**Owner**: Research slice (`apps/api/src/iguanatrader/contexts/research/`).

**Purpose**: Authoritative catalog of every external data source iguanatrader can pull research facts from. Covers what each source provides, how to register, the env var that activates it, current wiring status, and the steps to onboard a brand-new operator from zero.

**When to read this**:

- Onboarding a new operator / fresh deploy (Section 3).
- Deciding whether to add a new ticker's research coverage (Section 1 + 2).
- Building / updating the **Settings → Research → Sources** UI (Section 5).
- Rotating an exposed key (Section 4).

---

## 1. Source catalog (TL;DR)

| # | Source | Tier | Data | Cost | Env var | Register at | Wired? |
|---|--------|------|------|------|---------|-------------|--------|
| 1 | **SEC EDGAR** | A | Filings (10-K/Q, 8-K, Form 4) + XBRL companyfacts (EPS, Revenue, Assets…) | Free | `SEC_EDGAR_USER_AGENT` (string, not a key) | No registration — just provide `<company> <email>` UA per [SEC Fair Access](https://www.sec.gov/os/accessing-edgar-data) | ✅ Adapter built; CLI pending (I0) |
| 2 | **FRED** (St. Louis Fed) | A | Macro time-series (CPI, unemployment, fed funds, GDP…) — ALFRED vintage-aware | Free | `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html | ✅ Adapter built; CLI pending (I1) |
| 3 | **Finnhub** | B | Company news, earnings calendar, analyst recommendations, insider transactions | Free 60 req/min (paid tiers for higher rate) | `FINNHUB_API_KEY` | https://finnhub.io/register | ✅ Adapter built; CLI pending (I3) |
| 4 | **BEA** (Bureau of Economic Analysis) | A | NIPA tables (GDP components, personal income, savings rate) | Free | `BEA_API_KEY` | https://apps.bea.gov/API/signup/ — [user guide PDF](https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf) | ✅ Adapter built; CLI optional (I3+) |
| 5 | **BLS** (Bureau of Labor Statistics) | A | Employment, CPI detail, labour productivity, JOLTS | Free | `BLS_API_KEY` | https://data.bls.gov/registrationEngine/ | ✅ Adapter built; CLI optional (I3+) |
| 6 | **OpenBB Platform sidecar** | B | YFinance-default fundamentals (P/E, market cap, dividend yield), analyst ratings, ESG. Provider keys (FMP / Polygon / Intrinio) unlock richer data. AGPL-isolated per ADR-015 | Free with YFinance; provider keys at provider cost | `OPENBB_SIDECAR_URL` (internal), provider keys passed through: `OPENBB_FMP_API_KEY`, `OPENBB_POLYGON_API_KEY`, etc. | Sidecar: no registration. Providers: see Section 6 | ✅ Sidecar built; compose wiring + CLI pending (I2) |
| 7 | **GDELT** | B | Global news event database (politics, conflict, sentiment) | Free, no key | none | n/a | ✅ Adapter built; CLI optional (I3+) |
| 8 | **OpenFDA** | B | FDA drug approvals, recalls, adverse events (pharma research) | Free; optional key lifts rate limit | `OPENFDA_API_KEY` (optional) | https://open.fda.gov/apis/authentication/ | ✅ Adapter built; CLI optional (I3+) |
| 9 | **V-Dem** | C | Democracy / governance indicators (country-level macro context) | Free, CSV download | none | n/a — bootstrap-only | ✅ Adapter built (one-shot bootstrap) |
| 10 | **World Bank WGI** | C | Worldwide Governance Indicators (country-level) | Free | none | n/a — bootstrap-only | ✅ Adapter built (one-shot bootstrap) |

**Tier** legend: A = native point-in-time, backtest-safe. B = snapshot, **forbidden in backtest** (live use only). C = one-shot bootstrap.

---

## 2. Per-source detail

### SEC EDGAR (Tier A)

- **What it gives**: Every filing the issuer made (10-K, 10-Q, 8-K, Form 4, 13F). For 10-K/Q the adapter also pulls XBRL `companyfacts` → one `research_fact` row per `(taxonomy, concept, end_date)` tuple. Concepts include `us-gaap.EarningsPerShareDiluted`, `us-gaap.Revenues`, `us-gaap.Assets`, hundreds more.
- **Registration**: None. SEC requires only a `User-Agent: <company> <email>` header per their [Fair Access](https://www.sec.gov/os/accessing-edgar-data) policy.
- **Env var**: `SEC_EDGAR_USER_AGENT="iguanatrader your-email@example.com"`
- **Rate limit**: 10 req/s (SEC's official limit). Adapter token-bucket enforces this.
- **Coverage gap**: No earnings call transcripts (those aren't filed with the SEC). MD&A and Risk Factors text are inside 10-K's HTML — current adapter parses XBRL only, not the prose. Slice I4 (`edgartools` supplement) would close this.
- **License**: SEC data is U.S. public domain.
- **Module**: `apps/api/src/iguanatrader/contexts/research/sources/sec_edgar.py`

### FRED — Federal Reserve Economic Data (Tier A)

- **What it gives**: ~800,000 macro time-series. The adapter is **ALFRED-aware**: revisions land as NEW facts (bitemporal `recorded_from`), not overwriting prior vintages — so historical analysis at a past point-in-time is correct.
- **Common series IDs**: `CPIAUCSL` (CPI), `UNRATE` (unemployment), `DFF` (fed funds), `GDP`, `M2SL` (money supply), `DGS10` (10-year treasury).
- **Registration**: https://fred.stlouisfed.org/docs/api/api_key.html — 1 min, instant key by email.
- **Env var**: `FRED_API_KEY=<32 hex chars>`
- **Rate limit**: 120 req/min. Adapter throttles at 2 req/s.
- **Backfill**: CLI will support `--backfill 5y` (or similar) to seed deep history for a new symbol's macro context. Without backfill, methodology can't compute trend / regime / deviation-from-mean.
- **License**: FRED data is public domain (U.S. federal). St. Louis Fed Terms of Use require attribution.
- **Module**: `apps/api/src/iguanatrader/contexts/research/sources/fred.py`

### Finnhub (Tier B)

- **What it gives**: Company news (last 30 days on free tier), earnings calendar with consensus estimates, analyst recommendations (buy/hold/sell counts), insider transactions, basic financials, IPO calendar.
- **Registration**: https://finnhub.io/register — 1 min, key delivered after email verify. Free tier: 60 req/min. They also offer webhooks + passkey login (not used).
- **Env var**: `FINNHUB_API_KEY=<...>`
- **Rate limit**: 60 req/min (free), more on paid tiers.
- **Coverage gap**: Free tier news is last 30 days only; deep historical needs paid plan.
- **License**: Per Finnhub TOS — non-commercial free tier; commercial requires paid plan.
- **Module**: `apps/api/src/iguanatrader/contexts/research/sources/finnhub.py`

### BEA — Bureau of Economic Analysis (Tier A)

- **What it gives**: NIPA tables (GDP, personal income, corporate profits), Industry economic accounts, Regional accounts. Critical for sector/industry rotation analysis.
- **Registration**: https://apps.bea.gov/API/signup/ — instant.
- **Env var**: `BEA_API_KEY=<...>`
- **Rate limit**: 1000 req/hr per key.
- **Reference**: [BEA Web Service API user guide PDF](https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf).
- **License**: U.S. public domain.
- **Module**: `apps/api/src/iguanatrader/contexts/research/sources/bea.py`

### BLS — Bureau of Labor Statistics (Tier A)

- **What it gives**: Employment situation, CPI detail (by category), JOLTS, productivity, employment cost index. Granular labour-market data.
- **Registration**: https://data.bls.gov/registrationEngine/ — instant.
- **Env var**: `BLS_API_KEY=<...>`
- **Rate limit**: 500 req/day (v2 with key), 25 req/day (v1 without).
- **License**: U.S. public domain.
- **Module**: `apps/api/src/iguanatrader/contexts/research/sources/bls.py`

### OpenBB Platform sidecar (Tier B)

- **What it gives**: Unified facade over ~80 financial-data providers (YFinance default, no key). Endpoints exposed by the sidecar: `/v1/equity/fundamentals/{sym}` (P/E, market cap, dividend yield), `/v1/equity/ratings/{sym}` (consensus, target price), `/v1/equity/esg/{sym}` (ESG score), `/v1/economy/macro/{indicator}`.
- **Architecture**: Runs as its own Docker container (AGPL boundary per [ADR-015](../adr/ADR-015-2026-04-28-openbb-sidecar-isolation.md)). The iguanatrader monolith never imports `openbb`; communicates over loopback HTTP only.
- **Default provider (free)**: **YFinance** — covers basic fundamentals; no analyst transcripts.
- **Optional premium providers** (sidecar honours OpenBB-recognized env vars):
  - **FMP** (~$15/mo Starter): earnings call transcripts, analyst targets, deep historical fundamentals → `OPENBB_FMP_API_KEY`
  - **Polygon** (~$30/mo Basic): real-time prices, options data → `OPENBB_POLYGON_API_KEY`
  - **Intrinio** (~$50/mo+): institutional-grade fundamentals → `OPENBB_INTRINIO_API_KEY`
  - **Alpha Vantage** (free w/ limits, paid tiers): broad coverage → `OPENBB_ALPHA_VANTAGE_API_KEY`
- **Env vars**: `OPENBB_SIDECAR_URL` (internal, set in compose), `OPENBB_SIDECAR_ENABLED` (default `true`).
- **License**: OpenBB Platform is **AGPL-3.0**. The sidecar boundary keeps that obligation inside the container — the rest of iguanatrader stays Apache-2.0 + Commons Clause. **Do NOT** import `openbb` from `apps/api/`.
- **Module**: `apps/openbb-sidecar/` + caller adapter at `apps/api/src/iguanatrader/contexts/research/sources/openbb_sidecar.py`

### GDELT (Tier B)

- **What it gives**: Global Database of Events, Language and Tone — every news article ingested by GDELT, with sentiment + event codes. Useful for geopolitical risk overlays.
- **Registration**: None.
- **Rate limit**: GDELT's BigQuery / 2.0 API has informal limits; adapter throttles defensively.
- **License**: CC-BY 4.0.
- **Module**: `apps/api/src/iguanatrader/contexts/research/sources/gdelt.py`

### OpenFDA (Tier B)

- **What it gives**: Drug approvals (NDA/BLA decisions), adverse event reports, recalls, device approvals. Domain-specific to pharma research.
- **Registration**: Optional — https://open.fda.gov/apis/authentication/. Without key: 240 req/min, 1000 req/day. With key: 240 req/min, 120000 req/day.
- **Env var**: `OPENFDA_API_KEY` (optional).
- **License**: U.S. public domain.
- **Module**: `apps/api/src/iguanatrader/contexts/research/sources/openfda.py`

### V-Dem (Tier C — bootstrap-only)

- **What it gives**: Varieties of Democracy dataset — country-level democracy / freedom / civil liberties indicators. Used for sovereign-risk overlays.
- **Registration**: None. CSV downloads from https://www.v-dem.net/data/the-v-dem-dataset/.
- **License**: CC-BY 4.0.
- **Module**: `apps/api/src/iguanatrader/contexts/research/sources/vdem.py`

### World Bank WGI (Tier C — bootstrap-only)

- **What it gives**: Worldwide Governance Indicators — six dimensions (Voice & Accountability, Political Stability, Government Effectiveness, Regulatory Quality, Rule of Law, Control of Corruption). Country-level.
- **Registration**: None. API at https://databank.worldbank.org/.
- **License**: CC-BY 4.0.
- **Module**: `apps/api/src/iguanatrader/contexts/research/sources/wgi_world_bank.py`

---

## 3. Onboarding a new operator (from zero)

Goal: a fresh operator can produce a real (non-partial) research brief in <30 min.

**Required** (MVP minimal — gives ~70% of brief value):

1. SEC EDGAR — no registration, just set `SEC_EDGAR_USER_AGENT="<your-name-or-org> <your-email>"`.
2. FRED — register at https://fred.stlouisfed.org/docs/api/api_key.html. Save `FRED_API_KEY`.

**Recommended** (lifts to ~90% of brief value, still free):

3. Finnhub — register at https://finnhub.io/register. Save `FINNHUB_API_KEY`.
4. OpenBB sidecar — no registration. Default YFinance provider activates automatically.

**Optional** (deeper macro):

5. BEA — register at https://apps.bea.gov/API/signup/. Save `BEA_API_KEY`.
6. BLS — register at https://data.bls.gov/registrationEngine/. Save `BLS_API_KEY`.

**Premium** (only if literal earnings call transcripts are required):

7. FMP — register at https://site.financialmodelingprep.com/. Starter ~$15/mo. Save `OPENBB_FMP_API_KEY`.

### Adding the keys to a deployment

For the **single-host VPS** (current mvp profile):

```sh
ssh cx43
sudo -i
cd /opt/iguanatrader
cp .env .env.bak-$(date -u +%Y-%m-%d-%H%M)
cat >> .env <<'EOF'
SEC_EDGAR_USER_AGENT=iguanatrader your-email@example.com
FRED_API_KEY=...
FINNHUB_API_KEY=...
BEA_API_KEY=...
BLS_API_KEY=...
# Optional
OPENBB_FMP_API_KEY=...
EOF
docker compose -f compose/mvp.yml -f compose/mvp.override.yml up -d --no-deps --force-recreate api
```

For SOPS-encrypted deployments (paper / live target state — see [secret-rotation.md](secret-rotation.md)), keys land inside `.secrets/<env>.env.enc`.

### Registering symbols for the new tenant

After bootstrap, each ticker must be registered (otherwise `POST /research/briefs/{sym}/refresh` 404s):

```sh
docker exec iguanatrader-api-1 \
  iguanatrader admin register-symbol NVDA --tenant <your-slug>
```

Defaults: exchange=NASDAQ, tier=primary, methodology=three_pillar, schedule=manual. All overridable.

### Triggering initial ingestion

After Ingestion Wave I0–I2 land:

```sh
# SEC EDGAR — filings + XBRL fundamentals
docker exec iguanatrader-api-1 iguanatrader research ingest sec-edgar --symbol NVDA

# FRED — macro (with 5y backfill)
docker exec iguanatrader-api-1 iguanatrader research ingest fred \
  --series CPIAUCSL,UNRATE,DFF --backfill 5y

# OpenBB sidecar — fundamentals + ratings + ESG via YFinance
docker exec iguanatrader-api-1 iguanatrader research ingest openbb --symbol NVDA
```

Then the brief refresh in the UI will pull real values.

---

## 4. Key rotation

Treat any key that's appeared in chat, screenshots, or a non-`.gitignore`'d file as compromised. Rotation steps:

1. **FRED**: log in to https://fred.stlouisfed.org/, request a new key (regenerate). The old key revokes within minutes.
2. **Finnhub**: dashboard at https://finnhub.io/dashboard → API Keys → regenerate.
3. **BEA / BLS**: re-request from the registration URL with the same email; the old key is invalidated.
4. **OpenBB premium providers** (FMP / Polygon / etc.): each provider's dashboard.

Update the deployment env (Section 3 procedure) + recreate the api container. Then audit `apps/api/src/iguanatrader/contexts/research/sources/*.py` for any test fixtures that might have inlined the old key (should be none — all live keys are env-only).

---

## 5. Future: Settings → Research → Sources UI

When this lands as a slice (target: post-Ingestion-Wave), the UI should mirror Section 1's catalog with three operator-facing affordances:

- **Activate / deactivate** per source. Backed by a new `tenant_research_source_config` table:

```sql
tenant_id        UUID
source_id        TEXT  -- 'sec_edgar' | 'fred' | 'finnhub' | 'openbb_sidecar' | ...
enabled          BOOL  DEFAULT true
api_key_encrypted TEXT NULL  -- per-tenant key override (encrypted at rest)
config_overrides  JSONB NULL -- e.g. {"backfill_years": 5}
PRIMARY KEY (tenant_id, source_id)
```

- **Inline explainer**: each source card shows: what data it produces, free/paid badge, registration URL, link to the relevant section of this runbook, current health status (last successful fetch timestamp + last error if any).

- **Credential input**: per-tenant API key field (encrypted at rest with the tenant's keyring or SOPS-recipient-per-tenant). Setting a tenant key overrides the host-level env var.

Health status feeds from a new `ingest_runs` table the scheduler (slice I5) populates. Card colour: green (last run <24h, no errors), amber (last run 24-72h or warning-class errors), red (no runs in 72h or fatal errors).

The slice should also surface **per-source coverage gaps** as inline help text — e.g. "Finnhub free tier: news only last 30 days" / "YFinance: no earnings transcripts (need FMP $15/mo for those)".

---

## 6. Premium provider quick-pick

If transcripts or richer fundamentals become necessary, this is the picking order based on price-to-coverage:

1. **FMP Starter (~$15/mo)** — best entry point. Transcripts + analyst targets + 30-year fundamentals history + insider data + earnings calendar consensus.
2. **IBKR Reuters Worldwide Fundamentals (~$5/mo)** — competitive with FMP for fundamentals + analyst estimates, routed through the already-running TWS client. Cheaper but Reuters-only coverage.
3. **IBKR Reuters real-time news / news tick 292 (~$1–5/mo)** — live news bulletins via TWS news ticks. Useful if alerting flows need sub-minute event detection.
4. **Polygon Basic (~$30/mo)** — adds real-time options chain + tick data. Useful if iguanatrader expands beyond fundamentals into options strategies.
5. **Intrinio Equity Essentials (~$50/mo+)** — institutional-grade fundamentals + estimates. Overkill for retail until volume justifies.
6. **Alpha Vantage** — free tier 5 req/min + paid from $50/mo. Niche coverage; rarely the best price/value.

Options 1, 4, 5, 6 plug into the existing OpenBB sidecar via OpenBB-recognized env vars; no new adapter code. Options 2 and 3 plug into the planned IBKR adapter (slice I3 — see [roadmap-ingestion.md](../roadmap-ingestion.md)) via `reqFundamentalData` / news tick subscription on the existing TWS connection.

See [`roadmap-ingestion.md` — Future paid options](../roadmap-ingestion.md#future-paid-options-under-consideration) for the decision principle that gates spend on observed gaps.

---

## Related

- [ADR-015 OpenBB sidecar isolation](../adr/ADR-015-2026-04-28-openbb-sidecar-isolation.md) — AGPL boundary rationale.
- [secret-rotation.md](secret-rotation.md) — general key rotation procedure.
- [sops-decrypt-at-boot.md](sops-decrypt-at-boot.md) — encrypted-env layout for paper/live profiles.
- Roadmap: `docs/roadmap-llm-features.md` (post-Ingestion-Wave LLM features).
