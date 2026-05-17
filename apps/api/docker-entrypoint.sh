#!/bin/sh
# iguanatrader API entrypoint — runs `alembic upgrade head` before
# exec'ing the container's CMD. Idempotent: `upgrade head` is a no-op
# when the DB is already at head, so this is safe to run on every
# boot (including one-shot CLI invocations like `iguanatrader admin
# bootstrap-tenant`). Set IGUANA_SKIP_MIGRATIONS=1 to opt out (e.g.
# when running `alembic downgrade` manually).
set -e

if [ "${IGUANA_SKIP_MIGRATIONS:-0}" != "1" ]; then
    echo "[entrypoint] alembic upgrade head" >&2
    python -m alembic -c /app/apps/api/alembic.ini upgrade head
fi

exec "$@"
