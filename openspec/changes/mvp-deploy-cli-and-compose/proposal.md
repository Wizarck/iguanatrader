# Proposal: mvp-deploy-cli-and-compose

> **End-to-end MVP runnable on a VPS in <5 min**: `iguanatrader admin bootstrap-tenant` CLI + production-ready Dockerfiles for api + web + `docker-compose.mvp.yml` + VPS deploy guide. Closes the "how do I access the MVP" gap.

## Why

After 5 carry-forward slices (PR #116-120), the operator has no obvious path to actually run the MVP on a server:

- **No bootstrap CLI** — the auth route raises `BootstrapNotReadyError` on first login and the error message points at `iguanatrader admin bootstrap-tenant <slug>`, but that command **doesn't exist**. The only path today is a one-off Python `asyncio.run(...)` snippet.
- **No production Dockerfiles** — `apps/api/Dockerfile` and `apps/web/Dockerfile` don't exist. The canonical `docker-compose.yml` references them but they're documented as placeholders for "slice 2" (which never landed them).
- **No minimal compose stack** — the existing `docker-compose.yml` is full-stack (api + openbb sidecar + litestream + age key plumbing). An MVP-only stack would skip the sidecar (needs AGPL provider keys) + litestream (single-VPS doesn't need it).
- **No deploy guide** — `docs/getting-started.md` is the canonical onboarding doc but its first-run section says "becomes runnable end-to-end after Wave 4 lands" + assumes operators have IBKR TWS ready.

This slice closes all four gaps.

## What

### CLI

`apps/api/src/iguanatrader/cli/admin.py` — new Typer module auto-registered by the existing CLI discovery (`cli/main.py` walks `cli/*.py` and binds any file that exports `app: typer.Typer`).

```
iguanatrader admin bootstrap-tenant <slug> \
    --email <email> \
    --password <plaintext>   # prompted if omitted
    [--force-reset]
```

Idempotent on slug (errors on duplicate unless `--force-reset` deletes the old tenant + its users first). Password hashed via the existing `argon2-cffi` Argon2id pipeline (`iguanatrader.api.auth.hash_password`). DB URL resolved from `IGUANA_DATABASE_URL` env var (matches the rest of the CLI surface).

### Dockerfiles

**`apps/api/Dockerfile`** — multi-stage Python 3.11-slim:
- `builder` stage: installs Poetry, copies `pyproject.toml` + `poetry.lock` only, runs `poetry install --no-root --without dev` into a project-local `.venv`. Source code not copied yet → Docker caches the deps layer.
- `runtime` stage: copies the venv + source, runs `python -m iguanatrader.api` as a non-root `app` user. Healthcheck: `curl /healthz`.

**`apps/web/Dockerfile`** — multi-stage Node 20-bookworm-slim:
- `builder` stage: enables corepack + pnpm, installs the workspace deps, runs `pnpm --filter @iguanatrader/web build` (vite + adapter-node).
- `runtime` stage: copies the `build/` output + `node_modules` (adapter-node's bundle externalises some deps so the node_modules tree is needed). Runs `node build/index.js`. Healthcheck: `curl /`.

### Compose

**`docker-compose.mvp.yml`** — two services (`api`, `web`) + one named volume (`iguanatrader_data` for SQLite + payloads). Exposes ports 8000 + 5173. Reads `IGUANATRADER_JWT_SECRET` from the host environment via `${VAR:-CHANGE-ME-...}` so a missing override fails loudly at first login.

### Docs

**`docs/mvp-deploy.md`** — VPS deploy playbook. 7 steps from `git clone` to `curl http://vps:8000/healthz`, including a Caddy reverse-proxy config snippet for TLS termination, an operator-commands table, troubleshooting matrix, and rolling-update flow.

### CI

**`.github/workflows/build-images.yml`** restructured:
- Triggers extended to `push: main`, `pull_request: main`, and `workflow_dispatch` (paths-filtered to Dockerfile / compose / lockfile changes only — doesn't add CI weight on unrelated PRs).
- 3 jobs: `config-validation` (validates all 5 compose files including the new `.mvp.yml`), `build-mvp-api`, `build-mvp-web`.
- Removed the deprecated `target: [dev, paper, live, test]` matrix (those targets never existed in the placeholder Dockerfile that this slice replaces).

### Tests

**`apps/api/tests/integration/test_admin_bootstrap_tenant.py`** — three tests using `typer.testing.CliRunner`:
1. Happy path → tenant + user inserted, Argon2id hash format verified.
2. Duplicate slug without `--force-reset` → non-zero exit + "already exists" output.
3. `--force-reset` → existing tenant deleted + new one inserted (old user gone, new user present).

## Out of scope

- **Trading daemon container** — slice T4 ships the `iguanatrader trading run` daemon; bundling it as a third compose service requires IBKR TWS connectivity from the container (network + paper account creds) → operator slice.
- **OpenBB sidecar in MVP compose** — needs AGPL provider keys; defer until the operator has them ready.
- **TLS termination inside compose** — documented as a reverse-proxy step (Caddy) outside the compose stack.
- **Docker secrets / SOPS integration** — MVP uses plain env vars; the canonical SOPS+age pipeline is documented in `getting-started.md` §3.
- **`docker-compose.yml` / `.paper.yml` / `.live.yml` / `.test.yml` cleanup** — those files still reference the old `target: dev` shape. They're aspirational and not used by any pipeline today; out of scope for this MVP slice.
