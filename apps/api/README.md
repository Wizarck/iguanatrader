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
│   ├── api/                # FastAPI surface
│   │   ├── __init__.py     # Argon2 parameter constants
│   │   ├── __main__.py     # `python -m iguanatrader.api` smoke uvicorn
│   │   ├── app.py          # create_app() factory + dynamic discovery (slice 5)
│   │   ├── auth.py         # Argon2id + JWT primitives + Role enum
│   │   ├── deps.py         # get_current_user + requires_role + get_db
│   │   ├── dtos/           # Pydantic v2 DTOs (auth, common.Problem)
│   │   ├── errors.py       # Global IguanaError + Exception handler chain
│   │   ├── limiting.py     # slowapi Limiter + body-buffer middleware
│   │   ├── routes/         # APIRouter modules — auto-discovered (slice 5)
│   │   └── sse/            # SSE APIRouter modules — auto-discovered
│   ├── cli/                # Typer auto-discovery scaffold (slice 5; empty)
│   │   ├── __main__.py     # `python -m iguanatrader.cli` shim
│   │   └── main.py         # cli_app + _register_subcommands
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

## CLI — operator entrypoint

Slice 5 (`api-foundation-rfc7807`) plants a Typer auto-discovery scaffold; slice 5 itself ships ZERO subcommands. List what's available:

```sh
poetry run python -m iguanatrader.cli --help
# or once `poetry install` is done:
poetry run iguanatrader --help
```

**Adding a new subcommand**: drop a file `apps/api/src/iguanatrader/cli/<name>.py` exporting a top-level `app: typer.Typer` instance. The discovery loop in `cli/main.py::_register_subcommands` picks it up automatically — no edit to `cli/main.py` is required. Module name `_` is converted to CLI surface `-` (e.g. `bootstrap_tenant.py` → `iguanatrader bootstrap-tenant`). See gotcha #29 — heavy deps MUST be lazy-imported inside command bodies, never at module scope.

## Routes — adding a new family

The same anti-collision pattern applies to HTTP routes (slice 5):

```python
# apps/api/src/iguanatrader/api/routes/research.py
from fastapi import APIRouter

router = APIRouter(prefix="/research", tags=["research"])


@router.get("/{symbol}")
async def get_research(symbol: str) -> dict[str, str]:
    return {"symbol": symbol}
```

The discovery loop in `iguanatrader.api.routes.register_routers` mounts every module under `routes/` exporting a top-level `router: APIRouter` at the `/api/v1` prefix automatically. SSE endpoints follow the same shape under `iguanatrader.api.sse` and mount under `/api/v1/stream`. **Don't edit `app.py`** — adding a route family is a single-file change.

## Typed frontend client — `packages/shared-types/`

Slice 5 wires the OpenAPI → TypeScript pipeline. CI regenerates `packages/shared-types/src/index.ts` from `/openapi.json` on every push to a `slice/**` / `feat/**` branch (bot commit, mirroring `regenerate-lock.yml`). For local dev with a running API:

```sh
# Boot the API first (terminal 1):
poetry run python -m iguanatrader.api

# Regenerate the types (terminal 2):
pnpm typegen:from-running-api
```

This curls `http://127.0.0.1:8000/openapi.json` and runs `openapi-typescript` against it — same pipeline CI runs, just sourced from a manually-running uvicorn instead of one CI booted itself. Useful when iterating on a new DTO without pushing every commit.

## Research bounded-context (R1)

Slice R1 (`research-bitemporal-schema`) lands the Research & Intelligence fabric: 7 tables under `apps/api/src/iguanatrader/contexts/research/`, the `SourcePort` Protocol that Wave 3 source adapters (R2 EDGAR/FRED, R3 news/catalysts, R4 OpenBB sidecar) implement, the `ResearchRepository` writer, and DTO/route stubs that R5 (`research-brief-synthesis`) replaces in-place.

