## 1. Data model — owner role on authorized_senders

- [x] 1.1 Add `role` column to the `AuthorizedSender` ORM model (`persistence/models.py`): `Mapped[str]`, `nullable=False`, `server_default="user"`.
- [x] 1.2 Add a forward migration (`0036_authorized_senders_role`): `ADD COLUMN role` with `NOT NULL DEFAULT 'user'` and `CHECK (role IN ('user','owner'))` (SQLite `batch_alter_table` + Postgres path); downgrade drops the column.
- [x] 1.3 Repository accessor `resolve_enabled_sender(tenant_id, channel, external_id) -> ResolvedSender | None` returning `(id, role)`.
- [x] 1.4 Test (`test_migration_0036`): migration backfills pre-existing rows to `role='user'`; CHECK rejects an out-of-domain value; round-trips.

## 2. MCP channel adapter — identity revalidation + role resolution

- [x] 2.1 `resolve_enabled_sender` fetches the enabled `authorized_senders` row or returns `None` (no row / disabled).
- [x] 2.2 Map the row to `IncomingCommand`: `role = "admin" if row.role == "owner" else "user"` (payload role ignored).
- [x] 2.3 Bind `tenant_id_var`/`session_var` around the dispatch call (the MCP route is the adapter boundary).
- [x] 2.4 Pass the Hermes callback id from the payload as `IncomingCommand.idempotency_key`.
- [x] 2.5 Enforce the owner gate at the MCP action surface: non-owner → deny before dispatch (Gate E "owner siempre").
- [x] 2.6 Tests: unknown/disabled sender → 403 no echo; non-owner → 403 on every action tool; owner reaches dispatch.

## 3. Action tools on the MCP REST surface

- [x] 3.1 Request/response DTOs (`extra="forbid"`) for the six actions, each carrying `channel`, `external_id`, action-specific fields.
- [x] 3.2 `@router.post` handlers mirroring the existing tool pattern; each builds the `IncomingCommand` via §2 and calls `command_handler.dispatch()` with the mapped command name.
- [x] 3.3 Register the new tools in the catalogue (`HITL_TOOL_SPECS`, folded into `GET /mcp/tools`).
- [x] 3.4 Map `CommandResult.status` → HTTP: `ok`→200, `denied`→403, `error`→422, `ApprovalExpiredError`→410, not-configured→503.
- [x] 3.5 Integration tests: owner approve (200 + decision recorded); non-owner approve AND non-owner halt → 403; missing request → 422; owner halt → durable kill-switch; duplicate-callback approve → single decision.

## 4. list_pending_approvals read tool

- [x] 4.1 `list_pending_approvals` DTO + `@router.post` handler returning pending requests for the configured tenant with proposal summary + expiry.
- [x] 4.2 Register in the tool catalogue.
- [x] 4.3 Test: pending request returned with proposal summary.

## 5. Enriched outbound approval notification

- [x] 5.1 `build_outbound_message_from_request` loads the `TradeProposal` and renders symbol/side/quantity/entry/stop/expiry (best-effort; sparse fallback keeps the proposal id).
- [x] 5.2 Test: enriched body contains the fields; sparse fallback keeps the proposal id; existing binding test still green.

## 6. Follow-up pushes — execution + close-out

- [x] 6.1 `ExecutionNotifier.on_order_filled` resolves the tenant's authorised senders and pushes an execution-confirmation message via the Hermes transport.
- [x] 6.2 `ExecutionNotifier.on_trade_closed` pushes a close-out message carrying realized P&L.
- [x] 6.3 Wire both subscribers in the daemon bootstrap (guarded on Hermes config).
- [x] 6.4 Tests: `OrderFilled` → execution-confirmation push; `TradeClosed` → close-out push with P&L; no-senders is a no-op.

## 7. Reverse the documented exclusion + docs

- [x] 7.1 Update the `mcp.py` module docstring and the `mcp_tools.py` registry comment: approve/reject ARE exposed (via `mcp_hitl.py`), gated by per-operator `AuthorizedSender` revalidation.
- [x] 7.2 Document the two-layer model (service token never authorises a money action alone).

## 8. Config & secrets (no repo content)

- [x] 8.1 Document the required env (`IGUANATRADER_MCP_TOKEN`, `IGUANATRADER_MCP_TENANT_SLUG`, `HERMES_BASE_URL`, `HERMES_HMAC_SECRET`) in `docs/mcp-hitl-approvals-deploy.md`.
- [x] 8.2 Document the seed step: operator's **Telegram** chat id first (Gate E OQ1), `role='owner'`, `enabled=true`.
- [x] 8.3 Confirm `gitleaks` stays green (no token/secret in any tracked file).

## 9. Validation & gate

- [x] 9.1 `openspec validate mcp-hitl-approvals --strict` passes.
- [x] 9.2 Local parity where reproducible: ruff + black green on touched files; new pytest suites green. (mypy --strict is verified by CI — the local toolchain lacks the optional SDKs.)
- [x] 9.3 Register `mcp-hitl-approvals` as a net-new slice in `docs/openspec-slice.md` (depends on P1 `approval-channels-multichannel` + MCP surface B).
