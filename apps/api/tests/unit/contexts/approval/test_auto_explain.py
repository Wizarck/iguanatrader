"""Unit tests for the A1 auto-explain dispatcher wrapper.

Pure-unit — no LLM, no proposal repo, no Hermes channels. Fake the
inner :class:`ChannelDispatcher` and the :class:`NarrativeProvider`
so the wrapper's enrichment + best-effort degradation are exercised
in isolation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from iguanatrader.contexts.approval.auto_explain import (
    AutoExplainEnrichingDispatcher,
)
from iguanatrader.contexts.approval.channels.types import ApprovalRequestRow


def _request() -> ApprovalRequestRow:
    return ApprovalRequestRow(
        id=uuid4(),
        tenant_id=uuid4(),
        proposal_id=uuid4(),
        delivered_to_channels=["telegram"],
        timeout_seconds=900,
        expires_at=datetime(2026, 5, 18, 23, 59, tzinfo=UTC),
        created_at=datetime(2026, 5, 18, 23, 44, tzinfo=UTC),
    )


class _FakeInner:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, list[str]]] = []

    async def fanout(
        self,
        *,
        request: Any,
        channels: list[str],
    ) -> None:
        self.calls.append((request, list(channels)))


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_attaches_narrative_then_delegates_to_inner() -> None:
    inner = _FakeInner()

    async def _provider(_req: Any) -> str:
        return "AMD breakout — entry at 165, stop at 158, 1.0% risk."

    dispatcher = AutoExplainEnrichingDispatcher(inner=inner, provider=_provider)
    req = _request()

    _run(dispatcher.fanout(request=req, channels=["telegram"]))

    assert len(inner.calls) == 1
    forwarded, channels = inner.calls[0]
    assert channels == ["telegram"]
    # Narrative attached to the request payload (object.__setattr__).
    assert getattr(forwarded, "narrative", None) == (
        "AMD breakout — entry at 165, stop at 158, 1.0% risk."
    )


def test_skips_attachment_when_narrative_is_empty_string() -> None:
    """Empty narrative shouldn't pollute the payload — the inner
    dispatcher's body-builder falls back to the legacy raw template."""
    inner = _FakeInner()

    async def _provider(_req: Any) -> str:
        return "   "

    dispatcher = AutoExplainEnrichingDispatcher(inner=inner, provider=_provider)
    req = _request()

    _run(dispatcher.fanout(request=req, channels=["telegram"]))

    forwarded, _ = inner.calls[0]
    assert not hasattr(forwarded, "narrative") or forwarded.narrative is None


# ---------------------------------------------------------------------------
# Best-effort degradation
# ---------------------------------------------------------------------------


def test_provider_failure_does_not_block_fanout() -> None:
    """LLM timeout / budget block / parse error MUST NOT prevent the
    raw approval message from reaching the operator. The inner
    dispatcher sees an un-enriched request."""
    inner = _FakeInner()

    async def _provider(_req: Any) -> str:
        raise RuntimeError("Anthropic 429")

    dispatcher = AutoExplainEnrichingDispatcher(inner=inner, provider=_provider)
    req = _request()

    # Must not raise — best-effort path swallows the exception.
    _run(dispatcher.fanout(request=req, channels=["telegram"]))

    assert len(inner.calls) == 1
    forwarded, _ = inner.calls[0]
    assert not hasattr(forwarded, "narrative") or forwarded.narrative is None


def test_provider_returns_none_treated_as_empty() -> None:
    """A None-returning provider (e.g. some upstream short-circuit
    that says "skip narrative for this request") must NOT crash and
    must let the inner dispatcher proceed unenriched."""
    inner = _FakeInner()

    async def _provider(_req: Any) -> Any:
        return None

    dispatcher = AutoExplainEnrichingDispatcher(inner=inner, provider=_provider)
    req = _request()

    _run(dispatcher.fanout(request=req, channels=["telegram"]))

    assert len(inner.calls) == 1


def test_inner_failure_propagates() -> None:
    """If the inner dispatcher itself raises, that bubbles up — the
    wrapper's contract is to enrich, not to add new failure swallowing
    on top of the inner's own try/except (which already exists per
    FR32 isolation)."""

    class _FailingInner:
        async def fanout(self, *, request: Any, channels: list[str]) -> None:
            raise RuntimeError("downstream broker hung")

    async def _provider(_req: Any) -> str:
        return "ok"

    dispatcher = AutoExplainEnrichingDispatcher(inner=_FailingInner(), provider=_provider)

    with pytest.raises(RuntimeError, match="broker hung"):
        _run(dispatcher.fanout(request=_request(), channels=["telegram"]))


# ---------------------------------------------------------------------------
# Channel list pass-through
# ---------------------------------------------------------------------------


def test_channels_list_is_forwarded_verbatim() -> None:
    inner = _FakeInner()

    async def _provider(_req: Any) -> str:
        return "n"

    dispatcher = AutoExplainEnrichingDispatcher(inner=inner, provider=_provider)
    _run(
        dispatcher.fanout(
            request=_request(),
            channels=["telegram", "whatsapp", "dashboard"],
        )
    )
    _, channels = inner.calls[0]
    assert channels == ["telegram", "whatsapp", "dashboard"]
