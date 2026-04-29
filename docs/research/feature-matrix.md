# Feature Matrix — NautilusTrader vs Freqtrade vs iguanatrader

**Fecha:** 2026-04-27
**Propósito:** Comparar features clave entre los 2 frameworks OSS más relevantes y la propuesta de iguanatrader (MVP / v2 / v3) para identificar diferenciación real y huecos honestos.

**Leyenda**:
- ✅ Implementado y maduro
- ⚠️ Implementado pero limitado / con caveats
- ❌ No implementado
- 📅 MVP / 📅v2 / 📅v3 — planeado en esa fase de iguanatrader
- 🎯 Diferenciador único de iguanatrader

---

## 1. Architecture & Engine

| Feature | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| Event-driven architecture | ✅ Nanosecond determinismo | ❌ Vectorizado pandas | ✅ asyncio event loop 📅 MVP |
| MessageBus + separated engines | ✅ Pub/Sub, Cmd/Event | ❌ Monolítico | ✅ asyncio.Queue + pub/sub 📅 MVP |
| Single-threaded kernel | ✅ Garantía de orden | N/A | ✅ asyncio single loop 📅 MVP |
| Rust core | ✅ Hot paths | ❌ Python puro | ❌ Python puro (decisión) |
| Cache-before-handler ordering | ✅ Garantizado | N/A | ✅ 📅 MVP |
| Redis para durabilidad cross-restart | ✅ Opcional | ❌ | ❌ MVP / 📅v2 |
| Multi-strategy concurrente | ✅ | ⚠️ Con caveats | 📅 v2 |
| Multi-asset multi-venue | ✅ | ⚠️ Solo cripto | ⚠️ Solo equity US en MVP / 📅v2 multi-asset |

---

## 2. Strategy Interface

| Feature | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| Lifecycle hooks (`on_start`, `on_bar`, etc.) | ✅ ~10 hooks | ⚠️ 3 mandatorios (`populate_X`) + ~10 callbacks | ✅ 12 hooks (Lumibot pattern) 📅 MVP |
| Indicator helpers integrated | ⚠️ Externos | ✅ TA-Lib + qtpylib | ✅ TA-Lib + custom DonchianATR 📅 MVP |
| Multi-timeframe support | ✅ Built-in | ✅ `@informative('1h')` decorator | 📅 v2 |
| Parameter declarations (for sweeps) | ⚠️ Externos | ✅ `IntParameter`, `RealParameter`, `BooleanParameter`, `CategoricalParameter` | ✅ Pydantic Settings + Optuna 📅 MVP |
| Custom entry/exit price | ✅ | ✅ `custom_entry_price`, `custom_exit_price` | 📅 v2 |
| Custom stake amount | ✅ | ✅ `custom_stake_amount` | ✅ ATR-based sizing 📅 MVP |
| Hot-reload de strategy code | ❌ | ⚠️ Restart needed | ❌ MVP / 📅v2 |
| Strategy as a class with parameters dict | ✅ | ✅ | ✅ 📅 MVP |

---

## 3. Order Management

| Feature | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| Market orders | ✅ | ✅ | ✅ 📅 MVP |
| Limit orders | ✅ | ✅ | ✅ 📅 MVP |
| Stop / stop-limit | ✅ | ✅ | ✅ 📅 MVP |
| Trailing stops | ✅ | ✅ `custom_stoploss` | 📅 v2 |
| OCO (one-cancels-other) | ✅ | ⚠️ Limited | 📅 v2 |
| Bracket orders | ✅ | ❌ | 📅 v2 |
| Order cancellation API | ✅ | ✅ `/cancel_open_order` Telegram | ✅ 📅 MVP |
| Reload trade from exchange | ⚠️ | ✅ `/reload_trade` | 📅 v2 |
| Force exit / force entry | ⚠️ Custom | ✅ `/forceexit`, `/forcelong` Telegram | ✅ vía Telegram 📅 MVP |
| Multi-leg orders (options spreads) | ✅ | ❌ | ❌ MVP / 📅v3 (si options entran) |

