# tasks — deployment-foundation

> Task groups follow the dependency order: deps install (1) → secret primitives (2) → 6 adapters in parallel (3) → Helm chart (4) → Fleet GitRepo (5) → runbook (6) → CI gates (7) → acceptance smoke (8).
>
> Slot reservations per [.ai-playbook/specs/migration-slot-reservation.md](../../../.ai-playbook/specs/migration-slot-reservation.md): no migrations in this slice (pure wiring); no gotcha IDs claimed; ADR-INDEX MAY add `ADR-029-deployment-foundation-helm-chart` (operator-discretion).

## 1. Dependency installs (`pyproject.toml` at repo root — workspace pyproject, `package-mode = false`)

- [x] **1.1** Add `anthropic = "^0.40"` to `[tool.poetry.dependencies]`
- [x] **1.2** Add `ib_async = "^1.0"` to `[tool.poetry.dependencies]`
- [x] **1.3** Add `apscheduler = {version = "^3.10", extras = ["sqlalchemy"]}` to `[tool.poetry.dependencies]`
- [x] **1.4** Add `playwright = "^1.45"` to `[tool.poetry.dependencies]`
- [x] **1.5** Add `camoufox = "^0.4"` to `[tool.poetry.dependencies]`
- [x] **1.6** Add `reportlab = "^4.0"` to `[tool.poetry.dependencies]`
- [ ] **1.7** Run `poetry lock` and commit `poetry.lock`. **Operator-driven** — poetry hangs silently in this CLI harness; run from a real terminal: `poetry lock`.
- [ ] **1.8** Run `poetry install` locally; verify `poetry env info` reports the deps installed. **Operator-driven** (same reason as 1.7).
- [ ] **1.9** Run `poetry run playwright install chromium` (browser binary download ~600 MB) and commit any required `.gitattributes` markers (none expected — browsers live in `~/.cache/ms-playwright`, not in repo). **Operator-driven**.

## 2. Secret-handling primitives

- [x] **2.1** Add `apps/api/src/iguanatrader/config/secrets.py` — `class SecretEnv` with typed properties (`anthropic_api_key`, `ibkr_username`, `ibkr_password`, `tws_port`, `ibkr_host`, `ib_client_id`, `database_path`). Properties raise `MissingSecretError` if env var unset.
- [x] **2.2** Add `tests/unit/config/test_secrets.py` — verify `SecretEnv()` reads from `os.environ`; `monkeypatch.delenv` produces `MissingSecretError`; integer-coerced properties surface `MissingSecretError` (not `ValueError`) on malformed input.
- [ ] **2.3** Update `apps/api/src/iguanatrader/main.py` (or composition root) to construct `SecretEnv()` ONCE at startup and pass into adapter constructors via DI. Wired alongside each adapter's DI in §3.

## 3. Six production adapters (parallelisable per [.ai-playbook/specs/release-management.md §6.6](../../../.ai-playbook/specs/release-management.md))

> Subagent prompt template available at [.ai-playbook/templates/subagent-prompt.md.tmpl](../../../.ai-playbook/templates/subagent-prompt.md.tmpl) for Wave-N parallelism if main agent dispatches via `/openspec-apply-parallel`.

### 3.A AnthropicLLMClient

- [x] **3.A.1** Author `apps/api/src/iguanatrader/contexts/research/synthesis/anthropic_client.py`. ~110 lines: dynamic-per-call `@cost_meter` composition (model varies per call), text-block extraction, lazy SDK construction, `build_anthropic_llm_client_from_env()` helper.
- [ ] **3.A.2** Wire DI in research-synthesis service composition root: production code uses `build_anthropic_llm_client_from_env()`; tests continue to use `FakeLLMClient`. **Wired alongside §8 acceptance smoke** — composition root edits live in the smoke commit.
- [x] **3.A.3** Author `tests/unit/contexts/research/test_anthropic_client.py` — fake `AsyncAnthropic` (no SDK call); 5 cases covering happy path, multi-block concat, cache flag, empty content, composition-root helper.

### 3.B IbAsyncIBClient

