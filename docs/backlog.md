# iguanatrader — Backlog & Roadmap

**Date:** 2026-04-27
**Owner:** Arturo
**Policy:** Nothing gets discarded. Everything identified goes into a version or into the open backlog.

**Legend:**
- 🟢 Confirmed in its version
- 🟡 Proposed, pending validation
- 🎯 Unique differentiator
- ⚠️ Risk / gap to watch
- 📅 Target date (if applicable)

---

## v1.0 — MVP (current scope)

> **Goal:** functional personal dogfooding. You approve real trades on IBKR via Telegram + WhatsApp with a risk engine that can't be bypassed. Reproducible backtest. Cost observability for the LLM stack.

### Foundation
- 🟢 Repo structure `src/iguanatrader/`
- 🟢 Pydantic Settings + yaml configs
- 🟢 SQLite append-only with `tenant_id` first-class (multi-tenant ready schema)
- 🟢 Types: `Bar`, `Signal`, `Order`, `Fill`, `Position`, `ApiCostEvent`, `RiskOverride`
- 🟢 Unit tests + property tests (hypothesis over risk caps)
- 🟢 License **Apache-2.0 + Commons Clause** from the first commit 🎯
- 🟢 SOPS (age) for secrets + gitleaks pre-commit
- 🟢 **Docker + docker-compose** (mitigable, promoted to MVP)
- 🟢 **Base docs** (`getting-started.md`, `architecture.md`, `runbook.md`, `strategies/donchian_atr.md`)

### Engine architecture (Nautilus pattern adapted)
- 🟢 `MessageBus` with asyncio.Queue (pub/sub + cmd/event)
- 🟢 Separate engines: `DataEngine`, `ExecutionEngine`, `RiskEngine`, `Cache`
- 🟢 Cache-before-handler ordering guarantee
- 🟢 Single-threaded asyncio event loop

### Backtest engine
- 🟢 Event-driven, same loop as live
- 🟢 Parametric slippage (5-15 bps small-cap / 1-3 bps large-cap)
- 🟢 Realistic commission modeling (IBKR rates)
- 🟢 `BrokerageModel` per broker (Lean pattern) 🎯
- 🟢 Metrics: Sharpe, Sortino, Calmar, max DD, profit factor
- 🟢 Historical fixtures for tests

### BrokerInterface (mitigable, promoted to v1)
- 🟢 Abstract `BrokerInterface` from day 1
- 🟢 `IBKRAdapter` adapter (via `ib_async` + TWS Gateway)
- 🟢 Single `paper:true/false` switch (no dual-class) — Lumibot pattern
- 🟢 Periodic reconciliation with broker state

### Risk engine (Freqtrade Protections pattern)
- 🟢 Declarative protections in `config/risk.yaml`
- 🟢 `PerTradeRisk` (default 2%)
- 🟢 `DailyLossCap` (5% kill-switch until T+1)
- 🟢 `WeeklyLossCap` (15% kill-switch until W+1)
- 🟢 `MaxOpenPositions` (default 5)
- 🟢 `MaxDrawdown` (configurable threshold)
- 🟢 ATR-based position sizing (input to the risk engine)
- 🟢 Master switch `enable_protections: true`
- 🟢 Kill-switch file (`.killswitch`) + env var (`IGUANA_HALT`)
- 🟢 Override via Telegram (`/override <id> <reason>`) with immutable audit log 🎯
- 🟢 RiskEngine NOT bypassable from Strategy code (declarative only)

### Strategy interface (Lumibot pattern)
- 🟢 Lifecycle 12 hooks: `initialize`, `before_starting_trading`, `before_market_opens`, `on_trading_iteration`, `before_market_closes`, `after_market_closes`, `on_new_order`, `on_partially_filled_order`, `on_filled_order`, `on_canceled_order`, `on_parameters_updated`, `on_bot_crash`
- 🟢 `parameters` first-class + hot-reload via `on_parameters_updated`
- 🟢 **Per-symbol strategy config** (yaml-driven) 🎯

### Strategies included in MVP
- 🟢 **DonchianBreakout + ATR** (v0 — golden path)
- 🟢 **SMA Cross** (end-to-end smoke test)

