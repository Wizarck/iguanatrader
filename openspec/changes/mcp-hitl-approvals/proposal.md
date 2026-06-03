## Why

The operator wants a hands-off, messaging-driven workflow: iguanatrader contacts them on WhatsApp/Telegram and they approve or halt from the phone — never touching the CLI or the dashboard. The chosen topology is **Hermes** (external gateway that already owns the WhatsApp + Telegram connections via its own plugins) talking to iguanatrader over the **MCP REST surface**. But today that loop is impossible to close: the MCP surface **deliberately excludes** approve/reject ([mcp.py:44-46](../../../apps/api/src/iguanatrader/api/routes/mcp.py#L44-L46)), and the native channel transports are stubs (only `FakeTelegramTransport`/`FakeHermesTransport` exist, no real wire client, `start_listening` never runs in the daemon). So Hermes can be told a proposal exists but has **no path to execute the operator's decision**. This change exposes the human-in-the-loop actions on the MCP REST surface **without weakening the HITL trust boundary**, by requiring the operator's verified channel identity on every action and revalidating it against `AuthorizedSender`.

## What Changes

- Add **MCP REST action tools** under `/api/v1/mcp/tools/*` (same bespoke-REST shape as the existing `explain_proposal`/`risk_review` tools — JSON-RPC framing stays out of scope per the operator's confirmed Hermes-consumes-REST contract):
  - `approve_proposal`, `reject_proposal` — gate a pending `ApprovalRequest`.
  - `halt_trading`, `resume_trading` — operator kill-switch over the channel (**Kill-switch obligatorio** — must reach `RiskService` with a durable commit).
  - `lock`, `unlock` — pause/resume new approvals (`approvals_paused`).
- Every action tool **requires the operator's `channel` + `external_id`** in the payload (supplied by Hermes, which identifies the WhatsApp/Telegram sender). The handler builds an `IncomingCommand` and feeds the **existing** `command_handler.dispatch()` — reusing the `AuthorizedSender` whitelist, role-pinning (audit #32), tenant-scoping (audit #33), and idempotency. **No approval logic is duplicated; the trust boundary moves transport, not enforcement.**
- Add **MCP read tool** `list_pending_approvals` so Hermes can answer "what needs my approval?".
- **Enrich the outbound notification**: when a proposal needs approval, push a message to Hermes (the existing `HermesWhatsAppMessageDispatcher` → `POST {HERMES_BASE_URL}/messages`, option-1 push, already half-built) carrying symbol / side / quantity / entry / stop / expiry — not just the bare `proposal_id`.
- **Reverse the documented exclusion** in `mcp.py`/`mcp_tools.py` ("approve/reject not exposed") with the new, security-preserving rationale (per-operator revalidation).
- Config only (no secrets in repo): populate `IGUANATRADER_MCP_TOKEN` + `IGUANATRADER_MCP_TENANT_SLUG` via SOPS, and seed one `AuthorizedSender` row for the operator's WhatsApp number / Telegram chat id.
- **NOT** changing: the read-only MCP routes, the native channel adapters (left as-is; this change does not build the stubbed transports), JWT/dashboard approval path, or the MCP JSON-RPC roadmap item.

## Capabilities

### New Capabilities
- `mcp-hitl-actions`: human-in-the-loop control actions (approve, reject, halt, resume, lock/unlock, list-pending) exposed on the MCP REST surface for an authenticated external gateway (Hermes), with per-operator identity revalidation against `AuthorizedSender` and reuse of the existing approval command dispatch.

### Modified Capabilities
<!-- The approval-channels (P1) and mcp-read surfaces ship in code but are not yet promoted to openspec/specs/ (only compliance-baseline, monorepo-tooling, persistence-layer, secrets-baseline are archived). No archived spec's REQUIREMENTS change, so no delta spec is needed. -->
(none — no archived spec capability changes its requirements)

## Impact

- **Code**: `apps/api/src/iguanatrader/api/routes/mcp_tools.py` (new action endpoints + tool registry entries), `api/routes/mcp.py` (decision-note docstring + shared auth reuse), `contexts/approval/channels/command_handler.py` (reused as the shared core — minimal/no change), `shared/channel_dispatch/adapters/hermes.py` + the approval service notification path (enriched outbound), new request/response DTOs.
- **Security (hard rules)**: HITL boundary preserved by `AuthorizedSender` revalidation (never trust the MCP service token alone for a money action); kill-switch reachable via Hermes must commit durably (audit #27); the MCP bearer token is a secret → SOPS/age, `gitleaks` must pass; execution logs stay immutable/append-only.
- **APIs**: additive REST endpoints under `/api/v1/mcp/tools/*`; existing routes unchanged; OpenAPI schema grows (shared-types regen — note the pre-existing `packages/shared-types` deletion on main is a separate, non-blocking issue).
- **Dependencies**: none new (REST only; no `fastmcp`/`mcp` SDK).
- **Config / secrets**: `IGUANATRADER_MCP_TOKEN`, `IGUANATRADER_MCP_TENANT_SLUG`, and one `AuthorizedSender` row — all environment/data, none committed.
- **External**: depends on the Hermes gateway being deployed and configured to (a) push the operator's verified `channel`+`external_id` on action calls and (b) consume the bespoke REST surface (handover line 29: "no Hermes consumer yet").
