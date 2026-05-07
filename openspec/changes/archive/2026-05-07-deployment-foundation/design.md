# Design — deployment-foundation

> **Purpose**: codify the Protocol → ProductionAdapter swap pattern for 6 Wave-3 deferred-install Protocols (LLMClient, IBClient, SchedulerProtocol, ScrapeTier2Port, weekly-review PDF, Helm/k3s deploy topology) and the secret-handling primitives that make them runnable in a Rancher-Fleet-managed k3s cluster.
>
> **Pattern reference**: [.ai-playbook/specs/protocol-fake-deferred-install.md](../../../.ai-playbook/specs/protocol-fake-deferred-install.md) — codified in v0.11.0 from this exact pattern, recurring across 6 Wave-3 slices. This slice IS the canonical "deployment-foundation slice" the spec describes.

## 1. Architecture overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ apps/api  (FastAPI service, single asyncio loop, sqlite via litestream)      │
│                                                                              │
│   ┌──────────────────────┐    ┌──────────────────────┐                      │
│   │ research-synthesis   │    │ trading              │                      │
│   │ LLMClient port       │◀───│ IBClient port        │                      │
│   │   FakeLLMClient      │    │   FakeIBClient       │                      │
│   │   AnthropicLLMClient │    │   IbAsyncIBClient    │                      │
│   └──────────────────────┘    └──────────────────────┘                      │
│            │                            │                                   │
│            ▼ @cost_meter                ▼ heartbeat-mixin                   │
│   ┌──────────────────────┐    ┌──────────────────────┐                      │
│   │ orchestration        │    │ research-scraping    │                      │
│   │ SchedulerProtocol    │    │ ScrapeTier2Port      │                      │
│   │   InMemoryScheduler  │    │   Tier2StubFake      │                      │
│   │   APSchedulerAdapter │    │   Tier2PlaywrightCli │                      │
│   └──────────────────────┘    └──────────────────────┘                      │
│            │                            │                                   │
│            ▼ SQLAlchemyJobStore         ▼ chromium subprocess               │
│                                                                              │
│   weekly_review_pdf.py (reportlab) ◀── OrchestrationService.run_routine()   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                              ▲
                              │ secret env (SOPS-decrypted at deploy)
                              │
