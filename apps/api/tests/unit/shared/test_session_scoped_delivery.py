"""#2/#27/#29: session-per-delivery unit of work + transactional outbox.

Covers the mechanism in isolation (no DB):

* ``run_in_session_scope`` opens a fresh session, binds ``session_var`` +
  ``tenant_id_var``, commits on success / rolls back + re-raises on failure,
  and restores the contextvars afterwards.
* The transactional OUTBOX: events a unit of work publishes are buffered and
  delivered only AFTER the session commits (publish-after-commit), so a
  downstream subscriber never reads uncommitted state. On rollback the buffered
  events are discarded.
* ``MessageBus`` routes handler invocation through an injected middleware.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from iguanatrader.shared.contextvars import (
    run_in_session_scope,
    session_scoped_delivery,
    session_var,
    tenant_id_var,
)
from iguanatrader.shared.messagebus import Event, MessageBus


@dataclass
class _Ev(Event):
    tenant_id: Any = None


class _FakeSession:
    """Async-context-manager session double recording commit/rollback/close."""

    def __init__(self) -> None:
        self.committed = False
        self.rolledback = False
        self.closed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        self.closed = True
        return False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolledback = True


def _factory_collecting(created: list[_FakeSession]) -> Any:
    def _make() -> _FakeSession:
        s = _FakeSession()
        created.append(s)
        return s

    return _make


class _FakeBus:
    def __init__(self) -> None:
        self.published: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.published.append(event)


@pytest.mark.asyncio
async def test_commit_and_context_binding_on_success() -> None:
    created: list[_FakeSession] = []
    bus = _FakeBus()
    tid = uuid4()
    seen: dict[str, Any] = {}

    async def fn() -> None:
        seen["session"] = session_var.get()
        seen["tenant"] = tenant_id_var.get()

    await run_in_session_scope(_factory_collecting(created), bus, tid, fn)

    assert len(created) == 1
    assert created[0].committed and not created[0].rolledback
    assert created[0].closed
    assert seen["session"] is created[0]
    assert seen["tenant"] == tid
    # Contextvars restored afterwards (no leak across deliveries).
    assert session_var.get() is None
    assert tenant_id_var.get() is None
    assert bus.published == []


@pytest.mark.asyncio
async def test_rollback_and_reraise_on_error() -> None:
    created: list[_FakeSession] = []
    bus = _FakeBus()

    async def fn() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await run_in_session_scope(_factory_collecting(created), bus, uuid4(), fn)

    assert created[0].rolledback and not created[0].committed
    assert session_var.get() is None
    assert tenant_id_var.get() is None
    assert bus.published == []


@pytest.mark.asyncio
async def test_distinct_session_per_delivery() -> None:
    created: list[_FakeSession] = []
    bus = _FakeBus()

    async def fn() -> None:
        return None

    await run_in_session_scope(_factory_collecting(created), bus, uuid4(), fn)
    await run_in_session_scope(_factory_collecting(created), bus, uuid4(), fn)

    assert len(created) == 2
    assert created[0] is not created[1]


@pytest.mark.asyncio
async def test_outbox_publishes_only_after_commit() -> None:
    """Events published by the unit of work are buffered during it and
    delivered only after the session commits — and not at all on rollback."""
    created: list[_FakeSession] = []
    bus = MessageBus()  # real bus: its publish() honours the outbox var
    delivered: list[Event] = []
    committed_at_delivery: list[bool] = []

    async def subscriber(ev: _Ev) -> None:
        delivered.append(ev)
        committed_at_delivery.append(created[0].committed)

    bus.subscribe(_Ev, subscriber)

    async def fn() -> None:
        # Publishing here must NOT deliver yet — it is buffered in the outbox.
        await bus.publish(_Ev(tenant_id=None))
        assert delivered == []
        assert created[0].committed is False

    await run_in_session_scope(_factory_collecting(created), bus, None, fn)
    for _ in range(10):
        await asyncio.sleep(0)

    assert len(delivered) == 1
    # The session was already committed by the time the event was delivered.
    assert committed_at_delivery == [True]
    await bus.aclose()


@pytest.mark.asyncio
async def test_outbox_discarded_on_rollback() -> None:
    created: list[_FakeSession] = []
    bus = MessageBus()
    delivered: list[Event] = []

    async def subscriber(ev: _Ev) -> None:
        delivered.append(ev)

    bus.subscribe(_Ev, subscriber)

    async def fn() -> None:
        await bus.publish(_Ev(tenant_id=None))
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await run_in_session_scope(_factory_collecting(created), bus, None, fn)
    for _ in range(10):
        await asyncio.sleep(0)

    assert created[0].rolledback
    assert delivered == []  # never published — the unit of work failed
    await bus.aclose()


@pytest.mark.asyncio
async def test_session_scoped_delivery_middleware_end_to_end() -> None:
    """The bus middleware form: a handler that publishes a follow-up event
    delivers it only after its own delivery commits."""
    created: list[_FakeSession] = []
    bus = MessageBus()
    bus.set_delivery_middleware(session_scoped_delivery(_factory_collecting(created), bus))

    order: list[str] = []

    async def first(ev: _Ev) -> None:
        order.append("first")
        await bus.publish(_Ev2(tenant_id=None))

    async def second(ev: _Ev2) -> None:
        order.append("second")

    bus.subscribe(_Ev, first)
    bus.subscribe(_Ev2, second)
    await bus.publish(_Ev(tenant_id=None))
    for _ in range(20):
        await asyncio.sleep(0)

    assert order == ["first", "second"]
    # Two deliveries → two distinct per-delivery sessions, both committed.
    assert len(created) == 2
    assert all(s.committed for s in created)
    await bus.aclose()


@dataclass
class _Ev2(Event):
    tenant_id: Any = None


@pytest.mark.asyncio
async def test_bus_without_middleware_calls_handler_directly() -> None:
    """Backward-compat: default (no middleware, no outbox) is unchanged."""
    bus = MessageBus()
    got: list[Event] = []

    async def h(ev: _Ev) -> None:
        got.append(ev)

    bus.subscribe(_Ev, h)
    await bus.publish(_Ev(tenant_id=None))
    for _ in range(10):
        await asyncio.sleep(0)

    assert len(got) == 1
    await bus.aclose()
