---
type: deployment-guide
project: iguanatrader
schema_version: 1
created: 2026-05-12
updated: 2026-05-12
purpose: Step-by-step MVP deployment on a fresh VPS (Docker Compose, two containers).
---

# MVP Deployment — Docker Compose on a VPS

This guide brings the iguanatrader MVP up on a fresh Linux VPS in **under
5 minutes** using Docker Compose. It's the canonical "I just want to log
in and click around" path — the full production stack (litestream
replication, OpenBB sidecar, IBKR TWS) is documented in
[`getting-started.md`](getting-started.md) and the operator runbooks.

## What you get

Two containers wired together:

- **`api`** — FastAPI monolith on port 8000 (REST + SSE + Swagger docs).
- **`web`** — SvelteKit (adapter-node) frontend on port 5173.

Data persists in a named Docker volume (`iguanatrader_data`) — wipe with
`docker compose -f docker-compose.mvp.yml down -v` to start fresh.

**What this MVP profile deliberately does NOT include**:

- **OpenBB sidecar** (AGPL isolation; only required once you wire research
  adapters with real provider keys).
- **Litestream replication** (the canonical `docker-compose.yml` ships
  it; for an MVP a daily `docker run` `sqlite3 .dump` cron is enough).
- **IBKR TWS / Gateway** (paper or live trading; operator-blocked on
  broker credentials).
- **SOPS-encrypted env decryption** (use plain env vars on the VPS).

## Prerequisites

- A Linux VPS with **Docker 20.10+** and **Docker Compose v2** installed.
- Outbound HTTPS open (Docker pulls + git fetches).
- Inbound TCP 5173 + 8000 open (or a reverse proxy that forwards to
  them — recommended for HTTPS).

## Step 1 — Clone the repo

```bash
ssh root@<vps-ip>
git clone https://github.com/Wizarck/iguanatrader.git
cd iguanatrader
```

## Step 2 — Set the JWT secret + channel dispatcher

```bash
export IGUANATRADER_JWT_SECRET="$(openssl rand -hex 32)"   # 64-char hex
echo "IGUANATRADER_JWT_SECRET=$IGUANATRADER_JWT_SECRET" > .env
```

The compose file reads `IGUANATRADER_JWT_SECRET` from the shell env (or
`.env`). The default placeholder `CHANGE-ME-64-CHAR-HEX` is intentionally
non-functional so a forgotten override fails loudly at first login
attempt.

### Channel dispatcher (forgot-password recovery)

Slice `auth-forgot-password-flow` wires the previously dormant Telegram
and Hermes/WhatsApp adapters into the MVP profile. The `api` service
reads a single selector env var:

| `IGUANATRADER_CHANNEL_DISPATCHER` | Result |
|---|---|
| unset / `log_only` (default for tests) | LogOnly — no real sends; events visible in structlog |
| `email` (compose default) | SMTP only — needs `IGUANATRADER_SMTP_*` populated |
| `telegram_hermes` | Telegram + Hermes/WhatsApp |
| `telegram_hermes_email` | All three channels |

Per-channel fallback: a missing credential for one channel disables
THAT channel only — the remainder stays live. If every requested channel
is missing creds, the dispatcher falls back to LogOnly.

#### Step 2a — SMTP (email recovery channel)

```bash
cat >> .env <<'ENV'
IGUANATRADER_SMTP_HOST=smtp.your-provider.example
IGUANATRADER_SMTP_PORT=587
IGUANATRADER_SMTP_USERNAME=iguanatrader@palafitofood.com
IGUANATRADER_SMTP_PASSWORD=<password-from-provider>
IGUANATRADER_SMTP_FROM_ADDRESS=iguanatrader@palafitofood.com
IGUANATRADER_SMTP_FROM_NAME=iguanatrader
IGUANATRADER_SMTP_USE_TLS=true
ENV
```

**DNS prerequisites for `palafitofood.com`** (operator-side, one-time):

