# Design: dual-daemon-mode-toggle-and-reconcile

Architectural decisions, alternatives considered, and the tradeoff reasoning behind each. Read alongside `proposal.md`.

---

## D1. Why two daemons instead of one multi-mode daemon

### Alternative considered

A single `trading_daemon` process that internally manages two concurrent loops (one paper, one live), each connected to its respective IB Gateway. Shared Python interpreter, shared event loop, shared imports — would reduce RAM by ~150MB.

### Why rejected

Three reasons that compound:

1. **Failure isolation.** If the paper daemon hits an unhandled exception in its trading loop (a bad market-data deserialize, a strategy throwing on a corner case), it should NOT take down live trading. Process isolation is the cheapest failure boundary that satisfies the postulate "live trading must survive paper experiments." With two processes, paper can be in a crash loop and live is unaffected. With one process, asyncio's "tasks share the same event loop" property means a thread-local error in paper's coroutine can deadlock or starve the live coroutine.

2. **Independent restart cadence.** IBKR forces a weekly gateway restart at different times depending on account region. Paper accounts and live accounts may be in different regions (or the same — but the operator cannot rely on that). With two processes, paper's gateway restart only restarts paper's gateway; live keeps trading. With one daemon, a single gateway restart event would cascade to whatever code is sharing the same process.

3. **Tenant trading flag is per-mode, not per-daemon.** With `tenant_trading_modes(tenant_id, mode, enabled)`, a single multi-mode daemon would have to read TWO flags every tick and switch behaviour. That's a tangle of conditionals. With two daemons, each reads its own flag — simple boolean check, no branching.

The RAM cost (~150MB extra for a second Python interpreter + ~500MB for the second IB Gateway Java container) is acceptable on cx43 (16GB available, ~3GB used by current stack).

---

## D2. Why a DB flag (`tenant_trading_modes.enabled`) instead of docker container state

### Alternative considered

Toggle paper/live by literally starting/stopping the container: `docker compose start trading_daemon_live` / `docker compose stop trading_daemon_live`. The UI button would POST to a backend endpoint that shells out to `docker compose`.

### Why rejected

1. **Security blast radius.** For the API container to control other containers, it would need access to the host Docker socket (`/var/run/docker.sock`). That is **effective root on the host** — anyone who compromises the API container can launch arbitrary containers with arbitrary mounts. Roundtable participant Raúl (SRE) explicitly flagged this as unacceptable. The DB-flag pattern keeps the API container in its existing privilege envelope.

2. **State observability.** With `enabled=false` as a DB row, the system can answer "why isn't the live daemon trading?" with a SQL query: who toggled it off, when, with what reason. Container-state mode has no analogous audit trail unless we layer one on top.

3. **Reversibility.** A misclick that stops a container leaves the gateway in a half-state (TWS still logged in, sockets open, but the consumer daemon is gone). Resuming requires a full bring-up cycle. A misclick that flips `enabled=false` is reversible in one click — the daemon resumes its loop on the next tick.

4. **Reconcile is a separate concern.** Reconciliation needs to run regardless of `enabled` state (you reconcile a disabled daemon to make sure local state matches IBKR before re-enabling). Container start/stop entangles "trading on/off" with "process up/down." DB flag cleanly separates them.

The cost: both daemon processes consume RAM even when idle. Mitigated by D1's resource accounting.

---

## D3. Drain semantics — soft, with explicit pending-proposal rejection

### Alternative considered

**Hard stop**: on toggle-off, cancel every order currently submitted to IBKR via `cancel_all_open_orders()` API call. Aggressive but clean — guarantees no further fills.

**Pure soft stop**: on toggle-off, just stop generating new signals. Don't touch pending proposals (they sit in `pending_approval`); don't cancel IBKR-side orders. Operator manually decides what to do with the queue on resume.

### Why neither, and why we chose "drain with proposal rejection"

The user articulated the requirement: "mientras el daemon esté apagado no se pueden crear proposals ni fills." Translating to behaviour:

- **No new proposals**: trivially satisfied by skipping strategy ticks in the main loop.
- **No fills from new orders**: trivially satisfied by not submitting new orders.
- **Pending proposals (already generated, awaiting human approval)**: these are the ambiguous case. If the operator drains the daemon, can they still approve a proposal that's sitting in the queue? The user said "no se pueden crear proposals" — and a proposal that's still in `pending_approval` is operationally indistinguishable from a freshly-created one from the operator's perspective. Approving it would trigger an order submission, which is exactly what drain is supposed to prevent.

