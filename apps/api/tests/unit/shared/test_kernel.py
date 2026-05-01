"""Unit tests for :mod:`iguanatrader.shared.kernel` — :class:`BaseRepository`."""

from __future__ import annotations

import asyncio

import pytest
from iguanatrader.shared.contextvars import session_var
from iguanatrader.shared.kernel import BaseRepository


class TestSessionResolution:
    def test_resolves_session_from_contextvar(self) -> None:
        sentinel = object()
        token = session_var.set(sentinel)
        try:
            repo = BaseRepository()
            assert repo.session is sentinel
        finally:
            session_var.reset(token)

    def test_raises_lookup_error_when_unset(self) -> None:
        # Default state: session_var is None.
        repo = BaseRepository()
        with pytest.raises(LookupError, match="session_var is not set"):
            _ = repo.session


class TestAsyncContextIsolation:
    async def test_two_tasks_see_their_own_session(self) -> None:
        s_a = object()
        s_b = object()
        ready = asyncio.Event()
        observed: dict[str, object] = {}

        async def worker(session: object, key: str) -> None:
            session_var.set(session)
            await ready.wait()
            repo = BaseRepository()
            observed[key] = repo.session

        a = asyncio.create_task(worker(s_a, "a"))
        b = asyncio.create_task(worker(s_b, "b"))
        await asyncio.sleep(0)
        ready.set()
        await asyncio.gather(a, b)
        assert observed == {"a": s_a, "b": s_b}

    async def test_repo_in_inner_task_inherits_session(self) -> None:
        sentinel = object()
        token = session_var.set(sentinel)
        try:

            async def child() -> object:
                # No `session_var.set(...)` here — must inherit.
                await asyncio.sleep(0)
                return BaseRepository().session

            assert await child() is sentinel
        finally:
            session_var.reset(token)
