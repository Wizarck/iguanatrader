# tasks — deployment-foundation

> Task groups follow the dependency order: deps install (1) → secret primitives (2) → 6 adapters in parallel (3) → Helm chart (4) → Fleet GitRepo (5) → runbook (6) → CI gates (7) → acceptance smoke (8).
>
> Slot reservations per [.ai-playbook/specs/migration-slot-reservation.md](../../../.ai-playbook/specs/migration-slot-reservation.md): no migrations in this slice (pure wiring); no gotcha IDs claimed; ADR-INDEX MAY add `ADR-029-deployment-foundation-helm-chart` (operator-discretion).

## 1. Dependency installs (`apps/api/pyproject.toml`)

- [ ] **1.1** Add `anthropic = "^0.40"` to `[tool.poetry.dependencies]`
- [ ] **1.2** Add `ib_async = "^1.0"` to `[tool.poetry.dependencies]`
- [ ] **1.3** Add `apscheduler = {version = "^3.10", extras = ["sqlalchemy"]}` to `[tool.poetry.dependencies]`
- [ ] **1.4** Add `playwright = "^1.45"` to `[tool.poetry.dependencies]`
- [ ] **1.5** Add `camoufox = "^0.4"` to `[tool.poetry.dependencies]`
- [ ] **1.6** Add `reportlab = "^4.0"` to `[tool.poetry.dependencies]`
- [ ] **1.7** Run `poetry lock` and commit `poetry.lock`
- [ ] **1.8** Run `poetry install` locally; verify `poetry env info` reports the deps installed.
- [ ] **1.9** Run `playwright install chromium` (browser binary download ~600 MB) and commit any required `.gitattributes` markers (none expected — browsers live in `~/.cache/ms-playwright`, not in repo).

## 2. Secret-handling primitives

- [ ] **2.1** Add `apps/api/src/iguanatrader/config/secrets.py` — `class SecretEnv` with typed properties (`anthropic_api_key`, `ibkr_username`, `ibkr_password`, `tws_port`, ...). Properties raise `MissingSecretError` if env var unset.
- [ ] **2.2** Add `tests/unit/config/test_secrets.py` — verify `SecretEnv()` reads from `os.environ`; `monkeypatch.delenv` produces `MissingSecretError`.
- [ ] **2.3** Update `apps/api/src/iguanatrader/main.py` (or composition root) to construct `SecretEnv()` ONCE at startup and pass into adapter constructors via DI.

## 3. Six production adapters (parallelisable per [.ai-playbook/specs/release-management.md §6.6](../../../.ai-playbook/specs/release-management.md))

> Subagent prompt template available at [.ai-playbook/templates/subagent-prompt.md.tmpl](../../../.ai-playbook/templates/subagent-prompt.md.tmpl) for Wave-N parallelism if main agent dispatches via `/openspec-apply-parallel`.

### 3.A AnthropicLLMClient

- [ ] **3.A.1** Author `apps/api/src/iguanatrader/contexts/research/synthesis/anthropic_client.py`. ~50 lines: imports, class with `@cost_meter` on `generate`, error mapping `APIError → LLMClientError`.
- [ ] **3.A.2** Wire DI in research-synthesis service composition root: production code uses `AnthropicLLMClient(secrets.anthropic_api_key)`; tests continue to use `FakeLLMClient`.
- [ ] **3.A.3** Author `tests/unit/contexts/research/synthesis/test_anthropic_client.py` — construction test with `monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-test")`; `anthropic.AsyncAnthropic` mocked; verify `generate` returns expected text and emits `@cost_meter` event.

### 3.B IbAsyncIBClient

- [ ] **3.B.1** Author `apps/api/src/iguanatrader/contexts/trading/brokers/ib_async_client.py`. ~150 lines: extends `HeartbeatMixin`, implements `IBClient` Protocol methods, idempotency guard via existing `orders` table check.
- [ ] **3.B.2** Wire DI in trading service composition root.
- [ ] **3.B.3** Author `tests/unit/contexts/trading/brokers/test_ib_async_client.py` — construction test with `monkeypatch.setenv` for IBKR credentials; `ib_async.IB` mocked; verify connect/disconnect/place_order; verify HeartbeatMixin's 5-attempt ceiling triggers reconnect.

### 3.C APSchedulerAdapter

