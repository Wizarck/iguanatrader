# `apps/api/` — iguanatrader FastAPI backend

Python package: `iguanatrader.*`. Owns the HTTP API surface, persistence layer, shared kernel, and CLI entry points.

This README covers **first-run bootstrap** — the operator workflow for getting a brand-new clone of iguanatrader to a state where Arturo (or another tenant user) can log in via `/login`. For broader project orientation see [`/AGENTS.md`](../../AGENTS.md) and [`docs/getting-started.md`](../../docs/getting-started.md).

## Layout

```
apps/api/
├── alembic.ini             # Alembic config (migrations under src/iguanatrader/migrations/)
├── Makefile.includes       # Make targets glued into the root Makefile
├── scripts/                # Operator-facing scripts (slice 4: none; T4 lands bootstrap-tenant)
├── src/iguanatrader/
│   ├── api/                # FastAPI surface — slice 4 onward
│   │   ├── __init__.py     # Argon2 parameter constants
│   │   ├── __main__.py     # `python -m iguanatrader.api` smoke uvicorn
│   │   ├── app.py          # create_app() factory + slowapi wiring
│   │   ├── auth.py         # Argon2id + JWT primitives + Role enum
│   │   ├── deps.py         # get_current_user + requires_role + get_db
│   │   ├── dtos/           # Pydantic v2 request/response models
│   │   ├── limiting.py     # slowapi Limiter + body-buffer middleware
│   │   └── routes/         # APIRouter modules (manually included by app.py;
│   │                       #   slice 5 dynamic-discovers via pkgutil)
│   ├── persistence/        # SQLAlchemy 2.x async + Alembic + listeners
│   ├── shared/             # Kernel: errors, time, contextvars, money, etc.
│   └── migrations/versions/ # Alembic migration files
└── tests/{unit,integration,property}/
```

## First-run bootstrap

These steps assume you have completed `make bootstrap` from the repo root (Python 3.11+, Node 20+, pnpm 9+, Poetry 1.8+, Docker, age, sops). If not, see [`docs/getting-started.md`](../../docs/getting-started.md).

### 1. Set the JWT secret env var

The `IGUANATRADER_JWT_SECRET` env var MUST be set BEFORE booting the API. Generate a 32-byte secret:

```sh
export IGUANATRADER_JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
```

For production / staging, store this in the SOPS-encrypted env (`.secrets/{dev,paper,live}.env.enc`) following the same pattern as other secrets. See [`docs/runbooks/auth-secret-rotation.md`](../../docs/runbooks/auth-secret-rotation.md) for the rotation procedure.

### 2. Apply migrations

```sh
poetry run alembic -c apps/api/alembic.ini upgrade head
```

This creates the SQLite database (default `./data/iguanatrader.db`) with the schema as of the latest migration. As of slice 4 the schema includes:

- `tenants` — cross-tenant catalogue.
- `users` — single-seat-per-tenant, role CHECK in `('tenant_user', 'god_admin')`.
- `authorized_senders` — whitelisted Telegram/WhatsApp IDs (slice P1 enforces).

### 3. Bootstrap the first tenant + user

⚠️ **Slice T4 will land an `iguanatrader admin bootstrap-tenant <slug>` CLI**. Until then, operators have two options:

**Option A — pytest fixture path** (recommended for local dev):

The slice 4 integration suite has a fixture `seeded_tenant_user` at [`tests/integration/conftest.py`](tests/integration/conftest.py) that seeds a `Tenant` + `User` with email `alice@example.com` and password `correct horse battery staple`. Run it once against your dev DB:

```sh
# (TODO: write a small script that exercises the fixture against IGUANA_DATABASE_URL)
poetry run python -m apps.api.scripts.seed_dev_tenant
# Until that script lands, fall back to Option B.
```

**Option B — manual SQL snippet**:

Compute an Argon2id hash for your chosen password:

```sh
poetry run python - <<'PY'
from iguanatrader.api.auth import hash_password
print(hash_password("your-chosen-password"))
PY
```

Insert the rows. Replace the UUIDs and email with your own:

