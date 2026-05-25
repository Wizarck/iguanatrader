# Handover — 2026-05-18 (PM session) — roadmap progress: dual-daemon followups + LLM track + U-next-2

> **For pasting into a fresh Claude Code conversation.** Drop the contents below as your first message so the new session has full context.

---

## Project state

- Repo: `c:\Projects\iguanatrader` (Wizarck/iguanatrader on GitHub)
- Operator: Arturo Ramírez
- Current branch: `main` (clean, in sync with origin)
- Main HEAD at session end: after PR #271 merge — six PRs shipped this session.

## What landed this session (6 PRs, in chronological order)

1. **PR #266** — `slice/dual-daemon-followups` → main (squashed)
   - Closes Phase 2.5 + Phase 6 from the dual-daemon slice.
   - Migration `0030_trades_exit_reason_ibkr_reconcile.py`: extends `ck_trades_exit_reason_allowed` with `'ibkr_reconcile'`.
   - `BrokerPort.list_positions()` added; `IBKRAdapter` implements it; 7 test fakes updated for Protocol conformance.
   - `DaemonLifecycleService._reconcile_positions()`: diffs broker book vs `TradeRepository.list_open_for_tenant`, closes orphan local trades with `exit_reason='ibkr_reconcile'`.
   - `cli/trading.py` passes `trade_repo=TradeRepository()` into `DaemonLifecycleService`.
   - `_VALID_EXIT_REASONS` in `service.py` extended.
   - Test `apps/api/tests/integration/test_daemon_lifecycle_drain_reconcile.py` — 3/3 green covering drain idempotency + reconcile-in-sync no-op + reconcile-closes-orphan.

2. **PR #267** — `slice/a2-risk-review-persist` → main (squashed)
   - Closes A2 finish-line gap. The persister was a no-op stub; the 5 `risk_*` columns didn't exist.
   - Migration `0031_trade_proposal_risk_review.py`: adds `risk_score INT`, `risk_flags JSON`, `risk_rationale TEXT`, `risk_generated_at TIMESTAMPTZ`, `risk_model VARCHAR(64)` to `trade_proposals` + CHECK `risk_score BETWEEN 0 AND 100`. Whitelist extended on `TradeProposal.__append_only_mutable_columns__`.
   - `TradeProposalRepository.set_risk_assessment()` writes the 5 columns + stamps `risk_generated_at`.
   - `cli/llm_handler_wiring.py::build_risk_assessment_persister` adapter wired into `wire_llm_handlers`.
   - Per-tenant threshold override: `AutoRiskReviewOnCreateHandler` accepts `threshold_loader` callable; production loader reads `tenants.feature_flags["risk_review_confidence_threshold"]`.
   - `/settings/feature-flags` GET+PUT extended with range-validated threshold (decimal in `[0, 1]`, empty string clears).
   - **Side-fix**: `InvalidBudgetCapError` contract was wrong (`status_code` / `code` class vars ignored by `IguanaError`, fell through to 500). Same fix applied to new `InvalidRiskThresholdError`. Both use `type_uri` / `default_title` / `default_status`.
   - Test `test_auto_risk_review_persist.py` — 9/9 green.

3. **PR #268** — `slice/sops-live-creds-task19` → main (squashed)
   - Closes Task 19 from the dual-daemon slice (was operator-owned per Windows SOPS quirks; operator asked me to do it inline).
   - `.secrets/live.env.enc`: adds `IBKR_USERNAME_LIVE`, `IBKR_PASSWORD_LIVE`, `IBKR_ACCOUNT_ID_LIVE` (aliases of unsuffixed keys, kept for backwards-compat). Account ID populated with `U12492989`.
   - `.secrets/paper.env.enc`: **fix** — `IBKR_USERNAME` switched from auto-generated paper-trading user (`okqtbz074`) to the IBKR portal login (`arturoramirez6` / `halamadrid6`). The `gnzsnz/ib-gateway` image authenticates against the portal, not the auto-paper login. `IBKR_ACCOUNT_ID=DUR071858` unchanged.
   - Method (Windows SOPS): `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops --age <recipient> --input-type dotenv --output-type dotenv --encrypt <plaintext>` — explicit `--age` flag bypasses `.sops.yaml` config-discovery that fails on `/tmp` paths.

