"""Integration tests for ``GET /api/v1/auth/me``.

Slice ``auth-password-aging-warning``: assert the wire-up from
:func:`iguanatrader.api.deps.get_current_user`'s classifier through
``request.state`` and out as :class:`MeResponse` fields.

The shared in-process FastAPI app + on-disk SQLite + seeded tenant/user
fixtures live in ``conftest.py``; we lean on the same
``seeded_tenant_user`` and ``client`` fixtures used by
``test_auth_flow.py`` so the request shape (cookie flags, Set-Cookie,
JSON body) matches a real browser login.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .conftest import SEEDED_PLAINTEXT_PASSWORD, SEEDED_USER_EMAIL


async def _login(client: AsyncClient) -> None:
    """Helper: login the seeded user so subsequent requests carry the cookie."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": SEEDED_USER_EMAIL, "password": SEEDED_PLAINTEXT_PASSWORD},
    )
    assert resp.status_code == 200, resp.text


async def test_me_endpoint_returns_password_aging_state_stale(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Seed ``password_changed_at = NOW() - 95d`` → ``/me`` reports stale.

    Slice ``auth-password-aging-warning`` integration sanity check:
    classifier + request.state + MeResponse field round-trip end-to-end.
    Age must be ``>= 90`` to land in the ``stale`` band (the default
    threshold per :data:`_DEFAULT_PASSWORD_STALE_DAYS`).
    """
    user_uuid = UUID(seeded_tenant_user["user_id"])
    # Plant a 95-day-old password_changed_at via raw SQL — the column was
    # NULL on initial seed. Use a timezone-aware UTC datetime; SQLite
    # stores via ISO string and the column declaration is
    # ``DateTime(timezone=True)``.
    ninety_five_days_ago = datetime.now(tz=UTC) - timedelta(days=95)
    async with schema_session_factory() as s:
        await s.execute(
            text("UPDATE users SET password_changed_at = :pca WHERE id = :uid"),
            {"pca": ninety_five_days_ago.isoformat(), "uid": user_uuid.hex},
        )
        await s.commit()

    await _login(client)

    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert payload["password_aging_state"] == "stale"
    # ``age_days`` may be 94 or 95 depending on the second-of-day at which
    # the test runs vs. the planted timestamp (we plant exactly 95 * 86400
    # seconds ago; ``int(delta.total_seconds() // 86400)`` floors to 95
    # only if no time elapsed during the test). Assert the value is in
    # the expected 94/95 band so the test is robust to wall-clock drift.
    assert payload["password_age_days"] in (94, 95)
