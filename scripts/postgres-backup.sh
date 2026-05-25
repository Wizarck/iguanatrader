#!/usr/bin/env sh
# postgres-backup.sh — pg_dump wrapper with rotation.
#
# Invoked by the `pg-backup` service in compose/backup.yml on
# a sleep+loop cadence. Designed to run INSIDE a container with
# postgres + gzip available (postgres:16-alpine).
#
# Reads from env (provided by the compose service):
#   PGHOST     — defaults to `postgres`
#   PGPORT     — defaults to 5432
#   PGUSER     — defaults to `iguanatrader`
#   PGPASSWORD — required
#   PGDATABASE — defaults to `iguanatrader`
#   BACKUP_DIR — defaults to /backups (mounted from host)
#   RETENTION_DAYS — defaults to 30
#
# Output: ${BACKUP_DIR}/iguanatrader-YYYY-MM-DDTHH-MM-SSZ.sql.gz
#
# Exit codes:
#   0 — dump + rotate OK
#   1 — pg_dump failed
#   2 — gzip failed
#   3 — BACKUP_DIR missing / not writable
#
# Companion: scripts/postgres-restore.sh restores from one of these
# files. See docs/runbooks/postgres-backup-restore.md.

set -eu

PGHOST="${PGHOST:-postgres}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-iguanatrader}"
PGDATABASE="${PGDATABASE:-iguanatrader}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

if [ -z "${PGPASSWORD:-}" ]; then
  echo "error: PGPASSWORD is required (set via the postgres overlay)" >&2
  exit 1
fi

if [ ! -d "$BACKUP_DIR" ]; then
  echo "error: BACKUP_DIR does not exist: $BACKUP_DIR" >&2
  exit 3
fi
if ! [ -w "$BACKUP_DIR" ]; then
  echo "error: BACKUP_DIR is not writable: $BACKUP_DIR" >&2
  exit 3
fi

STAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
OUTFILE="$BACKUP_DIR/iguanatrader-$STAMP.sql.gz"
TMPFILE="$OUTFILE.partial"

export PGPASSWORD

echo "[$STAMP] starting pg_dump: $PGHOST:$PGPORT/$PGDATABASE"
if ! pg_dump \
       --host="$PGHOST" \
       --port="$PGPORT" \
       --username="$PGUSER" \
       --dbname="$PGDATABASE" \
       --format=custom \
       --no-owner \
       --no-acl \
       --compress=9 \
       --file="$TMPFILE.dump"; then
  echo "[$STAMP] error: pg_dump failed" >&2
  rm -f "$TMPFILE.dump" "$TMPFILE"
  exit 1
fi

# pg_dump --format=custom already produces a compressed dump; the
# additional gzip is for transport/portability uniformity with the
# old SQLite-tarball snapshot convention. -9 = max compression.
if ! gzip -c -9 "$TMPFILE.dump" > "$TMPFILE"; then
  echo "[$STAMP] error: gzip failed" >&2
  rm -f "$TMPFILE.dump" "$TMPFILE"
  exit 2
fi
rm -f "$TMPFILE.dump"

# Atomic rename — readers never see a half-written file.
mv "$TMPFILE" "$OUTFILE"

# Rotate — delete files older than RETENTION_DAYS days. Use -mtime
# +N which means "older than N days" — adequate for daily backups.
find "$BACKUP_DIR" -maxdepth 1 -type f -name "iguanatrader-*.sql.gz" \
    -mtime "+$RETENTION_DAYS" -print -delete

SIZE_BYTES="$(stat -c '%s' "$OUTFILE" 2>/dev/null || stat -f '%z' "$OUTFILE")"
echo "[$STAMP] OK: wrote $OUTFILE ($SIZE_BYTES bytes); retention=$RETENTION_DAYS days"
