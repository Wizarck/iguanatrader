# iguanatrader — Backlog & Roadmap

**Fecha:** 2026-04-27
**Owner:** Arturo
**Política:** Nada se descarta. Todo lo identificado va a una versión o al backlog libre.

**Leyenda:**
- 🟢 Confirmado en su versión
- 🟡 Propuesto, pendiente de validación
- 🎯 Diferenciador único
- ⚠️ Riesgo / hueco a vigilar
- 📅 Fecha objetivo (si aplica)

---

## v1.0 — MVP (current scope)

> **Objetivo:** dogfooding personal funcional. Tú apruebas trades reales en IBKR vía Telegram + WhatsApp con un risk engine que no se salta. Backtest reproducible. Cost observability del LLM stack.

### Foundation
- 🟢 Estructura repo `src/iguanatrader/`
- 🟢 Pydantic Settings + yaml configs
- 🟢 SQLite append-only con `tenant_id` first-class (schema multi-tenant ready)
- 🟢 Types: `Bar`, `Signal`, `Order`, `Fill`, `Position`, `ApiCostEvent`, `RiskOverride`
- 🟢 Tests unitarios + property tests (hypothesis sobre risk caps)
- 🟢 License **Apache-2.0 + Commons Clause** desde primer commit 🎯
- 🟢 SOPS (age) para secrets + gitleaks pre-commit
- 🟢 **Docker + docker-compose** (mitigable, sube a MVP)
- 🟢 **Docs base** (`getting-started.md`, `architecture.md`, `runbook.md`, `strategies/donchian_atr.md`)

### Engine architecture (Nautilus pattern adaptado)
- 🟢 `MessageBus` con asyncio.Queue (pub/sub + cmd/event)
- 🟢 Engines separados: `DataEngine`, `ExecutionEngine`, `RiskEngine`, `Cache`
- 🟢 Cache-before-handler ordering guarantee
- 🟢 Single-threaded asyncio event loop

### Backtest engine
- 🟢 Event-driven, mismo loop que live
- 🟢 Slippage paramétrico (5-15 bps small-cap / 1-3 bps large-cap)
- 🟢 Commission modeling realista (IBKR rates)
- 🟢 `BrokerageModel` per broker (Lean pattern) 🎯
- 🟢 Métricas: Sharpe, Sortino, Calmar, max DD, profit factor
- 🟢 Fixtures históricas para tests

### BrokerInterface (mitigable, sube a v1)
- 🟢 Interface abstracta `BrokerInterface` desde día 1
- 🟢 Adapter `IBKRAdapter` (vía `ib_async` + TWS Gateway)
- 🟢 Switch `paper:true/false` único (no dual-class) — Lumibot pattern
- 🟢 Reconciliación periódica con broker state

### Risk engine (Freqtrade Protections pattern)
- 🟢 Protections declarativas en `config/risk.yaml`
- 🟢 `PerTradeRisk` (default 2%)
- 🟢 `DailyLossCap` (5% kill-switch hasta T+1)
- 🟢 `WeeklyLossCap` (15% kill-switch hasta L+1)
- 🟢 `MaxOpenPositions` (default 5)
- 🟢 `MaxDrawdown` (configurable threshold)
- 🟢 ATR-based position sizing (input al risk engine)
- 🟢 Master switch `enable_protections: true`
- 🟢 Kill-switch file (`.killswitch`) + env var (`IGUANA_HALT`)
- 🟢 Override vía Telegram (`/override <id> <reason>`) con audit log inmutable 🎯
- 🟢 RiskEngine NO bypaseable desde código de Strategy (declarativo only)

### Strategy interface (Lumibot pattern)
- 🟢 Lifecycle 12 hooks: `initialize`, `before_starting_trading`, `before_market_opens`, `on_trading_iteration`, `before_market_closes`, `after_market_closes`, `on_new_order`, `on_partially_filled_order`, `on_filled_order`, `on_canceled_order`, `on_parameters_updated`, `on_bot_crash`
- 🟢 `parameters` first-class + hot-reload via `on_parameters_updated`
- 🟢 **Per-symbol strategy config** (yaml-driven) 🎯

