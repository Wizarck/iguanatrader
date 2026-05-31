"""Command dispatcher — single entry point for all inbound channel commands.

Per slice P1 design D2 + spec ``approval`` Requirement 3: every
transport (Telegram, Hermes/WhatsApp, dashboard) calls
:func:`dispatch` after sender verification + payload normalisation.
The dispatcher:

1. Looks up the :class:`CommandSpec` in the canonical 17-command
   registry.
2. Enforces the spec's ``required_role`` (admin/user) — caller
   identity is already attested by the channel adapter (whitelist or
   JWT). Role mismatch → ``CommandResult(status="denied")`` + structlog
   ``approval.command.role_denied``.
3. Performs in-process idempotency dedup keyed by the spec's
   ``idempotency_key_source``. The DB UNIQUE on
   ``approval_decisions.request_id`` is the canonical source of truth
   for /approve + /reject; this in-process cache is a fast-path that
   short-circuits before a DB round-trip when a duplicate Telegram
   callback_query lands.
4. Calls the handler.
5. Emits structlog ``approval.command.dispatched`` with the result
   status.

The dispatcher is transport-agnostic — it never imports any
``channels.telegram`` / ``channels.whatsapp_hermes`` / dashboard module.
"""

from __future__ import annotations

import importlib
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

import structlog

from iguanatrader.contexts.approval.channels.types import (
    CommandContext,
    CommandResult,
    CommandSpec,
    IncomingCommand,
)

log = structlog.get_logger("iguanatrader.contexts.approval.command_handler")

#: In-process idempotency cache. Bounded deque + set so duplicates from
#: at-least-once delivery (Telegram callback_query retries; WhatsApp
#: interactive_id replays) short-circuit before a DB round-trip. The
#: DB UNIQUE constraint is the canonical dedup source — this cache is
#: a fast-path optimisation only.
_DEDUP_WINDOW: int = 1024
_recent_keys: deque[str] = deque(maxlen=_DEDUP_WINDOW)
_recent_keys_set: set[str] = set()


def _registry() -> Mapping[str, CommandSpec]:
    """Late-binding registry lookup to break circular imports."""
    pkg = importlib.import_module("iguanatrader.contexts.approval.channels.commands")
    commands_attr = getattr(pkg, "COMMANDS", None)
    if not isinstance(commands_attr, Mapping):
        raise RuntimeError("approval commands package did not export COMMANDS mapping")
    return commands_attr


def _resolve_caller_role(incoming: IncomingCommand) -> str:
    """Read the role declared by the channel adapter on :class:`IncomingCommand`.

    Channels are responsible for setting ``incoming.role`` accurately:
    dashboard reads ``users.role`` from the JWT; bot channels read the
    role facet of ``authorized_senders`` (slice O1 follow-up adds the
    column; until then, bot senders default to ``"user"`` and admin
    commands flow only through the dashboard channel — gotcha #50).
    """
    return incoming.role


async def _approvals_paused(tenant_id: Any) -> bool:
    """Return True only when the tenant's ``approvals_paused`` flag reads True.

    #31: lazily resolves ``observability.tenant_admin.get_feature_flag``
    (late import keeps the dispatcher free of an import-time
    approval→observability dependency, matching the ``/lock`` handler).
    Any failure — module absent, no active session, missing tenant —
    yields False (not paused) and is logged: the gate must never wedge
    the normal approve path shut because it could not read state.
    """
    try:
        tenant_admin = importlib.import_module("iguanatrader.contexts.observability.tenant_admin")
        flag = await tenant_admin.get_feature_flag(
            "approvals_paused",
            False,
            tenant_id=tenant_id,
        )
        return bool(flag)
    except Exception as exc:  # noqa: BLE001 — fail-open + log, never wedge.
        log.warning("approval.command.pause_check_failed", error=str(exc))
        return False