### `SourcePort` contract (Wave 3 adapter authors — read this first)

Every source adapter exposes a `fetch(symbol, since)` method returning an iterable of `ResearchFactDraft`:

```python
from collections.abc import Iterable
from datetime import datetime
from iguanatrader.contexts.research import ResearchFactDraft, SourcePort


class SECEdgarSource(SourcePort):
    def fetch(self, symbol: str, since: datetime | None) -> Iterable[ResearchFactDraft]:
        for raw_filing_bytes in _walk_edgar(symbol, since):
            draft = ResearchFactDraft(
                source_id="sec_edgar",
                symbol_universe_id=...,
                fact_kind="fundamental.eps",
                effective_from=...,
                recorded_from=...,
                source_url=...,            # MANDATORY — exact provenance URL
                retrieval_method="api",   # MANDATORY — one of api/scrape/manual/llm
                retrieved_at=...,         # MANDATORY — UTC ISO 8601
                value_numeric=...,        # at least one value_* field MUST be set
            ).with_payload(raw_filing_bytes)
            yield draft
```

The `with_payload(raw_bytes)` factory is the canonical way to attach the raw payload — it computes the storage tier deterministically (size-based dispatch, see below) so adapters never set `raw_payload_*` columns manually.

### Hybrid payload storage — `with_payload` dispatch

Per ADR-014 §7b.3 + design D3 of slice R1:

- Payloads strictly less than 16384 bytes are stored inline in `raw_payload_inline` (JSONB on Postgres v1.5; cross-dialect JSON on SQLite MVP). `with_payload(b'<small>')` populates the column; the JSON parse falls back to a `{"_raw": "..."}` envelope on non-JSON bytes.
- Payloads of 16384 bytes or more are written to filesystem under `data/research_cache/<source_id>/<yyyy-mm>/<sha256>.json` (relative to the working directory; `ResearchRepository(payload_root=...)` lets tests override the root). The directory is created on first write — DO NOT pre-create in deploy scripts.

The CHECK constraint `(raw_payload_inline IS NULL) <> (raw_payload_path IS NULL)` enforces exactly-one-set; the consistency CHECKs add `sha256` mandatory-when-filesystem and `size_bytes >= 16384 → path NOT NULL`.

### Provenance enforcement (DO NOT bypass the repository)

Adapters MUST insert via `ResearchRepository.insert_fact(draft)`. Direct SQL inserts bypass:

- The driver `IntegrityError` → `MissingProvenanceError` lifting that produces the canonical RFC 7807 422 with `type=urn:iguanatrader:error:missing-provenance`.
- The hybrid-storage filesystem write (the path column would be set but the file would never land).
- The slice-3 `tenant_id_var` stamping (defence-in-depth against cross-tenant leak).

The L1 ORM listener + L2 BEFORE UPDATE/DELETE triggers enforce append-only on `research_facts`, `research_briefs`, `corporate_events`, `analyst_ratings`. The single permitted UPDATE is `ResearchRepository.supersede_fact(old_id, at)` which sets `recorded_to: NULL → :ts` via raw SQL through the trigger's narrow exception. Don't roll your own — the trigger pattern-matches the exact UPDATE form.

### Files

- `apps/api/src/iguanatrader/contexts/research/{models,ports,repository,events,errors}.py` — bounded-context surface.
- `apps/api/src/iguanatrader/api/dtos/research.py` — Pydantic v2 response models (consumed unchanged by R5).
- `apps/api/src/iguanatrader/api/routes/research.py` — four endpoints, each currently raising 501 until R5 ships.
- `apps/api/src/iguanatrader/migrations/versions/0003_research_tables.py` — schema migration.

## Risk context (slice K1) — operator surface

Slice K1 (`risk-engine-protections`) plants the bounded context under
`src/iguanatrader/contexts/risk/`. Public API:

