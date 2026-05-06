## Why

OpenBB Platform is the most convenient aggregator for fundamentals, ratings, ESG and macro indicators in the Python finance ecosystem — and it is licensed **AGPL-3.0**. iguanatrader-proper is licensed **Apache-2.0 + Commons Clause v1.0**. Importing `openbb` as a Python module from `apps/api/` would re-license the monolith virally: the AGPL §13 network-use clause + dynamic-linkage interpretation would force every iguanatrader user (us + customers in the eventual SaaS phase) to publish complete corresponding source under AGPL terms. That outcome is incompatible with the Commons Clause covenant and with the project's commercial trajectory. License compatibility here is **not aesthetic, it is legal compliance**: the wrong import statement creates a derivative-work obligation that cannot be retroactively undone.

The mitigation, decided at Gate B (2026-04-28) and recorded in [ADR-015](../../../docs/adr/ADR-015-2026-04-28-openbb-sidecar-isolation.md), is the standard **HTTP-loopback sidecar pattern**: OpenBB runs in its own Docker container with its own `pyproject.toml` (AGPL deps stay there), its own `LICENSE` file (AGPL-3.0 verbatim), exposes a minimalist FastAPI on `localhost:8765`, and the iguanatrader monolith talks to it like any other external HTTP source. No Python imports cross the boundary. No dynamic linkage. The sidecar binary is a separate work; the monolith communicates over the network protocol. This is the AGPL-equivalent of the LGPL "system library" exception that PostgreSQL drivers, Redis clients, etc. rely on.

Slice 1 (`bootstrap-monorepo`) declared the boundary structurally — it created the `.github/workflows/license-boundary-check.yml` workflow as a placeholder and reserved the `apps/openbb-sidecar/` directory in the project layout — but the workflow's actual scan is a no-op until the sidecar exists. **This slice (R4) lands the real container, the real client, and the real CI gate** that makes the license boundary an enforced invariant rather than a documented intent. Without it, R5 (`research-brief-synthesis`) cannot consume OpenBB-tier facts, and the CI cannot detect a future contributor accidentally adding `openbb = "^4"` to `apps/api/pyproject.toml`.

Per [docs/openspec-slice.md](../../../docs/openspec-slice.md) row R4, this slice belongs to Wave 3 (parallel ×7), depends only on `bootstrap-monorepo` (archived), and can run concurrently with the other six Wave-3 slices because every write path is disjoint (`apps/openbb-sidecar/**`, plus two new files under `apps/api/src/iguanatrader/contexts/research/sources/`, plus a workflow update).

## What Changes

