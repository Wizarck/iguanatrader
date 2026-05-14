# Proposal: auth-password-aging-warning

> **Add a "rotate your password" banner** when `password_changed_at < NOW() - 90d`. Per the [auth-change-password retro](../../../retros/auth-change-password.md) carry-forward. Soft warning — not a forced rotation. Operators on hardened deployments can act; permissive deployments stay frictionless.

## Why

`migrations/versions/0013_user_password_metadata.py` added `password_changed_at TIMESTAMP NULL` to `users` in the auth-change-password slice (PR #132). The intent (per retro carry-forward) was "surface a banner once the field crosses 90 days old". The data is captured but never read.

A 90-day rotation cadence is the canonical baseline for NIST SP 800-63B + most internal-security policies. Iguanatrader is a single-operator personal tool today, but the user runs other production stacks (eligia-core, palafito-b2b) where the same auth backbone is reused; the banner pattern travels with the auth slice when the codebase forks.

## What

### Backend: aging classifier in deps

`apps/api/src/iguanatrader/api/deps.py` — extend the `get_current_user` dependency to compute one extra field on the returned `AuthenticatedUser`:

```python
@dataclass(frozen=True)
class AuthenticatedUser:
    ...
    password_age_days: int | None  # None if password_changed_at is null (legacy)
    password_aging_state: Literal["fresh", "ageing", "stale"]
```

Classifier:
- `password_changed_at is None` → `password_age_days = None`, `password_aging_state = "fresh"` (legacy users grandfather in).
- `0 <= age_days < 60` → `"fresh"`.
- `60 <= age_days < 90` → `"ageing"` (heads-up banner).
- `age_days >= 90` → `"stale"` (action-requested banner).

The boundaries (60/90) are configurable via env vars:

- `IGUANATRADER_AUTH_PASSWORD_AGEING_DAYS` (default `60`).
- `IGUANATRADER_AUTH_PASSWORD_STALE_DAYS` (default `90`).

### API: surface in `/me`

`apps/api/src/iguanatrader/api/dtos/auth.py::MeOut` — add two optional fields:

```python
password_age_days: int | None = None
password_aging_state: Literal["fresh", "ageing", "stale"] = "fresh"
```

`apps/api/src/iguanatrader/api/routes/auth.py::me_endpoint` — pass them through from `AuthenticatedUser`.

### Frontend: dashboard banner

`apps/web/src/lib/components/PasswordAgeingBanner.svelte` — new component:

```svelte
<script lang="ts">
  let { ageingState, ageDays }: { ageingState: 'fresh' | 'ageing' | 'stale'; ageDays: number | null } = $props();
</script>

{#if ageingState === 'ageing'}
  <div role="status" class="banner warning">
    Your password is {ageDays} days old — consider rotating it.
    <a href="/account/change-password">Change password →</a>
  </div>
{:else if ageingState === 'stale'}
  <div role="alert" class="banner danger">
    Your password is {ageDays} days old. Please rotate it.
    <a href="/account/change-password">Change password →</a>
  </div>
{/if}
```

OKLCH design tokens: `warning` uses `--accent`, `danger` uses `--destructive`. Both inherit the existing card border-radius / padding rhythm.

Mount at the top of the `(app)/+layout.svelte` so the banner appears across every dashboard tab. Use the existing `me` server load:

```svelte
{#if data.me.password_aging_state !== 'fresh'}
  <PasswordAgeingBanner
    ageingState={data.me.password_aging_state}
    ageDays={data.me.password_age_days}
  />
{/if}
```

### Tests

#### Backend

`apps/api/tests/unit/api/test_deps_password_aging.py`:

1. `test_password_aging_state_fresh_when_null` — `password_changed_at is None` → `state="fresh"`, `age_days=None`.
2. `test_password_aging_state_fresh_when_recent` — 30 days old → `"fresh"`.
3. `test_password_aging_state_ageing_at_threshold` — 60 days old → `"ageing"`.
4. `test_password_aging_state_stale_at_threshold` — 90 days old → `"stale"`.
5. `test_password_aging_state_respects_env_overrides` — set `IGUANATRADER_AUTH_PASSWORD_AGEING_DAYS=30` and `_STALE_DAYS=60`; verify boundaries shift.

`apps/api/tests/integration/test_me_endpoint.py` (or extend existing) — exercise the wire-up:

6. `test_me_endpoint_returns_password_aging_state` — seed a user with `password_changed_at = NOW() - 95d`, hit `/api/v1/me`, assert `password_aging_state == "stale"` and `password_age_days == 95`.

#### Frontend

`apps/web/tests/password-ageing-banner.test.ts` — Vitest unit tests for the component:

1. `renders nothing when fresh` — `ageingState="fresh"` → no banner DOM.
2. `renders warning banner when ageing` — `"ageing"` + age=65 → `role="status"`, text contains "65 days".
3. `renders danger banner when stale` — `"stale"` + age=95 → `role="alert"`, text contains "Change password".
4. `link points to /account/change-password` in both states.

A Lighthouse a11y check on the dashboard layout will catch any contrast / role issues.

## Out of scope

- **Forced rotation after N days** — covered by the existing `must_change_password` flag (operator can set it via DB or admin CLI). This slice is the soft warning before that hammer falls.
- **Email/Telegram nag** — out of v1.5. Operators see the banner when they log in; that's sufficient.
- **Per-user threshold override** — same threshold for every tenant. Per-tenant `risk_caps`-style config slot deferred to v2.
- **Last-login pinging** — banners only fire on the next dashboard load. We don't push notifications.
- **Mobile / API-only consumers** — banner is dashboard-only. API consumers can read `/me.password_aging_state` and decide whether to render their own warning.

## Acceptance

- `AuthenticatedUser` gains `password_age_days` + `password_aging_state`.
- `MeOut` surfaces both.
- `PasswordAgeingBanner.svelte` renders conditionally on the dashboard layout.
- 6 backend tests + 4 frontend tests pass.
- mypy --strict + ruff + black clean.
- Lighthouse a11y on dashboard stays >= 95 with the banner visible.
- Env overrides documented in `docs/configuration.md` (or wherever env vars are catalogued).
