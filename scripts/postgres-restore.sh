#!/usr/bin/env sh
# postgres-restore.sh — pg_restore wrapper.
#
# Restores a single iguanatrader-*.sql.gz backup (produced by
# postgres-backup.sh) into a Postgres database. Designed to run
# INSIDE the `pg-backup` container which has psql + pg_restore.
#
# Usage (run via docker compose):
#
#   docker compose [overlays] run --rm pg-backup \
#       /scripts/postgres-restore.sh /backups/iguanatrader-2026-05-15T02-00-00Z.sql.gz
#
# Reads from env:
#   PGHOST     — defaults to `postgres`
#   PGPORT     — defaults to 5432
#   PGUSER     — defaults to `iguanatrader`
#   PGPASSWORD — required
#   PGDATABASE — defaults to `iguanatrader`
#   DROP_DB_FIRST — if "yes", DROP DATABASE + CREATE DATABASE before
#                   restoring. Off by default — pg_restore --clean
#                   handles object-level recreate inside the database.
#
# Exit codes:
#   0 — restore OK
#   1 — backup file missing / unreadable
#   2 — gunzip failed
#   3 — pg_restore failed
#   4 — required env missing
#
# Pairs with docs/runbooks/postgres-backup-restore.md §3.

set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <backup-file.sql.gz>" >&2
  exit 1
fi
BACKUP_FILE="$1"
shift

PGHOST="${PGHOST:-postgres}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-iguanatrader}"
PGDATABASE="${PGDATABASE:-iguanatrader}"
DROP_DB_FIRST="${DROP_DB_FIRST:-no}"

if [ -z "${PGPASSWORD:-}" ]; then
  echo "error: PGPASSWORD is required" >&2
  exit 4
fi

if [ ! -f "$BACKUP_FILE" ] || [ ! -r "$BACKUP_FILE" ]; then
  echo "error: backup file missing or unreadable: $BACKUP_FILE" >&2
  exit 1
fi

TMPDUMP="$(mktemp -t iguana-restore-XXXXXX.dump)"
trap 'rm -f -- "$TMPDUMP"' EXIT

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] decompressing $BACKUP_FILE"
if ! gunzip -c "$BACKUP_FILE" > "$TMPDUMP"; then
  echo "error: gunzip failed" >&2
  exit 2
fi

export PGPASSWORD

if [ "$DROP_DB_FIRST" = "yes" ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] DROP+CREATE $PGDATABASE"
  # Connect to template1 to drop the target DB cleanly.
  psql --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" --dbname=postgres \
       -c "DROP DATABASE IF EXISTS \"$PGDATABASE\" WITH (FORCE);" \
       -c "CREATE DATABASE \"$PGDATABASE\" OWNER \"$PGUSER\";"
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting pg_restore into $PGDATABASE"
if ! pg_restore \
       --host="$PGHOST" \
       --port="$PGPORT" \
       --username="$PGUSER" \
       --dbname="$PGDATABASE" \
       --no-owner \
       --no-acl \
       --clean \
       --if-exists \
       --exit-on-error \
       "$TMPDUMP"; then
  echo "error: pg_restore failed" >&2
  exit 3
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] OK: restored from $BACKUP_FILE"
