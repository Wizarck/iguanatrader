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

- [ ] `docker-compose.ibgateway.yml` pins `gnzsnz/ib-gateway` by `sha256` digest (NOT the floating `:stable` tag). Re-pin only after manual review of the next release notes — quarterly cadence (see [roadmap-ops.md](../roadmap-ops.md) O3).
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
  -f docker-compose.mvp.yml \
  -f docker-compose.mvp.override.yml \
  -f docker-compose.postgres.yml \
  -f docker-compose.ibgateway.yml \
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
docker compose -f docker-compose.mvp.yml \
               -f docker-compose.mvp.override.yml \
               -f docker-compose.postgres.yml \
               stop ib-gateway
docker compose -f docker-compose.mvp.yml \
               -f docker-compose.mvp.override.yml \
               -f docker-compose.postgres.yml \
               up -d   # without the ibgateway overlay
```

The api container restarts without the `IBKR_HOST=ib-gateway` override; broker calls in the trade flow surface as `MissingSecretError` (HTTP 500). UI + research surfaces are unaffected.