def _idempotency_check(spec: CommandSpec, incoming: IncomingCommand) -> str | None:
    """Return the resolved idempotency key, or ``None`` if not applicable."""
    if spec.idempotency_key_source == "none":
        return None
    # #39: every key is prefixed with the tenant id. The cache is a
    # single process-global structure shared across tenants; without the
    # prefix a key like ``/halt:<sender>:<bucket>`` (or a non-UUID
    # sender_external_id that two tenants happen to share) could let one
    # tenant's command suppress another tenant's command. The DB UNIQUE on
    # ``approval_decisions.request_id`` is the canonical guard; this keeps
    # the fast-path correct under multi-tenant load.
    if spec.idempotency_key_source == "request_id":
        if incoming.request_id is None:
            return None
        return f"{incoming.tenant_id}:{spec.name}:{incoming.request_id}"
    # payload-keyed: combine command, sender, and minute-bucket so
    # rapid retries dedupe but legitimate "halt then halt 30 seconds
    # later" do not.
    from iguanatrader.shared.time import now as utc_now

    minute_bucket = int(utc_now().timestamp() // 30)
    return f"{incoming.tenant_id}:{spec.name}:{incoming.sender_external_id}:{minute_bucket}"


def _record_key(key: str) -> None:
    if key in _recent_keys_set:
        return
    _recent_keys.append(key)
    _recent_keys_set.add(key)
    # deque is bounded; resync the set when an element is evicted.
    if len(_recent_keys) >= _DEDUP_WINDOW:
        _recent_keys_set.clear()
        _recent_keys_set.update(_recent_keys)


def _has_seen(key: str) -> bool:
    return key in _recent_keys_set


def reset_idempotency_cache() -> None:
    """Test-only helper: drop the in-process dedup window."""
    _recent_keys.clear()
    _recent_keys_set.clear()


async def dispatch(
    incoming: IncomingCommand,
    *,
    service: Any,
    message_bus: Any,
    repository: Any | None = None,
    role_resolver: Callable[[IncomingCommand], str] | None = None,
) -> CommandResult:
    """Route ``incoming`` to its handler. Returns the handler's :class:`CommandResult`.

    Unknown commands return ``CommandResult(status="unknown_command")``.
    Role mismatches return ``CommandResult(status="denied")`` and emit
    structlog ``approval.command.role_denied``.
    """
    registry = _registry()
    spec = registry.get(incoming.command_name)
    if spec is None:
        log.info(
            "approval.command.unknown",
            command=incoming.command_name,
            channel=incoming.channel,
        )
        return CommandResult(
            status="unknown_command",
            message=f"Unknown command: {incoming.command_name}",
        )

    actual_role = (role_resolver or _resolve_caller_role)(incoming)
    if spec.required_role == "admin" and actual_role != "admin":
        log.warning(
            "approval.command.role_denied",
            command=spec.name,
            required_role=spec.required_role,
            actual_role=actual_role,
            channel=incoming.channel,
        )
        return CommandResult(
            status="denied",
            message="This command requires admin role.",
        )

    # #31: operator pause gate. While ``approvals_paused`` is set for the
    # tenant, trade-actuating commands (/approve, /override) are denied —
    # even for an authorised caller. Read positively: only a confirmed
    # True pauses; any failure to read the flag (no session, missing
    # tenant) is treated as "not paused" so the dashboard/test paths that
    # lack a daemon session are unaffected, and logged for visibility.
    if spec.blocked_when_paused and await _approvals_paused(incoming.tenant_id):
        log.warning(
            "approval.command.paused_denied",
            command=spec.name,
            channel=incoming.channel,
            tenant_id=str(incoming.tenant_id),
        )
        return CommandResult(
            status="denied",
            message="Approvals are paused (/lock active). Use /unlock to resume.",
        )

    dedup_key = _idempotency_check(spec, incoming)
    if dedup_key is not None and _has_seen(dedup_key):
        log.info(
            "approval.command.deduped",
            command=spec.name,
            channel=incoming.channel,
        )
        return CommandResult(
            status="ok",
            message="Duplicate command suppressed.",
            extra={"deduped": True},
        )

    ctx = CommandContext(
        incoming=incoming,
        service=service,
        message_bus=message_bus,
        repository=repository,
    )
    log.info(
        "approval.command.dispatched",
        command=spec.name,
        channel=incoming.channel,
    )
    result = await spec.handler(ctx)
    if dedup_key is not None and result.status == "ok":
        _record_key(dedup_key)
    return result


__all__ = [
    "dispatch",
    "reset_idempotency_cache",
]
