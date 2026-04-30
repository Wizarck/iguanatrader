---
type: getting-started
project: iguanatrader
schema_version: 1
created: 2026-04-30
updated: 2026-04-30
purpose: Onboarding for a fresh clone — prereqs, install, first-run paper trading walkthrough
---

# Getting Started — iguanatrader

This document is the canonical onboarding entry. Read it once on a fresh clone; subsequent slices flesh out specific runbooks.

## 1. Prerequisites

Required versions (verified via `make bootstrap`):

| Tool | Min version | Verify | Install |
|---|---|---|---|
| Python | 3.11 | `python --version` | https://www.python.org/downloads/ (NOT Microsoft Store — see [docs/gotchas.md](gotchas.md)) |
| Node | 20 | `node --version` | https://nodejs.org/ |
| pnpm | 9 | `pnpm --version` | `npm install -g pnpm` |
| Poetry | 1.8 | `python -m poetry --version` | `pip install --user poetry` |
| Docker | 20.10 | `docker --version` | https://www.docker.com/products/docker-desktop |
| age | 1.0 | `age --version` | https://github.com/FiloSottile/age (or `winget install FiloSottile.age`) |
| sops | 3.8 | `sops --version` | https://github.com/getsops/sops (or `winget install Mozilla.SOPS`) |

### JSON1 SQLite verification

iguanatrader stores bitemporal research facts in SQLite with the JSON1 extension (per `docs/architecture-decisions.md` data layer). Verify your local Python's SQLite has it:

```bash
python -c "import sqlite3; sqlite3.connect(':memory:').execute('SELECT json(\"{}\")'); print('JSON1 OK')"
```

If this prints `JSON1 OK`, you're set. If you get `OperationalError: no such function: json`, install a Python build that includes JSON1 (the python.org installers do; some distro packages don't).

## 2. Install

```bash
git clone https://github.com/Wizarck/iguanatrader.git
cd iguanatrader
git submodule update --init --recursive
make bootstrap
```

`make bootstrap` runs:

1. Toolchain version checks (above).
2. `python -m poetry install --no-interaction` — Python dev deps.
3. `pnpm install --frozen-lockfile` — Node dev deps.
4. `pre-commit install` — activates the gitleaks-first hook chain.

## 3. Secrets — first-time setup

iguanatrader uses [SOPS + age](https://github.com/getsops/sops) for encrypted env files. The encryption recipient is the **iguanatrader master key**, derived deterministically from a passphrase via scrypt (salt: `iguanatrader-master-key-v1`).

### On a new dev machine, derive the master key locally:

```bash
python <<'PY'
import hashlib, sys, pathlib
sys.path.insert(0, "../eligia-core/desktop-stack/scripts")  # adjust if eligia-core lives elsewhere
import eligia_crypto

passphrase = input("iguanatrader master passphrase: ")
salt = b"iguanatrader-master-key-v1"
seed = hashlib.scrypt(passphrase.encode(), salt=salt, n=2**14, r=8, p=3, dklen=32)
identity = eligia_crypto._secret_to_age_identity(seed)
recipient = eligia_crypto._secret_to_age_recipient(seed)

print(f"public key (already in .secrets/.sops.yaml): {recipient}")
keys_file = pathlib.Path.home() / ".config/sops/age/keys.txt"
keys_file.parent.mkdir(parents=True, exist_ok=True)
content = keys_file.read_text(encoding="utf-8") if keys_file.exists() else ""
if identity in content:
    print("private key already in keys.txt; nothing to do")
else:
    block = f"\n# iguanatrader master key (password-derived, salt iguanatrader-master-key-v1)\n{identity}\n"
    keys_file.write_text(content + block, encoding="utf-8")
    print(f"private key appended to {keys_file}")
PY
```

The public key in `.secrets/.sops.yaml` MUST equal the printed value — if it doesn't, you typed the passphrase wrong (or you're on a different project's salt).

### Decrypt + edit a profile env

```bash
sops .secrets/dev.env.enc       # opens decrypted in $EDITOR; saves re-encrypted on exit
sops --decrypt .secrets/dev.env.enc   # prints to stdout (read-only)
```

## 4. First-run paper trading walkthrough

**(slice T2 + T3 + T4 plant the runtime; this section becomes runnable end-to-end after Wave 4 lands)**

Until then:

1. Fill `.secrets/paper.env.enc` with your IBKR paper-trading credentials (host, port `7497`, API key) via `sops .secrets/paper.env.enc`.
2. Start TWS/Gateway in paper-trading mode.
3. `docker compose -f docker-compose.paper.yml up` — boots the paper-trading bot.
4. The bot listens on `localhost:8000`. Health check: `curl http://localhost:8000/healthz`.

Live trading (`docker-compose.live.yml`) requires the operator to acknowledge risk via `--confirm-live --i-understand-the-risks` flag (per AGENTS.md §7 Override 1).

## 5. What's next

| Topic | Where |
|---|---|
| Architecture overview | [`architecture-decisions.md`](architecture-decisions.md) |
| Why these tech choices | [`adr/`](adr/) |
| Slice plan + dependency graph | [`openspec-slice.md`](openspec-slice.md) |
| Data model (bitemporal facts, append-only events) | [`data-model.md`](data-model.md) |
| Project structure (directory layout) | [`project-structure.md`](project-structure.md) |
| Non-obvious dev-loop quirks | [`gotchas.md`](gotchas.md) |

## 6. Help

- Bug / feature: open a [GitHub issue](https://github.com/Wizarck/iguanatrader/issues).
- Security: [`SECURITY.md`](../SECURITY.md) (private channel only).
- Direct: `arturo6ramirez@gmail.com`.
