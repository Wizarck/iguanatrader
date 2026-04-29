## Context

iguanatrader is a Python+Svelte monorepo whose 19 downstream slices (per [docs/openspec-slice.md](../../../docs/openspec-slice.md)) all assume a single canonical dev-loop, lint/format/type baseline, secrets layout, and CI surface. The architecture, tech choices, license, and ADRs were sealed at Gate A (PRD, 2026-04-28) and Gate B (architecture + data model + project structure, 2026-04-28); Gate C (slicing, 2026-04-28) approved the 20-change plan. This slice does not relitigate any of those decisions — it materialises them as concrete repo files so the rest of Wave 0 (`shared-primitives`, `persistence-tenant-enforcement`) and all four parallel waves can land cleanly.

Per [docs/architecture-decisions.md](../../../docs/architecture-decisions.md): Python 3.11+, Poetry workspaces, pnpm workspaces, FastAPI+Svelte5+SQLite single-tenant-ready, single asyncio loop, MessageBus+Engines pattern, append-only event sourcing, structlog+pydantic, SOPS+age secrets, Apache-2.0+Commons Clause, Docker compose with profiles per environment, OpenBB SDK isolated as AGPL sidecar (slice R4 lands the container; this slice lands the license-boundary-check workflow that protects the boundary).

The repository is a fresh checkout: `AGENTS.md`, `CLAUDE.md`, `docs/`, `.ai-playbook/` (submodule), `.skills-sources/` (submodule), `skills/` (regenerated mirror), `openspec/` (just initialised), and a minimal `package.json` (just devDep `@fission-ai/openspec`) already exist. Everything else is new in this slice.

## Goals / Non-Goals

**Goals:**

- Make `make bootstrap` runnable on a fresh clone (Windows + macOS + Linux) and detect Poetry / pnpm / Docker / age / sops with version checks.
- Make `pre-commit run --all-files` exit 0 on the empty-source repo (every hook either no-ops or finds no violations).
- Make `docker compose --profile {dev,paper,live,test} config` validate without error for all four compose files.
- Make `actionlint` pass on all four GitHub Actions workflows.
- Verify the `LICENSE` file is byte-identical to canonical Apache-2.0 + Commons Clause v1.0 sources (checksum gate in CI).
- Establish the `Makefile` + `Makefile.includes` pattern, the SOPS+age secrets layout, and the four ADR placeholder files so subsequent slices have a stable contract to extend.
- Be idempotent: running `make bootstrap` twice produces the same state (no drift, no unintended diff).

**Non-Goals:**

- No application source code under `apps/api/src/` (slice 2 plants `shared/`).
- No frontend source under `apps/web/src/` (slice W1 plants the SvelteKit skeleton).
- No `apps/openbb-sidecar/` container (slice R4); the license-boundary-check workflow ships in skip-with-`n/a` mode here and activates in R4.
- No DB migrations (slice 3 lands `0001_initial_schema.py`); Alembic config is also deferred.
- No actual secret values committed — only encrypted templates with `<placeholder>` envs.
- No release tagging, no Docker image push, no docs site build — those are out-of-scope until v1.

## Decisions

### Decision 1 — Poetry workspaces (not pip-tools, not Hatch, not uv)

Already sealed at Gate B. Poetry is the canonical workspace manager because (a) it handles workspace dependencies cleanly, (b) it locks transitively, (c) it integrates with `pre-commit` and `mypy --strict` workflows that the team has standardised on across other projects (eligia-core, openTrattOS, palafito-b2b). Alternatives considered: `pip-tools` (rejected: weak workspace support), `Hatch` (rejected: less mature for multi-project layouts), `uv` (rejected for now: still maturing, can revisit at v1 if locks become a bottleneck).

### Decision 2 — pnpm 9 (not npm, not yarn)

Already sealed at Gate B. pnpm chosen for: workspace symlinks (vs npm hoisting issues), faster CI (content-addressed store), strict peer-dep behaviour. The repo's existing `package.json` (containing only `@fission-ai/openspec` devDep) becomes the workspace root in this slice — `pnpm-workspace.yaml` declares `apps/web` + `packages/shared-types` as members.

### Decision 3 — Four Docker compose profiles, one file each

`docker-compose.yml` (dev), `docker-compose.paper.yml`, `docker-compose.live.yml`, `docker-compose.test.yml`. Each is a complete file (not overlay); they share the litestream sidecar definition via YAML anchors at the top of each file (no extends, no overrides, no inheritance complexity). Rationale: per AGENTS.md §4 paper-vs-live is a hard boundary — having one composed file per environment makes the boundary auditable in a single read. Docker compose v2 `profiles:` is not used because the boundary needs to be lexical (different file = different intent).

Alternatives considered: single compose file with overrides (rejected: makes paper-vs-live harder to audit + couples them); compose v2 profiles only (rejected: "paper" and "live" running from the same file is exactly the failure mode the boundary should prevent).

### Decision 4 — SOPS + age (not Vault, not 1Password CLI, not encrypted dotenv)