- `RiskService.evaluate_proposal(proposal)` — kill-switch gate first, then pure-functional engine call, then persist + emit.
- `RiskService.activate_kill_switch(...)` / `deactivate_kill_switch(...)` — lifecycle.
- `RiskService.record_override(...)` — audit-quality persistence (≥20 char reason, FK to `users.id`, JSONB confirmation chain).
- `iguanatrader.contexts.risk.engine.evaluate(...)` — pure function exported for property tests / future direct callers.

CLI ops (auto-discovered by slice-5 loader):

```sh
# Kill-switch
poetry run iguanatrader ops halt --reason "manual freeze: market dislocation observed"
poetry run iguanatrader ops resume --reason "market normalised; resuming live trading"

# Override audit (single-actor CLI flow)
poetry run iguanatrader ops override \
    --proposal-id <uuid> --risk-evaluation-id <uuid> \
    --reason "earnings beat justifies one-off bypass for AAPL"
```

The `--reason` argument is mandatory and ≥20 chars; Typer rejects shorter values BEFORE the service is called. Set `IGUANATRADER_OPS_TENANT_ID` and `IGUANATRADER_OPS_ACTOR_USER_ID` env vars on the CLI host so single-tenant operators don't have to repeat them on every invocation.

Cap defaults (env-overridable per-deployment):

| Cap | Default | Env var |
|---|---|---|
| Per-trade % of capital | `0.02` (2%) | `IGUANATRADER_RISK_PER_TRADE_PCT` |
| Daily loss % | `0.05` (5%) | `IGUANATRADER_RISK_DAILY_LOSS_PCT` |
| Weekly loss % | `0.15` (15%) | `IGUANATRADER_RISK_WEEKLY_LOSS_PCT` |
| Max open positions | `10` | `IGUANATRADER_RISK_MAX_OPEN_POSITIONS` |
| Max drawdown % | `0.15` (15%) | `IGUANATRADER_RISK_MAX_DRAWDOWN_PCT` |

Per-tenant cap overrides (via `risk_caps` config row + dashboard UI) are out of scope for K1; they land in a future slice.

### CI gate — Hypothesis property test

`apps/api/tests/property/test_risk_caps_invariant.py` is the **CI-blocking** gate (NFR-R6). It generates 200 arbitrary `(proposal, state, caps)` triples and asserts that every `outcome="allow"` decision satisfies every cap. Skipping it (e.g. `@pytest.mark.skip`) is a hard review fail — the marker `@pytest.mark.ci_blocking` flags the test as load-bearing.

Engine purity is verified by `tests/unit/contexts/risk/test_engine_purity.py` — an AST inspector that fails the build if `engine.py` (or any protection module) imports `datetime`, `time`, `sqlalchemy`, `requests`, `httpx`, or calls `.now()` / `.utcnow()` / `.commit()` / `.execute()` / `.add()` / `.delete()`. See gotcha #44.

## Bounded contexts — public surface

Each subpackage under `src/iguanatrader/contexts/<name>/` is one bounded context with a stable public API. Cross-context coupling MUST go through `iguanatrader.shared.messagebus.MessageBus`; direct deep imports across context boundaries are forbidden.

### `contexts/approval/` (slice P1 — `approval-channels-multichannel`)

Multichannel approval surface for trade proposals — Telegram + Hermes/WhatsApp + dashboard transports with a shared 17-command dispatcher, append-only audit, idempotent retries, authorized-sender enforcement, heartbeat-based reconnect resilience, and cross-context event emission.

**Events emitted** (slice 2 `MessageBus`):

- `approval.proposal.approved` — payload `{proposal_id, decision_id, decided_at, decided_by_user_id, decided_via_channel}`. Trading T2/T4 subscribes to trigger broker order placement.
- `approval.proposal.rejected` — payload `{proposal_id, decision_id, decided_at, reason?, decided_via_channel}`.
- `approval.proposal.timed_out` — payload `{proposal_id, request_id, expired_at}` (FR13 auto-discard).

**Ports consumed**:

