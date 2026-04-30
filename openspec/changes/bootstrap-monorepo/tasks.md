## 1. Python workspace + tooling baseline

- [x] 1.1 Author root `pyproject.toml` declaring Poetry workspace + dev-dep group (ruff, black, mypy, pytest, pytest-asyncio, hypothesis); pin Python ≥3.11.
- [x] 1.2 Add `[tool.ruff]` config in `pyproject.toml` (selected rule sets, line length, target-version py311); confirm `ruff check .` exits 0 on empty repo.
- [x] 1.3 Add `[tool.black]` config (line length 100, target-version py311); confirm `black --check .` exits 0.
- [x] 1.4 Add `[tool.mypy]` config with `strict = true`, `warn_unused_ignores = true`, `disallow_any_unimported = true`; confirm `mypy .` exits 0 on empty repo.
- [x] 1.5 Add `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` and `addopts = "-q"`; confirm `pytest --collect-only` exits 0 with "no tests collected".
- [x] 1.6 Run `poetry install --sync` and verify lockfile is generated; commit `poetry.lock`.

## 2. Node workspace + tooling baseline

- [x] 2.1 Add `pnpm-workspace.yaml` declaring `apps/web` + `packages/shared-types` as members.
- [x] 2.2 Augment root `package.json` with `workspaces` array referencing the same members; retain existing `@fission-ai/openspec` devDep.
- [x] 2.3 Add `eslint` + `prettier` + `openapi-typescript` as devDeps; provide stub configs (`.eslintrc.cjs`, `.prettierrc`) — full config lands in slices 5 / W1.
- [x] 2.4 Run `pnpm install` and verify lockfile is generated; commit `pnpm-lock.yaml`.

## 3. Makefile + per-package includes pattern

- [x] 3.1 Author root `Makefile` with `.PHONY: bootstrap lint format type test up down clean` targets.
- [x] 3.2 Implement `bootstrap` target: version-check Python 3.11+, Node 20+, pnpm 9+, Poetry 1.8+, Docker, age, sops; run `poetry install --sync`; run `pnpm install --frozen-lockfile`; run `pre-commit install`.
- [x] 3.3 Use `-include apps/api/Makefile.includes` and `-include apps/web/Makefile.includes` (lowercase `-include` so missing files are silently ignored).
- [x] 3.4 Verify idempotency: run `make bootstrap` twice on a clean tree and confirm `git status` shows zero diff between runs.

## 4. Docker compose four-profile setup

- [x] 4.1 Author `docker-compose.yml` (dev profile) with placeholder app service + litestream sidecar (using YAML anchor for litestream block).
- [x] 4.2 Author `docker-compose.paper.yml` mirroring dev but pointing at paper-trading endpoints + litestream sidecar.
- [x] 4.3 Author `docker-compose.live.yml` mirroring paper but pointing at live endpoints + litestream sidecar; include explicit `# AGENTS.md §4 — live profile, requires --confirm-live` header comment.
- [x] 4.4 Author `docker-compose.test.yml` with ephemeral SQLite (no litestream).
- [x] 4.5 Run `docker compose -f <each>.yml config` for all four files and confirm exit 0.

## 5. GitHub Actions workflows

- [x] 5.1 Author `.github/workflows/ci.yml`: jobs for ruff lint, black --check, mypy --strict, pytest, gitleaks scan, pre-commit run --all-files; trigger on push to main + pull_request.
- [x] 5.2 Author `.github/workflows/build-images.yml`: triggers on tag, builds Docker images for the dev/paper/live targets (no push at this stage; just `docker build` validation).
- [x] 5.3 Author `.github/workflows/openapi-types.yml`: stub job that prints "n/a — openapi schema not yet present" and exits 0 (slice 5 wires up real generation).
- [x] 5.4 Author `.github/workflows/license-boundary-check.yml`: checksum-validate `LICENSE` against recorded `LICENSE_APACHE2_SHA256` + `LICENSE_COMMONS_CLAUSE_SHA256` constants; if `apps/openbb-sidecar/` does not exist, log "n/a — sidecar not yet present" and exit 0.
- [x] 5.5 Run `actionlint` against `.github/workflows/` and confirm exit 0 with no findings.

