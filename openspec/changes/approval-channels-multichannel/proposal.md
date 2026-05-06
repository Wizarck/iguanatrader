## Why

The MVP's defining promise is "LLM proposes, human approves from phone, IBKR executes" (PRD §2 + Journey 2). Without the approval bounded context, no proposal can ever become a trade — every other Wave 2 slice (K1 risk, T1 trading, O1 observability) produces or evaluates proposals that dead-end in the database. P1 plants the missing link: a multichannel command surface (Telegram + Hermes/WhatsApp) with **17 shared commands**, **append-only audit** of every decision, and **resilient long-polling** that survives transient network drops without dropping pending approvals (NFR-I5/I6). The slice composes on top of slice 2's `HeartbeatMixin` + canonical `[3, 6, 12, 24, 48]` backoff (NFR-R7) — channels do not reimplement reconnect logic, they inherit it. The slice rides the slice-5 anti-collision foundation: a new `routes/approvals.py`, a new `sse/approvals.py`, a new `cli/approval.py` are dropped in alongside other Wave-2 contributors without touching `api/app.py`, `routes/__init__.py`, or `cli/main.py`. Now is the right time because slice 5 just shipped the foundation contract and slices K1 (risk) + T1 (trading) need a target for their `proposal.created` events to land — the approval context is the consumer that closes that loop.

## What Changes

- **New `approval` bounded context** under `apps/api/src/iguanatrader/contexts/approval/` with `service.py` (orchestration: `create_request → fan_out_to_channels → resolve_decision → emit_event`), `repository.py` (BaseRepository over the two append-only tables), `events.py` (publishes `approval.proposal.approved`, `approval.proposal.rejected`, `approval.proposal.timed_out` to the slice-2 `MessageBus`), and a `channels/` subpackage.
- **`channels/command_handler.py`** — single dispatcher that receives normalised `IncomingCommand` records (already verified against `authorized_senders`) and routes to a handler keyed by command name. The dispatcher is the source of truth for the **17 shared commands** so Telegram and WhatsApp/Hermes never drift: `/approve`, `/reject`, `/halt`, `/resume`, `/status`, `/positions`, `/equity`, `/strategies`, `/risk`, `/override`, `/cost`, `/budget`, `/help`, `/whoami`, `/lock`, `/unlock`, `/logout`.
- **`channels/telegram.py`** — Telegram channel adapter inheriting `HeartbeatMixin` (slice 2). Implements long-polling `_send_heartbeat` (probes the Telegram API), `_on_disconnect` (emits structlog `approval.channel.telegram.disconnected` + flushes pending in-flight callbacks), and reads inbound updates → normalises to `IncomingCommand` → forwards to `command_handler`. Hides the wire client behind a `TelegramTransportPort` (D8) so slice 5's tests can stub the network without new dependencies.
- **`channels/whatsapp_hermes.py`** — same shape over Meta's Cloud API surfaced via the Hermes facade. Same `HeartbeatMixin` heritage, same canonical backoff `[3, 6, 12, 24, 48]`, same dispatch into `command_handler`. Stubbed transport via `WhatsAppTransportPort`; real Hermes wiring deferred to a follow-up slice (D8).
- **Migration `0005_approval_tables.py`** — creates `approval_requests` and `approval_decisions` (both append-only — registered with the slice-3 `append_only_listener`). Schema follows `docs/data-model.md` §3.4 verbatim: `approval_requests(id, tenant_id, proposal_id FK, delivered_to_channels JSON, timeout_seconds, expires_at, created_at)` and `approval_decisions(id, tenant_id, request_id FK, outcome [granted|rejected|timeout], decided_via_channel, decided_by_user_id, decided_by_sender_id, latency_ms, created_at)` with `uq_approval_decisions_request_id` enforcing first-decision-wins idempotency.
- **`api/routes/approvals.py`** — `GET /api/v1/approvals` (list pending for the current tenant) + `POST /api/v1/approvals/{id}/approve` + `POST /api/v1/approvals/{id}/reject` (dashboard-channel parity with Telegram/WhatsApp commands; same service path, different transport). Errors raise `IguanaError` subclasses; the slice-5 global handler renders RFC 7807.
- **`api/sse/approvals.py`** — `GET /api/v1/stream/approvals` for the SvelteKit dashboard (slice W1 consumer). Streams `approval.request.created` + `approval.decision.recorded` events to authenticated clients (tenant-scoped via `contextvars`).
- **`api/dtos/approvals.py`** — `ApprovalRequest`, `ApprovalDecision`, `ApprovalCommandResult` Pydantic v2 models; the typegen pipeline emits these as TS interfaces in `@iguanatrader/shared-types` on first push.
- **`cli/approval.py`** — typer subcommand exposing read-only ops (`list`, `audit <request_id>`); auto-discovered by slice-5's CLI scaffold.
- **17-command canonical registry** — `channels/commands/__init__.py` exposes `COMMANDS: Mapping[str, CommandSpec]` enumerating all 17 with handler reference, required role, and idempotency-key convention. Both channels iterate this same dict — adding a command is a single-file edit, not a multi-file edit.
- **Authorized-sender enforcement** — every inbound command is checked against `authorized_senders(tenant_id, channel, external_id, enabled=TRUE)` before reaching the dispatcher. Non-whitelisted senders: log structlog `approval.channel.sender_rejected` + drop silently (no echo — avoids enumeration; PRD §Account-takeover row).
- **Idempotency keys** — `/approve` and `/reject` carry a per-request idempotency key (Telegram `callback_query_id` / WhatsApp `interactive_id`). The service path checks `approval_decisions.request_id` UNIQUE constraint; duplicate retries are no-ops, not double-decisions.
- **Tests** — `tests/integration/test_telegram_resilience.py` and `tests/integration/test_hermes_resilience.py` simulate channel drop → `HeartbeatMixin` walks the canonical backoff schedule → mark connected → resume processing pending updates without loss. `tests/integration/test_approval_flow.py` covers happy-path proposal → approve → event emission. `tests/unit/contexts/approval/test_command_dispatcher.py` covers the 17-command registry + authorized_senders enforcement.