- `iguanatrader.shared.heartbeat.HeartbeatMixin` — every channel subclasses (slice 2 D6).
- `iguanatrader.shared.backoff.backoff_seconds` — canonical `[3, 6, 12, 24, 48]` reconnect ladder.
- `iguanatrader.persistence.append_only_listener` — both new tables register `__tablename_is_append_only__ = True`.
- `ChannelTransportPort` (Protocol, slice-local) — wire-format facade. Slice P1 ships fakes only (D8).

**Errors raised** (slice-local under `contexts/approval/errors.py`; rendered as RFC 7807 by the slice 5 global handler):

- `ApprovalNotFoundError` (404, `urn:iguanatrader:error:approval-not-found`)
- `ApprovalAlreadyDecidedError` (409, `urn:iguanatrader:error:approval-already-decided`) — first-decision-wins (D4)
- `ApprovalExpiredError` (410, `urn:iguanatrader:error:approval-expired`)
- `UnauthorizedSenderError` (403, `urn:iguanatrader:error:unauthorized-sender`)

**The 17-command registry** lives in `contexts/approval/channels/commands/` — one module per command exporting `SPEC: CommandSpec`. The registry is built at import time via `pkgutil.iter_modules`. Adding a command is a single-file edit:

```
/approve  /reject  /halt    /resume   /status
/positions /equity /strategies /risk   /override
/cost     /budget  /help    /whoami   /lock
/unlock   /logout
```

`assert_canonical()` in `commands/__init__.py` enforces "exactly 17 entries; canonical names". The unit test `tests/unit/contexts/approval/test_command_registry.py` runs it on every test run.

**HTTP surface** (auto-discovered by slice 5 routers):

- `GET /api/v1/approvals` — list pending requests for the caller's tenant
- `POST /api/v1/approvals/{id}/approve` — record granted via dashboard channel
- `POST /api/v1/approvals/{id}/reject` — record rejected (optional `reason` body)
- `GET /api/v1/stream/approvals` — SSE feed of `ApprovalProposal*` events

**CLI surface** (auto-discovered):

- `iguanatrader approval list` — list pending requests
- `iguanatrader approval audit <request_id>` — full audit chain
- `iguanatrader approval sweep-expired` — manual timeout sweeper (slice O2 will cron-schedule)

## See also

- [`docs/architecture-decisions.md`](../../docs/architecture-decisions.md) — system-wide ADRs, including auth (D-Auth-1, D-Auth-2) + ADR-014 bitemporal research facts.
- [`docs/gotchas.md`](../../docs/gotchas.md) #24–#52 — slices 4-5 + R1 + T1 + K1 + P1 footguns.
- [`docs/runbooks/risk-kill-switch.md`](../../docs/runbooks/risk-kill-switch.md) — operator playbook for kill-switch activation + recovery.
- [`docs/runbooks/auth-secret-rotation.md`](../../docs/runbooks/auth-secret-rotation.md) — JWT secret rotation procedure.
- [`docs/runbooks/api-foundation-typegen.md`](../../docs/runbooks/api-foundation-typegen.md) — recovery playbook when the openapi-types CI workflow fails.
- [`docs/runbooks/approval-channels-resilience.md`](../../docs/runbooks/approval-channels-resilience.md) — slice P1 channel-outage diagnosis + token rotation.
- [`openspec/changes/auth-jwt-cookie/`](../../openspec/changes/auth-jwt-cookie/) — slice 4 design + spec contract.
- [`openspec/changes/api-foundation-rfc7807/`](../../openspec/changes/api-foundation-rfc7807/) — slice 5 design + spec contract.
- [`openspec/changes/research-bitemporal-schema/`](../../openspec/changes/research-bitemporal-schema/) — slice R1 design + spec contract.
- [`openspec/changes/approval-channels-multichannel/`](../../openspec/changes/approval-channels-multichannel/) — slice P1 design + spec contract.