4. **PR #269** — `chore/llm-roadmap-flip-a0-a3` → main (squashed)
   - Doc-only flip: `docs/roadmap-llm-features.md` A0/A1/A2/A3 → `merged` with pointers to the in-tree files (BudgetGuard, AutoExplain..., AutoJournal..., AutoRiskReview...).
   - Marks Task 19 done in `openspec/changes/archive/2026-05-18-dual-daemon-mode-toggle-and-reconcile/tasks.md`.

5. **PR #270** — `slice/u-next-2-trade-timeline` → main (squashed)
   - Closes UI roadmap row U-next-2.
   - **Variant fix**: `stateVariant()` no longer collapses `closing` and `closed` to `mute`. Now `open → accent`, `closing → warning` (yellow, active risk), `closed → mute`. Regression test pins the distinction.
   - **Order timeline**: `/api/v1/trades/{id}/orders` (new route, uses existing `OrderRepository.list_for_trade`); `/trades/[id]` page renders one row per Order (Entry / Stop / Target / Exit inferred from `order_type` + side relative to parent trade) with broker-side state Badge (`new` / `submitted` / `partially_filled` / `filled` / `canceled` / `rejected`) and timestamps. New helpers: `orderStateVariant()`, `orderRoleLabel()`.
   - Tests: 6 in `trades-detail-page.test.ts` (1 new orders happy-path + 1 new orders 503 + extended existing) + 13 in new `trades-variants.test.ts`. 19/19 green locally.

6. **PR #271** — `chore/u-next-2-flip-merged` → main (squashed)
   - One-line flip: U-next-2 row `in-progress → merged` after PR #270 landed.

## State of the roadmap tracks

