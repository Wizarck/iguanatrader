---
adr: 015
date: 2026-04-28
status: accepted
status-changed: 2026-05-06
decided-by: Arturo Ramírez (arturo6ramirez@gmail.com)
tags: [research, openbb, license-boundary, agpl, sidecar]
---

# ADR-015 — OpenBB sidecar isolation (AGPL-3.0 boundary)

## Status

**Accepted** as of 2026-05-06 with the merge of slice R4 (`openbb-sidecar-container`). The full implementation body is now this ADR; the original "Stub" section is preserved below for historical context.

## Context

OpenBB SDK ([OpenBB Platform](https://github.com/OpenBB-finance/OpenBBTerminal)) is licensed **AGPL-3.0-or-later**. iguanatrader is licensed **Apache-2.0 + Commons Clause v1.0**. The two licenses are not compatible for direct linkage:

- AGPL §13 ("Remote Network Interaction") imposes derivative-work obligations on any network service that contains AGPL-licensed code, requiring source disclosure to all users interacting with the service.
- Importing `openbb` as a Python module into the iguanatrader monolith would make the monolith a derivative work of OpenBB, virally re-licensing it under AGPL — incompatible with the Commons Clause overlay (which restricts commercial-resale rights that AGPL forbids restricting).

iguanatrader needs OpenBB's data surface (equity fundamentals, analyst estimates, ESG, FRED macro series) for the research synthesis layer (R5). Without isolation, the project either (a) drops OpenBB and re-implements every provider, (b) re-licenses to AGPL, or (c) finds a clean boundary.

## Decision

**(c)** — run OpenBB as an **isolated process** in its own container with its own dependency tree, communicating with the iguanatrader monolith only over HTTP. This is the standard "sidecar" pattern for crossing license boundaries.

### Boundary mechanics

1. **Filesystem isolation**: the sidecar lives at `apps/openbb-sidecar/` with its own `pyproject.toml`, `poetry.lock`, `LICENSE` (AGPL-3.0 verbatim from gnu.org), `Dockerfile`. The monolith at `apps/api/` has its own dep tree; openbb is never declared, never resolved, never imported there.
2. **Process isolation**: the sidecar is a separate container. In dev: `docker-compose` service `openbb_sidecar`. In paper/live: same container image, but orchestrated by k8s + Rancher Fleet once the `deployment-foundation` slice helmifies the whole stack (api + sidecar + litestream + frontend) together. Container image embeds the AGPL LICENSE per AGPL §13.
3. **Network isolation**: HTTP-loopback only. Compose: `expose: ["8765"]`, no host port binding. When the k8s deployment slice lands the equivalent contract is `Service type: ClusterIP` + NetworkPolicy ingress restricted to the monolith Pod by label match. Either way: the sidecar is reachable only from the monolith, never from outside the runtime boundary.
4. **Code isolation**: the iguanatrader monolith implements `OpenBBSidecarSource` (a `SourcePort` adapter) at `contexts/research/sources/openbb_sidecar.py`. It uses `httpx.Client` to call the sidecar's `/v1/equity/fundamentals/{symbol}` etc. — no `import openbb` anywhere in `apps/api/`.

### CI enforcement

The license-boundary check (`.github/workflows/license-boundary-check.yml` `agpl-boundary` job) runs three independent surface scans on every push/PR to main:

1. **Surface 1**: `grep -iE '^\s*openbb' apps/api/pyproject.toml` — catches `poetry add openbb`.
2. **Surface 2**: `grep -iE '^name = "openbb' apps/api/poetry.lock` — catches transitive AGPL drag-in.
3. **Surface 3**: `grep -RnE '^(from|import)\s+openbb(\.|$|\s)' apps/api/src/ packages/` — catches a hand-edit that bypasses the dep manager.

The same three surfaces also reject `yfinance` direct deps + imports — yfinance is the OpenBB Platform default provider for fundamentals/ESG, and per design D7 of slice R4 its access path goes through the sidecar (`YFinanceProxySource`) so the dependency chain stays inside the AGPL boundary.

Failure of any single surface fails the gate with `::error::` and a structured fix message naming the canonical access path.

## Consequences

**Positive**:
- iguanatrader stays Apache-2.0 + Commons Clause cleanly. AGPL obligations are confined to the sidecar (which is correctly licensed AGPL-3.0).
- Sidecar can be replaced or upgraded independently (e.g. pin to a specific OpenBB release) without coupling to the monolith's dependency upgrade cycle.
- License-boundary regression risk is automated away: the CI gate fails red the moment any of the three surfaces leak.
- Performance: HTTP-loopback over localhost (compose) or in-cluster Service DNS (k8s) is sub-millisecond — the boundary cost is negligible relative to the openbb call latency itself.

**Negative**:
- Operations cost: one extra container to deploy, monitor, and resource-reserve. Resource caps are documented (idle ~500 MB, peak ~1.5 GB; `requests cpu 500m memory 1Gi` / `limits cpu 1 memory 2Gi` — see `docs/architecture-decisions.md` §"OpenBB Sidecar Topology" L428).
- Startup latency: openbb is lazy-imported on first call (~5-15s cold). Mitigated via k8s `readinessProbe.initialDelaySeconds` + docker `HEALTHCHECK --start-period=60s`. Documented as gotcha #75.
- Operator footgun: if someone switches `expose:` → `ports:` (compose) or `ClusterIP` → `NodePort` (k8s), the sidecar becomes externally reachable and the AGPL obligations against external users start applying. Documented as gotcha #76.

**Neutral**:
- The sidecar's `OpenBBFacade` is the only module that imports openbb. Future replacement (e.g. dropping openbb in favor of direct yfinance + fmp + alpha-vantage clients) is a one-file edit.

## Cross-references

- `apps/openbb-sidecar/` — sidecar code + Dockerfile + LICENSE.
- `apps/api/src/iguanatrader/contexts/research/sources/openbb_sidecar.py` — monolith client.
- `apps/api/src/iguanatrader/contexts/research/sources/yfinance_proxy.py` — yfinance access via sidecar.
- `docker-compose.yml` — dev profile sidecar service.
- `.github/workflows/license-boundary-check.yml` — CI gate (3 independent surfaces).
- `docs/architecture-decisions.md` — §"OpenBB Sidecar Topology" + §"CD / deployment automation".
- `docs/project-structure.md` §13 — directory layout.
- `docs/gotchas.md` #75 (lazy-import readiness), #76 (port binding isolation), #77 (yfinance ban).
- `openspec/changes/archive/2026-05-XX-openbb-sidecar-container/` — slice R4 implementation record.
- Future `deployment-foundation` slice — will helmify api + sidecar + litestream + frontend together via Rancher Fleet (eligia-core/helm/eligia-stack pattern). Out of scope for R4.

## Original Stub (preserved)

> OpenBB SDK is licensed AGPL-3.0. iguanatrader is licensed Apache-2.0 + Commons Clause. The two licenses are not compatible for direct linkage: AGPL would virally re-license iguanatrader's main monolith if we imported `openbb` as a Python module.
>
> The mitigation: run OpenBB as a separate Docker container exposing an HTTP API on `localhost`. The iguanatrader monolith talks to it via plain HTTP (no Python imports of AGPL code). The container itself is licensed AGPL-3.0; the host monolith stays Apache+CC. This is the standard "sidecar" pattern for crossing license boundaries.
>
> The CI workflow `license-boundary-check.yml` (slice 1) declares the boundary; slice R4 fleshes it out with a real `apps/api/src/` scan that fails CI on any `from openbb…` import.
