## Context

Slice P1 lands the **approval bounded context** in Wave 2. Cumulative state at slice-P1 start:

- Slice 1-3 (Wave 0) — monorepo, `shared-primitives` (HeartbeatMixin + canonical backoff `[3, 6, 12, 24, 48]` + IguanaError hierarchy + MessageBus), persistence with tenant + append-only listeners. `authorized_senders` table already shipped in `0001_initial_schema.py`.
- Slice 4 — auth surface (`/login`, `/me`, JWT cookie); the dashboard side of approval will reuse the same auth dep.
- Slice 5 — RFC 7807 global handler, dynamic route/SSE/CLI discovery, OpenAPI typegen pipeline. P1 is the first concrete consumer of all three.
- Wave 2 siblings: K1 (risk) lands `kill_switch_state` + `kill_switch_events`; T1 (trading) lands `trade_proposals`. P1 reads both at the boundary (commands `/halt`, `/resume` write K1's events; `/approve` reads `trade_proposals.id` and writes the approval rows). Merge order `K1 → P1` per the brief.

The architectural challenge is **two transports, one logic surface**. Telegram and Hermes/WhatsApp present different inbound payload shapes (Telegram updates JSON vs Meta Cloud API webhook JSON), different idempotency tokens (`callback_query_id` vs `interactive_id`), and different reconnect semantics (Telegram long-polling getUpdates vs Meta webhook + outbound HTTP). But the 17 commands MUST be byte-for-byte identical at the user level (FR37) and the audit trail MUST be uniform regardless of channel (`approval_decisions.decided_via_channel`).

The answer is a **command_handler** dispatcher: each transport adapter is a thin layer that (1) verifies the sender, (2) normalises the inbound payload to a canonical `IncomingCommand` shape, (3) hands off to a single registry of 17 handlers, and (4) renders the response back to its native wire format. The transports inherit `HeartbeatMixin` for connection-lifecycle invariants and use canonical `backoff_seconds` for retries — neither reimplements either.

Resilience is the second-order concern. Both adapters MUST survive transient drops without losing pending approval requests (NFR-I5/I6). The `HeartbeatMixin` state machine plus the canonical backoff schedule is the contract; channels just plug in `_send_heartbeat` (probe the wire) and `_on_disconnect` (flush in-flight callbacks + emit alert). Pending requests live in the database (the `approval_requests` row exists regardless of whether the channel is connected); on reconnect, the adapter resumes long-polling and any decisions arriving for already-expired requests are auto-converted to `timeout` outcome by the timeout sweeper.

## Goals / Non-Goals

**Goals:**
- Plant the multichannel approval surface so the FR12 / FR13 / FR31-38 contract is enforceable end-to-end inside the slice (without real wire clients).
- Make the 17-command list a single-file enumeration that both channels iterate — no per-channel command drift possible.
- Reuse `HeartbeatMixin` + canonical backoff verbatim — channels MUST NOT reimplement either; deviation requires an ADR.
- Append-only audit per FR48 (decision granted/rejected/timeout with channel + latency); first-decision-wins via DB UNIQUE constraint.
- Cross-context event emission so trading (T2/T4) can pick up approved proposals without polling.
- Authorized-sender enforcement that drops silently (no echo) per the PRD account-takeover row + NFR-S3.

**Non-Goals:**
- Real `python-telegram-bot` or `hermes-client` wiring — D8 defers to a follow-up slice.
- Template approval flow for Meta WhatsApp (NFR-I6 second clause is launch-checklist territory).
- SvelteKit dashboard pages — slice W1 consumes the API surface this slice exposes.
- The `/override` reason-text storage + double-confirm semantics — owned by K1; P1 routes the command + chains the prompts but the audit row lives in K1's `risk_overrides`.
- Outbound proactive alerts (Tier 1/2/3 origination) — slice O2 owns the scheduler + filter; P1 owns the delivery surface that O2 invokes via the same channel adapters.
- Multi-tenant fan-out load testing — out of MVP perf goals.
- HTTPS termination, webhook signature verification (Meta) — deferred until real-client slice; the stub Port exposes a `verify_signature` hook for future use.

## Decisions

### D1. Channel abstraction via `ChannelPort` interface; both Telegram + WhatsApp/Hermes implement, both inherit `HeartbeatMixin`

**Decision**: define `apps/api/src/iguanatrader/contexts/approval/channels/base.py::ChannelPort(HeartbeatMixin)` as an abstract base class with three abstract methods: `async deliver_request(request: ApprovalRequest, recipient: AuthorizedSender) -> None`, `async start_listening(handler: CommandHandler) -> None`, and `async stop() -> None`. Telegram and Hermes/WhatsApp adapters subclass it; both inherit `HeartbeatMixin` transitively + override its `_send_heartbeat` / `_on_disconnect`. The service holds a `list[ChannelPort]` and fans out via `asyncio.gather(*[c.deliver_request(...) for c in channels])` (FR32 parallel delivery).

**Alternatives considered**:
- **Per-channel service (no shared port)**: each channel has its own service. Rejected — duplicates fan-out logic + makes adding a third channel (Slack? SMS?) a new service file each time.
- **Inheritance from a common base class but no formal Port**: works for the two adapters today but provides no type-checked seam for the stub-vs-real swap (D8). A `Protocol`-typed Port lets tests inject a `FakeChannelPort` that implements the same surface without a network.

**Rationale**: Ports are how the rest of the codebase (slice 2's `BrokerPort`, `StrategyPort`, etc.) handles multi-implementation. Same pattern. Fan-out is `asyncio.gather` over a list of Ports — no per-transport branching in the service.

### D2. Single 17-command registry in `channels/commands/__init__.py`; channels iterate, never enumerate

**Decision**: the canonical 17 commands live in one file as `COMMANDS: Mapping[str, CommandSpec]` where `CommandSpec` is a frozen dataclass with `name: str`, `handler: Callable[[CommandContext], Awaitable[CommandResult]]`, `required_role: Literal["admin", "user"]`, `idempotency_key_source: Literal["payload", "request_id", "none"]`, `description_md: str` (used by `/help`), and `arg_parser: Callable[[str], dict] | None`. The `command_handler` dispatcher receives an `IncomingCommand(command_name, raw_args, sender, channel, idempotency_key)`, looks up `COMMANDS[command_name]`, validates role + idempotency, calls `handler(ctx)`, returns the `CommandResult`. Both Telegram and WhatsApp adapters call into this dispatcher. Adding a command = appending to the dict + writing one handler function — zero edits to either transport adapter.

**The 17 commands** (PRD §FR-list + slice doc):

| # | Command | Required role | Side-effect target |
|---|---|---|---|
| 1 | `/approve <request_id?>` | user | `approval_decisions` row, `approval.proposal.approved` event |
| 2 | `/reject <request_id?> [reason]` | user | `approval_decisions` row, `approval.proposal.rejected` event |
| 3 | `/halt [reason]` | admin | `kill_switch_events` row (via K1 service) |
| 4 | `/resume` | admin | `kill_switch_events` row (via K1 service) |
| 5 | `/status` | user | read-only fold of trading + risk + approval state |
| 6 | `/positions` | user | read-only `trades WHERE state='open'` |
| 7 | `/equity` | user | read-only latest `equity_snapshots` |
| 8 | `/strategies` | user | read-only `strategy_configs` (active per tenant) |
| 9 | `/risk` | user | read-only fold of `risk_evaluations` + caps |
| 10 | `/override <reason ≥20 chars>` | admin | `risk_overrides` row (via K1 service) |
| 11 | `/cost` | user | read-only fold of `api_cost_events` (current month) |
| 12 | `/budget` | admin | reads + sets per-tenant monthly cap (slice O1 owns the table) |
| 13 | `/help` | user | renders the registry's `description_md` |
| 14 | `/whoami` | user | read-only echo of caller's `users.email` + `authorized_senders.display_name` |
| 15 | `/lock` | admin | sets `tenants.feature_flags.approvals_paused=true` (no new requests; existing decided in-place) |
| 16 | `/unlock` | admin | clears the same flag |
| 17 | `/logout` | user | invalidates the JWT for the dashboard side; on Telegram/WhatsApp it's a no-op acknowledgement (channel auth is `authorized_senders` whitelist, not session-based) |

**Alternatives considered**:
- **Per-channel command list**: drift guaranteed; FR37 violated.
- **Class-based dispatcher with method-name = command-name**: works but loses the rich `CommandSpec` metadata (role, idempotency-source, help-text); `/help` would need reflection. Rejected for explicitness.

**Rationale**: data-driven > polymorphism for a closed enumeration. The registry is also what `tests/unit/contexts/approval/test_command_dispatcher.py` parameterises over for the "all 17 commands have authorized-sender enforcement + idempotency check" property.

### D3. `HeartbeatMixin` inheritance + canonical backoff `[3, 6, 12, 24, 48]` — channels MUST NOT reimplement

**Decision**: both `TelegramChannel` and `HermesWhatsAppChannel` inherit `HeartbeatMixin` (slice 2). They override only `_send_heartbeat` (transport-specific probe — Telegram: `getMe`; Hermes: Meta `/me` health endpoint via the facade) and `_on_disconnect` (transport-specific cleanup — flush pending callbacks + emit `approval.channel.<channel>.disconnected` structlog). The `reconnect_loop` from the mixin is used as-is; it walks `backoff_seconds(attempt, with_jitter=True)` from slice 2. No channel imports `time.sleep` or `asyncio.sleep` directly with hardcoded numbers. Deviation = ADR.

**Alternatives considered**:
- **Per-channel reconnect logic** (Telegram has `python-telegram-bot.Application.start_polling` which handles its own retries): would short-circuit the `HeartbeatMixin` contract and make the integration tests untestable without booting the real client. Rejected.
- **Tunable backoff per channel**: explicit non-goal in slice 2 (NFR-R7). Rejected.

**Rationale**: NFR-I5/I6 is "reconnects automatically without losing pending messages". `HeartbeatMixin` already encodes the state machine that proves this; reuse it. The integration tests `test_telegram_resilience.py` + `test_hermes_resilience.py` simulate the drop by calling `await channel.mark_disconnected()` then asserting the reconnect_loop converges within 90s walltime (jittered worst case ≤ ~58s for the first 5 attempts).

### D4. Idempotency keys per command — `/approve` and `/reject` deduplicate via DB UNIQUE on `approval_decisions.request_id`

**Decision**: every command that mutates state carries an `idempotency_key`. For `/approve` and `/reject` the key is the `request_id` itself (the table has `uq_approval_decisions_request_id`; first INSERT wins, second raises `IntegrityError` which the service catches and returns a `ApprovalAlreadyDecidedError(409)` rendered as RFC 7807). For `/halt`, `/resume`, `/lock`, `/unlock` the key is `(command_name, sender_id, minute_bucket(now))` — a sender hammering `/halt` 3 times in 30s only triggers one event. For `/override` the key is `(proposal_id, sender_id)`. Read-only commands (`/status`, `/positions`, `/equity`, `/strategies`, `/risk`, `/cost`, `/budget`, `/help`, `/whoami`, `/logout`) skip the check.

**Alternatives considered**:
- **Application-level cache (Redis / in-memory)**: another moving piece; adds a dependency just for dedup. Rejected — the DB UNIQUE constraint is the source of truth anyway.
- **No idempotency**: at-least-once delivery from Telegram callback queries causes double-decisions (the user clicks "Approve" twice; both fire). Rejected — violates audit invariant.

**Rationale**: the database already serialises writes against the UNIQUE constraint; doing dedup at any other layer is duplicative. The race is exactly one INSERT, the loser raises, the service maps to a 409 + idempotent response (returns the original decision row).

### D5. Append-only `approval_decisions` audit table — UPDATE/DELETE forbidden via slice-3 listener

**Decision**: both new tables register `__tablename_is_append_only__ = True` so the slice-3 `append_only_listener` rejects UPDATE/DELETE. `approval_requests` rows mutate only insofar as the row's lifecycle is "created → never modified again"; decisions come via separate `approval_decisions` rows. Timeout outcomes are recorded by a periodic sweeper (slice O2's scheduler) writing a `approval_decisions` row with `outcome='timeout'`, `decided_via_channel='timeout'`, `decided_by_user_id=NULL`, `decided_by_sender_id=NULL`, `latency_ms = expires_at - created_at`. Only one row per request_id is allowed (UNIQUE).

**Alternatives considered**:
- **Mutable `approval_requests.status` column** (`pending|granted|rejected|timeout`): the data model says no. The fold-from-events pattern is the convention (slice 3 §1.3 + the existing `kill_switch_state` precedent).
- **Soft-delete column**: not applicable to append-only.

**Rationale**: PRD FR48 ("System persists every approval decision (granted / rejected / timeout) with channel and latency"); the data model §3.4 enforces it. Append-only + first-write-wins is the audit invariant.

### D6. `authorized_senders` enforcement at the channel boundary; non-whitelisted senders dropped silently

**Decision**: every inbound update at the transport layer (before dispatcher) runs `repository.is_sender_authorized(tenant_id, channel, external_id)` which checks the `authorized_senders` table for `enabled=TRUE`. On miss: emit structlog `approval.channel.sender_rejected` with `channel + external_id_hashed + tenant_id` and return without echoing — no error message back to the unauthorized sender. The PRD account-takeover row + NFR-S3/S4 require this exact behaviour: log + ignore, never reply (avoids enumeration / probing). The `tenant_id` lookup happens via the bot token (each tenant's Telegram bot token + WhatsApp phone number ID is stored encrypted per slice O1's secrets table; for this slice a single-tenant default is acceptable since slice 3's `0001_initial_schema.py` seeds one tenant).

**Note on storage**: the brief mentions "users.authorized_senders JSON column slice 3 planted". The authoritative data model (`docs/data-model.md` §2 + §1.3) instead defines `authorized_senders` as a **separate mutable table** with `(tenant_id, channel, external_id, enabled)` — slice 3's `0001_initial_schema.py` shipped this table. P1 reads from it. If a JSON column on `users` is desired in addition (denormalised for fast reads), it's a v2 micro-optimisation; this slice uses the canonical table.

**Alternatives considered**:
- **Echo "you are not authorized"**: enables enumeration of valid bot tokens by attackers + reveals the bot's presence. Rejected per the PRD.
- **Per-command authorization** (some commands open to all): no commands are open; every command requires whitelisting. Slack-style "anyone in the channel can read /help" is rejected because the bot is a private 1:1 surface — there is no public channel.

**Rationale**: NFR-S3 + NFR-S4 + the PRD threat-model row are aligned; this is the only behaviour that satisfies all three.

### D7. Cross-context events on the slice-2 MessageBus — `approval.proposal.{approved,rejected,timed_out}`

**Decision**: on every successful `approval_decisions` INSERT, the service publishes one event to the MessageBus:

- `approval.proposal.approved` — `payload: {proposal_id, decision_id, decided_at, decided_by_user_id, decided_via_channel}`. Trading service (T2/T4) subscribes; this is the trigger to call `BrokerPort.place_order(proposal)`.
- `approval.proposal.rejected` — `payload: {proposal_id, decision_id, decided_at, reason?}`. Trading service marks proposal terminal; observability records the rejection.
- `approval.proposal.timed_out` — `payload: {proposal_id, request_id, expired_at}`. Trading service marks proposal auto-discarded (FR13).

Event names follow the slice-2 convention `<context>.<entity>.<action>`. The slice-2 MessageBus guarantees FIFO ordering per subscriber; idempotency is the consumer's responsibility (T2/T4 will use `proposal_id` as the dedup key).

**Alternatives considered**:
- **Direct service call** (`from contexts.trading import service; service.execute_approved(proposal_id)`): violates bounded-context isolation; creates a hard coupling that ruins parallel slice testing. Rejected — slice 2's MessageBus exists exactly to avoid this.
- **Polling**: trading service polls `approval_decisions` every N seconds. Latency goes up; no need given the bus exists.

**Rationale**: the cross-context contract is the bus. Every Wave 2 slice agrees on the event vocabulary (this slice publishes; T2/T4 consume). Wire format: dataclass payloads, JSON-serialisable for SSE replay.

### D8. Channel I/O stubbed via `ChannelTransportPort` — real Telegram + Hermes clients deferred to follow-up slice

**Decision**: `apps/api/src/iguanatrader/contexts/approval/channels/transports/{base,fakes}.py` defines `ChannelTransportPort` (abstract: `async send_message(recipient, content) -> MessageId`, `async fetch_updates() -> list[IncomingCommand]`, `async health_check() -> bool`) plus `FakeTelegramTransport` + `FakeHermesTransport` that drive integration tests in-memory (no network). The `TelegramChannel` and `HermesWhatsAppChannel` adapters consume the Port; the production adapters point at real clients in a **follow-up slice** (`approval-channels-real-clients`, post-Wave-2). Slice P1 ships only the fakes. The slice's integration tests, the dispatcher, the heartbeat resilience tests, and the audit invariants are all exercised through the fakes.

**Alternatives considered**:
- **Add `python-telegram-bot` + Hermes facade now**: introduces two heavyweight runtime deps, two sets of credentials in CI, and Meta API approval workflow into a Wave 2 slice that is meant to land in parallel with K1 + O1. Rejected — too much surface in one slice.
- **Half-and-half**: real Telegram, fake Hermes. Inconsistent + still requires Telegram bot test credentials in CI. Rejected.
- **No Ports — channels use stub `httpx.MockTransport` directly**: works for tests but leaks the test seam into production code paths. Rejected.

**Rationale**: Ports are the established seam (slice 2 D6 + the existing `BrokerPort` precedent in T1's planned design). Stub-now-real-later is a deliberate scope choice that keeps Wave 2 fast: the contract is exercised end-to-end in tests; the real wire client is a 1-2 day follow-up slice that swaps the implementation behind the same Port. The decision is recorded here so reviewers know the deferral is intentional, not an oversight. Documented in `docs/gotchas.md` as a known follow-up.

## Risks / Trade-offs

- **[Risk] D8 stub means the slice ships zero real wire integration** → the contract-level guarantees (idempotency, audit, heartbeat) are tested but the actual Telegram bot or Meta webhook wiring is unproven until the follow-up slice. **Mitigation**: the follow-up slice is scoped tightly (one file per transport — drop-in real client behind the existing Port) and tracked in the project README's "post-Wave-2 follow-ups" section.

- **[Risk] FR32 fan-out (parallel delivery to all channels) means a partial failure is possible — Telegram delivers, Hermes errors out** → the user might approve via the channel that received but never sees the Hermes notification at all. **Mitigation**: `asyncio.gather(..., return_exceptions=True)` collects per-channel results; failures emit structlog `approval.channel.<name>.delivery_failed` + are added to a `delivery_failures` JSON field on the `approval_requests` row. The decision still resolves on whichever channel responded. Documented as gotcha.

- **[Risk] `/halt` + `/resume` cross-cutting into K1's bounded context** → the brief specifies merge order `K1 → P1` exactly because P1's command_handler imports `iguanatrader.contexts.risk.service`. **Mitigation**: this is the only cross-context import P1 introduces; the service-level call goes through K1's public API (no deep import). If K1 isn't merged first, P1's CI fails on `ImportError` at boot — loud, not silent.

- **[Risk] The 17-command registry grows** → adding command #18 in a future slice means editing this slice's `commands/__init__.py`. That's one file, a multi-PR conflict risk. **Mitigation**: the registry uses a sub-registry pattern internally — each command lives in its own module under `commands/<name>.py` exporting `SPEC: CommandSpec`, and `commands/__init__.py::COMMANDS = {m.SPEC.name: m.SPEC for m in pkgutil.iter_modules(...)}`. Same anti-collision pattern as routes/SSE/CLI. New command = new file. Documented in D2's implementation note.

- **[Risk] The append-only listener fires on test fixture inserts** → setup of `approval_requests` for tests is fine (INSERT-only), but tests that set up "an already-decided request" via raw SQL bypass might collide with the listener. **Mitigation**: tests use the service path consistently — no raw SQL for approval domain. The slice-3 listener exempts no path; this is the right default.

- **[Trade-off] D6 silent-drop of unauthorized senders is a UX cost** — a legitimate user who's not yet whitelisted sees no response and may think the bot is dead. **Cost accepted**: the PRD threat-model row makes this an explicit security choice. Operational doc (gotchas + runbook): "if the bot doesn't respond to your message, ask the admin to add your Telegram ID / phone to `authorized_senders`".

- **[Trade-off] D7 emits 3 distinct event names rather than one with a `kind` field** — costs a bit of subscriber glue (T2/T4 register 3 handlers instead of one) but each event has different payload shape (timed_out lacks `decided_by_user_id`); discriminated unions in the message bus would force a single payload type with many `Optional` fields. The 3-name pattern is consistent with the slice-2 convention (`<context>.<entity>.<action>`).

- **[Trade-off] D8 (stub-only) means the integration tests don't exercise actual wire-level idempotency** — Telegram's at-least-once `callback_query_id` semantics are emulated by the fake but real-world drift is possible. **Cost accepted**: the follow-up slice that wires real clients owns the wire-level acceptance test. P1's tests cover everything *up to* the wire boundary.

## Migration Plan

This slice has no live deployment to migrate from. Deployment path:

1. Merge slice K1 first (provides `kill_switch_state` + `risk_overrides` + `iguanatrader.contexts.risk.service` public API).
2. Merge slice P1: migration `0005_approval_tables.py` runs (creates two tables); auto-discovery picks up `routes/approvals.py` + `sse/approvals.py` + `cli/approval.py`; typegen pipeline regenerates `packages/shared-types/src/index.ts` to include `ApprovalRequest` + `ApprovalDecision` interfaces.
3. Operator step: ensure each tenant has at least one `authorized_senders` row before any user attempts `/approve` (if seeding is empty, all inbound commands silent-drop — by design).
4. Slice T2/T4 follow-on: the trading service subscribes to the three new MessageBus events + drives broker order placement on `approved`.
5. Slice W1 follow-on: the dashboard `/approvals` page consumes the SSE + REST endpoints.
6. Follow-up slice `approval-channels-real-clients`: swap the `FakeTelegramTransport` + `FakeHermesTransport` for the real implementations behind the same Port.

Rollback = revert the migration (`alembic downgrade -1`) + revert the PR. Append-only tables are dropped; no data loss because they're empty until users start hitting them.

## Open Questions

- **Q**: Should P1 ship a dashboard-channel `ChannelPort` adapter (so `/approvals/{id}/approve` HTTP POST also flows through `command_handler` for uniformity)? **Tentative answer**: yes — `DashboardChannel` is the third `ChannelPort` implementation; the route is a thin shim that constructs an `IncomingCommand(command_name='/approve', ..., channel='dashboard', sender=user_from_jwt)` and calls into the dispatcher. Decision audit row gets `decided_via_channel='dashboard'`. Confirmed: include this in the slice (it's tiny).

- **Q**: What about the `decided_by_sender_id` column when the channel is `dashboard`? **Tentative answer**: NULL (the FK constraint allows it; data model says "populated when channel = telegram/whatsapp"). The `decided_by_user_id` is populated instead. Documented in spec scenario.

- **Q**: Does timeout-sweep run inside this slice, or wait for O2's scheduler? **Tentative answer**: this slice ships a `service.sweep_expired_requests()` callable + a CLI command `iguanatrader approval sweep-expired` that an operator can run manually; O2's scheduler will invoke the same callable on a cron later. P1 does NOT ship its own scheduler. Two-step migration is fine.

- **Q**: Where does the `TelegramChannel`'s tenant routing happen — one bot per tenant or one bot multiplexed? **Tentative answer**: MVP is one bot per tenant (token stored encrypted per slice O1's secrets); the channel adapter is instantiated per-tenant at app boot. Multi-tenant multiplexing on a single bot is v2+. This slice's channel adapter takes `tenant_id` at construction.