- [x] **3.B.1** Author `apps/api/src/iguanatrader/contexts/trading/brokers/ib_async_client.py` — ~210 lines. Refined scope: this is the `IBClient` Protocol shim ONLY (HeartbeatMixin + idempotency live in the existing higher-level `IBKRAdapter` per slice T2 design). Translates 5 value-object shapes (Contract/Order/Position/AccountSummary/Execution) + delegates 8 Protocol methods to `ib_async.IB`. `build_ib_async_client_from_env()` helper.
- [ ] **3.B.2** Wire DI in trading service composition root: production `IBKRAdapter` constructor receives `IbAsyncIBClient()` via factory; tests continue to inject the in-tree fake. **Wired alongside §8 acceptance smoke**.
- [x] **3.B.3** Author `tests/unit/contexts/trading/brokers/test_ib_async_client.py` — fake `ib_async` injected via `sys.modules`; 9 cases covering connect/disconnect/req_current_time/positions/account_summary delegation, value-object translators (LMT, unsupported sec_type, missing limit_price). Heartbeat lifecycle + idempotency are exercised by existing `test_ibkr_adapter_lifecycle.py`.

### 3.C APSchedulerAdapter

- [x] **3.C.1** Author `apps/api/src/iguanatrader/contexts/orchestration/apscheduler_adapter.py` — ~95 lines. Lazy SDK construction; `add_job` translates `JobSpec.cron_kwargs` to APScheduler's `trigger="cron"`; `replace_existing=True` for idempotent re-registration; `shutdown(wait=False)` so process shutdown doesn't block on in-flight jobs; `misfire_grace_time=300s`.
- [ ] **3.C.2** Wire DI in orchestration service composition root: production code uses `build_apscheduler_adapter_from_env()`; tests continue to use `InMemoryScheduler`. **Wired alongside §8 acceptance smoke**.
- [x] **3.C.3** Author `tests/unit/contexts/orchestration/test_apscheduler_adapter.py` — `MagicMock` scheduler injected; 7 cases covering `add_job` arg shape, `list_jobs` registry, start idempotency, shutdown noop-when-not-running, `is_running` mirror.

### 3.D Tier2PlaywrightClient

- [x] **3.D.1** Author `apps/api/src/iguanatrader/contexts/research/scraping/tier2_playwright.py` — ~140 lines. Process-singleton browser holder with `asyncio.Semaphore(5)` concurrency cap; lazy chromium launch on first fetch; robots-check before navigation; 30s nav-timeout + 60s total-timeout; status-code mapping (403/429/503 → `ScrapeBlockedError`); `shutdown_playwright()` for FastAPI lifespan teardown.
- [ ] **3.D.2** Composition root rebinds `_DEFAULT_TIER_FNS[TIER_2_PLAYWRIGHT]` to `fetch_tier2_playwright` once deps are installed. **Wired alongside §8 acceptance smoke**.
- [x] **3.D.3** Author `tests/unit/contexts/research/test_tier2_playwright.py` — `playwright.async_api` mocked via `sys.modules`; 3 cases: 200-happy-path returns `ScrapeResult`, 403 raises `ScrapeBlockedError`, robots-disallow raises `ScrapeBlockedError`. NO real chromium launch.

### 3.E weekly_review_pdf

- [x] **3.E.1** Author `apps/api/src/iguanatrader/contexts/orchestration/weekly_review_pdf.py` — ~170 lines. Pure function `render_weekly_review_pdf(digest, review_date=None) -> bytes`; no disk I/O. 4 sections (Performance / Strategy attribution / Cost breakdown / Action items) defensively handle malformed digest fields.
- [ ] **3.E.2** Wire into `OrchestrationService.run_routine("weekly_review")` — the digest output is also rendered as PDF and the path is included in the routine result. **Wired alongside §8 acceptance smoke** — caller writes to `data/weekly_reviews/<YYYY-MM-DD>.pdf`.
- [x] **3.E.3** Author `tests/unit/contexts/orchestration/test_weekly_review_pdf.py` — `pytest.importorskip("reportlab")` install-gate; 5 cases: PDF magic bytes, empty-digest tolerance, review-date embedding, document-info `iguanatrader` author, malformed-digest tolerance.

### 3.F (No 6th adapter — Helm chart is the deployment surface, covered in §4 below.)

## 4. Helm chart (`helm/iguanatrader-stack/`)

