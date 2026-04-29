---
stepsCompleted:
  - step-01-init
  - step-02-discovery
  - step-02b-vision
  - step-02c-executive-summary
  - step-03-success
  - step-04-journeys
  - step-05-domain
  - step-06-innovation
  - step-07-project-type
  - step-08-scoping
  - step-09-functional
  - step-10-nonfunctional
  - step-11-polish
  - step-12-complete
workflowComplete: true
completedAt: 2026-04-27
lastEdited: 2026-04-27
editHistory:
  - date: 2026-04-27
    changes: |
      Polish edit aplicando Top 3 Improvements del validation report (status PASS, holistic 4.5/5):
      (1) 4 cosmetic fixes: FR56 enumerate shells (bash/zsh/fish/powershell); NFR-S6 nginx generic
      ("e.g., nginx"); NFR-S7 SQLCipher generic ("encryption-at-rest mechanism (e.g., SQLCipher
      o pgcrypto)"); NFR-O2 structlog generic ("context-binding mechanism del structured logger
      Python: structlog.contextvars").
      (2) Nueva subsección "### Fraud Prevention" en Domain-Specific Requirements (entre Future
      Regulatory y Domain-specific Risks) consolidando 6 vectores: account takeover, self-harm
      via runaway bot, secret leaks, token compromise, privilege escalation, backtest manipulation.
      (3) Journey 3 nota de scope clarifying que es representativa de la familia tier-3 routines
      (premarket/midday/postmarket/weekly), cubriendo el gap de pre-market briefing journey.
      Bonus: NFR self-count corregido en TOC (46→51 NFRs).
    triggeredBy: bmad-edit-prd workflow tras bmad-validate-prd PASS
    expectedQualityImpact: holistic 4.5/5 → 4.9/5; Domain Compliance Warning → Pass; Implementation
      Leakage Warning → Pass; Traceability gap closed; SMART 4.80 → 4.85; BMAD Principles 6.5/7 → 7/7
inputDocuments:
  - C:/Users/Arturo/.claude/plans/te-doy-ideas-a-lively-snowglobe.md
  - C:/Projects/iguanatrader/AGENTS.md
  - C:/Projects/iguanatrader/docs/research/oss-algo-trading-landscape.md
  - C:/Projects/iguanatrader/docs/research/platforms/lumibot.md
  - C:/Projects/iguanatrader/docs/research/platforms/nautilustrader.md
  - C:/Projects/iguanatrader/docs/research/platforms/lean.md
  - C:/Projects/iguanatrader/docs/research/platforms/freqtrade.md
  - C:/Projects/iguanatrader/docs/research/feature-matrix.md
  - C:/Projects/iguanatrader/docs/backlog.md
workflowType: prd
documentCounts:
  briefs: 0
  research: 1
  brainstorming: 0
  projectDocs: 1
  plans: 1
classification:
  projectType: cli_tool
  domain: fintech
  complexity: high
  projectContext: greenfield
  subClassification:
    userScope: single-user MVP, multi-tenant trajectory non-obstructive
    deployment: local-first
    moneyAtRiskProfile: own capital, progressive scaling
    primaryDriver: personal P&L (real money returns)
    secondaryDriver: technical learning (explicit declared driver)
    ossSaasCommitment: post-MVP optional, NOT MVP driver
    domainNotes: regulatory burden absorbed by broker (IBKR), not by iguanatrader
pendingDeepDives:
  - lumibot
  - nautilustrader
  - lean
  - freqtrade
project_name: iguanatrader
user_name: Arturo
date: 2026-04-27
---

# Product Requirements Document — iguanatrader

**Author:** Arturo
**Date:** 2026-04-27

## Table of Contents