## Capabilities

### New Capabilities

- `approval`: multichannel approval surface for trade proposals — Telegram + Hermes/WhatsApp transports with shared 17-command dispatcher, append-only audit of every decision, idempotent retries, authorized-sender enforcement, heartbeat-based reconnect resilience inheriting slice-2 primitives, and cross-context event emission for downstream trading execution.

### Modified Capabilities

(none — slice P1 does not modify any prior capability.)

## Impact

- **Affected code (slice-P1-owned, write-allowed)**:
  - `apps/api/src/iguanatrader/contexts/approval/{__init__,service,repository,events}.py` (NEW).
  - `apps/api/src/iguanatrader/contexts/approval/channels/{__init__,command_handler,telegram,whatsapp_hermes}.py` (NEW).
  - `apps/api/src/iguanatrader/contexts/approval/channels/commands/__init__.py` (NEW — 17-command registry).
  - `apps/api/src/iguanatrader/contexts/approval/models.py` (NEW — SQLAlchemy mappings for `approval_requests` + `approval_decisions`).
  - `apps/api/src/iguanatrader/migrations/versions/0005_approval_tables.py` (NEW).
  - `apps/api/src/iguanatrader/api/routes/approvals.py` (NEW — auto-discovered).
  - `apps/api/src/iguanatrader/api/sse/approvals.py` (NEW — auto-discovered).
  - `apps/api/src/iguanatrader/api/dtos/approvals.py` (NEW).
  - `apps/api/src/iguanatrader/cli/approval.py` (NEW — auto-discovered).
  - `apps/api/tests/integration/{test_telegram_resilience,test_hermes_resilience,test_approval_flow}.py` (NEW).
  - `apps/api/tests/unit/contexts/approval/{test_command_dispatcher,test_authorized_sender_guard,test_idempotency_keys}.py` (NEW).
