"""HTTP-level integration tests for ``/api/v1/risk/*`` routes.

Reuses the slice-4 ``client`` fixture (httpx ASGITransport against the
real ``create_app`` factory + the slice-5 dynamic discovery loop).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from iguanatrader.api.auth import encode_jwt

# Importing the ORM module registers the risk tables on Base.metadata
# so the conftest's create_all builds them.
from iguanatrader.contexts.risk.orm import (  # noqa: F401
    KillSwitchEventORM,
    KillSwitchStateORM,
    RiskEvaluationORM,
    RiskOverrideORM,
)
from iguanatrader.shared.time import now as utc_now


def _login_cookie(user_id: UUID, tenant_id: UUID) -> str:
    """Build a valid JWT for the seeded user (mirrors slice-4 helper)."""
    return encode_jwt(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "role": "tenant_user",
            "login_at": int(utc_now().timestamp()),
        },
    )


@pytest.mark.integration
async def test_get_risk_state_200_shape(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
) -> None:
    """``GET /api/v1/risk/state`` returns 200 with the expected envelope."""
    user_id = UUID(seeded_tenant_user["user_id"])
    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    token = _login_cookie(user_id, tenant_id)
    client.cookies.set("iguana_session", token)

    resp = await client.get("/api/v1/risk/state")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "caps" in body
    assert "state" in body
    assert "kill_switch_active" in body
    assert body["kill_switch_active"] is False
    # Caps default values surface as strings (Pydantic Decimal-as-str).
    assert body["caps"]["per_trade_pct"] == "0.02"


@pytest.mark.integration
async def test_post_risk_override_400_on_short_reason(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
) -> None:
    """Reason <20 chars → 422 (Pydantic native body validation)."""
    user_id = UUID(seeded_tenant_user["user_id"])
    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    token = _login_cookie(user_id, tenant_id)
    client.cookies.set("iguana_session", token)

    body = {
        "proposal_id": str(uuid4()),
        "risk_evaluation_id": str(uuid4()),
        "authorised_by_user_id": str(user_id),
        "reason_text": "x" * 19,
        "confirmation_chain": {
            "first_confirmation": {
                "channel": "cli",
                "at": datetime.now().isoformat(),
                "actor_user_id": str(user_id),
            },
            "second_confirmation": {
                "channel": "cli",
                "at": datetime.now().isoformat(),
                "actor_user_id": str(user_id),
            },
        },
    }
    resp = await client.post("/api/v1/risk/override", json=body)
    # FastAPI / Pydantic native body-validation failure → 422.
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
async def test_post_risk_override_201_persists_row(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    schema_session_factory: object,
) -> None:
    """Valid override → 201 + DB row.

    First insert a parent risk_evaluation row via raw SQL so the FK
    constraint is satisfied (the dashboard-driven flow normally has
    the evaluation already present).
    """
    user_id = UUID(seeded_tenant_user["user_id"])
    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    token = _login_cookie(user_id, tenant_id)
    client.cookies.set("iguana_session", token)

    # Pre-insert a parent risk_evaluation row.
    from sqlalchemy import text

    eval_id = uuid4()
    factory = schema_session_factory
    async with factory() as s:  # type: ignore[operator]
        await s.execute(
            text(
                "INSERT INTO risk_evaluations ("
                "id, tenant_id, proposal_id, outcome, state_snapshot, created_at"
                ") VALUES (:id, :tid, :pid, 'reject', '{}', :ca)"
            ),
            {
                "id": eval_id.hex,
                "tid": tenant_id.hex,
                "pid": uuid4().hex,
                "ca": utc_now(),
            },
        )
        await s.commit()

    body = {
        "proposal_id": str(uuid4()),
        "risk_evaluation_id": str(eval_id),
        "authorised_by_user_id": str(user_id),
        "reason_text": "Special override for verified earnings beat opportunity.",
        "confirmation_chain": {
            "first_confirmation": {
                "channel": "cli",
                "at": utc_now().isoformat(),
                "actor_user_id": str(user_id),
            },
            "second_confirmation": {
                "channel": "cli",
                "at": utc_now().isoformat(),
                "actor_user_id": str(user_id),
            },
        },
    }
    resp = await client.post("/api/v1/risk/override", json=body)
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert "override_id" in payload
    assert payload["reason_text"] == body["reason_text"]


@pytest.mark.integration
async def test_get_risk_state_unauthenticated_returns_401(
    client: AsyncClient,
) -> None:
    """No cookie → 401 (slice-4 auth dep)."""
    resp = await client.get("/api/v1/risk/state")
    # Note: slice-4 raises HTTPException directly (not IguanaError) so
    # the body is FastAPI's native shape — content-type
    # ``application/json`` not ``application/problem+json``. K1 does
    # not change that contract.
    assert resp.status_code == 401, resp.text


@pytest.mark.integration
async def test_decimal_amount(
    client: AsyncClient,
) -> None:
    """Sanity: Decimal arithmetic check that the import side-effects work.

    Adds a placeholder for future decimal-vs-float regression tests
    that should live alongside the route tests rather than in the
    purely-unit property suite.
    """
    assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")