---

## 4. Risk Management

| Feature | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| Pre-trade position limits | ✅ Built-in RiskEngine | ✅ Implícito | ✅ 📅 MVP |
| Pre-trade notional limits | ✅ | ⚠️ Via stake | ✅ 📅 MVP |
| Order rate limits | ✅ | ⚠️ Via cooldown | ✅ 📅 MVP |
| Per-trade size cap (% capital) | ✅ Custom | ✅ `stake_amount` | ✅ 2% default 📅 MVP |
| Stop-loss (fixed %) | ✅ | ✅ `stoploss = -0.10` | ✅ 📅 MVP |
| Stop-loss dinámico / custom | ✅ | ✅ `custom_stoploss` | 📅 v2 |
| Trailing stop-loss | ✅ | ✅ | 📅 v2 |
| Max daily loss cap | ⚠️ Custom | ⚠️ Via MaxDrawdown | ✅ 5% kill-switch 📅 MVP 🎯 |
| Max weekly loss cap | ⚠️ Custom | ⚠️ Via MaxDrawdown | ✅ 15% kill-switch 📅 MVP 🎯 |
| Max open positions | ✅ | ✅ `max_open_trades` | ✅ 5 default 📅 MVP |
| Drawdown protection automática | ✅ | ✅ `MaxDrawdown` Protection | ✅ 📅 MVP |
| Stoploss guard (consecutive losses) | ⚠️ Custom | ✅ `StoplossGuard` | 📅 v2 |
| Cooldown period entre trades | ⚠️ Custom | ✅ `CooldownPeriod` | 📅 v2 |
| Low profit pairs blocker | ❌ | ✅ `LowProfitPairs` | ❌ MVP / 📅v3 |
| Risk engine declarativo en yaml | ⚠️ Custom | ✅ `protections: [...]` | ✅ Freqtrade pattern 📅 MVP |
| Kill-switch file-based / env | ⚠️ Custom | ❌ | ✅ `.killswitch` file + `IGUANA_HALT` env 📅 MVP |
| Kill-switch desde Telegram | ❌ | ⚠️ `/stop` (para todo) | ✅ `/halt` específico 📅 MVP 🎯 |
| Override risk caps con motivo + log inmutable | ❌ | ⚠️ `/forcelong` con `force_entry_enable` | ✅ `/override <reason>` 📅 MVP 🎯 |

---

## 5. Backtest Engine

| Feature | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| Mismo código que live | ✅ Mismo runtime real | ✅ Diferente engine pero misma Strategy | ✅ Mismo loop 📅 MVP |
| Determinismo guaranteed | ✅ Nanosecond | ✅ Vectorizado | ⚠️ Microsecond (asyncio) 📅 MVP |
| Slippage modeling | ✅ | ✅ Configurable | ✅ Paramétrico 5-15bps small / 1-3bps large 📅 MVP |
| Commission modeling | ✅ | ✅ | ✅ IBKR realistic 📅 MVP |
| Reject simulation | ✅ Via BrokerageModel | ⚠️ Limited | ✅ Via BrokerageModel 📅 MVP |
| Multiple data sources (Yahoo, Polygon, IBKR) | ⚠️ Catalog-based | ✅ Multiple via plugins | ⚠️ Yahoo + IBKR cache 📅 MVP / 📅v2 Polygon |
| Walk-forward analysis | ✅ | ✅ | 📅 v2 |
| Monte Carlo simulation | ❌ | ⚠️ Custom | 📅 v3 |
| LLM replay caching en backtest | ❌ | ❌ | ✅ Lumibot pattern 📅 MVP 🎯 |
| `BrokerageModel` per broker (paridad backtest↔live) | ⚠️ Implícito | ⚠️ Implícito | ✅ Lean pattern explícito 📅 MVP |
| Equity curve metrics (Sharpe, Sortino, Calmar, max DD) | ✅ | ✅ | ✅ 📅 MVP |
| HTML report auto-generado | ⚠️ Limited | ⚠️ Limited | ✅ Lean pattern 📅 v2 |

