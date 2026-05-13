"""Property test: ``MultiChannelMessageDispatcher`` never silently drops recipients.

For any list of recipients (mix of good/bad/unknown channels), the invariant
``len(results) == len(recipients)`` MUST hold and every result status is one
of the three allowed values. This is the regression net for FR32 isolation
across the dispatch pipeline.

Marker: ``@pytest.mark.property``. Not ``ci_blocking`` — unit tests cover the
contract; this catches edge-case combinations.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from iguanatrader.shared.channel_dispatch import (
    DispatchResult,
    MultiChannelMessageDispatcher,
    OutboundMessage,
    Recipient,
)


class _BehaviorDispatcher:
    """Returns ``status`` for every recipient, optionally raising mid-batch."""

    def __init__(self, *, status: str, raise_at_index: int | None = None) -> None:
        self.status = status
        self.raise_at = raise_at_index

    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]:
        if self.raise_at is not None and len(recipients) > self.raise_at:
            raise RuntimeError("synthetic failure")
        return [
            DispatchResult(
                channel=r.channel,
                address=r.address,
                status=self.status,  # type: ignore[arg-type]
                wire_message_id=("wire-" + r.address) if self.status == "delivered" else None,
                error=None,
            )
            for r in recipients
        ]


_KNOWN_CHANNELS = ["telegram", "whatsapp", "email"]
_UNKNOWN_CHANNELS = ["signal", "discord", "irc"]

_recipient_strategy = st.builds(
    Recipient,
    channel=st.sampled_from(_KNOWN_CHANNELS + _UNKNOWN_CHANNELS),
    address=st.text(
        min_size=1, max_size=20, alphabet=st.characters(min_codepoint=33, max_codepoint=126)
    ),
    display_name=st.one_of(st.none(), st.text(max_size=20)),
)


@pytest.mark.property
@given(recipients=st.lists(_recipient_strategy, max_size=15))
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_multi_dispatch_never_silently_drops(recipients: list[Recipient]) -> None:
    async def _run() -> None:
        good_telegram = _BehaviorDispatcher(status="delivered")
        bad_whatsapp = _BehaviorDispatcher(status="delivered", raise_at_index=0)
        good_email = _BehaviorDispatcher(status="delivered")
        multi = MultiChannelMessageDispatcher(
            dispatchers={
                "telegram": good_telegram,
                "whatsapp": bad_whatsapp,
                "email": good_email,
            }
        )
        message = OutboundMessage(body="x", correlation_id="c")
        results = await multi.dispatch(message=message, recipients=recipients)

        # Invariant 1: one result per recipient, never silently dropped.
        assert len(results) == len(recipients)
        # Invariant 2: result ordering preserves recipient ordering.
        for r, dr in zip(recipients, results, strict=True):
            assert dr.channel == r.channel
            assert dr.address == r.address
        # Invariant 3: every status is in the allowed enum.
        assert all(dr.status in {"delivered", "failed", "skipped"} for dr in results)
        # Invariant 4: recipients on unknown channels are always skipped.
        for r, dr in zip(recipients, results, strict=True):
            if r.channel in _UNKNOWN_CHANNELS:
                assert dr.status == "skipped"
        # Invariant 5: whatsapp recipients (when present) are uniformly failed
        # because bad_whatsapp raises on every non-empty batch.
        whatsapp_results = [dr for dr in results if dr.channel == "whatsapp"]
        if whatsapp_results:
            assert all(dr.status == "failed" for dr in whatsapp_results)
        # Invariant 6: email recipients (when present) are uniformly delivered
        # because good_email is wired live alongside the failing whatsapp
        # adapter — FR32 isolation means one bad channel can't poison the
        # rest of the fanout.
        email_results = [dr for dr in results if dr.channel == "email"]
        if email_results:
            assert all(dr.status == "delivered" for dr in email_results)

    asyncio.run(_run())
