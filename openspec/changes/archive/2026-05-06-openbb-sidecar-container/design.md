## Context

Slice R4 lands the **AGPL-3.0 license-isolation pillar** of the iguanatrader research domain. Wave 0 + Wave 2 cumulative state at slice-R4 start:

- Slice 1 `bootstrap-monorepo` ✅ — LICENSE (Apache-2.0 + Commons Clause v1.0), `license-boundary-check.yml` workflow (with `agpl-boundary` job stubbed as no-op until this slice), reserved `apps/openbb-sidecar/` directory in `docs/project-structure.md` §11.
- Slice 2 `shared-primitives` ✅ — `HeartbeatMixin`, canonical backoff `[3, 6, 12, 24, 48]`, `IntegrationError` for upstream-unreachable signalling, `IguanaError` hierarchy + RFC 7807 rendering.
- Slice 5 `api-foundation-rfc7807` ✅ — dynamic-discovery for routes / SSE / CLI; the monolith's HTTP client lands as a `SourcePort` adapter that does NOT need to register a route (R5 owns `/research/*`).
- Slice R1 `research-bitemporal-schema` ✅ — `SourcePort` Protocol, `ResearchFactDraft.with_payload()`, `ResearchRepository.insert_fact()` with bitemporal supersession + provenance enforcement + hybrid payload-tier dispatch.

The decision space is dominated by **legal compliance**, not technical architecture. The OpenBB SDK is an excellent piece of software — and it is licensed AGPL-3.0. The "viral" property of the AGPL is its §13 "Remote Network Interaction" clause: any user interacting with the program over a network must be offered the corresponding source code. Combined with the conventional GPL §0 "based on" / §5 "modify" interpretation that dynamic linkage creates a derivative work, importing `openbb` as a Python module from `apps/api/` would re-license the entire iguanatrader monolith — including the parts under Apache-2.0 + Commons Clause — under AGPL-3.0 terms. That outcome is incompatible with our Commons Clause covenant (commercial-use restriction) and would force every deployment to publish source.

The mitigation is the **HTTP-loopback sidecar pattern**, the most widely-deployed AGPL-isolation strategy in industry: keep the AGPL software in its own process, expose it over a network protocol, and treat it as an external system. The legal interpretation that supports this is well-established: (a) AGPL §13 attaches to the program providing the network service, not to clients of the service — a plain HTTP client of an AGPL service is not itself an AGPL work; (b) the dynamic-linkage / derivative-work argument requires Python import-level coupling, which HTTP loopback eliminates by construction; (c) the sidecar binary is a separate work distributed under AGPL, with its own LICENSE file, and our distribution of the Docker image carries the AGPL obligation only for that image. We satisfy AGPL §13 by publishing the sidecar's complete source (it lives in this repo under `apps/openbb-sidecar/`); we do not satisfy AGPL §13 for the monolith because the monolith is not an AGPL work.