---

## 6. Hyperopt / Optimization

| Feature | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| Parameter sweeps | ⚠️ Externos | ✅ Optuna built-in | ✅ vectorbt research + Optuna 📅 MVP |
| Walk-forward optimization | ⚠️ | ✅ | 📅 v2 |
| Distributed optimization | ✅ | ✅ Ray | 📅 v3 |
| Cross-validation | ⚠️ | ✅ | 📅 v2 |
| Vectorized sweep engine (vectorbt) | ❌ | ❌ | ✅ MVP usa vectorbt para grid-search 📅 MVP |

---

## 7. Brokers / Exchanges

| Broker | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| **Interactive Brokers (IBKR)** | ✅ Nativo | ❌ | ✅ `ib_async` 📅 MVP |
| Alpaca (equity) | ❌ | ❌ | 📅 v3 (vía adapter) |
| Schwab | ❌ | ❌ | 📅 v3 |
| Tradier | ❌ | ❌ | ❌ |
| Binance, Coinbase, Kraken (cripto CEX) | ✅ | ✅ Via CCXT | ❌ MVP / 📅v3 |
| OKX, Bybit | ✅ | ✅ | ❌ |
| Hyperliquid, dYdX (DEX) | ✅ | ❌ | ❌ |
| Polymarket | ✅ | ❌ | ❌ |
| Betfair | ✅ | ❌ | ❌ |
| Deutsche Börse | ✅ | ❌ | ❌ |
| Forex (OANDA, FXCM) | ⚠️ | ❌ | ❌ |
| Futures (CME, Tradovate) | ✅ | ❌ | 📅 v3 |
| **Total brokers/venues** | **~15** | **~25 cripto via CCXT** | **1 (IBKR) en MVP** |

---

## 8. Persistence & Data

| Feature | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| SQLite storage | ⚠️ Catalog parquet | ✅ SQLAlchemy | ✅ SQLite append-only 📅 MVP |
| Postgres support | ⚠️ | ✅ | 📅 v2 |
| Append-only mode | ⚠️ | ❌ Mutable | ✅ 📅 MVP |
| Multi-tenant ready (`tenant_id` first-class) | ❌ | ❌ | ✅ Schema desde día 1 📅 MVP 🎯 |
| Trade history table | ✅ | ✅ | ✅ 📅 MVP |
| Order history table | ✅ | ✅ | ✅ 📅 MVP |
| Equity snapshots time-series | ✅ | ✅ | ✅ 📅 MVP |
| **`ApiCostEvent` table (LLM cost obs)** | ❌ | ❌ | ✅ 📅 MVP 🎯 |
| `RiskOverride` table (audit trail) | ❌ | ❌ | ✅ 📅 MVP 🎯 |
| Variable backup/restore | ⚠️ | ⚠️ | 📅 v2 |
| Parquet historical bars | ✅ Catalog | ✅ | ✅ 📅 MVP |

---

## 9. Notifications & HITL (Human-in-the-Loop)

