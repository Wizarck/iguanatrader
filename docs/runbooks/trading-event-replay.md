# Runbook — Trading event replay

**Last updated**: 2026-05-05 (slice T1 `trading-models-interfaces`).
**Owner**: trading bounded context (slice T1 plants the runbook skeleton; slice O1 + O2 refine).

## When to use this runbook

A downstream subscriber to a `trading.*` :class:`MessageBus` event crashed mid-handler and you need to replay the missed work. Common triggers:

- Slice K1 `RiskService` crashed before writing its `risk_evaluations` row → an in-flight `ProposalCreated` event was consumed but the engine output was never persisted.
- Slice P1 `ApprovalService` lost the Telegram dispatch context → a `ProposalRiskEvaluated` event is unaccounted-for.
- Slice O1 cost meter dropped a `trading.*` narration → analytics gap until replay.

## Important: bus is in-process, not durable

Per slice 2 design D1, the `MessageBus` is a single-process pub/sub with FIFO-per-subscriber queues. **There is no durable replay log on the bus itself** — events held in-memory are lost on process restart. Replay reconstructs the missing handler work from the **DB tables that the producer side wrote** before the failure.

This runbook is the operator playbook for that DB-driven replay. It does NOT cover:

- Live mid-flight event redelivery — slice 2's bus has no retry; restart the consumer + replay manually per the steps below.
- Cross-process queue (Redis / NATS) — out of scope per slice 2 Non-Goals.

## Step 1 — Identify the gap

The structlog event-name convention (NFR-O8) ties producer + consumer:

| Producer event (DB row) | Consumer slice | Receipt row to verify |
|---|---|---|
| `trading.proposal.created` (`trade_proposals` row) | K1 RiskService | `risk_evaluations.proposal_id` |
| `trading.proposal.risk_evaluated` (`risk_evaluations` row) | T1 TradingService | `audit_log` entry `entity_kind='approval_request'` |
| `trading.approval.requested` (`audit_log`) | P1 ApprovalService | `approval_requests.proposal_id` |
| `trading.proposal.approved` (`approval_decisions`) | T1 TradingService | `orders.proposal_id` (via `trades`) |
| `trading.order.placed` (`orders` row) | T2 reconciliation worker | `fills.order_id` (eventually) |
| `trading.order.filled` (`fills` row) | T1 update_equity | `equity_snapshots.created_at` post-fill |

Query: find producer rows without their corresponding consumer rows.

```sql
-- Example: proposals without risk evaluations (K1 gap).
SELECT tp.id, tp.created_at
FROM trade_proposals tp
LEFT JOIN risk_evaluations re ON re.proposal_id = tp.id
WHERE re.id IS NULL
  AND tp.created_at > :since;
```

## Step 2 — Verify the gap is genuine

Check that the consumer slice was running at the gap window. Cross-reference with:

- `audit_log` entries from the consumer slice (every state change writes a row per FR46).
- structlog events `<consumer-slice>.<entity>.<action>` in the log aggregation (slice O1 sink).

If the consumer slice was offline (deploy, restart, crash), the gap is genuine and replay is needed. If the consumer was up but no rows appeared, escalate — that's a bug, not a replay-able gap.

## Step 3 — Replay path per consumer

### K1 (RiskService)

```bash
# Replay every proposal without a risk evaluation since :since.
# Slice K1 will ship the CLI subcommand; this is the contract.
iguanatrader admin replay-risk --since 2026-05-05T00:00:00Z --tenant <slug>
```

Behaviour: re-emits `ProposalCreated` for each gap row → K1's existing subscriber handles it idempotently (idempotency key = proposal_id).

### P1 (ApprovalService)

```bash
iguanatrader admin replay-approvals --since 2026-05-05T00:00:00Z --tenant <slug>
```

Behaviour: re-emits `ApprovalRequested` for each evaluated-but-not-decided proposal. Operator must confirm with the user that no double-approval / double-rejection happens (slice P1's idempotency window covers single-process replays only).

### O1 (cost meter / structlog narrator)

The cost meter's gap is least-critical — it's an analytics view, not a state-mutating handler. Re-emit any of the above events; O1 deduplicates on (event_id, sink_id).

## Step 4 — Verify the replay

- Re-run the SQL gap query from Step 1 — it should return zero rows.
- Spot-check the `audit_log` for the consumer slice — its `<event>.replayed` breadcrumb should appear with `replayed_from=<original_event_id>`.
- Confirm the user-facing surface (dashboard / Telegram) reflects the replayed state.

## What slice T1 ships vs what subsequent slices fill

- **Slice T1 (this runbook's authoring)**: skeleton — the table mapping above + the in-process-bus caveat.
- **Slice O1 `observability-cost-meter`**: refines step 1's SQL helpers + adds a structlog correlation-ID join across all `trading.*` events.
- **Slice O2 `orchestration-scheduler-routines`**: adds the LangGraph-backed replay coordinator that operators invoke instead of running step 3 commands by hand.

## See also

- `docs/architecture-decisions.md` ADR-005 (MessageBus contract).
- `docs/data-model.md §6` (cross-context FKs + audit-log invariant).
- `apps/api/src/iguanatrader/contexts/trading/events.py` (frozen event wire format).
- `apps/api/src/iguanatrader/contexts/trading/service.py` (subscriber registration).
