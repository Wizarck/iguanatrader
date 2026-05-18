"""POST /api/v1/daemons/{mode}/toggle + POST /api/v1/daemons/{mode}/reconcile.

Slice ``dual-daemon-mode-toggle-and-reconcile``. Session-auth (any
logged-in user; the spec calls for an admin gate but MVP is single-
seat — there is no separate admin role in the codebase yet, so login
is the effective authorisation. Multi-seat / RBAC for these endpoints
is a follow-up).

The toggle endpoint requires password re-entry for ``mode='live'`` —
caught early so the operator doesn't accidentally arm real-money
trading with a misclick on the chip.

Cross-process signal: the API process and the trading_daemon process
are separate (Phase 4 compose split makes this explicit). These
endpoints write to ``tenant_trading_modes`` (toggle) + log the
reconcile intent — the daemon-side wiring that picks up the DB change
+ runs drain/reconcile lives in **Phase 3.5** (heartbeat-tick
flag-change detection + ``pending_reconcile_at`` watermark). For
in-process test runs the bus event path could short-circuit this, but
the prod multi-process deployment needs DB-driven polling.
"""

from __future__ import annotations

from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.auth import verify_password
from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.status import (
    DaemonReconcileOut,
    DaemonToggleIn,
    DaemonToggleOut,
)
from iguanatrader.contexts.trading.repository import TradingModeRepository
from iguanatrader.persistence import User
from iguanatrader.shared.contextvars import session_var
from iguanatrader.shared.errors import IguanaError

log = structlog.get_logger("iguanatrader.api.routes.daemons")

router = APIRouter(prefix="/daemons", tags=["daemons"])


_VALID_MODES = ("paper", "live")
_LIVE_REASON_MIN_CHARS = 20


class InvalidDaemonModeError(IguanaError):
    """Raised when ``{mode}`` is not ``'paper'`` or ``'live'``."""

    type_uri = "urn:iguanatrader:error:invalid-daemon-mode"
    default_title = "Invalid daemon mode"
    default_status = 400


class LiveTogglePayloadInvalidError(IguanaError):
    """Raised when a live-mode toggle is missing the required password / reason."""

    type_uri = "urn:iguanatrader:error:live-toggle-payload-invalid"
    default_title = "Live-toggle payload invalid"
    default_status = 422


class PasswordMismatchError(IguanaError):
    """Raised when ``password_reconfirm`` does not match the operator's hash."""

    type_uri = "urn:iguanatrader:error:password-mismatch"
    default_title = "Password mismatch"
    default_status = 403


def _validate_mode(mode: str) -> str:
    if mode not in _VALID_MODES:
        raise InvalidDaemonModeError(
            detail=f"Daemon mode must be one of {_VALID_MODES}; got {mode!r}."
        )
    return mode


@router.post("/{mode}/toggle", response_model=DaemonToggleOut)
async def toggle_daemon(
    mode: str,
    payload: DaemonToggleIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DaemonToggleOut:
    """Flip the trading_enabled flag for ``(tenant, mode)``.

    For ``mode='live'``: requires ``password_reconfirm`` + ``reason``
    (>=20 chars). Server re-verifies the password using the same
    Argon2id compare as login.

    Audit trail: every successful toggle writes a
    ``daemon.toggle`` structlog event with mode + new_state + user_id
    + reason. The audit_events table is left as a follow-up — the
    structlog event is grep-able and the audit_log slice will sweep
    structlog events into the table when it lands.
    """
    session_var.set(db)
    mode = _validate_mode(mode)

    if mode == "live":
        if not payload.password_reconfirm:
            raise LiveTogglePayloadInvalidError(
                detail="Live-mode toggle requires 'password_reconfirm'."
            )
        if not payload.reason or len(payload.reason.strip()) < _LIVE_REASON_MIN_CHARS:
            raise LiveTogglePayloadInvalidError(
                detail=(
                    f"Live-mode toggle requires 'reason' of at least "
                    f"{_LIVE_REASON_MIN_CHARS} characters."
                )
            )
        if not verify_password(payload.password_reconfirm, user.password_hash):
            log.warning(
                "api.daemons.toggle.password_mismatch",
                tenant_id=str(user.tenant_id),
                user_id=str(user.id),
                mode=mode,
            )
            raise PasswordMismatchError(detail="Password re-confirmation failed.")

    repo = TradingModeRepository()
    row = await repo.set_trading_enabled(
        tenant_id=user.tenant_id,
        mode=mode,
        enabled=payload.enabled,
        user_id=user.id,
        reason=payload.reason,
    )
    await db.commit()

    log.info(
        "daemon.toggle",
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        mode=mode,
        new_state=payload.enabled,
        reason=payload.reason,
    )

    return DaemonToggleOut(
        mode=row.mode,
        enabled=bool(row.enabled),
        last_toggled_at=row.last_toggled_at,
        reason=row.reason,
    )


@router.post("/{mode}/reconcile", response_model=DaemonReconcileOut, status_code=202)
async def reconcile_daemon(
    mode: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DaemonReconcileOut:
    """Emit a reconcile-request for ``(tenant, mode)``; daemon picks it up.

    Returns 202 Accepted — the actual reconcile is fire-and-forget on
    the daemon's side. The ``correlation_id`` in the response can be
    grepped against daemon-side structlog events for trace continuity.

    Cross-process signal (Phase 3.5): stamps
    ``tenant_trading_modes.pending_reconcile_at = now()``. The daemon's
    heartbeat-tick ``poll_for_state_changes`` compares this column
    against an in-memory watermark and runs reconcile when newer.
    """
    session_var.set(db)
    mode = _validate_mode(mode)
    correlation_id = uuid4()

    repo = TradingModeRepository()
    accepted_at = await repo.mark_reconcile_pending(
        tenant_id=user.tenant_id,
        mode=mode,
    )
    await db.commit()

    log.info(
        "daemon.reconcile",
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        mode=mode,
        correlation_id=str(correlation_id),
        pending_reconcile_at=accepted_at.isoformat(),
    )

    return DaemonReconcileOut(
        mode=mode,
        correlation_id=str(correlation_id),
        accepted_at=accepted_at,
    )


__all__ = ["router"]