| Feature | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| **Telegram bot integrado** | ❌ | ✅ ~30 comandos | ✅ ~17 comandos 📅 MVP |
| Telegram inline buttons (callback queries) | ❌ | ✅ Custom keyboard | ✅ Approval buttons 📅 MVP 🎯 |
| **WhatsApp via Meta API** | ❌ | ❌ | ✅ Hermes integration 📅 MVP 🎯 |
| Webhook notifications | ✅ MessageBus | ✅ | ✅ 📅 MVP |
| Email alerts | ❌ | ⚠️ Plugin | 📅 v2 |
| Discord integration | ❌ | ✅ Plugin | 📅 v3 |
| **Approval gate per trade** | ❌ | ⚠️ `confirm_trade_entry` (código, no humano) | ✅ Humano vía Telegram/WhatsApp 📅 MVP 🎯 |
| Approval timeout configurable | N/A | N/A | ✅ Default 60s 📅 MVP 🎯 |
| Per-user authorization (whitelist) | N/A | ✅ `authorized_users` | ✅ Per phone/handle 📅 MVP |
| Custom notification verbosity | ❌ | ✅ `notification_settings` | ✅ Per channel 📅 MVP |
| **Proactive cron-job alerts (tier-graded)** | ❌ | ⚠️ Limited | ✅ Tier 1/2/3 system 📅 MVP 🎯 |
| News integration (Perplexity/external) | ❌ | ⚠️ Plugin | ✅ Perplexity built-in 📅 MVP |
| Pre-market briefing automatic | ❌ | ❌ | ✅ LangGraph node 📅 MVP 🎯 |
| Mid-day / post-market check | ❌ | ❌ | ✅ LangGraph nodes 📅 MVP 🎯 |
| Weekly review PDF | ❌ | ❌ | ✅ LangGraph node + PDF 📅 MVP 🎯 |

---

## 10. UI / Dashboard

| Feature | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| Web dashboard built-in | ⚠️ Externo | ✅ FreqUI (React) | ✅ FastAPI + HTMX 📅 MVP |
| Mobile-responsive | ⚠️ | ✅ FreqUI mobile | ✅ HTMX mobile-first 📅 MVP |
| Charts (equity curve, drawdown live) | ⚠️ | ✅ | ✅ Plotly.js 📅 MVP |
| Trades list view | ⚠️ | ✅ | ✅ 📅 MVP |
| Pending approvals UI | ❌ | ❌ | ✅ 📅 MVP 🎯 |
| Order management UI | ⚠️ | ✅ | ✅ 📅 v2 |
| **Cost dashboard (LLM USD/día)** | ❌ | ❌ | ✅ 📅 MVP 🎯 |
| Hot-reload de config UI | ❌ | ✅ via `/reload_config` | ✅ via `/reload_config` 📅 MVP |
| Kill-switch button UI | ❌ | ❌ | ✅ Big red button 📅 MVP 🎯 |
| Strategy visualization | ❌ | ⚠️ Limited | 📅 v3 |

---

## 11. AI / LLM Integration

| Feature | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| LLM integration philosophy | ⚠️ Externo (no opinion) | ⚠️ FreqAI (ML, no LLM) | ✅ LLM=copiloto, no auto-trader |
| LLM-generated strategies (codegen) | ❌ | ❌ | 📅 v3 (Composer/BotSpot pattern) |
| LLM en Strategy hot path | ❌ | ❌ | ❌ Por diseño (NO) |
| **LLM en research / orchestration** | ❌ | ❌ | ✅ LangGraph nodes 📅 MVP 🎯 |
| **Cost observability per LLM call** | ❌ | ❌ | ✅ `ApiCostEvent` SQLite 📅 MVP 🎯 |
| Cost-per-trade ratio metric | ❌ | ❌ | ✅ Dashboard `/costs` 📅 MVP 🎯 |
| Replay caching para backtest determinista | ❌ (Lumibot lo tiene) | ❌ | ✅ 📅 MVP |
| MCP server support (Model Context Protocol) | ❌ | ❌ | ✅ Anthropic/Perplexity MCPs 📅 MVP |
| Sentiment analysis news | ❌ | ⚠️ Plugin | ✅ Perplexity built-in 📅 MVP |
| LLM confidence threshold para alerts Tier 2 | ❌ | ❌ | ✅ Default 60/100 📅 MVP 🎯 |
| Multi-model routing (Opus vs Sonnet vs Haiku) | ❌ | ❌ | ✅ Opus research, Sonnet routines, Haiku alerts 📅 MVP 🎯 |

