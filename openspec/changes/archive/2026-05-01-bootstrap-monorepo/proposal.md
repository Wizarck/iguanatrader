## Why

The 19 downstream slices of the iguanatrader MVP cannot start until the monorepo skeleton + tooling baseline exists: Python (Poetry) and Node (pnpm) workspaces, lint/format/type/test gates, multi-profile Docker compose, GitHub Actions workflows (CI, builds, OpenAPI types regen, license-boundary check), SOPS/age secrets layout, the Apache-2.0 + Commons Clause license, and the four ADR drafts (014-017) referenced by the Gate B architecture document. None of those drift back to a per-slice concern — they are repository-wide invariants that any slice's CI run depends on. This change establishes them once, sequentially, before Wave 1 can begin.

Per [docs/openspec-slice.md](../../../docs/openspec-slice.md) row 1, this is the head of Wave 0 (sequential foundation: bootstrap-monorepo → shared-primitives → persistence-tenant-enforcement) and a hard prerequisite for every other change.

## What Changes

- Add Poetry workspace root `pyproject.toml` (dev tooling: ruff, black, mypy strict, pytest, pytest-asyncio, hypothesis).
- Add pnpm workspace declaration (`pnpm-workspace.yaml` + workspaces array in existing `package.json`) declaring `apps/web` + `packages/shared-types` as members; existing `@fission-ai/openspec` devDep retained.
- Add root `Makefile` + `Makefile.includes` pattern (each subsequent slice owns its own `<path>/Makefile.includes`; root file uses `include`).
- Add four Docker compose files: `docker-compose.yml` (dev profile), `docker-compose.paper.yml`, `docker-compose.live.yml`, `docker-compose.test.yml`. Litestream service declared in dev/paper/live for SQLite continuous backup.
- Add four GitHub Actions workflows under `.github/workflows/`: `ci.yml` (lint + type + test + secrets-scan), `build-images.yml` (Docker images on tag), `openapi-types.yml` (regen `packages/shared-types/src/index.ts`), `license-boundary-check.yml` (skips with "n/a" until R4 lands `apps/openbb-sidecar/`).
- Add `.pre-commit-config.yaml`: gitleaks + ruff + black + mypy + check-toml + eslint stub + prettier stub + openapi-typescript regen + license-boundary check.
- Expand `.gitignore` (Python + Node + secrets + IDE + `data/` + `logs/` patterns), add `.gitleaksignore` (explicit safe-list), `.editorconfig`, `.dockerignore`.
- Add SOPS layout: `.secrets/.sops.yaml` (age recipients) + `.secrets/{dev,paper,live}.env.enc` template stubs.
- Add `LICENSE` (Apache-2.0 + Commons Clause v1.0, verbatim from canonical sources, checksum-verifiable).
- Add `SECURITY.md` (vuln disclosure policy), `CONTRIBUTING.md` placeholder, `CHANGELOG.md` initial entry, `README.md` (tagline + quickstart), `THIRD_PARTY_NOTICES.md` (initially empty).
- Add `docs/getting-started.md`: prereqs (Python 3.11+, Node 20+, pnpm 9+, Poetry 1.8+, Docker, JSON1 verify), install steps, paper-trading walkthrough placeholder.
- Add four ADR files (skeleton + `status: proposed`): `docs/adr/ADR-014-2026-04-28-bitemporal-research-facts.md`, `ADR-015-2026-04-28-openbb-sidecar-isolation.md`, `ADR-016-2026-04-28-research-domain-and-backtest-skip.md`, `ADR-017-2026-04-28-scrape-ladder-4-tiers.md`. Full content lands in subsequent slices that touch each decision.
- Existing `AGENTS.md` (project dispatcher) + `CLAUDE.md` (thin router) unchanged.

Out of scope (deferred): no Python source under `apps/api/src/` (slice 2), no Svelte source under `apps/web/src/` (slice W1), no `apps/openbb-sidecar/` (slice R4), no DB migrations (slice 3 lands `0001_initial_schema.py`).

## Capabilities

### New Capabilities

- `monorepo-tooling`: Poetry + pnpm workspace declarations, root `Makefile` + Makefile.includes pattern, four Docker compose profiles (dev/paper/live/test) with litestream sidecar, four GitHub Actions workflows, `.pre-commit-config.yaml`, `.gitignore`/`.gitleaksignore`/`.editorconfig`/`.dockerignore`. Establishes the dev-loop + CI baseline every slice consumes.
- `secrets-baseline`: SOPS+age layout under `.secrets/` with `.sops.yaml` recipients file and `{dev,paper,live}.env.enc` templates. Encodes the AGENTS.md §4 hard rule (API keys MUST live in SOPS-encrypted env files, never in code/config).
- `compliance-baseline`: LICENSE (Apache-2.0 + Commons Clause v1.0, checksum-verifiable), SECURITY.md, CONTRIBUTING.md placeholder, CHANGELOG.md initial entry, README.md, THIRD_PARTY_NOTICES.md, plus four ADR drafts (014-017) referenced by the Gate B architecture document. Establishes the licensing + attribution + decision-record baseline.

### Modified Capabilities

(none — this is the first slice; `openspec/specs/` is empty)

## Impact

- **Affected code**: repository root files only; no source code added under `apps/api/src/` or `apps/web/src/`.
- **APIs**: none (no application surface yet).
- **Dependencies**: introduces Python dev-deps (ruff, black, mypy, pytest, pytest-asyncio, hypothesis) and Node dev-deps (eslint, prettier, openapi-typescript) — all locked via `pyproject.toml` + `package.json`. Runtime deps deferred to slice 2 (`shared-primitives`).
- **Systems**: every subsequent slice's CI run depends on the pre-commit hooks + workflows + Makefile targets landed here. The license-boundary-check workflow is set up but skips until slice R4 introduces the AGPL boundary.
- **Documentation**: `docs/getting-started.md` becomes the canonical onboarding entry; `docs/adr/` becomes populated with four placeholder ADRs that subsequent slices flesh out.
- **Risk**: low — no functional code, no database, no network surface. Failure mode is "tooling broken" (caught in pre-commit / CI on first slice 2 PR), not "user impact".
