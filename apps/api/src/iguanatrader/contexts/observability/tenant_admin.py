"""Tenant feature-flag admin helpers — read/write ``tenants.feature_flags``.

#31: ``/lock`` and ``/unlock`` referenced ``set_feature_flag`` /
``get_feature_flag`` here, but the module never existed — so ``/lock``
was a silent no-op (it returned "Feature-flag admin unavailable." and
never persisted ``approvals_paused``). That left the documented operator
pause completely inert: a human could "pause approvals" and the system
would keep approving + executing. This module makes the flag real.

Both helpers resolve the active session from :data:`session_var` and the
tenant from an explicit ``tenant_id`` argument or :data:`tenant_id_var`
(the bot dispatch binds it via ``with_tenant_context`` — see #33). The
:class:`Tenant` mapping is non-tenant-scoped, so the slice-3 listener does
not require ``tenant_id_var`` for these queries (mirrors
``observability.budget._read_cap_for_tenant``).
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.persistence.models import Tenant
from iguanatrader.shared.contextvars import session_var, tenant_id_var


def _resolve_tenant_id(tenant_id: UUID | None) -> UUID | None:
    return tenant_id if tenant_id is not None else tenant_id_var.get()


async def get_feature_flag(
    key: str,
    default: Any = None,
    *,
    tenant_id: UUID | None = None,
) -> Any:
    """Return ``tenants.feature_flags[key]`` for the tenant, or ``default``.

    Read-only + side-effect free. Returns ``default`` (never raises) when
    there is no active session, no resolvable tenant, the tenant row is
    missing, or the key is absent — so callers on the gate path can treat
    "cannot determine" as "flag unset" without special-casing.
    """
    sess = session_var.get()
    if sess is None:
        return default
    tid = _resolve_tenant_id(tenant_id)
    if tid is None:
        return default
    session = cast(AsyncSession, sess)
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tid))
    ).scalar_one_or_none()
    if tenant is None or not tenant.feature_flags:
        return default
    return tenant.feature_flags.get(key, default)


async def set_feature_flag(
    key: str,
    value: Any,
    *,
    tenant_id: UUID | None = None,
) -> None:
    """Persist ``tenants.feature_flags[key] = value`` for the tenant.

    Unlike :func:`get_feature_flag`, this RAISES when it cannot resolve a
    session or tenant — a silently-dropped write is exactly the #31 bug
    (an operator believes approvals are paused when they are not).

    The flag dict is reassigned (not mutated in place) so SQLAlchemy's
    change detection fires without a ``MutableDict`` type on the column —
    the same approach the ``PUT /settings/feature-flags`` route uses.

    Durability: a commit is issued so the pause survives a daemon
    restart. The pause is a safety-relevant operator control (a lock that
    rolls back with the shared daemon session would give false safety —
    the #27 failure mode), so it follows the explicit-commit pattern
    already established by ``EquitySnapshotSweepService.sweep``. Once the
    session-per-event refactor (#29) lands, this commit becomes the
    natural unit-of-work boundary.
    """
    sess = session_var.get()
    if sess is None:
        raise RuntimeError("set_feature_flag requires an active session (session_var is unset)")
    tid = _resolve_tenant_id(tenant_id)
    if tid is None:
        raise RuntimeError(
            "set_feature_flag requires a tenant (pass tenant_id= or bind tenant_id_var)"
        )
    session = cast(AsyncSession, sess)
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tid))
    ).scalar_one_or_none()
    if tenant is None:
        raise RuntimeError(f"set_feature_flag: tenant {tid} not found")
    flags = dict(tenant.feature_flags or {})
    flags[key] = value
    tenant.feature_flags = flags
    await session.commit()


__all__ = ["get_feature_flag", "set_feature_flag"]
