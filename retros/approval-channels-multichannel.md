# Retrospective: approval-channels-multichannel (slice P1)

- **Archived**: 2026-05-06
- **Archive path**: openspec/changes/archive/2026-05-06-approval-channels-multichannel/
- **Schema**: spec-driven
- **PR**: #71 (squash-merged 2026-05-06; CI 13/14 green incl. AI-self-review; CodeRabbit L1 still in progress at merge but L2 fallback passed within 5min window per §4.5)

## What worked

- **17-command registry built at import via `pkgutil.iter_modules`.** Adding a command is one new `commands/<name>.py` file exporting `SPEC: CommandSpec` — zero per-channel adapter edits. `assert_canonical()` enforces "exactly 17 entries" so any drift (PR adds new file but forgets the registry whitelist) fails CI immediately. Cross-channel parity (FR37) is enforced by construction, not discipline.
- **Stub-only transports (D8 deferred wire clients).** Slice P1 ships `FakeTelegramTransport` + `FakeHermesTransport` exercising the contract end-to-end (idempotency, audit, heartbeat, dispatch) but defers the real wire clients to a follow-up `approval-channels-real-clients` slice. Test surface stays fast (no `python-telegram-bot` import, no Meta credentials), but the contract is fully validated. Documented in gotcha #51 + runbook so this isn't mistaken for production-readiness.
- **Authorized-sender silent-drop.** Inbound from non-whitelisted senders is dropped with no echo, no error reply, no enumeration surface. Only a structlog event with the SHA-256 hashed external_id is emitted server-side. Documented in gotcha #50 — by-design, never to be "fixed".

## What didn't

- **mypy --strict surface mismatch between slice scope and full apps/api/.** Six errors in test files only surfaced when CI runs `mypy --strict apps/api/` (broader scope). The local pre-flight `mypy --strict apps/api/src/iguanatrader/contexts/approval/` was clean. Future slices should run the full apps/api/ scope before pushing.
  - 4× sync `yield` fixtures annotated as `AsyncIterator[None]` → corrected to `Iterator[None]`.
  - 1× `dict[str, object]` heterogeneous unpacking → cast at call site.
  - 1× comparison-overlap from mypy narrowing (state field after `mark_disconnected()`) → targeted `# type: ignore[comparison-overlap]`.
- **Force-push twice during one PR lifecycle.** Initial push → mypy fail → fix → push. Then K1 merged on main mid-stream → P1 had to rebase + force-push a second time. Both rebases triggered conflicts on `contexts/__init__.py`, `apps/api/README.md`, `docs/gotchas.md` — predictable but tedious.
- **CodeRabbit L1 review can take longer than the L2 5-min window.** PR was mergeable on UNSTABLE state because the 7 required status checks all pass; L1 was still "Review in progress" but L2 fallback covered it within the window. The §4.5 contract handles this correctly; just a note for future merges that "CodeRabbit pending" is not a blocker by itself.

## Lessons

- **Pre-flight mypy at the broadest scope CI uses.** `mypy --strict apps/api/` (not just the slice subdir) catches test-file errors that only manifest at the broader scope. Add this to the slice-prompt's "before pushing" checklist.
- **Plan for back-to-back rebases when shipping siblings.** Wave-2-style sibling slices that both touch `contexts/__init__.py`, `README.md`, `gotchas.md`, `shared/errors.py` will conflict at every merge. Either: (a) coordinate ranges in the slice-prompt (e.g., R1: gotchas 40-49, T1: 50-59, K1: 60-69, P1: 70-79), or (b) merge sequentially with explicit "rebase + force-push" between each pair.
- **The §4.5 contract scales without manual intervention.** With branch protection's `required_pull_request_reviews` removed, two PRs (T1, K1) merged automatically once CI + AI-self-review passed. P1 is the third — confirms the autopilot pattern works for the developer-of-one workflow.

## Carry-forward to next change

- **Allocate gotcha numbering ranges in the slice-prompt** to avoid the renumbering tax — proposal: each slice claims a 10-number block, declared in the slice-prompt.
- **Add a `mypy --strict apps/api/` pre-push check** to slice contributor docs (or a pre-commit hook scoped to the broader path).
- **Document the L2 fallback timing** in release-management.md §4.5 — "CodeRabbit L1 may run longer than L2's 5-min window; merge is allowed when required-checks pass and L2 covered the AI-self-review surface".