- **Affected code (read-only consumed)**:
  - `iguanatrader.shared.heartbeat.HeartbeatMixin` (slice 2 contract; consumed unchanged).
  - `iguanatrader.shared.backoff.backoff_seconds` (slice 2 contract; consumed unchanged).
  - `iguanatrader.shared.messagebus.MessageBus` (slice 2 contract — emits `approval.proposal.{approved,rejected,timed_out}`).
  - `iguanatrader.shared.errors.IguanaError` hierarchy (slice 2; new subclasses added: see below).
  - `iguanatrader.persistence.append_only_listener` (slice 3 contract; new tables register against it).
  - `authorized_senders` table from slice 3's `0001_initial_schema.py` (read-only; checked on every inbound command).
  - `iguanatrader.api.errors` global RFC 7807 handler (slice 5; routes raise, handler renders).
  - `iguanatrader.api.routes.__init__.register_routers` + `iguanatrader.api.sse.__init__.register_sse` + `iguanatrader.cli.main._register_subcommands` (slice 5; auto-discovery).
- **New `IguanaError` subclasses** (added to `iguanatrader.shared.errors`):
  - `ApprovalNotFoundError` (404, `urn:iguanatrader:error:approval-not-found`).
  - `ApprovalAlreadyDecidedError` (409, `urn:iguanatrader:error:approval-already-decided`) — first-decision-wins on duplicate retries.
  - `ApprovalExpiredError` (410, `urn:iguanatrader:error:approval-expired`) — request crossed `expires_at`.
  - `UnauthorizedSenderError` (403, `urn:iguanatrader:error:unauthorized-sender`) — only logged + dropped at the channel boundary; the API surface uses it when the dashboard route receives a request from a tenant whose user is not also an `authorized_senders` entry (rare case; usually `AuthError` triggers first).
- **Cross-context events emitted to MessageBus** (consumed by trading context T2/T4):
  - `approval.proposal.approved(proposal_id, decision_id, decided_at)` — trading service kicks off broker order placement.
  - `approval.proposal.rejected(proposal_id, decision_id, decided_at, reason?)` — trading service marks proposal as terminal.
  - `approval.proposal.timed_out(proposal_id, request_id, expired_at)` — trading service marks proposal as auto-discarded (FR13).
- **Affected dependencies**:
  - **No new external deps.** Telegram + WhatsApp clients are stubbed behind Ports for this slice (D8). A follow-up slice (`approval-real-clients` or wired into P1.1) imports `python-telegram-bot` + `hermes-client` + adds Meta Cloud API credentials; out of scope here to keep integration tests fast and avoid new external attack surface in Wave 2.
- **Prerequisites**:
  - `api-foundation-rfc7807` (slice 5) — provides RFC 7807 + dynamic discovery + typegen pipeline. Hard prereq.
  - `risk-engine-protections` (K1) — read-only for `kill_switch_state` (the `/halt` and `/resume` commands write to K1's append-only `kill_switch_events`; merge order **K1 → P1** so the import surface exists). P1 does not duplicate K1 logic; it routes commands.
  - Slice 3 — `authorized_senders` table + `append_only_listener` + `tenant_listener`.
- **Capability coverage** (per `docs/openspec-slice.md` row P1): FR12, FR13, FR31, FR32, FR33, FR34, FR35, FR36, FR37, FR38 + NFR-I5 (Telegram reconnect), NFR-I6 (Hermes/WhatsApp reconnect + token rotation). FR33-FR35 (Tier-1/2/3 alerts) land their delivery surface here; the alert origination + scheduling is slice O2 — P1 owns the channel transport that O2 invokes.
- **Out of scope** (deferred to follow-up slices):
  - Real Telegram + Hermes/WhatsApp wire clients (D8 — stub-only for this slice).
  - Per-channel template approval workflow for Meta WhatsApp (NFR-I6 second clause: "templates pre-aprobados antes de v1.0 launch") — NFR-I6 in this slice covers reconnection only; template approval is a v0.9→v1.0 launch checklist item.
  - SvelteKit dashboard pages for `/approvals` — slice W1 consumes the SSE + REST endpoints this slice ships.
  - `/override` flow's double-confirmation dialog UX — this slice routes the command to risk service (K1 owns the override semantics); the chained confirmation prompts live in `command_handler` here but the override audit row is K1's table.
  - Hindsight integration of approval narratives — slice R6.
