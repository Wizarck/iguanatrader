# Retrospective: auth-password-aging-warning

- **PR**: [#164](https://github.com/Wizarck/iguanatrader/pull/164) (merged 2026-05-15, squash `3a09c91`).
- **Archive path**: `openspec/changes/archive/2026-05-15-auth-password-aging-warning/`
- **Lines shipped**: 628 insertions / 11 deletions across 12 files (backend + frontend + tests + docs).

## What worked

- **Carry-forward closed cleanly** — direct follow-up from auth-change-password retro. Operators get a soft nag without enforcing rotation; threshold env-overridable.
- **`request.state` for classifier passthrough** — `get_current_user` runs the classifier once and stashes `password_age_days` + `password_aging_state` on `request.state`. Endpoints read back into DTO. No DB round-trip per /me call beyond what was already there.
- **Pure-helper + component split for banner** — `password-ageing-banner.ts` holds the threshold logic + classification; `PasswordAgeingBanner.svelte` is the impure presentational layer. Pure half is testable without jsdom.
- **Layout-root mount** — `(app)/+layout.svelte` ensures the banner appears on every authed page, not just dashboard.

## What didn't

- **Agent hit org monthly usage limit at task 10** — completed implementation + tests + docs (tasks 1-9) but stopped before final lint/test/push. Parent (me) took over, ran scoped lints + pytest, found 1 failing integration test, diagnosed + fixed, committed + pushed + opened PR. Recovery: ~10 min. Pre-flag: when an agent hits usage-limit mid-slice, the parent can inherit the worktree state and finish without re-spawning.
- **`DeprecationWarning: sqlite3 datetime adapter` escalation** — `filterwarnings=["error"]` in pyproject.toml turns Python 3.13's deprecated default datetime adapter into a hard fail for any test that writes a datetime via raw `text()` SQL. Same class as PR #152 httpx-cookies deprecation. Fixed in this slice by passing `.isoformat()` to the parameter binding; deps.py now defensively handles `password_changed_at` as datetime OR ISO string (SQLite TEXT round-trip).
- **The defensive str/datetime handling is a wart** — ideally the ORM path returns datetime uniformly. The raw `text()` shortcut in the test sidesteps SQLAlchemy's type adapter. Carry-forward: `chore-register-sqlite-datetime-adapter` to make the conversion uniform at the app boundary.

## Carry-forward

- **`chore-register-sqlite-datetime-adapter`** — register a global `sqlite3.register_adapter(datetime, lambda dt: dt.isoformat())` + `sqlite3.register_converter("DATETIME", lambda s: datetime.fromisoformat(s.decode()))` so the ORM and raw-SQL paths agree. Removes the str/datetime defensive code in deps.py.
- **Email/Telegram out-of-band rotation reminders** — current banner is UI-only. v1.5.x if operators want push reminders.
- **Cron-enforced rotation** — banner is the nag, not the wall. v2 if compliance requires hard expiry.

## Pattern usage

- **Agent-resumption-after-usage-limit** — when an agent hits its budget, parent inherits the worktree state. Run `git status` in worktree → identify what's left → finish manually. Avoids re-running tasks 1-9 that already succeeded.
- **`filterwarnings=["error"]` + isolated `text()` SQL = walking minefield** — any deprecated stdlib function called via raw SQL trips the gate. Pre-flag for future tests: use `.isoformat()` for datetimes, explicit conversion for any other type with a deprecated adapter (sqlite3 date / decimal / etc.).
- **Pure-helper + impure-component split (3rd use)** — research-tab-ui's `recent.ts` + this slice's `password-ageing-banner.ts`. Consistent shape across UI features. Promote to playbook §svelte-component-organization if 4th hit.
