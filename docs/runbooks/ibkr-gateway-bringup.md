# Runbook — bring up the IB Gateway sidecar

**Audience**: operator (Arturo / single-host MVP).

**When to run**:

- First-time bring-up of the IB Gateway sidecar on a VPS.
- Switching the deployment between paper and live IBKR.
- Recovery after IBKR challenges a 2FA prompt and the gateway is stuck on the lock screen.

**Time budget**: 10–20 minutes for first-time setup; 2–5 minutes for paper/live switches; up to an hour if IBKR demands a 2FA confirmation that requires the mobile app.

**Blast radius**:

- The api container loses broker connectivity while the gateway is restarting.
- No data loss (no DB writes from the gateway).
- Order flow pauses; the trade state machine respects the broker `disconnected` state.

---

## 0. Security pre-bring-up (applies to paper AND live)

Run this checklist **once per VPS** before the first bring-up, and re-validate before flipping paper→live. Derived from the deep cybersecurity audit performed 2026-05-18 (see PR #261).

**Image supply chain**:

- [ ] `compose/ibgateway.yml` pins `gnzsnz/ib-gateway` by `sha256` digest (NOT the floating `:stable` tag). Re-pin only after manual review of the next release notes — quarterly cadence (see [roadmap-ops.md](../roadmap-ops.md) O3).
- [ ] (Pre-rebuild only) cross-check the IB Gateway installer SHA256 in the gnzsnz Dockerfile against IBKR's official `download2.interactivebrokers.com` distribution. One-time, out-of-band.

**Host-side**:

- [ ] `chmod 660 /var/run/docker.sock` on the VPS; audit `getent group docker` — only the operator account should be in it. Anyone with the docker socket bypasses SOPS entirely (can `docker exec` and read env / `config.ini` plaintext).
- [ ] Age private key (`~/.config/sops/age/keys.txt`) is on your **laptop only**, NEVER copied to the VPS. SOPS decrypt happens locally; the decrypted env is pushed to the VPS at deploy time via `scp` to a tmpfs / direct `docker compose up` from your laptop.
- [ ] Egress firewall on the VPS restricts the `ib-gateway` container's outbound traffic to `*.interactivebrokers.com` + Akamai edge ranges + your own services. Recommended via `iptables` or `ufw` on the host network namespace.

**Container-side**:

- [ ] `VNC_SERVER_PASSWORD` is UNSET unless you are actively bringing up the gateway (2FA challenge or first login). Setting it permanently leaves an extra credential surface on port 5900 with no benefit.
- [ ] First-week monitoring: from the VPS, run `nsenter -t $(docker inspect -f '{{.State.Pid}}' iguanatrader-ib-gateway-1) -n ss -tnp` periodically. Expected outbound endpoints only: `gdcdyn.interactivebrokers.com:4000-4002` (or sibling `ndcdyn`/`cdcdyn` depending on region). Anything else = investigate.

**Account-side**:

- [ ] Validate paper-trading account 1–2 weeks **before** populating the live credentials in `live.env.enc`. The cutover is one-line (`TRADING_MODE=live` + `TWS_PORT=4001`) so the practice run in paper gives you confidence the procedure is solid.
- [ ] When ready to flip to live: confirm with yourself that risk caps in `LIVE_CAPITAL_CAP_USD` are sized appropriately. The cutover is reversible (`TRADING_MODE=paper`) but a misconfigured cap during live can place real orders.

**Domain reference** (for your own verification):

The `Xdcdyn.interactivebrokers.com` pattern is IBKR's regional Gateway Discovery family (g=Europe, n=North America, c=Asia). DigiCert EV cert for `O=IBG LLC, Greenwich, Connecticut` validates these subdomains — verifiable via `openssl s_client -connect gdcdyn.interactivebrokers.com:443 -servername gdcdyn.interactivebrokers.com`.

---

## 1. Credentials (paper)

Paper account on this deployment: username `okqtbz074`, account `DUR071858` (pending IBKR approval as of 2026-05-15 — verify in the [IBKR portal](https://www.interactivebrokers.com/) before bringing up).

```sh
ssh eligia-vps
cd /opt/iguanatrader

# Source the SOPS-decrypted env once slice `sops-decrypt-at-boot`
# ships. Until then, export manually for the bring-up:
export TWS_USERID=okqtbz074
export TWS_PASSWORD='<from password manager>'
export TRADING_MODE=paper
export TWS_PORT=4002
export READ_ONLY_API=no
export VNC_SERVER_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(12))")
echo "VNC password: $VNC_SERVER_PASSWORD"  # save to password manager
```

## 2. Start the stack with the IB Gateway overlay

```sh
docker compose \
  -f compose/mvp.yml \
  -f compose/mvp.override.yml \
  -f compose/postgres.yml \
  -f compose/ibgateway.yml \
  up -d
```

The gateway healthcheck takes ~90 seconds on first boot (IBC needs to launch Java, log in, and open the API socket). Track progress:

```sh
docker compose ... ps  # ib-gateway should go starting -> healthy
docker compose ... logs -f --tail=50 ib-gateway
```

Healthy output ends with a line like `IBC: Login successful` and the API port (4002 for paper) listening.

## 3. Smoke-test connectivity from the api container

```sh
docker compose ... exec api python -c "
import os, asyncio
from iguanatrader.config.secrets import SecretEnv
async def main():
    se = SecretEnv()
    print(f'host={se.ibkr_host} port={se.tws_port} user={se.ibkr_username}')
    # Minimal handshake — adapter import + connect probe
    from iguanatrader.contexts.trading.brokers.ib_async_client import IbAsyncIBClient
    c = IbAsyncIBClient()
    await c.connect(host=se.ibkr_host, port=se.tws_port, client_id=se.ib_client_id)
    print('Connected:', c.is_connected())
    await c.disconnect()
asyncio.run(main())
"
```

Expected: `Connected: True`. If False, check the gateway logs for IBC login failures.

## 4. Cut over to live

```sh
docker compose ... stop ib-gateway
export TWS_USERID=arturoramirez6   # live username
export TWS_PASSWORD='<live password from password manager>'
export TRADING_MODE=live
export TWS_PORT=4001
docker compose ... up -d ib-gateway
```

Wait ~90s for the healthcheck. Same smoke-test as step 3 with the live `TWS_PORT=4001`.

**Before flipping the api container** to talk to the live gateway: confirm with the operator that the strategy + risk caps are sized for real capital. The slice ``trade-close-flow-exit-pathway`` made the lifecycle terminal-fill aware; verify no in-flight paper trades are open.

## 5. 2FA + VNC emergency access

IBKR occasionally challenges Gateway logins with a mobile-app 2FA prompt. When the healthcheck stays in `starting` past 3 minutes, gateway is probably stuck on the prompt screen.

Open a VNC tunnel from your operator machine:

```sh
# On your laptop
ssh -L 5900:127.0.0.1:5900 eligia-vps
# In a separate terminal, connect a VNC viewer (TigerVNC, RealVNC, etc.)
# to localhost:5900 with the password from step 1.
```

Confirm the 2FA prompt on your phone, then close the VNC tunnel.

## 6. Weekly IBKR-side restart

IBKR forces a Gateway restart once a week (typically Sunday morning, account-region-dependent). `gnzsnz/ib-gateway` handles this internally via IBC's `RestartTime` setting; you should see a brief healthcheck drop + recovery in the logs. Nothing to action unless the gateway fails to come back inside 5 minutes — then re-run step 2.

---

## Rollback

If the gateway misbehaves and you want to fall back to the no-broker stack (api will boot but order placement will fail with `MissingSecretError` until IBKR_HOST is unset / pointed elsewhere):

```sh
docker compose -f compose/mvp.yml \
               -f compose/mvp.override.yml \
               -f compose/postgres.yml \
               stop ib-gateway
docker compose -f compose/mvp.yml \
               -f compose/mvp.override.yml \
               -f compose/postgres.yml \
               up -d   # without the ibgateway overlay
```

The api container restarts without the `IBKR_HOST=ib-gateway` override; broker calls in the trade flow surface as `MissingSecretError` (HTTP 500). UI + research surfaces are unaffected.

---

## §7 Dual-daemon (paper + live) bring-up + toggle / reconcile via the UI

Slice `2026-05-18-dual-daemon-mode-toggle-and-reconcile` splits the single trading daemon into two parallel processes (`trading_daemon_paper` + `trading_daemon_live`) with their own gateway sidecars + own IBKR client ID + own scheduler jobstore. The live daemon **defaults to `enabled=false`** (migration 0026 seed) so the container can boot before the operator has populated live credentials.

### 7.1 Operator toggle via the header chip (recommended path)

Once both daemons are running:

1. Open the dashboard. Two chips appear at the top-right of every `(app)/*` page: yellow **PAPER** + red **LIVE**.
2. Click the chip to open the toggle modal.
   - **Paper toggle**: simple "Activar / Desactivar paper" + optional reason → submit. No password re-entry.
   - **Live toggle**: warning header + REQUIRED reason (>=20 chars) + REQUIRED password re-entry. The server re-verifies the password via the same Argon2id compare as login; a wrong password returns 403 and the modal stays open with a "contraseña incorrecta" hint + cleared password field.
3. The chip updates within ~10s of the toggle. Behind the scenes the API writes to `tenant_trading_modes.last_toggled_at` and the daemon's heartbeat cron (every 10s) reads that timestamp and runs drain when the flag transitioned to false.

### 7.2 On-demand reconcile (Settings → §Daemons → "Reconcile" button)

Triggers a forced sync between local state and IBKR's authoritative book. First cut reconciles fills (via the existing `TradingService.startup_reconcile`) + writes one `EquitySnapshot(snapshot_kind='event')` row from `broker.get_account_equity()`. Position-side reconcile (closing local trades absent from IBKR) is a Phase-2.5 follow-up.

Cross-process signal: API endpoint writes `tenant_trading_modes.pending_reconcile_at = now()`; daemon heartbeat cron compares against an in-memory watermark + runs reconcile when newer.

Returns 202 Accepted with a `correlation_id` UUID. Grep that ID against daemon-side structlog to trace the reconcile through to fill ingestion.

### 7.3 Drain semantics

On a true→false toggle the daemon's next heartbeat tick bulk-rejects `trade_proposals` rows where `mode = :mode AND state = 'pending_approval'`:

```sql
UPDATE trade_proposals
SET state = 'rejected',
    rejection_reason = 'daemon_drained',
    rejected_at = now()
WHERE tenant_id = :tenant AND mode = :mode AND state = 'pending_approval'
```

IBKR-side orders are **NOT** cancelled — IBKR is the authoritative book; we only refuse to create new orders going forward. To cancel an in-flight order, use IBKR's own TWS UI or `iguanatrader trading cancel <order_id>`.

### 7.4 Operator pre-bring-up checklist for live

Before flipping `live.enabled = true`:

- [ ] `.secrets/live.env.enc` carries `IBKR_USERNAME_LIVE` + `IBKR_PASSWORD_LIVE` (operator-owned SOPS edit; see §0).
- [ ] `IGUANATRADER_DAEMON_LIVE_SCHEDULER_ONLY` is `false` on the host (default is `true` for VPS where TWS is unreachable).
- [ ] `ib-gateway-live` health is `service_healthy` (compose port 4001 reachable, IBC auto-login completed).
- [ ] Recent reconcile (`POST /api/v1/daemons/live/reconcile` or the Settings button) shows fresh equity snapshot in `equity_snapshots` for `mode='live'`.
- [ ] Risk caps for live (`LIVE_CAPITAL_CAP_USD`) are set to the operator-intended ceiling (not the same number as paper).

After ticking all five, the toggle modal's live submit becomes the appropriate gate.