### Estrategias incluidas en MVP
- 🟢 **DonchianBreakout + ATR** (v0 — golden path)
- 🟢 **SMA Cross** (smoke test del end-to-end)

### Approval gate (Freqtrade Telegram pattern)
- 🟢 `ApprovalChannel` abstracto
- 🟢 `TelegramChannel` (`python-telegram-bot` con inline buttons)
- 🟢 `WhatsAppChannel` vía Hermes/Meta API 🎯
- 🟢 ~17 comandos: `/start`, `/stop`, `/pause`, `/reload_config`, `/propose`, `/approve`, `/reject`, `/forceexit`, `/status`, `/balance`, `/profit`, `/daily`, `/weekly`, `/performance`, `/trades`, `/logs`, `/risk_status`, `/cost_today`, `/cost_week`, `/halt`, `/resume`, `/override`, `/version`, `/help`
- 🟢 Per-user authorization (`authorized_phones`, `authorized_telegram_ids`)
- 🟢 Approval timeout configurable (default 60s) — si no respondes, propuesta descartada + log
- 🟢 Hindsight `bank-id` per user/teléfono (memoria aislada) 🎯

### Web dashboard
- 🟢 FastAPI + HTMX + Jinja2 + Plotly.js (mobile-first, localhost en MVP)
- 🟢 `/` — equity curve live + drawdown + posiciones abiertas + kill-switch button
- 🟢 `/approvals` — cola de propuestas pending (mismo backend que Telegram)
- 🟢 `/trades` — histórico filtrable (timestamp, symbol, side, qty, P&L, holding period)
- 🟢 `/portfolio` — per-symbol P&L + asset allocation + cash
- 🟢 `/costs` — USD/día por proveedor + por nodo LangGraph + ratio cost-per-trade 🎯
- 🟢 `/risk` — estado de risk caps + audit trail de overrides
- 🟢 `/runs` — histórico de backtests + live sessions

### LangGraph orchestration (Capa 3)
- 🟢 Nodes: `premarket_briefing` (8:30 ET), `midday_check` (1 PM ET), `postmarket_summary` (4:30 PM ET), `weekly_review` (Vie 6 PM ET, PDF) 🎯
- 🟢 Cron-jobs proactivos tier-graded (Tier 1 hardcoded / Tier 2 LLM-filtered / Tier 3 routine) 🎯
- 🟢 Multi-model routing: Opus 4.7 research / Sonnet 4.6 routines / Haiku 4.5 alerts triviales 🎯
- 🟢 Perplexity API para news/sentiment
- 🟢 LLM **propone**, NO ejecuta (constraint arquitectónico)

### Cost & P&L observability
- 🟢 `ApiCostEvent` table (provider, model, node, tokens in/out, cache reads/writes, USD cost)
- 🟢 `CostMeter` wrapper sobre Anthropic + Perplexity SDKs
- 🟢 Tabla precios versionada `config/llm_prices.yaml`
- 🟢 **Replay caching de LLM calls en backtest** (Lumibot pattern) 🎯
- 🟢 `PnLCalculator`: per-trade FIFO, per-symbol, per-portfolio (realized + unrealized)
- 🟢 EquitySnapshot timeseries (cada N min en sesión activa)

### Operacional
- 🟢 CLI `iguana` (typer): `ingest`, `backtest`, `paper`, `live`, `dashboard`, `propose`, `halt`, `resume`
- 🟢 Structured JSON logs (structlog) + rotación
- 🟢 Crash recovery (resume from last consistent state)
- 🟢 GitHub Project mandatory + `issue_sync.py` automation

### Ya en plan, **NO en MVP** (mover explícito)
- ❌ Migración engine a Lumibot/Lean/Nautilus en v2 (BrokerInterface deja la puerta)

---

## v1.5 — Quick wins post-MVP

> **Objetivo:** cubrir los huecos cómodos de v1 que dolerán pronto. Aún single-user, sin SaaS.

### Estrategias adicionales (catálogo retail equity)
- 🟡 **RSI mean-reversion** (counter-trend en oversold/overbought)
- 🟡 **Bollinger Bands breakout/squeeze** (vol-based)
- 🟡 **MACD crossover** (momentum-based)
- 🟡 **Volume-weighted Donchian** (Donchian + filtro volumen)