So pending proposals get **auto-rejected with `rejection_reason='daemon_drained'`** on drain. The operator sees them as historical "almost-fired" decisions, audit-traceable. On re-enable, the strategy will re-evaluate the same conditions and may emit a fresh proposal — that's the correct semantics (the world has moved on; the old proposal's risk assessment is stale).

**Implementation note (Phase 1.5 discovery)**: the original spec assumed `TradeProposal` already had `state` + `rejection_reason` + `rejected_at` columns — it did not. The codebase tracked rejection exclusively via the `approval_decisions` audit log (one row per decision, no row-level state on the proposal). Migration `0028_trade_proposal_state.py` adds the 3 columns + extends `TradeProposal.__append_only_mutable_columns__` so the drain `UPDATE` + the approval-handler state propagation can advance the row's lifecycle without breaking the otherwise-strict append-only contract. The `approval_decisions` log remains the cross-context event truth; the new columns are a row-level denormalisation so `pending_proposals_count` is an O(1) `WHERE` filter instead of a `LEFT JOIN` against `approval_decisions`. Same pattern that `Trade` already uses for its close-flow columns (`state` + `closed_at` + `exit_reason` + `realised_pnl`).

**IBKR-side orders are NOT cancelled** because IBKR is authoritative — we don't pretend to know whether IBKR has already filled them, partially filled, or queued them for the next market session. Cancelling them creates race conditions (we cancel an order that's about to fill; IBKR fills it anyway; we have an unrecorded execution). Letting them live their natural lifecycle is safer, and the operator can always cancel manually via IBKR's own dashboard or via `iguanatrader trading cancel <order_id>`.

This is exactly what the user phrased: "la cuenta de interactive broker siempre manda." IBKR is the source of truth for orders; the daemon only generates new ones (or refuses to).

---

## D4. Reconcile-on-resume is mandatory

### Decision

When `enabled=false` → `enabled=true` toggle is requested, the daemon MUST run reconcile against IBKR before accepting any new signals. The endpoint emits `daemon.reconcile.requested(mode)` and the daemon's main loop checks this flag at the top of each tick. The first tick after toggle-on runs reconcile; only subsequent ticks resume strategy evaluation.

### Why mandatory and not optional

While the daemon was off:
- IBKR may have closed positions at stop-loss (paper accounts have automated stop-loss simulation; live accounts may have GTC orders that filled during the drain).
- The operator may have manually closed positions via IBKR's own dashboard.
- The weekly IBKR restart may have reset gateway state.
- (Live only) margin calls or account events may have force-liquidated positions.

If the daemon resumes without reconcile, its in-memory + local-DB view of positions is stale. The first strategy tick would size a new trade against a position that may no longer exist, or generate a "close" signal for something IBKR already closed. Either way: wrong order sized against wrong assumed state = bad fills.

Reconcile is cheap (one IBKR API call per category: positions, open orders, cash). The 1-2 second delay before resuming signals is acceptable.

### On-demand reconcile button

The same `_reconcile_with_ibkr()` function powers `POST /api/v1/daemons/{mode}/reconcile`. The operator can trigger it at any time without toggling the daemon. Use cases:
- After a manual IBKR-side action (closed a position via TWS), force iguanatrader to pick it up immediately instead of waiting for the next scheduled reconcile.
- Suspected drift between local state and IBKR — call reconcile, compare logs.
- Before promoting paper to live — confirm local state matches what the live account thinks.

---

## D5. Live toggle requires password re-entry

### Decision

Toggling `live.enabled` to `true` requires the operator to re-enter their session password via a `password_reconfirm` field. Server-side: re-run the same hash-compare used at login; reject with 403 on mismatch. Paper toggle does NOT require this.

### Why

Marcos (day trader) flagged this in the roundtable: a single-click toggle to enable live trading is the kind of UX that loses money to mis-clicks, dropped phones, and cat-on-keyboard scenarios. Adding password re-entry adds friction proportional to the cost of a mistake.

This is **not** equivalent to the FR25 double-confirmation pattern (which requires two independent channels — dashboard + Telegram/WhatsApp). FR25 applies to *risk overrides* (bypassing a risk-cap rejection). Daemon toggle is a different threat model: the operator clearly intends to act; we just want to make sure they intend to act ON LIVE specifically.

Password re-entry covers:
- Lost phone scenario (someone has access to the open browser session but not the password).
- Shoulder-surfed session.
- Operator's-own-mistake friction.

Future enhancement (not in scope here): allow 2FA TOTP as an alternative to password re-entry. Roadmap candidate.

---

## D6. Why `daemon_heartbeats` table instead of in-memory `DaemonHealthRegistry`

