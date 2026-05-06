## ADDED Requirements

### Requirement: No AGPL-licensed Python packages SHALL be imported, declared, or transitively pulled into `apps/api/`

The system SHALL prevent any AGPL-licensed Python package — specifically the `openbb` family (`openbb`, `openbb-equity`, `openbb-economy`, `openbb-*` extensions) — from entering the iguanatrader monolith's runtime environment. The boundary is enforced on **three independent surfaces**, each gated by a hard-blocking CI step in `.github/workflows/license-boundary-check.yml`:

1. **Declared dependencies**: `apps/api/pyproject.toml` MUST NOT contain any line matching `^\s*openbb` (case-insensitive).
2. **Locked dependencies**: `apps/api/poetry.lock` MUST NOT contain any package whose name field matches `^name = "openbb`.
3. **Source imports**: `apps/api/src/` and `packages/` MUST NOT contain any Python source line matching `^(from|import)\s+openbb(\.|$|\s)`.

A failure on any one of the three SHALL fail the workflow with an explicit `::error::` message identifying the offending file and line. The workflow SHALL be configured as a required check on branch protection so PRs cannot merge while the gate is red.

#### Scenario: Developer accidentally adds openbb to apps/api/pyproject.toml

- **WHEN** a contributor edits `apps/api/pyproject.toml` and adds `openbb = "^4"` under `[tool.poetry.dependencies]`
- **AND** pushes the branch
- **THEN** the `agpl-boundary` job in `license-boundary-check.yml` runs and fails
- **AND** the workflow log shows `::error::AGPL violation: openbb dep found in apps/api/pyproject.toml`
- **AND** the PR cannot be merged until the line is removed

#### Scenario: Transitive AGPL package leaks via poetry resolution

- **WHEN** a contributor adds a benign-looking dep that transitively depends on `openbb-core`
- **AND** `apps/api/poetry.lock` regenerates with `name = "openbb-core"` somewhere in the lock graph
- **THEN** the lock-file scan step fails the workflow
- **AND** the contributor must either remove the offending dep or pin a version that does not transitively pull openbb

#### Scenario: Disguised import via importlib

- **WHEN** a contributor writes `mod = importlib.import_module("openbb")` inside `apps/api/src/...`
- **THEN** the regex-based source scan does NOT catch this (known limitation, design D4 risk note)
- **AND** the gate may produce a false negative; mitigation is code review + the future AST-based scanner planned for slice O1 hardening
- **AND** the project's stance is documented: regex catches honest mistakes; intentional disguise is a code-review concern, not a CI-only concern

### Requirement: OpenBB Platform SDK SHALL run only inside the `apps/openbb-sidecar/` package, isolated from the monolith

The system SHALL package OpenBB Platform as a separate Docker container under `apps/openbb-sidecar/` with its own `pyproject.toml` declaring `license = "AGPL-3.0-or-later"` (SPDX), its own `LICENSE` file containing the AGPL-3.0 v3 verbatim text, its own `poetry.lock`, its own `Dockerfile`, and its own pytest suite. The sidecar package SHALL be the only path through which iguanatrader interacts with OpenBB-licensed code. No iguanatrader code outside `apps/openbb-sidecar/` SHALL `from openbb` / `import openbb`.

#### Scenario: Sidecar package is structured per docs/project-structure.md §11

- **WHEN** the slice lands
- **THEN** `apps/openbb-sidecar/` contains: `pyproject.toml` (AGPL declaration), `poetry.lock`, `Dockerfile`, `.dockerignore`, `LICENSE` (AGPL-3.0 v3 verbatim), `README.md` (attribution + boundary explanation + ADR-015 link), `src/openbb_sidecar/{__init__,main,config}.py`, `src/openbb_sidecar/routes/{__init__,health,equity,economy}.py`, `src/openbb_sidecar/adapters/{__init__,openbb_facade}.py`, and `tests/{unit,integration}/`
- **AND** the sidecar's `LICENSE` file SHA256 matches the canonical AGPL-3.0 v3 text from `https://www.gnu.org/licenses/agpl-3.0.txt`
- **AND** the root repository `LICENSE` (Apache-2.0 + Commons Clause v1.0) is unchanged

#### Scenario: openbb is imported only inside the facade

- **WHEN** the slice lands
- **THEN** `rg "^(from|import)\s+openbb" apps/openbb-sidecar/src/` returns matches ONLY in `apps/openbb-sidecar/src/openbb_sidecar/adapters/openbb_facade.py`
- **AND** no route module (`routes/health.py`, `routes/equity.py`, `routes/economy.py`) imports openbb directly
- **AND** the facade is the single audit point for AGPL-licensed code inside the sidecar

