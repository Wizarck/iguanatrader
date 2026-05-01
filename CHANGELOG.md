# Changelog

All notable changes to `iguanatrader` are documented here. Semver after `v1.0.0`.

## [Unreleased]

Wave 0 + Wave 1 + Wave 2 + Wave 3 + Wave 4 (the 20 OpenSpec slices in `docs/openspec-slice.md`) are in flight on `slice/*` branches; merges to `main` happen one slice at a time per `release-management.md` §6 (dependency-driven merge order).

## [0.0.0] — 2026-04-30 — bootstrap

Slice 1/20 (`bootstrap-monorepo`) lands the monorepo skeleton + tooling baseline so the 19 downstream slices can build on a stable foundation.

### Added

- **Python workspace**: root `pyproject.toml` (Poetry, package-mode false) + `poetry.lock` + `poetry.toml` (in-project venv config). Dev tools: ruff, black, mypy `--strict`, pytest (asyncio-auto), hypothesis. All four exit 0 on the empty repo.
- **Node workspace**: `pnpm-workspace.yaml` declaring `apps/web` + `packages/shared-types` (folders land in slices W1 / 5). Root `package.json` carries the workspaces array, eslint/prettier/openapi-typescript devDeps + `@fission-ai/openspec` CLI. Stub `.eslintrc.cjs` + `.prettierrc` + `.prettierignore`.
- **Makefile**: root targets `bootstrap`, `lint`, `format`, `type`, `test`, `up`, `down`, `clean` with `-include` of per-package `Makefile.includes` (lazy; missing files don't error).
- **Docker compose**: 4 standalone files (`docker-compose{,.paper,.live,.test}.yml`) with litestream sidecar via YAML anchor (test profile uses ephemeral `:memory:` SQLite).
- **GitHub Actions**: `ci.yml` (lint+type+test+secrets-scan+pre-commit), `build-images.yml` (matrix dev/paper/live/test, skip-with-notice until slice 2 lands the Dockerfile), `openapi-types.yml` (skip-with-notice until slice 5), `license-boundary-check.yml` (Apache+CC checksum gate + AGPL-boundary skip until slice R4).
- **Pre-commit**: `.pre-commit-config.yaml` with gitleaks-first hook chain (gitleaks → check-toml/yaml/json + housekeeping → ruff → black → mypy → eslint stub → prettier stub → openapi-types-regen stub → license-boundary stub → playbook integration).
- **Dotfiles**: `.gitignore` (Python+Node+secrets+IDE+runtime), `.gitleaksignore` (allowlist; empty), `.editorconfig` (UTF-8 LF, language-specific indent), `.dockerignore` (universal: secrets-plaintext, tests, docs, .ai-playbook submodule).
- **Secrets baseline**: `.secrets/.sops.yaml` (iguanatrader master age recipient `age10nqq3z…`, derived from passphrase via scrypt(salt=`iguanatrader-master-key-v1`)). 3 dotenv-encrypted templates: `dev.env.enc`, `paper.env.enc`, `live.env.enc` with placeholder envs; opens via `sops .secrets/<profile>.env.enc`.
- **License baseline**: `LICENSE` (Apache-2.0 + Commons Clause v1.0 verbatim, byte-checksummed); `SECURITY.md` (vuln disclosure); `CONTRIBUTING.md` (placeholder until v1.0); `THIRD_PARTY_NOTICES.md` (initially empty); `README.md`.
- **Onboarding doc**: `docs/getting-started.md` with prereqs + JSON1 SQLite verify + install steps.
- **ADR drafts**: `docs/adr/ADR-014-2026-04-28-bitemporal-research-facts.md`, `ADR-015-…-openbb-sidecar-isolation.md`, `ADR-016-…-research-domain-and-backtest-skip.md` (full content), `ADR-017-…-scrape-ladder-4-tiers.md`. Per Gate B condition.
- **Gotchas log**: `docs/gotchas.md` with 3 documented friction points (Windows + Microsoft Store Python + Poetry, Make not on PATH, mcp-validate hook env-var checks).

### Pinned upstream

- `.ai-playbook` submodule: `v0.8.0-rc3` (release-management contract + bootstrap_gh_project.py + repo-link/visibility flags).
- `.skills-sources/ai-playbook` submodule: `v0.8.0-rc3` (matches dispatcher).
- `.skills-sources/eligia-skills` submodule: `v0.3.0` (unchanged).

### Known issues

- `make` not on Windows PATH — operators run via Git Bash MinGW make or WSL. Documented in `docs/gotchas.md`.
- `mcp-validate` pre-commit hook fails on missing env vars + reads eligia-core's mcp-servers.yaml as personal layer (legacy convention). Will be fixed in playbook `v0.8.0-rc4`. Documented in `docs/gotchas.md`.
- Poetry on Microsoft Store Python recreates venvs on every `poetry run`; workaround: `poetry config virtualenvs.in-project true` + invoke tools as `python -m <tool>`. `poetry.toml` carries this config repo-wide. Documented in `docs/gotchas.md`.
