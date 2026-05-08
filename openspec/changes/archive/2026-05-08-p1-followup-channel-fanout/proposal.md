# Proposal: p1-followup-channel-fanout

> **Minimum-viable channel-fanout abstraction** (Protocol + LogOnly fallback). Wires the bus-driven `ApprovalService._approval_requested_handler` to a `ChannelDispatcher` after the audit-row INSERT. Production Telegram + Hermes push adapters are stubbed at the Protocol layer for a future operator session to fill in (when bot tokens + per-tenant chat_id config are ready).

## Why

P1-followup-bus-subscriptions (PR #104, archived 2026-05-07) shipped:

- `ApprovalService.register_subscriptions(bus)` — subscribes to `trading.ApprovalRequested`.
- `_approval_requested_handler` — INSERTs an `approval_requests` row + logs `approval.bus.request_persisted`.

But the handler does NOT push the request to Telegram / Hermes / dashboard — operators discover requests via the dashboard SSE poll (`/sse/approvals`) or via direct `POST /approvals/{id}/{approve,reject}` calls. P1's existing `ChannelPort` implementations (TelegramChannel, HermesWhatsAppChannel) are constructed by the dashboard but never invoked by the bus path.

This slice closes the gap with a `ChannelDispatcher` Protocol + a v1 `LogOnlyChannelDispatcher` adapter. The wiring exists; the production push (real Telegram bot send / real Hermes HTTP) is documented as a future operator slice when:

1. Per-tenant `chat_id` (Telegram) + `phone_number` (Hermes) config is plumbed (currently ad-hoc env vars).
2. Bot tokens + Hermes credentials are SOPS-encrypted in the per-environment `dev.env.enc / paper.env.enc / live.env.enc` bundles.

Both are ops-config tasks that don't fit into a code slice.

## What

Pure additive on `ApprovalService` + new `ChannelDispatcher` abstraction.

### `ChannelDispatcher` Protocol (`apps/api/src/iguanatrader/contexts/approval/dispatcher.py` NEW)

```python
@runtime_checkable
class ChannelDispatcher(Protocol):
    async def fanout(
        self,
        *,
        request: ApprovalRequestRow,
        channels: list[str],
    ) -> None: ...
```

`fanout` MUST NOT raise — channel failures are logged + swallowed (FR32 isolation: one bad channel must not skip the rest).

### `LogOnlyChannelDispatcher` (`apps/api/src/iguanatrader/contexts/approval/dispatcher.py`)

```python
class LogOnlyChannelDispatcher:
    async def fanout(
        self, *, request: ApprovalRequestRow, channels: list[str],
    ) -> None:
        log.info(
            "approval.channel.fanout.log_only",
            request_id=str(request.id),
            proposal_id=str(request.proposal_id),
            channels=list(channels),
            note="LogOnlyChannelDispatcher v1 — production push deferred",
        )
```

Default daemon dispatcher when `IGUANATRADER_CHANNEL_DISPATCHER` env-var is unset OR set to `"log_only"`. Future "telegram_hermes" production dispatcher constructs `TelegramChannel` + `HermesWhatsAppChannel` from env-config + iterates per `request.delivered_to_channels`.

### `ApprovalService` modification (additive)

- `__init__` accepts new optional `channel_dispatcher: ChannelDispatcher | None = None`.
- `_approval_requested_handler` calls `await self._channel_dispatcher.fanout(...)` after `create_request` IF the dispatcher is set. The fanout is wrapped in try/except (FR32: a bad dispatcher must not bring down the audit-write path).

### Daemon wiring (`cli/trading.py`)

After `approval_service = ApprovalService(...)` construction, build the dispatcher (`build_channel_dispatcher_from_env()`) and pass it:

```python
approval_service = ApprovalService(
    repository=ApprovalRepository(),
    message_bus=bus,
    channel_dispatcher=build_channel_dispatcher_from_env(),
)
```

`build_channel_dispatcher_from_env()` returns `LogOnlyChannelDispatcher()` for v1 when `IGUANATRADER_CHANNEL_DISPATCHER` is unset or `"log_only"`. Future dispatchers register here.

## Out of scope (deferred to future operator slice)

- **Production Telegram bot send**: Telegram bot token from SOPS bundle; per-tenant `chat_id` lookup; rate-limit (Telegram bot API has 30 messages/sec).
- **Production Hermes WhatsApp send**: HTTP credentials; per-tenant phone number routing; HMAC payload signing (per ADR-?? if applicable).
- **Dashboard SSE notify**: dashboard already discovers via `/sse/approvals` poll — pushing a notification *to* the dashboard SSE channel from this dispatcher is redundant.
- **Per-tenant channel config table**: env-var v1; v2 SaaS adds `tenant_channel_configs`.

These are listed in the retro carry-forward + can ship as a future operator slice when ops config is ready.

## Acceptance criteria

1. `ChannelDispatcher` Protocol declared; `LogOnlyChannelDispatcher` implements it.
2. `ApprovalService.__init__` accepts optional `channel_dispatcher`; `_approval_requested_handler` calls `fanout` after `create_request` if set.
3. Dispatcher failures (any exception) are caught + logged + do NOT raise out of the handler (FR32).
4. Daemon wires `build_channel_dispatcher_from_env()` (returns `LogOnly` for v1).
5. mypy --strict + ruff + black + pre-commit + CI green.
6. ≥3 unit tests: dispatcher called after create_request / dispatcher failure swallowed / dispatcher not called when None.

## Blast radius

- 1 archive-surface change: `ApprovalService.__init__` gains optional kwarg (additive; existing tests inject `channel_dispatcher=None` implicitly via default).
- NEW package `apps/api/src/iguanatrader/contexts/approval/dispatcher.py` (Protocol + LogOnly adapter + factory).
- 1 daemon edit: `cli/trading.py`.
- 1 NEW test file.

P1 + P1-followup archive surfaces UNTOUCHED.

## Estimated effort

~2h, ~250 LoC.