### Requirement: Monolith ↔ sidecar communication SHALL be exclusively HTTP loopback on port 8765

The system SHALL communicate between the iguanatrader monolith and the OpenBB sidecar exclusively over HTTP using `httpx` against `http://localhost:8765` (configurable via the `OPENBB_SIDECAR_URL` env var on the monolith side). No alternative transport mechanism SHALL be permitted: no Unix socket, no shared memory, no Python `import` of sidecar code, no subprocess invocation of sidecar Python files, no gRPC, no RPC frameworks that depend on Python-level coupling. The HTTP boundary is what preserves the AGPL-3.0 ↔ Apache-2.0+CC license separation per ADR-015.

#### Scenario: Monolith adapter implements SourcePort via httpx HTTP GET

- **WHEN** R5 brief synthesis (or the integration test) invokes `await OpenBBSidecarSource(...).fetch("AAPL", since=None)`
- **THEN** the adapter issues HTTP GET requests to `http://localhost:8765/v1/equity/fundamentals/AAPL`, `http://localhost:8765/v1/equity/ratings/AAPL`, `http://localhost:8765/v1/equity/esg/AAPL` (parallel via `asyncio.gather`)
- **AND** parses the JSON responses
- **AND** yields `ResearchFactDraft` instances with `source_id="openbb-sidecar"`, `source_url=<the http URL hit>`, `retrieval_method="http_get"`, `recorded_from=utc_now()`, `value_jsonb=<parsed body>`, payload-tier-dispatched via `with_payload(payload_bytes)`
- **AND** at no point does the monolith Python process import any module from `apps/openbb-sidecar/src/openbb_sidecar/`

#### Scenario: Sidecar binds only to the docker-compose internal network, not the host

- **WHEN** the operator runs `docker compose up -d openbb_sidecar`
- **AND** queries `docker compose port openbb_sidecar 8765`
- **THEN** the command returns empty / `<no entry>` (NOT a host-bound port mapping)
- **AND** `curl http://localhost:8765/health` from the host SHALL fail with connection refused
- **AND** `curl http://openbb_sidecar:8765/health` from inside the `api` container SHALL succeed (internal docker network resolution)
- **AND** the sidecar is unreachable from outside the docker-compose project boundary

### Requirement: Sidecar SHALL expose `/health`, `/v1/equity/{fundamentals,ratings,esg}/{symbol}`, `/v1/economy/macro/{indicator}` and no other endpoints

The system SHALL expose only the minimum endpoint surface iguanatrader's R5 brief synthesis requires. The endpoint set SHALL be `GET /health`, `GET /v1/equity/fundamentals/{symbol}`, `GET /v1/equity/ratings/{symbol}`, `GET /v1/equity/esg/{symbol}`, `GET /v1/economy/macro/{indicator}`. Adding endpoints requires a new slice that owns the addition (same dynamic-discovery anti-collision pattern as the iguanatrader main API). The sidecar's OpenAPI schema SHALL NOT be merged into iguanatrader's monolith `/openapi.json` — it is a private internal API.

#### Scenario: Health endpoint returns 200 with openbb readiness flag

- **WHEN** a client GETs `http://openbb_sidecar:8765/health` (from inside the docker-compose network)
- **THEN** the response is `200 OK` with body `{"status": "ok", "openbb_loadable": <bool>, "version": "<sidecar-version>"}`
- **AND** the response is `200` even when `openbb_loadable: false` (a 5xx /health would mean the FastAPI process itself is dead; readiness is a flag, not an HTTP status)

#### Scenario: Equity fundamentals endpoint returns canonical fields

- **WHEN** a client GETs `http://openbb_sidecar:8765/v1/equity/fundamentals/AAPL`
- **AND** the OpenBB SDK returns successfully
- **THEN** the response is `200 OK` with at minimum the keys `symbol`, `pe_ratio`, `market_cap`, `dividend_yield`, `as_of_date`
- **AND** unknown symbol returns `404 Not Found` with structured detail
- **AND** OpenBB SDK upstream error returns `502 Bad Gateway` with structured detail

#### Scenario: Adding a new endpoint requires a new slice

- **WHEN** R5 (or a later slice) needs `GET /v1/news/{symbol}` from OpenBB
- **THEN** that slice creates `apps/openbb-sidecar/src/openbb_sidecar/routes/news.py` exporting `router: APIRouter`
- **AND** the dynamic-discovery loop in `routes/__init__.py` picks it up automatically with no edits to existing files
- **AND** the spec.md for that slice documents the new endpoint contract

