# Retrospective: t4-followup-market-data

> **Forward-authored** per [.ai-playbook/specs/runbook-bmad-openspec.md §4.1](../.ai-playbook/specs/runbook-bmad-openspec.md). Fields filled at archive time.

- **PR**: [#105](https://github.com/Wizarck/iguanatrader/pull/105) (merged 2026-05-08, squash `1790002`).
- **Archive path**: `openspec/changes/archive/2026-05-08-t4-followup-market-data/`
- **Lines shipped**: 3640 insertions across 28 files (≈3050 src+test: ~900 src + ~2150 tests; remaining 590 are openspec spec docs + retro stub + commit-history boilerplate).
- **CI iterations**: 3 rounds (round 1: black format fail in initial commit; round 2: 7 mypy errors from `object`-typed bootstrap_routines params; round 3: 3 mypy errors on closure narrowing — all fixed in 2 follow-up commits).

## What worked

- **Protocol+InTreeFake+DeferredProductionInstall shipped end-to-end**: Port + InMemory + DB + IBKR ingestor all in one slice, no deferral. The user explicitly requested this scope ("no quiero diferir el ibkr adapter"). Validates that the pattern scales to a 12h slice when warranted.
- **Skeleton-then-fill canonical instance #3**: T1 placeholders (`_make_strategy_resolver` `NotImplementedError` + `_placeholder` no-op) → T4-followup-market-data bodies. R1→R5, T1→T4, T1+T4→THIS. Three recurrences justify ai-playbook v0.11.1 promotion.
- **Migration slot reservation in proposal.md** prevented collision (slot `0012` claimed pre-emptively; `0011_orchestration_tables` was last). Per migration-slot-reservation.md.
- **Broker–ingestor IBKR connection sharing** keeps resource footprint at 1 socket; cron schedule (06:00 UTC ingestor vs 08:00+ UTC propose loops) prevents temporal overlap so contention is moot in v1.
- **Rate-limit via append-only audit table** is observable + cross-process safe by design (daemon + CLI invocations all share one source of truth — the table). Compare to in-memory token-bucket which would need cross-process coordination.
- **Local `.venv` ruff+black** (installed during P1-followup CI fix) prevented black --check fail this time around. The first push WAS clean on lint; the 3 CI rounds were all mypy-only.
- **Async test resolver helper `_async_const`** absorbed all 5 T4 test sites in 1-line replacement. Archive surface change cost: minimal.

## What didn't

- **Three CI rounds for mypy** — all from typing the new `bootstrap_routines` params as `object` instead of `Any`. mypy --strict treats `object` as having zero callable methods (correct strict semantics). Lesson: when introducing optional injection params for backwards-compat, default to `Any | None`, not `object | None`. Promote to ai-playbook gotcha.
- **Closure narrowing not propagated by mypy**: `if wire_propose_loops` at the outer scope did not narrow `market_data_port: Any | None → Any` inside the nested `_propose` closure. Required local non-None alias `md_port: Any = market_data_port` outside the closure for narrowing to stick. Recurring pattern when mixing optional injection + nested closures.
- **`_FakeBroker` Protocol mismatch** in the e2e test: `BrokerPort` requires `reconcile_fills` / `get_position` / `get_account_equity` (not `stream_fills` / `positions` / `disconnect`). Same lesson as K1+P1 followups: pre-flight grep destination Protocols during Gate B, not Gate D.
- **`Bar` field name `timestamp` (not `ts`)**: discovered at adapter-write time, mirrors K1-followup `CapType` literal lesson + P1-followup `trading.ProposalApproved` shape lesson. **Three recurrences of "discover destination dataclass shape at code-write time"** — formalise as a Gate-B pre-flight checklist item in ai-playbook v0.11.1.

## Lessons

- **Protocol + InTreeFake + DeferredProductionInstall** (ai-playbook v0.11): shipping all 3 adapters together (vs. deferring the production one) is viable when scope warrants — this slice did NOT defer the IBKR adapter despite it being the heavyweight component.
- **Decoupling fetch from evaluation** via a DB cache + scheduled write is the canonical pattern for rate-limited external data sources. Same pattern applies to any future external API integration where pacing limits or connection brittleness is a concern.
- **Append-only audit table for rate-limiting** scales naturally to multi-process scenarios (daemon + CLI + future schedulers all share the same source of truth). Compare to in-memory token-bucket which would need cross-process coordination.
- **Skeleton-then-fill recurrence #3** (R1→R5, T1→T4, T1+T4→t4-followup-market-data): officially promote to ai-playbook v0.11.1 alongside bus-bridge follow-up.

## Carry-forward to next change

- **trades-read-endpoints**: fill the 3 stub trade/order GET endpoints (501 → bodies). Independent of this slice.
- **market-data-replay**: operator CLI `iguanatrader market-data replay --routine=midday --date=2026-04-15` to replay a past tick. Schema enables it.
- **intraday-market-data**: `1m` / `1h` timeframe support + per-strategy timeframe override. v2 SaaS.
- **per-tenant-watchlist-table**: replace env-var with `watchlists` table. v2 SaaS.
- **Hypothesis property tests for proposal validation**: T4 retro flagged as deferred; not on critical path.

## Pattern usage

This slice is the **third canonical instance of "skeleton-then-fill"** + a fresh canonical of "**Protocol+InTreeFake+DeferredProductionInstall**" with all adapters shipping together (not deferred). The integration test in §9.2.1 is the FIRST end-to-end execution of K1-followup + P1-followup bridges — green run validates both followup slices' design.

## Acceptance status (operator-driven, post-merge)

- [x] mypy --strict + ruff + black + pre-commit + pytest + Helm + Lighthouse + CodeRabbit ALL green (after 3 mypy rounds).
- [ ] Paper-mode daemon boot → 06:00 UTC tick fires `market_data_sync` → bars appear in `market_data_bars` for watchlist symbols — operator-verified at next paper-mode run.
- [ ] Subsequent midday tick fires propose loops → at least one proposal flows through the bus → broker fill recorded.
- [ ] `iguanatrader market-data sync` CLI works end-to-end + respects rate limit.
- [ ] `iguanatrader market-data backfill --symbol AAPL --days 365` works.