### Approval gate (Freqtrade Telegram pattern)
- 🟢 Abstract `ApprovalChannel`
- 🟢 `TelegramChannel` (`python-telegram-bot` with inline buttons)
- 🟢 `WhatsAppChannel` via Hermes/Meta API 🎯
- 🟢 ~17 commands: `/start`, `/stop`, `/pause`, `/reload_config`, `/propose`, `/approve`, `/reject`, `/forceexit`, `/status`, `/balance`, `/profit`, `/daily`, `/weekly`, `/performance`, `/trades`, `/logs`, `/risk_status`, `/cost_today`, `/cost_week`, `/halt`, `/resume`, `/override`, `/version`, `/help`
- 🟢 Per-user authorization (`authorized_phones`, `authorized_telegram_ids`)
- 🟢 Configurable approval timeout (default 60s) — if you don't respond, the proposal is discarded + logged
- 🟢 Hindsight `bank-id` per user/phone (isolated memory) 🎯

### Web dashboard
- 🟢 FastAPI + HTMX + Jinja2 + Plotly.js (mobile-first, localhost in MVP)
- 🟢 `/` — live equity curve + drawdown + open positions + kill-switch button
- 🟢 `/approvals` — pending proposal queue (same backend as Telegram)
- 🟢 `/trades` — filterable history (timestamp, symbol, side, qty, P&L, holding period)
- 🟢 `/portfolio` — per-symbol P&L + asset allocation + cash
- 🟢 `/costs` — USD/day per provider + per LangGraph node + cost-per-trade ratio 🎯
- 🟢 `/risk` — risk cap status + override audit trail
- 🟢 `/runs` — backtest history + live sessions

### LangGraph orchestration (Layer 3)
- 🟢 Nodes: `premarket_briefing` (8:30 ET), `midday_check` (1 PM ET), `postmarket_summary` (4:30 PM ET), `weekly_review` (Fri 6 PM ET, PDF) 🎯
- 🟢 Proactive cron-jobs tier-graded (Tier 1 hardcoded / Tier 2 LLM-filtered / Tier 3 routine) 🎯
- 🟢 Multi-model routing: Opus 4.7 research / Sonnet 4.6 routines / Haiku 4.5 trivial alerts 🎯
- 🟢 Perplexity API for news/sentiment
- 🟢 LLM **proposes**, does NOT execute (architectural constraint)

### Cost & P&L observability
- 🟢 `ApiCostEvent` table (provider, model, node, tokens in/out, cache reads/writes, USD cost)
- 🟢 `CostMeter` wrapper over Anthropic + Perplexity SDKs
- 🟢 Versioned pricing table `config/llm_prices.yaml`
- 🟢 **Replay caching of LLM calls in backtest** (Lumibot pattern) 🎯
- 🟢 `PnLCalculator`: per-trade FIFO, per-symbol, per-portfolio (realized + unrealized)
- 🟢 EquitySnapshot timeseries (every N min during active session)

### Operational
- 🟢 CLI `iguana` (typer): `ingest`, `backtest`, `paper`, `live`, `dashboard`, `propose`, `halt`, `resume`
- 🟢 Structured JSON logs (structlog) + rotation
- 🟢 Crash recovery (resume from last consistent state)
- 🟢 GitHub Project mandatory + `issue_sync.py` automation

### Operator provisioning (post-deploy carry-forwards, session 2026-05-13)

Each item is a blocker external to the code — without it the shipped feature stays inactive / falls back to log-only. **Remove them from here once resolved.**

