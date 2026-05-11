# Proposal: p1-channel-fanout-production

> **Generic, upstream-extractable channel-dispatch core + production Telegram + Hermes/WhatsApp adapters.** Closes the v1 gap left by `p1-followup-channel-fanout` (PR #111) where `LogOnlyChannelDispatcher` was the only adapter shipped. The new code lives in `apps/api/src/iguanatrader/shared/channel_dispatch/` with **zero domain imports** so it can be lifted out as a standalone PyPI package (or upstream PR to e.g. `apprise`) in a later mechanical move.

## Why

The 6th canonical bus-bridge follow-up (`p1-followup-channel-fanout`, PR #111, archived 2026-05-08) wired the bus path to a `ChannelDispatcher` Protocol but only shipped `LogOnlyChannelDispatcher`. Operators currently approve via dashboard SSE because no real Telegram bot send / Hermes WhatsApp HTTP push is wired. The retro flagged a future operator slice once SOPS bundles + per-tenant `chat_id` config are ready.

Both gates have moved:

1. **Per-tenant recipient resolution is already possible** — `authorized_senders.external_id` (per `(tenant_id, channel)`) already stores the Telegram chat_id / WhatsApp phone number. No new schema needed.
2. **SOPS bundle wiring is a manual ops step**, not a code blocker — the dispatcher takes credentials via constructor injection so operators wire bot tokens / Hermes HMAC keys when ready (same `DeferredProductionInstall` pattern as R6 hindsight).

The original retro framed the work as ops-blocked. Re-evaluation: **only the credential bundle is operator work**; the dispatcher core, adapters, rate-limiter, signing, and binding layer are pure code, shippable now.

This slice ships the production code with **upstream-extractable design** so that:

- Generic core (`shared/channel_dispatch/`) has no `iguanatrader.contexts.*` imports.
- Adapters take pluggable HTTP transports (`httpx.AsyncClient` default; injectable for tests).
- The approval-context binding is a thin adapter that maps `ApprovalRequestRow` → `OutboundMessage`, leaving the core decoupled from the trading domain.

## What

Three layers, in order of dependence (bottom-up):

### Layer 1 — Generic core (`apps/api/src/iguanatrader/shared/channel_dispatch/`)

**Zero domain imports.** Pure utility code; `mypy --strict` + isolated test surface.

```
shared/channel_dispatch/
  __init__.py
  types.py          # OutboundMessage, Recipient, DispatchResult
  protocol.py       # MessageDispatcher, OutboundTransport
  log_only.py       # LogOnlyMessageDispatcher
  multi.py          # MultiChannelMessageDispatcher (per-channel routing + isolation)
  rate_limit.py     # AsyncTokenBucket
  sign.py           # hmac_sha256_hex helper
  adapters/
    __init__.py
    telegram.py     # TelegramBotMessageDispatcher
    hermes.py       # HermesWhatsAppMessageDispatcher
```

Public types:

```python
@dataclass(frozen=True, slots=True)
class OutboundMessage:
    body: str
    correlation_id: str               # opaque caller-supplied id (e.g. request UUID)
    metadata: Mapping[str, str] = field(default_factory=dict)
    subject: str | None = None        # optional — Telegram has no subject; some channels do

@dataclass(frozen=True, slots=True)
class Recipient:
    channel: str                      # "telegram" | "whatsapp" | future channels
    address: str                      # chat_id | phone_number | etc.
    display_name: str | None = None

@dataclass(frozen=True, slots=True)
class DispatchResult:
    channel: str
    address: str
    status: Literal["delivered", "failed", "skipped"]
    wire_message_id: str | None = None
    error: str | None = None

@runtime_checkable
class MessageDispatcher(Protocol):
    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]:
        """Send `message` to each `recipient`. MUST NOT raise — per-recipient
        failures are returned as DispatchResult(status='failed', error=...)."""
        ...

@runtime_checkable
class OutboundTransport(Protocol):
    async def send(self, *, address: str, body: str) -> str:
        """Wire-level send. Returns wire message id. May raise on transport error."""
        ...
```

Key design choices:

- **`dispatch` returns results, never raises** — caller decides whether to log / persist failures. Aligns with FR32 isolation.
- **Per-recipient try/except inside `MultiChannelMessageDispatcher`** — one bad recipient cannot skip the rest.
- **`OutboundTransport` is the smallest possible Protocol** so adapters can inject any HTTP client (httpx, aiohttp, fakes). No `IncomingCommand` coupling (cf. existing `ChannelTransportPort` which has it).
- **Rate limiter is async + token-bucket** with a configurable `rate_per_second` (default 30 for Telegram, 80 for Meta Cloud API). Acquires before each `send`.
- **HMAC signing** is a single helper; Hermes adapter wraps the request body with `X-Signature: sha256=<hex>` header.

### Layer 2 — Concrete adapters (live in `shared/channel_dispatch/adapters/`)

`TelegramBotMessageDispatcher`:
- Constructor: `bot_token: str`, `transport: OutboundTransport | None = None`, `rate_limit: AsyncTokenBucket | None = None`.
- Default transport: `_HttpxTelegramTransport(bot_token)` posting to `https://api.telegram.org/bot<token>/sendMessage`.
- Default rate limit: `AsyncTokenBucket(rate_per_second=30, burst=30)` (Telegram bot API limit).
- Filter recipients to `channel == "telegram"`; route others to `DispatchResult(status="skipped")` so MultiChannel sees them.

`HermesWhatsAppMessageDispatcher`:
- Constructor: `hermes_base_url: str`, `hmac_secret: str`, `transport: OutboundTransport | None = None`, `rate_limit: AsyncTokenBucket | None = None`.
- Default transport: `_HttpxHermesTransport(base_url, hmac_secret)` POSTing JSON `{recipient, body}` with `X-Signature: sha256=<hex>`.
- Default rate limit: `AsyncTokenBucket(rate_per_second=80, burst=80)` (Meta Cloud API limit).
- Filters to `channel == "whatsapp"`.

`MultiChannelMessageDispatcher`:
- Constructor: `dispatchers: Mapping[str, MessageDispatcher]` keyed by channel name.
- Routes each recipient to `dispatchers[recipient.channel]`. Unknown channel → `DispatchResult(status="skipped", error="no dispatcher for channel=...")`.
- Per-dispatcher try/except so one broken adapter cannot kill the rest.

### Layer 3 — Iguanatrader binding (`apps/api/src/iguanatrader/contexts/approval/dispatcher.py`)

Binding layer maps approval-context types ↔ generic core. **Existing `ChannelDispatcher` Protocol stays** (additive — backward compat with PR #111 callers); a new `ChannelDispatcherFromMessageDispatcher` adapter wraps the generic dispatcher.

```python
def build_outbound_message_from_request(request: ApprovalRequestRow) -> OutboundMessage:
    return OutboundMessage(
        body=f"Approve trade proposal {request.proposal_id}? expires_at={request.expires_at.isoformat()}",
        correlation_id=str(request.id),
        metadata={"proposal_id": str(request.proposal_id), "request_kind": request.kind},
    )

async def resolve_recipients_from_request(
    request: ApprovalRequestRow,
    repository: ApprovalRepository,
) -> list[Recipient]:
    """Look up enabled `authorized_senders` rows for this tenant + each requested channel.
    Returns one Recipient per (channel, external_id) pair."""
    ...

class _MessageDispatcherChannelAdapter:
    """Adapts a generic `MessageDispatcher` to the legacy `ChannelDispatcher` shape."""
    def __init__(self, inner: MessageDispatcher, repository: ApprovalRepository) -> None: ...
    async def fanout(self, *, request: ApprovalRequestRow, channels: list[str]) -> None:
        message = build_outbound_message_from_request(request)
        recipients = await resolve_recipients_from_request(request, self._repository)
        results = await self._inner.dispatch(message=message, recipients=recipients)
        for r in results:
            log.info("approval.channel.dispatch.result", **asdict(r))
```

`build_channel_dispatcher_from_env()` extends:

```python
def build_channel_dispatcher_from_env(
    repository: ApprovalRepository | None = None,
) -> ChannelDispatcher:
    kind = os.environ.get("IGUANATRADER_CHANNEL_DISPATCHER", "").strip().lower()
    if kind in {"", "log_only"}:
        return LogOnlyChannelDispatcher()
    if kind == "telegram_hermes":
        if repository is None:
            log.error("approval.channel.dispatcher.no_repository", fallback="log_only")
            return LogOnlyChannelDispatcher()
        return _build_telegram_hermes_from_env(repository)
    log.warning("approval.channel.dispatcher.unknown_kind", kind=kind, fallback="log_only")
    return LogOnlyChannelDispatcher()
```

`_build_telegram_hermes_from_env(repository)`:
- Reads `TELEGRAM_BOT_TOKEN`, `HERMES_BASE_URL`, `HERMES_HMAC_SECRET` from env.
- If any missing → log structured error + fallback to `LogOnlyChannelDispatcher` (operator can set them later without code change).
- Otherwise constructs `MultiChannelMessageDispatcher` + `_MessageDispatcherChannelAdapter`.

### Daemon wiring (`cli/trading.py`)

Single line change: pass `repository=ApprovalRepository()` to `build_channel_dispatcher_from_env()`.

## Out of scope (genuinely deferred)

- **SOPS encrypted env bundles** for production credentials — operator step (already canonical pattern; not code).
- **Per-tenant rate-limit overrides** — env-var rate limit is global per dispatcher; per-tenant tuning is a v2 ergonomic if it ever matters.
- **Real wire integration test against Telegram sandbox** — needs network + a sandbox bot account; defer to ops smoke-test playbook.
- **Inbound webhook receiver for Hermes** — already covered by P1's existing `HermesWhatsAppChannel` (long-poll/webhook path); this slice is **outbound only**.
- **Retry / dead-letter queue for failed dispatches** — DispatchResult records failures; persistence + retry is a v2 hardening slice.

## Pattern usage

- **Protocol+InTreeFake+DeferredProductionInstall #4** — `MessageDispatcher` Protocol + `LogOnlyMessageDispatcher` (InTree fake) + Telegram/Hermes (DeferredProductionInstall via env-var credentials). 4th canonical instance after T4-followup-market-data, R6 hindsight, p1-followup-channel-fanout.
- **shared/ as upstream-extractable lib** — first slice to deliberately design `shared/` modules for upstream extraction. Sets precedent for future cross-project utilities (rate-limiters, signing helpers, etc.).