1. [Executive Summary](#executive-summary) — vision + JTBD + 12 differentiators + why now
2. [Project Classification](#project-classification) — type, domain, complexity, drivers
3. [Success Criteria](#success-criteria) — user / business / technical success + measurable outcomes
4. [Product Scope](#product-scope) — MVP / Growth / Vision (resumen)
5. [User Journeys](#user-journeys) — 5 narrative journeys + capability mapping
6. [Domain-Specific Requirements](#domain-specific-requirements) — security, audit, resilience, future regulatory
7. [Innovation & Novel Patterns](#innovation--novel-patterns) — meta-patterns + validation + risk mitigation
8. [CLI-Specific Requirements](#cli-specific-requirements) — command structure, output formats, config schema, scripting
9. [Project Scoping & Phased Development](#project-scoping--phased-development) — MVP strategy, resources, risk consolidación
10. [Functional Requirements](#functional-requirements) — 76 FRs en 9 capability areas (capability contract; FR6-FR10 removed 2026-04-28, FR80-FR81 added Hindsight integration)
11. [Non-Functional Requirements](#non-functional-requirements) — 52 NFRs en 7 quality categories (NFR-P6 + NFR-O6 removed 2026-04-28; NFR-P9 + NFR-O8 + NFR-I8 added; net 52)

**External references** (single-source-of-truth para detalle granular):

- [`docs/backlog.md`](backlog.md) — backlog feature v1.0/v1.5/v2/v3 + Backlog libre + riesgos operacionales + ADRs
- [`docs/research/oss-algo-trading-landscape.md`](research/oss-algo-trading-landscape.md) — landscape research del ecosistema OSS
- [`docs/research/feature-matrix.md`](research/feature-matrix.md) — comparativa Nautilus vs Freqtrade vs iguanatrader
- [`docs/research/platforms/lumibot.md`](research/platforms/lumibot.md), [`nautilustrader.md`](research/platforms/nautilustrader.md), [`lean.md`](research/platforms/lean.md), [`freqtrade.md`](research/platforms/freqtrade.md) — deep-dives técnicos por plataforma
- [`AGENTS.md`](../AGENTS.md) — project dispatcher (identidad, hard rules, capability map, MCP sources)

**Reading order recommended**: Executive Summary → Project Classification → Success Criteria → User Journeys (visceral) → Functional Requirements (capability contract) → resto según interés.

---

## Executive Summary

iguanatrader es un sistema personal de trading algorítmico que sitúa al LLM como copiloto de research y orquestación —jamás como ejecutor autónomo— y deja al humano la decisión final por trade vía Telegram + WhatsApp. Un motor event-driven en Python puro (asyncio single-loop, microsecond resolution suficiente para retail equity sobre bars/eventos discretos) ejecuta vía Interactive Brokers. Un risk engine declarativo en yaml hace cumplir caps configurables (per-trade, daily, weekly, max open positions, drawdown) sobre cada propuesta de la Strategy. La Strategy no puede saltarlos en código; el usuario sí puede deshabilitarlos en config o overridearlos en runtime con motivo escrito y audit log inmutable. Cada llamada al LLM se loggea con su coste en USD, generando la primera observabilidad de stack-LLM del ecosistema OSS de trading auditado.

El MVP es single-user (uso personal de Arturo) con arquitectura **multi-tenant ready desde día 1**, sustentada en mecanismos concretos:

- `tenant_id` first-class en cada tabla del schema SQLite/Postgres
- `bank-id` Hindsight (memoria LLM aislada) per usuario/teléfono hasheado
- `ApprovalChannel` abstracto que permite credenciales (Telegram bot token, WhatsApp number Meta) per tenant
- Modelo "1 proceso/container per tenant" listo para v2 sin refactor del kernel

Esto preserva la opcionalidad de open-source + SaaS comercial post-MVP sin reescritura.

### Job-to-be-done

> *"Cuando estoy en el bar, en una reunión o sin tiempo de mirar charts, quiero que mi sistema me proponga trades disciplinados con razonamiento explícito y me deje aprobar/rechazar en 30 segundos desde el móvil, de modo que mantenga la velocidad y disciplina del bot sin ceder el override humano."*

### What Makes This Special

12 diferenciadores **identificados como ausentes en los 4 frameworks principales auditados** (NautilusTrader 22.3k★, Freqtrade 49.4k★, Lean 18.6k★, Lumibot 1.4k★) según deep-dives 2026-04-27:

| # | Feature | Estado en el ecosistema auditado | Versión iguanatrader |
|---|---|---|---|
| 1 | Approval gate humano per trade vía Telegram + WhatsApp | Inexistente | MVP |
| 2 | WhatsApp Meta API + Telegram canales paralelos | Inexistente | MVP |
| 3 | Cost observability del LLM stack (USD/nodo, USD/trade) | Inexistente | MVP |
| 4 | LLM en research/orchestration con guardrails (LangGraph propone, no ejecuta) | Inexistente | MVP |
| 5 | Bitemporal knowledge repository per-symbol con provenance + show-your-work | Inexistente | MVP (Gate A amendment 2026-04-28) |
| 6 | Cron-jobs proactivos tier-graded (1 hardcoded / 2 LLM-filtered / 3 routine) | Inexistente | MVP (los 3 tiers) |
| 7 | Multi-tenant ready desde día 1 | Inexistente | MVP (schema) → v2 (infra) |
| 8 | Risk caps Daily 5% / Weekly 15% kill-switch out-of-box | Custom only en otros | MVP |
| 9 | Override con audit-trail inmutable (`/override <reason>`) | Inexistente | MVP |
| 10 | Cost dashboard dedicado (`/costs` page) | Inexistente | MVP |
| 11 | Multi-model LLM routing (Opus research / Sonnet routines / Haiku alerts) | Inexistente | MVP |
| 12 | License **Apache-2.0 + Commons Clause** desde día 1 | Más restrictivo en otros (LGPL/GPL) | MVP (decisión inmutable día 1) |

**Core insight**: los LLMs son brillantes razonando, terribles operando. La industria 2025-2026 vende "AI agentic auto-trader" (TradingAgents et al). iguanatrader vende lo contrario — *"responsible LLM-orchestrated retail trading"* donde el gate humano es **feature**, no bug.

**Why now**: convergencia simultánea de:

- (a) LLMs maduros para razonamiento financiero (Opus 4.7 con thinking + tool use)
- (b) `ib_async` ecosystem maduro
- (c) coste LLM operable (estimación basada en pricing Anthropic 2026-04 + cache hits típicos 40-60%: ~$0.05-0.50 USD por trade con Opus 4.7 + cache; **verificar con benchmark real en MVP**)
- (d) categoría comercial abierta sin líder OSS; en SaaS cerrado, **Composer.trade** es el referente actual ($40/mes, no-code visual + LLM codegen) **sin layer LLM-agentic explícito ni approval gate por trade**

## Project Classification

| Eje | Valor |
|---|---|
| Project type | `cli_tool` con web dashboard local (FastAPI + HTMX, mobile-first) |
| Domain | `fintech` — uso personal; broker (IBKR) absorbe la capa regulatoria |
| Complexity | `high` (financial risk + technical complexity, sin compliance burden directo) |
| Project context | `greenfield` (repo bootstrapped 2026-04-26 sobre ai-playbook v0.3.1) |
| User scope | Single-user MVP; arquitectura no-obstaculizante para multi-tenant futuro |
| Deployment | Local-first MVP (TWS Gateway local, dashboard localhost, SQLite + Docker) |
| Money-at-risk profile | Capital propio, escala progresiva (1 share → 200-500€ → más) |

### Drivers

- **Primary driver — P&L personal real**, neto de LLM cost + broker commissions + time-spent.
  - **Umbral MVP exitoso (decisión 2026-04-27)**: **≥ 0 — capital preservation. "No perder dinero ya vale."**
  - **Baseline comparador**: **No definido en MVP** — evaluación absoluta, no relativa. Puede añadirse post-MVP si surge necesidad.
  - **Capital inicial live**: 200-500€ (rampa progresiva: 1 share → 200€ → 500€ → más solo tras evidencia).
  - **Caps adicionales**: max drawdown ≤15%, cost mensual absoluto ≤50€/mes.
  - Detalle cuantitativo y métricas en **Success Criteria > Business Success**.

- **Secondary driver — aprendizaje técnico desafiante**. Métricas trackables propuestas:
  - ≥10 ADRs documentados al cerrar MVP
  - ≥20 entradas en `gotchas.md`
  - ≥4 retros mensuales ejecutados (1/mes durante MVP)
  - ≥3 patrones identificados como "shippable a OSS si saliera"

- **OSS/SaaS commitment — trayectoria post-MVP opcional, NO driver del MVP.**
  - **Trigger de evaluación SaaS propuesto**: post-MVP de 6 meses (≥30 días IBKR live + 5 meses scaling). GO/NO-GO con 5 criterios:
    - (a) P&L positivo neto-de-todo durante ≥4 meses
    - (b) ratio cost-per-trade estable y razonable
    - (c) zero risk-cap breach no-overrideado
    - (d) feedback positivo de ≥3 early users informalmente probados
    - (e) Arturo siente que es producto, no tool
  - Si los 5 cumplen → **GO**. Si <3 → **NO-GO permanente**. Si 3-4 → re-evaluar tras 3 meses adicionales.

## Success Criteria

### User Success

El "user" en MVP es Arturo. El éxito = el flow funciona como prometido.

| Métrica | Target |
|---|---|
| Tiempo de decisión approval por trade | ≤ 30s en 90% de propuestas (móvil-first cumplido) |
| Trades ejecutados sin approval explícito | **0** (constraint duro, kill-switch trigger si pasa) |
| Latencia Tier 1 alerts (crítico) | < 60s desde event hasta notificación |
| Latencia Tier 2 alerts (LLM-filtered context) | ≤ 15 min en mercado abierto |
| Tier 3 routines respetadas (premarket/midday/postmarket/weekly) | 100% schedule respetado |
| Briefing pre-mercado | ≤ 2 min lectura, accionable |
| Weekly review PDF | Usado al menos 1 vez para informar la semana siguiente (proxy de utilidad) |

### Business Success

Sin SaaS en MVP, "business" = P&L personal de Arturo como ideal user. Decisiones del 2026-04-27:

| Métrica | Target confirmado |
|---|---|
| **P&L net-of-everything** (LLM cost + broker commissions descontados) | **≥ 0 — capital preservation. No perder dinero ya vale.** |
| **Baseline comparador** | **No definido en MVP** — evaluación absoluta, no relativa. Puede añadirse post-MVP si surge necesidad |
| **Capital inicial live** | **200-500€** confirmado (rampa progresiva: 1 share → 200€ → 500€ → más solo tras evidencia) |
| **Max drawdown** | ≤ 15% (alineado con weekly cap del risk engine) |
| **Cost mensual absoluto** (LLM + broker commissions) | ≤ 50€/mes (apropiado para capital MVP) |
| **Cost-per-trade ratio** (informacional) | Trackeado y reportado en `/costs` dashboard. Sin target numérico hasta que capital escale (a 200-500€ el ratio es naturalmente alto) |
| Periodo de evaluación MVP | 6-12 meses post-live (≥30 días IBKR live de calidad mínima) |
| **Risk-cap breach overrides count** | ≤ 3 al cerrar MVP (más = el sistema te chirría → señal de mal fit) |

### Technical Success

| Métrica | Target |
|---|---|
| Paper↔live parity | Test concreto: misma estrategia + research_brief en paper y live durante 5 trading days, **delta de fills ≤ 1% del avg fill** (NFR-R reformulado tras Gate A amendment 2026-04-28) |
| Risk caps property-tested | hypothesis NUNCA permite cruzar caps configurados, sea cual sea la señal |
| Cost observability | **100%** llamadas a Anthropic + Perplexity persisten `ApiCostEvent` en SQLite |
| Approval gate reliability | Timeout config respetado, audit trail completo (sin gap entre proposal → approval/rejection/timeout) |
| Multi-tenant schema validation | Test: 2 tenants concurrentes con datos distintos NO cross-contaminate |
| Uncaught exceptions en hot path | **0** durante 30 días IBKR live continuo |
| Test coverage | ≥ 80% en `core/`, `risk/`, `persistence/`, `brokers/` |
| Property tests pasando | 100% (hypothesis sobre risk engine + types) |

### Measurable Outcomes (consolidados)

**Aprendizaje técnico (Secondary driver):**

- ≥ 10 ADRs documentados al cerrar MVP
- ≥ 20 entradas en `gotchas.md`
- ≥ 4 retros mensuales ejecutadas
- ≥ 3 patrones identificados como "shippable a OSS si saliera"

**OSS/SaaS trigger evaluation** (post-MVP, no MVP): post 6 meses, GO/NO-GO con 5 criterios documentados en sección Drivers.

## Product Scope

### MVP — Minimum Viable Product (v1.0)

**Objetivo**: dogfooding personal funcional — Arturo aprueba trades reales en IBKR vía Telegram + WhatsApp con risk engine que no se salta. Per-symbol research repository (bitemporal, multi-source con provenance) que alimenta decisiones. Cost observability del LLM stack. Multi-tenant schema ready (no infra). Apache-2.0 desde día 1. Docker básico. Docs base. Backtest fuera de scope MVP (Gate A amendment 2026-04-28).

Catálogo completo en [`docs/backlog.md` § v1.0](backlog.md). Headlines:

- Engine: MessageBus + DataEngine + ExecutionEngine + RiskEngine + Cache (Nautilus pattern adaptado en Python puro)
- BrokerInterface abstracta + IBKR adapter `ib_async`
- Strategies en MVP: **DonchianATR + SMA Cross**
- Per-symbol strategy config en yaml (activar/desactivar/configurar per symbol)
- Risk engine declarativo (per-trade 2%, daily 5%, weekly 15%, max 5 positions, drawdown)
- Approval channels: **Telegram + WhatsApp via Hermes/Meta API**
- Web dashboard SvelteKit (mobile-first, localhost): `/`, `/approvals`, `/trades`, `/portfolio`, `/costs`, `/risk`, `/research/<symbol>`
- LangGraph orchestration: premarket / midday / postmarket / weekly nodes + cron-jobs Tier 1+2+3
- Cost observability `ApiCostEvent` (LLM cache observability via `cache_hit_tokens`)
- Multi-model LLM routing (Opus 4.7 / Sonnet 4.6 / Haiku 4.5)
- **Research & Intelligence domain**: bitemporal knowledge repo per-symbol; ingestion SEC EDGAR + FRED + Finnhub + GDELT + openFDA + OpenInsider + yfinance via OpenBB sidecar; LLM research_briefs con citations + audit_trail; methodology configurable per-watchlist (3-pillar / CANSLIM / Magic Formula / QARP / Multi-factor)
- Multi-tenant schema (`tenant_id` first-class)
- License Apache-2.0 + Commons Clause; OpenBB sidecar isolated for AGPL boundary
- Docker + docker-compose
- Docs base (`getting-started`, `architecture`, `runbook`, `strategies/donchian_atr`, `data-model`, `personas-jtbd`)
- ≥ 17 comandos Telegram + WhatsApp idénticos

### Growth Features (Post-MVP) — v1.5 + v2

**Objetivo**: cubrir huecos cómodos + preparar arquitectura para multi-broker / SaaS beta.

Detalle en [`docs/backlog.md § v1.5`](backlog.md) y [§ v2](backlog.md). Headlines:

- **v1.5**: estrategias adicionales (RSI / Bollinger / MACD / VolumeBreakout) + IBKR Execution Algos (Adaptive/TWAP/VWAP/Snap) + StoplossGuard + CooldownPeriod + Trailing stops + Postgres opcional + Walk-forward + HTML reports + Hot-reload de strategy code
- **v2**: BrokerInterface adapters (Alpaca / Schwab / Tradier) + OCO + bracket orders + IBKR Iceberg/PassRelative/POV + Pairs trading / Z-score / Multi-timeframe + LowProfitPairs blocker + Email + Discord + Order management UI + Futures (CME via IBKR) + multi-tenant infra Docker Compose

### Vision (Future) — v3 + Backlog libre

**Objetivo**: producto comercial OSS+SaaS si triggers post-MVP los activan.

Detalle en [`docs/backlog.md § v3`](backlog.md) y [§ Backlog libre](backlog.md). Headlines:

- **v3**: 3-tier pricing (Solo/Team/Pro) + onboarding/billing Stripe + Cripto via CCXT + DEX (Hyperliquid/dYdX/Polymarket) + Forex + DarkIce/Accumulate-Distribute + Sector rotation / Earnings drift / Risk parity + LLM strategy codegen + marketplace + cohort course + Foundation governance
- **Backlog libre**: Bonds / Mutual funds / ML/RL strategies (FinRL) / Monte Carlo / Mobile app nativa / TradingView Pine importer / Apple Watch / Voice approval (Whisper) / OpenTelemetry tracing distribuido / Migración a Nautilus engine si v3 escala

## User Journeys

El **único primary user en MVP es Arturo** en distintas modalidades operativas. La Journey 5 mapea el caso multi-tenant de v3 SaaS para validar el design intent.

### Journey 1 — Happy path: aprobación de trade durante una reunión

**Persona**: Arturo, en reunión de cliente, jueves 14:35h Madrid (8:35 ET, 5 min después del open de Wall Street).

**Opening scene**: el móvil vibra discreto. WhatsApp muestra:

> 🤖 *iguanatrader propone:*
> **BUY SPY** — DonchianATR breakout (high 30d cruzado al alza)
> Tamaño: 1 share @ ~$612.40 = $612 (1.8% del capital)
> Stop: $597.20 (ATR x 2.5). Risk al stop: -$15.20 (-2.5%)
> Confidence node: 72% · Cost node: $0.08
>
> 🟢 Aprobar · 🔴 Rechazar · ✏️ Modificar · ⏱️ 50s para descartar

**Rising action**: Arturo finge consultar el calendario. Lee la propuesta en 8 segundos. Confidence 72% es razonable, el risk cabe en el daily cap (queda 78% del 5% disponible), el stop está a un soporte técnico claro. Pulsa 🟢 Aprobar.

**Climax**: 2.3 segundos después, WhatsApp confirma:

> ✅ **FILLED** SPY @ $612.42 (1 share, slippage +$0.02)
> Daily P&L: -$0.00 · Daily cap: 4.1% / 5%
> Posiciones abiertas: 3

**Resolution**: la reunión sigue. Por la tarde, dashboard muestra P&L vivo, equity curve actualizada. A las 22:30h llega el postmarket summary: "SPY +0.8%, P&L hoy +$3.45 net of $0.12 LLM cost".

**Capabilities reveladas**: approval channel WhatsApp con razonamiento explícito; botones inline (callback queries); timeout configurable con countdown visible; cálculo en tiempo real de risk impact; confirmación de fill con slippage; postmarket summary automático con P&L net-of-cost.

---

### Journey 2 — Edge case: warning de cap + override consciente

**Persona**: Arturo, lunes 15:20h Madrid (9:20 ET). Earnings de NVDA hoy after-close.

**Opening scene**: Telegram, mensaje proactivo Tier 2:

> ⚠️ **Heads-up: Daily loss usado 4.0% / 5%**
> Quedan 8 horas de mercado. 1 stop más de magnitud típica te llevaría al cap.
> Tu última proposal NVDA (queue) tiene risk 1.4% si stop hit → daily total proyectado: 5.4% (over cap).
>
> El RiskEngine va a **REJECT** la propuesta NVDA cuando se procese (en 12 min, pre-NVDA earnings briefing).

**Rising action**: 12 min después llega la propuesta NVDA, marcada `🚫 RISK REJECTED`. Botón: `[Override]`. Arturo pulsa Override. Bot pide:

> 🔐 **Confirma override del RiskEngine**
> Cap: daily 5%. Tu daily projected: 5.4%.
> Esto NO es una operación rutinaria. Escribe el motivo (mín 20 chars) — quedará en audit log inmutable.

Arturo escribe: `"earnings NVDA, convicción manual, stop -8% no -ATRx2.5"`. Bot pide segunda confirmación con preview del trade modificado.

**Climax**: confirmación. Trade ejecuta. WhatsApp muestra:

> ✅ FILLED NVDA @ $X (override registrado: `risk_override_id=42`)

**Resolution**: NVDA reporta. Sube 11%. Arturo cierra +6.4% vía `/forceexit`. El trade aparece en weekly review marcado con 🟡 "manual override — earnings play". El sistema no le pide explicaciones — solo registra y reporta.

**Capabilities reveladas**: Tier 2 proactive alerts sobre cap consumption; RiskEngine rejection con razón explícita; mecanismo `/override` con doble confirmación + motivo escrito ≥ N chars; tabla `risk_overrides` append-only; marcado visual de override en histórico; modificación de stop por usuario en mismo flow.

---

### Journey 3 — Routine: weekly review domingo mañana

> **Nota de scope**: Journey 3 es **representativa de la familia tier-3 routines** (premarket 8:30 ET / midday 1 PM / postmarket 4:30 PM / weekly Vie 6 PM). Las cuatro siguen el mismo pattern UX — notification proactiva con razonamiento estructurado, lectura ≤2 min, accionable. Weekly review es la instancia más rica (PDF multi-página) y por eso se narra aquí; las otras tres comparten cron schedule + LLM-generated insights + canal multi-mensajería. Cobertura formal: FR43, FR44, NFR-P4, success criterion "Briefing pre-mercado ≤2 min lectura".

**Persona**: Arturo, domingo 10:00h Madrid, café en mano, sin reuniones.

**Opening scene**: WhatsApp del viernes anterior 18:00h ET, sin abrir hasta ahora:

> 📊 **Weekly Review semana 17 / 2026**
> P&L semanal: **+47.20€ (+0.94%)** net-of-cost
> Trades: 8 (5 winners, 3 losers, 0 BE)
> Avg holding: 1.4 días
> Max drawdown intra-semana: 1.2%
> Coste LLM total: 4.10€ (Opus 0.8€ research, Sonnet 2.4€ routines, Haiku 0.9€ alerts)
> Ratio cost/gross-P&L: 8% (mejorando vs 12% sem-16)
> Risk overrides: 0
>
> 📎 PDF detallado adjunto (8 páginas)

**Rising action**: PDF en 8 páginas: equity curve + drawdown / tabla de trades con razonamiento + decisión + resultado / análisis por strategy (DonchianATR vs SMA Cross) / cost breakdown por nodo LangGraph / lecciones detectadas por el LLM listadas para `memoria.md` / propuesta de tweaks (ej: *"RSI period 14 mostró edge en SPY en últimas 8 semanas paper, considerar pruebas con 21 en próximo período paper"*) / outlook próxima semana (eventos macro, earnings).

**Climax**: Arturo identifica una lección genuina: *"los breakouts confirmados con volumen >2x avg ganaron 4/4 esta semana, los sin filtro volumen 1/4. Considerar `VolumeBreakoutDonchian` (v1.5)"*. Lo apunta en el plan de la próxima sprint.

**Resolution**: PDF cerrado en 7 minutos. El sistema guardó la memoria de la semana por él.

**Capabilities reveladas**: cron-job Tier 3 weekly review viernes 18:00 ET; generación PDF multi-página con plotly + jinja; LLM-generated insights por trade; cost breakdown per LangGraph node; auto-detected "lessons" candidatas para `memoria.md`; outlook macro/earnings de la próxima semana.

---

### Journey 4 — Failure recovery: TWS Gateway cae mid-session

**Persona**: Arturo, miércoles 16:40h Madrid (10:40 ET), trabajando en otro proyecto. 2 posiciones abiertas (SPY long, AAPL long).

**Opening scene**: WhatsApp Tier 1 alert (crítico, 0 LLM filtering, hardcoded):

> 🔴 **ALERT — Pérdida de conexión IBKR**
> Última heartbeat: hace 95s
> Posiciones expuestas: 2 (SPY 1sh, AAPL 1sh)
> Reintentando reconexión... (3/10)

**Rising action**: Arturo abre el dashboard `/risk`. El kill-switch está armado pero no activado. Mientras tanto, el bot reintenta:

> 🟡 Reintento 5/10 falló (TWS Gateway no responde en localhost:7497). Reintentando...

A los 90 segundos:

> ✅ **Reconectado a IBKR**
> Iniciando reconciliación de estado...
> Orders pending broker-side: 0 ✓
> Positions broker-side vs cache: SPY 1sh ✓ | AAPL 1sh ✓
> No hay discrepancias. Resumiendo operación normal.

**Climax**: el sistema le dijo qué pasó, qué intentó, y qué confirmó después. Sin spam, sin silencio.

**Alternative climax (failure cascade)**: si reconciliación detecta discrepancia (cache: AAPL 1sh, broker: AAPL 0):

> 🚨 **DISCREPANCIA CRÍTICA DETECTADA**
> Cache: AAPL 1 share. Broker: AAPL 0 shares.
> Hipótesis: orden cerrada por broker (margin call? stop hit during disconnect?)
> Kill-switch ACTIVADO automáticamente. Trading pausado.
> Acción requerida: revisar `/portfolio` y confirmar estado real.
> Para resumir: `/resume` tras verificar.

**Resolution**: Arturo verifica vía TWS, ve que AAPL hit el stop durante el outage (-1.8%). Aprende. Marca para `gotchas.md`: *"TWS Gateway disconnect window puede ejecutar stops del lado broker sin notificar al bot — siempre stop server-side, no client-side"*.

**Capabilities reveladas**: heartbeat monitoring + Tier 1 alert hardcoded; reintento automático con backoff exponencial; reconciliación de estado broker↔cache post-reconnect; kill-switch automático bajo discrepancia detectada; mensajes diferenciados (warning amarillo vs critical rojo); `/resume` con verificación previa requerida.

---

### Journey 5 — Future (v3 SaaS): Sara descubre iguanatrader en Hacker News

**Persona**: Sara, 32 años, ingeniera de datos en Barcelona. Cuenta IBKR Pro hace 2 años. Probó QuantConnect (pesado), Composer.trade (caja negra). Lee Hacker News diariamente.

**Opening scene**: HN front page: *"Show HN: iguanatrader — LLM proposes, you approve from your phone, IBKR executes (open-source, Apache+CC)"*. Click. Landing en español/inglés. Hero: GIF de 8 segundos del approval flow en WhatsApp.

**Rising action**: README. Principio claro: *"LLM never executes autonomously"*. Screenshots del cost dashboard. GitHub: 800 stars, último commit hace 2 días, 8 contributors. Apache 2.0 + Commons Clause. Le convence más que Freqtrade (cripto-only) o Lumibot (GPL).

Sign up gratis (free tier: research dashboard unlimited + paper trading limitado a 1 strategy + 1 symbol). Conecta IBKR paper vía OAuth. Wizard la guía a primera Strategy: DonchianATR sobre SPY. Research_brief de SPY se genera en 30s con citations a SEC filings + FRED macro + news recientes. Ve thesis, fundamentals, catalysts próximos, coste estimado de LLM en live.

**Climax**: a la semana siguiente, paga el tier Solo (€29/mes). Activa live en cuenta paper. Primera proposal pre-mercado en WhatsApp. Aprueba. Engancha.

**Resolution**: 3 meses después, mueve a IBKR live con €5K. P&L modesto pero positivo. Escribe un post técnico: *"Why I left QC for iguanatrader"*. Tráfico orgánico crece. Comunidad emerge.

**Capabilities reveladas (NO en MVP, plan v3)**: landing público con demo; sign-up flow + email verification; IBKR OAuth integration; wizard de primera Strategy; free tier (research dashboard + 1 strategy paper); pricing tier Solo €29/mes; multi-tenant infra (1 contenedor por user); onboarding paper → live.

---

### Journey Requirements Summary

Capacidades reveladas por las journeys, agrupadas por capability area:

| Capability area | Journeys que la requieren | Versión |
|---|---|---|
| **Approval channel WhatsApp + Telegram** con razonamiento + buttons + timeout countdown | J1, J2 | MVP |
| **Risk engine con caps + override flow + audit trail** | J2 | MVP |
| **Cost observability + breakdown per LangGraph node** | J3, J5 | MVP |
| **Cron-jobs Tier 1 (hardcoded crítico)** | J4 | MVP |
| **Cron-jobs Tier 2 (LLM-filtered context)** | J2 | MVP |
| **Cron-jobs Tier 3 (routines: premarket / midday / postmarket / weekly)** | J3 | MVP |
| **Heartbeat monitoring + reconciliación broker↔cache + kill-switch automático** | J4 | MVP |
| **Web dashboard `/portfolio` `/risk` `/costs` `/runs`** | J3, J4 | MVP |
| **Weekly Review PDF** con equity + trades + cost + lessons + outlook | J3 | MVP |
| **`/override` flow** con doble confirm + motivo + audit | J2 | MVP |
| **`/forceexit` desde Telegram/WhatsApp** | J2 | MVP |
| **Landing page público + sign-up + OAuth IBKR + wizard onboarding** | J5 | v3 |
| **Multi-tenant infra (container per tenant)** | J5 | v2 (infra) → v3 (SaaS) |
| **Pricing tier Solo / Team / Pro** + Stripe | J5 | v3 |

## Domain-Specific Requirements

iguanatrader es `fintech` con `high` complexity, pero la complejidad **no viene de carga regulatoria** sino de financial risk + technical. En MVP single-user con capital propio + broker (IBKR) absorbiendo la capa regulatoria: GDPR no aplica (no procesas datos de terceros), KYC/AML no aplica (no custodia fondos ajenos), MiFID II / SEC RIA no aplica (un único usuario = tú), PCI-DSS no aplica (no pagos / tarjetas).

Las preocupaciones domain-specific reales son **operacionales (security + audit + resilience)** y **anticipatorias (futuro regulatorio v3 SaaS)**.

### Security operacional (MVP — aplica)

| Concern | Mecanismo |
|---|---|
| Credenciales broker (IBKR API keys + TWS Gateway access) | SOPS (age) + `.env.local` gitignored. `pre-commit` con gitleaks. Nunca hardcoded. |
| API keys LLM (Anthropic, Perplexity) | Idem SOPS. `iguana_secrets.yaml.enc`. |
| Telegram bot token + WhatsApp Meta credentials | Idem. Tokens rotables sin redeploy. |
| Auth runtime (quién manda comandos al bot) | `authorized_phones` (WhatsApp) + `authorized_telegram_ids` whitelist. Mensajes de no-autorizados: log + ignore. |
| Acceso al dashboard local | localhost-only en MVP, sin auth. Si se expone a red local → basic auth + reverse proxy nginx. |
| Encriptación at-rest de DB | SQLite sin encryption en MVP (single-user, FDE de OS suficiente). En v2 multi-tenant: SQLCipher per-tenant o Postgres con `pgcrypto`. |

### Audit & inmutabilidad (MVP — aplica, es diferenciador)

| Tipo de evento | Garantía |
|---|---|
| Trades / orders / fills | Append-only en SQLite. NO `UPDATE`, NO `DELETE`. Estado computable como vista. |
| Risk overrides (`/override <reason>`) | Tabla `risk_overrides` append-only con `tenant_id`, `proposal_id`, `reason_text`, `confirmation_chain`, `timestamp`, `risk_state_snapshot`. |
| LLM API calls | Tabla `api_cost_events` append-only. Hash del prompt opcional (decisión: privacidad vs auditoría). |
| Approval decisions (granted / rejected / timeout) | Tabla `approval_events` append-only con channel (Telegram/WhatsApp), latencia, decisión, user_id. |
| Config changes via `/reload_config` | Tabla `config_history` con diff de yaml + timestamp + trigger source. |

### Resilience patterns (MVP — aplica, justificado en Journey 4)

- **Heartbeat IBKR** cada 30s, alert Tier 1 si gap > 90s
- **Reintento exponencial** con backoff (3, 6, 12, 24, 48s × 5 intentos)
- **Reconciliación post-reconnect** broker↔cache (orders + positions); si discrepancia → kill-switch automático
- **Crash recovery**: estado computable desde SQLite append-only — el restart NO pierde estado, solo recompone desde events
- **Kill-switch redundante**: file (`.killswitch`) + env (`IGUANA_HALT`) + Telegram/WhatsApp (`/halt`) + dashboard button — cualquiera triggers halt

### Future regulatory considerations (v3 SaaS — NO en MVP, listed para evitar build-traps)

| Régimen | Aplica si | Mitigación de diseño |
|---|---|---|
| EU MiFID II | SaaS con users EU + propones trades específicos | Mantener arquitectura "user-owned-account orchestration": el user tiene su cuenta IBKR; iguanatrader solo orquesta software del user. Defensible como "trading software" no "investment service" |
| US SEC / FINRA "Investment Advisor" | SaaS con users US + recomiendas trades | Idem. Triple-aprobación por trade refuerza la defensa. Considerar entrar en EU primero |
| GDPR | Cualquier user EU en SaaS | DPA con providers (Anthropic, Meta, Twilio si aplica). Right-to-erasure: tabla `tenant_id` permite borrado quirúrgico. Logging mínimo de PII |
| CCPA | Users California en SaaS | Similar a GDPR, scope reducido |
| AML / KYC | NO aplica si no custodias fondos | Mantener "user has IBKR account, we don't touch funds" — IBKR hace KYC, no nosotros |
| Tax reporting (1099-B en US, modelo 720 en ES) | El broker emite | iguanatrader debe **poder exportar trades** en formato compatible para que el usuario contraste con su 1099 / declaración fiscal — endpoints `/export_trades_csv` + `/export_trades_pdf` |

### Fraud Prevention

Para iguanatrader (single-user MVP, capital propio, sin custodia de fondos ajenos), "fraud prevention" tradicional fintech (PCI-DSS, payment fraud, AML transaction monitoring) **no aplica**. Las superficies de fraude reales y sus mitigaciones:

| Vector de fraude | Mitigación | FR/NFR refs |
|---|---|---|
| **Account takeover** (atacante manda comandos al bot fingiendo ser Arturo) | Whitelist explícita `authorized_phones` (WhatsApp) + `authorized_telegram_ids` (Telegram). Mensajes de senders no-whitelisted: log + ignore sin respuesta (evita info leak por enumeration). | FR31, FR38, NFR-S3, NFR-S4 |
| **Self-harm via runaway bot** (LLM hallucination genera trades destructivos) | Triple gate obligatorio: (a) RiskEngine filtra/recorta antes; (b) reasoning estructurado parseable obligatorio; (c) human approval explícito por trade. Sin approval → no execution. | FR45, FR24-FR30, FR11 |
| **Code-level secret leaks** (commit accidental de keys/tokens) | Pre-commit gitleaks + CI block. Secrets siempre SOPS-encrypted o env vars, nunca yaml plain. `.env.local` gitignored, `.env.example` checked-in con keys vacías. | NFR-S1, NFR-S2 |
| **Token compromise post-leak** (atacante obtiene token broker/LLM/Telegram) | Tokens rotables sin redeploy ni reinicio de daemon (hot-reload via SIGHUP). Runbook documenta procedimiento de rotación de emergencia. | NFR-S8 |
| **Privilege escalation interna** (multi-tenant v2/v3) | NA en MVP (single-user). En v2 multi-tenant: aislamiento `tenant_id` per query + per-process containers; un tenant nunca lee datos de otro. RBAC formal en v3 SaaS si hay roles. | NFR-SC1, NFR-SC4 |
| **Research data manipulation** (fact corruption en knowledge repo via fuente comprometida) | Cada fact persiste con `source_id` + `source_url` + `retrieved_at` + `retrieval_method`; bitemporal schema permite detectar revisiones contradictorias del mismo fact entre vintages; LLM research_briefs deben citar facts y no inventar valores; show-your-work audit_trail bloquea cálculos sin trazabilidad. | FR68-FR70, FR71 |

**Resumen**: la prevención de fraude en iguanatrader es **arquitectónica, no transaccional**. El bot no puede defraudar al usuario porque el bot no decide ejecutar nada solo. El usuario puede ser engañado solo si pierde control de su canal de aprobación, y eso se mitiga con whitelist + secret rotation. NO se requiere fraud detection ML, transaction scoring, ni AML compliance porque el flujo financiero entero ocurre dentro de la cuenta propia del usuario en su broker (IBKR), que ya tiene su propia capa AML/KYC.

### Domain-specific risks & mitigations

| Riesgo | Mitigación |
|---|---|
| Lookahead bias en research feature consumption (Strategy lee snapshot actual al evaluar bar histórica) | Tier system A/B/C en feature provider registry; CI assertion que strategy code no consume tier-B features sin `retrieved_at <= bar.date` constraint. Live trading no afectado (current data IS correct). |
| Race condition risk-check vs submit | `with order_lock:` envuelve risk check + submit en sección crítica. |
| Overfitting en parameter tuning | Defaults textbook MVP (Donchian 20+5, ATR ×2.0); paper trading 30-90 días valida; walk-forward optimization deferrida a v1.5+ si paper revela edge. |
| Telegram/WhatsApp spoofing | `authorized_phones` whitelist. Cualquier mensaje de número no whitelisted: log + ignore. |
| TWS Gateway disconnect ejecuta stops broker-side sin notificar | Lección de Journey 4. Stops siempre **server-side al broker** (no client-side). Documentar en `gotchas.md`. |
| LLM hallucination en proposal | Triple gate: (a) RiskEngine filtra/recorta antes del approval; (b) humano aprueba; (c) propuesta debe incluir reasoning estructurado parseable (no free-form). |
| Cost runaway de LLM | Daily/weekly budget cap en LLM cost. Si excedido: routines downgrade a Sonnet/Haiku automáticamente, alertas Tier 2 se silencian. |

## Innovation & Novel Patterns

### Detected Innovation Areas

3 patrones meta-innovativos (más allá de los 12 features individuales del Executive Summary):

#### 1. Categoría inversa: "Responsible LLM-orchestrated retail trading"

La industria 2025-2026 vende **AI-agentic auto-trader**:

- TradingAgents (Tauric Research) — multi-LLM agents que deciden trades autónomos en demo académico
- LLM-trading-agents (proliferación Medium) — tutoriales de "deja que GPT haga trades por ti"
- Composer.trade "Trade With AI" — LLM genera estrategia, ejecuta sin gate explícito por trade

iguanatrader vende **lo opuesto**: el LLM razona y propone, el humano es el gate obligatorio, el motor determinista ejecuta. Ningún OSS hoy ocupa esta posición. La inversión del paradigma es la innovation, no la suma de features.

#### 2. Cost observability del propio LLM stack como first-class citizen

Hasta hoy, los proyectos OSS de trading no miden lo que cuesta su propia capa de IA. iguanatrader lo eleva a tabla append-only desde día 1 (`api_cost_events`), página dashboard dedicada (`/costs`), métrica derivada `cost-per-trade ratio`, multi-model routing automático con budget caps. Esto es novel — no porque sea técnicamente difícil, sino porque **nadie lo ha hecho explícito en este vertical**.

#### 3. Mobile-first multi-canal (Telegram + WhatsApp) con razonamiento embedded en la propuesta

Los bots OSS existen (Freqtrade Telegram). Las propuestas con razonamiento existen (GPT prompts custom). **La combinación "mensaje móvil + razonamiento estructurado del LLM + 30s para approval/reject + audit trail" es el flow no construido**. El reuse de Hermes para WhatsApp Meta API multiplica la accesibilidad sin construir desde cero.

### Market Context & Competitive Landscape

| Categoría | Líderes 2026 | Posición de iguanatrader |
|---|---|---|
| OSS multi-asset framework | Lean (18.6k★), NautilusTrader (22.3k★) | NO competimos — ellos generalistas, nosotros opinionados |
| OSS cripto-bot retail | Freqtrade (49.4k★), Hummingbot (9k★), OctoBot (3.5k★) | NO competimos — cripto-only vs equity US |
| OSS Python equity-friendly | Lumibot (1.4k★ — GPL bloquea SaaS) | Competimos parcialmente; Lumibot tiene engine + LLM hooks pero NO approval gate humano |
| SaaS cerrado retail-quant | Composer.trade ($40/mes, no-code visual + LLM codegen) | iguanatrader compite en valor: open-core + IBKR (vs Alpaca-only) + approval gate por trade (vs sin gate) + cost observability |
| Académico LLM-trading | TradingAgents (alta tracción) | NO competimos — ellos demos, nosotros producto |
| **Categoría "responsible LLM-orchestrated retail"** | **VACÍA** | iguanatrader es el primer OSS con presence en esta categoría |

### Validation Approach

Cómo validamos que la innovación aporta valor real, **no es innovation theater**:

| Innovation claim | Cómo se valida (concreto y medible) |
|---|---|
| "Approval gate humano per trade es feature, no bug" | Métrica MVP: tiempo medio decisión approval ≤ 30s. Si Arturo encuentra el flow molesto y empieza a auto-aprobar todo o a hacer override masivo, el patrón **falla** |
| "Cost observability del LLM stack tiene valor" | Ratio cost-per-trade visible y trackeado en `/costs`. Si en 6 meses Arturo nunca consulta el dashboard y el ratio sube sin que nadie note, **falla** |
| "Mobile-first multi-canal acelera decisiones" | % de approvals decididas en <30s. Si <70%, el flow móvil no funciona como prometido |
| "LLM en research/orchestration con guardrails añade alpha" | Ablation test: comparar P&L de propuestas con razonamiento LLM vs propuestas hardcoded del Strategy directo. Si el LLM-augmented no aporta edge medible, **se desactiva post-MVP** |
| "Multi-tenant ready desde día 1 ahorra refactor v2" | Time-to-deploy primer tenant adicional en v2 (target: <1 semana). Si requiere refactor mayor, el "ready" era retórica |

### Risk Mitigation

Innovation risks específicos + mitigaciones:

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| LLM hallucination en proposal de trade | Media | Alto | Triple gate: (a) RiskEngine filtra ANTES; (b) reasoning estructurado parseable obligatorio; (c) humano final |
| Cost runaway de LLM (loop, prompt ineficiente) | Baja | Medio | Budget caps daily/weekly; auto-downgrade Opus→Sonnet→Haiku al exceder; alertas Tier 2 silenciadas si over-budget |
| Approval fatigue (Arturo deja de leer propuestas) | Media | Alto | Contar overrides + measure tiempo de decisión; si >30s sostenido → mal fit, considerar desactivar canal |
| Multi-canal complexity sin uso real | Baja | Bajo | Métrica distribución approvals Telegram vs WhatsApp. Si <10% por canal, considerar deprecar |
| Bus factor 1 mata el OSS si saliera | Alta (estructural) | Crítico para v3 | Documented governance plan en v2 antes de OSS launch; o Foundation-style si traction lo justifica |
| "Categoría inversa" es nicho que no escala | Media | Alto | Trigger SaaS de Step 2c es exactamente el go/no-go check post-MVP |
| Composer / SaaS cerrado pivota y mata la diferenciación | Media | Alto | Mantener velocidad de iteración + open-core como moat. Composer no puede abrirse sin destrozar su valuation |
| Research repo provenance gaps (fact ingested without complete metadata) | Baja | Alto | DB CHECK + NOT NULL constraints + CI integration test bloquean inserts incompletos; cualquier `source_id IS NULL` o `retrieved_at IS NULL` falla en transacción |

### Fallback si la innovation no funciona

Si tras 6 meses de MVP los gates de validación **fallan**:

- Si el approval gate molesta → reducir frecuencia de propuestas (LLM filter más estricto), no eliminar el gate
- Si el LLM no aporta alpha → mantener iguanatrader como bot determinista puro, dejar LangGraph en mode "informativo, no propositivo"
- Si multi-canal es overhead → consolidar en Telegram solo, deprecar WhatsApp Hermes path
- Si cost observability nadie la usa → mantenerla (es low-cost) pero quitarla de feature list de v3 SaaS positioning
- Si la categoría no resona → pivot a "tu propio Composer en open-source" (mismo engine, distinto positioning)

iguanatrader sigue siendo útil como bot personal de Arturo incluso si toda la hipótesis de innovation falla. El downside máximo es "bot funcional menos diferenciado", no "proyecto muerto".

## CLI-Specific Requirements

### Project-Type Overview

iguanatrader expone su funcionalidad principal a través de un CLI `iguana` (typer-based) que cubre 3 modos operativos: **scripting one-shot** (ingest, propose, research, export), **daemon long-running** (paper, live, dashboard), y **comandos de operación** (halt, resume, override). El CLI es la **capa de control humano local**; los canales móviles (Telegram + WhatsApp) son la capa de control remoto.

### Technical Architecture Considerations

Scriptable, no interactive REPL. Cada comando es un proceso atómico con exit code estable. No hay shell custom dentro del bot. Modos long-running (`live`, `paper`, `dashboard`) corren como procesos daemon con signal handling correcto (SIGTERM = halt limpio, SIGINT = idem, SIGHUP = reload config).

**Stack**: `typer` + `rich` (UX humana) + `structlog` (JSON logs) + `pydantic-settings` (config validation).

### Command Structure

Jerarquía `iguana <verb> [noun] [flags]`:

| Comando | Modo | Función |
|---|---|---|
| `iguana init` | one-shot | Inicializa proyecto local (configs, secrets template, DB schema) |
| `iguana ingest bars <symbol> [--from <date>] [--to <date>]` | one-shot | Descarga bars históricos, persiste a parquet cache (FR66) |
| `iguana research refresh <symbol>` | one-shot | Force-refresh research_brief vigente para symbol; ingesta facts pendientes (EDGAR/FRED/news) + LLM synthesis |
| `iguana research show <symbol> [--version <n>]` | one-shot | Imprime brief vigente o versión específica con citations + audit_trail |
| `iguana paper` | daemon | Paper trading IBKR (`PAPER=true` en config) |
| `iguana live` | daemon | Live trading IBKR (requiere `--confirm-live` flag) |
| `iguana dashboard [--port 8000]` | daemon | Sirve FastAPI + HTMX en localhost |
| `iguana propose <strategy> <symbol>` | one-shot | Fuerza una propuesta manual (research mode) |
| `iguana halt [--reason <text>]` | one-shot | Activa kill-switch (escribe `.killswitch`, notifica via Telegram) |
| `iguana resume` | one-shot | Quita kill-switch (con verificación previa) |
| `iguana override <proposal_id> --reason <text>` | one-shot | Override de RiskEngine reject (audit log) |
| `iguana reload-config` | one-shot | Hot-reload de yaml configs |
| `iguana export trades [--from <date>] [--format csv\|pdf]` | one-shot | Exporta histórico de trades |
| `iguana strategies list` | one-shot | Cataloga strategies disponibles |
| `iguana strategies enable <symbol>` / `disable <symbol>` | one-shot | Toggle per-symbol |
| `iguana strategies set-param <symbol> <param> <value>` | one-shot | Hot-tune param |
| `iguana retain <kind> --content <text>` | one-shot | Persist a Hindsight bank `iguanatrader` (heredado del playbook) |
| `iguana version` | one-shot | Versión + commit hash + python version |

Subcommand grouping via typer apps anidadas: `iguana strategies` agrupa list/enable/disable/set-param; `iguana export` agrupa trades/portfolio/risk-overrides; etc.

### Output Formats

**Default: human-readable** con `rich`:

- Tablas con colors para `iguana strategies list`, `iguana export trades`, `iguana version`
- Progress bars para `iguana ingest bars`, `iguana research refresh`
- Boxes con summary para `iguana research show`

**`--json` flag** en todo comando one-shot que produzca data: salida machine-parseable a stdout. Diseñado para chaining con `jq` o consumo desde scripts:

```bash
iguana export trades --from 2026-01-01 --json | jq '.[] | select(.pnl > 0) | .symbol' | sort | uniq -c
```

**Logs estructurados** via `structlog` → JSON a stdout (modo daemon) o fichero rotativo. Niveles: DEBUG/INFO/WARNING/ERROR con `event` + contextual fields (tenant_id, strategy, symbol, proposal_id, etc.).

**Reportes binarios**:

- PDF para weekly review (WeasyPrint o ReportLab) — FR44
- HTML para `iguana research show <symbol> --html` (Plotly fundamentals chart + brief render)
- CSV para `iguana export trades --format csv`

**Exit codes** con semántica estable:

- `0` — éxito
- `1` — error genérico
- `2` — config inválida
- `3` — broker no disponible / TWS Gateway down
- `4` — kill-switch activo (rechaza comandos de trading)
- `5` — risk cap breach (override needed)

### Config Schema

**Stack**: `pydantic-settings` carga + valida en arranque.

**Layering** (precedencia descendente):

1. CLI flags (`--port 8001` override puntual)
2. ENV vars (`IGUANA_RISK_DAILY_PCT=0.04` para sesión específica)
3. Secrets cifrados (`config/secrets.yaml.enc` SOPS-encrypted; decifra en runtime con age key)
4. Yaml configs versionados:
   - `config/iguana.yaml` — config maestra (broker, mode, paths)
   - `config/risk.yaml` — protections + caps
   - `config/strategies.yaml` — per-symbol strategy + params
   - `config/llm_prices.yaml` — pricing table versionada
   - `config/slippage.yaml` — modelos de slippage por broker
5. Defaults hardcoded en pydantic models

**Validación**: pydantic falla rápido en arranque con mensajes específicos. Test obligatorio: `iguana init` con config inválido devuelve exit code 2 + mensaje claro indicando qué key falla.

**Hot-reload** vía `iguana reload-config` (también disponible en `/reload_config` Telegram). Diff + audit log a `config_history` table.

**Secrets**:

- Nunca en yaml plain. Siempre SOPS-encrypted o ENV var.
- `gitleaks` pre-commit + CI block.
- `.env.local` gitignored para development; `.env.example` checked-in con keys vacías.
- Rotación de tokens documentada en runbook (no requiere redeploy).

### Scripting Support

**Stdin/stdout**: comandos one-shot escriben **solo data útil** a stdout cuando `--json` (sin progress bars ni colors), permitiendo pipe limpios. Errores siempre a stderr.

**Daemon mode** (`paper`, `live`, `dashboard`):

- Escribe PID a `~/.iguana/iguana.pid`
- Listen para SIGTERM (halt graceful — cierra trades pending, persist state, cierra conexiones), SIGINT (idem), SIGHUP (reload config)
- Stdout JSON logs por default; `--log-file` para redirección
- Compatible con `systemd` y `docker compose` orquestación

**Idempotency**: comandos como `iguana halt` son idempotentes (kill-switch ya activo → noop con exit 0 + warning). `iguana ingest` ya cacheado → noop con `--force` para re-fetch.

**Composability**:

```bash
# Pipeline típico de research
iguana ingest bars SPY --from 2024-01-01 \
  && iguana research refresh SPY \
  && iguana research show SPY --json \
  | jq '.brief.thesis' \
  | tee /tmp/spy_thesis.txt
```

**Shell completion**: typer auto-genera completions vía `iguana --install-completion <bash|zsh|fish|powershell>`. Cada comando documentado con `--help` producible.

### Implementation Considerations

- CLI testeada con `typer.testing.CliRunner`: cada comando con tests unitarios cubriendo happy path + error paths + exit codes
- Logging structurado desde primer commit (no print statements). `structlog.contextvars.bind_contextvars()` para propagar `tenant_id`, `proposal_id` automáticamente
- Type-safe end-to-end: pydantic models validan I/O de cada comando
- Versioning semántico: `iguana version` muestra version + commit + python + dependencies clave
- `--help` rico auto-generado por typer; mantener documentación inline (no docs duplicadas en md externas)

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP Approach: Problem-solving MVP** (no platform, no revenue, no experience).

Decisión consciente: el primary driver es resolver **el problema de Arturo** (trading disciplinado con poco tiempo). NO buscamos:

- "Experience MVP" — nadie más usa el producto en MVP, no hay delight para optimizar más allá del propio user
- "Platform MVP" — multi-tenant es **schema-ready** (ADR-008), no funcionalidad activa hasta v2
- "Revenue MVP" — sin pricing en MVP, sin sign-ups, sin Stripe; OSS+SaaS es trayectoria post-MVP gated por trigger del Executive Summary

Esto significa que **decisiones marginales se resuelven hacia "lo simple que funciona para Arturo hoy"**, no "lo que escalaría a 1000 users". Ejemplo: dashboard sin auth en localhost (no construir login multi-user para que Arturo se loggee a su propia máquina).

Validación del approach: post-MVP, el trigger de evaluación SaaS es exactamente el go/no-go check. Si los 5 criterios cumplen, **entonces** se reescribe el approach a "platform MVP" en v2.

### Resource Requirements

| Dimensión | Valor |
|---|---|
| Equipo | **1 dev (Arturo) + Claude Code como copilot** |
| Capital de riesgo (cuenta IBKR live) | 200-500€ rampa progresiva |
| Capital operacional (LLM + infra) | ≤ 50€/mes target |
| Time budget MVP | 3-4 meses calendar (estimación, dependiente de hours/week que Arturo dedique) |
| Bus factor | **1 (Arturo)** ⚠️ — riesgo estructural documentado en backlog § "Riesgos operacionales" |
| Skills críticas | Python async, IBKR API, LangGraph, FastAPI, pydantic, asyncio, SQLAlchemy. Todo cubierto por Arturo + Claude. Nada exótico tipo Rust o C#. |

### MVP Feature Set (Phase 1) — pointer a docs ya completos

> **Catálogo completo en [`docs/backlog.md` § v1.0](backlog.md)** (no duplico aquí — el backlog es la SSOT de scope per-versión).

Headlines del scope MVP:

- Engine: MessageBus + DataEngine + ExecutionEngine + RiskEngine + Cache (Nautilus pattern adaptado en Python puro)
- BrokerInterface abstracta + IBKR adapter (`ib_async`)
- Strategies en MVP: DonchianATR + SMA Cross
- Per-symbol strategy config (yaml-driven, hot-reloadable)
- Risk engine declarativo (per-trade 2%, daily 5%, weekly 15%, max 5 positions, drawdown)
- Approval channels: Telegram + WhatsApp via Hermes
- Web dashboard SvelteKit (mobile-first, localhost): ~8 páginas (incl. `/research/<symbol>`)
- LangGraph orchestration: 4 routine nodes + cron-jobs Tier 1/2/3
- Research & Intelligence domain (FR57-FR79): bitemporal knowledge repo + multi-source ingestion + LLM research_briefs con citations
- Cost observability (`ApiCostEvent` con cache_hit_tokens)
- Multi-model LLM routing (Opus / Sonnet / Haiku)
- Multi-tenant schema (`tenant_id` first-class)
- License Apache-2.0 + Commons Clause
- Docker + docker-compose
- Docs base (`getting-started`, `architecture`, `runbook`, `strategies/donchian_atr`)
- CLI con ~16 comandos + completions
- Telegram/WhatsApp con ~20 comandos idénticos

**User journeys soportadas en MVP**: J1 (happy path), J2 (override edge case), J3 (weekly review routine), J4 (failure recovery). J5 (Sara SaaS onboarding) es **explícitamente fuera de MVP** — diseñada en Step 4 solo para validar design intent multi-tenant futuro.

### Post-MVP Features

> Detalle granular en [`docs/backlog.md`](backlog.md) — secciones v1.5, v2, v3 y Backlog libre.

**Phase 2 — Growth (v1.5 + v2)**: estrategias adicionales (RSI/Bollinger/MACD/VolumeBreakout/Pairs/MultiTF), IBKR Execution Algos (Adaptive/TWAP/VWAP/Snap/Iceberg/POV), risk extensions (StoplossGuard/CooldownPeriod/Trailing), brokers adicionales (Alpaca/Schwab/Tradier), order types avanzados (OCO/bracket), futures CME, Postgres opcional, walk-forward, Docker Compose multi-tenant infra.

**Phase 3 — Expansion (v3)**: SaaS launch con tier 3-niveles (Solo/Team/Pro), onboarding/billing Stripe, cripto via CCXT, DEX (Hyperliquid/dYdX/Polymarket), forex, IBKR DarkIce/Accumulate-Distribute, estrategias macro (sector rotation/earnings drift/risk parity), LLM strategy codegen, marketplace, education flywheel, Foundation governance.

**Backlog libre** (sin compromiso): bonds, mutual funds, ML/RL strategies, Monte Carlo, mobile app nativa, TradingView Pine importer, Apple Watch, voice approval, OpenTelemetry distribuido, migración engine a Nautilus si v3 escala.

### Risk Mitigation Strategy (consolidación)

Riesgos ya documentados en Domain Requirements y Innovation Risk. Consolidados por categoría con scope-impact:

| Categoría | Riesgo | Mitigación | Impacto en scope MVP |
|---|---|---|---|
| Technical | LLM hallucination en proposal | Triple gate (RiskEngine + reasoning estructurado + humano) | NO recorta — feature core |
| Technical | Cost runaway de LLM | Budget caps + auto-downgrade modelo + alertas Tier 2 silenciables | NO recorta |
| Technical | TWS Gateway disconnect ejecuta stops broker-side | Stops siempre server-side; reconciliación post-reconnect | NO recorta |
| Technical | Lookahead en research feature consumption (tier B sin retrieved_at constraint) | Tier system A/B/C en feature provider registry; CI assertion bloquea uso incorrecto en strategy code | NO recorta |
| Technical | Race conditions risk-check vs submit | `with order_lock:` envuelve sección crítica | NO recorta |
| Market | "Categoría inversa" no resona (nicho que no escala) | Trigger SaaS post-MVP es el go/no-go check | NO recorta MVP — decide v3 |
| Market | Composer/SaaS cerrado pivota y mata diferenciación | Velocidad de iteración + open-core como moat | NO recorta MVP |
| Market | Approval fatigue (Arturo deja de leer propuestas) | Métrica tiempo de decisión; si >30s sostenido → desactivar canal | NO recorta — validation gate |
| Resource | Bus factor 1 mata el proyecto si Arturo se va | Documented governance en v2 antes de OSS launch | NO recorta MVP — plan v2 |
| Resource | Time budget 3-4 meses se desliza a 6-8 | **Recortar Multi-model LLM routing y Web dashboard a versión mínima si time pressure** | RECORTE CONDICIONAL |
| Resource | Capital LLM excede 50€/mes | Pasar routines a Sonnet/Haiku permanente; deprecar Tier 2 alerts si no aportan | NO recorta MVP estructuralmente |

**Recortes contingentes si time-pressure** (en orden de severidad):

1. Web dashboard reduce a 3 páginas (`/`, `/approvals`, `/risk`) — quita `/trades`, `/portfolio`, `/costs`, `/runs` (nice-to-have). Datos siguen en SQLite, accesibles via CLI.
2. WhatsApp se posterga a v1.5 (Telegram-only en MVP).
3. Multi-model LLM routing se simplifica a Sonnet-only.
4. Postmarket summary y midday check (Tier 3) se postpone a v1.5 (mantiene solo premarket + weekly).

**NO se recortan jamás**: RiskEngine + caps, BrokerInterface abstracta, multi-tenant schema, license, Telegram approval, audit trail. **Eso es la columna vertebral arquitectónica**.

## Functional Requirements

> **Capability contract**: a partir de aquí, toda feature debe trazar a un FR. Lo que no esté listado, no existirá en el producto final salvo que se añada explícitamente.

### Strategy Management

- **FR1**: User can list available trading strategies and their applicable versions
- **FR2**: User can enable or disable a strategy for a specific symbol without affecting open positions
- **FR3**: User can configure per-symbol strategy parameters via yaml or runtime command
- **FR4**: User can hot-reload strategy configuration without restarting the system
- **FR5**: User can override individual strategy parameters at runtime via approval channel command

### [REMOVED 2026-04-28] Backtest & Research

> **Status**: REMOVED 2026-04-28. Backtest scope skipped from MVP per scope decision (Camino C, Gate A amendment 2026-04-28). Paper trading remains the recommended validation gate per AGENTS.md §7 Override 1, but it is no longer mandatory — user retains final authority on going live without paper history.
>
> Historical bar ingest (formerly FR9) is reframed and migrated to **Research & Intelligence Domain** (FR66) — bars remain useful for charting + LLM research context + indicator computation, just not for backtest replay.
>
> FR6, FR7, FR8, FR10 are eliminated outright. The `backtest` bounded context is removed from architecture (was: `apps/api/src/iguanatrader/contexts/backtest/`). Strategy validation now relies on paper trading discipline (recommended) + manual chart review + research-driven discretion. If backtest demonstrably becomes valuable in v1.5+ based on paper-trading evidence, it can be reintroduced as a separate proposal.

### Trade Lifecycle

- **FR11**: System proposes trades with structured reasoning (signal source, sizing rationale, stop placement, confidence score)
- **FR12**: User can approve or reject each trade proposal within a configurable timeout window
- **FR13**: System auto-discards proposals that exceed approval timeout and logs the discard reason
- **FR14**: System submits approved orders to broker via abstract BrokerInterface
- **FR15**: System tracks order state lifecycle (new, partially filled, filled, canceled, rejected) and notifies user on transitions
- **FR16**: System reconciles broker state with internal cache after disconnection events
- **FR17**: User can force-exit an open position via approval channel command
- **FR18**: User can force-create a position outside automated proposals (with risk validation applied)

### Risk Management

- **FR19**: System enforces per-trade risk cap (% of capital) configured in yaml
- **FR20**: System enforces daily loss cap with automatic kill-switch on breach
- **FR21**: System enforces weekly loss cap with automatic kill-switch on breach
- **FR22**: System enforces maximum open positions limit
- **FR23**: System enforces maximum drawdown protection
- **FR24**: System rejects strategy-generated proposals that violate risk caps before they reach the approval channel
- **FR25**: User can override risk-rejected proposals via approval channel with mandatory written reason (≥20 chars) and double confirmation
- **FR26**: System persists every override with timestamp, reason text, risk state snapshot, and confirmation chain
- **FR27**: User can disable all risk protections via single master config switch
- **FR28**: User can disable individual protections selectively via config
- **FR29**: User can activate kill-switch via file flag, environment variable, approval channel command, or dashboard button
- **FR30**: System refuses all trade execution while kill-switch is active

### Notifications & HITL Channels

- **FR31**: User can authorize specific Telegram user IDs and WhatsApp phone numbers as authorized command sources
- **FR32**: System routes trade proposals to all authorized channels in parallel
- **FR33**: System delivers Tier 1 critical alerts within 60s of triggering event via hardcoded heuristics
- **FR34**: System delivers Tier 2 LLM-filtered context alerts at configurable polling intervals during market hours
- **FR35**: System delivers Tier 3 scheduled routine outputs at configured cron times (premarket / midday / postmarket / weekly)
- **FR36**: User can configure notification verbosity per channel and per tier
- **FR37**: User can issue all approval and operational commands identically via Telegram or WhatsApp
- **FR38**: System rejects and logs commands from non-authorized senders without execution

### LLM Orchestration & Cost Observability

- **FR39**: System routes LLM calls to different models per task type (research / routine / alerting)
- **FR40**: System logs every LLM call with provider, model, node, tokens, cache status, USD cost, and request metadata
- **FR41**: System enforces daily and weekly LLM budget caps with auto-downgrade to cheaper models on breach
- **FR42**: System computes cost-per-trade ratio and reports it in dashboard
- **FR43**: System runs scheduled orchestration routines (premarket briefing, midday check, postmarket summary, weekly review)
- **FR44**: System produces weekly review as PDF artifact with equity curve, trade analysis, lessons, and outlook
- **FR45**: System never executes trades autonomously from LLM output (LLM proposes; execution requires human approval gate)

### Data, Persistence & Audit

- **FR46**: System persists trades, orders, fills, positions, and equity snapshots in append-only storage
- **FR47**: System persists every config change with diff and trigger source
- **FR48**: System persists every approval decision (granted / rejected / timeout) with channel and latency
- **FR49**: System tags every persisted record with `tenant_id` to support multi-tenancy
- **FR50**: User can export trades and risk overrides as CSV or PDF per date range
- **FR51**: System maintains a separate Hindsight memory bank per tenant identifier

### Operational Surface

- **FR52**: User can invoke all functionality via CLI commands with stable, documented exit codes
- **FR53**: User can run system in daemon mode with graceful signal handling (SIGTERM/SIGINT halt clean, SIGHUP reload config)
- **FR54**: User can view real-time portfolio state, equity curve, pending approvals, costs, and risk status via web dashboard
- **FR55**: User can trigger kill-switch from web dashboard with single click
- **FR56**: User can install shell completion for **bash, zsh, fish, and powershell** via CLI flag (`iguana --install-completion <shell>`)

### Research & Intelligence Domain

> Added 2026-04-28 via Gate A amendment. Captures the per-symbol knowledge repository that integrates fundamentals, macro, news, sentiment, catalysts, analyst ratings, insider activity, ESG, technicals, sector context, and PESTEL signals into LLM-synthesized research briefs that inform trade decisions. See `docs/research/data-sources-catalogue.md` for the source catalogue + 7 closed open questions. License/legal posture: Apache-2.0+Commons Clause preserved via OpenBB sidecar isolation; all scraped data subject to non-redistribution policy.

#### Configuration & methodology

- **FR57**: User can configure watchlist symbols with two tiers: primary (≤50 streaming + research-active) and secondary (SP500 + Russell 2000 — alerts only, no streaming)
- **FR58**: User can select per-watchlist research methodology profile from `{3-pillar, CANSLIM, Magic Formula, QARP, Multi-factor}` — all 5 frameworks shipped MVP

#### Ingestion

- **FR59**: System ingests SEC filings (10-K, 10-Q, 8-K, Form 4 insider, 13F-HR institutional) via SEC EDGAR official APIs with point-in-time filing-date semantics (vía `edgartools` Python lib)
- **FR60**: System ingests macro indicators via FRED + ALFRED + BLS + BEA APIs with vintage-aware (point-in-time) data — ALFRED preserves original publication vintages, not revisions
- **FR61**: System ingests news + sentiment via GDELT DOC 2.0 + Finnhub free tier with ticker-tagged sentiment scoring
- **FR62**: System ingests calendars + catalysts (earnings dates, FDA approvals, FOMC meetings, ex-dividend, splits, M&A) via Finnhub earnings calendar + openFDA + ALFRED FOMC schedule + SEC 8-K filings stream
- **FR63**: System ingests insider transactions via SEC Form 4 (authoritative, via `edgartools`) AND OpenInsider scraping for aggregated screens (top buyers/sellers across universe) — both included MVP
- **FR64**: System ingests analyst ratings via yfinance recommendations + Finnhub consensus + Finviz scraping (Tier 2 ladder)
- **FR65**: System ingests ESG aggregate scores via `yfinance.sustainability` (Sustainalytics-via-Yahoo) — best-effort, single-source caveat documented in fact provenance
- **FR66**: User can ingest historical bars per symbol/timeframe to local parquet cache for research context (charting, indicator computation, LLM briefing) — IBKR primary, Yahoo Finance fallback
- **FR67**: System ingests geopolitics/PESTEL signals via GDELT events (BigQuery, partitioned by date+ticker to stay under 100 GB/mo free tier ceiling) + WGI World Bank governance + V-Dem academic dataset

#### Storage & provenance

- **FR68**: System persists research facts in bitemporal schema (`effective_from / effective_to` × `recorded_from / recorded_to`) supporting "what did we know about symbol X at time T" queries with both event-time and knowledge-time semantics — see ADR-014 (to be created)
- **FR69**: System refuses to persist `research_fact` without complete provenance metadata: `source_id`, `source_url`, `retrieval_method` ∈ `{api, scrape, manual, llm}`, `retrieved_at` (UTC ISO 8601). Enforcement: DB CHECK + NOT NULL constraints + CI integration test. Inserts violating contract raise `MissingProvenanceError`
- **FR70**: System persists `audit_trail` JSON for every numeric calculation in research_briefs: `formula` (text), `inputs` (each citing `source_id` + `retrieved_at` + raw value), `intermediate_steps` (ordered list), `final_output` — show-your-work principle, queryable via `/api/v1/research/briefs/{id}/audit-trail`

#### Synthesis

- **FR71**: System produces LLM-synthesized `research_brief` per symbol consolidating fundamentals + macro + news + analyst + insider + ESG + technicals + sector + PESTEL with citations to underlying `research_facts` + audit_trail for any computed metric (P/E, growth rates, ratios)
- **FR72**: System refreshes `research_briefs` on schedule (configurable per symbol: daily/weekly/manual) AND on-trigger when material new fact arrives (earnings release, 8-K filing, breaking news with high relevance score)
- **FR73**: `research_briefs` are immutable per version — refresh creates new version row with monotonically increasing `version` field; old versions retained indefinitely for backtest replay (when reintroduced) + trade audit

#### Integration with trading

- **FR74**: `TradeProposal` references the `research_brief` vigente at proposal time (`research_brief_id` FK) so trade audit replays "exactly which brief informed this decision"; brief is read-once and its content snapshot stored in proposal `reasoning` JSON for full self-containment
- **FR75**: System enforces tier-based feature availability for research queries: **Tier A** (native point-in-time: EDGAR XBRL, ALFRED) — full historical access; **Tier B** (snapshot collected with `retrieved_at` constraint) — available since collection-start date; **Tier C** (one-shot bootstrap) — only at the bootstrapped timestamp. Strategy code MUST handle `None` returns gracefully when tier-B/C feature has no history at query time

#### Platform & policy

- **FR76**: System integrates OpenBB Platform via **sidecar process** (Docker container, FastAPI on `localhost:8765`) preserving AGPL-3.0 ↔ Apache-2.0+CC license boundary — iguanatrader-proper never links OpenBB code in-process; communication exclusively via HTTP loopback
- **FR77**: System uses 4-tier web scraping ladder for non-API sources: Tier 1 WebFetch (httpx + BS4) → Tier 2 Playwright (Chromium) → Tier 3 Camoufox MCP (Firefox stealth) → Tier 4 Camoufox + captcha solver (paid service); per-source tier configured in `apps/api/src/iguanatrader/contexts/research/sources/<source>.py` adapter
- **FR78**: System never redistributes scraped raw data outside iguanatrader's research boundary; only emits derived metrics with explicit source attribution. Internal cache (parquet/SQLite) is gitignored by default and excluded from any data export
- **FR79**: System emits identifying User-Agent (`iguanatrader/<version> (+arturo6ramirez@gmail.com)`) on every scraping request, respects `robots.txt` programmatically (lib `urllib.robotparser`), and rate-limits HTML scrapes to 1 req / 3s minimum

#### Hindsight integration (complementary narrative memory layer)

- **FR80** (write-on, MVP day 1): System retains narrative summaries to Hindsight bank `iguanatrader-research-<tenant_id>` at three trigger points: (a) `kind=brief_summary` after every research_brief synthesis with thesis + key insights + brief_id metadata; (b) `kind=trade_retrospective` after every trade close linking proposal_id + research_brief_id + outcome (P&L, time-to-fill, slippage) + LLM-extracted lesson; (c) `kind=pattern_observation` weekly cross-symbol patterns detected by LLM. Always-on, no user toggle. Storage purpose: build narrative history that becomes valuable for recall after ≥12 months operation.
- **FR81** (read-togglable, MVP default OFF): User can enable or disable Hindsight recall in research_brief synthesis via dashboard settings page. Per-tenant toggle (`tenants.feature_flags.hindsight_recall_enabled`). Default OFF; recommended ON after ≥12 months of operation. When OFF, brief synthesis skips Hindsight recall step (graceful baseline using only research_facts SQL). Toggle change persisted in `audit_log` + `config_changes` with timestamp + actor + diff. Help text inline explaining 12-month rationale. CLI alternative: `iguana settings feature-flag hindsight_recall <enable|disable>`.

### FR Traceability

| Capability area | Source de discovery | FRs |
|---|---|---|
| Strategy Management | ADR-008 (per-symbol config) | FR1-FR5 |
| ~~Backtest & Research~~ | REMOVED 2026-04-28 (Gate A amendment) | ~~FR6-FR10~~ |
| Trade Lifecycle | Journeys 1 & 4 + execution lifecycle pattern | FR11-FR18 |
| Risk Management | Journey 2 + Protections pattern + ADR-006 revisado | FR19-FR30 |
| Notifications & HITL | Journeys 1-4 + Telegram + Hermes WhatsApp | FR31-FR38 |
| LLM Orchestration & Cost | Vision pillars + Innovation areas | FR39-FR45 |
| Data, Persistence & Audit | Domain Audit section + multi-tenant schema | FR46-FR51 |
| Operational Surface | CLI-Specific Requirements | FR52-FR56 |
| **Research & Intelligence Domain** | **Gate A amendment 2026-04-28 + `docs/research/data-sources-catalogue.md`** | **FR57-FR81** |

## Non-Functional Requirements

> Categorías selectivas. Skipped explícitamente: **Accessibility** (single-user MVP, no broad audience) y **Compliance regulatory** (cubierto en Domain Requirements § Future regulatory considerations).

### Performance

- **NFR-P1**: 90% de trade proposals entregadas a Telegram/WhatsApp dentro de 5s desde generación
- **NFR-P2**: Approval timeout countdown garantiza ≥50s útiles para el usuario (timeout default 60s, latencia de delivery <10s)
- **NFR-P3**: 99% de Tier 1 alerts entregadas dentro de 60s desde el event trigger
- **NFR-P4**: Tier 2 polling intervals respetados ±1min (default 15min en mercado abierto)
- **NFR-P5**: 95% de órdenes aprobadas confirmadas por broker dentro de 3s post-approval (excluye latencia broker)
- **NFR-P6**: ~~Backtest de 1 año diario sobre 1 símbolo completa en <60s~~ — REMOVED 2026-04-28 (Gate A amendment, backtest out of MVP scope)
- **NFR-P7**: Dashboard page load <500ms en localhost
- **NFR-P8**: Heartbeat IBKR cada 30s; alert disparada si gap > 90s
- **NFR-P9**: Research_brief refresh para 1 symbol completa en <30s (full re-synthesis con cache hit ratio ≥40%)

### Security

- **NFR-S1**: Todos los secrets (broker keys, LLM keys, Telegram bot token, WhatsApp Meta credentials) cifrados at-rest con SOPS+age
- **NFR-S2**: Pre-commit `gitleaks` debe pasar en cada commit; CI bloquea merges con leaks detectados
- **NFR-S3**: Whitelist explícita de senders autorizados (Telegram IDs + WhatsApp phone numbers); valores en config encriptado
- **NFR-S4**: Mensajes de senders no-whitelisted: log + ignore, sin respuesta (evita info leak por enumeration)
- **NFR-S5**: Override commands requieren motivo escrito ≥20 caracteres + double confirmation antes de aplicar
- **NFR-S6**: Dashboard servido en `localhost` only por default; exposición a red local requiere basic auth + reverse proxy (e.g., nginx)
- **NFR-S7**: SQLite at-rest sin encryption en MVP (single-user, FDE de OS suficiente). Encryption-at-rest mechanism per-tenant (e.g., SQLCipher o Postgres `pgcrypto`) desde v2 multi-tenant
- **NFR-S8**: API tokens rotables sin redeploy ni reinicio de daemon (hot-reload via SIGHUP)

### Reliability

- **NFR-R1**: 30 días IBKR live continuo con **0 uncaught exceptions** en hot path (medible vía structured logs grep)
- **NFR-R2**: Reconciliation broker↔cache 100% successful tras cualquier reconnect (test E2E: simular outage, verificar matching de orders + positions)
- **NFR-R3**: Crash recovery: tras `kill -9` + restart, estado SQLite append-only permite reconstruir state sin pérdida de events
- **NFR-R4**: 100% de proposals que exceden timeout son discarded sin ejecución (test obligatorio)
- **NFR-R5**: Kill-switch latency: desde activación (file/env/cmd/dashboard) hasta sistema rechaza nuevos trades: <2s
- **NFR-R6**: Property tests sobre RiskEngine pasan al 100% — hypothesis NUNCA permite cruzar caps configurados, sea cual sea la señal (CI-blocking)
- **NFR-R7**: Reconnect IBKR con backoff exponencial: 3, 6, 12, 24, 48s × 5 intentos; tras eso → kill-switch automático

### Observability

- **NFR-O1**: **100%** de LLM calls (Anthropic + Perplexity) persisten `ApiCostEvent` en SQLite con todos los campos requeridos
- **NFR-O2**: Structured JSON logs con `tenant_id`, `proposal_id`, `strategy`, `symbol` propagados automáticamente via context-binding mechanism del structured logger (Python: `structlog.contextvars`)
- **NFR-O3**: Log rotation: máx 100MB per file, 7 días retention default (configurable)
- **NFR-O4**: Cost dashboard `/costs` actualizado cada 5min en sesión activa
- **NFR-O5**: Audit trail de risk overrides + approval decisions queryable via CLI (`iguana export risk-overrides --format csv`)
- **NFR-O6**: ~~Backtest HTML report <10s post-run~~ — REMOVED 2026-04-28 (Gate A amendment)
- **NFR-O7**: Cada propuesta incluye `prompt_hash` opcional en `ApiCostEvent.metadata` para auditoría reproducible (privacy trade-off documentado)
- **NFR-O8**: Research_brief render HTML/JSON debe incluir 100% de citations resueltas a `research_facts.source_url`; broken citations fallan el render (soft-fail con warning, hard-fail en CI)

### Maintainability

- **NFR-M1**: Test coverage ≥ 80% en `core/`, `risk/`, `persistence/`, `brokers/` (CI-blocking)
- **NFR-M2**: Property tests (hypothesis) sobre risk engine + types pasando 100% (CI-blocking)
- **NFR-M3**: Type-checking `mypy --strict` en `src/iguanatrader/core/*` (CI-blocking)
- **NFR-M4**: Lint `ruff` + format `black` sin warnings (CI-blocking)
- **NFR-M5**: Docs base completos antes de v1.0 release: `getting-started.md`, `architecture.md`, `runbook.md`, `strategies/donchian_atr.md`
- **NFR-M6**: ≥10 ADRs documentados al cerrar MVP (target Secondary driver)
- **NFR-M7**: ≥20 entradas en `gotchas.md` al cerrar MVP (target Secondary driver)
- **NFR-M8**: Governance plan documentado en `docs/governance.md` antes de OSS launch (mitigación bus factor 1)
- **NFR-M9**: Pin dependencies con `poetry.lock` o equivalente; updates manuales via dependabot (no auto-merge)

### Scalability (light, future-oriented)

- **NFR-SC1**: Schema multi-tenant ready desde día 1: `tenant_id` en cada tabla del SQLite/Postgres, todas las queries filtradas
- **NFR-SC2**: Migración SQLite → Postgres con mismo schema sin pérdida de data (test E2E en v1.5)
- **NFR-SC3**: Patrón "1 contenedor por tenant" documentado en runbook v2 (no implementado MVP)
- **NFR-SC4**: Hindsight bank per `tenant_id` aislado: queries cross-tenant retornan 0 resultados (test multi-tenant scenario)
- **NFR-SC5**: Schema permite añadir nuevos brokers sin DDL changes (uso de `broker_id` enum + JSON metadata por broker)

### Integration

- **NFR-I1**: `BrokerInterface` abstracta documentada con contract tests; nuevo adapter implementable en <40h dev (validado vs IBKR adapter como benchmark)
- **NFR-I2**: IBKR adapter resilient a TWS Gateway disconnects con backoff exponencial 5 retries antes de kill-switch
- **NFR-I3**: Anthropic SDK uso con **prompt caching habilitado**; target cache hits 40-60% en routines repetitivas (medido en MVP, ajustado en v1.5)
- **NFR-I4**: Perplexity API rate-limited a `config.perplexity.max_rpm` con queue + backoff exponencial
- **NFR-I5**: Telegram bot reconecta automáticamente en pérdida de conexión sin perder mensajes pending (long-polling resilience)
- **NFR-I6**: WhatsApp via Hermes/Meta API: templates pre-aprobados antes de v1.0 launch; rotación de tokens sin downtime
- **NFR-I7**: MCP server compatibility: Anthropic + Perplexity expuestos via MCP cuando aplique (Hindsight bank `iguanatrader` ya provisioned)
- **NFR-I8**: Hindsight recall (when enabled per FR81) latency p50 < 500ms, p95 < 2s. Failure or timeout → brief synthesis proceeds with `hindsight_recalled=false` flag in research_brief metadata; structlog WARNING `research.hindsight.recall_failed`; no block of brief synthesis (graceful degradation invariant)
