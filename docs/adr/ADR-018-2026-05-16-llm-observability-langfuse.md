---
adr: 018
date: 2026-05-16
status: accepted
decided-by: Arturo Ramírez (arturo6ramirez@gmail.com)
tags: [observability, llm, langfuse, eligia-integration]
---

# ADR-018 — LLM observability via Langfuse SaaS, shared with ELIGIA stack

## Status

**Accepted**. Implemented in slice `llm-observability-and-signals` (PR #194).

## Context

Iguanatrader makes LLM calls in four flows:

1. **Research synthesis** (`Synthesizer.synthesize` → `AnthropicLLMClient.complete`) — multi-step pipeline writing research briefs.
2. **Proposal explainer** (`POST /api/v1/proposals/{id}/explain`) — human-readable narrative for a strategy-emitted proposal.
3. **Proposal risk review** (`POST /api/v1/proposals/{id}/risk-review`) — informational risk score + flags.
4. **Trade journal** (`POST /api/v1/trades/{id}/journal`) — post-mortem narrative after a trade closes.

Pre-slice O1 shipped a `@cost_meter` decorator that persists `ApiCostEvent` per call in the iguanatrader DB. That covers **tenant billing** (who spent what, attributable per-tenant). It does NOT cover cross-stack observability: when a prompt regresses, when a model swap blows out costs, when error rates spike — `@cost_meter` produces a per-row DB log, not aggregated dashboards.

The ELIGIA stack (Hermes / Paperclip / Hindsight / RAG / etc.) already runs against **Langfuse Cloud SaaS** with shared credentials in `eligia-core/secrets/secrets.env`. Every service in that stack publishes observations tagged with `metadata.consumer` + `metadata.application`; the ELIGIA dashboard aggregates them into widgets (cost-by-consumer, top-models, error-rate, traces-today).

## Decision

1. **Use Langfuse SaaS (Cloud), not self-hosted.** The ELIGIA stack already uses it; sharing the same project + creds means iguanatrader appears as a new consumer in the existing dashboard rather than requiring a parallel infra stack. Migration to self-hosted is one env-var change if SaaS terms change.

2. **Bypass the ELIGIA LiteLLM proxy.** Iguanatrader uses the Anthropic Python SDK directly (per slice `deployment-foundation`); routing through LiteLLM would mean a network hop + a runtime dep on the ELIGIA cluster being reachable. We instead use the **Langfuse Python SDK directly** with the shared credentials.

3. **`@cost_meter` and Langfuse coexist.** Different audiences, no functional overlap:
   - `@cost_meter` → per-tenant `ApiCostEvent` in DB → drives **iguanatrader's internal tenant billing**.
   - Langfuse → SaaS export with prompt/response/tokens/cost → drives **the cross-stack ELIGIA dashboard**.
   Both fire on every LLM call.

4. **Canonical tag shape** for every observation:
   - `metadata.consumer = "iguanatrader"` (fixed literal — one row in the dashboard's `Top by Consumer` widget).
   - `metadata.application = "iguanatrader-{module}"` (one per flow: `synthesis` / `explainer` / `risk` / `journal`).
   - `metadata.env = paper|live|dev` (from `IGUANATRADER_ENV`).
   - `metadata.tenant_id = <UUID>` when the call is in a tenant request scope (iguanatrader-specific drill-down inside Langfuse Cloud UI).
   - Per dashboard backend resolution chain (`eligia-core/dashboard/backend/routes/langfuse.py::_obs_metadata_tag`): observation-level metadata wins, parent trace fallback, then `model_group` suffix derivation (the last only fires for LiteLLM-routed calls — iguanatrader does NOT route via LiteLLM, so we must always set the observation metadata directly).

5. **Wrapper module** (`contexts/observability/langfuse_client.py`) is the single point of contact with the SDK. Reasons:
   - Optional dep at runtime: missing creds → no-op stand-ins (`_NoOpTrace` / `_NoOpGeneration`) keep call-sites unconditional.
   - Tag-shape enforcement: every span gets the canonical metadata in one place.
   - Replaceable: swapping to self-hosted Langfuse or to OpenTelemetry + Tempo is a single-file change.

6. **Model selection per flow** (cost / latency / quality trade-off):
   - Synthesis: caller chooses (R5 wiring) — usually sonnet for the multi-step pipeline.
   - Explainer: `claude-3-5-haiku` (restatement task; haiku is sufficient).
   - Risk review: `claude-3-5-sonnet` (multi-attribute reasoning).
   - Journal: `claude-3-5-haiku` (narrative summarisation).

## Consequences

**Positive**:

- One source of truth for LLM observability across Arturo's whole AI stack. Cost spikes / prompt regressions / error storms surface in one place.
- New iguanatrader LLM call-sites land with one decorator + the application tag; everything else (cost computation, error counting, dashboard aggregation) is automatic.
- Tenant billing remains internal — Langfuse SaaS never sees `tenant_id` as a billing primary; it's a drill-down label only.

**Negative**:

- Iguanatrader becomes dependent on Langfuse Cloud's availability for telemetry visibility. **NOT a runtime dependency** — the wrapper falls through to no-ops on SDK failure, so the API keeps serving LLM calls; we just lose visibility until it recovers.
- Free-tier rate-limit of ~100 req/min on Langfuse's public API affects the **ELIGIA dashboard** read path (already mitigated by their 1h cache). Iguanatrader's publish path is independent.
- Prompt + response bodies leave iguanatrader's runtime. The Langfuse Cloud project is EU-hosted; this is acceptable for non-PII trading research data. **Do NOT enable Langfuse on flows that touch PII** (none today; flagged for future review when authentication / KYC flows land).

**Carry-forward** (not in this slice):

- Add a Grafana alert when `metadata.application = iguanatrader-*` calls have `level=ERROR` rate >5% over 10 minutes.
- Wire the `eligia-core/dashboard/openspec/changes/add-cost-by-tag-widget` UNTAGGED_LABEL row to alert when iguanatrader's untagged share rises above 0% (a real bug — every iguanatrader call should be tagged).

## Cross-references

- `docs/gotchas.md` §83 — Langfuse + `@cost_meter` dual-tracking pattern.
- `eligia-core/dashboard/backend/routes/langfuse.py` — dashboard backend resolution chain.
- `eligia-core/helm/eligia-stack/values.yaml` — Langfuse env wiring for ELIGIA services.
- `apps/api/src/iguanatrader/contexts/observability/langfuse_client.py` — the wrapper.
