"""Integration tests for the slice 4 ``auth-jwt-cookie`` HTTP surface.

Each test runs against a fresh in-process FastAPI app (per the
``client`` fixture in :mod:`conftest`) backed by a fresh on-disk
SQLite database. The tests cover the spec scenarios in
``openspec/changes/auth-jwt-cookie/specs/web-authentication/spec.md``:

* Successful login + cookie flags + ``/me`` round-trip + logout (4.1).
* Wrong password vs email-not-found return uniform 401 + timing
  parity (4.2).
* Rate-limit returns 429 + ``Retry-After`` after 5 attempts (4.3).
* Zero-tenant bootstrap returns 503 (4.4).
* JWT auto-rotation attaches ``Set-Cookie`` near expiry (4.5).
* 7-day cookie ceiling returns 401 even with otherwise-valid JWT (4.6).
* :func:`requires_role` factory gates by role (4.7).
"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from iguanatrader.api import deps as api_deps
from iguanatrader.api.auth import (
    COOKIE_CEILING_SECONDS,
    JWT_DEFAULT_EXP_SECONDS,
    Role,
    encode_jwt,
    hash_password,
)
from iguanatrader.api.deps import COOKIE_NAME, requires_role
from iguanatrader.persistence import Tenant, User
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .conftest import (
    SEEDED_PLAINTEXT_PASSWORD,
    SEEDED_USER_EMAIL,
)

# --------------------------------------------------------------------------- #
# 4.1 — login → /me → logout
# --------------------------------------------------------------------------- #


async def test_login_success_sets_cookie_and_me_round_trips(
    client: AsyncClient, seeded_tenant_user: dict[str, str]
) -> None:
    # Login.
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": SEEDED_USER_EMAIL, "password": SEEDED_PLAINTEXT_PASSWORD},
    )
    assert resp.status_code == 200
    assert resp.json() == {"redirect_to": "/"}

    # Cookie flags (parse the raw Set-Cookie header).
    set_cookie_header = resp.headers.get("set-cookie", "")
    assert COOKIE_NAME in set_cookie_header
    assert "HttpOnly" in set_cookie_header
    assert "Secure" in set_cookie_header
    assert "samesite=strict" in set_cookie_header.lower()
    assert f"Max-Age={COOKIE_CEILING_SECONDS}" in set_cookie_header
    # Domain unset (default = exact host).
    assert "Domain=" not in set_cookie_header

    # /me round-trip.
    me_resp = await client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200
    payload = me_resp.json()
    assert payload["user_id"] == seeded_tenant_user["user_id"]
    assert payload["tenant_id"] == seeded_tenant_user["tenant_id"]
    assert payload["email"] == SEEDED_USER_EMAIL
    assert payload["role"] == "tenant_user"
    assert "password_hash" not in payload

    # Logout clears the cookie.
    logout_resp = await client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 200
    logout_set_cookie = logout_resp.headers.get("set-cookie", "")
    assert COOKIE_NAME in logout_set_cookie
    assert "Max-Age=0" in logout_set_cookie

    # /me after logout → 401. httpx auto-applied the cleared cookie;
    # explicitly drop our jar to be deterministic.
    client.cookies.clear()
    after_logout = await client.get("/api/v1/auth/me")
    assert after_logout.status_code == 401


# --------------------------------------------------------------------------- #
# 4.2 — uniform 401 + timing parity
# --------------------------------------------------------------------------- #


async def test_login_wrong_password_returns_401_uniform_with_not_found(
    client: AsyncClient, seeded_tenant_user: dict[str, str]
) -> None:
    """Wrong-password and email-not-found return identical body shapes;
    both run an Argon2id verify (timing parity within ~50% tolerance —
    the verify dominates the response time)."""

    # Wrong password.
    t0 = time.perf_counter()
    wrong_pw = await client.post(
        "/api/v1/auth/login",
        json={"email": SEEDED_USER_EMAIL, "password": "definitely-not-the-password"},
    )
    elapsed_wrong = time.perf_counter() - t0
    assert wrong_pw.status_code == 401
    assert wrong_pw.headers["content-type"].startswith("application/problem+json")
    assert "set-cookie" not in wrong_pw.headers

    # Email not found.
    t1 = time.perf_counter()
    not_found = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "irrelevant"},
    )
    elapsed_nf = time.perf_counter() - t1
    assert not_found.status_code == 401
    assert not_found.headers["content-type"].startswith("application/problem+json")

    # Body shapes match (no field distinguishing the two cases).
    assert wrong_pw.json() == not_found.json()

    # Soft timing parity — within 50% of each other (Argon2id dominates;
    # CI noise can stretch one side by ~20-30%, hence the loose bound).
    ratio = max(elapsed_wrong, elapsed_nf) / max(min(elapsed_wrong, elapsed_nf), 1e-6)
    assert ratio < 2.0, f"timing diverged too much: {elapsed_wrong=} {elapsed_nf=}"


# --------------------------------------------------------------------------- #
# 4.3 — rate-limit
# --------------------------------------------------------------------------- #


async def test_login_rate_limited_after_5_attempts(
    client: AsyncClient, seeded_tenant_user: dict[str, str]
) -> None:
    payload = {"email": SEEDED_USER_EMAIL, "password": "wrong-password"}

    # 5 wrong-password attempts succeed-as-401 (limit not breached yet).
    for _ in range(5):
        r = await client.post("/api/v1/auth/login", json=payload)
        assert r.status_code == 401

    # 6th attempt hits the limit.
    sixth = await client.post("/api/v1/auth/login", json=payload)
    assert sixth.status_code == 429
    assert sixth.headers["content-type"].startswith("application/problem+json")
    assert "Retry-After" in sixth.headers
    body = sixth.json()
    assert body["status"] == 429
    assert body["type"] == "urn:iguanatrader:error:rate-limit"


async def test_login_rate_limit_is_per_tuple_not_per_ip(
    client: AsyncClient, seeded_tenant_user: dict[str, str]
) -> None:
    # Burn the limit for email_a.
    for _ in range(5):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "burned@example.com", "password": "x"},
        )
        # 401 because email-not-found runs the dummy verify.
        assert r.status_code == 401

    # email_a is now rate-limited.
    burned = await client.post(
        "/api/v1/auth/login",
        json={"email": "burned@example.com", "password": "x"},
    )
    assert burned.status_code == 429

    # Different email under the same client (same IP) is NOT yet limited.
    fresh = await client.post(
        "/api/v1/auth/login",
        json={"email": SEEDED_USER_EMAIL, "password": SEEDED_PLAINTEXT_PASSWORD},
    )
    assert fresh.status_code == 200


# --------------------------------------------------------------------------- #
# 4.4 — zero-tenant bootstrap
# --------------------------------------------------------------------------- #


async def test_zero_tenant_bootstrap_returns_503(
    client: AsyncClient,
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No Tenant rows yet → 503 with RFC 7807 Problem Detail body."""
    # No seeded_tenant_user fixture — schema is bare.
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "anyone@example.com", "password": "irrelevant"},
    )
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 503
    # Slice 5 (api-foundation-rfc7807) D9 canonicalises the type URI
    # scheme from the slice-4 URL form to the project-wide urn form.
    assert body["type"] == "urn:iguanatrader:error:not-bootstrapped"
    assert body["title"] == "Service Not Bootstrapped"
    assert "iguanatrader admin bootstrap-tenant" in body["detail"]


