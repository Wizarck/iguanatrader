## ADDED Requirements

### Requirement: Approval channels share a single 17-command registry

The system SHALL expose exactly 17 user-facing commands — `/approve`, `/reject`, `/halt`, `/resume`, `/status`, `/positions`, `/equity`, `/strategies`, `/risk`, `/override`, `/cost`, `/budget`, `/help`, `/whoami`, `/lock`, `/unlock`, `/logout` — defined in a single canonical registry under `apps/api/src/iguanatrader/contexts/approval/channels/commands/__init__.py`. The Telegram adapter, the Hermes/WhatsApp adapter, and the dashboard adapter SHALL each iterate this same registry; no adapter SHALL define commands locally. (FR37)

#### Scenario: All three channels accept the same `/approve` command

- **WHEN** an authorized sender issues `/approve <request_id>` via Telegram, Hermes/WhatsApp, or the dashboard `POST /api/v1/approvals/{id}/approve`
- **THEN** all three transports normalise to the same `IncomingCommand(command_name="/approve", ...)` dispatched to the same handler
- **AND** the resulting `approval_decisions` row differs only in `decided_via_channel` (`telegram` | `whatsapp` | `dashboard`)
- **AND** the resulting MessageBus event `approval.proposal.approved` is byte-identical regardless of source channel

#### Scenario: A new command is added by appending one file

- **WHEN** a future slice adds command `/audit` by dropping `commands/audit.py` exporting `SPEC: CommandSpec(name="/audit", ...)`
- **THEN** the registry's `pkgutil.iter_modules` discovery picks it up at boot
- **AND** the command is reachable on Telegram, Hermes/WhatsApp, and dashboard simultaneously without editing either transport adapter

### Requirement: Channels reconnect via `HeartbeatMixin` + canonical backoff after a connection drop

The system SHALL implement `TelegramChannel` and `HermesWhatsAppChannel` as subclasses of `iguanatrader.shared.heartbeat.HeartbeatMixin`. After a connection drop, the channel SHALL invoke `HeartbeatMixin.reconnect_loop()` which walks the canonical backoff schedule `[3, 6, 12, 24, 48]` seconds (`iguanatrader.shared.backoff.backoff_seconds`) with ±20% jitter. Pending `approval_requests` rows persist throughout the drop; on reconnect, the channel resumes long-polling and any inbound decisions for unexpired requests SHALL be processed normally. (NFR-I5, NFR-I6)

#### Scenario: Telegram channel survives a network drop without losing pending requests

- **GIVEN** the Telegram channel is `CONNECTED` and one `approval_requests` row exists with `expires_at = now + 60s`
- **WHEN** the channel transitions to `DISCONNECTED` (simulated `await channel.mark_disconnected()`)
- **THEN** structlog event `approval.channel.telegram.disconnected` is emitted exactly once
- **AND** the `_on_disconnect` hook fires exactly once
- **AND** the `reconnect_loop` task waits 3s (jittered to `[2.4s, 3.6s]`), then calls `_send_heartbeat`
- **AND** when `_send_heartbeat` succeeds on attempt N, the channel marks `CONNECTED` and resumes polling
- **AND** the `approval_requests` row is still pending (no row was modified during the outage; append-only invariant holds)
- **AND** an inbound `/approve` arriving post-reconnect resolves the request normally

#### Scenario: Hermes/WhatsApp channel applies the canonical backoff schedule, not its own

- **WHEN** the Hermes channel reconnect_loop runs through 5 failed attempts
- **THEN** the sleep durations between attempts are `backoff_seconds(0..4, with_jitter=True)` — base values `[3, 6, 12, 24, 48]` ±20%
- **AND** no transport adapter imports `time.sleep` or `asyncio.sleep` with a hardcoded numeric literal (CI grep assertion)

### Requirement: Inbound commands are dispatched through a single `command_handler` regardless of channel

The system SHALL provide `apps/api/src/iguanatrader/contexts/approval/channels/command_handler.py::dispatch(incoming: IncomingCommand) -> CommandResult` as the single entry point for all inbound commands. Both transport adapters and the dashboard route SHALL call `dispatch` after sender verification + payload normalisation. The dispatcher SHALL look up the handler in the 17-command registry, enforce the command's `required_role`, run the idempotency check, and invoke the handler. The dispatcher SHALL NOT perform transport-specific work.

#### Scenario: Dispatcher routes `/positions` to the correct handler

- **GIVEN** the registry contains `COMMANDS["/positions"]` with `handler=_handle_positions, required_role="user"`
- **WHEN** `dispatch(IncomingCommand(command_name="/positions", sender=<authorized_user>, channel="telegram", ...))` is called
- **THEN** the dispatcher invokes `_handle_positions(ctx)` exactly once
- **AND** the returned `CommandResult` carries the open-trades fold for the caller's tenant
- **AND** structlog event `approval.command.dispatched` is emitted with `command="/positions"` and `channel="telegram"`

