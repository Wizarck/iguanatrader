# Runbook — cut over SQLite VPS deployment to Postgres

**Audience**: operator (Arturo / single-host MVP).

**When to run**:

- Before flipping iguanatrader from paper to live (Postgres is required for live per the live-readiness plan).
- Any time SQLite contention shows up under load (WAL "database is locked" errors in the API logs).

**Time budget**: 20–30 minutes assuming the SQLite volume is small (<100MB).

**Blast radius**:

- Iguanatrader is offline for the duration of the cut-over (DB is the only writer; no concurrent paths).
- Cloudflare tunnel target does NOT change — same compose ports.
- Existing data is preserved via dump/load. **Take a snapshot of the volume before starting** (step 1) — if the load fails, restore is `docker volume cp` of that snapshot.

---

## 1. Snapshot the SQLite volume

```sh
ssh eligia-vps
cd /opt/iguanatrader
# Stop the api/web stack BUT keep the volume mounted somewhere readable
docker compose -f compose/mvp.yml -f compose/mvp.override.yml down

# Tar the volume to a timestamped snapshot under /root/iguanatrader-backups/
mkdir -p /root/iguanatrader-backups
docker run --rm \
  -v iguanatrader_iguanatrader_data:/data:ro \
  -v /root/iguanatrader-backups:/backups \
  alpine tar -czf /backups/sqlite-pre-pg-cutover-$(date -u +%Y-%m-%dT%H-%M-%SZ).tar.gz -C /data .
ls -lh /root/iguanatrader-backups/
```

If the snapshot is >100MB, copy it off the VPS to a separate machine before proceeding.

## 2. Pull the slice + bring up Postgres

```sh
cd /opt/iguanatrader
git fetch origin
git checkout main
git pull origin main
# Verify the slice landed:
ls compose/postgres.yml || { echo "slice not deployed"; exit 1; }

# Pick a real password (don't leave the placeholder)
export POSTGRES_PASSWORD=$(python3 -c "import secrets; print(secrets.token_hex(24))")
echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" >> /opt/iguanatrader/.env.postgres
# (and persist it to your password manager + the SOPS bundle in step 6)

docker compose -f compose/mvp.yml \
               -f compose/mvp.override.yml \
               -f compose/postgres.yml \
               --env-file /opt/iguanatrader/.env.postgres \
               up -d postgres

# Wait for healthcheck
until docker compose -f compose/mvp.yml \
                    -f compose/mvp.override.yml \
                    -f compose/postgres.yml \
                    --env-file /opt/iguanatrader/.env.postgres \
                    ps postgres --format json | grep -q '"Health":"healthy"'; do
  sleep 2
done
```

## 3. Apply Alembic head against the empty Postgres

```sh
docker compose -f compose/mvp.yml \
               -f compose/mvp.override.yml \
               -f compose/postgres.yml \
               --env-file /opt/iguanatrader/.env.postgres \
               run --rm api \
               python -m alembic -c apps/api/alembic.ini upgrade head
# Expected last line: "INFO  [alembic.runtime.migration] Running upgrade ... -> 0017_trade_state_simplify"
```

## 4. Copy data from the SQLite snapshot into Postgres

If your SQLite DB has **no real data** (tenants are seeded fresh, no fill history yet): skip to step 5 and re-bootstrap tenants from the CLI.

Otherwise use `pgloader`:

```sh
# On the VPS — pgloader containerized so you don't pollute the host
docker run --rm \
  -v iguanatrader_iguanatrader_data:/sqlite:ro \
  --network iguanatrader_default \
  dimitri/pgloader:latest \
  pgloader \
    --type sqlite \
    --with "data only" \
    --with "drop indexes" \
    /sqlite/iguanatrader.db \
    postgresql://iguanatrader:${POSTGRES_PASSWORD}@postgres:5432/iguanatrader
```

`--with "data only"` is critical — the schema is already at head from Alembic. `--with "drop indexes"` then rebuilds indexes after the bulk load (faster).

Verify row counts match:

```sh
docker compose -f compose/mvp.yml ... run --rm api python -c "
import asyncio, os
from sqlalchemy import text
from iguanatrader.persistence import engine_factory
async def main():
    pg = engine_factory(os.environ['IGUANA_DATABASE_URL'])
    async with pg.connect() as c:
        for t in ('tenants','users','trade_proposals','trades','orders','fills'):
            r = await c.execute(text(f'SELECT count(*) FROM {t}'))
            print(t, r.scalar_one())
asyncio.run(main())
"
```

Cross-check those counts against the SQLite snapshot (run the same query with `sqlite3 sqlite-pre-pg-cutover-*.tar.gz`-extracted DB).

## 5. Bring the stack up against Postgres

```sh
docker compose -f compose/mvp.yml \
               -f compose/mvp.override.yml \
               -f compose/postgres.yml \
               --env-file /opt/iguanatrader/.env.postgres \
               up -d
docker compose ps  # all three should be healthy
curl -s http://localhost:8800/healthz   # api liveness
curl -s http://localhost:8801/          # web 200 OK
```

Then visit https://iguanatrader.palafitofood.com/ and verify login works.

## 6. Persist `POSTGRES_PASSWORD` in SOPS

```sh
# On your laptop, not the VPS
cd /c/Projects/iguanatrader
sops .secrets/live.env.enc
# Add line: POSTGRES_PASSWORD=<value from step 2>
git add .secrets/live.env.enc
git commit -m "chore(secrets): record POSTGRES_PASSWORD for live cut-over"
```

## 7. Retain the SQLite snapshot for 30 days

Don't delete `/root/iguanatrader-backups/sqlite-pre-pg-cutover-*.tar.gz` until you've confirmed 30 days of normal operation on Postgres. If anything goes sideways in week 1, the rollback path is: stop the stack, restore the SQLite volume from tarball, bring up without the `-f compose/postgres.yml` overlay.

---

## Rollback

```sh
docker compose -f compose/mvp.yml \
               -f compose/mvp.override.yml \
               -f compose/postgres.yml \
               --env-file /opt/iguanatrader/.env.postgres \
               down
docker run --rm \
  -v iguanatrader_iguanatrader_data:/data \
  -v /root/iguanatrader-backups:/backups:ro \
  alpine sh -c 'cd /data && tar -xzf /backups/sqlite-pre-pg-cutover-*.tar.gz'
docker compose -f compose/mvp.yml \
               -f compose/mvp.override.yml up -d
```

This brings you back to the pre-cut-over state. The Postgres volume `iguanatrader_postgres_data` is preserved for forensics; you can `docker volume rm` it once you've confirmed the rollback is stable.