- [ ] **3.C.1** Author `apps/api/src/iguanatrader/contexts/orchestration/apscheduler_adapter.py`. ~80 lines: `AsyncIOScheduler` + `SQLAlchemyJobStore` wiring; methods delegate to scheduler.
- [ ] **3.C.2** Wire DI in orchestration service composition root.
- [ ] **3.C.3** Author `tests/unit/contexts/orchestration/test_apscheduler_adapter.py` — construction test against in-memory sqlite (`sqlite:///:memory:`); verify `add_job` persists; verify `start/shutdown` lifecycle.

### 3.D Tier2PlaywrightClient

- [ ] **3.D.1** Author `apps/api/src/iguanatrader/contexts/research/scraping/tier2_playwright.py`. ~100 lines: lazy chromium launch, robots check, `page.goto` + `page.content`, error mapping.
- [ ] **3.D.2** Replace `fetch_tier2_stub` references in `ladder.py` with `Tier2PlaywrightClient` (Protocol → adapter swap).
- [ ] **3.D.3** Author `tests/unit/contexts/research/scraping/test_tier2_playwright.py` — `playwright.async_api` mocked; verify navigation, body extraction, robots-check enforcement, timeout handling. NO real chromium launch in tests (fake-first per [.ai-playbook/specs/protocol-fake-deferred-install.md](../../../.ai-playbook/specs/protocol-fake-deferred-install.md)).

### 3.E weekly_review_pdf

- [ ] **3.E.1** Author `apps/api/src/iguanatrader/contexts/orchestration/weekly_review_pdf.py`. ~120 lines: `render_weekly_review_pdf(digest)` builds PDF via reportlab, writes to `data/weekly_reviews/<date>.pdf`, returns bytes.
- [ ] **3.E.2** Wire into `OrchestrationService.run_routine("weekly_review")` — the digest output is now also rendered as PDF and the path is included in the routine result.
- [ ] **3.E.3** Author `tests/unit/contexts/orchestration/test_weekly_review_pdf.py` — given a sample digest dict, verify PDF bytes are valid (starts with `%PDF-`), file is written, and the 4 sections (FR44) are present.

### 3.F (No 6th adapter — Helm chart is the deployment surface, covered in §4 below.)

## 4. Helm chart (`helm/iguanatrader-stack/`)

- [ ] **4.1** Create `helm/iguanatrader-stack/Chart.yaml` (`name: iguanatrader-stack, version: 0.1.0, appVersion: 0.1.0`)
- [ ] **4.2** Create `helm/iguanatrader-stack/values.yaml` with documented defaults per design.md §2.6.
- [ ] **4.3** Create `helm/iguanatrader-stack/templates/deployment-api.yaml` — FastAPI pod with env from ConfigMap + Secret, sqlite PV mount, liveness/readiness probes.
- [ ] **4.4** Create `helm/iguanatrader-stack/templates/deployment-openbb-sidecar.yaml` — separate pod (AGPL boundary per ADR-013).
- [ ] **4.5** Create `helm/iguanatrader-stack/templates/deployment-web.yaml` — Svelte 5 frontend; nginx serving built static.
- [ ] **4.6** Create `helm/iguanatrader-stack/templates/statefulset-litestream.yaml` — litestream sidecar replicating sqlite to S3.
- [ ] **4.7** Create `helm/iguanatrader-stack/templates/service.yaml` (ClusterIP for api/web/openbb).
- [ ] **4.8** Create `helm/iguanatrader-stack/templates/ingress.yaml` (path-based routing).
- [ ] **4.9** Create `helm/iguanatrader-stack/templates/configmap-env.yaml` (non-secret env).
- [ ] **4.10** Create `helm/iguanatrader-stack/templates/secret-sops.yaml` (SOPS-encrypted; sops-secrets-operator decrypts at deploy).
- [ ] **4.11** Run `helm template helm/iguanatrader-stack/` locally; verify YAML output is valid Kubernetes manifests.
- [ ] **4.12** Run `helm lint helm/iguanatrader-stack/`; address all warnings/errors.

## 5. Rancher Fleet GitRepo (`deploy/fleet-gitrepo.yaml`)

- [ ] **5.1** Create `deploy/fleet-gitrepo.yaml` with `fleet.cattle.io/v1alpha1 GitRepo` pointing at this repo's `helm/iguanatrader-stack/`.
- [ ] **5.2** Document Fleet bundle override pattern (per-env values via `clusterSelector` labels).