### Alternative considered

Pure in-process registry: the daemon updates a Python dict every 10s; the API queries it via shared memory or IPC.

### Why DB table

The api container and the daemon containers are **separate processes** that do not share memory. Any in-process registry would have to live in the api container — which means the daemon would push heartbeats to the api via HTTP every 10s. That's a redundant network round-trip, error-prone (what if the api restarts? does the daemon retry? buffer?).

A `daemon_heartbeats` table is dirt-cheap:
- 1 row per (tenant, mode), upserted every 10s.
- The api's `GET /api/v1/status` reads it.
- DB is the existing shared substrate — no new transport mechanism needed.
- Stale detection is trivial: `WHERE last_heartbeat_at > NOW() - INTERVAL '30 seconds'`.

The write traffic is negligible (~6 rows/min total across both daemons). SQLite handles this without breaking a sweat.

---

## D7. Polling cadence in the web layout

### Decision

The layout root polls `GET /api/v1/status` every 5 seconds while the tab is visible. Pauses (clears interval) when `document.visibilityState === 'hidden'` and resumes on visibility change.

### Why 5s and not 1s, 10s, or SSE/WebSocket

- **1s**: too noisy, generates ~70 req/operator/hour for a piece of data that changes minutes apart on average.
- **10s**: too laggy; an operator clicks LIVE toggle and waits 10s before the chip updates → feels broken.
- **SSE/WebSocket**: justified if the system has 100+ concurrent operators per backend. We have 1. The complexity is not worth it for a single-operator system.
- **5s**: ~720 req/operator/hour, ~ 17KB/hour bandwidth, trivially handled. Operator perceives the chip as "live" without server churn.

Pausing on tab hidden is the small additional optimization. The browser's `visibilitychange` event handler stops the interval and a single fetch on resume catches up.

---

## D8. Mode badge colors are FIXED, not state-dependent

### Decision

- `paper` mode badge is ALWAYS yellow (warning) — regardless of `enabled` state, regardless of `ib_connected` state.
- `live` mode badge is ALWAYS red (destructive) — regardless of anything.
- The dim/saturated brightness encodes the boolean "this daemon is currently operating."

### Why this anti-pattern relative to typical service health UIs

Standard "service health" UI uses green=up / red=down. In trading, **red conveys risk**, not failure. If the LIVE chip turned green when active, we'd be telling the operator "all is well" precisely when they should be most alert. The chip should make the operator MORE careful when LIVE is on, not less.

So: color encodes **what mode it is** (paper=warning, live=destructive), brightness encodes **whether it's running**. The two pieces of information stay orthogonal in the visual system.

Day trader and UX designer in the roundtable converged on this. Diana (compliance) also approved — "the LIVE chip should never recede into the visual background."

---

## D9. Live daemon defaults to `enabled=false` on first migration

### Decision

The migration seeds `tenant_trading_modes` rows for every existing tenant as:
- `(tenant_id, 'paper', enabled=true)` — preserves current behaviour.
- `(tenant_id, 'live', enabled=false)` — explicit operator action required to enable.

### Why default-off for live

Current production state has a single tenant (Arturo) running paper-mode-only. A migration that auto-enables live would:
1. Boot the live daemon, which would try to connect to `ib-gateway-live`.
2. `ib-gateway-live` would boot but the operator has not yet populated `TWS_USERID_LIVE`/`TWS_PASSWORD_LIVE` in SOPS — connection fails, retry loop, log spam.
3. Confusing failure mode for the operator who just upgraded.

Default-off keeps the upgrade silent: paper continues as before; live appears in the UI as a disabled chip; operator opts in when ready. Reversible.

---

## D10. What we did NOT change

To keep the slice small enough to ship in one PR:

- **`mode` column on existing tables stays.** `TradeProposal.mode`, `Trade.mode`, `EquitySnapshot.mode` are already there and correct. No data migration needed for those.
- **Risk caps stay per-deployment-env** (`PAPER_CAPITAL_CAP_USD` vs `LIVE_CAPITAL_CAP_USD`). Future slice may unify into a `risk_caps` table keyed by mode, but env-driven works for now.
- **Strategy table unchanged.** Per-mode strategy gating (`Strategy.enabled_modes`) is the follow-up slice O8.
- **Portfolio / risk / trades queries already filter by mode** in many places. A separate audit pass (part of follow-up O7) will catch any remaining mode-blind queries; not required for this slice's correctness.
- **Existing CLI `iguanatrader trading reconcile`** stays. The new endpoint shares its implementation but does not deprecate the CLI — useful for emergency operator access when the UI is down.