### IBKR Execution Algorithms (algos de orden, no de decisión)
- 🟡 **Adaptive** — el más recomendado para retail
- 🟡 **TWAP** — Time-Weighted Average Price
- 🟡 **VWAP** — Volume-Weighted Average Price
- 🟡 **Snap (Bid/Mid/Ask)** — captura puntual

### Risk engine extensiones (Freqtrade-style)
- 🟡 **StoplossGuard** (pause tras N stoploss consecutivos)
- 🟡 **CooldownPeriod** (tiempo mínimo entre trades del mismo symbol)
- 🟡 **Trailing stops dinámicos** (custom_stoploss equivalent)

### Backtest engine extensiones
- 🟡 **Walk-forward analysis**
- 🟡 **HTML report auto-generado** (Lean pattern)
- 🟡 **Datos Polygon** (premium opcional vs Yahoo MVP)

### Operacional
- 🟡 **Hot-reload de strategy code** (sin restart)
- 🟡 **Postgres opcional** (mismo schema, swap SQLite ↔ Postgres por config)
- 🟡 **Variable backup/restore** (Lumibot pattern)
- 🟡 **Prometheus metrics export**

---

## v2 — Multi-broker + SaaS preparation

> **Objetivo:** validar arquitectura multi-tenant. Múltiples brokers. Lista para invitar 5-10 beta users si se decide OSS launch.

### Brokers adicionales (BrokerInterface ya lista)
- 🟡 **AlpacaAdapter** (equity US, free)
- 🟡 **SchwabAdapter**
- 🟡 **TradierAdapter**

### Order types
- 🟡 OCO (one-cancels-other)
- 🟡 Bracket orders
- 🟡 IBKR Iceberg + PassRelative + Percentage of Volume

### Estrategias sofisticadas
- 🟡 **Pairs trading / cointegration** (long A short B cuando spread se aleja)
- 🟡 **Z-score mean reversion** (statistical)
- 🟡 **Multi-timeframe trend following** (confluence 1D + 1H + 15m)

### Risk engine
- 🟡 **LowProfitPairs blocker** (Freqtrade pattern)

### Notificaciones
- 🟡 Email alerts
- 🟡 Discord integration

### UI
- 🟡 Hot-reload de config UI desde dashboard
- 🟡 Strategy visualization (estrategia activa + recent signals)
- 🟡 Order management UI (cancel/modify desde web)

### Multi-asset
- 🟡 **Futures** (CME via IBKR — micros: MES, MNQ, MGC, MCL)

### Multi-tenant infra
- 🟡 Per-user secrets aislados (SOPS per tenant)
- 🟡 1 proceso/container per tenant pattern (Docker Compose orchestration)

---

## v3 — SaaS launch

> **Objetivo:** producto comercial. OSS Apache + Commons Clause + tier paid hosted. Decisión basada en evidencia: si v2 valida adopción + tu propio dogfooding genera P&L positivo.

### Pricing
- 🟡 **3 tiers**: Solo / Team / Pro (inspirado QC simplificado)
- 🟡 Free tier: backtest unlimited, sin live
- 🟡 Solo paid: paper + live single-broker
- 🟡 Team paid: 3-5 seats, multi-broker, dashboard compartido
- 🟡 Pro: unlimited compute, soporte SLA, multi-strategy concurrente

### Onboarding & billing
- 🟡 Sign-up flow + email verification
- 🟡 Broker connect wizard (OAuth donde aplique)
- 🟡 Stripe integration

### Estrategias avanzadas
- 🟡 **Sector rotation** (momentum mensual ETFs sectoriales)
- 🟡 **Earnings post-drift** (event-driven sobre calendar)
- 🟡 **Risk parity rebalancing** (allocation systemática mensual)

### Multi-asset expansion
- 🟡 **Cripto exchanges** vía CCXT (Binance, Coinbase, Kraken)
- 🟡 **DEX support** (Hyperliquid, dYdX, Polymarket)
- 🟡 **Forex** (OANDA via IBKR)