# --------------------------------------------------------------------------- #
# 4.5 — JWT auto-rotation
# --------------------------------------------------------------------------- #


async def test_jwt_rotation_attaches_set_cookie_on_near_expiry_request(
    client: AsyncClient, seeded_tenant_user: dict[str, str]
) -> None:
    """A request whose JWT exp is within 30 min of now triggers rotation."""
    now = int(time.time())
    near_expiry_token = encode_jwt(
        {
            "sub": seeded_tenant_user["user_id"],
            "tenant_id": seeded_tenant_user["tenant_id"],
            "role": "tenant_user",
            "login_at": now,  # fresh session — ceiling NOT reached
        },
        exp_seconds=25 * 60,  # 25 min < 30 min rotation threshold
    )
    client.cookies.set(COOKIE_NAME, near_expiry_token)

    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert COOKIE_NAME in set_cookie, "rotation should attach Set-Cookie"
    # The new cookie's Max-Age is the remaining cookie ceiling (now - login_at = 0
    # → max_age == COOKIE_CEILING_SECONDS).
    assert f"Max-Age={COOKIE_CEILING_SECONDS}" in set_cookie


# --------------------------------------------------------------------------- #
# 4.6 — 7-day cookie ceiling
# --------------------------------------------------------------------------- #


async def test_7day_ceiling_returns_401_even_with_valid_jwt(
    client: AsyncClient, seeded_tenant_user: dict[str, str]
) -> None:
    """JWT may be otherwise-valid but if login_at was ≥ 7d ago → 401."""
    now = int(time.time())
    expired_session_token = encode_jwt(
        {
            "sub": seeded_tenant_user["user_id"],
            "tenant_id": seeded_tenant_user["tenant_id"],
            "role": "tenant_user",
            "login_at": now - COOKIE_CEILING_SECONDS - 60,  # 7d 1min ago
        },
        exp_seconds=JWT_DEFAULT_EXP_SECONDS,  # JWT itself is fresh
    )
    client.cookies.set(COOKIE_NAME, expired_session_token)

    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# 4.7 — role gating via requires_role
