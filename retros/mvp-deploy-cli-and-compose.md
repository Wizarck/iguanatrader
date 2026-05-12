# Retrospective: mvp-deploy-cli-and-compose

> **Forward-authored** — fill at archive.

- **PR**: TBD (merged TBD, squash `TBD`).
- **Archive path**: `openspec/changes/archive/2026-05-12-mvp-deploy-cli-and-compose/`
- **Lines shipped**: TBD insertions / TBD deletions across TBD files. CI TBD.

## What worked

- TBD

## What didn't

- TBD

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
