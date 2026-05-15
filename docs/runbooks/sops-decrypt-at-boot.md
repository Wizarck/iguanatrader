# Runbook — bring up iguanatrader with SOPS-decrypted secrets

**Audience**: operator (Arturo / single-host MVP) bringing up paper or live deployments on the VPS.

**When to run**:

- Any iguanatrader bring-up that touches paper or live credentials. Replaces the `export TWS_USERID=…` shell-export pattern from `docs/runbooks/ibkr-gateway-bringup.md` §1 once the operator has SOPS configured locally.
- Recovery after a `MissingSecretError` boot failure in the api container.

**Time budget**: ~2 minutes after first-time SOPS setup; ~10 minutes if you also need to install `sops` + register the age key.

**Blast radius**: zero — the wrapper is a thin shell layer; misuse fails closed (the api container won't boot without the env vars). Plaintext credentials live briefly in a `mode 600` tempfile in `$TMPDIR` and are removed by an EXIT trap.

---

## 1. One-time SOPS setup

```sh
# Install sops if missing (Linux/macOS via brew; Windows winget shown below):
winget install Mozilla.SOPS    # Windows
# brew install sops            # macOS
# apt install sops             # Debian/Ubuntu

# Verify
sops --version
```

Register the iguanatrader age private key under your home dir. The public-key recipient is in `.secrets/.sops.yaml`:

```sh
ls -la ~/.config/sops/age/keys.txt
# If missing, copy from your password manager / cross-machine bootstrap:
mkdir -p ~/.config/sops/age
chmod 700 ~/.config/sops/age
# Paste the private key (starts with `AGE-SECRET-KEY-1...`) into keys.txt:
nano ~/.config/sops/age/keys.txt
chmod 600 ~/.config/sops/age/keys.txt
```

If you don't have the private key: it's per-dev. Recover the master via passphrase (`docs/getting-started.md §Secrets`) or generate a new per-node key + ask whoever has the iguanatrader-master to add your public key to `.secrets/.sops.yaml` and re-encrypt the bundles.

Sanity-check decryption:

```sh
sops --input-type=dotenv --output-type=dotenv -d .secrets/dev.env.enc | head -5
```

You should see plain `KEY=VALUE` lines (placeholders if it's the dev bundle on a fresh repo).

## 2. Daily bring-up with the wrapper

The wrapper `scripts/iguana-compose.sh` decrypts the chosen profile's secrets, layers the right compose overlays, and forwards to `docker compose`:

```sh
# Paper trading on VPS
scripts/iguana-compose.sh paper up -d

# Logs from any service
scripts/iguana-compose.sh paper logs -f --tail=50 ib-gateway

# Status snapshot
scripts/iguana-compose.sh paper ps

# Shutdown
scripts/iguana-compose.sh paper down
```

Profile → file → overlays:

| Profile | Secrets file              | Overlays loaded (in order) |
|---------|---------------------------|----------------------------|
| `dev`   | `.secrets/dev.env.enc`    | `mvp.yml` + `mvp.override.yml` |
| `paper` | `.secrets/paper.env.enc`  | `mvp.yml` + `mvp.override.yml` + `postgres.yml` + `ibgateway.yml` |
| `live`  | `.secrets/live.env.enc`   | `mvp.yml` + `mvp.override.yml` + `postgres.yml` + `ibgateway.yml` |

Overlays are loaded conditionally on file existence so the wrapper works across the incremental Fase A slice rollout — if you check out a branch where one overlay is not yet present, the wrapper transparently skips it.

## 3. How the plaintext is protected

- The wrapper runs `sops -d --input-type=dotenv --output-type=dotenv` and writes the plaintext to `mktemp -t iguana-${PROFILE}-XXXXXX.env`.
- Immediately `chmod 600` so only the operator UID can read it.
- A `trap 'rm -f $TMP_ENV' EXIT` removes the file as soon as the wrapper exits — success, failure, or signal.
- The plaintext is NOT exported into the parent shell environment, so it doesn't leak into `ps`/`/proc/.../environ` of unrelated processes.

Limitations:

- The tempfile exists on disk while docker compose runs. On the VPS, `/tmp` lives on the same volume as the rest of the rootfs — there's no in-memory tmpfs by default. If you need stricter guarantees, run on a host where `/tmp` is `tmpfs` (most modern Linux distros: yes by default).
- `docker compose` itself reads the `--env-file` and may keep variables in its own state during `up`. After `up -d` returns, the secrets live inside the containers' env (visible via `docker inspect` to anyone with docker socket access — same threat model as any compose deploy).

## 4. Editing a secrets bundle

```sh
sops .secrets/paper.env.enc   # opens decrypted in $EDITOR; saves re-encrypted on exit
```

Or print decrypted to stdout (read-only):

```sh
sops -d .secrets/paper.env.enc   # auto-detects format (works without flags for editor mode)
sops --input-type=dotenv --output-type=dotenv -d .secrets/paper.env.enc   # explicit for scripts
```

Commit + push the encrypted file:

```sh
git add .secrets/paper.env.enc
git commit -m "chore(secrets): rotate <KEY_NAME> for paper"
git push
```

The plaintext stays on your machine only.

## 5. Adding a new recipient

If a new dev machine needs to decrypt:

```sh
# On the new machine: generate an age key
age-keygen -o ~/.config/sops/age/keys.txt
chmod 600 ~/.config/sops/age/keys.txt
# Copy the public key (printed by age-keygen)

# Back on a machine that ALREADY can decrypt:
# Edit .secrets/.sops.yaml — append the new public key to the recipients line
git diff .secrets/.sops.yaml   # review

# Re-encrypt each bundle so the new recipient is added:
sops updatekeys .secrets/dev.env.enc
sops updatekeys .secrets/paper.env.enc
sops updatekeys .secrets/live.env.enc

git add .secrets/
git commit -m "chore(secrets): authorize <dev-name> for SOPS decrypt"
```

---

## Rollback

If the wrapper misbehaves, fall back to the manual `export` pattern documented in `docs/runbooks/ibkr-gateway-bringup.md` §1 — same env vars, just typed by hand into the shell. Useful for debugging variable resolution.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `error: age key file not found` | `~/.config/sops/age/keys.txt` missing | See §1; or set `SOPS_AGE_KEY_FILE=/alt/path` and re-run. |
| `Failed to get the data key` | Age key doesn't match any recipient in `.sops.yaml` | Confirm the right keys.txt is in place; if your public key isn't in `.sops.yaml`, ask another dev to add it + `sops updatekeys`. |
| `Error unmarshalling input json` | `sops` invoked without `--input-type=dotenv` (the wrapper passes it; bare `sops exec-env` calls don't) | Use `scripts/iguana-compose.sh`, not raw `sops exec-env`. |
| Containers boot but `MissingSecretError` in logs | Decrypted file is missing a key the adapter needs | `sops .secrets/<profile>.env.enc` and add the missing `KEY=value`. |
