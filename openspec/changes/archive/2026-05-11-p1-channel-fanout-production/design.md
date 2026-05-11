# Design: p1-channel-fanout-production

## D1 — Generic core lives in `shared/` (upstream-extractable)

`apps/api/src/iguanatrader/shared/` already contains **zero** `from iguanatrader.contexts.*` imports (verified via `grep -lE "from iguanatrader.contexts" apps/api/src/iguanatrader/shared/*.py` → no matches). It is the canonical home for domain-free utilities (`messagebus`, `kernel`, `backoff`, `decimal_utils`, `time`, `errors`, `ports`, `types`).

Adding `shared/channel_dispatch/` keeps the invariant: the new package may import from `typing`, `dataclasses`, `asyncio`, `httpx`, `hmac`, `hashlib`, `time`, `structlog`, and other `shared/*` siblings — never from `contexts/`.

**Extraction path** (future, mechanical): `git mv apps/api/src/iguanatrader/shared/channel_dispatch packages/channel-dispatch-py/src/channel_dispatch` + create `packages/channel-dispatch-py/pyproject.toml` + add `path = "../packages/channel-dispatch-py"` dep in `apps/api/pyproject.toml`. No code changes required.

## D2 — Two Protocols, not one

The existing approval-context `ChannelDispatcher` Protocol takes `ApprovalRequestRow` + `channels: list[str]`. That coupling is fine for the binding layer but unsuitable for upstream.

The generic core defines two narrow Protocols:

- `MessageDispatcher.dispatch(*, message: OutboundMessage, recipients: Sequence[Recipient]) → list[DispatchResult]` — fanout-level abstraction.
- `OutboundTransport.send(*, address: str, body: str) → str` — wire-level abstraction (the smallest possible surface — channel adapters inject any HTTP client behind it).

The binding layer in `contexts/approval/dispatcher.py` adapts the legacy `ChannelDispatcher.fanout` to the generic `MessageDispatcher.dispatch`. Both Protocols coexist; the legacy one becomes the iguanatrader-specific facade, the generic one is the upstreamable surface.

## D3 — Recipient resolution via existing `authorized_senders` table

The retro for PR #111 anticipated a new `chat_id` / `phone_number` schema. **Re-evaluation: not needed.** Migration `0001_initial_schema.py` already declares:

```python
op.create_table(
    "authorized_senders",
    sa.Column("tenant_id", sa.CHAR(36), nullable=False),
    sa.Column("channel", sa.Text(), nullable=False),  # CHECK in ('telegram','whatsapp')
    sa.Column("external_id", sa.Text(), nullable=False),
    sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    sa.UniqueConstraint("tenant_id", "channel", "external_id"),
)
```

For Telegram, `external_id` IS the `chat_id` (canonical Telegram bot API parameter). For WhatsApp, `external_id` IS the wa_id / phone number (Meta Cloud API parameter). The binding-layer `resolve_recipients_from_request` SELECTs `WHERE tenant_id = :t AND channel = ANY(:requested_channels) AND enabled = TRUE`, returning one `Recipient(channel, address=external_id, display_name)` per row. Zero migration churn.

## D4 — Rate limiting: async token bucket, per-dispatcher

`AsyncTokenBucket(rate_per_second: float, burst: int)` with `async def acquire(self) -> None` semantics. Implementation: monotonic-clock token replenish + `asyncio.Lock` for concurrency safety. Default rates:

- Telegram: 30 msg/s (per `https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this`).
- Meta Cloud API: 80 msg/s (conservative — actual tier-based limits range 250–1000/s; 80 is safe across tiers).

Each adapter holds its own bucket (independent budgets). The bucket is overrideable via constructor for tests + tuning. Per-tenant overrides are deferred (out of scope per proposal).

## D5 — HMAC signing for Hermes

Hermes endpoint expects `X-Signature: sha256=<hex(hmac(body))>` per the Meta Cloud API webhook convention. Helper `hmac_sha256_hex(secret: bytes, payload: bytes) -> str` wraps `hmac.new(secret, payload, hashlib.sha256).hexdigest()`. Adapter computes signature on the JSON-serialized body before posting.

## D6 — FR32 isolation: defense in depth

Three layers:

1. **`MessageDispatcher.dispatch` MUST NOT raise** — per-recipient failures inside concrete adapters are caught and returned as `DispatchResult(status="failed", error=str(exc))`.
2. **`MultiChannelMessageDispatcher` per-dispatcher try/except** — a constructor-time crash in one adapter cannot kill another adapter's batch.
3. **Binding-layer `_MessageDispatcherChannelAdapter.fanout` outer try/except** in `ApprovalService._approval_requested_handler` (already in place from PR #111) — guarantees a totally broken dispatcher cannot bring down the audit-write path.

Property test (D8) covers all three layers.

## D7 — Composition root: env-driven, fallback-friendly

`build_channel_dispatcher_from_env(repository)`:

| `IGUANATRADER_CHANNEL_DISPATCHER` | Outcome |
|---|---|
| unset, `""`, `"log_only"` | `LogOnlyChannelDispatcher()` (existing v1 default) |
| `"telegram_hermes"` + all of `TELEGRAM_BOT_TOKEN` + `HERMES_BASE_URL` + `HERMES_HMAC_SECRET` set | Production `MultiChannelMessageDispatcher` wrapped in `_MessageDispatcherChannelAdapter` |
| `"telegram_hermes"` + any required env var missing | Log `approval.channel.dispatcher.missing_credentials` + fallback to `LogOnlyChannelDispatcher` |
| `"telegram_hermes"` + repository is None | Log `approval.channel.dispatcher.no_repository` + fallback |
| any other value | Log `approval.channel.dispatcher.unknown_kind` + fallback (existing behavior) |

**Fallback-not-crash** is intentional: operator can set `IGUANATRADER_CHANNEL_DISPATCHER=telegram_hermes` *before* SOPS bundle lands; daemon stays up + logs missing credentials so the gap is visible without breaking startup.

## D8 — Test surface

Three layers:

1. **Unit tests for generic core** (`tests/unit/shared/channel_dispatch/`):
   - `test_log_only.py` — returns `DispatchResult(status="skipped", ...)` per recipient.
   - `test_multi.py` — routes by channel, isolates per-dispatcher failures, handles unknown channels.
   - `test_telegram_adapter.py` — uses `_FakeOutboundTransport` (records calls), verifies rate-limiter is acquired, verifies `channel != "telegram"` recipients are skipped.
   - `test_hermes_adapter.py` — verifies HMAC signature in header, `channel != "whatsapp"` skipped.
   - `test_rate_limit.py` — timing-sensitive: 100 acquires at rate=30/s should take ≥3.3s.
   - `test_sign.py` — known-vector HMAC test.

2. **Property test** (`tests/property/test_channel_dispatch_isolation.py`):
   - 50 examples: random list of (good, bad) recipients across multiple channels — assert that:
     - `len(results) == len(recipients)` (no recipient silently dropped).
     - Each `DispatchResult.status ∈ {"delivered", "failed", "skipped"}`.
     - At least one `delivered` if at least one good recipient existed.
   - Marker: `@pytest.mark.property` (not `ci_blocking` — unit tests cover the contract).

3. **Integration test for binding** (`tests/integration/contexts/approval/test_channel_dispatcher_binding.py`):
   - End-to-end: insert `authorized_senders` rows + emit `ApprovalRequested` event + assert `_MessageDispatcherChannelAdapter` correctly resolves recipients + a fake `MessageDispatcher` records the expected `OutboundMessage` + recipients.

No real Telegram / Hermes wire calls in CI. Operator validation against sandboxes is documented in `docs/operations/channel-dispatch-smoke-test.md` (future ops slice — out of scope here).

## D9 — Mypy strictness

`shared/channel_dispatch/` is added to the `mypy --strict` surface. `Sequence`, `Mapping`, `Literal`, `Protocol`, `runtime_checkable` already conform to the project's strict baseline. `httpx.AsyncClient` is fully typed in modern releases (no `# type: ignore` expected).

## D10 — Backward compatibility

PR #111's public surface (`ChannelDispatcher` Protocol, `LogOnlyChannelDispatcher`, `build_channel_dispatcher_from_env`) is unchanged. Existing tests in `tests/unit/contexts/approval/test_channel_dispatcher.py` continue to pass without modification. The new generic core is purely additive.

## Risks

| Risk | Mitigation |
|---|---|
| `httpx` version skew vs existing repo dep | Inspect `apps/api/pyproject.toml`; reuse pinned version (already required by other adapters) |
| Token bucket race under high concurrency | `asyncio.Lock` around the replenish-and-decrement op; property test exercises burst behavior |
| Operator sets `telegram_hermes` without credentials → silent log-only | Documented in CHANGELOG + structured log + gauge metric `approval.channel.dispatcher.fallback{reason="missing_credentials"}` (left for future obs slice — log-only here) |
| HMAC secret leaked via log | Adapter MUST NOT log secret. Property test asserts no occurrence of secret in `caplog.records`. |
