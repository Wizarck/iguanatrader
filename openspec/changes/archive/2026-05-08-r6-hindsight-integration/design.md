# Design — r6-hindsight-integration

> Architectural decisions inline in [proposal.md](proposal.md). This file documents the per-component contracts.

## 1. `HindsightPort` Protocol

```python
@runtime_checkable
class HindsightPort(Protocol):
    async def recall(
        self,
        *,
        bank: str,
        query: str,
        limit: int = 20,
        timeout_ms: int = 2000,
    ) -> list[str]: ...

    async def retain(
        self,
        *,
        bank: str,
        kind: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None: ...
```

`bank` is `f"iguanatrader-research-{tenant_id}"` per design tier; the adapter does NOT compute it (caller responsibility).

## 2. Adapters

### `InMemoryHindsightAdapter`
- Constructor: `seed: dict[str, list[str]]` mapping `bank` → preset retain entries.
- `recall(bank, query, limit, timeout_ms)` returns up to `limit` entries from `seed[bank]` filtered by case-insensitive substring match on `query`. No real semantic search.
- `retain(bank, kind, content, metadata)` appends `f"[{kind}] {content}"` to `seed.setdefault(bank, [])`.

### `HttpHindsightAdapter`
- Constructor: `base_url: str`, `timeout_seconds: float = 5.0` (default; `recall(timeout_ms=...)` overrides per-call).
- POSTs JSON to `{base_url}/recall` and `{base_url}/retain`. Raises `HindsightUnavailable` on connection error, `HindsightTimeout` on async-timeout, `HindsightWriteFailed` on non-2xx response.
- env: `IGUANATRADER_HINDSIGHT_URL` (default `http://localhost:8765/hindsight`).

## 3. Bus-bridge: `HindsightRetainHandler`

```python
class HindsightRetainHandler:
    def __init__(
        self, *, hindsight: HindsightPort, repository: ResearchRepository,
    ) -> None: ...

    def register_subscriptions(self, bus: MessageBus) -> None:
        from iguanatrader.contexts.research.events import ResearchBriefSynthesized
        bus.subscribe(
            ResearchBriefSynthesized,
            self._on_brief_synthesized,
            idempotent=True,
        )

    async def _on_brief_synthesized(self, event: ResearchBriefSynthesized) -> None:
        # 1. Re-query the brief by id (event payload is light per slice 2 D3).
        # 2. Compose retain content from thesis + key insights.
        # 3. await self._hindsight.retain(...) wrapped in try/except.
        # 4. Failures: log "research.hindsight.retain_failed" + swallow (FR80 graceful).
```

Same shape as `K1.RiskService.register_subscriptions` (PR #103) and `P1.ApprovalService.register_subscriptions` (PR #104) — bus-bridge follow-up pattern, 5th canonical instance.

## 4. R5 surface modifications (additive only)

### `BriefService.__init__`

```python
def __init__(
    self,
    *,
    repository: ResearchRepository,
    composite_provider: CompositeFeatureProvider,
    synthesizer: Synthesizer,
    audit_service: AuditTrailService,
    bus: MessageBus | None = None,
    default_model: str = "claude-3-5-sonnet",
    hindsight: HindsightPort | None = None,  # NEW
) -> None: ...
```

### `BriefService.refresh`

Insert AFTER feature-bundle fetch + BEFORE synthesizer call:

```python
narrative_context: list[str] = []
if self._hindsight is not None:
    enabled = await self._tenant_feature_flag("hindsight_recall_enabled")
    if enabled:
        try:
            narrative_context = await self._hindsight.recall(
                bank=f"iguanatrader-research-{tenant_id}",
                query=f"{symbol} fundamentals macro context lessons",
                limit=20,
                timeout_ms=2000,
            )
        except (HindsightUnavailable, HindsightTimeout):
            logger.warning("research.hindsight.recall_failed", extra={"symbol": symbol})
            narrative_context = []
```

`_tenant_feature_flag(key)` is a private helper that loads the current tenant row + reads the `feature_flags` dict.

### `Synthesizer.synthesize`

```python
async def synthesize(
    self,
    *,
    symbol: str,
    methodology: str,
    feature_bundle: FeatureBundle,
    methodology_result: MethodologyResult,
    model: str,
    narrative_context: list[str] | None = None,  # NEW
) -> SynthesizedBrief: ...
```

`_render_prompt` prepends a `## Hindsight narrative\n\n{joined context}` section if `narrative_context` is non-empty.

## 5. Settings route

`apps/api/src/iguanatrader/api/routes/settings.py`:

```python
@router.get("/feature-flags", response_model=FeatureFlagsOut)
async def get_feature_flags(user: User = Depends(get_current_user), db: ...) -> FeatureFlagsOut: ...

@router.put("/feature-flags", response_model=FeatureFlagsOut)
async def put_feature_flags(
    payload: FeatureFlagsIn, user: User = Depends(get_current_user), db: ...,
) -> FeatureFlagsOut: ...
```

`FeatureFlagsIn` whitelists `hindsight_recall_enabled: bool` (only v1 key); unknown keys → 400 `ValidationError`. Persists via UPDATE on `tenants.feature_flags`.

## 6. CLI

`apps/api/src/iguanatrader/cli/settings.py`:

```
iguanatrader settings feature-flag get [--key=hindsight_recall_enabled]
iguanatrader settings feature-flag set <KEY>=<VALUE> [--tenant=<slug>]
```

Reuses `_tenant.resolve_tenant_id` + session_factory shape. Supports `--tenant` for multi-tenant local ops.

## 7. Daemon wiring

`cli/trading.py` `_run_daemon` (after `approval_service.register_subscriptions(bus)` block):

```python
from iguanatrader.contexts.research.hindsight.http_adapter import (
    HttpHindsightAdapter, build_hindsight_adapter_from_env,
)
from iguanatrader.contexts.research.hindsight.retain_handler import (
    HindsightRetainHandler,
)

hindsight = build_hindsight_adapter_from_env()
hindsight_retain = HindsightRetainHandler(
    hindsight=hindsight, repository=ResearchRepository(),
)
hindsight_retain.register_subscriptions(bus)
```

If `IGUANATRADER_HINDSIGHT_URL` env-var unset, `build_hindsight_adapter_from_env()` returns an `InMemoryHindsightAdapter()` for dev/CI safety (matches the deployment-foundation `InTreeFake+DeferredProductionInstall` pattern).

## 8. Tests

| File | Tests |
|---|---|
| `tests/unit/contexts/research/hindsight/test_in_memory.py` | seeded bank returns entries / empty bank returns [] / case-insensitive query match |
| `tests/unit/contexts/research/hindsight/test_retain_handler.py` | event → retain called / repository fetch failure → log + swallow / hindsight raises → log + swallow |
| `tests/integration/test_hindsight_recall_gated.py` | flag OFF → recall NOT called / flag ON → recall called + narrative passed to synth |
| `tests/integration/test_hindsight_retain_always_on.py` | publish ResearchBriefSynthesized → retain invoked once with brief thesis |
| `tests/unit/api/routes/test_settings_routes.py` | GET → 200 with flags / PUT happy path / PUT unknown key → 400 |
| `tests/unit/cli/test_settings_cli.py` | --help / get / set roundtrip via CliRunner |
