# Proposal: test-cookies-pattern-migration

> **Migrate all `apps/api/tests/integration/test_*.py` calls from the deprecated `await client.get(url, cookies={COOKIE_NAME: cookie})` per-request kwarg to the canonical `client.cookies.set(COOKIE_NAME, cookie)` + plain `await client.get(url)` pattern.** Resolves the `httpx`-deprecation-warning → `pytest.filterwarnings=["error"]` escalation that breaks Windows-local test runs.

## Why

`pyproject.toml::filterwarnings = ["error"]` turns httpx's `DeprecationWarning: Setting per-request cookies=... is being deprecated` into a hard failure. CI on Linux happens to not surface it (httpx version pinning quirk), but Windows-local dev hits it on every pytest invocation, blocking confidence.

Two prior slices already hit this:
- **PR #149** (`proposals-list-endpoint`) — agent migrated mid-flight; retro flagged the legacy files as deferred sweep.
- **PR #151** (`market-data-snapshot-port`) — agent's local pytest hit the same wall on the 3 new tests + 5 pre-existing files. Retro promoted this sweep from "nice to have" to "next chore" — Windows-local dev confidence blocker.

The canonical pattern is already in use in `test_proposals_routes.py`, `test_trades_route_smoke.py`, `test_risk_routes.py`, `test_auth_flow.py`. This slice brings the remaining 5 files to parity.

## What

### Migration rule

Replace, in each test function:

```python
# BEFORE
resp = await client.get(URL, cookies={COOKIE_NAME: cookie})
```

with

```python
# AFTER (once per cookie at first use; re-set when cookie changes)
client.cookies.set(COOKIE_NAME, cookie)
resp = await client.get(URL)
```

If a test uses two cookies (cross-tenant assertions, e.g. `cookie_a` for setup → `cookie_b` for negative tests), insert a second `client.cookies.set(COOKIE_NAME, cookie_b)` immediately before the section using the new cookie. `client.cookies.set` overwrites cleanly — no need to delete first.

### Files in scope (5)

1. `apps/api/tests/integration/test_portfolio_routes.py` — 23 call sites
2. `apps/api/tests/integration/test_strategies_routes.py` — 12 call sites
3. `apps/api/tests/integration/test_approval_routes.py` — 3 call sites
4. `apps/api/tests/integration/test_settings_routes.py` — 4 call sites
5. `apps/api/tests/integration/test_trade_routes.py` — 5 call sites

Total: ~47 transformations.

### Out of scope

- **Test logic changes** — purely mechanical kwarg → setter migration. No assertions, fixtures, or seed helpers touched.
- **httpx version bump** — keep the pin as-is; pattern migration is forward-compatible regardless.
- **conftest-level abstraction** — could hoist `client.cookies.set` into a fixture (`authed_client`), but that's a larger surface change deferred to v1.5 `test-fixtures-authed-client` if the pattern keeps proliferating.
- **`test_auth_flow.py`, `test_proposals_routes.py`, `test_trades_route_smoke.py`, `test_risk_routes.py`** — already on the canonical pattern.

### Acceptance

- `pytest apps/api/tests/integration/test_portfolio_routes.py apps/api/tests/integration/test_strategies_routes.py apps/api/tests/integration/test_approval_routes.py apps/api/tests/integration/test_settings_routes.py apps/api/tests/integration/test_trade_routes.py` runs clean on Windows-local (no `DeprecationWarning` escalation).
- CI on Linux remains green (14/14).
- Zero diff in test outcomes (same pass/fail count, same assertions).