# --------------------------------------------------------------------------- #


async def test_role_gating_tenant_user_vs_god_admin(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """tenant_user gets 403, god_admin gets 200 on a god_admin-gated route."""
    # Seed both users + their tenants. Tenant inserts are cross-tenant
    # (NOT scoped); User inserts MUST run under with_tenant_context so
    # the slice-3 listener's _stamp_tenant_on_inserts finds the tenant.
    tu_tenant_uuid = uuid4()
    ga_tenant_uuid = uuid4()
    tu_user_uuid = uuid4()
    ga_user_uuid = uuid4()
    pw_hash = hash_password(SEEDED_PLAINTEXT_PASSWORD)

    async with schema_session_factory() as s:
        s.add_all(
            [
                Tenant(id=tu_tenant_uuid, name="tu-tenant", feature_flags={}),
                Tenant(id=ga_tenant_uuid, name="ga-tenant", feature_flags={}),
            ]
        )
        await s.commit()

    async with with_tenant_context(tu_tenant_uuid), schema_session_factory() as s:
        s.add(
            User(
                id=tu_user_uuid,
                tenant_id=tu_tenant_uuid,
                email="tu@example.com",
                password_hash=pw_hash,
                role="tenant_user",
            )
        )
        await s.commit()

    async with with_tenant_context(ga_tenant_uuid), schema_session_factory() as s:
        s.add(
            User(
                id=ga_user_uuid,
                tenant_id=ga_tenant_uuid,
                email="ga@example.com",
                password_hash=pw_hash,
                role="god_admin",
            )
        )
        await s.commit()

    # Build an app with a stub route gated by requires_role(Role.god_admin).
    from iguanatrader.api.app import create_app

    app: FastAPI = create_app()

    @app.get("/_test/god-only")
    async def _god_only(user: Any = Depends(requires_role(Role.god_admin))) -> dict[str, str]:
        return {"role": user.role}

    async def _override_get_db() -> Any:
        async with schema_session_factory() as s:
            yield s

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="https://test") as c:
        # tenant_user → 403.
        tu_token = encode_jwt(
            {
                "sub": str(tu_user_uuid),
                "tenant_id": str(tu_tenant_uuid),
                "role": "tenant_user",
                "login_at": int(time.time()),
            }
        )
        c.cookies.set(COOKIE_NAME, tu_token)
        tu_resp = await c.get("/_test/god-only")
        assert tu_resp.status_code == 403

        # god_admin → 200.
        c.cookies.clear()
        ga_token = encode_jwt(
            {
                "sub": str(ga_user_uuid),
                "tenant_id": str(ga_tenant_uuid),
                "role": "god_admin",
                "login_at": int(time.time()),
            }
        )
        c.cookies.set(COOKIE_NAME, ga_token)
        ga_resp = await c.get("/_test/god-only")
        assert ga_resp.status_code == 200
        assert ga_resp.json() == {"role": "god_admin"}


# --------------------------------------------------------------------------- #
# Bonus: missing cookie → 401
# --------------------------------------------------------------------------- #


async def test_me_without_cookie_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Bonus: tampered JWT → 401
# --------------------------------------------------------------------------- #


async def test_me_with_tampered_jwt_returns_401(
    client: AsyncClient, seeded_tenant_user: dict[str, str]
) -> None:
    token = encode_jwt(
        {
            "sub": seeded_tenant_user["user_id"],
            "tenant_id": seeded_tenant_user["tenant_id"],
            "role": "tenant_user",
            "login_at": int(time.time()),
        }
    )
    head, payload, sig = token.rsplit(".", 2)
    tampered = f"{head}.{payload}.{'A' if sig[0] != 'A' else 'B'}{sig[1:]}"
    client.cookies.set(COOKIE_NAME, tampered)

    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