## 6. Secret rotation runbook (`docs/runbooks/secret-rotation.md`)

- [ ] **6.1** Author `docs/runbooks/secret-rotation.md` per [.ai-playbook/runbooks/cascade-failure-template.md](../../../.ai-playbook/runbooks/cascade-failure-template.md) structure (5 sections — adapted for rotation, not cascade).
- [ ] **6.2** Cover ANTHROPIC_API_KEY, IBKR_USERNAME/PASSWORD, TWS_PORT, (future) TWOCAPTCHA_API_KEY.
- [ ] **6.3** Document SOPS encrypt/decrypt commands using existing project SOPS keyring.
- [ ] **6.4** Document rollback procedure (revert SOPS-encrypted file commit).

## 7. CI gates

- [ ] **7.1** Add `tests/ci/test_license_boundary.py` — walks `pyproject.toml` deps and asserts each is in MIT/Apache-2.0/BSD-3/BSD-2 allow-list. AGPL allowed only inside `apps/openbb-sidecar/`.
- [ ] **7.2** Run `tests/ci/test_license_boundary.py` — verify all 6 new deps pass.
- [ ] **7.3** Add `tests/ci/test_helm_chart_lints.py` — pytest wrapper that shells out to `helm lint` and asserts exit 0.
- [ ] **7.4** Wire both into `.github/workflows/ci.yml` matrix.

## 8. Acceptance smoke (per design.md §5)

- [ ] **8.1** Local k3d smoke: `k3d cluster create iguanatrader-dev`; `helm install iguanatrader helm/iguanatrader-stack/ --set image.api=ghcr.io/wizarck/iguanatrader-api:latest`; verify all pods READY within 90s.
- [ ] **8.2** First-run smoke per [.ai-playbook/runbooks/release.md §10](../../../.ai-playbook/runbooks/release.md): exercise each adapter once against real SDK boundary:
  - **8.2.A** AnthropicLLMClient against test Anthropic API key (`generate("test prompt", model="claude-haiku-4-5", max_tokens=64)` returns text).
  - **8.2.B** IbAsyncIBClient against IBKR paper account (connect → place dummy order → reconcile → disconnect).
  - **8.2.C** APSchedulerAdapter persists a job across process restart (start, add_job, shutdown, restart, list_jobs returns the job).
  - **8.2.D** Tier2PlaywrightClient fetches a known-stable URL (`https://example.com`) and asserts body contains "Example Domain".
  - **8.2.E** weekly_review_pdf renders a sample digest to a PDF and the file opens in a viewer (manual operator verification).
- [ ] **8.3** Secret rotation runbook end-to-end: operator follows §6 against fresh SOPS keyring; no code changes needed.
- [ ] **8.4** Fleet GitRepo CI verification: GitRepo CR applied to dev k3s; `kubectl get gitrepo iguanatrader -n fleet-default` reports synced; deployed pods match `helm template` output.

## 9. Retro draft

- [ ] **9.1** Author `retros/deployment-foundation.md` stub per [.ai-playbook/runbook-bmad-openspec.md §4.1](../../../.ai-playbook/specs/runbook-bmad-openspec.md#4-retrospective-cadence) "forward-authored retros" pattern. Fill `What worked` / `What didn't` / `Lessons` / `Carry-forward` post-merge.

---

## Estimated effort

| Group | Files touched | Effort |
|---|---|---|
| 1 (deps) | `pyproject.toml`, `poetry.lock` | 15 min + ~700 MB disk for playwright |
| 2 (secrets) | 2 new files | 30 min |
| 3 (6 adapters) | 12 new files (6 adapters + 6 test files) | ~3 h sequential / ~1 h parallel via 6 subagents |
| 4 (helm) | 12 new files | 2 h |
| 5 (fleet) | 1 new file | 15 min |
| 6 (runbook) | 1 new file | 1 h |
| 7 (CI gates) | 2 new test files + workflow edit | 30 min |
| 8 (smoke) | manual exercise | 2 h (mostly waiting on real SDKs) |
| 9 (retro) | 1 new file | 30 min draft |

**Total**: ~10 h sequential / ~5 h with intra-slice parallelism in §3.

**Disk requirement**: ~2 GB free before starting §1.9 (playwright chromium ~700 MB + anthropic + ib_async + apscheduler + reportlab + camoufox + their transitive deps + apt cache for system fonts that reportlab may pull).