## 6. Pre-commit configuration

- [ ] 6.1 Author `.pre-commit-config.yaml` with hook order: gitleaks → check-toml → ruff → black → mypy → eslint (stub) → prettier (stub) → openapi-typescript regen (no-op) → license-boundary-check (no-op).
- [ ] 6.2 Run `pre-commit install` to activate hooks locally.
- [ ] 6.3 Run `pre-commit run --all-files` and confirm exit 0 (all hooks no-op or pass).
- [ ] 6.4 Test the gitleaks-first ordering: stage a file containing a fake AWS access key, run pre-commit, confirm the commit is blocked before any other hook runs.

## 7. Gitignore + supporting dotfiles

- [ ] 7.1 Expand `.gitignore` with Python (`__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `dist/`, `build/`, `*.egg-info/`), Node (`node_modules/` already present, `dist/`, `.svelte-kit/`), secrets (`.secrets/*.env` without `.enc`, `*.key`, `*.pem`), IDE (`.vscode/`, `.idea/`), runtime (`data/`, `logs/`, `*.db`, `*.sqlite`, `*.sqlite-journal`).
- [ ] 7.2 Author `.gitleaksignore` with explicit safe-list (initially empty body, schema header only).
- [ ] 7.3 Author `.editorconfig` with reasonable defaults (UTF-8, LF line endings, 4-space Python, 2-space JS/YAML, 100-col max, trim trailing whitespace, insert final newline).
- [ ] 7.4 Author `.dockerignore` with universal patterns (`.git/`, `node_modules/`, `__pycache__/`, `.venv/`, `.secrets/*.env` without `.enc`, `*.md` except essentials, `tests/`).

## 8. SOPS + age secrets layout

- [ ] 8.1 Author `.secrets/.sops.yaml` declaring creation rule for `.secrets/.*\.env$` with Arturo's age public key as recipient.
- [ ] 8.2 Author plaintext template `.secrets/dev.env.template` with placeholder envs (e.g. `IBKR_HOST=<placeholder>`, `BROKER_API_KEY=<placeholder>`, `OPENAI_API_KEY=<placeholder>`, `TELEGRAM_BOT_TOKEN=<placeholder>`); encrypt to `.secrets/dev.env.enc`; remove the plaintext.
- [ ] 8.3 Repeat 8.2 for `.secrets/paper.env.enc` and `.secrets/live.env.enc` with profile-specific placeholders.
- [ ] 8.4 Verify all three encrypted files decrypt cleanly with `sops -d` using the matching age private key.
- [ ] 8.5 Run `gitleaks detect --source . --no-banner` and confirm zero findings on the bootstrap tree.

## 9. License + compliance baseline

- [ ] 9.1 Download canonical Apache-2.0 text from `https://www.apache.org/licenses/LICENSE-2.0.txt`; record sha256 in `.github/workflows/license-boundary-check.yml` as `LICENSE_APACHE2_SHA256`.
- [ ] 9.2 Download canonical Commons Clause v1.0 text from `https://commonsclause.com/`; record sha256 as `LICENSE_COMMONS_CLAUSE_SHA256`.
- [ ] 9.3 Author root `LICENSE` concatenating Apache-2.0 + delimiter + Commons Clause v1.0; verify checksums match recorded constants.
- [ ] 9.4 Author root `SECURITY.md` with vulnerability disclosure policy: supported versions, reporting channel (GitHub security advisories), expected response time (best-effort within 7 days at MVP), non-public-disclosure clause.
- [ ] 9.5 Author root `CONTRIBUTING.md` (placeholder for v1: "Contribution guidelines pending; for now, contact arturo6ramirez@gmail.com").
- [ ] 9.6 Author root `CHANGELOG.md` with `## [0.0.0] — 2026-04-29 — bootstrap` entry summarising this slice's contents.
- [ ] 9.7 Author root `README.md`: tagline + links to PRD, ADRs, getting-started, LICENSE, CONTRIBUTING.
- [ ] 9.8 Author root `THIRD_PARTY_NOTICES.md` (heading + "No third-party code copied yet" sentence).

## 10. Documentation: getting-started + ADR drafts

- [ ] 10.1 Author `docs/getting-started.md` with: prerequisites table (Python 3.11+, Node 20+, pnpm 9+, Poetry 1.8+, Docker, age, sops + verify commands), JSON1 SQLite smoke-test command, install steps mapped to `make bootstrap`, "what's next" pointer to architecture-decisions + paper-trading walkthrough placeholder.
- [ ] 10.2 Verify the JSON1 verify command works on the developer's machine (Windows + macOS + Linux as available).
- [ ] 10.3 Author `docs/adr/ADR-014-2026-04-28-bitemporal-research-facts.md` (skeleton: frontmatter `status: proposed`, `date: 2026-04-28`, `decided-by: Arturo Ramírez (arturo6ramirez@gmail.com)`; body cites Gate B amendment in `docs/hitl-gates-log.md` + `docs/architecture-decisions.md` Step "Research bounded context" + `docs/data-model.md` §7b Q2 resolution; "Full content pending — slice R1 fleshes this out").
- [ ] 10.4 Author `docs/adr/ADR-015-2026-04-28-openbb-sidecar-isolation.md` (skeleton: same frontmatter; body cites `docs/architecture-decisions.md` "OpenBB Sidecar Topology" section; "Full content pending — slice R4 fleshes this out").
- [ ] 10.5 Author `docs/adr/ADR-016-2026-04-28-research-domain-and-backtest-skip.md` (FULL content — this decision is self-contained at Gate A amendment): Context (PRD originally had FR6-FR10 backtest; user reasoning prompted skip); Decision (eliminate backtest, add Research domain FR57-FR81; rationale "skippeamos y no hace falta gate, quien quiera probar live puede hacerlo, es a riesgo del usuario"); Consequences (paper-trading recommended via AGENTS.md §7 Override 1; backtest deferred to v2 if user demand emerges); cite `docs/hitl-gates-log.md` Gate A amendment.
- [ ] 10.6 Author `docs/adr/ADR-017-2026-04-28-scrape-ladder-4-tiers.md` (skeleton: same frontmatter; body cites `docs/architecture-decisions.md` scrape ladder section + 4 critical caveats from Gate A amendment; "Full content pending — slice R3 fleshes this out").

## 11. Final verification before PR

- [ ] 11.1 Run `make bootstrap` on a clean clone (fresh worktree); confirm exit 0 and `git status` shows zero diff after.
- [ ] 11.2 Run `pre-commit run --all-files` and confirm exit 0.
- [ ] 11.3 Run `docker compose -f docker-compose.yml config` + `... -f docker-compose.paper.yml config` + `... -f docker-compose.live.yml config` + `... -f docker-compose.test.yml config` and confirm all four exit 0.
- [ ] 11.4 Run `actionlint .github/workflows/` and confirm exit 0.
- [ ] 11.5 Run `gitleaks detect --source . --no-banner` and confirm zero findings.
- [ ] 11.6 Run `npx openspec validate --change bootstrap-monorepo` and confirm exit 0.
- [ ] 11.7 Verify scope-check: `ls apps/api/src/iguanatrader/ apps/web/src/ apps/openbb-sidecar/` returns "no such file or directory" for all three (no source code introduced beyond what slice 1 owns).
- [ ] 11.8 Open PR to main with title "feat(bootstrap): monorepo skeleton + tooling baseline (slice 1/20)"; reference `docs/openspec-slice.md` row 1 and `docs/hitl-gates-log.md` Gate C in the PR description.
- [ ] 11.9 Record Gate F approval in `docs/hitl-gates-log.md` after PR review + merge.
- [ ] 11.10 Run `/opsx:archive bootstrap-monorepo` to promote `specs/monorepo-tooling/spec.md` + `specs/secrets-baseline/spec.md` + `specs/compliance-baseline/spec.md` to `openspec/specs/`, draft `retros/bootstrap-monorepo.md`.
