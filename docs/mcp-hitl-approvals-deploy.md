# MCP HITL approvals — deploy & config

Enables the hands-off approval loop: iguanatrader pushes proposals to
**Hermes** (the external WhatsApp/Telegram gateway), and the operator
approves / halts from their phone. Hermes is an MCP REST client of
iguanatrader; iguanatrader never registers against Meta/Telegram.

See the design in [openspec/changes/mcp-hitl-approvals/design.md](../openspec/changes/mcp-hitl-approvals/design.md).

## 1. Environment (all via SOPS — never committed)

| Var | Purpose |
|-----|---------|
| `IGUANATRADER_MCP_TOKEN` | Static bearer for the MCP surface (Layer 1). Generate a long random token; put it in `/opt/iguanatrader/.env` and in Hermes's client config. Unset → the MCP surface returns 503. |
| `IGUANATRADER_MCP_TENANT_SLUG` | The tenant `name` the MCP surface binds every request to. |
| `HERMES_BASE_URL` | Base URL of the Hermes gateway (outbound pushes `POST {HERMES_BASE_URL}/messages`). |
| `HERMES_HMAC_SECRET` | Shared secret signing outbound pushes (`X-Signature: sha256=…`). |

The MCP token and the HMAC secret are secrets → keep them in the
SOPS/age-encrypted env files only. `gitleaks` must stay green; nothing in
this slice puts a secret in a tracked file.

## 2. Seed the operator (data, not code)

Insert one `authorized_senders` row for the operator. Gate E chose
**Telegram first**; WhatsApp is the same step with `channel='whatsapp'`.

- `channel`: `'telegram'` (the operator's Telegram chat id) — or `'whatsapp'` (E.164 phone).
- `external_id`: that chat id / phone number (the value Hermes forwards as the verified sender).
- `role`: **`'owner'`** — every HITL action tool is owner-only (Gate E "owner siempre"). A `'user'` row is whitelisted but cannot invoke any action tool.
- `enabled`: `true`.

The `role` column ships in migration `0036_authorized_senders_role`
(`NOT NULL DEFAULT 'user'`, `CHECK role IN ('user','owner')`).

## 3. Trust model (why the token alone is not enough)

1. **Layer 1 — service token.** `Authorization: Bearer <IGUANATRADER_MCP_TOKEN>`.
2. **Layer 2 — operator identity.** Every action tool revalidates the
   `channel`+`external_id` Hermes forwards against `authorized_senders`
   (enabled, correct tenant) and resolves the privilege `role` **from the
   DB** — never the request payload. A non-owner, or an unknown/disabled
   sender, is denied (403) with no proposal details echoed.

A leaked bearer token therefore still cannot move money: it is not a
whitelisted operator and cannot self-elevate to `owner`.

## 4. What the operator gets

- Approval push enriched with symbol / side / quantity / entry / stop / expiry.
- After approving: a second push on **execution** (`OrderFilled`) and a
  **close-out** push with realized P&L (`TradeClosed`) — the execution
  notifier is wired only when `HERMES_BASE_URL` + `HERMES_HMAC_SECRET` are set.
- Tools: `approve_proposal`, `reject_proposal`, `halt_trading`,
  `resume_trading`, `lock`, `unlock`, `list_pending_approvals` under
  `/api/v1/mcp/tools/*`.
