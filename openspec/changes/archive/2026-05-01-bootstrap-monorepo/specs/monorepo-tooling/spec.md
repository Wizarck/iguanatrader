## ADDED Requirements

### Requirement: Repository declares a Poetry workspace at the root

The system SHALL provide a root `pyproject.toml` declaring a Poetry workspace whose dev-dependency group includes ruff, black, mypy (configured `--strict`), pytest, pytest-asyncio, and hypothesis. The workspace SHALL be installable in one command via `poetry install --sync`.

#### Scenario: Fresh clone installs Python tooling

- **WHEN** a developer runs `poetry install --sync` immediately after `git clone`
- **THEN** Poetry resolves and installs ruff, black, mypy, pytest, pytest-asyncio, and hypothesis without prompting and exits with code 0

#### Scenario: pyproject.toml is the canonical config for ruff, black, mypy

- **WHEN** any of `ruff check .`, `black --check .`, or `mypy .` runs
- **THEN** the tool reads its configuration from `pyproject.toml` (no separate `.ruff.toml`, `pyproject-black.toml`, or `mypy.ini` files exist) and applies it consistently

### Requirement: Repository declares a pnpm 9 workspace at the root

The system SHALL provide a root `pnpm-workspace.yaml` declaring `apps/web` and `packages/shared-types` as workspace members, and the existing root `package.json` SHALL be augmented with the `workspaces` array referencing the same members. The existing `@fission-ai/openspec` devDep SHALL be retained.

#### Scenario: pnpm install resolves workspace members

- **WHEN** a developer runs `pnpm install` at the repo root
- **THEN** pnpm reads `pnpm-workspace.yaml`, links `apps/web` and `packages/shared-types` as workspace packages, and exits 0 even when those folders are empty placeholders

### Requirement: Root Makefile declares the dev-loop entry points

The system SHALL provide a root `Makefile` exposing the targets `bootstrap`, `lint`, `format`, `type`, `test`, `up`, `down`, and `clean` as `.PHONY`, and SHALL `include` per-package `Makefile.includes` files when those packages exist (with the include guarded so root works before subsequent slices land their packages).

#### Scenario: make bootstrap detects toolchain prerequisites

- **WHEN** `make bootstrap` runs on a fresh clone
- **THEN** the target verifies the presence of Python 3.11+, Node 20+, pnpm 9+, Poetry 1.8+, Docker, age, and sops, prints the resolved versions, and exits 0 only if all are present

#### Scenario: make bootstrap is idempotent

- **WHEN** `make bootstrap` is run twice in succession on a clean tree
- **THEN** the second run produces the same state as the first (no diff in `git status`, no re-installs requested by Poetry or pnpm beyond already-locked dependencies)

#### Scenario: Root Makefile tolerates missing per-package includes

- **WHEN** `make bootstrap` runs after only this slice has merged (no `apps/api/Makefile.includes` exists yet)
- **THEN** the root `Makefile` does NOT error on the missing include and the target completes successfully (achieved via `-include` directive or equivalent guarded include)

### Requirement: Four Docker compose files cover dev, paper, live, test profiles

The system SHALL provide four standalone `docker-compose.yml`, `docker-compose.paper.yml`, `docker-compose.live.yml`, `docker-compose.test.yml` files at the repo root. Each file SHALL declare a `litestream` sidecar service (except `test`, where ephemeral SQLite is used). All four files SHALL pass `docker compose -f <file> config` validation.

#### Scenario: All four compose files validate

- **WHEN** `docker compose -f docker-compose.yml config`, `docker compose -f docker-compose.paper.yml config`, `docker compose -f docker-compose.live.yml config`, and `docker compose -f docker-compose.test.yml config` are each executed
- **THEN** each command exits 0 and prints the resolved YAML with no warnings about missing services or unresolved references

#### Scenario: Litestream service is present in dev/paper/live but not test

- **WHEN** the resolved configs of the four compose files are inspected
- **THEN** `dev`, `paper`, and `live` each include a `litestream` service definition; `test` does NOT include `litestream` (test uses ephemeral SQLite)

### Requirement: Four GitHub Actions workflows cover CI, builds, OpenAPI types, license boundary

The system SHALL provide four workflow files under `.github/workflows/`: `ci.yml`, `build-images.yml`, `openapi-types.yml`, `license-boundary-check.yml`. All four SHALL pass `actionlint` validation. Until slice R4 lands the OpenBB sidecar, `license-boundary-check.yml` SHALL run and emit "n/a — sidecar not yet present" with exit 0.

#### Scenario: All workflows pass actionlint

- **WHEN** `actionlint` is run against `.github/workflows/`
- **THEN** the tool exits 0 with no syntax, expression, or shellcheck errors

#### Scenario: ci.yml runs lint + type + test + secrets-scan on every push to main and on every PR

- **WHEN** `ci.yml` is triggered (push to `main` or pull_request)
- **THEN** the workflow runs jobs for: ruff lint, black --check, mypy --strict, pytest (no tests yet so the job no-ops with exit 0), gitleaks scan, and pre-commit run --all-files

#### Scenario: license-boundary-check.yml skips gracefully before slice R4

- **WHEN** `license-boundary-check.yml` is triggered on a commit where `apps/openbb-sidecar/` does not exist
- **THEN** the workflow logs "n/a — sidecar not yet present" and exits 0

### Requirement: Pre-commit configuration enforces secrets-scan first, then format/type/lint

The system SHALL provide a `.pre-commit-config.yaml` whose hook chain begins with `gitleaks`, followed by `check-toml`, `ruff`, `black`, `mypy`, `eslint` (stub), `prettier` (stub), `openapi-typescript regen` (no-op until slice 5), and `license-boundary-check` (no-op until slice R4). Running `pre-commit run --all-files` on the bootstrap tree SHALL exit 0.

#### Scenario: gitleaks runs before any other hook

- **WHEN** the resolved hook order in `.pre-commit-config.yaml` is read
- **THEN** `gitleaks` is the first hook in the list

#### Scenario: pre-commit run --all-files passes on the empty repo

- **WHEN** `pre-commit run --all-files` is run after this slice's merge (and before any subsequent slice has added source code)
- **THEN** all hooks either no-op (no matching files) or pass, and the overall command exits 0

#### Scenario: gitignore + gitleaksignore + editorconfig + dockerignore all exist

- **WHEN** the repo root is inspected after this slice's merge
- **THEN** `.gitignore` includes Python, Node, secrets, IDE, `data/`, and `logs/` patterns; `.gitleaksignore` exists with explicit safe-list entries; `.editorconfig` exists with reasonable defaults; `.dockerignore` exists with universal ignore patterns