Already sealed at Gate B. SOPS + age chosen for: file-based (commits to repo), per-recipient (Arturo's age public key + future contributors), no external SaaS dep, works offline, integrates with pre-commit gitleaks for the unencrypted-side check. `.secrets/.sops.yaml` declares recipients; `.secrets/{dev,paper,live}.env.enc` are encrypted templates with placeholder envs. Decryption is opt-in per environment (a contributor only needs to decrypt `dev.env.enc` to run paper-trading locally).

### Decision 5 — Pre-commit hook chain order matters

Order in `.pre-commit-config.yaml`: `gitleaks` (FIRST — catches secrets before any other hook touches the file) → `check-toml` → `ruff` → `black` → `mypy` (Python) → `eslint stub` → `prettier stub` (Node, stub means hooks declared but config will be filled out in slices 5/W1) → `openapi-typescript` regen (slice 5 wires up generation; here it's a no-op pass) → `license-boundary-check` (skips with "n/a" until slice R4 lands the AGPL sidecar). Rationale: secrets-scan must run first because formatters can rewrite a leaked token into a different shape.

### Decision 6 — `Makefile` + per-package `Makefile.includes`

Root `Makefile` declares phony targets (`bootstrap`, `lint`, `test`, `up`, `down`) and uses `include apps/api/Makefile.includes` + `include apps/web/Makefile.includes` + (eventually) `include apps/openbb-sidecar/Makefile.includes`. Each subsequent slice owns the includes file for its package (slice 2 lands `apps/api/Makefile.includes` with the API-specific targets). Rationale: zero merge conflicts on the root Makefile across parallel slices in Wave 2/3 — each slice writes its own `.includes` file, root Makefile is touched once here.

### Decision 7 — Four ADR placeholder files now, full content in subsequent slices

ADR-014 (bitemporal research_facts), ADR-015 (OpenBB sidecar isolation), ADR-016 (research domain + backtest skip), ADR-017 (scrape ladder 4 tiers) ship as skeleton files with frontmatter (`status: proposed`, `date: 2026-04-28`, the original Gate B amendment date) + a one-paragraph stub citing where the decision is recorded in `docs/architecture-decisions.md`. Each subsequent slice that touches the decision (R1 for 014, R4 for 015, R3 for 017) MUST flesh out the corresponding ADR as part of its own acceptance criteria. ADR-016 (research+backtest scope) is the most "free-standing" — it can be filled here. Rationale: physical ADR existence was a Gate B condition; full content where the decision is hot is more truthful than synthesising it now.

### Decision 8 — License text byte-verified, not "trust me"

LICENSE assembles Apache-2.0 (canonical from `https://www.apache.org/licenses/LICENSE-2.0.txt`, sha256 known) + Commons Clause v1.0 (canonical from `https://commonsclause.com/`, sha256 known). The `license-boundary-check.yml` workflow includes a checksum gate that compares each segment against the recorded sha256. Rationale: AGENTS.md §4 makes the licensing boundary a hard rule; "the license file is correct" cannot be trust-based.

## Risks / Trade-offs

- **[Risk] Windows path separators in pre-commit / Makefile** → Mitigation: shell scripts in Makefile invoked through bash (Git Bash on Windows); pre-commit's `pass_filenames` uses forward slashes natively. CI matrix runs `ubuntu-latest` only at this stage; Windows compatibility verified locally by Arturo (the only dev) before merge.
- **[Risk] Tooling drift from skipped license-boundary check until slice R4** → Mitigation: workflow runs and emits "n/a — sidecar not yet present" with exit 0; slice R4's PR MUST flip the skip to active enforcement (recorded in R4's tasks.md).
- **[Risk] Idempotency — `make bootstrap` re-running corrupting state** → Mitigation: bootstrap target is composed of: (a) version checks (pure read), (b) `poetry install --sync` (idempotent), (c) `pnpm install --frozen-lockfile` (idempotent), (d) `pre-commit install` (idempotent). No `cp` / `chmod` / `touch` operations that could overwrite local edits.
- **[Risk] SOPS recipients missing for new contributors** → Mitigation: `CONTRIBUTING.md` (placeholder in this slice, fleshed out at v1) documents the age key handoff process; for now Arturo is sole contributor.
- **[Risk] LICENSE checksum brittleness if upstream Apache-2.0 / Commons Clause text changes (unlikely but possible)** → Mitigation: checksums recorded in `.github/workflows/license-boundary-check.yml` as a `LICENSE_APACHE2_SHA256` constant + `LICENSE_COMMONS_CLAUSE_SHA256` constant; if upstream changes, the workflow fails and the human reviews + updates the constants in a follow-up PR.
- **[Trade-off] Four full compose files vs one with profiles** → Chosen four-file because the auditability win > the duplication cost. The duplicated YAML anchor block (litestream service) is small (~12 lines); diverging on it is unlikely.

## Migration Plan

Not applicable — greenfield repo, no prior deployment to migrate from. The PR for this slice is the first green-field merge to `main`; subsequent slices each PR their own additions.

## Open Questions

None at the design level. Open implementation details (e.g. exact `ruff` rule set, exact `mypy` strict overrides) are deferred to the spec scenarios + tasks list — they are knob-tweaking, not architectural decisions.
