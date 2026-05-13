# iguanatrader — BACKLOG

> Snapshot 2026-05-13 after merging PRs #130 / #131 / #132 / #135 / #136 / #137.
> Maintained as a living document — when a row ships, move it to `retros/` instead of mutating it inline.

The MVP today (`docker compose -f docker-compose.mvp.yml ...`) has: login + JWT cookie, change-password (auth) + must_change_password gate, forgot-password endpoint with guardrail, settings page (feature flags + Security section), 7 dashboard tabs rendering honest "Vista pendiente" placeholders.

What's **missing** is split into two halves:

- **Section A — operator-side**: things the operator (Arturo) must provision/configure outside the codebase. **No code unblocks these — they need external accounts, DNS, or third-party services.**
- **Section B — dev-side**: things the codebase must grow into. **Each row is a future slice (proposal → tasks → PR) that I can implement.**

---

## Section A — Operator-side blockers (waiting on Arturo)

| # | Item | What's needed | Unblocks |
|---|---|---|---|
| A1 | **SMTP relay** for sender `iguanatrader@palafitofood.com` | Account at Mailgun / Resend / SES / Postmark / self-hosted Postfix → 4 env vars: `IGUANATRADER_SMTP_HOST`, `_PORT`, `_USERNAME`, `_PASSWORD` | Real email delivery for forgot-password + future alerts |
| A2 | **DNS SPF + DKIM** on `palafitofood.com` | Cloudflare DNS edit (operator owns the domain) | A1 emails not landing in spam |
| A3 | **Telegram chat_id** for Arturo's account | `/start` the iguanatrader bot → grab the returned `chat_id` → `UPDATE users SET telegram_chat_id='<id>' WHERE email='arturo6ramirez@gmail.com'` | Telegram recovery channel + future Telegram alerts |
| A4 | **Hermes service alignment** (WhatsApp channel) | Verify ELIGIA's Hermes deployment supports HMAC mode (iguanatrader's adapter signs POST bodies). If it uses bearer auth instead, decide: switch ELIGIA Hermes to HMAC, OR add a bearer-auth variant to iguanatrader's adapter. | WhatsApp recovery channel |
| A5 | **SOPS bundle key rename** (gated on A4) | `sops -d .secrets/dev.env.enc` → rename `HERMES_WEBHOOK_URL` → `HERMES_BASE_URL` + `HERMES_AUTH_TOKEN` → `HERMES_HMAC_SECRET` → re-encrypt. Mirror in `paper.env.enc` + `live.env.enc`. | A4 → activates iguanatrader's Hermes adapter |
| A6 | **ANTHROPIC_API_KEY** + Tier-A keys (EDGAR / FRED / BLS / BEA / FINNHUB) | Sign up at each provider (most are free) → populate in SOPS bundle | Real research brief synthesis at `/research/{symbol}` |
| A7 | **IBKR TWS / Gateway** + paper account creds | TWS Gateway running reachable from the iguanatrader container (host networking or `host.docker.internal`) + IBKR paper account credentials | Trading daemon (`iguanatrader trading run`) + real positions/trades/orders flowing |
| A8 | **OpenBB sidecar** (AGPL isolation) | Separate container with OpenBB Platform + API keys (Polygon, Intrinio, etc.) + `OPENBB_SIDECAR_URL` wired into api compose | Tier-B fundamentals (analyst_rating_avg, esg_score, fundamentals_snapshot) for research briefs |

Operator-side cost estimate (provisioning, not code): A1+A2 ~1 hour, A3 ~5 min, A4 ~30 min investigation, A5 ~10 min after A4, A6 ~1 hour of signups, A7 ~2 hours setup, A8 ~half-day.

---

## Section B — Dev-side backlog (Claude can ship)

### B1. Dashboard UI wiring (7 slices)

Each tab has backend endpoints already — the work is server-side `load` fns + page UI components + empty states + tests. Proposed slice names:

