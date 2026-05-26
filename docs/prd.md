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
      Polish edit applying the Top 3 Improvements from the validation report (status PASS, holistic 4.5/5):
      (1) 4 cosmetic fixes: FR56 enumerates shells (bash/zsh/fish/powershell); NFR-S6 nginx generic
      ("e.g., nginx"); NFR-S7 SQLCipher generic ("encryption-at-rest mechanism (e.g., SQLCipher
      or pgcrypto)"); NFR-O2 structlog generic ("context-binding mechanism of the Python structured
      logger: structlog.contextvars").
      (2) New "### Fraud Prevention" subsection in Domain-Specific Requirements (between Future
      Regulatory and Domain-specific Risks) consolidating 6 vectors: account takeover, self-harm
      via runaway bot, secret leaks, token compromise, privilege escalation, backtest manipulation.
      (3) Journey 3 scope note clarifying that it is representative of the tier-3 routines family
      (premarket/midday/postmarket/weekly), covering the pre-market briefing journey gap.
      Bonus: NFR self-count corrected in TOC (46→51 NFRs).
    triggeredBy: bmad-edit-prd workflow after bmad-validate-prd PASS
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
4. [Product Scope](#product-scope) — MVP / Growth / Vision (summary)
5. [User Journeys](#user-journeys) — 5 narrative journeys + capability mapping
6. [Domain-Specific Requirements](#domain-specific-requirements) — security, audit, resilience, future regulatory
7. [Innovation & Novel Patterns](#innovation--novel-patterns) — meta-patterns + validation + risk mitigation
8. [CLI-Specific Requirements](#cli-specific-requirements) — command structure, output formats, config schema, scripting
9. [Project Scoping & Phased Development](#project-scoping--phased-development) — MVP strategy, resources, risk consolidation
10. [Functional Requirements](#functional-requirements) — 76 FRs across 9 capability areas (capability contract; FR6-FR10 removed 2026-04-28, FR80-FR81 added Hindsight integration)
11. [Non-Functional Requirements](#non-functional-requirements) — 52 NFRs across 7 quality categories (NFR-P6 + NFR-O6 removed 2026-04-28; NFR-P9 + NFR-O8 + NFR-I8 added; net 52)

**External references** (single-source-of-truth for granular detail):

- [`docs/backlog.md`](backlog.md) — feature backlog v1.0/v1.5/v2/v3 + free backlog + operational risks + ADRs
- [`docs/research/oss-algo-trading-landscape.md`](research/oss-algo-trading-landscape.md) — landscape research of the OSS ecosystem
- [`docs/research/feature-matrix.md`](research/feature-matrix.md) — comparison Nautilus vs Freqtrade vs iguanatrader
- [`docs/research/platforms/lumibot.md`](research/platforms/lumibot.md), [`nautilustrader.md`](research/platforms/nautilustrader.md), [`lean.md`](research/platforms/lean.md), [`freqtrade.md`](research/platforms/freqtrade.md) — technical deep-dives per platform
- [`AGENTS.md`](../AGENTS.md) — project dispatcher (identity, hard rules, capability map, MCP sources)

**Recommended reading order**: Executive Summary → Project Classification → Success Criteria → User Journeys (visceral) → Functional Requirements (capability contract) → the rest based on interest.

---

## Executive Summary

iguanatrader is a personal algorithmic trading system that positions the LLM as a research and orchestration copilot — never as an autonomous executor — and leaves the final per-trade decision to the human via Telegram + WhatsApp. An event-driven engine in pure Python (asyncio single-loop, microsecond resolution sufficient for retail equity over discrete bars/events) executes via Interactive Brokers. A declarative risk engine in yaml enforces configurable caps (per-trade, daily, weekly, max open positions, drawdown) on every Strategy proposal. The Strategy cannot bypass them in code; the user can disable them in config or override them at runtime with a written reason and an immutable audit log. Every LLM call is logged with its USD cost, generating the first LLM-stack observability of the audited OSS trading ecosystem.

The MVP is single-user (personal use by Arturo) with **multi-tenant ready architecture from day 1**, backed by concrete mechanisms:

- `tenant_id` first-class in every table of the SQLite/Postgres schema
- `bank-id` Hindsight (isolated LLM memory) per user/hashed phone
- Abstract `ApprovalChannel` allowing credentials (Telegram bot token, WhatsApp Meta number) per tenant
- "1 process/container per tenant" model ready for v2 without kernel refactor

This preserves the optionality of open-source + commercial SaaS post-MVP without rewrite.

### Job-to-be-done

> *"When I am at the bar, in a meeting, or without time to look at charts, I want my system to propose disciplined trades with explicit reasoning and let me approve/reject in 30 seconds from my phone, so that I keep the speed and discipline of the bot without giving up human override."*

### What Makes This Special

12 differentiators **identified as absent in the 4 main audited frameworks** (NautilusTrader 22.3k★, Freqtrade 49.4k★, Lean 18.6k★, Lumibot 1.4k★) according to deep-dives 2026-04-27:

| # | Feature | Status in audited ecosystem | iguanatrader version |
|---|---|---|---|
| 1 | Human approval gate per trade via Telegram + WhatsApp | Non-existent | MVP |
| 2 | WhatsApp Meta API + Telegram parallel channels | Non-existent | MVP |
| 3 | LLM stack cost observability (USD/node, USD/trade) | Non-existent | MVP |
| 4 | LLM in research/orchestration with guardrails (LangGraph proposes, does not execute) | Non-existent | MVP |
| 5 | Bitemporal knowledge repository per-symbol with provenance + show-your-work | Non-existent | MVP (Gate A amendment 2026-04-28) |
| 6 | Proactive tier-graded cron-jobs (1 hardcoded / 2 LLM-filtered / 3 routine) | Non-existent | MVP (all 3 tiers) |
| 7 | Multi-tenant ready from day 1 | Non-existent | MVP (schema) → v2 (infra) |
| 8 | Risk caps Daily 5% / Weekly 15% kill-switch out-of-box | Custom only in others | MVP |
| 9 | Override with immutable audit-trail (`/override <reason>`) | Non-existent | MVP |
| 10 | Dedicated cost dashboard (`/costs` page) | Non-existent | MVP |
| 11 | Multi-model LLM routing (Opus research / Sonnet routines / Haiku alerts) | Non-existent | MVP |
| 12 | License **Apache-2.0 + Commons Clause** from day 1 | More restrictive in others (LGPL/GPL) | MVP (immutable day-1 decision) |

**Core insight**: LLMs are brilliant at reasoning, terrible at operating. The 2025-2026 industry sells "AI agentic auto-trader" (TradingAgents et al). iguanatrader sells the opposite — *"responsible LLM-orchestrated retail trading"* where the human gate is a **feature**, not a bug.

**Why now**: simultaneous convergence of:

- (a) LLMs mature for financial reasoning (Opus 4.7 with thinking + tool use)
- (b) mature `ib_async` ecosystem
- (c) operable LLM cost (estimate based on Anthropic pricing 2026-04 + typical cache hits 40-60%: ~$0.05-0.50 USD per trade with Opus 4.7 + cache; **verify with real benchmark in MVP**)
- (d) open commercial category with no OSS leader; in closed SaaS, **Composer.trade** is the current reference ($40/month, no-code visual + LLM codegen) **without an explicit LLM-agentic layer or per-trade approval gate**

## Project Classification

| Axis | Value |
|---|---|
| Project type | `cli_tool` with local web dashboard (FastAPI + HTMX, mobile-first) |
| Domain | `fintech` — personal use; broker (IBKR) absorbs the regulatory layer |
| Complexity | `high` (financial risk + technical complexity, without direct compliance burden) |
| Project context | `greenfield` (repo bootstrapped 2026-04-26 on ai-playbook v0.3.1) |
| User scope | Single-user MVP; architecture non-obstructive for future multi-tenant |
| Deployment | Local-first MVP (TWS Gateway local, dashboard localhost, SQLite + Docker) |
| Money-at-risk profile | Own capital, progressive scaling (1 share → 200-500€ → more) |

### Drivers

- **Primary driver — real personal P&L**, net of LLM cost + broker commissions + time-spent.
  - **Successful MVP threshold (decision 2026-04-27)**: **≥ 0 — capital preservation. "Not losing money is already worth it."**
  - **Comparator baseline**: **Not defined in MVP** — absolute evaluation, not relative. May be added post-MVP if the need arises.
  - **Initial live capital**: 200-500€ (progressive ramp: 1 share → 200€ → 500€ → more only after evidence).
  - **Additional caps**: max drawdown ≤15%, absolute monthly cost ≤50€/month.
  - Quantitative detail and metrics in **Success Criteria > Business Success**.

- **Secondary driver — challenging technical learning**. Proposed trackable metrics:
  - ≥10 documented ADRs upon closing MVP
  - ≥20 entries in `gotchas.md`
  - ≥4 monthly retros executed (1/month during MVP)
  - ≥3 patterns identified as "shippable to OSS if released"

- **OSS/SaaS commitment — optional post-MVP trajectory, NOT an MVP driver.**
  - **Proposed SaaS evaluation trigger**: post-MVP at 6 months (≥30 days IBKR live + 5 months scaling). GO/NO-GO with 5 criteria:
    - (a) Positive P&L net-of-everything for ≥4 months
    - (b) stable and reasonable cost-per-trade ratio
    - (c) zero non-overridden risk-cap breach
    - (d) positive feedback from ≥3 informally tested early users
    - (e) Arturo feels it is a product, not a tool
  - If all 5 are met → **GO**. If <3 → **NO-GO permanent**. If 3-4 → re-evaluate after 3 additional months.

## Success Criteria

### User Success

The "user" in MVP is Arturo. Success = the flow works as promised.

| Metric | Target |
|---|---|
| Per-trade approval decision time | ≤ 30s on 90% of proposals (mobile-first achieved) |
| Trades executed without explicit approval | **0** (hard constraint, kill-switch trigger if breached) |
| Tier 1 alert latency (critical) | < 60s from event to notification |
| Tier 2 alert latency (LLM-filtered context) | ≤ 15 min during market open |
| Tier 3 routines respected (premarket/midday/postmarket/weekly) | 100% schedule respected |
| Pre-market briefing | ≤ 2 min reading, actionable |
| Weekly review PDF | Used at least once to inform the following week (proxy for usefulness) |

### Business Success

Without SaaS in MVP, "business" = Arturo's personal P&L as ideal user. Decisions from 2026-04-27:

| Metric | Confirmed target |
|---|---|
| **P&L net-of-everything** (LLM cost + broker commissions deducted) | **≥ 0 — capital preservation. Not losing money is already worth it.** |
| **Comparator baseline** | **Not defined in MVP** — absolute evaluation, not relative. May be added post-MVP if the need arises |
| **Initial live capital** | **200-500€** confirmed (progressive ramp: 1 share → 200€ → 500€ → more only after evidence) |
| **Max drawdown** | ≤ 15% (aligned with the risk engine weekly cap) |
| **Absolute monthly cost** (LLM + broker commissions) | ≤ 50€/month (appropriate for MVP capital) |
| **Cost-per-trade ratio** (informational) | Tracked and reported in `/costs` dashboard. No numeric target until capital scales (at 200-500€ the ratio is naturally high) |
| MVP evaluation period | 6-12 months post-live (≥30 days IBKR live of minimum quality) |
| **Risk-cap breach overrides count** | ≤ 3 upon closing MVP (more = the system squeaks at you → signal of bad fit) |

### Technical Success

| Metric | Target |
|---|---|
| Paper↔live parity | Concrete test: same strategy + research_brief in paper and live for 5 trading days, **fill delta ≤ 1% of avg fill** (NFR-R reformulated after Gate A amendment 2026-04-28) |
| Risk caps property-tested | hypothesis NEVER allows crossing configured caps, regardless of signal |
| Cost observability | **100%** of calls to Anthropic + Perplexity persist `ApiCostEvent` in SQLite |
| Approval gate reliability | Timeout config respected, full audit trail (no gap between proposal → approval/rejection/timeout) |
| Multi-tenant schema validation | Test: 2 concurrent tenants with distinct data do NOT cross-contaminate |
| Uncaught exceptions in hot path | **0** during 30 days of continuous IBKR live |
| Test coverage | ≥ 80% in `core/`, `risk/`, `persistence/`, `brokers/` |
| Passing property tests | 100% (hypothesis on risk engine + types) |

### Measurable Outcomes (consolidated)

**Technical learning (Secondary driver):**

- ≥ 10 documented ADRs upon closing MVP
- ≥ 20 entries in `gotchas.md`
- ≥ 4 monthly retros executed
- ≥ 3 patterns identified as "shippable to OSS if released"

**OSS/SaaS trigger evaluation** (post-MVP, not MVP): after 6 months, GO/NO-GO with 5 criteria documented in the Drivers section.

## Product Scope

### MVP — Minimum Viable Product (v1.0)

**Objective**: functional personal dogfooding — Arturo approves real trades in IBKR via Telegram + WhatsApp with a risk engine that cannot be bypassed. Per-symbol research repository (bitemporal, multi-source with provenance) that feeds decisions. LLM stack cost observability. Multi-tenant schema ready (no infra). Apache-2.0 from day 1. Basic Docker. Base docs. Backtest out of MVP scope (Gate A amendment 2026-04-28).

Complete catalog in [`docs/backlog.md` § v1.0](backlog.md). Headlines:

- Engine: MessageBus + DataEngine + ExecutionEngine + RiskEngine + Cache (Nautilus pattern adapted in pure Python)
- Abstract BrokerInterface + IBKR adapter `ib_async`
- MVP Strategies: **DonchianATR + SMA Cross**
- Per-symbol strategy config in yaml (enable/disable/configure per symbol)
- Declarative risk engine (per-trade 2%, daily 5%, weekly 15%, max 5 positions, drawdown)
- Approval channels: **Telegram + WhatsApp via Hermes/Meta API**
- Web dashboard SvelteKit (mobile-first, localhost): `/`, `/approvals`, `/trades`, `/portfolio`, `/costs`, `/risk`, `/research/<symbol>`
- LangGraph orchestration: premarket / midday / postmarket / weekly nodes + cron-jobs Tier 1+2+3
- Cost observability `ApiCostEvent` (LLM cache observability via `cache_hit_tokens`)
- Multi-model LLM routing (Opus 4.7 / Sonnet 4.6 / Haiku 4.5)
- **Research & Intelligence domain**: bitemporal knowledge repo per-symbol; ingestion SEC EDGAR + FRED + Finnhub + GDELT + openFDA + OpenInsider + yfinance via OpenBB sidecar; LLM research_briefs with citations + audit_trail; configurable methodology per-watchlist (3-pillar / CANSLIM / Magic Formula / QARP / Multi-factor)
- Multi-tenant schema (`tenant_id` first-class)
- License Apache-2.0 + Commons Clause; OpenBB sidecar isolated for AGPL boundary
- Docker + docker-compose
- Base docs (`getting-started`, `architecture`, `runbook`, `strategies/donchian_atr`, `data-model`, `personas-jtbd`)
- ≥ 17 identical Telegram + WhatsApp commands

### Growth Features (Post-MVP) — v1.5 + v2

**Objective**: cover comfortable gaps + prepare architecture for multi-broker / SaaS beta.

Detail in [`docs/backlog.md § v1.5`](backlog.md) and [§ v2](backlog.md). Headlines:

- **v1.5**: additional strategies (RSI / Bollinger / MACD / VolumeBreakout) + IBKR Execution Algos (Adaptive/TWAP/VWAP/Snap) + StoplossGuard + CooldownPeriod + Trailing stops + optional Postgres + Walk-forward + HTML reports + Hot-reload of strategy code
- **v2**: BrokerInterface adapters (Alpaca / Schwab / Tradier) + OCO + bracket orders + IBKR Iceberg/PassRelative/POV + Pairs trading / Z-score / Multi-timeframe + LowProfitPairs blocker + Email + Discord + Order management UI + Futures (CME via IBKR) + multi-tenant infra Docker Compose

### Vision (Future) — v3 + Free Backlog

**Objective**: OSS+SaaS commercial product if post-MVP triggers activate them.

Detail in [`docs/backlog.md § v3`](backlog.md) and [§ Free Backlog](backlog.md). Headlines:

- **v3**: 3-tier pricing (Solo/Team/Pro) + Stripe onboarding/billing + Crypto via CCXT + DEX (Hyperliquid/dYdX/Polymarket) + Forex + DarkIce/Accumulate-Distribute + Sector rotation / Earnings drift / Risk parity + LLM strategy codegen + marketplace + cohort course + Foundation governance
- **Free backlog**: Bonds / Mutual funds / ML/RL strategies (FinRL) / Monte Carlo / Native mobile app / TradingView Pine importer / Apple Watch / Voice approval (Whisper) / Distributed OpenTelemetry tracing / Migration to Nautilus engine if v3 scales

## User Journeys

The **only primary user in MVP is Arturo** in different operating modes. Journey 5 maps the multi-tenant case for v3 SaaS to validate the design intent.

### Journey 1 — Happy path: trade approval during a meeting

**Persona**: Arturo, in a client meeting, Thursday 14:35 Madrid (8:35 ET, 5 min after the Wall Street open).

**Opening scene**: the phone vibrates discreetly. WhatsApp shows:

> 🤖 *iguanatrader proposes:*
> **BUY SPY** — DonchianATR breakout (30d high crossed upward)
> Size: 1 share @ ~$612.40 = $612 (1.8% of capital)
> Stop: $597.20 (ATR x 2.5). Risk at stop: -$15.20 (-2.5%)
> Confidence node: 72% · Cost node: $0.08
>
> 🟢 Approve · 🔴 Reject · ✏️ Modify · ⏱️ 50s to discard

**Rising action**: Arturo pretends to check the calendar. He reads the proposal in 8 seconds. Confidence 72% is reasonable, the risk fits in the daily cap (78% of the 5% remaining), the stop is at a clear technical support. He presses 🟢 Approve.

**Climax**: 2.3 seconds later, WhatsApp confirms:

> ✅ **FILLED** SPY @ $612.42 (1 share, slippage +$0.02)
> Daily P&L: -$0.00 · Daily cap: 4.1% / 5%
> Open positions: 3

**Resolution**: the meeting continues. In the afternoon, the dashboard shows live P&L, updated equity curve. At 22:30, the postmarket summary arrives: "SPY +0.8%, P&L today +$3.45 net of $0.12 LLM cost".

**Capabilities revealed**: WhatsApp approval channel with explicit reasoning; inline buttons (callback queries); configurable timeout with visible countdown; real-time calculation of risk impact; fill confirmation with slippage; automatic postmarket summary with net-of-cost P&L.

---

### Journey 2 — Edge case: cap warning + conscious override

**Persona**: Arturo, Monday 15:20 Madrid (9:20 ET). NVDA earnings today after-close.

**Opening scene**: Telegram, proactive Tier 2 message:

> ⚠️ **Heads-up: Daily loss used 4.0% / 5%**
> 8 hours of market remaining. 1 more stop of typical magnitude would take you to the cap.
> Your latest NVDA proposal (queued) has risk 1.4% if stop hits → projected daily total: 5.4% (over cap).
>
> The RiskEngine will **REJECT** the NVDA proposal when it gets processed (in 12 min, pre-NVDA earnings briefing).

**Rising action**: 12 min later the NVDA proposal arrives, flagged `🚫 RISK REJECTED`. Button: `[Override]`. Arturo presses Override. The bot asks:

> 🔐 **Confirm RiskEngine override**
> Cap: daily 5%. Your projected daily: 5.4%.
> This is NOT a routine operation. Write the reason (min 20 chars) — it will remain in the immutable audit log.

Arturo writes: `"NVDA earnings, manual conviction, stop -8% not -ATRx2.5"`. The bot asks for a second confirmation with a preview of the modified trade.

**Climax**: confirmation. The trade executes. WhatsApp shows:

> ✅ FILLED NVDA @ $X (override logged: `risk_override_id=42`)

**Resolution**: NVDA reports. Up 11%. Arturo closes +6.4% via `/forceexit`. The trade appears in the weekly review flagged with 🟡 "manual override — earnings play". The system does not ask him for explanations — it just records and reports.

**Capabilities revealed**: Tier 2 proactive alerts about cap consumption; RiskEngine rejection with explicit reason; `/override` mechanism with double confirmation + written reason ≥ N chars; append-only `risk_overrides` table; visual marking of override in history; user-modified stop in same flow.

---

### Journey 3 — Routine: Sunday morning weekly review

> **Scope note**: Journey 3 is **representative of the tier-3 routines family** (premarket 8:30 ET / midday 1 PM / postmarket 4:30 PM / weekly Fri 6 PM). All four follow the same UX pattern — proactive notification with structured reasoning, ≤2 min reading, actionable. Weekly review is the richest instance (multi-page PDF) and is therefore narrated here; the other three share cron schedule + LLM-generated insights + multi-messaging channel. Formal coverage: FR43, FR44, NFR-P4, success criterion "Pre-market briefing ≤2 min reading".

**Persona**: Arturo, Sunday 10:00 Madrid, coffee in hand, no meetings.

**Opening scene**: WhatsApp from the previous Friday 18:00 ET, unopened until now:

> 📊 **Weekly Review week 17 / 2026**
> Weekly P&L: **+47.20€ (+0.94%)** net-of-cost
> Trades: 8 (5 winners, 3 losers, 0 BE)
> Avg holding: 1.4 days
> Max intra-week drawdown: 1.2%
> Total LLM cost: 4.10€ (Opus 0.8€ research, Sonnet 2.4€ routines, Haiku 0.9€ alerts)
> Cost/gross-P&L ratio: 8% (improving vs 12% week-16)
> Risk overrides: 0
>
> 📎 Detailed PDF attached (8 pages)

**Rising action**: 8-page PDF: equity curve + drawdown / trade table with reasoning + decision + result / analysis per strategy (DonchianATR vs SMA Cross) / cost breakdown per LangGraph node / lessons detected by the LLM listed for `memoria.md` / proposed tweaks (e.g., *"RSI period 14 showed edge in SPY over the last 8 weeks paper, consider tests with 21 in the next paper period"*) / outlook next week (macro events, earnings).

**Climax**: Arturo identifies a genuine lesson: *"breakouts confirmed with volume >2x avg won 4/4 this week, those without volume filter 1/4. Consider `VolumeBreakoutDonchian` (v1.5)"*. He notes it in the next sprint plan.

**Resolution**: PDF closed in 7 minutes. The system saved the memory of the week for him.

**Capabilities revealed**: Tier 3 cron-job weekly review Friday 18:00 ET; multi-page PDF generation with plotly + jinja; LLM-generated insights per trade; cost breakdown per LangGraph node; auto-detected "lessons" candidates for `memoria.md`; macro/earnings outlook for the next week.

---

### Journey 4 — Failure recovery: TWS Gateway goes down mid-session

**Persona**: Arturo, Wednesday 16:40 Madrid (10:40 ET), working on another project. 2 open positions (SPY long, AAPL long).

**Opening scene**: WhatsApp Tier 1 alert (critical, 0 LLM filtering, hardcoded):

> 🔴 **ALERT — IBKR connection lost**
> Last heartbeat: 95s ago
> Exposed positions: 2 (SPY 1sh, AAPL 1sh)
> Retrying reconnection... (3/10)

**Rising action**: Arturo opens the `/risk` dashboard. The kill-switch is armed but not activated. Meanwhile, the bot retries:

> 🟡 Retry 5/10 failed (TWS Gateway does not respond on localhost:7497). Retrying...

After 90 seconds:

> ✅ **Reconnected to IBKR**
> Starting state reconciliation...
> Orders pending broker-side: 0 ✓
> Positions broker-side vs cache: SPY 1sh ✓ | AAPL 1sh ✓
> No discrepancies. Resuming normal operation.

**Climax**: the system told him what happened, what it tried, and what it confirmed afterwards. No spam, no silence.

**Alternative climax (failure cascade)**: if reconciliation detects a discrepancy (cache: AAPL 1sh, broker: AAPL 0):

> 🚨 **CRITICAL DISCREPANCY DETECTED**
> Cache: AAPL 1 share. Broker: AAPL 0 shares.
> Hypothesis: order closed by broker (margin call? stop hit during disconnect?)
> Kill-switch ACTIVATED automatically. Trading paused.
> Action required: review `/portfolio` and confirm real state.
> To resume: `/resume` after verifying.

**Resolution**: Arturo verifies via TWS, sees that AAPL hit the stop during the outage (-1.8%). He learns. He marks for `gotchas.md`: *"TWS Gateway disconnect window can execute stops broker-side without notifying the bot — always server-side stops, not client-side"*.

**Capabilities revealed**: heartbeat monitoring + hardcoded Tier 1 alert; automatic retry with exponential backoff; broker↔cache state reconciliation post-reconnect; automatic kill-switch under detected discrepancy; differentiated messages (yellow warning vs red critical); `/resume` with required prior verification.

---

### Journey 5 — Future (v3 SaaS): Sara discovers iguanatrader on Hacker News

**Persona**: Sara, 32, data engineer in Barcelona. IBKR Pro account for 2 years. Tried QuantConnect (heavy), Composer.trade (black box). Reads Hacker News daily.

**Opening scene**: HN front page: *"Show HN: iguanatrader — LLM proposes, you approve from your phone, IBKR executes (open-source, Apache+CC)"*. Click. Landing in Spanish/English. Hero: 8-second GIF of the approval flow on WhatsApp.

**Rising action**: README. Clear principle: *"LLM never executes autonomously"*. Screenshots of the cost dashboard. GitHub: 800 stars, last commit 2 days ago, 8 contributors. Apache 2.0 + Commons Clause. Convinces her more than Freqtrade (crypto-only) or Lumibot (GPL).

Free sign up (free tier: unlimited research dashboard + paper trading limited to 1 strategy + 1 symbol). She connects IBKR paper via OAuth. A wizard guides her to a first Strategy: DonchianATR on SPY. SPY research_brief is generated in 30s with citations to SEC filings + FRED macro + recent news. She sees thesis, fundamentals, upcoming catalysts, estimated live LLM cost.

**Climax**: the following week, she pays the Solo tier (€29/month). Activates live on paper account. First pre-market proposal on WhatsApp. Approves. Hooked.

**Resolution**: 3 months later, she moves to IBKR live with €5K. Modest but positive P&L. Writes a technical post: *"Why I left QC for iguanatrader"*. Organic traffic grows. A community emerges.

**Capabilities revealed (NOT in MVP, v3 plan)**: public landing with demo; sign-up flow + email verification; IBKR OAuth integration; first-Strategy wizard; free tier (research dashboard + 1 paper strategy); Solo €29/month pricing tier; multi-tenant infra (1 container per user); paper → live onboarding.

---

### Journey Requirements Summary

Capabilities revealed by the journeys, grouped by capability area:

| Capability area | Journeys requiring it | Version |
|---|---|---|
| **WhatsApp + Telegram approval channel** with reasoning + buttons + timeout countdown | J1, J2 | MVP |
| **Risk engine with caps + override flow + audit trail** | J2 | MVP |
| **Cost observability + breakdown per LangGraph node** | J3, J5 | MVP |
| **Cron-jobs Tier 1 (hardcoded critical)** | J4 | MVP |
| **Cron-jobs Tier 2 (LLM-filtered context)** | J2 | MVP |
| **Cron-jobs Tier 3 (routines: premarket / midday / postmarket / weekly)** | J3 | MVP |
| **Heartbeat monitoring + broker↔cache reconciliation + automatic kill-switch** | J4 | MVP |
| **Web dashboard `/portfolio` `/risk` `/costs` `/runs`** | J3, J4 | MVP |
| **Weekly Review PDF** with equity + trades + cost + lessons + outlook | J3 | MVP |
| **`/override` flow** with double confirm + reason + audit | J2 | MVP |
| **`/forceexit` from Telegram/WhatsApp** | J2 | MVP |
| **Public landing page + sign-up + IBKR OAuth + onboarding wizard** | J5 | v3 |
| **Multi-tenant infra (container per tenant)** | J5 | v2 (infra) → v3 (SaaS) |
| **Pricing tier Solo / Team / Pro** + Stripe | J5 | v3 |

## Domain-Specific Requirements

iguanatrader is `fintech` with `high` complexity, but the complexity **does not come from regulatory burden** but from financial risk + technical. In single-user MVP with own capital + broker (IBKR) absorbing the regulatory layer: GDPR does not apply (you do not process third-party data), KYC/AML does not apply (you do not custody third-party funds), MiFID II / SEC RIA does not apply (a single user = you), PCI-DSS does not apply (no payments / cards).

The real domain-specific concerns are **operational (security + audit + resilience)** and **anticipatory (future v3 SaaS regulatory)**.

### Operational security (MVP — applies)

| Concern | Mechanism |
|---|---|
| Broker credentials (IBKR API keys + TWS Gateway access) | SOPS (age) + gitignored `.env.local`. `pre-commit` with gitleaks. Never hardcoded. |
| LLM API keys (Anthropic, Perplexity) | Same SOPS. `iguana_secrets.yaml.enc`. |
| Telegram bot token + WhatsApp Meta credentials | Same. Tokens rotatable without redeploy. |
| Runtime auth (who issues commands to the bot) | `authorized_phones` (WhatsApp) + `authorized_telegram_ids` whitelist. Messages from non-authorized senders: log + ignore. |
| Local dashboard access | localhost-only in MVP, no auth. If exposed to local network → basic auth + nginx reverse proxy. |
| DB encryption at-rest | SQLite without encryption in MVP (single-user, OS FDE sufficient). In v2 multi-tenant: SQLCipher per-tenant or Postgres with `pgcrypto`. |

### Audit & immutability (MVP — applies, is a differentiator)

| Event type | Guarantee |
|---|---|
| Trades / orders / fills | Append-only in SQLite. NO `UPDATE`, NO `DELETE`. State computable as a view. |
| Risk overrides (`/override <reason>`) | Append-only `risk_overrides` table with `tenant_id`, `proposal_id`, `reason_text`, `confirmation_chain`, `timestamp`, `risk_state_snapshot`. |
| LLM API calls | Append-only `api_cost_events` table. Optional prompt hash (decision: privacy vs audit). |
| Approval decisions (granted / rejected / timeout) | Append-only `approval_events` table with channel (Telegram/WhatsApp), latency, decision, user_id. |
| Config changes via `/reload_config` | `config_history` table with yaml diff + timestamp + trigger source. |

### Resilience patterns (MVP — applies, justified in Journey 4)

- **IBKR heartbeat** every 30s, Tier 1 alert if gap > 90s
- **Exponential retry** with backoff (3, 6, 12, 24, 48s × 5 attempts)
- **Post-reconnect reconciliation** broker↔cache (orders + positions); if discrepancy → automatic kill-switch
- **Crash recovery**: state computable from append-only SQLite — restart does NOT lose state, it just recomposes from events
- **Redundant kill-switch**: file (`.killswitch`) + env (`IGUANA_HALT`) + Telegram/WhatsApp (`/halt`) + dashboard button — any of them triggers halt

### Future regulatory considerations (v3 SaaS — NOT in MVP, listed to avoid build-traps)

| Regime | Applies if | Design mitigation |
|---|---|---|
| EU MiFID II | SaaS with EU users + you propose specific trades | Keep "user-owned-account orchestration" architecture: the user has their IBKR account; iguanatrader only orchestrates the user's software. Defensible as "trading software" not "investment service" |
| US SEC / FINRA "Investment Advisor" | SaaS with US users + you recommend trades | Same. Triple-approval per trade reinforces the defense. Consider entering EU first |
| GDPR | Any EU user in SaaS | DPA with providers (Anthropic, Meta, Twilio if applicable). Right-to-erasure: `tenant_id` table allows surgical deletion. Minimal PII logging |
| CCPA | California users in SaaS | Similar to GDPR, reduced scope |
| AML / KYC | Does NOT apply if you do not custody funds | Keep "user has IBKR account, we don't touch funds" — IBKR does KYC, not us |
| Tax reporting (1099-B in US, modelo 720 in ES) | The broker issues it | iguanatrader must **be able to export trades** in a compatible format so the user can reconcile with their 1099 / tax return — endpoints `/export_trades_csv` + `/export_trades_pdf` |

### Fraud Prevention

For iguanatrader (single-user MVP, own capital, no custody of third-party funds), traditional fintech "fraud prevention" (PCI-DSS, payment fraud, AML transaction monitoring) **does not apply**. The actual fraud surfaces and their mitigations:

| Fraud vector | Mitigation | FR/NFR refs |
|---|---|---|
| **Account takeover** (attacker issues bot commands impersonating Arturo) | Explicit whitelist `authorized_phones` (WhatsApp) + `authorized_telegram_ids` (Telegram). Messages from non-whitelisted senders: log + ignore without reply (avoids enumeration info leak). | FR31, FR38, NFR-S3, NFR-S4 |
| **Self-harm via runaway bot** (LLM hallucination generates destructive trades) | Mandatory triple gate: (a) RiskEngine filters/clips first; (b) mandatory parseable structured reasoning; (c) explicit human approval per trade. Without approval → no execution. | FR45, FR24-FR30, FR11 |
| **Code-level secret leaks** (accidental commit of keys/tokens) | Pre-commit gitleaks + CI block. Secrets always SOPS-encrypted or env vars, never yaml plain. `.env.local` gitignored, `.env.example` checked-in with empty keys. | NFR-S1, NFR-S2 |
| **Token compromise post-leak** (attacker obtains broker/LLM/Telegram token) | Tokens rotatable without redeploy or daemon restart (hot-reload via SIGHUP). Runbook documents emergency rotation procedure. | NFR-S8 |
| **Internal privilege escalation** (multi-tenant v2/v3) | NA in MVP (single-user). In v2 multi-tenant: `tenant_id` isolation per query + per-process containers; a tenant never reads another's data. Formal RBAC in v3 SaaS if there are roles. | NFR-SC1, NFR-SC4 |
| **Research data manipulation** (fact corruption in knowledge repo via compromised source) | Every fact persists with `source_id` + `source_url` + `retrieved_at` + `retrieval_method`; bitemporal schema allows detecting contradictory revisions of the same fact across vintages; LLM research_briefs must cite facts and not invent values; show-your-work audit_trail blocks calculations without traceability. | FR68-FR70, FR71 |

**Summary**: fraud prevention in iguanatrader is **architectural, not transactional**. The bot cannot defraud the user because the bot cannot decide to execute anything by itself. The user can only be deceived if they lose control of their approval channel, and that is mitigated with whitelist + secret rotation. ML fraud detection, transaction scoring, or AML compliance are NOT required because the entire financial flow occurs within the user's own account at their broker (IBKR), which already has its own AML/KYC layer.

### Domain-specific risks & mitigations

| Risk | Mitigation |
|---|---|
| Lookahead bias in research feature consumption (Strategy reads current snapshot when evaluating historical bar) | Tier A/B/C system in feature provider registry; CI assertion that strategy code does not consume tier-B features without `retrieved_at <= bar.date` constraint. Live trading not affected (current data IS correct). |
| Race condition risk-check vs submit | `with order_lock:` wraps risk check + submit in a critical section. |
| Overfitting in parameter tuning | Textbook MVP defaults (Donchian 20+5, ATR ×2.0); paper trading 30-90 days validates; walk-forward optimization deferred to v1.5+ if paper reveals edge. |
| Telegram/WhatsApp spoofing | `authorized_phones` whitelist. Any message from non-whitelisted number: log + ignore. |
| TWS Gateway disconnect executes broker-side stops without notifying | Lesson from Journey 4. Stops always **server-side at the broker** (not client-side). Document in `gotchas.md`. |
| LLM hallucination in proposal | Triple gate: (a) RiskEngine filters/clips before approval; (b) human approves; (c) proposal must include parseable structured reasoning (not free-form). |
| LLM cost runaway | Daily/weekly LLM cost budget cap. If exceeded: routines downgrade to Sonnet/Haiku automatically, Tier 2 alerts get silenced. |

## Innovation & Novel Patterns

### Detected Innovation Areas

3 meta-innovative patterns (beyond the 12 individual features in the Executive Summary):

#### 1. Inverse category: "Responsible LLM-orchestrated retail trading"

The 2025-2026 industry sells **AI-agentic auto-trader**:

- TradingAgents (Tauric Research) — multi-LLM agents that decide autonomous trades in academic demo
- LLM-trading-agents (Medium proliferation) — "let GPT do the trades for you" tutorials
- Composer.trade "Trade With AI" — LLM generates strategy, executes without explicit per-trade gate

iguanatrader sells **the opposite**: the LLM reasons and proposes, the human is the mandatory gate, the deterministic engine executes. No OSS currently occupies this position. The paradigm inversion is the innovation, not the sum of features.

#### 2. Cost observability of the LLM stack itself as first-class citizen

To date, OSS trading projects do not measure what their own AI layer costs. iguanatrader elevates it to append-only table from day 1 (`api_cost_events`), dedicated dashboard page (`/costs`), derived metric `cost-per-trade ratio`, automatic multi-model routing with budget caps. This is novel — not because it is technically difficult, but because **nobody has made it explicit in this vertical**.

#### 3. Mobile-first multi-channel (Telegram + WhatsApp) with reasoning embedded in the proposal

OSS bots exist (Freqtrade Telegram). Proposals with reasoning exist (custom GPT prompts). **The combination "mobile message + structured LLM reasoning + 30s to approval/reject + audit trail" is the flow not yet built**. Reusing Hermes for WhatsApp Meta API multiplies accessibility without building from scratch.

### Market Context & Competitive Landscape

| Category | 2026 Leaders | iguanatrader position |
|---|---|---|
| OSS multi-asset framework | Lean (18.6k★), NautilusTrader (22.3k★) | NOT competing — they are generalists, we are opinionated |
| OSS retail crypto-bot | Freqtrade (49.4k★), Hummingbot (9k★), OctoBot (3.5k★) | NOT competing — crypto-only vs US equity |
| OSS Python equity-friendly | Lumibot (1.4k★ — GPL blocks SaaS) | Partially competing; Lumibot has engine + LLM hooks but NO human approval gate |
| Closed SaaS retail-quant | Composer.trade ($40/month, no-code visual + LLM codegen) | iguanatrader competes on value: open-core + IBKR (vs Alpaca-only) + per-trade approval gate (vs no gate) + cost observability |
| Academic LLM-trading | TradingAgents (high traction) | NOT competing — they are demos, we are product |
| **"Responsible LLM-orchestrated retail" category** | **EMPTY** | iguanatrader is the first OSS with presence in this category |

### Validation Approach

How we validate that the innovation delivers real value, **it is not innovation theater**:

| Innovation claim | How it is validated (concrete and measurable) |
|---|---|
| "Human approval gate per trade is a feature, not a bug" | MVP metric: average approval decision time ≤ 30s. If Arturo finds the flow annoying and starts auto-approving everything or doing massive overrides, the pattern **fails** |
| "LLM stack cost observability has value" | Cost-per-trade ratio visible and tracked in `/costs`. If in 6 months Arturo never consults the dashboard and the ratio rises unnoticed, **it fails** |
| "Mobile-first multi-channel speeds up decisions" | % of approvals decided in <30s. If <70%, the mobile flow does not work as promised |
| "LLM in research/orchestration with guardrails adds alpha" | Ablation test: compare P&L of proposals with LLM reasoning vs hardcoded proposals from the Strategy direct. If the LLM-augmented does not provide measurable edge, **it is deactivated post-MVP** |
| "Multi-tenant ready from day 1 saves v2 refactor" | Time-to-deploy first additional tenant in v2 (target: <1 week). If it requires a major refactor, the "ready" was rhetoric |

### Risk Mitigation

Specific innovation risks + mitigations:

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| LLM hallucination in trade proposal | Medium | High | Triple gate: (a) RiskEngine filters BEFORE; (b) mandatory parseable structured reasoning; (c) human final |
| LLM cost runaway (loop, inefficient prompt) | Low | Medium | Daily/weekly budget caps; auto-downgrade Opus→Sonnet→Haiku on excess; Tier 2 alerts silenced if over-budget |
| Approval fatigue (Arturo stops reading proposals) | Medium | High | Count overrides + measure decision time; if >30s sustained → bad fit, consider deactivating channel |
| Multi-channel complexity without real use | Low | Low | Approval distribution metric Telegram vs WhatsApp. If <10% per channel, consider deprecating |
| Bus factor 1 kills the OSS if released | High (structural) | Critical for v3 | Documented governance plan in v2 before OSS launch; or Foundation-style if traction justifies it |
| "Inverse category" is a niche that does not scale | Medium | High | SaaS trigger from Step 2c is exactly the post-MVP go/no-go check |
| Composer / closed SaaS pivots and kills the differentiation | Medium | High | Maintain iteration speed + open-core as moat. Composer cannot open-source without destroying its valuation |
| Research repo provenance gaps (fact ingested without complete metadata) | Low | High | DB CHECK + NOT NULL constraints + CI integration test block incomplete inserts; any `source_id IS NULL` or `retrieved_at IS NULL` fails in transaction |

### Fallback if the innovation does not work

If after 6 months of MVP the validation gates **fail**:

- If the approval gate annoys → reduce proposal frequency (stricter LLM filter), do not eliminate the gate
- If the LLM does not provide alpha → keep iguanatrader as a pure deterministic bot, leave LangGraph in "informative, not propositive" mode
- If multi-channel is overhead → consolidate on Telegram only, deprecate the WhatsApp Hermes path
- If nobody uses cost observability → keep it (it is low-cost) but remove it from the v3 SaaS positioning feature list
- If the category does not resonate → pivot to "your own Composer in open-source" (same engine, different positioning)

iguanatrader is still useful as Arturo's personal bot even if the entire innovation hypothesis fails. The maximum downside is "functional but less differentiated bot", not "dead project".

## CLI-Specific Requirements

### Project-Type Overview

iguanatrader exposes its main functionality through an `iguana` CLI (typer-based) covering 3 operating modes: **one-shot scripting** (ingest, propose, research, export), **long-running daemon** (paper, live, dashboard), and **operational commands** (halt, resume, override). The CLI is the **local human control layer**; the mobile channels (Telegram + WhatsApp) are the remote control layer.

### Technical Architecture Considerations

Scriptable, no interactive REPL. Each command is an atomic process with stable exit code. There is no custom shell inside the bot. Long-running modes (`live`, `paper`, `dashboard`) run as daemon processes with correct signal handling (SIGTERM = clean halt, SIGINT = same, SIGHUP = reload config).

**Stack**: `typer` + `rich` (human UX) + `structlog` (JSON logs) + `pydantic-settings` (config validation).

### Command Structure

Hierarchy `iguana <verb> [noun] [flags]`:

| Command | Mode | Function |
|---|---|---|
| `iguana init` | one-shot | Initializes local project (configs, secrets template, DB schema) |
| `iguana ingest bars <symbol> [--from <date>] [--to <date>]` | one-shot | Downloads historical bars, persists to parquet cache (FR66) |
| `iguana research refresh <symbol>` | one-shot | Force-refresh current research_brief for symbol; ingests pending facts (EDGAR/FRED/news) + LLM synthesis |
| `iguana research show <symbol> [--version <n>]` | one-shot | Prints current brief or specific version with citations + audit_trail |
| `iguana paper` | daemon | IBKR paper trading (`PAPER=true` in config) |
| `iguana live` | daemon | IBKR live trading (requires `--confirm-live` flag) |
| `iguana dashboard [--port 8000]` | daemon | Serves FastAPI + HTMX on localhost |
| `iguana propose <strategy> <symbol>` | one-shot | Forces a manual proposal (research mode) |
| `iguana halt [--reason <text>]` | one-shot | Activates kill-switch (writes `.killswitch`, notifies via Telegram) |
| `iguana resume` | one-shot | Removes kill-switch (with prior verification) |
| `iguana override <proposal_id> --reason <text>` | one-shot | Override of RiskEngine reject (audit log) |
| `iguana reload-config` | one-shot | Hot-reload of yaml configs |
| `iguana export trades [--from <date>] [--format csv\|pdf]` | one-shot | Exports trade history |
| `iguana strategies list` | one-shot | Catalogs available strategies |
| `iguana strategies enable <symbol>` / `disable <symbol>` | one-shot | Per-symbol toggle |
| `iguana strategies set-param <symbol> <param> <value>` | one-shot | Hot-tune param |
| `iguana retain <kind> --content <text>` | one-shot | Persist to Hindsight bank `iguanatrader` (inherited from playbook) |
| `iguana version` | one-shot | Version + commit hash + python version |

Subcommand grouping via nested typer apps: `iguana strategies` groups list/enable/disable/set-param; `iguana export` groups trades/portfolio/risk-overrides; etc.

### Output Formats

**Default: human-readable** with `rich`:

- Tables with colors for `iguana strategies list`, `iguana export trades`, `iguana version`
- Progress bars for `iguana ingest bars`, `iguana research refresh`
- Boxes with summary for `iguana research show`

**`--json` flag** on every one-shot command that produces data: machine-parseable stdout output. Designed for chaining with `jq` or consumption from scripts:

```bash
iguana export trades --from 2026-01-01 --json | jq '.[] | select(.pnl > 0) | .symbol' | sort | uniq -c
```

**Structured logs** via `structlog` → JSON to stdout (daemon mode) or rotating file. Levels: DEBUG/INFO/WARNING/ERROR with `event` + contextual fields (tenant_id, strategy, symbol, proposal_id, etc.).

**Binary reports**:

- PDF for weekly review (WeasyPrint or ReportLab) — FR44
- HTML for `iguana research show <symbol> --html` (Plotly fundamentals chart + brief render)
- CSV for `iguana export trades --format csv`

**Exit codes** with stable semantics:

- `0` — success
- `1` — generic error
- `2` — invalid config
- `3` — broker unavailable / TWS Gateway down
- `4` — kill-switch active (rejects trading commands)
- `5` — risk cap breach (override needed)

### Config Schema

**Stack**: `pydantic-settings` loads + validates at startup.

**Layering** (descending precedence):

1. CLI flags (`--port 8001` one-off override)
2. ENV vars (`IGUANA_RISK_DAILY_PCT=0.04` for a specific session)
3. Encrypted secrets (`config/secrets.yaml.enc` SOPS-encrypted; decrypts at runtime with age key)
4. Versioned yaml configs:
   - `config/iguana.yaml` — master config (broker, mode, paths)
   - `config/risk.yaml` — protections + caps
   - `config/strategies.yaml` — per-symbol strategy + params
   - `config/llm_prices.yaml` — versioned pricing table
   - `config/slippage.yaml` — slippage models per broker
5. Defaults hardcoded in pydantic models

**Validation**: pydantic fails fast at startup with specific messages. Mandatory test: `iguana init` with invalid config returns exit code 2 + clear message indicating which key fails.

**Hot-reload** via `iguana reload-config` (also available on `/reload_config` Telegram). Diff + audit log to `config_history` table.

**Secrets**:

- Never in yaml plain. Always SOPS-encrypted or ENV var.
- `gitleaks` pre-commit + CI block.
- `.env.local` gitignored for development; `.env.example` checked-in with empty keys.
- Token rotation documented in runbook (does not require redeploy).

### Scripting Support

**Stdin/stdout**: one-shot commands write **only useful data** to stdout when `--json` (without progress bars or colors), allowing clean pipes. Errors always to stderr.

**Daemon mode** (`paper`, `live`, `dashboard`):

- Writes PID to `~/.iguana/iguana.pid`
- Listens for SIGTERM (graceful halt — closes pending trades, persists state, closes connections), SIGINT (same), SIGHUP (reload config)
- Stdout JSON logs by default; `--log-file` for redirection
- Compatible with `systemd` and `docker compose` orchestration

**Idempotency**: commands like `iguana halt` are idempotent (kill-switch already active → noop with exit 0 + warning). `iguana ingest` already cached → noop with `--force` to re-fetch.

**Composability**:

```bash
# Typical research pipeline
iguana ingest bars SPY --from 2024-01-01 \
  && iguana research refresh SPY \
  && iguana research show SPY --json \
  | jq '.brief.thesis' \
  | tee /tmp/spy_thesis.txt
```

**Shell completion**: typer auto-generates completions via `iguana --install-completion <bash|zsh|fish|powershell>`. Each command documented with producible `--help`.

### Implementation Considerations

- CLI tested with `typer.testing.CliRunner`: each command with unit tests covering happy path + error paths + exit codes
- Structured logging from the first commit (no print statements). `structlog.contextvars.bind_contextvars()` to propagate `tenant_id`, `proposal_id` automatically
- Type-safe end-to-end: pydantic models validate I/O of each command
- Semantic versioning: `iguana version` shows version + commit + python + key dependencies
- Rich `--help` auto-generated by typer; keep inline documentation (no duplicated docs in external md)

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP Approach: Problem-solving MVP** (no platform, no revenue, no experience).

Conscious decision: the primary driver is to solve **Arturo's problem** (disciplined trading with little time). We do NOT pursue:

- "Experience MVP" — nobody else uses the product in MVP, no delight to optimize for beyond the user himself
- "Platform MVP" — multi-tenant is **schema-ready** (ADR-008), not active functionality until v2
- "Revenue MVP" — no pricing in MVP, no sign-ups, no Stripe; OSS+SaaS is a post-MVP trajectory gated by the Executive Summary trigger

This means that **marginal decisions are resolved toward "the simple thing that works for Arturo today"**, not "what would scale to 1000 users". Example: dashboard without auth on localhost (do not build multi-user login so that Arturo can log into his own machine).

Validation of the approach: post-MVP, the SaaS evaluation trigger is exactly the go/no-go check. If the 5 criteria are met, **then** the approach is rewritten to "platform MVP" in v2.

### Resource Requirements

| Dimension | Value |
|---|---|
| Team | **1 dev (Arturo) + Claude Code as copilot** |
| Risk capital (IBKR live account) | 200-500€ progressive ramp |
| Operational capital (LLM + infra) | ≤ 50€/month target |
| MVP time budget | 3-4 calendar months (estimate, dependent on hours/week Arturo dedicates) |
| Bus factor | **1 (Arturo)** ⚠️ — structural risk documented in backlog § "Operational risks" |
| Critical skills | Python async, IBKR API, LangGraph, FastAPI, pydantic, asyncio, SQLAlchemy. All covered by Arturo + Claude. Nothing exotic like Rust or C#. |

### MVP Feature Set (Phase 1) — pointer to already-completed docs

> **Complete catalog in [`docs/backlog.md` § v1.0](backlog.md)** (not duplicated here — the backlog is the SSOT for per-version scope).

MVP scope headlines:

- Engine: MessageBus + DataEngine + ExecutionEngine + RiskEngine + Cache (Nautilus pattern adapted in pure Python)
- Abstract BrokerInterface + IBKR adapter (`ib_async`)
- MVP Strategies: DonchianATR + SMA Cross
- Per-symbol strategy config (yaml-driven, hot-reloadable)
- Declarative risk engine (per-trade 2%, daily 5%, weekly 15%, max 5 positions, drawdown)
- Approval channels: Telegram + WhatsApp via Hermes
- Web dashboard SvelteKit (mobile-first, localhost): ~8 pages (incl. `/research/<symbol>`)
- LangGraph orchestration: 4 routine nodes + cron-jobs Tier 1/2/3
- Research & Intelligence domain (FR57-FR79): bitemporal knowledge repo + multi-source ingestion + LLM research_briefs with citations
- Cost observability (`ApiCostEvent` with cache_hit_tokens)
- Multi-model LLM routing (Opus / Sonnet / Haiku)
- Multi-tenant schema (`tenant_id` first-class)
- License Apache-2.0 + Commons Clause
- Docker + docker-compose
- Base docs (`getting-started`, `architecture`, `runbook`, `strategies/donchian_atr`)
- CLI with ~16 commands + completions
- Telegram/WhatsApp with ~20 identical commands

**User journeys supported in MVP**: J1 (happy path), J2 (override edge case), J3 (weekly review routine), J4 (failure recovery). J5 (Sara SaaS onboarding) is **explicitly out of MVP** — designed in Step 4 only to validate future multi-tenant design intent.

### Post-MVP Features

> Granular detail in [`docs/backlog.md`](backlog.md) — sections v1.5, v2, v3 and free backlog.

**Phase 2 — Growth (v1.5 + v2)**: additional strategies (RSI/Bollinger/MACD/VolumeBreakout/Pairs/MultiTF), IBKR Execution Algos (Adaptive/TWAP/VWAP/Snap/Iceberg/POV), risk extensions (StoplossGuard/CooldownPeriod/Trailing), additional brokers (Alpaca/Schwab/Tradier), advanced order types (OCO/bracket), CME futures, optional Postgres, walk-forward, Docker Compose multi-tenant infra.

**Phase 3 — Expansion (v3)**: SaaS launch with 3-tier (Solo/Team/Pro), Stripe onboarding/billing, crypto via CCXT, DEX (Hyperliquid/dYdX/Polymarket), forex, IBKR DarkIce/Accumulate-Distribute, macro strategies (sector rotation/earnings drift/risk parity), LLM strategy codegen, marketplace, education flywheel, Foundation governance.

**Free backlog** (no commitment): bonds, mutual funds, ML/RL strategies, Monte Carlo, native mobile app, TradingView Pine importer, Apple Watch, voice approval, distributed OpenTelemetry, migrate engine to Nautilus if v3 scales.

### Risk Mitigation Strategy (consolidation)

Risks already documented in Domain Requirements and Innovation Risk. Consolidated by category with scope-impact:

| Category | Risk | Mitigation | MVP scope impact |
|---|---|---|---|
| Technical | LLM hallucination in proposal | Triple gate (RiskEngine + structured reasoning + human) | DOES NOT cut — core feature |
| Technical | LLM cost runaway | Budget caps + auto-downgrade model + silenceable Tier 2 alerts | DOES NOT cut |
| Technical | TWS Gateway disconnect executes broker-side stops | Always server-side stops; post-reconnect reconciliation | DOES NOT cut |
| Technical | Lookahead in research feature consumption (tier B without retrieved_at constraint) | Tier A/B/C system in feature provider registry; CI assertion blocks incorrect use in strategy code | DOES NOT cut |
| Technical | Race conditions risk-check vs submit | `with order_lock:` wraps critical section | DOES NOT cut |
| Market | "Inverse category" does not resonate (niche that does not scale) | Post-MVP SaaS trigger is the go/no-go check | DOES NOT cut MVP — decides v3 |
| Market | Composer/closed SaaS pivots and kills differentiation | Iteration speed + open-core as moat | DOES NOT cut MVP |
| Market | Approval fatigue (Arturo stops reading proposals) | Decision-time metric; if >30s sustained → deactivate channel | DOES NOT cut — validation gate |
| Resource | Bus factor 1 kills the project if Arturo leaves | Documented governance in v2 before OSS launch | DOES NOT cut MVP — plan v2 |
| Resource | 3-4 month time budget slips to 6-8 | **Cut Multi-model LLM routing and Web dashboard to minimum version if time pressure** | CONDITIONAL CUT |
| Resource | LLM capital exceeds 50€/month | Move routines to Sonnet/Haiku permanently; deprecate Tier 2 alerts if they do not contribute | DOES NOT cut MVP structurally |

**Contingent cuts under time-pressure** (in order of severity):

1. Web dashboard reduced to 3 pages (`/`, `/approvals`, `/risk`) — removes `/trades`, `/portfolio`, `/costs`, `/runs` (nice-to-have). Data remains in SQLite, accessible via CLI.
2. WhatsApp postponed to v1.5 (Telegram-only in MVP).
3. Multi-model LLM routing simplified to Sonnet-only.
4. Postmarket summary and midday check (Tier 3) postponed to v1.5 (keep only premarket + weekly).

**NEVER cut**: RiskEngine + caps, abstract BrokerInterface, multi-tenant schema, license, Telegram approval, audit trail. **That is the architectural backbone**.

## Functional Requirements

> **Capability contract**: from here onward, every feature must trace to an FR. What is not listed will not exist in the final product unless explicitly added.

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

- **FR59**: System ingests SEC filings (10-K, 10-Q, 8-K, Form 4 insider, 13F-HR institutional) via SEC EDGAR official APIs with point-in-time filing-date semantics (via `edgartools` Python lib)
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

- **FR74**: `TradeProposal` references the current `research_brief` at proposal time (`research_brief_id` FK) so trade audit replays "exactly which brief informed this decision"; brief is read-once and its content snapshot stored in proposal `reasoning` JSON for full self-containment
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

| Capability area | Discovery source | FRs |
|---|---|---|
| Strategy Management | ADR-008 (per-symbol config) | FR1-FR5 |
| ~~Backtest & Research~~ | REMOVED 2026-04-28 (Gate A amendment) | ~~FR6-FR10~~ |
| Trade Lifecycle | Journeys 1 & 4 + execution lifecycle pattern | FR11-FR18 |
| Risk Management | Journey 2 + Protections pattern + ADR-006 revised | FR19-FR30 |
| Notifications & HITL | Journeys 1-4 + Telegram + Hermes WhatsApp | FR31-FR38 |
| LLM Orchestration & Cost | Vision pillars + Innovation areas | FR39-FR45 |
| Data, Persistence & Audit | Domain Audit section + multi-tenant schema | FR46-FR51 |
| Operational Surface | CLI-Specific Requirements | FR52-FR56 |
| **Research & Intelligence Domain** | **Gate A amendment 2026-04-28 + `docs/research/data-sources-catalogue.md`** | **FR57-FR81** |

## Non-Functional Requirements

> Selective categories. Explicitly skipped: **Accessibility** (single-user MVP, no broad audience) and **Compliance regulatory** (covered in Domain Requirements § Future regulatory considerations).

### Performance

- **NFR-P1**: 90% of trade proposals delivered to Telegram/WhatsApp within 5s from generation
- **NFR-P2**: Approval timeout countdown guarantees ≥50s useful for the user (default timeout 60s, delivery latency <10s)
- **NFR-P3**: 99% of Tier 1 alerts delivered within 60s from the event trigger
- **NFR-P4**: Tier 2 polling intervals respected ±1min (default 15min during market open)
- **NFR-P5**: 95% of approved orders confirmed by broker within 3s post-approval (excludes broker latency)
- **NFR-P6**: ~~1-year daily backtest on 1 symbol completes in <60s~~ — REMOVED 2026-04-28 (Gate A amendment, backtest out of MVP scope)
- **NFR-P7**: Dashboard page load <500ms on localhost
- **NFR-P8**: IBKR heartbeat every 30s; alert triggered if gap > 90s
- **NFR-P9**: Research_brief refresh for 1 symbol completes in <30s (full re-synthesis with cache hit ratio ≥40%)

### Security

- **NFR-S1**: All secrets (broker keys, LLM keys, Telegram bot token, WhatsApp Meta credentials) encrypted at-rest with SOPS+age
- **NFR-S2**: Pre-commit `gitleaks` must pass on every commit; CI blocks merges with detected leaks
- **NFR-S3**: Explicit whitelist of authorized senders (Telegram IDs + WhatsApp phone numbers); values in encrypted config
- **NFR-S4**: Messages from non-whitelisted senders: log + ignore, no reply (avoids enumeration info leak)
- **NFR-S5**: Override commands require ≥20-character written reason + double confirmation before applying
- **NFR-S6**: Dashboard served on `localhost` only by default; exposing to local network requires basic auth + reverse proxy (e.g., nginx)
- **NFR-S7**: SQLite at-rest without encryption in MVP (single-user, OS FDE sufficient). Per-tenant encryption-at-rest mechanism (e.g., SQLCipher or Postgres `pgcrypto`) from v2 multi-tenant
- **NFR-S8**: API tokens rotatable without redeploy or daemon restart (hot-reload via SIGHUP)

### Reliability

- **NFR-R1**: 30 days of continuous IBKR live with **0 uncaught exceptions** in hot path (measurable via structured logs grep)
- **NFR-R2**: Broker↔cache reconciliation 100% successful after any reconnect (E2E test: simulate outage, verify orders + positions matching)
- **NFR-R3**: Crash recovery: after `kill -9` + restart, append-only SQLite state allows reconstructing state without losing events
- **NFR-R4**: 100% of proposals exceeding timeout are discarded without execution (mandatory test)
- **NFR-R5**: Kill-switch latency: from activation (file/env/cmd/dashboard) until system rejects new trades: <2s
- **NFR-R6**: Property tests on RiskEngine pass at 100% — hypothesis NEVER allows crossing configured caps, regardless of signal (CI-blocking)
- **NFR-R7**: IBKR reconnect with exponential backoff: 3, 6, 12, 24, 48s × 5 attempts; after that → automatic kill-switch

### Observability

- **NFR-O1**: **100%** of LLM calls (Anthropic + Perplexity) persist `ApiCostEvent` in SQLite with all required fields
- **NFR-O2**: Structured JSON logs with `tenant_id`, `proposal_id`, `strategy`, `symbol` propagated automatically via context-binding mechanism of the Python structured logger (`structlog.contextvars`)
- **NFR-O3**: Log rotation: max 100MB per file, 7-day default retention (configurable)
- **NFR-O4**: Cost dashboard `/costs` updated every 5min during active session
- **NFR-O5**: Audit trail of risk overrides + approval decisions queryable via CLI (`iguana export risk-overrides --format csv`)
- **NFR-O6**: ~~Backtest HTML report <10s post-run~~ — REMOVED 2026-04-28 (Gate A amendment)
- **NFR-O7**: Each proposal includes optional `prompt_hash` in `ApiCostEvent.metadata` for reproducible audit (documented privacy trade-off)
- **NFR-O8**: Research_brief HTML/JSON render must include 100% of citations resolved to `research_facts.source_url`; broken citations fail the render (soft-fail with warning, hard-fail in CI)

### Maintainability

- **NFR-M1**: Test coverage ≥ 80% in `core/`, `risk/`, `persistence/`, `brokers/` (CI-blocking)
- **NFR-M2**: Property tests (hypothesis) on risk engine + types passing 100% (CI-blocking)
- **NFR-M3**: Type-checking `mypy --strict` on `src/iguanatrader/core/*` (CI-blocking)
- **NFR-M4**: Lint `ruff` + format `black` without warnings (CI-blocking)
- **NFR-M5**: Base docs complete before v1.0 release: `getting-started.md`, `architecture.md`, `runbook.md`, `strategies/donchian_atr.md`
- **NFR-M6**: ≥10 documented ADRs upon closing MVP (Secondary driver target)
- **NFR-M7**: ≥20 entries in `gotchas.md` upon closing MVP (Secondary driver target)
- **NFR-M8**: Governance plan documented in `docs/governance.md` before OSS launch (bus factor 1 mitigation)
- **NFR-M9**: Pin dependencies with `poetry.lock` or equivalent; manual updates via dependabot (no auto-merge)

### Scalability (light, future-oriented)

- **NFR-SC1**: Multi-tenant schema ready from day 1: `tenant_id` on every table of SQLite/Postgres, all queries filtered
- **NFR-SC2**: SQLite → Postgres migration with same schema without data loss (E2E test in v1.5)
- **NFR-SC3**: "1 container per tenant" pattern documented in v2 runbook (not implemented in MVP)
- **NFR-SC4**: Hindsight bank per `tenant_id` isolated: cross-tenant queries return 0 results (multi-tenant scenario test)
- **NFR-SC5**: Schema allows adding new brokers without DDL changes (uses `broker_id` enum + per-broker JSON metadata)

### Integration

- **NFR-I1**: Abstract `BrokerInterface` documented with contract tests; new adapter implementable in <40h dev (validated against IBKR adapter as benchmark)
- **NFR-I2**: IBKR adapter resilient to TWS Gateway disconnects with exponential backoff 5 retries before kill-switch
- **NFR-I3**: Anthropic SDK used with **prompt caching enabled**; target cache hits 40-60% on repetitive routines (measured in MVP, adjusted in v1.5)
- **NFR-I4**: Perplexity API rate-limited to `config.perplexity.max_rpm` with queue + exponential backoff
- **NFR-I5**: Telegram bot reconnects automatically on connection loss without losing pending messages (long-polling resilience)
- **NFR-I6**: WhatsApp via Hermes/Meta API: pre-approved templates before v1.0 launch; token rotation without downtime
- **NFR-I7**: MCP server compatibility: Anthropic + Perplexity exposed via MCP when applicable (Hindsight bank `iguanatrader` already provisioned)
- **NFR-I8**: Hindsight recall (when enabled per FR81) latency p50 < 500ms, p95 < 2s. Failure or timeout → brief synthesis proceeds with `hindsight_recalled=false` flag in research_brief metadata; structlog WARNING `research.hindsight.recall_failed`; no block of brief synthesis (graceful degradation invariant)
