"""Integration tests for the A2-persist slice — :class:`AutoRiskReviewOnCreateHandler`
now writes its assessment back onto the ``trade_proposals`` row instead of the
pre-slice no-op stub.

Covers:

* **Persister adapter** — ``set_risk_assessment`` lands all five risk_*
  columns on the row + ``risk_generated_at`` stamps wall-clock.
* **Threshold from feature-flags** — ``tenants.feature_flags['risk_review_confidence_threshold']``
  overrides :data:`DEFAULT_CONFIDENCE_THRESHOLD` at handler invocation. A
  tenant who lowered the threshold gets a review on a confidence the
  default would skip; a tenant who raised it to ``"1.00"`` gets no review
  even on a confidence the default would catch.
* **Settings PUT** — the route now accepts ``risk_review_confidence_threshold``
  in the payload + round-trips it on GET.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from iguanatrader.api import deps as api_deps
from iguanatrader.api.app import create_app
from iguanatrader.api.auth import encode_jwt, hash_password
from iguanatrader.api.deps import COOKIE_NAME
from iguanatrader.cli.llm_handler_wiring import (
    build_risk_assessment_persister,
    build_risk_review_threshold_loader,
)
from iguanatrader.contexts.research.auto_risk_review import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    AutoRiskReviewOnCreateHandler,
)
from iguanatrader.contexts.trading.events import ProposalCreated
from iguanatrader.contexts.trading.models import StrategyConfig, TradeProposal
from iguanatrader.contexts.trading.repository import TradeProposalRepository
from iguanatrader.persistence import (
    Tenant,
    User,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_JWT_SECRET", "x" * 64)


@pytest.fixture
async def session_maker(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    db_path = tmp_path / "a2.db"
    engine: AsyncEngine = engine_factory(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = session_factory(engine)
    try:
        yield sf
    finally:
        await engine.dispose()


async def _seed_tenant_with_proposal(
    sf: async_sessionmaker[AsyncSession],
    *,
    feature_flags: dict[str, Any] | None = None,
    confidence: Decimal = Decimal("0.90"),
) -> tuple[UUID, UUID]:
    """Return ``(tenant_id, proposal_id)``. Seeds a TradeProposal in
    ``state='pending_approval'`` with ``confidence_score=confidence``."""
    tid = uuid4()
    pid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name=f"t{tid.hex[:8]}", feature_flags=feature_flags or {}))
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        sc_id = uuid4()
        s.add(
            StrategyConfig(
                id=sc_id,
                tenant_id=tid,
                strategy_kind="donchian_atr",
                symbol="AAPL",
                params={"channel": 20},
                enabled=True,
                version=1,
            )
        )
        s.add(
            TradeProposal(
                id=pid,
                tenant_id=tid,
                strategy_config_id=sc_id,
                symbol="AAPL",
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("100"),
                stop_price=Decimal("95"),
                confidence_score=confidence,
                reasoning={"signal": "breakout"},
                mode="paper",
                correlation_id=uuid4(),
                state="pending_approval",
            )
        )
        await s.commit()
    return tid, pid


# ---------------------------------------------------------------------------
# Fakes for the A2 collaborators
# ---------------------------------------------------------------------------


class _FakeAssessment:
    def __init__(
        self,
        *,
        proposal_id: str,
        risk_score: int = 73,
        flags: list[str] | None = None,
        rationale: str = "Earnings 5d out; thin pre-earnings liquidity.",
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self.proposal_id = proposal_id
        self.risk_score = risk_score
        self.flags = flags or ["earnings_within_5d", "low_liquidity"]
        self.rationale = rationale
        self.model = model
        self.generated_at = datetime.now(UTC)
        self.tokens_input = 1200
        self.tokens_output = 450


class _FakeAssessor:
    """Captures the kwargs the handler invokes ``.assess`` with."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def assess(self, **kwargs: Any) -> _FakeAssessment:
        self.calls.append(kwargs)
        return _FakeAssessment(proposal_id=kwargs["proposal_id"])