- **New `apps/openbb-sidecar/` package** — independent Poetry project with its own `pyproject.toml` (declares `openbb = "^4"` + `openbb-equity` + `openbb-economy` extensions, AGPL-3.0 in `[tool.poetry] license`), `poetry.lock`, `Dockerfile` (multi-stage builder + runtime, Python 3.11), `.dockerignore`, `LICENSE` (AGPL-3.0 v3 verbatim — separate file from root `LICENSE`), `README.md` (AGPL-3.0 attribution + boundary explanation + link to ADR-015).
- **Sidecar FastAPI app** — `src/openbb_sidecar/{__init__,main,config}.py` boots a minimal FastAPI app on `localhost:8765` with structlog + a startup hook that imports `openbb` and asserts the SDK is loadable (readiness probe).
- **Sidecar routes** — `src/openbb_sidecar/routes/{__init__,health,equity,economy}.py`. `health.py` exposes `GET /health` (liveness — returns 200 when the openbb SDK is importable). `equity.py` exposes `GET /v1/equity/fundamentals/{symbol}`, `GET /v1/equity/ratings/{symbol}`, `GET /v1/equity/esg/{symbol}`. `economy.py` exposes `GET /v1/economy/macro/{indicator}`. Endpoint surface is the **minimal subset** iguanatrader's R5 synthesis needs (per `docs/architecture-decisions.md` §"OpenBB Sidecar Topology"); expandable on demand.
- **Sidecar adapter facade** — `src/openbb_sidecar/adapters/openbb_facade.py` is the single thin wrapper over the OpenBB Python SDK. Routes never call `openbb` directly; the facade is the only place AGPL imports are allowed inside the sidecar.
- **docker-compose integration** — `docker-compose.yml` (dev), `docker-compose.paper.yml`, `docker-compose.live.yml` gain an `openbb_sidecar` service with `build.context: ./apps/openbb-sidecar`, port `8765:8765` exposed only on the docker-compose internal network (NOT bound to host `0.0.0.0`), `healthcheck` polling `GET /health` every 30s, and the `api` service gains `depends_on: { openbb_sidecar: { condition: service_healthy } }`. The `docker-compose.test.yml` file is left untouched (sidecar mocked in unit tests; integration tests use the dev compose).
- **Monolith HTTP client** — `apps/api/src/iguanatrader/contexts/research/sources/openbb_sidecar.py` implements R1's `SourcePort` Protocol. Uses `httpx.AsyncClient` (already a dep), targets `localhost:8765`, applies the canonical exponential backoff `[3, 6, 12, 24, 48]` from `shared/backoff.py`, and respects the `HeartbeatMixin` from slice 2 for liveness. On 5xx → retry; on 4xx → log + skip + return empty iterable; on connection error after final backoff → log `research.openbb_sidecar.unreachable` + return empty iterable (R5 brief marks `partial=true`).
- **Yfinance proxy adapter** — `apps/api/src/iguanatrader/contexts/research/sources/yfinance_proxy.py`. yfinance fundamentals/ratings/ESG (per FR64, FR65) flow **through** the OpenBB sidecar rather than directly importing yfinance into `apps/api/` (yfinance ships under Apache-2.0, no license issue, but the OpenBB facade already exposes yfinance under a uniform interface, so we route through to keep one HTTP egress surface).
- **License-boundary CI enforcement (real, not stub)** — `.github/workflows/license-boundary-check.yml` `agpl-boundary` job replaces the slice-1 `echo "placeholder no-op"` step with three real assertions: (1) grep `apps/api/pyproject.toml` for any line matching `^openbb` (case-insensitive) — fail; (2) parse `apps/api/poetry.lock` and assert no package's `name` starts with `openbb-` — fail; (3) ripgrep `apps/api/src/` and `packages/` for `^(from|import)\s+openbb(\.|$|\s)` — fail with the offending file:line. All three are hard-block (exit 1 → workflow fails → PR cannot merge).
- **SBOM tagging note** — sidecar `pyproject.toml` declares `license = "AGPL-3.0-or-later"`; root `pyproject.toml` declares `license = "Apache-2.0 AND LicenseRef-Commons-Clause"`. SBOM-generation step (slice 1's `build-images.yml` runs `cyclonedx-py` per the OSS-algo-trading-landscape doc; verify it emits a per-image `sbom.json` separating the two licenses). If SBOM step is not yet wired (verify in slice-1 archive), this slice adds a follow-up note to gotchas; full SBOM-on-image-publish lands in O2 hardening.

Out of scope (deferred): R5 synthesis consumption of the openbb_sidecar adapter (R5 mocks the `SourcePort` during dev); production secrets management (sidecar needs no secrets in MVP — OpenBB-Platform free tier endpoints suffice for fundamentals/ratings/ESG/macro queries); k3s manifests (docker-compose only for MVP; k3s manifests live in v1.5 deploy slice); backtest features (T-track is removed per Gate A amendment 2026-04-28, ADR-016).

## Capabilities

### New Capabilities

(none — this slice ADDS to the existing `research` capability landed in R1)

### Modified Capabilities

- `research`: adds three new requirement groups — license-isolation invariant (no AGPL imports in `apps/api/`), HTTP-loopback-only sidecar communication contract (port 8765, JSON over httpx, never unix-socket / shared-memory / Python import), and sidecar healthcheck + retry contract for the `OpenBBSidecarSource` adapter. The R1 bitemporal-schema requirements are unchanged at the requirement level; this slice plants a new fact-source channel that flows facts through the existing repository's `insert_fact` path with `source_id` rows pointing to the sidecar's stable URL.

## Impact

- **Affected code (slice-R4-owned, write-allowed)**:
  - `apps/openbb-sidecar/{pyproject.toml, poetry.lock, Dockerfile, .dockerignore, README.md, LICENSE}` (NEW — package root).
  - `apps/openbb-sidecar/src/openbb_sidecar/{__init__,main,config}.py` (NEW — FastAPI app + settings).
  - `apps/openbb-sidecar/src/openbb_sidecar/routes/{__init__,health,equity,economy}.py` (NEW — route modules).
  - `apps/openbb-sidecar/src/openbb_sidecar/adapters/{__init__,openbb_facade}.py` (NEW — single AGPL-import boundary inside the sidecar).
  - `apps/openbb-sidecar/tests/{unit/test_openbb_facade.py, integration/test_routes.py}` (NEW — sidecar's own pytest suite, runs in its own poetry env).
  - `apps/api/src/iguanatrader/contexts/research/sources/{__init__,openbb_sidecar,yfinance_proxy}.py` (NEW — `SourcePort` implementations; `__init__.py` is the first file under `sources/`, anti-collision discovery is module-level so this is fine).
  - `apps/api/tests/integration/test_openbb_sidecar_client.py` (NEW — monolith client → mock sidecar → research_facts row).
  - `docker-compose.yml`, `docker-compose.paper.yml`, `docker-compose.live.yml` (MOD — add `openbb_sidecar` service block + `depends_on` clause on `api`).
  - `.github/workflows/license-boundary-check.yml` (MOD — replace the slice-1 placeholder no-op in the `agpl-boundary` job with the three real assertions).
  - `docs/gotchas.md` (MOD — append gotchas about httpx timeout tuning + yfinance-via-OpenBB rationale).
- **Affected code (R1-owned, read-only consumed)**:
  - `apps/api/src/iguanatrader/contexts/research/ports.py::SourcePort` — protocol implemented by both new sources.
  - `apps/api/src/iguanatrader/contexts/research/ports.py::ResearchFactDraft.with_payload(...)` — used to wrap raw OpenBB JSON responses for hybrid-storage dispatch.
  - `apps/api/src/iguanatrader/contexts/research/repository.py::ResearchRepository.insert_fact(...)` — consumed unchanged.
  - `apps/api/src/iguanatrader/shared/{backoff, heartbeat, errors}.py` (slice 2) — backoff schedule + HeartbeatMixin + IntegrationError raised on final-attempt failure.
- **APIs**: no new routes added to the iguanatrader monolith (R5 lands `/research/*`). The sidecar exposes its own minimal FastAPI but it is **not part of iguanatrader's public API surface** — only the monolith talks to it; it is not exposed on host `0.0.0.0` and not documented in `/openapi.json` of the monolith.
- **Dependencies (sidecar — AGPL space)**: `openbb = "^4"`, `openbb-equity`, `openbb-economy`, `fastapi = "^0.115"`, `uvicorn = "^0.32"`, `httpx = "^0.27"`, `structlog = "^24.4"`, `pydantic-settings = "^2.6"`. All under the sidecar's own `pyproject.toml`; none reach `apps/api/`.
- **Dependencies (monolith — Apache+CC space)**: zero new deps (`httpx` already vendored by slice 4 for the auth flow; `structlog` from slice 2; `pydantic-settings` already in root).
- **Prerequisites**: `bootstrap-monorepo` archived (LICENSE + license-boundary-check workflow placeholder + reserved sidecar dir); `shared-primitives` archived (HeartbeatMixin + backoff + IntegrationError); `research-bitemporal-schema` archived (SourcePort protocol + ResearchFactDraft + repository.insert_fact). All three are in `openspec/changes/archive/`.
- **Capability coverage** (per `docs/openspec-slice.md` row R4): targets FR76 ("System integrates OpenBB Platform via sidecar process preserving AGPL-3.0 ↔ Apache-2.0+CC license boundary — iguanatrader-proper never links OpenBB code in-process; communication exclusively via HTTP loopback") and is the implementation pillar of ADR-015.
- **Acceptance criteria** (slice-level — full per-task list lives in `tasks.md` §8):
  - [ ] `docker compose up openbb_sidecar` builds the sidecar image cleanly.
  - [ ] `docker compose ps` shows `openbb_sidecar` with status `(healthy)` after readiness window.
  - [ ] `curl http://localhost:8765/health` returns 200 + `{"status": "ok", "openbb_loadable": true}`.
  - [ ] `curl http://localhost:8765/v1/equity/fundamentals/AAPL` returns 200 + a JSON body with at least `symbol`, `pe_ratio`, `market_cap` keys (smoke; full schema under `apps/openbb-sidecar/tests/`).
  - [ ] From the monolith: `await OpenBBSidecarSource(...).fetch("AAPL", since=None)` yields ≥1 `ResearchFactDraft` instance with `source_id="openbb-sidecar"` and `source_url` containing `localhost:8765`.
  - [ ] License-boundary CI workflow's `agpl-boundary` job: PASSES on `main` (no AGPL leakage); injecting a stub `openbb = "^4"` line into `apps/api/pyproject.toml` on a branch FAILS the workflow with a clear error message naming the offending line.
  - [ ] Pre-commit, `mypy --strict apps/openbb-sidecar/src/`, `mypy --strict apps/api/src/iguanatrader/contexts/research/sources/`, and the slice's pytest suite are all green.
- **Risk**: low-to-medium. The boundary itself is well-understood (sidecar pattern is industry-standard). The medium-risk surface is the `openbb` SDK's own surprises (heavy import time, optional sub-deps, occasional API breakage). Mitigation: pin OpenBB to a specific version in sidecar `pyproject.toml`; lazy-import inside the facade so cold-start still passes the healthcheck; integration test against a live sidecar in CI (not just unit-mocked).
- **Out of scope** (per `docs/openspec-slice.md` row R4 + scope note):
  - R5 brief synthesis consumption of the new adapter (R5 mocks `SourcePort` during dev).
  - k3s / Kubernetes manifests (docker-compose is the v1 deployment unit; k3s lands in v1.5 deploy slice).
  - Sidecar API authentication (loopback-only binding makes auth unnecessary at MVP; if exposed beyond loopback later, add HMAC + per-tenant key).
  - Backtest feature ingestion (T-track removed per ADR-016).
  - Multi-version OpenBB rolling upgrade (single pinned version per release; bump is its own slice).