┌─────────────────────────────────────────────────────────────────────────────┐
│ helm/iguanatrader-stack/  (Rancher Fleet GitRepo manifest at deploy/)        │
│                                                                              │
│   Chart.yaml                                                                 │
│   values.yaml          (defaults; per-env override via Fleet bundle)         │
│   templates/                                                                 │
│     deployment-api.yaml          (api pod; secret env from k8s Secret)       │
│     deployment-openbb-sidecar.yaml  (AGPL boundary; separate pod)            │
│     deployment-web.yaml          (Svelte 5 frontend)                         │
│     statefulset-litestream.yaml  (sqlite replication sidecar to S3)          │
│     service.yaml + ingress.yaml                                              │
│     configmap-env.yaml           (non-secret env)                            │
│     secret-sops.yaml             (SOPS-encrypted; sops-secrets-operator)     │
│                                                                              │
│ deploy/                                                                      │
│   fleet-gitrepo.yaml   (one GitRepo CR pointing at this repo's helm/)        │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 2. Per-Protocol adapter specifications

Each adapter follows the canonical pattern from [protocol-fake-deferred-install.md §4](../../../.ai-playbook/specs/protocol-fake-deferred-install.md#4-the-four-artefacts-of-the-pattern):

### 2.1 `AnthropicLLMClient`

- **File**: `apps/api/src/iguanatrader/contexts/research/synthesis/anthropic_client.py`
- **Protocol**: `LLMClient` (defined in `llm_client.py` from R5)
- **SDK**: `anthropic ^0.40` (MIT license)
- **Secret**: `ANTHROPIC_API_KEY` from SOPS-decrypted env
- **Decorator**: `@cost_meter("anthropic", model=...)` from O1
- **Construction**: `AnthropicLLMClient(api_key=os.environ["ANTHROPIC_API_KEY"])` at app composition root.
- **Method**: `async def generate(prompt: str, *, model: str, max_tokens: int, temperature: float = 0.0) -> str`
- **SDK call**: `self._client.messages.create(model=model, max_tokens=max_tokens, temperature=temperature, messages=[{"role": "user", "content": prompt}])`
- **Return**: `msg.content[0].text` — extract first text block from response.
- **Error mapping**: `anthropic.APIError` → existing `LLMClientError` (defined in R5); preserve retry semantics already in research-synthesis pipeline.

### 2.2 `IbAsyncIBClient`

- **File**: `apps/api/src/iguanatrader/contexts/trading/brokers/ib_async_client.py`
- **Protocol**: `IBClient` (defined in `client_protocol.py` from T2)
- **SDK**: `ib_async ^1.0` (MIT license)
- **Secrets**: `IBKR_USERNAME`, `IBKR_PASSWORD`, `TWS_PORT` from SOPS env
- **Decorator**: NO `@cost_meter` (broker calls are unbilled per O1 spec).
- **Construction**: `IbAsyncIBClient(host=os.environ.get("IBKR_HOST","127.0.0.1"), port=int(os.environ["TWS_PORT"]), client_id=int(os.environ.get("IB_CLIENT_ID","1")))`
- **Composition**: extends `HeartbeatMixin` from T2 (5-attempt ceiling, canonical backoff `[3, 6, 12, 24, 48]` from shared-primitives).
- **Methods**: `connect`, `disconnect`, `is_connected`, `place_order` (idempotent via `client_order_id`), `reconcile_fills`, `get_account_equity`, `subscribe_market_data`.
- **Idempotency**: `place_order(order: NewOrder)` checks `client_order_id` already submitted via local `orders` table BEFORE calling `ib_async.IB.placeOrder`.

### 2.3 `APSchedulerAdapter`

- **File**: `apps/api/src/iguanatrader/contexts/orchestration/apscheduler_adapter.py`
- **Protocol**: `SchedulerProtocol` (defined in `scheduler.py` from O2)
- **SDK**: `apscheduler ^3.10` (MIT license)
- **Secrets**: none (jobstore SQLite is local file; no remote auth)
- **Construction**: `APSchedulerAdapter(jobstore_url="sqlite:///" + os.environ["DATABASE_PATH"], timezone=ZoneInfo("America/New_York"))`
- **Methods**: `add_job(job_id, func, trigger, **kwargs)`, `remove_job(job_id)`, `pause_job(job_id)`, `resume_job(job_id)`, `start()`, `shutdown()`.
- **Persistence**: `SQLAlchemyJobStore` with the existing main-app sqlite (NOT a separate db) — jobs survive restart.
- **Trigger types**: cron (premarket / midday / postmarket / weekly_review), interval (heartbeat tick), date (one-shot retries).

### 2.4 `Tier2PlaywrightClient`

- **File**: `apps/api/src/iguanatrader/contexts/research/scraping/tier2_playwright.py`
- **Protocol**: `ScrapeTier2Port` (defined in `ladder.py` from R3)
- **SDK**: `playwright ^1.45` (Apache-2.0 license; chromium browser binaries ~600MB)
- **Secrets**: none for stock Playwright; `TWOCAPTCHA_API_KEY` deferred to post-MVP.
- **Construction**: lazy chromium launch at first `fetch()` call; reuse browser across calls within process lifetime; close on app shutdown.
- **Method**: `async def fetch(url: str, *, user_agent: str | None = None, robots_check: bool = True) -> ScrapeResult`
- **Robots check**: invokes existing `robots_check.py` from R3 (no change).
- **Body extraction**: `page.content()` for raw HTML; downstream `extract_text` from R3 unchanged.
- **Error mapping**: `playwright.async_api.TimeoutError` → existing `ScrapeTimeoutError`; `playwright.async_api.Error` → `ScrapeFetchError`.
- **Resource caps**: max 5 concurrent pages, 30s navigation timeout, 60s total per fetch.

### 2.5 `weekly_review_pdf.py`

- **File**: `apps/api/src/iguanatrader/contexts/orchestration/weekly_review_pdf.py`
- **SDK**: `reportlab ^4.0` (BSD license)
- **Input**: digest dict from `OrchestrationService.run_routine("weekly_review")` — already shipped by O2 returning markdown digest.
- **Output**: PDF file at `data/weekly_reviews/<YYYY-MM-DD>.pdf` plus a return value of bytes for piping to email/Hermes.
- **Layout**: 4 sections matching FR44 (Performance / Strategy attribution / Cost breakdown / Action items). Use the project's design palette (TBD; mock with default fonts for v0).
- **Function**: `def render_weekly_review_pdf(digest: WeeklyReviewDigest) -> bytes`

### 2.6 Helm chart + Fleet GitRepo

- **Helm chart**: `helm/iguanatrader-stack/`
  - `Chart.yaml` — `name: iguanatrader-stack, version: 0.1.0, appVersion: <git-rev>`
  - `values.yaml` — defaults: `replicas: {api: 1, web: 1, openbb: 1, litestream: 1}`, `resources: {api: {limits: {memory: 512Mi, cpu: 500m}, requests: {memory: 256Mi, cpu: 100m}}, ...}`, `image: {api: <ghcr>/iguanatrader-api:latest, ...}`, `ingress: {host: iguanatrader.local, tls: false}`
  - `templates/`:
    - `deployment-api.yaml` — single FastAPI pod, env from ConfigMap + Secret, mount sqlite PV at `/data`
    - `deployment-openbb-sidecar.yaml` — separate pod for AGPL openbb (per ADR-013)
    - `deployment-web.yaml` — Svelte 5 frontend; nginx serving built static
    - `statefulset-litestream.yaml` — litestream sidecar replicating sqlite to S3 (env: `LITESTREAM_S3_BUCKET`, `LITESTREAM_AWS_*`)
    - `service.yaml` — ClusterIP services for api + web + openbb
    - `ingress.yaml` — single ingress with path-based routing (`/api` → api, `/openbb` → openbb-sidecar, `/` → web)
    - `configmap-env.yaml` — non-secret env (LOG_LEVEL, METRICS_ENABLED, etc.)
    - `secret-sops.yaml` — SOPS-encrypted Secret manifest, decrypted at deploy by `sops-secrets-operator`

- **Fleet GitRepo**: `deploy/fleet-gitrepo.yaml`
  - Single `fleet.cattle.io/v1alpha1 GitRepo` CR pointing at this repo's `helm/iguanatrader-stack/`
  - `paths: ["helm/iguanatrader-stack/"]`
  - `targetNamespace: iguanatrader`
  - Bundle defines per-env overrides (dev/paper/live) via `clusterSelector` labels.

### 2.7 Secret rotation runbook

- **File**: `docs/runbooks/secret-rotation.md`
- **Surface**: ANTHROPIC_API_KEY + IBKR_USERNAME/PASSWORD + TWS_PORT + (future) TWOCAPTCHA_API_KEY
- **Procedure**: 5-step sequence — generate new key, encrypt with SOPS, commit, push, verify deploy
- **Rollback**: previous SOPS-encrypted version stays in git history; revert is `git revert` of the secret commit.

## 3. Anti-patterns explicitly rejected

Per [protocol-fake-deferred-install.md §7](../../../.ai-playbook/specs/protocol-fake-deferred-install.md#7-anti-patterns):

- **Adapter with business logic** — every adapter file is mechanical SDK translation only. If retry logic feels needed, it goes in the consumer (research-synthesis service or trading service), not in the adapter.
- **Production SDK referenced in tests** — only construction tests use `monkeypatch.setenv` to stub; the actual `anthropic.AsyncAnthropic` instantiation is mocked.
- **Multiple adapters per Protocol** — exactly one production adapter per Protocol; the fake stays for local dev / unit tests.
- **Secret-handling logic in the Protocol or fake** — secrets enter at adapter construction time only; Protocol describes the operation, fake is deterministic.

## 4. Migration / rollback discipline

Per [hitl-approval-pattern.md §5.2](../../../.ai-playbook/specs/hitl-approval-pattern.md#52-production-deployment) and [multi-layer-defense-single-operator.md](../../../.ai-playbook/specs/multi-layer-defense-single-operator.md):

- **HITL-gated deploy**: the Helm install / upgrade is operator-gated via WABA-MCP per ADR-028 (eligia-core canonical pattern); iguanatrader inherits the same flow once eligia-core's WABA-MCP service is reachable.
- **Rollback path**: `helm rollback iguanatrader <prev-revision>` — Helm revision history retains last 10 revisions by default.
- **Fleet bundle GitOps**: every change to `helm/iguanatrader-stack/` triggers a Fleet sync; rollback = revert PR + push.

## 5. Acceptance gates beyond proposal.md §"Acceptance"

- **License-boundary CI**: `tests/ci/test_license_boundary.py` walks `pyproject.toml` and asserts every new dep is in `["MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause"]` allow-list. AGPL deps are allowed only inside `apps/openbb-sidecar/` (per ADR-013).
- **`pyproject.toml` integrity**: `poetry lock --check` passes after the 6 deps land.
- **k3d local smoke**: `helm install iguanatrader helm/iguanatrader-stack/ --set image.api=local-dev:latest` against a `k3d cluster create iguanatrader-dev` boots all pods to READY within 90s.
- **First-run smoke per [.ai-playbook/runbooks/release.md §10](../../../.ai-playbook/runbooks/release.md)**: each new adapter exercised once against its real SDK boundary (Anthropic test API key, IBKR paper account, etc.) BEFORE the slice merges. Failures discovered locally, not in production.

## 6. Open questions

(none — slice is mechanical wiring; no design ambiguity)
