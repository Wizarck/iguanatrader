## ADDED Requirements

### Requirement: MCP REST surface exposes HITL action tools

The system SHALL expose human-in-the-loop control tools on the MCP REST surface under `/api/v1/mcp/tools/*`, using the same bespoke-REST shape, bearer auth, and tenant binding as the existing action tools. The tools are: `approve_proposal`, `reject_proposal`, `halt_trading`, `resume_trading`, `lock`, `unlock` (actions) and `list_pending_approvals` (read). JSON-RPC framing SHALL NOT be required.

#### Scenario: Action tool is reachable with a valid bearer token

- **WHEN** an authenticated MCP client `POST`s to `/api/v1/mcp/tools/approve_proposal` with a body carrying `request_id`, `channel`, and `external_id`, and the `Authorization: Bearer` header matches `IGUANATRADER_MCP_TOKEN`
- **THEN** the request is accepted, the operator identity is revalidated (see "Per-operator identity revalidation"), and on success the response is HTTP 200 with the dispatch outcome

#### Scenario: Missing or wrong bearer token is rejected

- **WHEN** a request to any `/api/v1/mcp/tools/*` action arrives with an absent or non-matching `Authorization: Bearer` header
- **THEN** the system returns HTTP 401 and performs no approval, kill-switch, or lock side effect

#### Scenario: Surface is unconfigured

- **GIVEN** `IGUANATRADER_MCP_TOKEN` or `IGUANATRADER_MCP_TENANT_SLUG` is unset
- **WHEN** any MCP tool route is called
- **THEN** the system returns HTTP 503 (MCP not configured) and no side effect occurs

### Requirement: Per-operator identity revalidation against AuthorizedSender

The system SHALL require the operator's `channel` and `external_id` on every action tool and SHALL revalidate them against the `authorized_senders` whitelist before any decision is dispatched. An enabled `authorized_senders` row matching `(tenant_id, channel, external_id)` is mandatory. The MCP service bearer token alone SHALL NEVER authorise a money action. When no enabled row matches, the system SHALL deny the action, perform no side effect, and SHALL NOT echo proposal details.

#### Scenario: Unknown or disabled sender is denied

- **GIVEN** the payload's `(channel, external_id)` has no enabled row in `authorized_senders` for the configured tenant
- **WHEN** `approve_proposal` (or any action tool) is called with a valid bearer token
- **THEN** the system denies the action, executes nothing, logs the sender by salted hash, and returns a denial that does not reveal the proposal's symbol, side, quantity, or prices

#### Scenario: Whitelisted sender proceeds to dispatch

- **GIVEN** an enabled `authorized_senders` row exists for `(tenant_id, channel, external_id)`
- **WHEN** the action tool is called with a valid bearer token
- **THEN** the handler builds an `IncomingCommand` for that sender and invokes the existing `command_handler.dispatch()`

### Requirement: Every action tool requires the tenant owner, resolved from the database

The system SHALL resolve the operator's role from the `authorized_senders.role` column, never from the request payload, and SHALL require `role='owner'` for EVERY action tool (`approve_proposal`, `reject_proposal`, `halt_trading`, `resume_trading`, `lock`, `unlock`). The owner gate SHALL be enforced at the MCP adapter as a precondition before dispatch. A non-owner authorised sender SHALL be denied every action tool.

#### Scenario: Non-owner is denied any action

- **GIVEN** an enabled `authorized_senders` row with `role='user'`
- **WHEN** that sender calls `approve_proposal` or `halt_trading`
- **THEN** the system denies the action and performs no approval, kill-switch, or lock side effect

#### Scenario: Owner may act

- **GIVEN** an enabled `authorized_senders` row with `role='owner'`
- **WHEN** that sender calls `halt_trading` or `approve_proposal`
- **THEN** the action is dispatched (the kill-switch activates durably for halt; the decision is recorded for approve)

#### Scenario: Payload-asserted role is ignored

- **GIVEN** a request whose body or headers assert an elevated role for a sender whose DB row is `role='user'`
- **WHEN** any action tool is called
- **THEN** the system uses the database role (`user`) and denies the action

### Requirement: authorized_senders gains a role column

The system SHALL add a `role` column to `authorized_senders`, `NOT NULL DEFAULT 'user'`, constrained to `('user','owner')`. A forward migration SHALL add the column; existing rows SHALL become `user` (deny-by-default for privileged ops). The MCP adapter SHALL map `owner` to the `admin` privilege when constructing `IncomingCommand.role`.

#### Scenario: Migration backfills existing rows as user

- **WHEN** the migration that adds `authorized_senders.role` is applied to a database with pre-existing rows
- **THEN** every pre-existing row has `role='user'` and a non-null value, and the `CHECK (role IN ('user','owner'))` constraint is enforced

#### Scenario: Owner row resolves to admin privilege