#### Scenario: Dispatcher rejects a command requiring a higher role

- **WHEN** `dispatch(IncomingCommand(command_name="/halt", sender=<user_role_user>, ...))` is called
- **THEN** the dispatcher emits structlog `approval.command.role_denied` with `command="/halt", required_role="admin", actual_role="user"`
- **AND** returns `CommandResult(status="denied", message="This command requires admin role.")`
- **AND** no `kill_switch_events` row is written

### Requirement: Non-whitelisted senders are dropped silently at the channel boundary

The system SHALL check every inbound message against `authorized_senders(tenant_id, channel, external_id, enabled=TRUE)` before dispatching to the command_handler. Non-matching senders SHALL be dropped silently — no echo to the sender, no exception raised — and a structlog event `approval.channel.sender_rejected` SHALL be emitted with `channel`, hashed `external_id`, and `tenant_id`. (FR31, FR38, NFR-S3, NFR-S4)

#### Scenario: Unauthorized Telegram user issues `/status`

- **GIVEN** a Telegram user with ID `999999` who is NOT in `authorized_senders` for any tenant
- **WHEN** they send `/status` to the bot
- **THEN** the channel adapter does NOT echo any response back to the user
- **AND** the channel adapter does NOT raise an exception
- **AND** structlog event `approval.channel.sender_rejected` is emitted with `channel="telegram"`, `external_id_sha256=<hash of "999999">`, `tenant_id=<bot's tenant>`
- **AND** no `IncomingCommand` is constructed; the dispatcher is never called

#### Scenario: Disabled `authorized_senders` row blocks the same way as no row

- **GIVEN** a row `authorized_senders(tenant_id=T, channel='telegram', external_id='123', enabled=FALSE)`
- **WHEN** Telegram user `123` sends `/status`
- **THEN** the message is dropped silently — same outcome as if the row did not exist

### Requirement: `/approve` and `/reject` are idempotent — duplicate retries do not create duplicate decisions

The system SHALL guard `/approve` and `/reject` against duplicate dispatch (e.g., Telegram callback_query at-least-once delivery, user double-clicking the inline button) via the database UNIQUE constraint `uq_approval_decisions_request_id`. The first commit wins; subsequent attempts SHALL raise `ApprovalAlreadyDecidedError` (HTTP 409, RFC 7807 type URI `urn:iguanatrader:error:approval-already-decided`) and the response SHALL idempotently echo the original decision. No duplicate `approval.proposal.approved` event SHALL be emitted to the MessageBus.

#### Scenario: User clicks "Approve" twice on the Telegram inline keyboard

- **GIVEN** a pending `approval_requests` row with `id=R`
- **WHEN** the user clicks "Approve" and the callback delivers twice (`callback_query_id=Q1` and a retry `callback_query_id=Q2`)
- **THEN** the first dispatch INSERTs `approval_decisions(request_id=R, outcome='granted', ...)` successfully
- **AND** the MessageBus emits `approval.proposal.approved` exactly once
- **AND** the second dispatch's INSERT raises `IntegrityError` against `uq_approval_decisions_request_id`
- **AND** the service catches it, returns the existing decision row, and the user sees the same "approved at HH:MM:SS" confirmation

#### Scenario: `/approve` retry from a different channel after the first wins

- **GIVEN** the user approved request `R` via Telegram
- **WHEN** the same user 5 seconds later clicks Approve via the dashboard `POST /api/v1/approvals/R/approve`
- **THEN** the dashboard route raises `ApprovalAlreadyDecidedError`
- **AND** the global RFC 7807 handler renders `{"type": "urn:iguanatrader:error:approval-already-decided", "title": "Approval already decided", "status": 409, "detail": "Decision already recorded via telegram at <iso8601 timestamp>."}`

### Requirement: Every approval decision is recorded append-only with channel + latency

The system SHALL persist every approval outcome — `granted`, `rejected`, `timeout` — as a row in `approval_decisions`. The table SHALL be registered with the slice-3 `append_only_listener`; UPDATE and DELETE operations SHALL raise `AppendOnlyViolation`. Each row SHALL record `decided_via_channel`, `latency_ms` (computed as `decision.created_at - request.created_at` in milliseconds), and the deciding identity (`decided_by_user_id` for dashboard channel; `decided_by_sender_id` for telegram/whatsapp; both NULL for `outcome='timeout'`). (FR48, FR12, FR13)

#### Scenario: `/approve` via Telegram records full decision row