- **SPF**: add the SMTP provider's include to the existing `palafitofood.com`
  TXT record (e.g. `v=spf1 include:provider.example -all`).
- **DKIM**: provider hands you a TXT record at
  `<selector>._domainkey.palafitofood.com`; publish it on Cloudflare /
  your DNS host before the first send (otherwise inbound providers
  silently mark messages as spam).
- **From address override**: if your provider does not let you send
  as `iguanatrader@palafitofood.com`, override
  `IGUANATRADER_SMTP_FROM_ADDRESS` + `IGUANATRADER_SMTP_FROM_NAME`
  to the operator-controlled address.

#### Step 2b — Telegram (optional)

```bash
echo "TELEGRAM_BOT_TOKEN=<bot-token-from-BotFather>" >> .env
```

The user-side recovery channel is keyed by `users.telegram_chat_id`
(operator-set via SQL or the future admin CLI). If the column is NULL
for a given user, that user does not receive the temp password over
Telegram even when the bot is wired.

#### Step 2c — Hermes / WhatsApp (optional)

```bash
cat >> .env <<'ENV'
HERMES_BASE_URL=https://hermes.your-tenant.example
HERMES_HMAC_SECRET=<32-byte-hmac-secret>
ENV
```

> **SOPS bundle rename note**: the canonical `.secrets/dev.env.enc`,
> `paper.env.enc`, `live.env.enc` bundles still carry the legacy
> `HERMES_WEBHOOK_URL` + `HERMES_AUTH_TOKEN` names from ELIGIA's Hermes.
> iguanatrader's adapter expects the canonical `HERMES_BASE_URL` +
> `HERMES_HMAC_SECRET`. Rename via SOPS decrypt → edit → re-encrypt:
>
> ```bash
> sops .secrets/dev.env.enc        # opens editor; rename the keys
> sops .secrets/paper.env.enc
> sops .secrets/live.env.enc
> ```
>
> The MVP profile does NOT consume SOPS bundles (uses plain env vars per
> Step 2 above) — this rename only matters for the canonical
> `docker-compose.yml` / production stack.

#### Step 2d — Enable the multi-channel dispatcher

Once the creds above are populated, flip the selector:

```bash
echo "IGUANATRADER_CHANNEL_DISPATCHER=telegram_hermes_email" >> .env
docker compose -f docker-compose.mvp.yml up -d --force-recreate api
```

Operator self-service recovery (`POST /api/v1/auth/forgot-password`)
will then fan the temporary credential out to every channel the user
has opted into.

## Step 3 — Build the images

```bash
docker compose -f docker-compose.mvp.yml build
```

First build: ~3-5 minutes (Poetry deps + Vite production bundle).
Subsequent builds reuse Docker layer cache.

## Step 4 — Run migrations + seed the first tenant

```bash
# Apply Alembic migrations to the SQLite file in the named volume.
docker compose -f docker-compose.mvp.yml run --rm api \
    python -m alembic -c apps/api/alembic.ini upgrade head

# Create the first tenant + admin user. Interactive password prompt
# unless you pass --password / -p on the command line.
docker compose -f docker-compose.mvp.yml run --rm api \
    iguanatrader admin bootstrap-tenant arturo-trading \
        --email arturo@example.com \
        --password 'changeme-2026-pick-a-real-one'
```

Successful output ends with `OK — tenant_id=<uuid> user_id=<uuid> email=...`.
The `bootstrap-tenant` command is idempotent on the tenant slug: re-running
without `--force-reset` errors out cleanly.

## Step 5 — Start the stack

```bash
docker compose -f docker-compose.mvp.yml up -d
```

Verify both containers are healthy:

```bash
docker compose -f docker-compose.mvp.yml ps
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:5173/
```

## Step 6 — Log in

Open `http://<vps-ip>:5173/login` in a browser. Enter the email + password
you seeded in Step 4. You land on `/portfolio` (the canonical post-login
redirect).

### What you can do in the MVP

