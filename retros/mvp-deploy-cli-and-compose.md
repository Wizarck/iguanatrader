# Retrospective: mvp-deploy-cli-and-compose

> **Forward-authored** — fill at archive.

- **PR**: [#123](https://github.com/Wizarck/iguanatrader/pull/123) (merged 2026-05-12, squash `a333ea5`).
- **Archive path**: `openspec/changes/archive/2026-05-12-mvp-deploy-cli-and-compose/`
- **Lines shipped**: 923 insertions / 16 deletions across 10 files. CI 15/15 verde tras 1 fix round (Poetry 1.8 → 2.0 to match lockfile + missing `AsyncSession` import in test).

## What worked

- **CLI auto-discovery picked up `admin.py` immediately** — zero edits to `cli/main.py`. The pattern documented in slice 5 compounds: every future subcommand module drops in for free.
- **Docker build CI jobs on PR via path filter** — `build-images.yml` only fires on Dockerfile/compose/lockfile changes, so the 3-5min docker build doesn't add weight to routine PRs. This PR triggered all 3 build jobs naturally because it touched the Dockerfiles.
- **Argon2id hash format check in the test** (`password_hash.startswith("$argon2")`) is the right granularity — verifies the hashing layer ran without re-implementing Argon2 parsing in test code.
- **`--force-reset` flag for idempotent re-bootstrap** matters more than it looked — operators who type the wrong password on the prompt need a clean retry path; without it they'd be locked into SQL editing.
- **Two-stage Dockerfile with `target: runtime`** keeps the final image lean while `target: builder` is reusable if someone needs the dev-shell-flavored image with build tools.

## What didn't

- **Poetry version mismatch caught only by CI** — the lockfile header `Poetry 2.4.0` was not visible to me when I wrote the Dockerfile (I defaulted to a remembered 1.8.4). Pre-flag candidate: when writing a Python Dockerfile, `head -2 poetry.lock` first to read the generator version, then pin the Dockerfile to match (within the same major).
- **mypy `async_sessionmaker[None]` type slip** — I copy-pasted the signature from a fixture that returned `None` (no parameter narrowing needed) without thinking about the generic type arg. mypy --strict caught it but only on CI (local venv doesn't have project deps installed). Pre-flag: when annotating SQLAlchemy `async_sessionmaker[T]`, `T` MUST be `AsyncSession` (the type of what `session_factory()` produces); never `None`.
- **No local Docker validation possible** — Windows dev box without Docker daemon active. Relied entirely on the new CI build jobs. The first-push docker failure was discovered remotely, costing 5min of CI cycle. Trade-off accepted; the alternative (spinning up Docker Desktop) wasn't worth the local-loop friction for a slice this small.

## Carry-forward

- **Trading daemon as a 3rd compose service** — `iguanatrader trading run` long-running container; operator-blocked on IBKR TWS host networking + paper account creds.
- **`docker-compose.yml` / `.paper.yml` / `.live.yml` / `.test.yml` cleanup** — they still reference deprecated `target: dev` shape. Aspirational, not used; cleanup is a small follow-up.
- **TLS inside compose** — currently delegated to a reverse proxy (Caddy / nginx) outside the stack. A future slice could add a 3rd `caddy` service with auto-cert.
- **SOPS-encrypted env bundle for the VPS** — current MVP uses plain `IGUANATRADER_JWT_SECRET=...` env var. Promoting to SOPS+age matches the canonical pipeline but adds VPS-side tooling (age binary, key file management).
- **Healthcheck endpoint for the frontend** — currently `curl /` which returns the login page; a dedicated `/healthz` route on the SvelteKit side would distinguish "app responds" from "app responds + can render".

## Pattern usage

- **CLI auto-discovery picks up `admin.py`** without touching `cli/main.py` — same pattern the existing 7 subcommand modules (research, trading, ops, etc.) use. New subcommand modules drop into `cli/` and register automatically.
- **Multi-stage Dockerfiles** with explicit `builder` + `runtime` targets keep image size small + caching reliable. The compose file pins `target: runtime` so accidental dev-shell-flavoured builds don't ship.
- **Path-filtered CI on Docker workflow** — `build-images.yml` only fires when Dockerfile/compose/lockfile files change, not on every PR. Keeps the ~3-5min docker-build cost off the critical path for routine PRs while still catching breakage on the changes that actually touch the build surface.