- **GIVEN** an `authorized_senders` row with `role='owner'`
- **WHEN** the MCP adapter builds the `IncomingCommand` for that sender
- **THEN** `IncomingCommand.role == "admin"`

### Requirement: Reuse of the existing approval dispatch with no duplicated logic

The system SHALL route every action through `command_handler.dispatch()` and SHALL NOT duplicate approval, kill-switch, idempotency, expiry, or pause logic. The MCP path SHALL inherit the existing guards: late decisions raise `ApprovalExpiredError`, paused approvals (`/lock`) block trade-actuating commands, and the tenant-keyed idempotency window dedupes retries.

#### Scenario: Approving an expired request is rejected

- **GIVEN** an approval request whose `expires_at` is in the past
- **WHEN** `approve_proposal` is dispatched for it
- **THEN** the system surfaces `ApprovalExpiredError` (HTTP 410) and records no grant

#### Scenario: Approvals paused blocks approve

- **GIVEN** the tenant's `approvals_paused` flag is set (via `lock`)
- **WHEN** `approve_proposal` is called by an authorised sender
- **THEN** the dispatch denies the command and no execution is enqueued

#### Scenario: Duplicate call within the idempotency window executes once

- **GIVEN** an authorised owner approves a request
- **WHEN** the same approval arrives a second time carrying the same Hermes callback id within the idempotency window
- **THEN** exactly one approval decision is recorded and exactly one execution is enqueued

### Requirement: Kill-switch over the channel is durable

The system SHALL ensure that a `halt_trading` action reaches `RiskService` and commits the kill-switch activation immediately, so that a process crash or restart after the halt does not resume trading.

#### Scenario: Halt survives a restart

- **GIVEN** an owner calls `halt_trading`
- **WHEN** the activation completes and a fresh database session subsequently loads the kill-switch state
- **THEN** the kill-switch reads as active (the event row and cache were committed at activation time)

### Requirement: Enriched outbound approval notification

When an approval is requested, the system SHALL push a message to Hermes (`POST {HERMES_BASE_URL}/messages`) whose body carries the proposal's symbol, side, quantity, indicative entry price, stop price, and expiry — not only the proposal id.

#### Scenario: Approval push includes decision-relevant fields

- **WHEN** an `ApprovalRequested`/notification fanout fires for a pending proposal
- **THEN** the message body sent to Hermes contains the symbol, side, quantity, indicative entry, stop price, and expiry of that proposal

### Requirement: Notify through to execution and close-out via follow-up pushes

The system SHALL push a follow-up message to the operator when the approved proposal's order is filled (execution confirmed), and SHALL push a further message when the resulting trade closes, carrying the realized profit/loss. Both pushes SHALL go to the proposal's authorised senders.

#### Scenario: OrderFilled triggers an execution-confirmation push

- **GIVEN** a proposal was approved and its order subsequently fills
- **WHEN** the `OrderFilled` event is published
- **THEN** an execution-confirmation message is pushed to the proposal's authorised senders referencing the proposal/order

#### Scenario: TradeClosed triggers a close-out push with realized P&L

- **GIVEN** the position opened by an approved proposal subsequently closes
- **WHEN** the `TradeClosed` event is published
- **THEN** a close-out message is pushed to the proposal's authorised senders carrying the realized profit/loss

### Requirement: list_pending_approvals read tool

The system SHALL expose a `list_pending_approvals` MCP read tool that returns the pending approval requests for the configured tenant, each with a proposal summary and expiry, so Hermes can answer "what needs my approval?". Results SHALL be scoped to the configured tenant only.

#### Scenario: Pending requests are listed for the tenant

- **GIVEN** the configured tenant has two pending approval requests
- **WHEN** `list_pending_approvals` is called with a valid bearer token
- **THEN** the response lists both requests with proposal summary and expiry, and excludes any other tenant's requests

### Requirement: The documented MCP exclusion of approve/reject is reversed

The system SHALL update the `mcp.py` / `mcp_tools.py` documentation that previously stated approve/reject are not exposed, replacing it with the security-preserving rationale (per-operator `AuthorizedSender` revalidation restores the HITL boundary).

#### Scenario: Exclusion comment reflects the new contract

- **WHEN** the MCP route module docstring is read after this change
- **THEN** it no longer claims approve/reject are unexposed and instead documents that they are gated by per-operator identity revalidation

### Requirement: Configuration and secrets stay out of the repository

The system SHALL source the MCP bearer token and tenant slug from environment/SOPS, never from committed files, and SHALL keep `gitleaks` green. Seeding the operator's `authorized_senders` row (including `role='owner'`) is data/deploy, not repository content.

#### Scenario: No secret is committed

- **WHEN** `gitleaks detect --source . --no-banner` runs after this change
- **THEN** it exits 0 with no findings, and neither `IGUANATRADER_MCP_TOKEN` nor `HERMES_HMAC_SECRET` appears in any tracked file
