---
type: roadmap
project: iguanatrader
schema_version: 1
created: 2026-05-16
updated: 2026-05-16
purpose: Forward-looking slice plan for the LLM-features track post slice `llm-observability-and-signals` (PR #194). Lean by design; each slice gets a formal OpenSpec change when it starts.
---

# Roadmap — LLM features track

Single source of truth for the LLM-driven feature work that follows PR #194. Each row below corresponds to a future slice; when work begins, open the formal proposal via `/opsx:propose <slice-id>` and link the resulting `openspec/changes/<name>/` directory back here.

**Track owner**: Arturo Ramírez.
**Scope**: auto-triggers for the three #194 endpoints (explainer / risk-review / journal) + Hindsight write-back + MCP server exposing iguanatrader to Hermes.

## Status legend

- `proposed` — described here, no implementation work
- `in-progress` — OpenSpec change exists, branch open
- `merged` — code on main
- `deployed` — running in production on the VPS
- `parked` — descoped or deferred indefinitely

---

## A0 — LLM budget cap (per-tenant, configurable)

**Status**: proposed
**Prereq for**: A1, A2, A3, B (any slice that triggers LLM calls without operator interaction)
**Estimated**: ~200 LOC + 1 migration (0019)

### Why first

A1/A2/A3 each add automatic LLM invocations behind user-facing events. Without a hard cap, a misbehaving strategy or a runaway event handler could rack up Anthropic charges silently. A0 lands the safety net before automation lands.

### Components

- Migration 0019: extend tenant settings with `monthly_llm_budget_usd NUMERIC(10,2) NULL`. NULL = no cap (current behaviour preserved).
- Extend `BudgetGuard` ([contexts/observability/budget.py](../apps/api/src/iguanatrader/contexts/observability/budget.py)) to:
  - Sum `ApiCostEvent.cost_usd` for current month for the calling tenant.
  - Block the call (raise `BudgetExceededError`) when the running total + the projected call cost exceeds the cap.
  - Emit `observability.budget.warning` structlog event at 80% utilisation.
- DTO + route: extend `GET /api/v1/settings` payload + `PUT /api/v1/settings` to allow editing (admin-only role).
- Decision (capture in ADR-019): which flows respect the cap. Initial proposal: synthesis + explainer + risk-review + journal — all of them. Trading-signal proper (strategies) does not invoke LLM so it is unaffected.

### Open questions

- Should the cap reset on the 1st of each calendar month, or 30 days rolling? Calendar-month is simpler; rolling is more conservative. Decide in the OpenSpec change.
- Behaviour when cap is hit during an auto-trigger (A1/A2/A3): degrade silently (log + skip the LLM step, keep the rest of the flow) vs. block the proposal/trade entirely. Proposal: degrade silently — the LLM step is informational; missing it is acceptable.

---

## A3 — Auto-journal on trade-close + Hindsight retain

**Status**: proposed
**Prereq**: A0
**Estimated**: ~180 LOC, no migration

### Why this is the keystone slice

This is the slice that closes the personal-AI feedback loop: every trade that closes leaves a narrative both in iguanatrader's DB AND in the Hindsight bank. Future research synthesis runs (`Synthesizer.synthesize`) already accept `narrative_context` populated from Hindsight recall, so the next synthesis automatically benefits from the lessons of past trades. Without A3, journals are write-only archives.

### Components

- Bus handler for `TradeClosed` event (event already published by `TradingService.close_trade_handler` post-fill reconciliation).
- Handler calls `TradeJournalWriter.write()` → persists `narrative` on `trades.journal_narrative` (column shipped in migration 0018).
- Same handler additionally calls `hindsight_client.retain(bank="iguanatrader", kind="trade_journal", content=narrative, metadata={symbol, side, realised_pnl, exit_reason, mode, closed_at})`.
- Best-effort semantics: LLM failure → trade stays closed, journal column NULL, no Hindsight write. Hindsight failure → DB column populated, log warning, no retry. Never rolls back the trade close.
- Langfuse application tag remains `iguanatrader-journal` (unchanged from #194 manual endpoint).
- Tests: mock `TradeClosed` event, assert handler dispatches both writes; tests for each failure branch.

### Hindsight integration touchpoints

- Bank: `iguanatrader` (already provisioned per [AGENTS.md](../AGENTS.md) §5 capability map).
- Retain script today is `python .ai-playbook/scripts/retain_memory.py --bank iguanatrader --kind <kind> --content "…" --why "…"` (manual). A3 implements an in-process Python client equivalent.
- Recall consumers already exist: the synthesizer's `narrative_context` parameter (slice R6). Once journals start landing in Hindsight, recall will surface them automatically.

---

## A1 — Auto-explain on dispatch

**Status**: proposed
**Prereq**: A0
**Estimated**: ~150 LOC, no migration

### What

When `ChannelDispatcher` ([contexts/approval/dispatcher.py](../apps/api/src/iguanatrader/contexts/approval/dispatcher.py)) fires the webhook to Hermes for a new proposal, it first invokes `ProposalExplainerService` in-process (not HTTP) and includes the narrative in the webhook payload. Hermes embeds the narrative in the Telegram/WhatsApp message instead of sending raw metadata.

### Components

- `ChannelDispatcher` constructor accepts an injected `ProposalExplainerService` (currently it has no LLM dependency).
- New field on the Hermes webhook payload: `narrative: str`, `narrative_model: str`, `narrative_generated_at: datetime`.
- A0 budget check: if `BudgetGuard` would block the explainer call, log info and skip the field (Hermes payload keeps the raw metadata only).
- Coordinating change in `eligia-core`: Hermes template for trade-proposal notifications consumes `narrative` when present, otherwise falls back to the current raw template. Tracked separately as `eligia-core` work item.
- Tests: dispatcher unit tests with explainer stub; integration test of the webhook payload shape.

### Cost

~$0.001 per proposal (Claude 4.5 Haiku, ~500 tokens output). At paper-trading volume this is negligible; A0 backstop covers a runaway scenario.

---

## A2 — Auto-risk-review on high-confidence proposals

**Status**: proposed
**Prereq**: A0, A1
**Estimated**: ~250 LOC + 1 migration (0020)

### What

When a `ProposalCreated` event fires and the proposal's `confidence_score > threshold` (default 0.8, configurable in tenant settings), the handler invokes `ProposalRiskAssessor` and persists the structured result back on the proposal row. A1's dispatcher then includes the risk score + flags in the Hermes message.

### Components

- Migration 0020: add `risk_score INT NULL, risk_flags JSON NULL, risk_rationale TEXT NULL, risk_generated_at TIMESTAMP NULL, risk_model VARCHAR(64) NULL` to `trade_proposals`.
- Whitelist extension on the append-only listener for the five new columns.
- Tenant settings: `risk_review_confidence_threshold NUMERIC(3,2) NULL` (default 0.80, NULL means disable auto-risk-review entirely).
- Handler of `ProposalCreated` invokes `ProposalRiskAssessor` when threshold met.
- Best-effort: parse errors / network failures / budget exceeded → log warning, proposal continues without risk fields. Hermes message renders without risk section when fields are NULL.
- A1's dispatcher (already shipped by that slice) reads `risk_score` + `risk_flags` and embeds them in the message template.
- Coordinating change in `eligia-core`: Hermes template extension for risk fields.

### Cost

~$0.02 per high-confidence proposal (Claude 4.6 Sonnet, ~1500 tokens). Per A0, capped per tenant.

---

## B — iguanatrader-mcp server (exposed to Hermes)

**Status**: in-progress (scaffolding + action tools shipped; JSON-RPC framing + Hermes registration pending — see [B1](#b1--mcp-json-rpc-framing--hermes-registration) below).
**Prereq**: A2 (so risk-review fields exist for the MCP to read)
**Estimated**: ~600 LOC, no new image

### Shipped (as of 2026-05-18)

- Read-only resources at `/api/v1/mcp/{trades,briefs,portfolio}` (PR #197 et al).
- Action tools `explain` / `risk` / `journal` / `synthesize` at `/api/v1/mcp/tools/{name}` (PR #255).
- Tool catalogue at `GET /api/v1/mcp/tools`.
- Token gen + SOPS storage (PR #260: `IGUANATRADER_MCP_TOKEN` in `paper.env.enc` + `live.env.enc`, wired through `docker-compose.mvp.yml`).
- Frontend `/mcp-tools` page showing catalogue + Hermes config snippet.

### Pending

`IGUANATRADER_MCP_TENANT_SLUG` is still empty in SOPS — operator must populate it to match the bootstrapped tenant before the routes leave 503. Hermes-side registration in `eligia-core/mcp-servers.yaml` not yet wired.

### What

Mount an MCP server at `/mcp` in the existing iguanatrader-api FastAPI process. Hermes registers it in its `mcp-servers.yaml` and can then query iguanatrader conversationally over Telegram/WhatsApp ("show me my last trade's journal", "what's the risk review on proposal X?", "summarise SPY's latest brief").

### Tech decisions (resolved in this conversation, locked here)

- **Auth**: shared static bearer token via env var on both ends (`IGUANATRADER_MCP_TOKEN`). Constant-time compare, no rotation, no JWT.
- **Tenant resolution**: env var `IGUANATRADER_MCP_TENANT_SLUG` resolved once at server start; every MCP query runs inside `with_tenant_context(<resolved tenant_id>)`. Reuses the existing tenant listener.
- **Deployable**: same FastAPI process — `app.include_router(mcp_router, prefix="/mcp")`. No new image, no new Dockerfile.

### Surface

**Resources (read-only)**:
- `iguanatrader://trades/{trade_id}` → trade row + journal narrative (if persisted)
- `iguanatrader://trades?since=YYYY-MM-DD&symbol=X` → filtered list
- `iguanatrader://proposals/{proposal_id}` → proposal + explain + risk (if persisted)
- `iguanatrader://proposals?state=pending` → list of pending proposals
- `iguanatrader://briefs/{symbol}/latest` → most recent research brief for symbol
- `iguanatrader://portfolio` → latest equity snapshot + open positions

**Tools (actions, respect A0 budget)**:
- `iguanatrader.explain_proposal(id)` — force regeneration of narrative
- `iguanatrader.risk_review(id)` — force regeneration of risk assessment
- `iguanatrader.journal_trade(id, regenerate=False)` — force regeneration of journal
- `iguanatrader.synthesize_brief(symbol, methodology="three_pillar")` — on-demand synthesis

Explicit out-of-scope for v1:
- `approve_proposal` — too autonomous, requires separate trust conversation
- `place_order` — same
- Anything that touches IBKR directly

### Coordinating changes outside iguanatrader

- `eligia-core/mcp-servers.yaml`: add `iguanatrader` entry pointing to internal Docker URL + bearer token (SOPS-encrypted).
- `eligia-core/secrets/secrets.env`: add `IGUANATRADER_MCP_TOKEN=<random hex>` SOPS-encrypted.
- Hermes config reload to pick up the new MCP.

---

## B1 — MCP JSON-RPC framing + Hermes registration

**Status**: proposed
**Prereq**: B (scaffolding shipped) + a Hermes consumer that needs canonical MCP semantics.
**Estimated**: ~300 LOC; depends on upstream lib choice.

### Why a follow-up

The B routes ship as REST-shaped POSTs (`/api/v1/mcp/tools/{name}` body = input JSON, response = output JSON). That is sufficient for a hand-rolled Hermes adapter but is **not** spec-compliant MCP — Anthropic's MCP wire protocol uses JSON-RPC 2.0 over stdio or SSE. Until the JSON-RPC framing lands, off-the-shelf MCP clients (Claude Desktop, Cursor MCP, Inspector) cannot consume iguanatrader.

### Decisions to lock

- **Lib**: `fastmcp` (FastAPI-native) vs `mcp` (official Python SDK). `fastmcp` lets us keep the existing FastAPI process; `mcp` SDK is canonical but biases towards stdio transport.
- **Transport**: SSE (over the same compose-network bearer-token envelope) vs Streamable HTTP. SSE is simpler for a single long-lived consumer like Hermes; Streamable HTTP is the newer recommendation.
- **Backwards compatibility**: keep the existing REST routes alive during the transition, or hard-cut to JSON-RPC. Soft transition is safer for the `/mcp-tools` page which currently consumes the REST catalogue.

### Out of scope

- Multi-tenant MCP — `IGUANATRADER_MCP_TENANT_SLUG` stays an env-derived single-tenant resolver. Multi-tenant would need per-token tenant resolution.

---

## Tracking flow

```
docs/roadmap-llm-features.md (this file)   ← global view, always current
            │
            │ "starting A0"
            ▼
/opsx:propose a0-llm-budget-cap
            │
            │ → openspec/changes/a0-llm-budget-cap/{proposal,design,tasks}.md
            │
            ▼
branch a0-llm-budget-cap → PR → CI → merge → deploy
            │
            ▼
This file: A0 row updated `proposed → in-progress → merged → deployed`
```

When each slice closes, update its status row + add a one-line summary of what actually shipped (drift between proposal and reality is fine; the row captures reality).

## Out of scope for this track (future, not promised)

- Multi-LLM routing (OpenAI / Gemini): only Anthropic SDK today; no plan to add until a concrete need.
- LLM-driven trade execution: the LLM is informational/explanatory only. Strategies remain deterministic.
- Real-time streaming responses: all endpoints are request-response. Streaming via SSE is a UI-side concern, not LLM-side.
- LangGraph orchestration of multi-step LLM workflows: today the synthesizer pipeline is the only multi-step LLM flow, and it's a hand-coded sync pipeline. No plan to migrate to a graph framework.