### Requirement: Sidecar healthcheck + monolith retry contract

The system SHALL gate the iguanatrader `api` service's startup on the sidecar's docker healthcheck via `depends_on: { openbb_sidecar: { condition: service_healthy } }` in all three runtime compose profiles (dev, paper, live). The healthcheck SHALL poll `GET /health` on `interval: 10s`, `timeout: 5s`, `retries: 12`, `start_period: 60s` (dev) / `90s` (paper) / `120s` (live). The monolith's `OpenBBSidecarSource` adapter SHALL implement retry/backoff per the canonical schedule `[3, 6, 12, 24, 48]` seconds (from `iguanatrader.shared.backoff`) and inherit `HeartbeatMixin` from `iguanatrader.shared.heartbeat` for liveness pings.

#### Scenario: Sidecar slow to warm up

- **WHEN** `docker compose up -d` boots both services from cold
- **AND** OpenBB SDK first-import takes 10 seconds inside the sidecar container
- **THEN** the sidecar's docker healthcheck reports `(starting)` for ~10s, then `(healthy)`
- **AND** the api service waits for `(healthy)` before its own container starts
- **AND** when the api process eventually issues its first sidecar request, the sidecar responds 200

#### Scenario: Sidecar transient 5xx during operation

- **WHEN** the monolith adapter receives a `503 Service Unavailable` from the sidecar
- **THEN** the adapter sleeps 3 seconds and retries
- **AND** if still 5xx, sleeps 6 seconds, then 12, then 24, then 48 (canonical schedule from slice 2)
- **AND** if all 5 attempts fail, raises `IntegrationError("openbb sidecar 5xx after 5 attempts")`
- **AND** emits structlog `research.openbb_sidecar.unreachable` with full backoff trace

#### Scenario: Sidecar 4xx — terminal client error, no retry

- **WHEN** the adapter receives `404 Not Found` for an unknown symbol
- **THEN** the adapter does NOT retry (4xx is terminal — retrying will not change the answer)
- **AND** logs structlog `research.openbb_sidecar.client_error` at WARN level with the symbol + status
- **AND** the `fetch()` method yields nothing for that endpoint, returns gracefully
- **AND** the caller (R5) does not see an exception; brief synthesis continues with the missing fact handled by partial-brief logic

#### Scenario: Adapter disabled via env var

- **WHEN** the monolith is started with `OPENBB_SIDECAR_ENABLED=false`
- **AND** R5 (or the integration test) invokes `OpenBBSidecarSource(...).fetch("AAPL", since=None)`
- **THEN** the adapter yields nothing without making any HTTP calls
- **AND** the sidecar service may be entirely absent from the compose profile without affecting the monolith's boot
- **AND** R5 brief synthesis simply omits OpenBB-tier facts from the brief

### Requirement: Sidecar carries its own LICENSE file (AGPL-3.0 v3 verbatim) separate from the root repository LICENSE

The system SHALL ship `apps/openbb-sidecar/LICENSE` containing the AGPL-3.0 v3 license text verbatim. This file SHALL be distinct from the repository root `LICENSE` (Apache-2.0 + Commons Clause v1.0) and SHALL be included in the sidecar Docker image (NOT excluded by `.dockerignore`). The sidecar's `pyproject.toml` SHALL declare `license = "AGPL-3.0-or-later"` (SPDX identifier). The sidecar's `README.md` SHALL include an explicit attribution to OpenBB Platform with a link to the upstream repository and a one-paragraph explanation of the iguanatrader boundary intent (linking to ADR-015).

#### Scenario: Sidecar Docker image contains the LICENSE

- **WHEN** the operator runs `docker run --rm iguanatrader/openbb-sidecar:dev cat /app/LICENSE` (or equivalent path)
- **THEN** the AGPL-3.0 v3 text is printed
- **AND** the image is in compliance with AGPL §13's source-availability requirement (the sidecar source is in this monorepo under `apps/openbb-sidecar/`)

#### Scenario: SBOM correctly tags sidecar AGPL packages

- **WHEN** `build-images.yml` (slice 1) runs `cyclonedx-py` against `apps/openbb-sidecar/poetry.lock`
- **THEN** the resulting `sbom.json` for the sidecar image lists the `openbb` family with `licenses: [{license: {id: "AGPL-3.0-or-later"}}]`
- **AND** the `apps/api/poetry.lock`-derived SBOM for the api image contains zero packages with AGPL licenses (double-redundant with the `agpl-boundary` CI job)
