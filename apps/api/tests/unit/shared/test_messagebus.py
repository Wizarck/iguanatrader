"""Unit tests for :mod:`iguanatrader.shared.messagebus`."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from iguanatrader.shared.messagebus import Event, MessageBus


@dataclass
class _Click(Event):
    n: int = 0


@dataclass
class _Pong(Event):
    text: str = ""


class TestSingleSubscriberFifo:
    async def test_events_delivered_in_publication_order(self) -> None:
        bus = MessageBus()
        seen: list[int] = []

        async def handler(ev: _Click) -> None:
            seen.append(ev.n)

        sub = bus.subscribe(_Click, handler)

        for n in range(10):
            await bus.publish(_Click(n=n))

        # Wait for the queue to drain.
        await sub.queue.join()
        assert seen == list(range(10))
        await bus.aclose()


class TestMultipleSubscribersIndependent:
    async def test_slow_subscriber_does_not_block_fast_one(self) -> None:
        bus = MessageBus()
        fast_seen: list[int] = []
        slow_seen: list[int] = []

        slow_gate = asyncio.Event()

        async def fast(ev: _Click) -> None:
            fast_seen.append(ev.n)

        async def slow(ev: _Click) -> None:
            await slow_gate.wait()
            slow_seen.append(ev.n)

        sub_fast = bus.subscribe(_Click, fast)
        sub_slow = bus.subscribe(_Click, slow)

        for n in range(10):
            await bus.publish(_Click(n=n))

        # Fast subscriber drains independently of the gated slow one.
        await sub_fast.queue.join()
        assert fast_seen == list(range(10))
        # Slow subscriber has not delivered anything yet — its handler is
        # blocked on the gate, but its queue accepted all 10 events.
        assert slow_seen == []

        # Now release the slow subscriber and let it finish.
        slow_gate.set()
        await sub_slow.queue.join()
        assert slow_seen == list(range(10))

        await bus.aclose()


class TestEventTypeRouting:
    async def test_only_matching_subscribers_get_event(self) -> None:
        bus = MessageBus()
        clicks: list[_Click] = []
        pongs: list[_Pong] = []

        async def on_click(ev: _Click) -> None:
            clicks.append(ev)

        async def on_pong(ev: _Pong) -> None:
            pongs.append(ev)

        sub_a = bus.subscribe(_Click, on_click)
        sub_b = bus.subscribe(_Pong, on_pong)

        await bus.publish(_Click(n=1))
        await bus.publish(_Pong(text="x"))
        await bus.publish(_Click(n=2))

        await sub_a.queue.join()
        await sub_b.queue.join()
        assert [c.n for c in clicks] == [1, 2]
        assert [p.text for p in pongs] == ["x"]
        await bus.aclose()


class TestIdempotency:
    async def test_idempotent_subscriber_dedupes_by_key(self) -> None:
        bus = MessageBus()
        seen: list[int] = []

        async def handler(ev: _Click) -> None:
            seen.append(ev.n)

        sub = bus.subscribe(_Click, handler, idempotent=True)

        # Publish two events with the same key + a third with a fresh key.
        await bus.publish(_Click(n=1, idempotency_key="k1"))
        # Wait for the first to be processed so it lands in `recent_keys`.
        await sub.queue.join()
        await bus.publish(_Click(n=2, idempotency_key="k1"))  # duplicate
        await bus.publish(_Click(n=3, idempotency_key="k2"))  # fresh
        await sub.queue.join()

        # n=2 was suppressed because it shared key "k1" with n=1.
        assert seen == [1, 3]
        await bus.aclose()

    async def test_event_without_key_is_not_deduped(self) -> None:
        bus = MessageBus()
        seen: list[int] = []

        async def handler(ev: _Click) -> None:
            seen.append(ev.n)

        sub = bus.subscribe(_Click, handler, idempotent=True)

        # Same payload, no idempotency_key — both delivered.
        await bus.publish(_Click(n=1))
        await bus.publish(_Click(n=1))
        await sub.queue.join()
        assert seen == [1, 1]
        await bus.aclose()

    async def test_non_idempotent_subscriber_ignores_key(self) -> None:
        bus = MessageBus()
        seen: list[int] = []

        async def handler(ev: _Click) -> None:
            seen.append(ev.n)

        sub = bus.subscribe(_Click, handler)  # idempotent=False (default)
        await bus.publish(_Click(n=1, idempotency_key="k1"))
        await bus.publish(_Click(n=2, idempotency_key="k1"))
        await sub.queue.join()
        assert seen == [1, 2]
        await bus.aclose()


class TestUnsubscribeAndClose:
    async def test_unsubscribe_stops_delivery(self) -> None:
        bus = MessageBus()
        seen: list[int] = []

        async def handler(ev: _Click) -> None:
            seen.append(ev.n)

        sub = bus.subscribe(_Click, handler)
        await bus.publish(_Click(n=1))
        await sub.queue.join()
        await bus.unsubscribe(sub)
        await bus.publish(_Click(n=2))  # nobody listening anymore
        # Nothing more to wait for; assert state.
        assert seen == [1]
        await bus.aclose()

    async def test_publish_after_close_raises(self) -> None:
        bus = MessageBus()
        await bus.aclose()
        with pytest.raises(RuntimeError, match="closed"):
            await bus.publish(_Click(n=1))

    async def test_subscribe_after_close_raises(self) -> None:
        bus = MessageBus()
        await bus.aclose()

        async def handler(ev: _Click) -> None:
            pass

        with pytest.raises(RuntimeError, match="closed"):
            bus.subscribe(_Click, handler)

    async def test_aclose_is_idempotent(self) -> None:
        bus = MessageBus()
        await bus.aclose()
        await bus.aclose()  # no-op; must not raise