```sql
-- Inside `sqlite3 ./data/iguanatrader.db`:
INSERT INTO tenants (id, name, feature_flags)
VALUES ('11111111-1111-1111-1111-111111111111', 'arturo-trading', '{}');

INSERT INTO users (id, tenant_id, email, password_hash, role)
VALUES (
  '22222222-2222-2222-2222-222222222222',
  '11111111-1111-1111-1111-111111111111',
  'arturo@example.com',
  '<paste-the-hash-from-the-python-snippet>',
  'tenant_user'
);
```

If you skip this step, `POST /api/v1/auth/login` returns `503 Service Unavailable` with a Problem Detail body pointing at this README.

### 4. Boot the API

For ad-hoc smoke testing:

```sh
poetry run python -m iguanatrader.api
# → Listening on http://127.0.0.1:8000 (uvicorn)
```

For dev integration with the SvelteKit frontend (`apps/web/`), the SvelteKit dev server's form action proxies to `http://127.0.0.1:8000` by default — start the API first, then run `pnpm --filter @iguanatrader/web dev` from the repo root.

For prod deployment, see the docker-compose stacks (`docker-compose.paper.yml`, `docker-compose.live.yml`).

### 5. Verify with `/me`

```sh
# Log in.
curl -s -c /tmp/iguana.cookie \
  -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"arturo@example.com","password":"your-chosen-password"}'
# → {"redirect_to": "/"}

# Round-trip.
curl -s -b /tmp/iguana.cookie http://127.0.0.1:8000/api/v1/auth/me | python -m json.tool
# → {
#     "user_id": "...",
#     "tenant_id": "...",
#     "email": "arturo@example.com",
#     "role": "tenant_user",
#     "created_at": "..."
#   }
```

If you get a 503 here, revisit step 3 (no tenant rows yet). If 401, the password didn't verify — recheck the hash you inserted in step 3.

## Tests

```sh
# Unit (Argon2id + JWT primitives + Role enum + email hash).
poetry run pytest apps/api/tests/unit/test_auth_primitives.py -v

# Integration (full HTTP flow with httpx ASGITransport + on-disk SQLite).
poetry run pytest apps/api/tests/integration/test_auth_flow.py -v

# Property (Hypothesis JWT round-trip).
poetry run pytest apps/api/tests/property/test_jwt_round_trip.py -v

# All slice 4 tests with coverage.
poetry run pytest apps/api/tests/ \
  --cov=apps/api/src/iguanatrader/api \
  --cov-report=term-missing
```

## Operational env vars

| Var | Default | Purpose |
|---|---|---|
| `IGUANATRADER_JWT_SECRET` | (required) | HS256 signing key, ≥32 bytes |
| `IGUANATRADER_ARGON2_TIME_COST` | `3` | Argon2id iterations |
| `IGUANATRADER_ARGON2_MEMORY_KIB` | `65536` | Argon2id memory cost (KiB) |
| `IGUANATRADER_ARGON2_PARALLELISM` | `4` | Argon2id parallel lanes |
| `IGUANATRADER_ARGON2_HASH_LEN` | `32` | Argon2id digest length (bytes) |
| `IGUANATRADER_ARGON2_SALT_LEN` | `16` | Argon2id salt length (bytes) |
| `IGUANATRADER_DEV_INSECURE_COOKIE` | unset | `=1` to drop the `Secure` flag (local HTTP only — see gotchas #25) |
| `IGUANA_DATABASE_URL` | `sqlite+aiosqlite:///./data/iguanatrader.db` | SQLAlchemy async DB URL |
| `IGUANATRADER_API_HOST` | `127.0.0.1` | uvicorn bind host (smoke entry only) |
| `IGUANATRADER_API_PORT` | `8000` | uvicorn bind port (smoke entry only) |

## See also

- [`docs/architecture-decisions.md`](../../docs/architecture-decisions.md) — system-wide ADRs, including auth (D-Auth-1, D-Auth-2).
- [`docs/gotchas.md`](../../docs/gotchas.md) #24–#28 — slice 4 auth-specific footguns.
- [`docs/runbooks/auth-secret-rotation.md`](../../docs/runbooks/auth-secret-rotation.md) — JWT secret rotation procedure.
- [`openspec/changes/auth-jwt-cookie/`](../../openspec/changes/auth-jwt-cookie/) — slice 4 design + spec contract.
