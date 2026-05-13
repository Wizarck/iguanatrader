"""Integration tests for the slice ``auth-change-password`` HTTP surface.

Five cases (proposal §Tests):

1. Happy: 204 + flag cleared + hash rotated + password_changed_at set.
2. Old wrong → 401 RFC 7807 ``auth-mismatch``.
3. New <12 chars → 400 ``validation``.
4. New == old → 400 ``validation``.
5. ``must_change_password=TRUE`` user gets 403 on a gated route until
   they change.

All cases run against the same in-process FastAPI app the slice 4 tests
use (per ``conftest.py``). The seeded user starts with
``must_change_password=False`` so the change-password route itself is
reachable; case 5 explicitly flips the flag via raw SQL to test the
gate.
"""

from __future__ import annotations

from uuid import UUID

from httpx import AsyncClient
from iguanatrader.api.auth import verify_password
from iguanatrader.persistence import User
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .conftest import SEEDED_PLAINTEXT_PASSWORD, SEEDED_USER_EMAIL


async def _login(client: AsyncClient) -> None:
    """Helper: login the seeded user so subsequent requests carry the cookie."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": SEEDED_USER_EMAIL, "password": SEEDED_PLAINTEXT_PASSWORD},
    )
    assert resp.status_code == 200, resp.text


# --------------------------------------------------------------------------- #
# 1 — happy path
# --------------------------------------------------------------------------- #


async def test_change_password_happy_204_flag_cleared_hash_rotated(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Pre-condition: force the flag on so we also assert it gets cleared.
    user_uuid = UUID(seeded_tenant_user["user_id"])
    async with schema_session_factory() as s:
        await s.execute(
            text("UPDATE users SET must_change_password = 1 WHERE id = :uid"),
            {"uid": user_uuid.hex},
        )
        await s.commit()

    await _login(client)

    new_password = "brand-new-pw-9!"
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={
            "old_password": SEEDED_PLAINTEXT_PASSWORD,
            "new_password": new_password,
        },
    )
    assert resp.status_code == 204, resp.text
    assert resp.content == b""

    async with (
        with_tenant_context(UUID(seeded_tenant_user["tenant_id"])),
        schema_session_factory() as s,
    ):
        row = (await s.execute(select(User).where(User.id == user_uuid))).scalars().first()
        assert row is not None
        assert row.must_change_password is False
        assert row.password_changed_at is not None
        # New hash verifies new plaintext; old plaintext NO longer verifies.
        assert verify_password(new_password, row.password_hash)
        assert not verify_password(SEEDED_PLAINTEXT_PASSWORD, row.password_hash)


# --------------------------------------------------------------------------- #
# 2 — wrong old password
# --------------------------------------------------------------------------- #


async def test_change_password_wrong_old_returns_401_auth_mismatch(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
) -> None:
    await _login(client)

    resp = await client.post(
        "/api/v1/auth/change-password",
        json={
            "old_password": "definitely-not-the-current-password",
            "new_password": "valid-new-pw-9!",
        },
    )
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 401
    assert body["type"] == "urn:iguanatrader:error:auth-mismatch"
    assert "current password" in body["detail"].lower()


# --------------------------------------------------------------------------- #
# 3 — new password too short
# --------------------------------------------------------------------------- #


async def test_change_password_new_too_short_returns_400_validation(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
) -> None:
    await _login(client)

    resp = await client.post(
        "/api/v1/auth/change-password",
        json={
            "old_password": SEEDED_PLAINTEXT_PASSWORD,
            "new_password": "short1!",  # 7 chars
        },
    )
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 400
    assert body["type"] == "urn:iguanatrader:error:validation"
    assert "12 characters" in body["detail"]


# --------------------------------------------------------------------------- #
# 4 — new == old
# --------------------------------------------------------------------------- #


async def test_change_password_new_equals_old_returns_400_validation(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
) -> None:
    await _login(client)

    resp = await client.post(
        "/api/v1/auth/change-password",
        json={
            "old_password": SEEDED_PLAINTEXT_PASSWORD,
            "new_password": SEEDED_PLAINTEXT_PASSWORD,
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["type"] == "urn:iguanatrader:error:validation"
    assert "different" in body["detail"].lower()


# --------------------------------------------------------------------------- #
# 5 — gate fires on a non-allow-listed route until the user changes
# --------------------------------------------------------------------------- #


async def test_must_change_password_gates_portfolio_route(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Flip the flag on.
    user_uuid = UUID(seeded_tenant_user["user_id"])
    async with schema_session_factory() as s:
        await s.execute(
            text("UPDATE users SET must_change_password = 1 WHERE id = :uid"),
            {"uid": user_uuid.hex},
        )
        await s.commit()

    await _login(client)

    # Hitting any gated route → 403 RFC 7807 ``password-change-required``.
    gated = await client.get("/api/v1/portfolio/summary")
    assert gated.status_code == 403
    assert gated.headers["content-type"].startswith("application/problem+json")
    body = gated.json()
    assert body["status"] == 403
    assert body["type"] == "urn:iguanatrader:error:password-change-required"

    # /auth/me is allow-listed → still 200 + ``must_change_password=true``.
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True

    # Change the password → 204.
    new_password = "fresh-rotation-9!"
    rotate = await client.post(
        "/api/v1/auth/change-password",
        json={
            "old_password": SEEDED_PLAINTEXT_PASSWORD,
            "new_password": new_password,
        },
    )
    assert rotate.status_code == 204, rotate.text

    # Re-hit the previously-gated route → no longer gated.
    # NOTE: portfolio is a 501 stub at this slice's time, but the wire
    # contract is "any non-403 status proves the gate is no longer
    # firing" — once the rotation lands, the gate steps aside and the
    # native route handler runs.
    post_rotate = await client.get("/api/v1/portfolio/summary")
    assert post_rotate.status_code != 403
    # /auth/me now reports the flag cleared.
    me_after = await client.get("/api/v1/auth/me")
    assert me_after.status_code == 200
    assert me_after.json()["must_change_password"] is False