- **GIVEN** an approval request created at `t0`
- **WHEN** an authorized Telegram sender issues `/approve` at `t0 + 8.4s`
- **THEN** an `approval_decisions` row is INSERTed with `outcome='granted'`, `decided_via_channel='telegram'`, `decided_by_sender_id=<sender row id>`, `decided_by_user_id=NULL`, `latency_ms=8400`
- **AND** an `UPDATE approval_decisions SET outcome='rejected' WHERE request_id=R` SHALL raise `AppendOnlyViolation`

#### Scenario: Timeout sweeper records system-decided outcome

- **GIVEN** an approval request with `expires_at = t0 + 60s` and no decision by `t0 + 61s`
- **WHEN** `service.sweep_expired_requests()` runs
- **THEN** an `approval_decisions` row is INSERTed with `outcome='timeout'`, `decided_via_channel='timeout'`, `decided_by_user_id=NULL`, `decided_by_sender_id=NULL`, `latency_ms=60000`
- **AND** the MessageBus emits `approval.proposal.timed_out` (FR13)

### Requirement: Approval outcomes emit cross-context events on the MessageBus

The system SHALL publish exactly one MessageBus event per `approval_decisions` INSERT: `approval.proposal.approved` (outcome=granted), `approval.proposal.rejected` (outcome=rejected), or `approval.proposal.timed_out` (outcome=timeout). Event names follow the slice-2 convention `<context>.<entity>.<action>`. The events are the trading bounded context's signal to advance the proposal lifecycle (T2/T4 will subscribe).

#### Scenario: Approved decision triggers exactly one approved event

- **WHEN** an `approval_decisions` row with `outcome='granted'` is committed
- **THEN** the MessageBus receives exactly one `approval.proposal.approved` event with payload `{proposal_id, decision_id, decided_at, decided_by_user_id, decided_via_channel}`
- **AND** subscribers process the event in FIFO order per slice-2 contract

#### Scenario: Rejected decision does NOT emit `approved` event

- **WHEN** an `approval_decisions` row with `outcome='rejected'` is committed
- **THEN** the MessageBus receives exactly one `approval.proposal.rejected` event
- **AND** zero `approval.proposal.approved` events are emitted

### Requirement: Channels fan out approval requests in parallel with per-channel failure isolation

The system SHALL fan out a new `approval_requests` row to all channels in `delivered_to_channels` via `asyncio.gather(*[c.deliver_request(...) for c in channels], return_exceptions=True)` (FR32). Per-channel delivery failures SHALL NOT abort delivery to the other channels. Failed deliveries SHALL emit structlog `approval.channel.<channel>.delivery_failed` and append the failure to `approval_requests.delivery_failures` (JSON list); the request SHALL still resolve via whichever channel responds first.

#### Scenario: Hermes delivery fails but Telegram succeeds

- **GIVEN** an `approval_requests` row targeting `["telegram", "whatsapp"]`
- **WHEN** Hermes raises a transient error during `deliver_request` and Telegram succeeds
- **THEN** structlog event `approval.channel.whatsapp.delivery_failed` is emitted with `error_class` + `module`
- **AND** the request is still pending (not failed) and the user can decide via Telegram
- **AND** when the user decides via Telegram, the decision is recorded and the request resolves normally

### Requirement: 17 commands are enumerated with correct role + idempotency-source metadata

The system SHALL define exactly 17 entries in the canonical command registry, each with the correct `required_role` and `idempotency_key_source` per the design D2 table. The registry SHALL be the single source of truth for `/help` content rendering.

#### Scenario: `/help` renders the registry's description field

- **WHEN** any authorized sender issues `/help`
- **THEN** the response lists all 17 commands with their `description_md` text in the order defined by the registry
- **AND** the response is identical (modulo formatting) across Telegram, WhatsApp, and dashboard channels

#### Scenario: Registry contract test enumerates all 17 with required metadata

- **WHEN** the unit test `test_command_registry_completeness` runs
- **THEN** `len(COMMANDS) == 17`
- **AND** the set of command names equals `{"/approve", "/reject", "/halt", "/resume", "/status", "/positions", "/equity", "/strategies", "/risk", "/override", "/cost", "/budget", "/help", "/whoami", "/lock", "/unlock", "/logout"}`
- **AND** `/halt`, `/resume`, `/override`, `/budget`, `/lock`, `/unlock` have `required_role="admin"`; the remaining 11 have `required_role="user"`
- **AND** `/approve` and `/reject` have `idempotency_key_source="request_id"`; `/halt`, `/resume`, `/lock`, `/unlock` have `idempotency_key_source="payload"`; read-only commands have `idempotency_key_source="none"`