---

## 12. Multi-tenant / SaaS Readiness

| Feature | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| `tenant_id` first-class en schema | ❌ | ❌ | ✅ Día 1 📅 MVP 🎯 |
| Per-user secrets (broker creds aisladas) | ❌ | ❌ | ✅ SOPS per tenant 📅 v2 |
| Per-user Hindsight bank (memoria aislada) | N/A | N/A | ✅ `bank-id` por phone 📅 MVP 🎯 |
| Multi-instance per host (1 proceso/tenant) | ⚠️ | ✅ Docker pattern | ✅ Container pattern 📅 v2 |
| Tier-based pricing structure | ⚠️ Cloud paid | ❌ OSS only | ✅ Solo/Team/Pro 📅 v3 |
| Onboarding flow (sign-up, broker connect) | ⚠️ Cloud | ❌ | 📅 v3 |
| Billing integration (Stripe etc.) | ⚠️ Cloud | ❌ | 📅 v3 |

---

## 13. Operational

| Feature | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| CLI maduro | ⚠️ | ✅ `freqtrade` cmd | ✅ `iguana` typer 📅 MVP |
| Docker support | ✅ | ✅ Imagen oficial | 📅 v2 |
| Daemon / always-on mode | ✅ | ✅ | ✅ 📅 MVP |
| Crash recovery | ✅ | ✅ | ✅ 📅 MVP |
| Structured JSON logs | ✅ | ✅ | ✅ structlog 📅 MVP |
| Prometheus metrics | ⚠️ | ✅ | 📅 v2 |
| `dry-run` flag (paper trading) | ⚠️ Catalog mode | ✅ Inviolable | ✅ Inviolable 📅 MVP |
| Hot-reload de config | ❌ | ✅ `/reload_config` | ✅ 📅 MVP |
| Rolling logs | ✅ | ✅ | ✅ 📅 MVP |

---

## 14. License & Community

| Aspect | NautilusTrader | Freqtrade | iguanatrader |
|---|---|---|---|
| **License** | LGPL-3.0 | GPL-3.0 | **Apache-2.0 + Commons Clause** 🎯 |
| Permite SaaS comercial cerrado encima | ⚠️ Con dynamic linking | ❌ | ✅ |
| Stars (2026-04) | 22.288 | 49.440 | 0 |
| Bus factor estimado | Alto (Nautech Systems Pty Ltd) | Medio-alto (Matthias V + comunidad) | **Bajo (Arturo solo)** ⚠️ |
| Discord / community | ✅ Activo | ✅ Activo enorme | ❌ MVP / 📅v3 |
| Documentación madurez | Alta | Muy alta | Baja MVP / 📅v2 |
| Years in production | 5+ | 8+ | 0 |
| Battle-testing | Hedge funds | Retail crypto masivo | 0 |

---

## 🎯 Diferenciadores únicos de iguanatrader (lo que NADIE más hace)

Marcados con 🎯 en la matriz:

1. **Approval gate humano per trade** vía Telegram + WhatsApp (NEITHER lo tiene; Freqtrade tiene `confirm_trade_entry` pero es código, no humano)
2. **WhatsApp via Meta API + Telegram** ambos canales paralelos (NEITHER lo tiene)
3. **Cost observability del propio LLM stack** (USD por nodo, USD por trade, ratio cost/trade)
4. **LLM en research/orchestration con guardrails** (LangGraph nodes premarket/midday/weekly que **proponen**, NO ejecutan)
5. **Replay caching de llamadas LLM en backtest** (solo Lumibot lo tiene, iguanatrader lo replica)
6. **Cron-jobs proactivos tier-graded** (Tier 1 hardcoded, Tier 2 LLM-filtered, Tier 3 routine)
7. **Multi-tenant ready desde día 1** (`tenant_id` first-class + Hindsight `bank-id` per user)
8. **Risk caps específicos como kill-switch** (Daily 5%, Weekly 15% — Nautilus/Freqtrade lo permiten via custom, iguanatrader lo trae out-of-box)
9. **Override audit-trail** (`/override <reason>` con log inmutable)
10. **Cost dashboard dedicado** (`/costs` page)
11. **Multi-model LLM routing** (Opus para research, Sonnet para routines baratas, Haiku para alerts triviales)
12. **License Apache-2.0 + Commons Clause** desde día 1 (preserva opcionalidad SaaS)

