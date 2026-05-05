# Runbook — `openapi-types.yml` workflow recovery

**Audience**: operator (Arturo or future co-developer) when the
`OpenAPI types regen + Lighthouse` GitHub Actions workflow fails on a
slice branch and is blocking PR merge.

**Owner**: slice 5 (`api-foundation-rfc7807`) plants this workflow;
this runbook lives alongside it.

## When this runbook fires

The `openapi-types.yml` workflow has two jobs:

1. **regen** — boots `python -m uvicorn iguanatrader.api.app:create_app --factory`, fetches `/openapi.json`, regenerates `packages/shared-types/src/index.ts`, bot-commits the diff on slice branches.
2. **lighthouse** — boots `pnpm --filter @iguanatrader/web dev`, runs `lhci autorun` against `http://localhost:5173/login`, asserts a11y ≥ 90.

Failure modes that bring you here:

- **regen job fails to boot the FastAPI app** — usually a missing env var (`IGUANATRADER_JWT_SECRET`) on the runner, or a slice introduced a route module that raises on import (the dynamic-discovery loop re-raises by design — see gotcha #28's slice O1 follow-up).
- **regen job's openapi-typescript pass fails** — the OpenAPI schema generator emitted a shape the TS-typegen tool can't render. Usually a missing Pydantic discriminator or a forward-ref that didn't resolve.
- **regen job committed a diff but the next CI run still flags drift** — the bot pushed but the PR's HEAD didn't refresh; merge the bot commit into your branch (`git pull --rebase`).
- **lighthouse a11y < 90** — the slice introduced a regression on `/login` (most often: an `<input>` without an associated `<label>`, or a heading-order skip).

## Decision tree

```
                    Is the regen job failing?
                            │
                ┌───────────┴───────────┐
                │                       │
              Yes                       No
                │                       │
                ▼                       ▼
     Read the failing step's      Is the lighthouse job
     log from the workflow run    failing?
                │                       │
                ▼                       ▼
     "FastAPI failed to boot"     a11y assertion fail
              ↓                          ↓
        See §1 below              See §3 below

     openapi-typescript error
              ↓
        See §2 below
```

## §1 — FastAPI failed to boot in CI

**Symptom**: regen job's "Boot FastAPI app in background" step exits with `FastAPI failed to boot`.

**First check**: the workflow's structlog output. If you see `api.router.import_failed` with a module name, a route module raises on import.

**Workflow**: pull the slice branch locally, run `python -m iguanatrader.api` in your shell. The same exception fires; fix at the module's source. Common causes:

- Forgot to add the new route's import-time deps to `pyproject.toml` (e.g., `fastapi-utils`).
- Circular import — slice's new module imports something that hasn't been added yet.
- ORM model imported at module scope without the SQLAlchemy registry being initialised.

**Manual local regen** (if the workflow is flaky and you want to unblock the merge while you investigate the underlying cause):

```sh
poetry install --no-interaction --with dev
poetry run python -m iguanatrader.api &
UVICORN_PID=$!
sleep 5
curl -fsS http://127.0.0.1:8000/openapi.json -o /tmp/openapi.json
pnpm --filter @iguanatrader/shared-types exec openapi-typescript \
  /tmp/openapi.json -o packages/shared-types/src/index.ts
kill $UVICORN_PID
git diff packages/shared-types/src/index.ts
git add packages/shared-types/src/index.ts
git commit -m "chore(types): regenerate shared-types from /openapi.json (manual)"
git push
```

The next CI run picks up your manual commit and the diff check passes.

## §2 — `openapi-typescript` failed on the schema

**Symptom**: regen job's "Regenerate packages/shared-types/src/index.ts" step exits with a JS error referencing a `$ref` it can't resolve, or a `oneOf` with a missing discriminator.

**Workflow**: hand-render the OpenAPI schema and inspect:

```sh
poetry run python -m iguanatrader.api &
sleep 5
curl -s http://127.0.0.1:8000/openapi.json | python -m json.tool > /tmp/openapi.json
# Look for the failing schema component referenced in the CI error.
```

Common causes + fixes:

- **Forward-ref Pydantic types** — Pydantic v2 sometimes emits `$ref` to a model that isn't yet registered. Solution: explicitly call `Model.model_rebuild()` at module import time.
- **`Union[X, Y]` without discriminator** — `openapi-typescript` v7 supports discriminated unions but balks on bare `oneOf`. Add `Field(discriminator="type")` to the parent model.
- **Pydantic `RootModel` rendering as `additionalProperties: True` by accident** — rare; `RootModel` should round-trip cleanly. If it doesn't, replace with an explicit nested model.

After fixing, push — the workflow regenerates from scratch.

## §3 — Lighthouse a11y assertion failed

**Symptom**: lighthouse job exits with `assertion error: categories:accessibility` and a Lighthouse audit ID (e.g., `label`, `heading-order`, `color-contrast`).

**Workflow**: download the workflow artefact (`.lighthouseci/`), open the HTML report locally, find the failing audit. Most often it's:

- A new `<input>` introduced without an associated `<label>` (Lighthouse audit `label`).
- A heading hierarchy that skips levels (h2 → h4) (`heading-order`).
- Color contrast below 4.5:1 (`color-contrast`) — usually triggered by a hardcoded hex in a Svelte component instead of using the OKLCH design tokens.

**Fix**: address the audit, push, the workflow re-runs.

**Don't lower the threshold** to unblock the merge. The hard gate (a11y ≥ 90) is by design (per slice 5 D7). If a particular audit is genuinely a false positive (rare), open an issue + add the audit ID to the lighthouserc.cjs `assertions` block as `"warn"` rather than `"error"` — but only after explicit Sally / UX sign-off.

## Out-of-scope

- **`regen-lock.yml` failures** — different workflow (poetry.lock regeneration); see [its own runbook](TODO-add-when-it-exists.md) — until then, see gotcha #18 for the "poetry isn't on the local PATH" workaround.
- **Frontend type errors after a regen bot commit** — that's a slice consumer issue (slice W1+ owns the SvelteKit imports). Report the failure to the slice owner; do not edit `packages/shared-types/src/index.ts` by hand.