| Surface | URL | What works in MVP |
|---|---|---|
| Login / logout | `/login` | Full Argon2id auth + JWT cookie |
| Dashboard shell | `/` | Sidebar with 8 domain links + TopBar |
| Research index | `/research` | Watchlist + brief summaries (empty until you synthesise one) |
| Brief detail | `/research/AAPL` | Markdown body + citation chips + fact timeline |
| Audit trail | `/research/AAPL/audit-trail/1` | FR70 derivation chain accordion |
| Approvals | `/approvals` | Pending approval requests (SSE-driven) |
| Settings | `/settings` | Tenant settings |
| OpenAPI docs | `:8000/docs` | Swagger UI for every backend route |

### What needs more setup

- **Synthesising a real brief** requires an `ANTHROPIC_API_KEY` + Tier-A
  research keys (EDGAR, FRED, BLS, BEA). See
  [`getting-started.md`](getting-started.md) §4b. Without them, the
  Refresh button on a brief detail page returns 503/501.
- **Paper trading** requires IBKR TWS / Gateway running on
  `localhost:7497`. Wire via `IGUANATRADER_BROKER_*` env vars + add the
  `trading-daemon` service to the compose file (slice T4 docs forthcoming).

## Step 7 — TLS + reverse proxy (recommended for prod)

The MVP profile binds 8000 + 5173 directly. For real-world VPS exposure,
front them with Caddy or nginx:

```caddyfile
# /etc/caddy/Caddyfile
trading.example.com {
    @api path /api/* /docs /openapi.json /healthz /sse/*
    handle @api {
        reverse_proxy localhost:8000
    }
    handle {
        reverse_proxy localhost:5173
    }
}
```

Then unbind the host ports in `docker-compose.mvp.yml` (remove the
`ports:` blocks) so the containers are only reachable through the
proxy.

## Operator commands

All available via `docker compose -f docker-compose.mvp.yml run --rm api iguanatrader <cmd>`:

| Command | Purpose |
|---|---|
| `admin bootstrap-tenant <slug>` | Create the first tenant + admin user. |
| `admin bootstrap-tenant <slug> --force-reset` | **Destructive.** Delete existing tenant + users, then re-create. |
| `research refresh-brief --symbol AAPL` | One-shot brief synthesis (requires LLM + data keys). |
| `research audit --brief-id <uuid>` | Pretty-print the audit trail. |
| `approval list` | List pending approval requests. |
| `approval audit --request-id <uuid>` | Trace one request through its decision tree. |
| `ops halt` / `ops resume` / `ops override` | Risk kill-switch operator surface. |
| `trading run --mode paper --tenant <slug>` | Long-running paper-trading daemon. |

## Troubleshooting

| Symptom | Fix |
|---|---|
| Login returns `BootstrapNotReadyError` | Step 4 missing. Re-run `bootstrap-tenant`. |
| Login returns 500 with no detail | `IGUANATRADER_JWT_SECRET` is the placeholder. Set it via `.env` then `docker compose up -d --force-recreate api`. |
| Login returns 401 with valid creds | Password mismatch — check the password you typed in Step 4 wasn't echoed somewhere; re-run with `--force-reset`. |
| Frontend shows a SvelteKit 404 page | Browser hit `web:5173` before the `web` container finished cold-starting; wait 5s + reload. |
| `docker compose ps` shows `unhealthy` | `docker compose logs api` / `logs web` for stack traces. The healthcheck hits `/healthz` (api) and `/` (web). |

## Rolling updates

```bash
git pull --ff-only
docker compose -f docker-compose.mvp.yml build api web
docker compose -f docker-compose.mvp.yml up -d --force-recreate api web
docker compose -f docker-compose.mvp.yml run --rm api \
    python -m alembic -c apps/api/alembic.ini upgrade head
```

Migrations run AFTER the new image is up because Alembic is forward-only
(applying a migration written for code that's no longer running is
safer than the reverse). SQLite is single-writer so brief downtime during
the migration is acceptable.