- ⚠️ **SMTP relay** for sender `iguanatrader@palafitofood.com` — account on Mailgun/Resend/SES/Postmark + 4 vars (`IGUANATRADER_SMTP_HOST` + `_PORT` + `_USERNAME` + `_PASSWORD`). **Blocks**: real forgot-password delivery (`auth-forgot-password-flow` PR #135 + guardrail PR #137) — currently falls back to log-only via per-channel fallback.
- ⚠️ **DNS SPF + DKIM** on `palafitofood.com` (Cloudflare) — gated on SMTP. **Blocks**: keeping A1 out of spam.
- ⚠️ **Telegram `chat_id`** for Arturo — `/start` to the iguanatrader bot → grab `chat_id` → `UPDATE users SET telegram_chat_id='<id>' WHERE email='arturo6ramirez@gmail.com'`. **Blocks**: Telegram recovery channel + future Telegram alerts. Migration 0014 (PR #135) added the column; it still needs to be populated.
- ⚠️ **Hermes (WhatsApp) HMAC alignment** with the ELIGIA instance — verify whether it supports HMAC (iguanatrader's adapter signs POST bodies). If it uses bearer auth: decide between (a) switching ELIGIA Hermes to HMAC, (b) adding a bearer-auth variant to iguanatrader's adapter. **Blocks**: WhatsApp recovery channel.
- ⚠️ **SOPS bundle key rename** (gated on Hermes alignment) — `sops -d .secrets/dev.env.enc` → rename `HERMES_WEBHOOK_URL` → `HERMES_BASE_URL` + `HERMES_AUTH_TOKEN` → `HERMES_HMAC_SECRET` → re-encrypt. Mirror in `paper.env.enc` + `live.env.enc`.

### Already planned, **NOT in MVP** (explicit move)
- ❌ Engine migration to Lumibot/Lean/Nautilus in v2 (BrokerInterface leaves the door open)

---

## v1.5 — Quick wins post-MVP

> **Goal:** cover the comfortable gaps in v1 that will hurt soon. Still single-user, no SaaS.

### Additional strategies (retail equity catalog)
- 🟡 **RSI mean-reversion** (counter-trend on oversold/overbought)
- 🟡 **Bollinger Bands breakout/squeeze** (vol-based)
- 🟡 **MACD crossover** (momentum-based)
- 🟡 **Volume-weighted Donchian** (Donchian + volume filter)

### IBKR Execution Algorithms (order algos, not decision algos)
- 🟡 **Adaptive** — the most recommended for retail
- 🟡 **TWAP** — Time-Weighted Average Price
- 🟡 **VWAP** — Volume-Weighted Average Price
- 🟡 **Snap (Bid/Mid/Ask)** — point-in-time capture

### Risk engine extensions (Freqtrade-style)
- 🟡 **StoplossGuard** (pause after N consecutive stoplosses)
- 🟡 **CooldownPeriod** (minimum time between trades on the same symbol)
- 🟡 **Dynamic trailing stops** (custom_stoploss equivalent)

### Backtest engine extensions
- 🟡 **Walk-forward analysis**
- 🟡 **Auto-generated HTML report** (Lean pattern)
- 🟡 **Polygon data** (optional premium vs Yahoo MVP)

### Operational
- 🟡 **Hot-reload of strategy code** (no restart)
- 🟡 **Optional Postgres** (same schema, swap SQLite ↔ Postgres via config)
- 🟡 **Variable backup/restore** (Lumibot pattern)
- 🟡 **Prometheus metrics export**

---

## v2 — Multi-broker + SaaS preparation

> **Goal:** validate multi-tenant architecture. Multiple brokers. Ready to invite 5-10 beta users if OSS launch is decided.

### Additional brokers (BrokerInterface already ready)
- 🟡 **AlpacaAdapter** (US equity, free)
- 🟡 **SchwabAdapter**
- 🟡 **TradierAdapter**

### Order types
- 🟡 OCO (one-cancels-other)
- 🟡 Bracket orders
- 🟡 IBKR Iceberg + PassRelative + Percentage of Volume

### Sophisticated strategies
- 🟡 **Pairs trading / cointegration** (long A short B when spread diverges)
- 🟡 **Z-score mean reversion** (statistical)
- 🟡 **Multi-timeframe trend following** (1D + 1H + 15m confluence)

### Risk engine
- 🟡 **LowProfitPairs blocker** (Freqtrade pattern)

### Notifications
- 🟡 Email alerts
- 🟡 Discord integration

### UI
- 🟡 Hot-reload of UI config from dashboard
- 🟡 Strategy visualization (active strategy + recent signals)
- 🟡 Order management UI (cancel/modify from web)

### Multi-asset
- 🟡 **Futures** (CME via IBKR — micros: MES, MNQ, MGC, MCL)

### Multi-tenant infra
- 🟡 Per-user isolated secrets (SOPS per tenant)
- 🟡 1 process/container per tenant pattern (Docker Compose orchestration)

---

## v3 — SaaS launch

> **Goal:** commercial product. OSS Apache + Commons Clause + paid hosted tier. Evidence-based decision: if v2 validates adoption + your own dogfooding generates positive P&L.

### Pricing
- 🟡 **3 tiers**: Solo / Team / Pro (inspired by simplified QC)
- 🟡 Free tier: unlimited backtest, no live
- 🟡 Solo paid: paper + live single-broker
- 🟡 Team paid: 3-5 seats, multi-broker, shared dashboard
- 🟡 Pro: unlimited compute, SLA support, concurrent multi-strategy

### Onboarding & billing
- 🟡 Sign-up flow + email verification
- 🟡 Broker connect wizard (OAuth where applicable)
- 🟡 Stripe integration

### Advanced strategies
- 🟡 **Sector rotation** (monthly momentum on sector ETFs)
- 🟡 **Earnings post-drift** (event-driven over calendar)
- 🟡 **Risk parity rebalancing** (systematic monthly allocation)

### Multi-asset expansion
- 🟡 **Crypto exchanges** via CCXT (Binance, Coinbase, Kraken)
- 🟡 **DEX support** (Hyperliquid, dYdX, Polymarket)
- 🟡 **Forex** (OANDA via IBKR)

### Advanced IBKR Execution Algos
- 🟡 DarkIce (dark pool + iceberg combo)
- 🟡 Accumulate-Distribute (gradual builds)
- 🟡 ArrivalPx (benchmark to arrival price)

### Advanced LLM features
- 🟡 **LLM strategy codegen** (Composer/BotSpot pattern — user describes in NL, LLM generates Strategy class)
- 🟡 **Strategy marketplace** (users share strategies, marketplace with revenue share)
- 🟡 Distributed hyperopt (Ray cluster)
- 🟡 Cohort-based course (education flywheel)
- 🟡 Discord community + Foundation-style governance

---

## Open backlog — no version commitment

Items identified that are NOT planned. Ideas to consider if real demand emerges.

### Niche asset classes
- Polymarket / Betfair (algorithmic event-betting)
- Bonds
- Mutual funds
- Physical commodities

### Advanced methods
- Monte Carlo simulation for stress-testing
- ML/RL strategies (FinRL pattern)
- Adaptive reinforcement learning strategies
- Multi-source sentiment analysis (Twitter/X, Reddit, news)

### Platforms
- Native iOS/Android mobile app (vs current dashboard PWA)
- IB FYI alerts integration
- TradingView Pine Script importer (compile Pine → Python Strategy)
- MT4/MT5 bridge

### Integrations
- WhatsApp Business API multi-country
- Slack integration
- Apple Watch quick approval
- Voice approval (Whisper + LLM intent)

### Observability
- Distributed OpenTelemetry tracing
- Pre-built Grafana dashboards
- Honeycomb integration

### Nautilus migration (if v3 scales)
- Migrate execution engine to NautilusTrader as backend (keeping the iguanatrader API in pure Python as a wrapper)

---

## Operational risks (not features, require a decision)

### ⚠️ Bus factor 1
**The most serious one.** If you go OSS, explicit governance from day 1:
- Documented co-maintainer (sibling? trusted friend with Python knowledge?)
- Or Foundation-style governance (Hummingbot model)
- Succession plan if something happens to you

**Action**: document in `docs/governance.md` before the OSS launch (likely v2-v3).

### ⚠️ No Docker in MVP — MITIGATED
Promoted to v1 MVP. Basic Docker + docker-compose from the first release.

### ⚠️ 0 docs / 0 community — PARTIALLY MITIGATED
Base docs promoted to v1 MVP. Community building begins in v3 with OSS launch.

### ⚠️ Regulatory risk if SaaS
For v3 SaaS:
- Audit whether it falls under "investment advisor" (US SEC/FINRA) or "investment service" (EU MiFID II)
- Maintain the "the user is the one with the IBKR account; you only orchestrate their software" architecture
- Consider entering EU first (clearer regulation)

---

## Architectural decisions that affect v1 (proposed ADRs)

| ADR | Decision |
|---|---|
| ADR-001 | 12-hook Strategy lifecycle (Lumibot pattern) |
| ADR-002 | MessageBus + separate Engines in pure Python (Nautilus pattern) |
| ADR-003 | License **Apache-2.0 + Commons Clause** from the first commit |
| ADR-004 | `BrokerageModel` per broker from MVP (Lean pattern) |
| ADR-005 (post-MVP) | v3 SaaS 3-tier `Solo / Team / Pro` |
| ADR-006 (revised) | Declarative risk engine in yaml, non-bypassable from Strategy code, config-disableable, Telegram-overrideable with audit log |
| ADR-007 | Telegram + WhatsApp catalog via Hermes |
| **ADR-008 (NEW)** | **Per-symbol strategy config in yaml — each symbol activates/deactivates/configures its own strategy** |
| **ADR-009 (NEW)** | **Strategies included in MVP: only DonchianATR + SMA cross. The rest in v1.5 (RSI/Bollinger/MACD), v2 (pairs/multi-tf), v3 (sector/earnings/risk-parity)** |
| **ADR-010 (NEW)** | **IBKR Execution Algorithms are exposed as an optional `execution_algo` in each strategy config (Adaptive/TWAP/VWAP in v1.5)** |

---

## ADR-008 — Per-symbol strategy config (detail)

### Decision
Each symbol has its own (strategy + parameters + enabled state). Configurable in yaml, hot-reloadable via `/reload_config`.

### Proposed schema

```yaml
# config/strategies.yaml

defaults:
  strategy: DonchianATR
  params:
    period: 20
    atr_multiplier: 2.0
  execution_algo: Adaptive  # optional, default Adaptive from v1.5

symbols:
  SPY:
    enabled: true
    strategy: DonchianATR
    params: {period: 30, atr_multiplier: 2.5}

  QQQ:
    enabled: true
    strategy: SMA_Cross
    params: {fast: 50, slow: 200}

  AAPL:
    enabled: true
    strategy: RSI_MeanReversion  # available in v1.5
    params: {rsi_period: 14, oversold: 30, overbought: 70}

  TSLA:
    enabled: false  # disabled but config preserved (toggle from Telegram)
    strategy: BollingerBreakout
    params: {period: 20, num_std: 2.0}

  # complex strategy (v2)
  KO_PEP_PAIR:
    enabled: false
    strategy: PairsTrading
    params:
      symbol_a: KO
      symbol_b: PEP
      lookback: 60
      entry_zscore: 2.0
      exit_zscore: 0.5
```

### Derived Telegram commands

| Command | Function |
|---|---|
| `/strategies` | List symbols + strategy + state (enabled/disabled) |
| `/enable_symbol <symbol>` | Activates strategy for symbol |
| `/disable_symbol <symbol>` | Deactivates strategy (keeps open positions) |
| `/set_strategy <symbol> <strategy_name>` | Changes a symbol's strategy |
| `/set_param <symbol> <param> <value>` | Hot-tune a param without restarting |
| `/list_strategies` | Catalog of strategies available in this version |

### Architectural implication

- `StrategyManager` loads `config/strategies.yaml` at startup and on `/reload_config`
- Each `(symbol, strategy)` instantiates a `StrategyInstance` with its independent state
- The `RiskEngine` sees all concurrent proposals and applies caps at portfolio level (not per-strategy)
- The `ApprovalChannel` shows the `symbol + strategy_name` in each proposal so the user knows "what is suggesting what"
- Hot-disable from Telegram does NOT close open positions (that requires an explicit `/forceexit`)

---

## Catalog of supported strategies (full view)

| Strategy | Version | Description | Main parameters |
|---|---|---|---|
| **DonchianATR** | v1.0 | Breakout of the N-period high, ATR-based sizing | `period`, `atr_multiplier` |
| **SMA_Cross** | v1.0 | Fast SMA crossing over slow SMA | `fast`, `slow` |
| **RSI_MeanReversion** | v1.5 | Buy oversold, sell overbought | `rsi_period`, `oversold`, `overbought` |
| **BollingerBreakout** | v1.5 | Band crossing with volume confirmation | `period`, `num_std`, `vol_filter` |
| **MACD_Cross** | v1.5 | MACD signal line cross | `fast`, `slow`, `signal` |
| **VolumeBreakoutDonchian** | v1.5 | DonchianATR + anomalous volume filter | `period`, `atr_mult`, `vol_threshold` |
| **PairsTrading** | v2 | Long A short B when spread diverges from mean | `symbol_a`, `symbol_b`, `lookback`, `entry_z`, `exit_z` |
| **ZScoreMeanReversion** | v2 | Statistical mean reversion without directional bias | `lookback`, `entry_z`, `exit_z` |
| **MultiTimeframeTrendFollowing** | v2 | Confluence 1D + 1H + 15m | `tf_macro`, `tf_meso`, `tf_micro` |
| **SectorRotation** | v3 | Monthly momentum of sector ETFs | `etfs_list`, `lookback_months`, `top_n` |
| **EarningsPostDrift** | v3 | Event-driven on earnings calendar | `min_surprise_pct`, `holding_period` |
| **RiskParityRebalance** | v3 | Systematic monthly allocation | `target_vol`, `rebalance_freq` |
| **CustomMLStrategy** | v3 | Pluggable ML/RL (FinRL pattern) | Serializable model + features pipeline |