### LLM features (`docs/roadmap-llm-features.md`)
- **A0** budget cap — merged
- **A3** auto-journal — merged
- **A1** auto-explain — merged
- **A2** auto-risk-review — merged (PR #267)
- **B** MCP server scaffolding — `in-progress` (per roadmap; resources + tools shipped previously)
- **B1** MCP JSON-RPC framing — `proposed` ← next LLM-side slice
  - Decision needed before starting: `fastmcp` (FastAPI-native) vs official `mcp` SDK (canonical, biases stdio transport). SSE vs Streamable HTTP transport. Soft transition (keep REST routes alive) vs hard cut.

### Ops (`docs/roadmap-ops.md`)
- **O1** SOPS decrypt-at-boot — `proposed`, operator-owned. ~150 LOC + entrypoint shim. Would mount age key into containers + decrypt SOPS env inline before FastAPI boots.
- **O2** IB Gateway production cutover — `in-progress` (overlay shipped, paper account validation pending IBKR-side, credentials now correct per PR #268).
- **O3** image-supply-chain — earlier work in this area already pinned digests.
- **O4** dual-daemon — **merged 2026-05-18** (PRs #265 + #266).
- **O5** per-mode strategy gating — `proposed`. ~250 LOC + migration. Adds `Strategy.enabled_modes: list[str]`.
- **O6** strategy health observability — `proposed`. ~400 LOC + migration. `last_run_at`, `last_error_text`, `signals_today`, perf aggregates.
- **O7** trades-filters + shadow mode — `proposed`. ~500 LOC + migration + filter component. Prereq: O4 (done).

### UI (`docs/roadmap-ui.md`)
- **U1** Symbol search autocomplete — `proposed`. ~250 LOC + new `GET /api/v1/symbols/search` + bundled tickers.
- **U2** Audit-trail viewer — `proposed`. Small (~80 LOC). `AuditTrailViewer.svelte` already exists; just needs wiring into brief detail page + the JSON-dump removal.
- **U3** Investment recommendation styling — `proposed (partial)`. Promote `## Recommendation` to a card with colored action chip.
- **U4** Search highlight + recent dedup — `proposed`. Tiny (~30 LOC) — reorder recents on revisit, cap at 5.
- **U5** Full app English translation — `proposed`. Mechanical, ~50 strings × 20 files.
- **U6** Light theme implementation — `proposed (stubbed)`. ~50 LOC CSS + OKLCH contrast audit; toggle exists but no-op until palette is defined.
- **U-next-1** mode chips — **merged 2026-05-18** (PR #265).
- **U-next-2** Order timeline + variant — **merged 2026-05-18** (PR #270).
- **U-next-3** Filter panel — `proposed`, folded into O7.

## Recommended next-slice picks (by ease-of-ship × leverage)

1. **U4** (recent dedup) — ~30 LOC, no API, no design decisions. Quickest win.
2. **U2** (audit-trail viewer) — ~80 LOC, route already exists, frontend-only.
3. **U3** (recommendation card) — ~100 LOC, frontend-only, design constrained by existing markdown structure.
4. **U5** (English translation) — mechanical sweep, but spans many files; do as a single PR.
5. **U6** (light theme) — needs OKLCH audit + manual screenshot pass; do after operator has time to review visual output.
6. **O1** (SOPS-at-boot) — operator-owned, ask before starting.
7. **O5** / **O6** / **O7** / **U1** / **B1** — each needs a fresh session and at least one design decision before code.

## Pinned facts for future sessions

- **IBKR credentials layout** (memory: `project_ibkr_credentials_layout.md`):
  - Paper portal login = `arturoramirez6` / `halamadrid6`
  - Paper account ID = `DUR071858`
  - Live portal login = `arturo6ramirez` / `Tostada6!`
  - Live account ID = `U12492989`
  - `okqtbz074` was the IBKR auto-generated paper-trading login; **not** used by gnzsnz/ib-gateway. Don't put it back as `IBKR_USERNAME`.
- **Pytest CI is collect-only** (memory `project_ci_pytest_collect_only.md`) — green CI ≠ tests pass. Run locally with `c:/Projects/iguanatrader/.venv/Scripts/python -m pytest <path>` before pushing.
- **Web test failure on main** in `tests/research-tab.test.ts` (`FIFO with newest-first` assertion in `caps the persisted list at 8 entries`) — pre-existing, unrelated to recent slices. Confirmed by running tests on `main` with no local changes.
- **SOPS on Windows**: use `SOPS_AGE_KEY_FILE="C:/Users/Arturo/.config/sops/age/keys.txt"` for decrypt; for encrypt outside the repo (e.g. `/tmp` plaintext), pass `--age age10nqq3zd2t88nzym3wr95ju5rt0la9m3363sdnm8xfx44davzg4hqk0qh00` explicitly — the `.sops.yaml` `path_regex` resolver fails on out-of-repo paths.
- **Migration numbers**: next available is `0032`. Recent history: 0026 tenant_trading_modes, 0027 daemon_heartbeats, 0028 trade_proposal_state, 0029 reconcile_marker, 0030 exit_reason_ibkr_reconcile, 0031 trade_proposal_risk_review.
- **Operator preference** (memory `feedback_no_mid_flow_confirmation.md`): once greenlit, commit per task and roll without "¿commito? / ¿sigo?" check-ins.
- **Branch naming**: `slice/<short-name>` for feature work, `chore/<short-name>` for doc-only or lint-only. PR squash-merge with branch deletion.

## Operator-side TODO post-deploy

When operator has time on the VPS (`cx43`):

1. Pull main; `docker compose -f compose/mvp.yml -f compose/ibgateway.yml -f compose/mvp.override.yml pull` + `up -d --build` to roll the dual-daemon configuration.
2. Source `.secrets/paper.env.enc` (decrypted) into env; verify `ib-gateway-paper` boots + VNC 5900 reachable.
3. Validate paper daemon: `curl /api/v1/status` returns paper enabled + heartbeat fresh.
4. Toggle paper on → confirm propose-cron fires; toggle off → confirm pending proposals drain.
5. Then live: source `live.env.enc`, bring up `ib-gateway-live` (port 4001, VNC 5901), confirm 2FA flow via VNC, paper→live toggle through `/settings`.
6. Bring-up runbook at `docs/runbooks/ibkr-gateway-bringup.md §7`.

## How to start the next session

```
git checkout main
git pull --ff-only
# Pick a slice from "Recommended next-slice picks" above
git checkout -b slice/<name>
```

Or paste this whole file as the first message and tell Claude which slice to start.