### IBKR Execution Algos avanzados
- 🟡 DarkIce (dark pool + iceberg combo)
- 🟡 Accumulate-Distribute (builds graduales)
- 🟡 ArrivalPx (benchmark al precio de arrival)

### LLM features avanzadas
- 🟡 **LLM strategy codegen** (Composer/BotSpot pattern — usuario describe NL, LLM genera Strategy class)
- 🟡 **Strategy marketplace** (usuarios comparten estrategias, marketplace con revenue share)
- 🟡 Distributed hyperopt (Ray cluster)
- 🟡 Cohort-based course (education flywheel)
- 🟡 Discord community + Foundation-style governance

---

## Backlog libre — sin compromiso de versión

Cosas identificadas que NO están planificadas. Ideas para considerar si surge demanda real.

### Asset classes nicho
- Polymarket / Betfair (event-betting algorítmico)
- Bonds
- Mutual funds
- Comodidades físicas

### Métodos avanzados
- Monte Carlo simulation para stress-testing
- ML/RL strategies (FinRL pattern)
- Reinforcement learning estrategias adaptativas
- Sentiment analysis multi-source (Twitter/X, Reddit, news)

### Plataformas
- Mobile app nativa iOS/Android (vs PWA actual del dashboard)
- IB FYI alerts integration
- TradingView Pine Script importer (compilar Pine → Python Strategy)
- MT4/MT5 bridge

### Integraciones
- WhatsApp Business API multi-país
- Slack integration
- Apple Watch quick approval
- Voice approval (Whisper + LLM intent)

### Observabilidad
- OpenTelemetry tracing distribuido
- Grafana dashboards pre-built
- Honeycomb integration

### Nautilus migration (si v3 escala)
- Migrar engine de execution a NautilusTrader como backend (manteniendo iguanatrader API en Python puro como wrapper)

---

## Riesgos operacionales (no son features, requieren decisión)

### ⚠️ Bus factor 1
**El más serio.** Si vas OSS, gobernanza explícita desde día 1:
- Co-maintainer documentado (¿hermano? ¿amigo de confianza con conocimiento Python?)
- O Foundation-style governance (modelo Hummingbot)
- Plan de sucesión si te pasa algo

**Acción**: documentar en `docs/governance.md` antes del OSS launch (probable v2-v3).

### ⚠️ Sin Docker en MVP — MITIGADO
Subido a v1 MVP. Docker + docker-compose básico desde primer release.

### ⚠️ 0 docs / 0 community — MITIGADO parcialmente
Docs base subidas a v1 MVP. Community building empieza en v3 con OSS launch.

### ⚠️ Riesgo regulatorio si SaaS
Para v3 SaaS:
- Auditar si cae en "investment advisor" (US SEC/FINRA) o "investment service" (EU MiFID II)
- Mantener arquitectura "el usuario es quien tiene la cuenta IBKR; tú solo orquestas su software"
- Considerar entrar en EU primero (regulación más clara)

---

## Decisiones arquitectónicas que afectan v1 (ADRs propuestos)

| ADR | Decisión |
|---|---|
| ADR-001 | Strategy lifecycle de 12 hooks (Lumibot pattern) |
| ADR-002 | MessageBus + Engines separados en Python puro (Nautilus pattern) |
| ADR-003 | License **Apache-2.0 + Commons Clause** desde primer commit |
| ADR-004 | `BrokerageModel` per broker desde MVP (Lean pattern) |
| ADR-005 (post-MVP) | v3 SaaS tier 3-niveles `Solo / Team / Pro` |
| ADR-006 (revisado) | Risk engine declarativo en yaml, no-bypaseable desde Strategy code, config-deshabilitable, Telegram-overrideable con audit log |
| ADR-007 | Catálogo Telegram + WhatsApp via Hermes |
| **ADR-008 (NUEVO)** | **Per-symbol strategy config en yaml — cada symbol activa/desactiva/configura su propia strategy** |
| **ADR-009 (NUEVO)** | **Estrategias incluidas en MVP: solo DonchianATR + SMA cross. Resto en v1.5 (RSI/Bollinger/MACD), v2 (pairs/multi-tf), v3 (sector/earnings/risk-parity)** |
| **ADR-010 (NUEVO)** | **IBKR Execution Algorithms se exponen como `execution_algo` opcional en cada strategy config (Adaptive/TWAP/VWAP en v1.5)** |

