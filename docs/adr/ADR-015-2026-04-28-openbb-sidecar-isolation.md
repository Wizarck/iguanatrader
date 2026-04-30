---
adr: 015
date: 2026-04-28
status: proposed
decided-by: Arturo Ramírez (arturo6ramirez@gmail.com)
tags: [research, openbb, license-boundary, agpl, sidecar]
---

# ADR-015 — OpenBB sidecar isolation (AGPL-3.0 boundary)

## Status

**Proposed**. Recorded at Gate B (2026-04-28); full body lands when slice **R4** (`openbb-sidecar-container`) builds the isolated container — at which point this ADR transitions to `accepted`.

## Stub

OpenBB SDK (https://github.com/OpenBB-finance/OpenBBTerminal) is licensed AGPL-3.0. iguanatrader is licensed Apache-2.0 + Commons Clause. The two licenses are **not compatible** for direct linkage: AGPL would virally re-license iguanatrader's main monolith if we imported `openbb` as a Python module.

The mitigation: run OpenBB as a **separate Docker container** exposing an HTTP API on `localhost`. The iguanatrader monolith talks to it via plain HTTP (no Python imports of AGPL code). The container itself is licensed AGPL-3.0; the host monolith stays Apache+CC. This is the standard "sidecar" pattern for crossing license boundaries.

The CI workflow `license-boundary-check.yml` (slice 1) declares the boundary; slice R4 fleshes it out with a real `apps/api/src/` scan that fails CI on any `from openbb…` import.

## Cross-references

- `docs/architecture-decisions.md` — §"OpenBB Sidecar Topology" + §"External integrations".
- `docs/project-structure.md` §13 (`apps/openbb-sidecar/`) — directory layout.
- `.github/workflows/license-boundary-check.yml` — CI gate that this ADR governs.
- `docs/hitl-gates-log.md` — Gate A amendment 2026-04-28 (research domain decisions, including OpenBB sidecar).
- `docs/openspec-slice.md` row R4 — slice that lands the container.

## Full content

Pending. Slice R4's `proposal.md` + `design.md` + spec scenarios will populate this ADR's full Context / Decision / Consequences sections via the OpenSpec lifecycle.
