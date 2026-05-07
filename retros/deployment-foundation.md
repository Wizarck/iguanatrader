# Retrospective: deployment-foundation (Wave 4 keystone)

- **Authored**: forward-authored 2026-05-07 per [.ai-playbook/specs/runbook-bmad-openspec.md §4.1](../.ai-playbook/specs/runbook-bmad-openspec.md#4-retrospective-cadence) — fields filled at archive time.
- **PR**: TBD (slice/deployment-foundation branch open)
- **Archive path**: `openspec/changes/archive/<archive-date>-deployment-foundation/` (set on archive)
- **Lines shipped**: ~1,400 LoC src + ~900 LoC tests + ~600 LoC helm chart + ~250 LoC runbook (preliminary count; finalise on archive).

## What worked

- _(fill on archive)_

## What didn't

- _(fill on archive — pre-flag candidates: poetry CLI hangs in agent harness so 1.7-1.9 deferred-to-operator; harness needs --no-tty mode for poetry+pip)_

## Lessons

- _(fill on archive)_

## Carry-forward to next change

- **W2 frontend deploy** — extend `helm/iguanatrader-stack/templates/` with `deployment-web.yaml` once the Svelte 5 frontend ships.
- **2Captcha tier-4 wiring** — separate post-MVP slice; gated by operator opt-in budget.
- **Production observability stack** (`production-otel`) — OTLP exporters + Grafana dashboards.
- **Multi-region failover** (v2 SaaS).

## Pattern usage (deployment-foundation IS the canonical example)

This slice is the **canonical instance** of the pattern documented in
[.ai-playbook/specs/protocol-fake-deferred-install.md](../.ai-playbook/specs/protocol-fake-deferred-install.md). Five Wave-3 fakes
swap to production adapters in one slice:

| Wave-3 slice | Protocol | Fake (kept for tests) | Production adapter |
|---|---|---|---|
| R5 research-brief-synthesis | `LLMClient` | `FakeLLMClient` | `AnthropicLLMClient` |
| T2 trading-broker | `IBClient` | `tests/_fakes/ib_async_fake.py` | `IbAsyncIBClient` |
| O2 orchestration-scheduler-routines | `SchedulerProtocol` | `InMemoryScheduler` | `APSchedulerAdapter` |
| R3 research-bitemporal-schema (Tier-2) | `TierFn` (function-shape) | `fetch_tier2_stub` | `fetch_tier2_playwright` |
| O2 (FR44 follow-up) | (digest dict shape) | (markdown placeholder) | `render_weekly_review_pdf` |

The chart + Fleet GitRepo + secret-rotation runbook complete the
**deploy-time HITL gate** documented in
[.ai-playbook/specs/multi-layer-defense-single-operator.md](../.ai-playbook/specs/multi-layer-defense-single-operator.md).

## Acceptance smoke (operator-driven, post-merge)

Per [.ai-playbook/runbooks/release.md §10](../.ai-playbook/specs/release-management.md), each adapter is exercised once
against its real-SDK boundary BEFORE the slice merges. Track in
`tasks.md` §8:

- [ ] §8.1 k3d cluster boot (helm install → all pods READY ≤90s)
- [ ] §8.2.A Anthropic SDK round-trip (test API key)
- [ ] §8.2.B IBKR paper account connect → place dummy order → reconcile
- [ ] §8.2.C APScheduler persists job across restart
- [ ] §8.2.D Playwright fetches example.com
- [ ] §8.2.E weekly_review_pdf opens in viewer
- [ ] §8.3 secret-rotation runbook end-to-end
- [ ] §8.4 Fleet GitRepo CI verification

When all 8 boxes are checked, archive the change + finalise the
"What worked / What didn't / Lessons" sections of this retro.