---

## ADR-008 — Per-symbol strategy config (detalle)

### Decisión
Cada symbol tiene su propio (estrategia + parámetros + estado enabled). Configurable en yaml, hot-reloadable vía `/reload_config`.

### Schema propuesto

```yaml
# config/strategies.yaml

defaults:
  strategy: DonchianATR
  params:
    period: 20
    atr_multiplier: 2.0
  execution_algo: Adaptive  # opcional, default Adaptive desde v1.5

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
    strategy: RSI_MeanReversion  # disponible en v1.5
    params: {rsi_period: 14, oversold: 30, overbought: 70}

  TSLA:
    enabled: false  # disabled but config preservada (toggle desde Telegram)
    strategy: BollingerBreakout
    params: {period: 20, num_std: 2.0}

  # estrategia compleja (v2)
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

### Comandos Telegram derivados

| Comando | Función |
|---|---|
| `/strategies` | Lista symbols + strategy + estado (enabled/disabled) |
| `/enable_symbol <symbol>` | Activa strategy para symbol |
| `/disable_symbol <symbol>` | Desactiva strategy (mantiene posiciones abiertas) |
| `/set_strategy <symbol> <strategy_name>` | Cambia strategy de un symbol |
| `/set_param <symbol> <param> <value>` | Hot-tunear un param sin reiniciar |
| `/list_strategies` | Catálogo de strategies disponibles en esta versión |

### Implicación arquitectónica

- `StrategyManager` carga `config/strategies.yaml` al arranque y al `/reload_config`
- Cada `(symbol, strategy)` instancia un `StrategyInstance` con su estado independiente
- El `RiskEngine` ve todas las propuestas concurrentes y aplica caps a nivel portfolio (no per-strategy)
- El `ApprovalChannel` muestra el `symbol + strategy_name` en cada propuesta para que el usuario sepa "qué está sugiriendo qué"
- Hot-disable desde Telegram NO cierra posiciones abiertas (eso requiere `/forceexit` explícito)

---

## Catálogo de estrategias soportadas (visión completa)

| Estrategia | Versión | Descripción | Parámetros principales |
|---|---|---|---|
| **DonchianATR** | v1.0 | Breakout del high de N periodos, sizing ATR-based | `period`, `atr_multiplier` |
| **SMA_Cross** | v1.0 | Cross fast SMA over slow SMA | `fast`, `slow` |
| **RSI_MeanReversion** | v1.5 | Buy oversold, sell overbought | `rsi_period`, `oversold`, `overbought` |
| **BollingerBreakout** | v1.5 | Cruce de banda con confirmación volumen | `period`, `num_std`, `vol_filter` |
| **MACD_Cross** | v1.5 | Cross signal line del MACD | `fast`, `slow`, `signal` |
| **VolumeBreakoutDonchian** | v1.5 | DonchianATR + filtro de volumen anómalo | `period`, `atr_mult`, `vol_threshold` |
| **PairsTrading** | v2 | Long A short B cuando spread se aleja del mean | `symbol_a`, `symbol_b`, `lookback`, `entry_z`, `exit_z` |
| **ZScoreMeanReversion** | v2 | Mean reversion estadística sin direction bias | `lookback`, `entry_z`, `exit_z` |
| **MultiTimeframeTrendFollowing** | v2 | Confluence 1D + 1H + 15m | `tf_macro`, `tf_meso`, `tf_micro` |
| **SectorRotation** | v3 | Momentum mensual de ETFs sectoriales | `etfs_list`, `lookback_months`, `top_n` |
| **EarningsPostDrift** | v3 | Event-driven sobre earnings calendar | `min_surprise_pct`, `holding_period` |
| **RiskParityRebalance** | v3 | Allocation systemática mensual | `target_vol`, `rebalance_freq` |
| **CustomMLStrategy** | v3 | Pluggable ML/RL (FinRL pattern) | Modelo serializable + features pipeline |