---

## 🕳️ Lo que vamos a echar en falta (huecos honestos vs Nautilus/Freqtrade)

### En MVP, gravemente:

1. **Solo 1 broker (IBKR)** — Nautilus tiene 15, Freqtrade ~25. iguanatrader necesita ampliar en v2/v3.
2. **Solo equity US** — sin cripto, sin futures, sin forex, sin DEX. Nicho intencional pero limita TAM.
3. **0 community, 0 docs, 0 stars** — fricción de adopción real cuando salgamos a OSS.
4. **Bus factor 1 (solo Arturo)** — riesgo crítico documentado en research previa.
5. **Sin Postgres en MVP** — SQLite escala hasta cierto volumen multi-tenant.
6. **Sin Docker en MVP** — deployment manual local. No es SaaS-ready.
7. **Sin trailing stops** — ATR-based static + custom_stoploss en v2.
8. **Sin walk-forward / Monte Carlo** — métodos estadísticos serios faltan en v2/v3.
9. **Sin OCO / bracket orders** — limitación seria para options/futures (que tampoco están en MVP).
10. **Sin hyperopt distribuido** — Optuna single-machine en MVP, Ray en v3.

### Vs Freqtrade específicamente:

- **Sin StoplossGuard built-in** (consecutive losses → pause): cómodo, falta en MVP.
- **Sin CooldownPeriod automático**: solo manual via lock_pair.
- **Sin LowProfitPairs blocker**: feature útil que falta.
- **Sin FreqUI mobile-mature**: nuestro dashboard HTMX será MVP-grade vs FreqUI battle-tested.
- **Sin FreqAI module** (ML pipeline reproducible): no es prioridad pero lo notarán users sofisticados.

### Vs Nautilus específicamente:

- **Sin nanosecond determinism**: microsecond es suficiente para retail equity, pero no es lo mismo.
- **Sin Rust performance**: para multi-strategy concurrente con altas QPS, Python puro será un cuello en v3.
- **Sin DEX support** (Hyperliquid, dYdX, Polymarket): cierra la opción "iguanatrader DeFi mode".
- **Sin Polymarket / event-betting**: nicho creciente que ignoramos.
- **Sin Betfair (sports betting algorítmico)**: nicho random que probablemente no nos importa.

### Honest verdict del trade-off

Nautilus y Freqtrade son **frameworks generalistas** después de años de feature-creep. iguanatrader es **un producto opinionado** para un caso específico (retail equity con LLM-orchestrated approval gate vía móvil).

**Vamos a echar en falta breadth** (asset classes, brokers, indicators, optimization methods).
**Vamos a ganar depth en lo que importa** (approval gate, multi-canal móvil, cost observability del LLM stack, routines proactivas, multi-tenant ready desde día 1).

Esto es **el trade-off correcto** para un MVP single-user con visión SaaS retail-prosumer. Los huecos vs Nautilus/Freqtrade no nos sangran porque son generalistas y nosotros somos específicos.

**Lo único que SÍ debería preocuparnos en serio**:
- **Bus factor 1**: gobernanza explícita desde día 1 si OSS sale.
- **Sin Docker en MVP**: si v2 SaaS llega antes de lo esperado, será refactor doloroso.
- **0 community / 0 docs**: fricción de adopción real si salimos a OSS antes de tener docs serias.

Estos 3 sí son pendientes a planificar en el roadmap, no a ignorar.
