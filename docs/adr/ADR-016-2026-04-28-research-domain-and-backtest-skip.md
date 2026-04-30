---
adr: 016
date: 2026-04-28
status: accepted
decided-by: Arturo Ramírez (arturo6ramirez@gmail.com)
tags: [research, backtest, scope, mvp]
---

# ADR-016 — Research domain addition + backtest scope skip

## Status

**Accepted** (Gate A amendment 2026-04-28). This ADR is self-contained — the decision is fully captured here at Gate B time, no slice needs to flesh it out further.

## Context

The original PRD (Gate A, 2026-04-27) included **Backtest & Research** as bounded context with FR6-FR10 covering historical replay + strategy validation. Two days later, during the architecture phase (Gate B preparation), Arturo questioned the value of backtesting for the MVP:

- Quote (2026-04-28): *"skippeamos y no hace falta gate, quien quiera probar live puede hacerlo, es a riesgo del usuario"*.

Three options were considered (BMAD party-mode roundtable):

- **A — Keep backtest**: ship the full PRD as-is. Pro: full functionality. Con: substantial implementation cost (replay engine, timeseries cache, no-lookahead enforcement) for what is, in practice, a check that paper-trading already performs.
- **B — Defer backtest to v2**: ship MVP without backtest, plan to add it post-launch. Pro: faster MVP. Con: leaves a gap that paper-trading partially covers.
- **C — Skip backtest entirely**: drop FR6-FR10 from the PRD, do NOT plan to add it. Operators rehearse via paper trading; "live at your own risk" if you skip paper. Pro: simplest scope, smallest surface. Con: no backtest means strategy parameter tuning relies on paper trading + live observation alone.

The PRD was simultaneously being expanded with a much larger **Research bounded context** (FR57-FR79: corporate filings ingestion, macro indicators, news catalysts, analyst ratings, brief synthesis with 5 methodologies, Hindsight integration). The combination of "drop backtest + add research" reframed the MVP scope around *decision support* (research-driven trade proposals) rather than *historical validation* (backtest-driven strategy tuning).

## Decision

**Adopt option C**. The research bounded context replaces the backtest bounded context. Specifically:

- **Removed**: FR6-FR10 (backtest), NFR-P6 (backtest performance), NFR-O6 (backtest observability), `contexts/backtest/` directory, `replay_cache.py` mode-aware logic, "backtest" mode from the profile enum (now `paper` / `live` only).
- **Added**: FR57-FR81 (research: 25 new FRs), NFR-P9 (research brief refresh latency), NFR-O8 (research citation chain), NFR-I8 (Hindsight recall latency + graceful degradation), Research bounded context with bitemporal `research_facts` (ADR-014), OpenBB SDK sidecar (ADR-015), 4-tier scrape ladder (ADR-017), 5 methodology profiles (3-pillar / CANSLIM / Magic Formula / QARP / Multi-factor), Hindsight integration (FR80 write always-on + FR81 recall togglable per-tenant).
- **Paper-trading rule relaxed**: AGENTS.md §7 Override 1 — paper trading is **strongly recommended** but not hard-blocked. Operators may go directly to live via `--confirm-live --i-understand-the-risks` flag. The CLI emits a WARNING with risk acknowledgment text.

## Consequences

**Positive**:

- MVP scope drops a substantial code surface (~3000 LOC estimated for backtest engine + cache + replay). Slice count stays at 20 even with research domain addition because backtest's removal counterbalances research's growth.
- Operator's mental model is simpler: paper-trading rehearses live; there is no third "backtest" mode to understand.
- Research domain offers far more user value: the bot can propose *why* a trade makes sense (cited research) rather than only *what* (mechanical strategy output).

**Negative / accepted trade-offs**:

- Strategy parameter tuning has no historical-replay validation. Operators must tune via paper trading and accept that paper performance ≠ live performance perfectly.
- "Live at your own risk" is genuinely risky for novice operators. AGENTS.md §7 Override 1 mitigates with the WARNING but does not block.
- v2 may revive backtest if user feedback demands it. The research domain's bitemporal schema is *bitemporal-friendly* for backtest synthesis (point-in-time queries), so reviving backtest in v2 is feasible but not pre-built.

## Cross-references

- `docs/prd.md` — FR57-FR81 (research) + Removed Section "Backtest & Research".
- `docs/architecture-decisions.md` — §"Research bounded context" + critical-path "research_brief synthesis with Hindsight integration".
- `docs/hitl-gates-log.md` — Gate A amendment entry 2026-04-28 with full decision rationale.
- ADR-014 (bitemporal research_facts) — schema this ADR enables.
- ADR-015 (OpenBB sidecar) — license boundary this ADR introduces.
- ADR-017 (scrape ladder) — research data-source resilience this ADR introduces.
- `docs/research/data-sources-catalogue.md` — 38 sources × 12 categories researched 2026-04-28.

## Notes

- 7 open questions resolved 2026-04-28 (see `docs/hitl-gates-log.md` Gate A amendment): OpenBB sidecar from day 1, €0 paid-tier baseline, 3-tier point-in-time policy (A native / B snapshot / C bootstrap), bitemporal knowledge schema, GDELT BigQuery free tier with budget cap, Form 4 EDGAR + OpenInsider both included, ESG via yfinance.sustainability single-source.
- 4 critical caveats acknowledged: yfinance grey-area, OpenBB AGPL trap (mitigated via sidecar), SEC Climate Rule withdrawn 2025-03 (ESG single-source), captcha-solver paid services available for tier-4 scrape.
