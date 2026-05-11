# Retrospective: p1-channel-fanout-production

> **Forward-authored** — fill at archive with squash SHA, CI rounds, and pre-flag candidates.

- **PR**: [#114](https://github.com/Wizarck/iguanatrader/pull/114) (merged 2026-05-11, squash `e88da28`).
- **Archive path**: `openspec/changes/archive/2026-05-11-p1-channel-fanout-production/`
- **Lines shipped**: 2133 insertions / 27 deletions across 27 files (~1100 generic core + adapters, ~250 binding layer, ~450 tests, ~330 openspec/retro/wiring). CI 12/12 verde **al primer push** (zero fix rounds).

## What worked

- **Generic core in `shared/channel_dispatch/`** keeps zero `iguanatrader.contexts.*` imports — extraction to a PyPI package is a mechanical `git mv` + new `pyproject.toml`. Verified the invariant via `grep -lE "from iguanatrader.contexts" apps/api/src/iguanatrader/shared/channel_dispatch/*.py → no matches`.
- **Per-tenant recipient resolution via existing `authorized_senders.external_id`** — no migration needed. The retro for PR #111 anticipated a new schema; re-evaluation showed `external_id` IS the canonical Telegram chat_id / WhatsApp wa_id.
- **DeferredProductionInstall pattern**: env-var credentials fall back to LogOnly + structured error log when missing — daemon stays up, operator wires SOPS bundle without code changes. Same shape as R6 hindsight adapter.
- **Two-Protocol coexistence**: legacy `ChannelDispatcher.fanout(request, channels)` stays for backward compat (PR #111's tests pass unchanged); new generic `MessageDispatcher.dispatch(message, recipients)` is upstream-extractable. The binding layer is a thin adapter between them.
- **`RateLimiter` Protocol** in `protocol.py` (added during test-writing) lets tests inject lightweight counting fakes without `# type: ignore` — pre-flag candidate validated: "define a Protocol when adapters need pluggable concrete dependencies for tests".

## What didn't

- **Initial property test used `async def` directly under `@given`** — Hypothesis doesn't natively support async test functions; pytest-asyncio + hypothesis interplay requires wrapping the async logic inside a sync test via `asyncio.run(_run())`. Caught on local lint pass; fixed before push. Pre-flag for future property tests on async surfaces.
- **Initial `rate_limit` type hint was `AsyncTokenBucket | None`** which forced `# type: ignore[arg-type]` for test fakes. Refactored to introduce a `RateLimiter` Protocol (`acquire(self) -> None`) so adapters accept any structurally-compatible rate limiter. Pre-flag confirmed: "define a Protocol when adapters need pluggable concrete dependencies for tests".
- **`httpx` listed under `[tool.poetry.group.dev.dependencies]`** in `pyproject.toml` even though it's used by runtime adapters (research scraping + openbb sidecar + now channel dispatch). Did not touch the pin in this slice (CI passes because the dev group is installed in the same poetry env); pre-flag for a one-line cleanup slice to move httpx to main runtime deps.

## Pre-flag candidates

- **Define Protocols for injectable dependencies that need test fakes** — saved one `# type: ignore` round here vs. the dev experience of pre-emptively casting in tests. Cheaper than discovering it during mypy --strict.
- **For async + Hypothesis property tests, wrap async logic in `asyncio.run(_run())` inside a sync `def` test** — the existing `test_propose_event_emission.py` (PR #112) already uses this pattern; codifies as the canonical async-property-test shape.
- **`shared/` is the canonical home for upstream-extractable modules** — the invariant "no `from iguanatrader.contexts` imports" was already true; this slice cements `shared/` as the deliberate extraction surface (vs. `lib/` or `packages/`-from-day-one). Documented in design D1.

## Carry-forward

- **SOPS-encrypted env bundles** for production credentials (`TELEGRAM_BOT_TOKEN`, `HERMES_BASE_URL`, `HERMES_HMAC_SECRET`) — operator step. Canonical pattern; not a code task.
- **Real wire smoke tests** against Telegram sandbox + Hermes staging — needs network + sandbox accounts; ops playbook task (out of CI scope).
- **Inbound webhook receiver for Hermes** — already covered by P1's existing `HermesWhatsAppChannel` (long-poll / webhook path). This slice is outbound only.
- **Retry / dead-letter queue for failed dispatches** — `DispatchResult` records failures; persistence + retry is a v2 hardening slice.
- **Per-tenant rate-limit overrides** — env-var rate limit is global per dispatcher; per-tenant tuning is v2 if/when needed.
- **Upstream extraction**: when the codebase is ready, `git mv apps/api/src/iguanatrader/shared/channel_dispatch packages/channel-dispatch-py/src/channel_dispatch` + create a standalone `pyproject.toml`. Zero code changes required.

## Pattern usage

- **Protocol+InTreeFake+DeferredProductionInstall #4**: `MessageDispatcher` Protocol + `LogOnlyMessageDispatcher` (InTree fake) + Telegram/Hermes adapters (DeferredProductionInstall via env-var credentials). 4th canonical instance after T4-followup-market-data, R6 hindsight, p1-followup-channel-fanout.
- **shared/ as upstream-extractable lib** — first slice to deliberately design `shared/` modules for upstream extraction. Sets precedent for future cross-project utilities (rate-limiters, signing helpers, etc.).