- [x] **4.1** Create `helm/iguanatrader-stack/Chart.yaml` (`name: iguanatrader-stack, version: 0.1.0, appVersion: 0.1.0`).
- [x] **4.2** Create `helm/iguanatrader-stack/values.yaml` with documented defaults per design.md §2.6 (image / env / secret / resources / persistence / litestream / ingress / service / probes).
- [x] **4.3** Create `helm/iguanatrader-stack/templates/statefulset-api.yaml` — FastAPI pod + co-located litestream sidecar (same StatefulSet so the sqlite PV is mounted into both containers); env from ConfigMap + Secret; PV mount via volumeClaimTemplates; liveness/readiness probes.
- [x] **4.4** Create `helm/iguanatrader-stack/templates/deployment-openbb.yaml` — separate pod (AGPL boundary per ADR-013); ClusterIP-only.
- [x] **4.5** ~~deployment-web.yaml~~ → **deferred to a W-series slice** when the Svelte 5 frontend ships. Chart documents the deferral in `Chart.yaml` description.
- [x] **4.6** Create `helm/iguanatrader-stack/templates/configmap-litestream.yaml` — litestream config (S3 bucket / region / sync-interval). Co-located with the api StatefulSet via volume mount instead of separate StatefulSet (litestream is intended to live in the SAME pod as the writer per its docs).
- [x] **4.7** Create `helm/iguanatrader-stack/templates/service.yaml` — two ClusterIP services (api + openbb-sidecar) in one file.
- [x] **4.8** Create `helm/iguanatrader-stack/templates/ingress.yaml` — path-based routing (`/api`, `/openbb`); TLS optional via values.
- [x] **4.9** Create `helm/iguanatrader-stack/templates/configmap-env.yaml` — non-secret env.
- [x] **4.10** Create `helm/iguanatrader-stack/templates/secret.yaml` — placeholder Secret for first-install; replaced at deploy by `sops-secrets-operator`. Plus `_helpers.tpl` (labels + image refs) and `NOTES.txt` (post-install hints) and `.helmignore`.
- [ ] **4.11** Run `helm template helm/iguanatrader-stack/` locally; verify YAML output is valid Kubernetes manifests. **Operator-driven** — needs `helm` CLI + a values file with non-empty `litestream.s3.bucket`.
- [ ] **4.12** Run `helm lint helm/iguanatrader-stack/`; address all warnings/errors. **Operator-driven**.

## 5. Rancher Fleet GitRepo (`deploy/fleet-gitrepo.yaml`)

- [x] **5.1** Create `deploy/fleet-gitrepo.yaml` — `fleet.cattle.io/v1alpha1 GitRepo` pointing at `helm/iguanatrader-stack`. `targetNamespace: iguanatrader`.
- [x] **5.2** Document Fleet bundle override pattern via `targets[].clusterSelector` labels — three pre-wired targets (dev/paper/live).

## 6. Secret rotation runbook (`docs/runbooks/secret-rotation.md`)

- [x] **6.1** Author `docs/runbooks/secret-rotation.md` — 6 sections (Surface / Pre-rotation checklist / Procedure-per-secret / Verification / Rollback / Common failures).
- [x] **6.2** Cover `ANTHROPIC_API_KEY`, `IBKR_USERNAME`/`PASSWORD`, `LITESTREAM_AWS_*`, `TWOCAPTCHA_API_KEY` (future). Clarifies `TWS_PORT`/`IBKR_HOST`/`IB_CLIENT_ID` are NOT secrets (configmap-env).
- [x] **6.3** Document `sops --decrypt` / `sops --encrypt` commands + base64 encoding for K8s Secret data; `shred` of plaintext temp file.
- [x] **6.4** Document rollback procedure: `git revert <rotation-commit>` + Fleet auto-sync; explicit warning against manual `kubectl apply` (Fleet would overwrite).

## 7. CI gates

- [x] **7.1** Add `apps/api/tests/ci/test_license_boundary.py` — verifies each Wave-4 dep is listed in `pyproject.toml` AND its license is in the allow-list `{MIT, Apache-2.0, BSD-3-Clause, BSD-2-Clause, MPL-2.0}`. Complements existing `.github/workflows/license-boundary-check.yml` (which enforces the AGPL boundary; this file enforces the new-dep allow-list).
- [ ] **7.2** Run `apps/api/tests/ci/test_license_boundary.py` — operator runs after `poetry install` (3 cases: deps-listed parametrise, license-allow-list, anthropic no-AGPL-leak).
- [x] **7.3** Add `apps/api/tests/ci/test_helm_chart_lints.py` — `helm lint` + `helm template` parse-back; skipped when `helm` not on PATH.
- [x] **7.4** Wire `helm-lint` job into `.github/workflows/ci.yml` (uses `azure/setup-helm@v4`); pytest tests are picked up by the existing `test` job once it actually runs (currently `--collect-only`, will switch to full run when slice acceptance lands).

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

- [x] **9.1** Author `retros/deployment-foundation.md` stub per the "forward-authored retros" pattern. Pattern-usage table cross-links the 5 Wave-3 fakes → 5 production adapters. `What worked` / `What didn't` / `Lessons` filled at archive time.

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
