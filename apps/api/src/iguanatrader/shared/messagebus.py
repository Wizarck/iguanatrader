"""In-process MessageBus — FIFO per subscriber, opt-in idempotency.

Per design decision D1 (slice 2 ``shared-primitives``):

* **One queue per subscriber.** ``publish(event)`` fans out by enqueuing
  the event to each subscriber's :class:`asyncio.Queue`. A slow handler
  cannot block a fast one because they read from independent queues.
* **FIFO per subscriber.** Each subscriber's worker task drains its
  queue in publication order; per-subscriber ordering is the strongest
  guarantee the bus offers.
* **Opt-in idempotency.** Events that carry an ``idempotency_key`` can
  be subscribed-to with ``idempotent=True``; the bus suppresses
  duplicate deliveries within a bounded recent-keys window
  (``dedup_window``, default 1000).

The bus is single-process. Distributed messaging (Redis, NATS) is
explicitly out of scope and would land in a future change with its own
ADR (per design.md Non-Goals).

Usage::

    bus = MessageBus()

    async def on_proposal(ev: ProposalCreated) -> None:
        ...

    sub = bus.subscribe(ProposalCreated, on_proposal)

    await bus.publish(ProposalCreated(...))

    # On shutdown:
    await bus.aclose()
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar, cast

EventT = TypeVar("EventT", bound="Event")


@dataclass
class Event:
    """Base for events routed through :class:`MessageBus`.

    Subclasses are typically dataclasses with the domain payload. The
    ``idempotency_key`` attribute is optional; it is consulted only by
    subscribers registered with ``idempotent=True``. Duplicate keys at
    those subscribers are silently suppressed.
    """

    idempotency_key: str | None = None


_Handler = Callable[[EventT], Awaitable[None]]


@dataclass
class Subscription(Generic[EventT]):
    """Handle returned by :meth:`MessageBus.subscribe`.

    Hold onto it for the lifetime of the subscriber; cancel it via
    :meth:`MessageBus.unsubscribe` when shutting down a component.
    """

    event_type: type[EventT]
    handler: _Handler[EventT]
    queue: asyncio.Queue[EventT] = field(repr=False)
    idempotent: bool = False
    dedup_window: int = 1000
    _task: asyncio.Task[None] | None = field(default=None, repr=False)
    _recent_keys: deque[str] = field(default_factory=deque, repr=False)
    _recent_keys_set: set[str] = field(default_factory=set, repr=False)

    def _record_key(self, key: str) -> None:
        if key in self._recent_keys_set:
            return
        self._recent_keys.append(key)
        self._recent_keys_set.add(key)
        while len(self._recent_keys) > self.dedup_window:
            evicted = self._recent_keys.popleft()
            self._recent_keys_set.discard(evicted)

    def _has_seen(self, key: str) -> bool:
        return key in self._recent_keys_set


class MessageBus:
    """In-process pub/sub with per-subscriber FIFO queues.

    .. caution:: handler exceptions kill the worker task

       The internal worker task does NOT catch exceptions raised by a
       handler. If a handler raises, its worker task terminates and
       that subscriber stops receiving events. Slice 2 has no logging
       wired up (slice O1 lands ``structlog``); until then, callers
       SHOULD wrap their handler bodies in a ``try/except`` and decide
       whether to log + swallow or let the failure propagate.
    """

    def __init__(self) -> None:
        self._subscriptions: dict[type[Event], list[Subscription[Event]]] = {}
        self._closed = False

    def subscribe(
        self,
        event_type: type[EventT],
        handler: _Handler[EventT],
        *,
        idempotent: bool = False,
        dedup_window: int = 1000,
    ) -> Subscription[EventT]:
        """Register a handler for ``event_type``.

        If ``idempotent`` is true, the bus tracks the last
        ``dedup_window`` ``idempotency_key`` values delivered to this
        subscriber and silently drops duplicates. Events without an
        ``idempotency_key`` are delivered as-is regardless of the flag
        (idempotency is opt-in per event).
        """
        if self._closed:
            raise RuntimeError("MessageBus is closed; cannot subscribe")

        queue: asyncio.Queue[EventT] = asyncio.Queue()
        sub: Subscription[EventT] = Subscription(
            event_type=event_type,
            handler=handler,
            queue=queue,
            idempotent=idempotent,
            dedup_window=dedup_window,
        )
        # Internal storage erases the precise EventT type — at the worker
        # / dispatch level the bus only needs ``Subscription[Event]``.
        # cast is safe because handler/queue both consume the value as
        # the more general Event type once we hand it to the worker.
        sub_erased = cast("Subscription[Event]", sub)
        sub._task = asyncio.create_task(self._worker(sub_erased))
        bucket = self._subscriptions.setdefault(event_type, [])
        bucket.append(sub_erased)
        return sub

    async def unsubscribe(self, sub: Subscription[EventT]) -> None:
        """Cancel a subscription's worker task and remove it from routing."""
        sub_erased = cast("Subscription[Event]", sub)
        bucket = self._subscriptions.get(sub.event_type)
        if bucket is not None and sub_erased in bucket:
            bucket.remove(sub_erased)
        if sub._task is not None:
            sub._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await sub._task

    async def publish(self, event: Event) -> None:
        """Fan ``event`` out to every subscriber registered for its type.

        Idempotent subscribers with a matching recent key skip enqueue.
        Returns once each subscriber's queue has accepted the event;
        actual handler invocation happens asynchronously in worker
        tasks.
        """
        if self._closed:
            raise RuntimeError("MessageBus is closed; cannot publish")

        bucket = self._subscriptions.get(type(event), [])
        for sub in bucket:
            if (
                sub.idempotent
                and event.idempotency_key is not None
                and sub._has_seen(event.idempotency_key)
            ):
                continue
            await sub.queue.put(event)

    async def aclose(self) -> None:
        """Cancel all worker tasks and release resources."""
        if self._closed:
            return
        self._closed = True
        all_subs = [s for bucket in self._subscriptions.values() for s in bucket]
        for sub in all_subs:
            if sub._task is not None:
                sub._task.cancel()
        for sub in all_subs:
            if sub._task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await sub._task
        self._subscriptions.clear()

    async def _worker(self, sub: Subscription[Event]) -> None:
        """Drain ``sub.queue`` in FIFO order, invoking the handler."""
        while True:
            event = await sub.queue.get()
            try:
                await sub.handler(event)
                if sub.idempotent and event.idempotency_key is not None:
                    sub._record_key(event.idempotency_key)
            finally:
                sub.queue.task_done()


__all__ = ["Event", "MessageBus", "Subscription"]
