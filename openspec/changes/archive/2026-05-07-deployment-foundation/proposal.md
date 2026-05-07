## Why

Six Wave-3 slices (R5, T2, R3, R3-Tier-2/3/4, R3-OpenInsider/Finviz, T2 fake-only-no-real-broker, O2 SchedulerProtocol) ship Protocol + InTreeFake adapters with their production-SDK wiring **deferred to a deployment-foundation slice**. Each retro carries a "production wiring deferred to deployment slice" carry-forward — seven retros consecutively flagged the same pattern. **Without this slice, the bot is a collection of fakes with no real broker / LLM / scheduler / scraper.**

This slice installs the deferred deps + wires the Protocol → real-SDK swap for each. Pure dep + wiring + secret-handling slice — minimal new code. The bulk is `pyproject.toml` additions, secret-handling primitives, and per-Protocol adapter shims that compose `@cost_meter` decorator over each SDK.

## What Changes

- **Deps added to `apps/api/pyproject.toml`**:
  - `anthropic = "^0.40"` — production LLM client. Wraps in `AnthropicLLMClient` adapter that satisfies R5's `LLMClient` Protocol.
  - `ib_async = "^1.0"` — production IBKR SDK. Wraps in `IbAsyncIBClient` adapter that satisfies T2's `IBClient` Protocol.
  - `apscheduler = "^3.10"` — production scheduler. Wraps in `APSchedulerAdapter` that satisfies O2's `SchedulerProtocol`.
  - `playwright = "^1.45"` — production Tier-2 scrape. Wires R3's `fetch_tier2_stub` → `fetch_tier2_playwright`.
  - `camoufox = "^0.4"` — production Tier-3 scrape (Camoufox-MCP via stdio).
  - `reportlab = "^4.0"` — weekly review PDF generator (FR44).
- **`AnthropicLLMClient`** at `apps/api/src/iguanatrader/contexts/research/synthesis/anthropic_client.py` — wraps `anthropic.AsyncAnthropic().messages.create()` with `@cost_meter("anthropic", model)` decorator from O1. Reads `ANTHROPIC_API_KEY` from SOPS-encrypted env.
- **`IbAsyncIBClient`** at `apps/api/src/iguanatrader/contexts/trading/brokers/ib_async_client.py` — thin `ib_async.IB` adapter satisfying `IBClient` Protocol. No `@cost_meter` (broker calls are unbilled).
- **`APSchedulerAdapter`** at `apps/api/src/iguanatrader/contexts/orchestration/apscheduler_adapter.py` — wraps `AsyncIOScheduler(jobstores=SQLAlchemyJobStore, timezone=ZoneInfo("America/New_York"))` satisfying `SchedulerProtocol`.
- **Tier-2 Playwright** at `apps/api/src/iguanatrader/contexts/research/scraping/tier2_playwright.py` — replaces `fetch_tier2_stub` with `chromium.launch()` + page navigation + body extraction.
- **`weekly_review_pdf.py`** at `apps/api/src/iguanatrader/contexts/orchestration/weekly_review_pdf.py` — reportlab-based PDF generator consuming the digest payload from `OrchestrationService.run_routine("weekly_review")`.
- **Helm chart** at `helm/iguanatrader-stack/` — Chart.yaml + values.yaml + templates/ for: api Deployment + openbb-sidecar Deployment + frontend Deployment + litestream sidecar + Service + Ingress + ConfigMap (env) + Secret (SOPS-decrypted at deploy time). Mirrors the `eligia-core/helm/eligia-stack/` pattern from ADR-015.
- **Fleet GitRepo** at `deploy/fleet-gitrepo.yaml` for Rancher Fleet GitOps deployment to k3s.
- **Secret rotation runbook** at `docs/runbooks/secret-rotation.md` — operator procedure for rotating Anthropic / IBKR / 2Captcha keys via SOPS.
- **Deferred from this slice**: 2Captcha wiring (Tier-4) — operator-driven opt-in, separate post-MVP slice.

## Capabilities

- All Wave-3 capabilities transition from "Protocol + Fake" to "Protocol + ProductionAdapter". No new capabilities; pure-wiring slice.

## Impact

- 6 deps added. License-boundary check verifies all are MIT / Apache / BSD compatible (anthropic Python SDK MIT, ib_async MIT, APScheduler MIT, Playwright Apache-2.0, Camoufox MIT, reportlab BSD).
- Secret-handling for `ANTHROPIC_API_KEY` + `IBKR_USERNAME`/`PASSWORD` + `TWS_PORT` + (future) `TWOCAPTCHA_API_KEY` via existing SOPS pattern.
- Helm chart + Fleet GitRepo enable production deploy to existing k3s + Rancher topology.
- 6 production-adapter classes added; 6 corresponding "production wiring lands here" deferred markers from prior retros are resolved.

## Prerequisites

All Wave-3 slices archived (R1-R5 + T1-T3 + K1/P1 + O1/O2 + W1). T4 (`trading-routes-and-daemon`) optional but recommended — without T4 the daemon entrypoint has no orchestration consuming the production adapters.

## Out of scope

- 2Captcha tier-4 scrape wiring (separate post-MVP slice; needs operator opt-in budget).
- Production observability stack (OTLP exporters, Grafana dashboards) — separate `production-otel` slice.
- Multi-region failover (v2 SaaS).
- IBKR live-mode credentials handling beyond paper (operator-driven; documented in runbook only).

## Acceptance

- All 6 Protocol → ProductionAdapter swaps land + their construction tested with mocked secret env.
- `helm install iguanatrader helm/iguanatrader-stack/` boots a working dev cluster locally (k3d) with all components reaching READY.
- Fleet GitRepo CI verifies the Helm chart against the same k3d locally before merge.
- Secret rotation runbook is followed end-to-end against a fresh SOPS keyring without code changes.
- License-boundary CI verifies all 6 new deps are non-AGPL (or correctly isolated to the AGPL openbb-sidecar boundary if any inherit AGPL transitively).
