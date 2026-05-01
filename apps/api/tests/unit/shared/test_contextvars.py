"""Unit tests for :mod:`iguanatrader.shared.contextvars` — tenant + session ContextVars.

Covers the spec scenarios for the "tenant_id ContextVar carries scope across
async boundaries" requirement and the ContextVar-related behaviour of
"BaseRepository reads session and tenant scope from ContextVars" in the
shared-kernel spec.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from iguanatrader.shared.contextvars import (
    propagate_tenant_to,
    session_var,
    tenant_id_var,
    with_tenant_context,
)


class TestTenantIdVar:
    async def test_default_is_none(self) -> None:
        assert tenant_id_var.get() is None

    async def test_propagates_across_await(self) -> None:
        t1 = uuid4()
        token = tenant_id_var.set(t1)
        try:

            async def inner() -> UUID | None:
                # `await` introduces a task switch in asyncio's eyes; the
                # ContextVar should still resolve to t1 inside `inner`.
                await asyncio.sleep(0)
                return tenant_id_var.get()

            got = await inner()
            assert got == t1
        finally:
            tenant_id_var.reset(token)

    async def test_reset_restores_previous_value(self) -> None:
        assert tenant_id_var.get() is None
        token = tenant_id_var.set(uuid4())
        tenant_id_var.reset(token)
        assert tenant_id_var.get() is None

    async def test_isolation_between_sibling_tasks(self) -> None:
        # Two tasks, each setting their own tenant_id, do not leak into each
        # other. We assert via a barrier so both tasks have their values set
        # simultaneously.
        t1 = uuid4()
        t2 = uuid4()
        ready = asyncio.Event()
        observed: dict[str, UUID | None] = {}

        async def worker(tid: UUID, key: str) -> None:
            tenant_id_var.set(tid)
            await ready.wait()
            observed[key] = tenant_id_var.get()

        a = asyncio.create_task(worker(t1, "a"))
        b = asyncio.create_task(worker(t2, "b"))
        # Wake both tasks atomically.
        await asyncio.sleep(0)
        ready.set()
        await asyncio.gather(a, b)
        assert observed == {"a": t1, "b": t2}


class TestWithTenantContext:
    async def test_sets_and_restores(self) -> None:
        t1 = uuid4()
        assert tenant_id_var.get() is None
        async with with_tenant_context(t1):
            assert tenant_id_var.get() == t1
        assert tenant_id_var.get() is None

    async def test_nested_contexts(self) -> None:
        outer = uuid4()
        inner = uuid4()
        async with with_tenant_context(outer):
            assert tenant_id_var.get() == outer
            async with with_tenant_context(inner):
                assert tenant_id_var.get() == inner
            assert tenant_id_var.get() == outer
        assert tenant_id_var.get() is None

    async def test_restores_on_exception(self) -> None:
        t1 = uuid4()
        with pytest.raises(RuntimeError, match="boom"):
            async with with_tenant_context(t1):
                raise RuntimeError("boom")
        assert tenant_id_var.get() is None

    async def test_accepts_none_to_clear(self) -> None:
        t1 = uuid4()
        token = tenant_id_var.set(t1)
        try:
            async with with_tenant_context(None):
                assert tenant_id_var.get() is None
            assert tenant_id_var.get() == t1
        finally:
            tenant_id_var.reset(token)


class TestSessionAndTenantAreIndependent:
    async def test_setting_session_does_not_clear_tenant(self) -> None:
        t1 = uuid4()
        sentinel: object = object()  # stand-in for an AsyncSession instance
        async with with_tenant_context(t1):
            tok = session_var.set(sentinel)
            try:
                assert tenant_id_var.get() == t1
                assert session_var.get() is sentinel
            finally:
                session_var.reset(tok)
        assert tenant_id_var.get() is None
        assert session_var.get() is None


class TestPropagateTenantTo:
    async def test_spawned_task_sees_current_tenant(self) -> None:
        t1 = uuid4()
        async with with_tenant_context(t1):

            async def child() -> UUID | None:
                await asyncio.sleep(0)
                return tenant_id_var.get()

            task = propagate_tenant_to(child())
            got = await task
        assert got == t1
