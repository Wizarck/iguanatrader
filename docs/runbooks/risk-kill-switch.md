# Runbook — risk kill-switch lifecycle

**Owner**: slice K1 (`risk-engine-protections`).
**NFR-R5**: kill-switch activation → first refused trade in <2 seconds.
**NFR-R6**: caps invariant property-tested as a CI-blocking gate.

This runbook is the operator playbook for activating, confirming, recovering, and de-activating the kill-switch. It assumes the API is up, the database is reachable, and at least one tenant has been bootstrapped (per [`apps/api/README.md`](../../apps/api/README.md) §3).

## When to halt

Activate the kill-switch immediately when ANY of:

1. Market dislocation: liquidity vacuum, exchange outage, abnormal spread > 5x normal.
2. Strategy misbehavior: PNL diverges sharply from backtest expectation; multiple stops hit in a row.
3. Operator-side outage: dashboard unreachable, channel commands failing — halt out-of-band so trades can't be approved blindly.
4. Cap breach detected manually before the auto-activation has caught up (rare; the service auto-activates on first daily / weekly / max_drawdown breach of the day).

## Sources of activation

The `kill_switch_events.source` CHECK constraint admits seven values (per data-model §3.3 + K1 spec deviation):

| Source                    | Trigger                                                              |
|---------------------------|-----------------------------------------------------------------------|
| `cli`                     | `iguanatrader ops halt --reason "..."` (this runbook)                 |
| `channel_command`         | Telegram/Hermes `/halt` command (slice P1)                            |
| `dashboard_button`        | SvelteKit `/risk` page button (slice W2)                              |
| `automatic_cap_breach`    | Service-layer auto-activation on first daily / weekly / max_drawdown breach of the day |
| `automatic_backoff`       | Slice T4 broker-resilience auto-halt on connectivity collapse         |
| `file_flag`               | Filesystem flag (legacy emergency lever; not wired in K1)             |
| `env_var`                 | Env-var-driven halt at boot (legacy emergency lever; not wired in K1) |

## Activation — operator workflow

### CLI (recommended)

```sh
# 1. Set env vars on the CLI host (one-time per shell):
export IGUANATRADER_OPS_TENANT_ID=11111111-1111-1111-1111-111111111111
export IGUANATRADER_OPS_ACTOR_USER_ID=22222222-2222-2222-2222-222222222222

# 2. Activate. The --reason MUST be ≥20 chars (Typer rejects shorter):
poetry run iguanatrader ops halt --reason "manual freeze: market dislocation 2026-05-05"
# → kill-switch activated: event_id=33333333-3333-3333-3333-333333333333

# 3. Confirm activation propagated (sub-2s contract):
sqlite3 ./data/iguanatrader.db <<SQL
SELECT tenant_id, is_active, last_event_id, updated_at
FROM kill_switch_state
WHERE tenant_id = '11111111-1111-1111-1111-111111111111';
SQL
# → tenant_id|1|33333333-...|2026-05-05T...
```

### Channel command (slice P1, post-K1)

```
@iguana_bot /halt manual freeze: market dislocation observed
```

Channel handler invokes `RiskService.activate_kill_switch(source="channel_command", actor_user_id=<sender>, reason=<text>)`.

### Dashboard button (slice W2, post-K1)

`POST /api/v1/risk/halt` with `{"reason": "..."}` body. Currently NOT exposed in K1 — only `POST /api/v1/risk/override` is wired (the halt endpoint is added when slice W2 ships the dashboard button).

## Confirming activation

The cache row is the NFR-R5 hot-path read; the event log is the audit. Both should agree:

```sql
-- Latest event for the tenant.
SELECT id, transition, source, actor_user_id, reason, created_at
FROM kill_switch_events
WHERE tenant_id = '11111111-1111-1111-1111-111111111111'
ORDER BY created_at DESC
LIMIT 1;

-- Cache row.
SELECT * FROM kill_switch_state
WHERE tenant_id = '11111111-1111-1111-1111-111111111111';
```

If `kill_switch_state.last_event_id` matches the latest event id → cache is fresh, NFR-R5 budget intact.

## Recovery — cache drift detected

Per K1 design D4 + gotcha #32: a partial commit between event-append and cache-update can leave the cache stale. To recover from drift:

```sql
-- Recompute is_active from the latest event row.
UPDATE kill_switch_state
SET is_active = (
  SELECT CASE transition WHEN 'activated' THEN 1 ELSE 0 END
  FROM kill_switch_events
  WHERE tenant_id = kill_switch_state.tenant_id
  ORDER BY created_at DESC
  LIMIT 1
),
last_event_id = (
  SELECT id FROM kill_switch_events
  WHERE tenant_id = kill_switch_state.tenant_id
  ORDER BY created_at DESC
  LIMIT 1
),
updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE tenant_id = '11111111-1111-1111-1111-111111111111';
```

This recovery routine is also run automatically at API boot in slice O1 (when the lifespan-managed risk bus + recovery hook lands). For K1 the recomputation is manual.

## Deactivation

```sh
poetry run iguanatrader ops resume --reason "market normalised; resuming live trading"
# → kill-switch deactivated: event_id=44444444-4444-4444-4444-444444444444
```

`POST /api/v1/risk/resume` is added in slice W2 alongside the halt button. Until then the CLI / channel are the only deactivation surfaces.

## Override audit — when to use

If a single trade MUST go through despite a cap breach (e.g. earnings event you are confident about), the override flow lets an operator bypass the cap WITHOUT deactivating the global kill-switch. The audit is heavyweight by design:

- `reason_text` ≥ 20 chars (Pydantic + service + DB CHECK).
- `confirmation_chain` JSONB carrying first + second confirmations.
- FK to `users.id` ON DELETE RESTRICT (the user who authorised cannot be deleted while the override exists).

CLI:

```sh
poetry run iguanatrader ops override \
    --proposal-id <uuid> --risk-evaluation-id <uuid> \
    --reason "earnings beat 12%; one-off allocation justified"
```

The CLI synthesises a single-actor `confirmation_chain` (both first + second confirmations reference the same `--actor-user-id` + `"cli"` channel). For dual-actor confirmations, use the channel / dashboard surfaces (post-K1).

## Weekly review

Every Monday during retrospective:

1. `iguana export risk-overrides --since 7d` (ships in NFR-O5 export slice).
2. Review every override row for: legitimate reason text (not `"a"*20` junk), correct cap-breach context, double-confirmation chain integrity.
3. Flag junk reasons in retro notes; they don't fail CI but operators should track which reasons get challenged.

## See also

- `openspec/changes/risk-engine-protections/` (slice K1 design + spec contract — archived or not yet created at time of writing).
- [docs/data-model.md §3.3](../data-model.md) — risk table schema.
- [docs/gotchas.md #44, #45, #46](../gotchas.md) — engine purity, cache drift, reason-text junk floor.
- [apps/api/README.md](../../apps/api/README.md) §"Risk context" — public API summary.