class _FakeProposalLoader:
    """Returns a stub object satisfying ``_ProposalSnapshot``."""

    def __init__(self, *, proposal: TradeProposal) -> None:
        self._proposal = proposal

    async def load(self, _proposal_id: Any) -> TradeProposal:
        return self._proposal


# ---------------------------------------------------------------------------
# Persister adapter — A2 task 2.5b
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persister_writes_all_five_risk_columns(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """``build_risk_assessment_persister`` UPDATEs the five risk_* columns
    on the row + stamps ``risk_generated_at``."""
    tid, pid = await _seed_tenant_with_proposal(session_maker)

    async with with_tenant_context(tid), session_maker() as s:
        session_var.set(s)
        repo = TradeProposalRepository()
        persister = build_risk_assessment_persister(proposal_repo=repo)
        assessment = _FakeAssessment(proposal_id=str(pid), risk_score=88)
        await persister(assessment)
        await s.commit()

    async with with_tenant_context(tid), session_maker() as s:
        from sqlalchemy import select

        row = (await s.execute(select(TradeProposal).where(TradeProposal.id == pid))).scalar_one()

    assert row.risk_score == 88
    assert row.risk_flags == ["earnings_within_5d", "low_liquidity"]
    assert row.risk_rationale == "Earnings 5d out; thin pre-earnings liquidity."
    assert row.risk_model == "claude-sonnet-4-6"
    assert row.risk_generated_at is not None


# ---------------------------------------------------------------------------
# Threshold loader — feature-flags drive the runtime threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_threshold_loader_returns_none_when_flag_absent(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """No feature-flag → loader returns None → handler uses construction default."""
    tid, _ = await _seed_tenant_with_proposal(session_maker)
    loader = build_risk_review_threshold_loader()

    async with with_tenant_context(tid), session_maker() as s:
        session_var.set(s)
        result = await loader(tid)

    assert result is None


@pytest.mark.asyncio
async def test_threshold_loader_returns_flag_value_when_set(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Flag set → loader returns the Decimal."""
    tid, _ = await _seed_tenant_with_proposal(
        session_maker,
        feature_flags={"risk_review_confidence_threshold": "0.65"},
    )
    loader = build_risk_review_threshold_loader()

    async with with_tenant_context(tid), session_maker() as s:
        session_var.set(s)
        result = await loader(tid)

    assert result == Decimal("0.65")


@pytest.mark.asyncio
async def test_handler_skips_review_when_tenant_raises_threshold_to_one(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Tenant set threshold=1.00 effectively disables auto-review even
    on a high-confidence proposal."""
    tid, pid = await _seed_tenant_with_proposal(
        session_maker,
        feature_flags={"risk_review_confidence_threshold": "1.00"},
        confidence=Decimal("0.95"),
    )

    async with with_tenant_context(tid), session_maker() as s:
        session_var.set(s)
        repo = TradeProposalRepository()
        proposal = await repo.get_by_id(pid)
        assert proposal is not None

        assessor = _FakeAssessor()
        handler = AutoRiskReviewOnCreateHandler(
            assessor=assessor,  # type: ignore[arg-type]
            loader=_FakeProposalLoader(proposal=proposal),
            persister=build_risk_assessment_persister(proposal_repo=repo),
            threshold_loader=build_risk_review_threshold_loader(),
        )

        event = ProposalCreated(
            tenant_id=tid,
            proposal_id=pid,
            symbol="AAPL",
            strategy_kind="donchian_atr",
            strategy_version=1,
            correlation_id=uuid4(),
        )
        await handler(event)

    assert assessor.calls == []  # never invoked


@pytest.mark.asyncio
async def test_handler_runs_review_when_tenant_lowers_threshold_below_confidence(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Tenant lowered the threshold below the default; a 0.70 proposal
    (below the default 0.80) now triggers the review."""
    tid, pid = await _seed_tenant_with_proposal(
        session_maker,
        feature_flags={"risk_review_confidence_threshold": "0.65"},
        confidence=Decimal("0.70"),
    )

    async with with_tenant_context(tid), session_maker() as s:
        session_var.set(s)
        repo = TradeProposalRepository()
        proposal = await repo.get_by_id(pid)
        assert proposal is not None

        assessor = _FakeAssessor()
        handler = AutoRiskReviewOnCreateHandler(
            assessor=assessor,  # type: ignore[arg-type]
            loader=_FakeProposalLoader(proposal=proposal),
            persister=build_risk_assessment_persister(proposal_repo=repo),
            threshold_loader=build_risk_review_threshold_loader(),
        )

        event = ProposalCreated(
            tenant_id=tid,
            proposal_id=pid,
            symbol="AAPL",
            strategy_kind="donchian_atr",
            strategy_version=1,
            correlation_id=uuid4(),
        )
        await handler(event)
        await s.commit()

    assert len(assessor.calls) == 1
    async with with_tenant_context(tid), session_maker() as s:
        from sqlalchemy import select

        row = (await s.execute(select(TradeProposal).where(TradeProposal.id == pid))).scalar_one()
    assert row.risk_score == 73
    assert row.risk_generated_at is not None


@pytest.mark.asyncio
async def test_default_threshold_constant_unchanged() -> None:
    """Belt-and-braces: the canonical default stays at 0.80 to match the
    roadmap + the FeatureFlagsIn DTO description."""
    assert Decimal("0.80") == DEFAULT_CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Settings route — accepts + round-trips the new feature-flag
# ---------------------------------------------------------------------------


@pytest.fixture
async def app_client(
    session_maker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[AsyncClient, UUID]]:
    """Yield an authenticated client + the seeded tenant_id."""
    tid = uuid4()
    uid = uuid4()
    async with session_maker() as s:
        s.add(Tenant(id=tid, name="t-a2-settings", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), session_maker() as s:
        s.add(
            User(
                id=uid,
                tenant_id=tid,
                email="a2@example.com",
                password_hash=hash_password("correct-horse-battery-staple"),
                role="tenant_user",
            )
        )
        await s.commit()

    app = create_app()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_maker() as s:
            yield s

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        client.cookies.set(
            COOKIE_NAME,
            encode_jwt(
                {
                    "sub": str(uid),
                    "tenant_id": str(tid),
                    "role": "tenant_user",
                    "login_at": int(datetime.now(UTC).timestamp()),
                },
                exp_seconds=3600,
            ),
        )
        yield client, tid
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_settings_put_accepts_risk_threshold(
    app_client: tuple[AsyncClient, UUID],
) -> None:
    client, _tid = app_client
    resp = await client.put(
        "/api/v1/settings/feature-flags",
        json={"risk_review_confidence_threshold": "0.65"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["risk_review_confidence_threshold"] == "0.65"

    # Round-trip via GET.
    resp_get = await client.get("/api/v1/settings/feature-flags")
    assert resp_get.status_code == 200
    assert resp_get.json()["risk_review_confidence_threshold"] == "0.65"


@pytest.mark.asyncio
async def test_settings_put_rejects_out_of_range_threshold(
    app_client: tuple[AsyncClient, UUID],
) -> None:
    client, _tid = app_client
    resp = await client.put(
        "/api/v1/settings/feature-flags",
        json={"risk_review_confidence_threshold": "1.50"},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_settings_put_clears_threshold_with_empty_string(
    app_client: tuple[AsyncClient, UUID],
) -> None:
    client, _tid = app_client
    # Set then clear.
    await client.put(
        "/api/v1/settings/feature-flags",
        json={"risk_review_confidence_threshold": "0.85"},
    )
    resp = await client.put(
        "/api/v1/settings/feature-flags",
        json={"risk_review_confidence_threshold": ""},
    )
    assert resp.status_code == 200
    assert resp.json()["risk_review_confidence_threshold"] is None