| Slice | Tab | Backend | New file(s) | Approx size |
|---|---|---|---|---|
| `portfolio-dashboard-mvp` | /portfolio | `/api/v1/portfolio` + `/positions` + `/equity` | `+page.server.ts`, replace placeholder with cash/positions table + equity sparkline | M |
| `trades-list-and-detail` | /trades | `/api/v1/trades` + `/{id}` + `/{id}/fills` | List page + `[trade_id]/+page.svelte` detail with fills | M |
| `strategies-config-ui` | /strategies | `/api/v1/strategies` (CRUD) | List + edit form (PUT/DELETE wired) | M |
| `research-index-and-list-endpoint` | /research | **NEW**: `GET /api/v1/research/briefs` list endpoint (watchlist-driven) + UI consuming it | New API route + UI list. `/research/{symbol}` already real | M+ |
| `approvals-queue-and-sse` | /approvals | `/api/v1/approvals` + `/api/v1/stream/approvals` (SSE) | Pending queue + SSE-driven realtime updates + approve/reject buttons | M+ |
| `risk-state-and-override-ui` | /risk | `/api/v1/risk/state` + `/risk/override` | Kill-switch status + override form | M |
| `costs-dashboard-mvp` | /costs | `/api/v1/costs/summary` + `/by-provider` + `/per-trade` | Spend dashboard + breakdown | M |

S/M/L: M = ~6 hours of slice work (proposal → tests → PR → CI green).

### B2. Auth + bootstrap follow-ups

| Slice | What | Why |
|---|---|---|
| `admin-set-password-cli` | `iguanatrader admin set-password <slug> --email <e>` | Non-destructive password reset (today only `bootstrap-tenant --force-reset` works; nukes tenant + data). |
| `admin-set-recovery-channels-cli` | `iguanatrader admin set-recovery-channel <slug> --email <e> --telegram <id> --whatsapp <phone>` | Operator-facing alternative to manual SQL UPDATE for `telegram_chat_id`/`whatsapp_phone` (carry-forward from PR #135). |
| `bootstrap-tenant-must-change-password-flag` | `--must-change-password` opt-in on bootstrap | Force first-login rotation for provisional admin credentials (carry-forward from PR #132). |
| `forgot-password-per-email-rate-limit` | Custom slowapi keyfunc `(ip, email)` for `/forgot-password` | Today only IP-rate-limited — stricter abuse prevention. Carry from PR #135. |

### B3. Trading + research activation (S/M slices)

| Slice | What |
|---|---|
| `trading-daemon-compose-service` | Add `trading-daemon` as a 3rd compose service running `iguanatrader trading run --mode paper`. Blocked on A7 (IBKR). |
| `research-source-feature-flags` | Wire per-source enable/disable via env or settings UI (currently all-or-nothing per Tier). |
| `tier-c-registry-populate` | Populate the Tier-C feature provider registry with VDEM + WGI (currently empty stub). |
| `cli-coverage-audit` | Audit each `iguanatrader <subcommand>` for end-to-end smoke runnability + add operator-runbook doc. |

### B4. Dormant code activation (per audit table in PR #135 description)

Some dormant code lights up after Section A items land. None require new slices — just env wiring. Listed for traceability:

- A1 + A5 lights up: SMTP adapter, Hermes adapter
- A3 (chat_id) lights up: Telegram adapter (already wired in compose env)
- A6 lights up: EDGAR / FRED / BLS / BEA / FINNHUB research adapters → real brief synthesis
- A7 lights up: IBKR adapter + market_data ingestion + trading daemon
- A8 lights up: OpenBB sidecar → Tier-B feature provider

### B5. CI / infra small improvements

| Slice | What |
|---|---|
| `ci-container-smoke-test` | New job in `build-images.yml`: after `docker compose build`, run `up -d` + `curl /healthz` + `curl /` to catch runtime regressions (would have caught 5/8 bugs from PR #130). |
| `vps-deploy-runbook` | Codify the SOPS-decrypt → `.env` → migrate → `up -d` flow as a script (`scripts/deploy-vps.sh`) instead of operator running each command manually. |
| `mvp-deploy-md-truth-pass` | Rewrite the `What works in MVP` table in `docs/mvp-deploy.md` to match reality (today says `/portfolio` is "loading…" which is now `Vista pendiente`; says `/research` works which is false at the index level). |

---

## Priority ranking (subjective, by Claude based on user value)

1. **B5 `mvp-deploy-md-truth-pass`** — 10 min. Stop the docs lying.
2. **B2 `admin-set-password-cli`** — 1 hour. Removes the destructive `--force-reset` footgun.
3. **B1 `portfolio-dashboard-mvp`** — 4-6 hours. Most "real trader bot" UX win for the time invested.
4. **B5 `ci-container-smoke-test`** — 2 hours. Pays back 10× by catching future runtime regressions pre-merge.
5. **Section A items** — operator's call.
6. **Rest of B1** — 6× ~6h slices.

---

## How this file evolves

- New slice spawned → add a row in B with proposal link.
- Slice shipped → REMOVE the row (don't leave checkmark debris); the squash commit + retro carries history.
- Section A items resolved → REMOVE the row.
- Quarterly: re-snapshot the file with the current date header.
