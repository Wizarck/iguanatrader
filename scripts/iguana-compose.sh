#!/usr/bin/env bash
# iguana-compose — SOPS-aware docker compose wrapper.
#
# Decrypts .secrets/<profile>.env.enc with the operator's age key
# (~/.config/sops/age/keys.txt) and runs `docker compose` with the
# plaintext values populated via `--env-file`. Plaintext lives briefly
# in a mode-600 tempfile under $TMPDIR that is removed on exit (trap).
#
# Usage:
#
#   scripts/iguana-compose.sh <profile> <docker-compose-subcommand> [args...]
#
# Profiles:
#   dev    — local development; .secrets/dev.env.enc
#   paper  — paper trading on VPS; .secrets/paper.env.enc; mvp+postgres+ibgateway overlays
#   live   — live trading on VPS; .secrets/live.env.enc; mvp+postgres+ibgateway overlays
#
# Examples:
#   scripts/iguana-compose.sh paper up -d
#   scripts/iguana-compose.sh paper ps
#   scripts/iguana-compose.sh paper logs -f --tail=50 ib-gateway
#   scripts/iguana-compose.sh paper down
#   scripts/iguana-compose.sh live up -d
#
# Prereqs:
#   - sops binary on PATH (https://github.com/getsops/sops/releases)
#   - age private key at ~/.config/sops/age/keys.txt with a recipient
#     listed in .secrets/.sops.yaml (sops 3.7.3 does NOT auto-find this
#     path — we set SOPS_AGE_KEY_FILE explicitly).
#
# Exit codes:
#   1 — usage error / unknown profile
#   2 — secrets file missing for profile
#   3 — sops binary missing
#   4 — age key file missing
#   N — propagated from `docker compose`
#
# Why a tempfile and not `sops exec-env`: sops 3.7.3's `exec-env`
# subcommand infers the input format from the file extension and does
# NOT accept `--input-type` (regression vs the top-level sops binary).
# Our encrypted files are dotenv-format with `.env.enc` extension,
# which sops defaults to JSON. Using `sops -d --input-type=dotenv` +
# `--env-file` bypasses the format-detection bug while keeping the
# plaintext on a chmod-600 tempfile that the EXIT trap removes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SECRETS_DIR="$REPO_ROOT/.secrets"
AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"

usage() {
  cat >&2 <<'EOF'
Usage: scripts/iguana-compose.sh <profile> <docker-compose-subcommand> [args...]

Profiles: dev | paper | live

Examples:
  scripts/iguana-compose.sh paper up -d
  scripts/iguana-compose.sh paper logs -f api
  scripts/iguana-compose.sh live ps
EOF
  exit 1
}

if [[ $# -lt 2 ]]; then
  usage
fi

PROFILE="$1"
shift

case "$PROFILE" in
  dev|paper|live) ;;
  *) echo "error: unknown profile '$PROFILE' (expected dev|paper|live)" >&2; exit 1 ;;
esac

SECRETS_FILE="$SECRETS_DIR/$PROFILE.env.enc"
if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "error: secrets file not found: $SECRETS_FILE" >&2
  exit 2
fi

if ! command -v sops >/dev/null 2>&1; then
  echo "error: sops binary not on PATH (see https://github.com/getsops/sops/releases)" >&2
  exit 3
fi

if [[ ! -f "$AGE_KEY_FILE" ]]; then
  echo "error: age key file not found: $AGE_KEY_FILE" >&2
  echo "       set SOPS_AGE_KEY_FILE to override the default path." >&2
  exit 4
fi

# Decrypt into a chmod-600 tempfile that EXIT trap removes.
TMP_ENV="$(mktemp -t "iguana-${PROFILE}-XXXXXX.env")"
chmod 600 "$TMP_ENV"
trap 'rm -f -- "$TMP_ENV"' EXIT

SOPS_AGE_KEY_FILE="$AGE_KEY_FILE" \
  sops --input-type=dotenv --output-type=dotenv -d "$SECRETS_FILE" > "$TMP_ENV"

# Compose overlay stack per profile. `dev` keeps the MVP single-host
# defaults; paper + live layer postgres + ibgateway on top.
#
# Overlays are loaded conditionally on file existence so this wrapper
# works across the incremental rollout of Fase A slices — the postgres
# overlay landed in slice ``postgres-compose-overlay``, the ibgateway
# overlay in slice ``ibkr-gateway-sidecar``, etc. If you bring up
# paper/live on a branch where one of those is not yet merged, the
# wrapper transparently falls back to the layers that ARE present.
COMPOSE_FILES=( -f "$REPO_ROOT/compose/mvp.yml" )
if [[ -f "$REPO_ROOT/compose/mvp.override.yml" ]]; then
  COMPOSE_FILES+=( -f "$REPO_ROOT/compose/mvp.override.yml" )
fi
case "$PROFILE" in
  paper|live)
    if [[ -f "$REPO_ROOT/compose/postgres.yml" ]]; then
      COMPOSE_FILES+=( -f "$REPO_ROOT/compose/postgres.yml" )
    fi
    if [[ -f "$REPO_ROOT/compose/ibgateway.yml" ]]; then
      COMPOSE_FILES+=( -f "$REPO_ROOT/compose/ibgateway.yml" )
    fi
    ;;
esac

# Note: no `exec` — we need the EXIT trap above to fire and remove
# the plaintext tempfile after docker compose returns.
docker compose "${COMPOSE_FILES[@]}" --env-file "$TMP_ENV" "$@"