The challenge is **defensive enforcement**, not just topology. Anyone with commit access could accidentally type `import openbb` into `apps/api/src/...` and re-introduce the boundary violation. The CI gate (`license-boundary-check.yml`'s `agpl-boundary` job) is the single technical control that prevents this; it is a gate that MUST be hard-blocking, MUST scan three independent surfaces (declared deps, locked deps, source imports), and MUST be impossible to silence without an explicit, audit-trail-leaving override.

## Goals / Non-Goals

**Goals:**

- Stand up `apps/openbb-sidecar/` as an independent Poetry package with its own `pyproject.toml` (AGPL deps stay local), its own `LICENSE` file (AGPL-3.0 verbatim, separate from the root LICENSE), its own `Dockerfile` (multi-stage builder + runtime, Python 3.11), and its own pytest suite.
- Plant the sidecar's FastAPI surface — minimal endpoint set covering equity fundamentals / ratings / ESG and macro indicators, sufficient for R5 brief synthesis.
- Plant the monolith's HTTP client adapter (`OpenBBSidecarSource` implementing `SourcePort`) with retry/backoff, heartbeat, and graceful degradation when the sidecar is unreachable.
- Wire the sidecar into all three runtime docker-compose profiles (dev, paper, live) with a healthcheck-based `depends_on` so the API service waits for sidecar readiness.
- **Replace the slice-1 license-boundary-check placeholder with three real, hard-blocking CI assertions**: declared deps (`pyproject.toml` grep), locked deps (`poetry.lock` parse), and source imports (`apps/api/src/`, `packages/` ripgrep).
- Add a sidecar README explaining the AGPL-3.0 license + boundary intent + ADR-015 link, so future contributors understand WHY the package is structured the way it is.

**Non-Goals:**

- No R5 brief synthesis consumption of the new adapter (R5 lands its own slice; until then R5 mocks `SourcePort` during dev).
- No k3s / Kubernetes manifests — docker-compose is the v1 deployment unit. k3s manifests with `requests/limits` per architecture-decisions.md §"OpenBB Sidecar Topology" land in v1.5 deploy slice.
- No sidecar API authentication — the sidecar binds only to the docker-compose internal network (NOT host `0.0.0.0`), so loopback-only is the security boundary. If a future deployment exposes the sidecar beyond loopback, add HMAC per-tenant token + scope to the request.
- No multi-version OpenBB rolling upgrade — single pinned version per release; bumps are their own slice.
- No SBOM generation pipeline changes — slice 1's `build-images.yml` already runs `cyclonedx-py`; this slice trusts that pipeline to emit a per-image SBOM that correctly tags the sidecar image as AGPL-3.0 vs the api image as Apache-2.0+CC.
- No `openbb` SDK direct imports anywhere in `apps/api/`, `packages/`, or any non-sidecar code path — this is the central invariant the slice enforces.

## Decisions

### D1. Two-container topology on the docker-compose internal network

**Decision**: `apps/openbb-sidecar/` is a fully separate Poetry project (its own `pyproject.toml`, `poetry.lock`, `Dockerfile`, `LICENSE`, pytest suite). The `Dockerfile` produces an image `iguanatrader/openbb-sidecar:<env>`. The compose files (`docker-compose.yml`, `docker-compose.paper.yml`, `docker-compose.live.yml`) declare the sidecar as a service alongside the existing `api` service. They share the default docker-compose bridge network; the sidecar exposes port `8765` only on that internal network (NOT bound to host `0.0.0.0`). The `api` service has `depends_on: { openbb_sidecar: { condition: service_healthy } }` so the API waits for the sidecar's healthcheck to pass before starting.

**Alternatives considered**:

- **Single container, dual venv**: install `openbb` into a separate Python virtualenv inside the same container and shell out via subprocess. Rejected — the AGPL-isolation argument depends on dynamic-linkage absence at the *process* level, not the venv level. Subprocess works but Docker is the canonical pattern + gives us proper resource isolation + healthchecks.
- **OpenBB as an external service** (e.g., OpenBB Cloud): adds a network dependency we don't control, breaks the offline-paper-trading story, and OpenBB Cloud's API is paid + rate-limited. The sidecar pattern keeps everything local.
- **Run OpenBB in a Lambda / Function-as-a-Service**: same isolation guarantee, more operational overhead, no benefit. Rejected.

**Rationale**: Docker container = process boundary = no dynamic linkage = AGPL clean separation. docker-compose internal network = no exposed surface area = no auth needed. Healthcheck-based `depends_on` = boot-order correctness without polling.

### D2. Sidecar FastAPI surface is the *minimum* iguanatrader needs — not the OpenBB API mirrored

**Decision**: the sidecar exposes only `GET /health`, `GET /v1/equity/fundamentals/{symbol}`, `GET /v1/equity/ratings/{symbol}`, `GET /v1/equity/esg/{symbol}`, `GET /v1/economy/macro/{indicator}`. Future expansion is on demand (e.g., when R5 brief synthesis identifies a missing data point). Each endpoint is a thin async wrapper that delegates to `adapters/openbb_facade.py`, which is the **only** place inside the sidecar that imports `openbb`.

**Alternatives considered**:

- **Mirror the entire OpenBB Platform API**: massive surface, mostly unused, slows cold start. Rejected — YAGNI, also makes the boundary harder to audit (more surface = more attack vectors for upstream vulnerabilities).
- **Generic `/v1/openbb/<path>` passthrough proxy**: opaque, hard to mock in tests, leaks OpenBB's evolving URL shape into iguanatrader's research adapter. Rejected.

**Rationale**: explicit endpoints = explicit contract. The five endpoints listed cover everything R5 brief synthesis needs from the OpenBB ecosystem (per `docs/data-sources-catalogue.md`). When R5 (or a later slice) needs more, that slice adds the endpoint — same dynamic-discovery pattern as iguanatrader's main API (slice 5 D1).

**Endpoint contract** (smoke-level; full schema in spec.md):
- `GET /health` → 200 `{"status": "ok", "openbb_loadable": bool, "version": "<openbb-version>"}` always; never 5xx (a 5xx /health means the service is dead).
- `GET /v1/equity/fundamentals/{symbol}` → 200 with at least `symbol`, `pe_ratio`, `market_cap`, `dividend_yield`, `as_of_date` keys; 404 on unknown symbol; 502 on upstream OpenBB error (sidecar wraps `openbb` exceptions).
- `GET /v1/equity/ratings/{symbol}` → 200 with `symbol`, `consensus`, `target_price`, `analyst_count`, `as_of_date`.
- `GET /v1/equity/esg/{symbol}` → 200 with `symbol`, `esg_score`, `environmental_score`, `social_score`, `governance_score`, `as_of_date`.
- `GET /v1/economy/macro/{indicator}` → 200 with `indicator`, `series` (list of `{date, value}`), `unit`, `frequency`.

### D3. Monolith client `OpenBBSidecarSource` implements R1's `SourcePort` Protocol

**Decision**: `apps/api/src/iguanatrader/contexts/research/sources/openbb_sidecar.py` defines `class OpenBBSidecarSource:` whose `fetch(symbol, since)` method returns an iterable of `ResearchFactDraft`. The class uses `httpx.AsyncClient` (one shared instance, not per-call), targets `localhost:8765` (configurable via `OPENBB_SIDECAR_URL` env var, defaults to `http://localhost:8765`), applies the canonical exponential backoff `[3, 6, 12, 24, 48]` from `iguanatrader.shared.backoff`, and inherits `HeartbeatMixin` from `iguanatrader.shared.heartbeat` to ping `/health` every 30s when the daemon is running.

**Failure-mode behaviour** (matches R1's `SourcePort` contract):

- HTTP 5xx response → retry per backoff schedule. If all 5 attempts fail → raise `IntegrationError("openbb sidecar 5xx after 5 attempts")`.
- HTTP 4xx response (404, 422, etc.) → log structlog `research.openbb_sidecar.client_error` at WARN, return empty iterable (do not retry — 4xx is a terminal client-side issue; the symbol is unknown to OpenBB or the request is malformed).
- Connection error / timeout → retry per backoff schedule. After final attempt → log `research.openbb_sidecar.unreachable` at WARN and raise `IntegrationError`. Caller (R5) catches and marks brief `partial=true`.
- 200 OK → JSON-parse the body, hash it via `with_payload(payload_bytes)` for hybrid-storage tier dispatch, build `ResearchFactDraft` with `source_id="openbb-sidecar"`, `source_url=f"http://localhost:8765/v1/equity/fundamentals/{symbol}"` (or whichever endpoint), `retrieval_method="http_get"`, `retrieved_at=utc_now()`, `effective_from=as_of_date`, `recorded_from=utc_now()`, `value_jsonb=<parsed body>`. Yield one draft per logical fact (e.g., one for fundamentals, one for ratings, one for ESG when bulk-fetched).

**Alternatives considered**:

- **httpx sync client + thread offload**: simpler but blocks the asyncio event loop. Rejected — every other source adapter is async; consistency wins.
- **gRPC instead of HTTP+JSON**: more efficient on the wire but adds protobuf tooling + breaks the "every adapter is HTTP" mental model. Rejected for MVP; revisit if perf requires.
- **Per-symbol `httpx.AsyncClient`**: connection-pool churn. Rejected — one shared client per source instance.

**Rationale**: implements R1's existing `SourcePort` Protocol verbatim, so the repository's `insert_fact` path consumes OpenBB facts identically to EDGAR / FRED facts. No special-casing in the upstream pipeline.

### D4. The `agpl-boundary` CI job scans **three independent surfaces** — declared deps, locked deps, source imports

**Decision**: the slice-1 placeholder no-op in `.github/workflows/license-boundary-check.yml`'s `agpl-boundary` job is replaced with three real assertions running in sequence:

```yaml
- name: Assert no AGPL declared in apps/api/pyproject.toml
  run: |
    if grep -iE '^\s*openbb' apps/api/pyproject.toml; then
      echo "::error::AGPL violation: openbb dep found in apps/api/pyproject.toml"
      exit 1
    fi

- name: Assert no AGPL packages in apps/api/poetry.lock
  run: |
    if grep -iE '^name = "openbb' apps/api/poetry.lock; then
      echo "::error::AGPL violation: openbb-* package found in apps/api/poetry.lock"
      exit 1
    fi

- name: Assert no openbb imports in apps/api/src/ or packages/
  run: |
    # ripgrep with PCRE2 to match any `from openbb...` or `import openbb...`
    if rg -nE '^(from|import)\s+openbb(\.|$|\s)' apps/api/src/ packages/ 2>/dev/null; then
      echo "::error::AGPL violation: openbb import found in monolith source"
      exit 1
    fi
```

**Alternatives considered**:

- **Single grep on source only**: misses transitive deps that might pull `openbb` in unexpectedly via a misnamed pyproject entry. Rejected — defence in depth.
- **License scanner (e.g., `licensee`, `pip-licenses`)**: heavier, slower, and we don't need full SPDX classification; we need a yes/no for one specific package family. Rejected for this gate (SBOM step in `build-images.yml` does the full scan).
- **ruff custom rule**: works for source imports but doesn't catch declared/locked deps. Could be additive (slice O1 may add it) but is not sufficient alone.

**Rationale**: declared deps catch `pyproject.toml` typos before lock; locked deps catch transitives Poetry resolves automatically; source imports catch the developer who skipped `poetry add` and just `pip install openbb`-d into their venv. All three surfaces would have to fail simultaneously for a violation to slip through.

**Audit trail**: the workflow's GitHub Actions run is itself the audit log. Any override (e.g., `[skip ci]` or branch protection bypass) is logged + visible in PR history. There is no `--no-verify` equivalent at the workflow level when branch protection is configured (slice O1 hardens this).

### D5. Sidecar uses a single thin facade over the OpenBB SDK; routes never import `openbb` directly

**Decision**: `apps/openbb-sidecar/src/openbb_sidecar/adapters/openbb_facade.py` is the **only** module inside the sidecar that imports `openbb`. The `routes/{equity,economy}.py` modules import `OpenBBFacade` and call methods on it. This makes the AGPL-import boundary easy to audit even within the sidecar — anyone reading the codebase sees `openbb` mentioned in exactly one place.

**Alternatives considered**:

- **Routes import openbb directly**: works, but spreads the AGPL surface. If we later need to swap implementations (e.g., test with a fake), every route changes. Rejected.
- **Generic registry / plugin system**: over-engineered for a 5-endpoint surface. Rejected for MVP.

**Rationale**: classic facade pattern. One place to mock for tests, one place to upgrade when OpenBB releases a breaking change, one place to audit for license-boundary purposes.

### D6. Sidecar `pyproject.toml` declares `license = "AGPL-3.0-or-later"` SPDX; root stays Apache-2.0 + LicenseRef-Commons-Clause

**Decision**: the sidecar's `pyproject.toml` `[tool.poetry]` block sets `license = "AGPL-3.0-or-later"` (the SPDX identifier). The root `pyproject.toml` (slice 1) declares `license = "Apache-2.0 AND LicenseRef-Commons-Clause"` (composite SPDX expression). The `apps/openbb-sidecar/LICENSE` file contains the full AGPL-3.0 text verbatim, sourced from https://www.gnu.org/licenses/agpl-3.0.txt. The `apps/openbb-sidecar/README.md` opens with a one-line attribution: "This sidecar embeds OpenBB Platform (https://github.com/OpenBB-finance/OpenBBTerminal), licensed AGPL-3.0. The iguanatrader monolith communicates with this sidecar exclusively over HTTP loopback per ADR-015 to preserve license compatibility with iguanatrader's Apache-2.0 + Commons Clause v1.0 licensing."

**SBOM tagging**: when `build-images.yml` runs `cyclonedx-py` against the sidecar's `poetry.lock`, the resulting `sbom.json` correctly inherits the SPDX classifier from each package. The OpenBB family resolves to AGPL-3.0; FastAPI/uvicorn/httpx resolve to MIT/BSD/Apache; the sidecar itself resolves to AGPL-3.0-or-later. The `api` image's SBOM (separate scan against `apps/api/poetry.lock`) MUST contain zero AGPL packages — this is double-redundant with the `agpl-boundary` CI job but useful for downstream attestation (e.g., Sigstore signing in v1.5).

**Rationale**: SPDX is the lingua franca for license expression in modern toolchains (cyclonedx, pip-licenses, GitHub Dependency Graph). Declaring it correctly upfront avoids manual classification later.

### D7. yfinance fundamentals/ratings/ESG flow through the OpenBB sidecar, not via direct yfinance import in the monolith

**Decision**: `apps/api/src/iguanatrader/contexts/research/sources/yfinance_proxy.py` calls the OpenBB sidecar's `/v1/equity/fundamentals/{symbol}` etc. endpoints (which internally route to OpenBB's yfinance integration). The monolith does NOT add `yfinance` as a direct dep.

**Alternatives considered**:

- **Direct yfinance import in `apps/api/`**: yfinance is Apache-2.0, no license issue. But it is unmaintained-ish, scrape-fragile, and mixing it with the OpenBB-sourced yfinance creates two code paths for the same data. Rejected.
- **Skip yfinance entirely**: fundamentals are critical for R5 brief synthesis. Yahoo's free tier is the only no-cost source for non-US-listed equities. Rejected.

**Rationale**: one HTTP egress surface for all OpenBB-ecosystem data sources. Simpler observability, simpler retry policy, simpler cost accounting.

### D8. Healthcheck = readiness probe, NOT liveness probe — sidecar boots OpenBB lazily

**Decision**: `GET /health` returns 200 only when `openbb_facade.is_ready()` is `True`, where `is_ready()` returns the cached result of `try: import openbb except: return False`. The import happens on first call (lazy), so a cold container boot can take 5-10s before the healthcheck passes (OpenBB's import-time cost is non-trivial). docker-compose's `healthcheck` block is configured with `interval: 10s`, `timeout: 5s`, `retries: 12`, `start_period: 60s` — giving the sidecar up to 2 minutes to warm up before the API service's `depends_on` clause considers it failed.

**Alternatives considered**:

- **Eager import at startup**: container boot fails entirely if OpenBB import fails (e.g., missing transitive dep). Worse failure mode — operator sees the container restarting in a loop instead of a failing healthcheck with a clear `/health` body.
- **No readiness gating, just liveness**: API service starts before sidecar is ready, first OpenBB call fails, retry kicks in. Works but adds noise. Rejected.

**Rationale**: lazy-import + health-gated startup = clean boot semantics. The `/health` body's `openbb_loadable: false` field tells the operator exactly what's wrong if the readiness check times out.

### D9. Sidecar's own pytest suite runs in its own Poetry env; CI matrix runs both side-by-side

**Decision**: `apps/openbb-sidecar/tests/{unit,integration}/` is a self-contained pytest suite. CI's `ci.yml` (slice 1) gains a new job `sidecar-tests` that runs `cd apps/openbb-sidecar && poetry install && poetry run pytest`. The monolith's `pytest apps/api/tests/integration/test_openbb_sidecar_client.py` runs against either a mock httpx transport (default, fast) or a live sidecar fixture (opt-in via `pytest -m sidecar_live` env flag, which boots the docker-compose `openbb_sidecar` service before the test session).

**Rationale**: AGPL-3.0 obligations attach to the sidecar code; the sidecar must therefore be testable in isolation as a complete piece of software. Separation also enforces that the monolith's tests cannot accidentally import sidecar code (different venv).

### D10. Configuration via pydantic-settings, env vars only — no SOPS for the sidecar in MVP

**Decision**: `apps/openbb-sidecar/src/openbb_sidecar/config.py` uses `pydantic-settings` to read `OPENBB_SIDECAR_HOST` (default `0.0.0.0` *inside* the container — bound only to the internal docker network), `OPENBB_SIDECAR_PORT` (default `8765`), `OPENBB_SIDECAR_LOG_LEVEL` (default `INFO`). No SOPS layer because the sidecar handles no secrets (OpenBB-Platform free tier endpoints suffice for fundamentals/ratings/ESG/macro queries). If a future endpoint requires an OpenBB Pro API key, that key flows in via SOPS-decrypted env at compose-up time + `pydantic-settings` reads it.

**Rationale**: simpler boot, fewer attack surfaces, fewer moving parts. SOPS layering can be added in a follow-up slice when there's an actual secret to protect.

## Risks / Trade-offs

- **[Risk] OpenBB SDK transitive deps include something AGPL-incompatible** (e.g., a sub-package with a more restrictive license) → the sidecar's own LICENSE compliance breaks. **Mitigation**: SBOM scan on `apps/openbb-sidecar/poetry.lock` in `build-images.yml`; flag any non-OSI-approved license. The project's `THIRD_PARTY_NOTICES.md` (slice 1) is updated with the sidecar's transitive-dep license summary on every OpenBB pin bump.

- **[Risk] OpenBB SDK breaking API change at next minor version bump** → sidecar `openbb_facade.py` breaks; routes return 502; monolith adapters mark partial=true. **Mitigation**: pin `openbb = "<minor>.<patch>"` (exact, not range) in sidecar `pyproject.toml`; OpenBB upgrades are an explicit, bounded slice. Sidecar's own integration tests catch upstream breakage at CI time.

- **[Risk] License-boundary CI job has a false negative — e.g., a creative import disguise (`importlib.import_module("openbb")`) sneaks past the regex** → AGPL leak undetected. **Mitigation**: the regex is intentionally conservative (matches `from openbb`, `import openbb`); dynamic imports via string would be a new attack vector. Slice O1 hardens with a Python AST-based scanner (parses each file, checks `Import` / `ImportFrom` nodes for any `openbb` reference). For MVP, the regex + code review catches 99%.

- **[Risk] Healthcheck timeout in CI environments** (OpenBB's first import on a slow CI runner can exceed 60s `start_period`) → integration test flakes. **Mitigation**: `start_period: 120s` in test compose profile; CI runner is x86_64 Linux with ample CPU; OpenBB import benchmarked at ~7-12s on standard runners. If flakes appear, increase `start_period`.

- **[Risk] Sidecar bound to `0.0.0.0` inside container could leak via misconfigured host networking** → `localhost:8765` accidentally reachable from outside. **Mitigation**: docker-compose `ports:` block intentionally omitted (only `expose:` is used) so the port is not bound to the host's network namespace. Documented gotcha + verification step in `tasks.md` (`docker compose port openbb_sidecar 8765` should return empty / `<no entry>`). For k3s deployment (v1.5), use a `ClusterIP` Service, never `NodePort`/`LoadBalancer`.

- **[Risk] yfinance-via-OpenBB rate limits more aggressive than direct yfinance** → ESG / fundamentals fetch fails with 429 more often. **Mitigation**: monolith adapter respects backoff; R5 brief synthesis gracefully marks `partial=true`. If empirically the rate limit is too tight, fall back to direct yfinance (still Apache-2.0, no license issue) — but only inside the sidecar; iguanatrader-proper still talks HTTP loopback.

- **[Trade-off] Two-container deployment adds operational surface** → operator now runs `docker compose ps` and sees two services, both must be healthy. Slightly more cognitive load, slightly more memory footprint (~500-800 MB idle for the sidecar per architecture-decisions.md profiling). For MVP single-VPS deploy on Hetzner CAX31 (16 GB RAM), this is comfortably within budget.

- **[Trade-off] AGPL-isolation via HTTP boundary is a *legal interpretation*, not a court-tested guarantee** → in the unlikely event of FSF / OpenBB-author litigation, a court could rule differently. **Mitigation**: this is the industry-standard interpretation (e.g., MongoDB SSPL ↔ AWS DocumentDB controversy hinged on a similar boundary; numerous AGPL-licensed databases run as sidecars in commercial SaaS without issue). ADR-015 documents the rationale; if legal counsel later flags concerns, the sidecar is opt-out (the system functions without it, R5 briefs just lose OpenBB-tier facts and mark partial=true).

## Migration Plan

This slice has no live deployment to migrate from. Deployment path:

1. Merge slice R4 to main.
2. CI re-runs on main: `agpl-boundary` job now passes (no leakage); `build-images.yml` builds + pushes `iguanatrader/openbb-sidecar:dev` to GHCR alongside the existing `iguanatrader/api:dev`.
3. Operator pulls the updated repo, runs `docker compose up`. Sidecar boots, healthcheck passes after ~30-60s, API starts.
4. R5 (when it lands) consumes `OpenBBSidecarSource` via the existing `SourcePort` Protocol; brief synthesis pulls fundamentals/ratings/ESG facts from the sidecar.
5. If the sidecar is intentionally disabled (e.g., resource-constrained dev), set `OPENBB_SIDECAR_ENABLED=false` (env flag added in this slice's `apps/api/src/iguanatrader/contexts/research/sources/openbb_sidecar.py::OpenBBSidecarSource.__init__`); the adapter returns empty iterables without making HTTP calls.

Rollback = revert PR. No DB schema changes (R1 already landed `research_facts`); no API surface changes in the monolith. Removing the sidecar service from compose + the two adapter files restores the pre-R4 state. The `license-boundary-check.yml` workflow's `agpl-boundary` job becomes a placeholder again (gate exists but scans nothing), which is acceptable as the `apps/api/` deps remain AGPL-clean by construction.

## Open Questions

- **Q**: Should the sidecar's `/health` body include a per-endpoint readiness map (e.g., `{"equity_fundamentals": true, "economy_macro": false}`) to surface partial degradation? **Tentative answer**: no for MVP — single `openbb_loadable` boolean is sufficient; OpenBB itself is monolithic from the import perspective. If empirically we see endpoint-specific upstream failures, slice O2 may add granular reporting.

- **Q**: Should the monolith's `OpenBBSidecarSource` cache responses (e.g., 1h TTL) to reduce sidecar load on R5 brief refresh storms? **Tentative answer**: no — the bitemporal `research_facts` table is itself the cache (recorded_from cursor + supersession dedup); adding a second layer adds complexity without clear benefit. R5 explicitly opts to refresh; if rate-limited, brief marks partial=true. Revisit if production telemetry shows sidecar saturation.

- **Q**: Should we publish the `iguanatrader/openbb-sidecar:<tag>` image to a public registry (alongside Docker Hub / GHCR public)? **Tentative answer**: no for MVP — the AGPL distribution obligation only attaches when we *distribute* the binary. Internal-only GHCR push is fine; if we ever publish publicly, we must also publish the corresponding source (which we already do — it's in this monorepo). Documented as a v1.5 distribution-strategy concern.

- **Q**: When (if ever) should we add a non-Docker fallback for the sidecar (e.g., systemd unit, supervisord process)? **Tentative answer**: never for the iguanatrader project — Docker is the operational baseline. Operators who insist on bare-metal can run the sidecar directly via `poetry run uvicorn openbb_sidecar.main:app` against `apps/openbb-sidecar/` and point the monolith's `OPENBB_SIDECAR_URL` at it. Documented in the sidecar README.
