# Retrospective: t4-followup-market-data

> **Forward-authored** per [.ai-playbook/specs/runbook-bmad-openspec.md §4.1](../.ai-playbook/specs/runbook-bmad-openspec.md). Fields filled at archive time.

- **PR**: TBD (slice/t4-followup-market-data branch open)
- **Archive path**: `openspec/changes/archive/<archive-date>-t4-followup-market-data/`
- **Lines shipped**: ~1800 LoC estimate (~900 src + ~840 tests + ~100 retro/openspec).

## What worked

- _(fill on archive — pre-flag candidates: Protocol+InTreeFake+DeferredProductionInstall pattern shipped end-to-end (Port + InMemory + DB + IBKR ingestor all in one slice, no deferral); skeleton-then-fill canonical instance #3 (T1 placeholders → T4-followup bodies); migration slot reservation in proposal.md prevented collision; broker-ingestor IBKR connection sharing kept resource footprint at 1 socket; rate-limit via append-only audit table is observable + cross-process safe by design.)_

## What didn't

- _(fill on archive — pre-flag candidates: T4 archive surface change (StrategyResolver async signature) required test wrapper helper `_async_const`; would have been a CI fail if not pre-empted at design time. Bar dataclass field name `timestamp` (not `ts`) discovered at adapter-write time, same lesson as K1-followup CapType discovery — pre-flight grep cross-context dataclass shapes during Gate B.)_

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

- [ ] Paper-mode daemon boot → 06:00 UTC tick fires `market_data_sync` → bars appear in `market_data_bars` for watchlist symbols.
- [ ] Subsequent midday tick fires propose loops → at least one proposal flows through the bus → broker fill recorded.
- [ ] `iguanatrader market-data sync` CLI works end-to-end + respects rate limit.
- [ ] `iguanatrader market-data backfill --symbol AAPL --days 365` works.
- [ ] mypy --strict + pre-commit + CI green.
