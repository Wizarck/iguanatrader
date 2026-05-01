"""Property test: every subscriber observes events in publication order.

For any sequence of N distinct events published to a bus with K
subscribers (registered for the same event type), each subscriber's
observed sequence equals the publication sequence verbatim.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from iguanatrader.shared.messagebus import Event, MessageBus

# Same Windows-specific guard as ``test_heartbeat_idempotency.py``: ProactorEventLoop
# leaks FDs when ``asyncio.run`` is called many times by Hypothesis.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@dataclass
class _Tagged(Event):
    tag: int = 0


@given(
    sequence=st.lists(st.integers(min_value=0, max_value=10000), min_size=1, max_size=50),
    n_subscribers=st.integers(min_value=1, max_value=4),
)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=50)
def test_each_subscriber_sees_publication_order(sequence: list[int], n_subscribers: int) -> None:
    asyncio.run(_run(sequence, n_subscribers))


async def _run(sequence: list[int], n_subscribers: int) -> None:
    bus = MessageBus()
    observed: list[list[int]] = [[] for _ in range(n_subscribers)]

    def make_handler(idx: int) -> object:
        async def handler(ev: _Tagged) -> None:
            observed[idx].append(ev.tag)

        return handler

    subs = [bus.subscribe(_Tagged, make_handler(i)) for i in range(n_subscribers)]  # type: ignore[arg-type]

    for n in sequence:
        await bus.publish(_Tagged(tag=n))

    for sub in subs:
        await sub.queue.join()

    # Every subscriber must have observed the publication order verbatim.
    for obs in observed:
        assert obs == sequence

    await bus.aclose()
