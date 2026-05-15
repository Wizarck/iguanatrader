# Runbook — Postgres backup + restore

**Audience**: operator (Arturo / single-host MVP) running the VPS Postgres stack.

**When to run**:

- Backup: automatic — the `pg-backup` service runs once every 24h at 02:00 UTC and persists `iguanatrader-YYYY-MM-DDTHH-MM-SSZ.sql.gz` under `/root/iguanatrader-backups/`. The operator's only routine action is to verify the cron is alive (see §1) and copy files off-VPS periodically (§4 carry-forward).
- Restore: when recovering from data corruption, accidental DELETE, or a failed migration. Also useful for spin-up of a staging clone.

**Time budget**:

- Backup: ~30s for the current ~780KB DB; grows roughly linearly with row count. Budget 5–10 min when the DB hits ~1GB.
- Restore: depends on dump size. The first restore on a fresh empty DB is fastest. Restore-over-an-existing-DB uses `pg_restore --clean --if-exists` which drops + recreates each object before reload.

**Blast radius**:

- Backup is read-only against the live DB. Production write traffic is unaffected.
- Restore is destructive: it `DROP`s and recreates every object in `$PGDATABASE`. Use `DROP_DB_FIRST=yes` only when you want to nuke the whole DB; default leaves the DB present and lets `pg_restore` do object-by-object replacement.

---

## 1. Verify the backup cron is alive

```sh
scripts/iguana-compose.sh paper logs --tail=20 pg-backup
```

Look for either:

- `pg-backup: sleeping <N>s until next 02:00 UTC` — alive, waiting.
- `[YYYY-MM-DDTHH-MM-SSZ] OK: wrote /backups/iguanatrader-... (N bytes)` — last backup succeeded.

If you see `dump failed (will retry next cycle)`, inspect logs above for the underlying `pg_dump` stderr.

List the current backup set:

```sh
ls -lh /root/iguanatrader-backups/
```

Default retention keeps 30 days; older files are auto-deleted.

## 2. How the cron schedule is implemented

The `pg-backup` container runs a plain `sh` loop (no `supercronic`/`cron` daemon dependency):

```sh
while true; do
  sleep until next 02:00 UTC
  /scripts/postgres-backup.sh
done
```

Rationale: `pg-backup` is the only timed service in this overlay; introducing `supercronic` would add an image-layer dependency for one cron entry. The plain sleep loop survives container restarts (the first iteration on boot calculates time-to-next-02:00 and waits) and is trivially auditable in `docker logs`.

If `pg-backup` is restarted mid-sleep, the next firing aligns to the original UTC tick — there's no drift. If the container is down across a 02:00 UTC window, that day's backup is missed; the next day's run is unaffected.

## 3. Manual backup (out-of-cycle)

To take an immediate backup without waiting for 02:00 UTC:

```sh
scripts/iguana-compose.sh paper exec pg-backup /scripts/postgres-backup.sh
```

Output goes to the same `/backups` directory + counts toward the 30-day rotation.

## 4. Restore from a backup

**This is destructive — confirm the target DB is the right one before running.**

```sh
ssh eligia-vps
cd /opt/iguanatrader
ls -lh /root/iguanatrader-backups/    # pick the file to restore

# Stop the api so no concurrent writes during restore:
scripts/iguana-compose.sh paper stop api web

# Restore over the existing DB (drops + recreates objects):
scripts/iguana-compose.sh paper run --rm pg-backup \
    /scripts/postgres-restore.sh /backups/iguanatrader-2026-05-15T02-00-00Z.sql.gz

# Full DROP DATABASE + CREATE DATABASE (nukes everything first):
scripts/iguana-compose.sh paper run --rm -e DROP_DB_FIRST=yes pg-backup \
    /scripts/postgres-restore.sh /backups/iguanatrader-2026-05-15T02-00-00Z.sql.gz

# Bring everything back up:
scripts/iguana-compose.sh paper start api web
```

Verify row counts post-restore:

```sh
scripts/iguana-compose.sh paper exec postgres \
    psql -U iguanatrader -d iguanatrader \
    -c "SELECT 'tenants' AS table_name, count(*) FROM tenants
        UNION ALL SELECT 'trades', count(*) FROM trades
        UNION ALL SELECT 'fills', count(*) FROM fills
        UNION ALL SELECT 'equity_snapshots', count(*) FROM equity_snapshots;"
```

## 5. Off-VPS replication (carry-forward)

Currently backups live ONLY on the same VPS as the live DB. A disk failure or VPS provider outage takes both. The next slice (`postgres-backup-offsite`, planned but not in scope here) will push the rotated files to B2 / S3 / cloud storage via `rclone` or `b2 sync` on the same sleep cadence.

Interim manual procedure: rsync the daily dumps to an off-VPS host:

```sh
# On the operator laptop (or another box):
rsync -avz --delete \
    eligia-vps:/root/iguanatrader-backups/ \
    ~/iguanatrader-backups-mirror/
```

Add to your laptop's crontab if you want it automated.

---

## Rollback

If the `pg-backup` service itself misbehaves (e.g. fills up the disk), stop it without affecting the rest of the stack:

```sh
scripts/iguana-compose.sh paper stop pg-backup
# Manually delete oldest files if disk space is tight:
ls -t /root/iguanatrader-backups/ | tail -n +31 | xargs -I{} rm /root/iguanatrader-backups/{}
```

The api + web + postgres keep running; only the cron pauses. Resume with `scripts/iguana-compose.sh paper start pg-backup`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `pg_dump: error: connection ... refused` | postgres not healthy yet | `scripts/iguana-compose.sh paper ps`; wait for postgres `(healthy)`; restart `pg-backup`. |
| `error: BACKUP_DIR is not writable` | `/root/iguanatrader-backups` host bind missing or wrong perms | `mkdir -p /root/iguanatrader-backups && chown root:root /root/iguanatrader-backups`. |
| Restore aborts mid-file | `pg_restore --exit-on-error` hit a constraint conflict | Use `DROP_DB_FIRST=yes` to start from an empty DB instead. |
| Backups stop after a date | container OOMed or crash-looped | `docker compose logs pg-backup --tail=200`; if a real crash, inspect the underlying error + reopen. |
