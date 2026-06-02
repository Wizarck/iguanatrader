## 1. Data model — owner role on authorized_senders

- [ ] 1.1 Add `role` column to the `AuthorizedSender` ORM model (`persistence/models.py`): `Mapped[str]`, `nullable=False`, `server_default="user"`.
- [ ] 1.2 Add a forward migration: `ALTER TABLE authorized_senders ADD COLUMN role` with `NOT NULL DEFAULT 'user'` and `CHECK (role IN ('user','owner'))` (SQLite `batch_alter_table` + Postgres path); downgrade drops the column.
- [ ] 1.3 Repository accessor to load an enabled sender by `(tenant_id, channel, external_id)` returning the row incl. `role` (extend the existing authorized-sender lookup used by the channel adapters).
- [ ] 1.4 Unit test: migration backfills pre-existing rows to `role='user'`; CHECK rejects an out-of-domain value.

## 2. MCP channel adapter — identity revalidation + role resolution

- [ ] 2.1 Add a shared helper `resolve_operator_sender(db, tenant_id, channel, external_id)` that fetches the enabled `authorized_senders` row or returns "denied" (no row / disabled).
- [ ] 2.2 Map the row to `IncomingCommand`: set `channel`, `sender_external_id`, `tenant_id`, `sender_db_id`, and `role = "admin" if row.role == "owner" else "user"` (payload role ignored).
- [ ] 2.3 Bind `tenant_id_var`/`with_tenant_context` around the dispatch call (the MCP route is the adapter boundary).
- [ ] 2.4 Pass the Hermes callback id from the payload as `IncomingCommand.idempotency_key`.
- [ ] 2.5 Enforce the owner gate at the MCP action surface: if the resolved sender's `role != 'owner'`, deny the action tool before dispatch (all action tools are owner-only per Gate E "owner siempre").
- [ ] 2.6 Unit tests: unknown/disabled sender → denied with no side effect and no proposal echo; `owner` row → `role=="admin"`; non-owner → denied on every action tool; payload-asserted role is ignored.

## 3. Action tools on the MCP REST surface

- [ ] 3.1 Add request/response DTOs (`extra="forbid"`) for `approve_proposal`, `reject_proposal`, `halt_trading`, `resume_trading`, `lock`, `unlock` — each carrying `channel`, `external_id`, and the action-specific fields (`request_id`, `reason`).
- [ ] 3.2 Add `@router.post` handlers mirroring the existing tool pattern (`dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)]`); each builds the `IncomingCommand` via §2 and calls `command_handler.dispatch()` with the mapped command name (`/approve`, `/reject`, `/halt`, `/resume`, `/lock`, `/unlock`).
- [ ] 3.3 Register the new tools in `_TOOL_SPECS` with input schemas.
- [ ] 3.4 Map `CommandResult.status` → HTTP: `ok`→200, `denied`→403, `unknown_command`→400, `ApprovalExpiredError`→410, not-configured→503.
- [ ] 3.5 Integration tests: owner approve happy path (200 + decision recorded); non-owner approve → 403 AND non-owner halt → 403; expired approve → 410; paused approve (`/lock` active) → denied; duplicate-callback approve → single execution.

## 4. list_pending_approvals read tool

- [ ] 4.1 Add `list_pending_approvals` DTO + `@router.post` handler returning pending requests for the configured tenant with proposal summary + expiry.
- [ ] 4.2 Register in `_TOOL_SPECS`.
- [ ] 4.3 Test: two pendings returned; cross-tenant request excluded.

## 5. Enriched outbound approval notification

- [ ] 5.1 Modify `build_outbound_message_from_request` (`contexts/approval/dispatcher.py`) to load the `TradeProposal` and render symbol/side/quantity/indicative-entry/stop/expiry into the body.
- [ ] 5.2 Test: the message body sent to the Hermes adapter contains all six fields.

## 6. Follow-up pushes — execution + close-out

- [ ] 6.1 Subscribe an `OrderFilled` handler that resolves the proposal's authorised senders and pushes an execution-confirmation message (`✅ ejecutado: …`) via `HermesWhatsAppMessageDispatcher.send`.
- [ ] 6.2 Subscribe a `TradeClosed` handler that pushes a close-out message carrying realized P&L (`🔚 … cerrado: +$X / +Y%`) to the same senders.
- [ ] 6.3 Wire both subscribers in the daemon/bus bootstrap (per-event session, consistent with audit #29).
- [ ] 6.4 Tests: `OrderFilled` → one execution-confirmation push; `TradeClosed` → one close-out push with the realized P&L.

## 7. Reverse the documented exclusion + docs

- [ ] 7.1 Update the `mcp.py` module docstring (lines ~38-46) and the `mcp_tools.py` registry comment: approve/reject ARE exposed, gated by per-operator `AuthorizedSender` revalidation (remove the "not exposed" rationale).
- [ ] 7.2 Note in the docstring that the service bearer token alone never authorises a money action (Layer 1 vs Layer 2).

## 8. Config & secrets (no repo content)

- [ ] 8.1 Document the required env in the deploy notes: `IGUANATRADER_MCP_TOKEN`, `IGUANATRADER_MCP_TENANT_SLUG`, `HERMES_BASE_URL`, `HERMES_HMAC_SECRET` (all via SOPS).
- [ ] 8.2 Document the seed step: seed the operator's **Telegram** chat id first (Gate E OQ1) as one `authorized_senders` row (`role='owner'`, `enabled=true`); WhatsApp is a later seed via the same path — data, not committed.
- [ ] 8.3 Confirm `gitleaks` stays green (no token/secret in any tracked file).

## 9. Validation & gate

- [ ] 9.1 `openspec validate mcp-hitl-approvals --strict` passes.
- [ ] 9.2 Full required-check parity locally where possible (ruff + black + mypy --strict on touched files; pytest for new tests).
- [ ] 9.3 Update `docs/openspec-slice.md` to register `mcp-hitl-approvals` as a net-new slice depending on P1 `approval-channels-multichannel` + MCP surface (B).
