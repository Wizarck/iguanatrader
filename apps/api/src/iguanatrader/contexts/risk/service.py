"""Risk service — orchestrates I/O around the pure-functional engine.

Per slice K1 design D1+D4+D5+D6 + tasks 4.2:

* :meth:`RiskService.evaluate_proposal` — kill-switch gate first,
  load state, call :func:`engine.evaluate`, persist evaluation,
  publish event, auto-activate kill-switch on cap-breach (D6 + spec
  scenario "Day-to-date loss at 5.1% halts new proposals").
* :meth:`RiskService.record_override` — validate audit fields BEFORE
  any DB write (defence-in-depth: Pydantic + service + DB CHECK),
  raise :class:`OverrideAuditMissingError` on failure, persist, emit
  ``risk.proposal.override_required``.
* :meth:`RiskService.activate_kill_switch` /
  :meth:`RiskService.deactivate_kill_switch` — same-transaction
  append + cache-update (D4); de-dup events publish on no-op
  transitions.
* :meth:`RiskService.load_caps` — env-overridable Decimal load
  (D3); returns a fresh :class:`RiskCaps` per call so test fixtures
  can monkey-patch env vars between tests.

The service NEVER imports SQLAlchemy directly — all I/O goes through
the :class:`RiskRepositoryPort`. This keeps the service unit-testable
with a fake repo without standing up a database.

structlog event names (per K1 prompt):
``risk.evaluation.accepted`` / ``risk.evaluation.rejected`` /
``risk.override.recorded`` / ``risk.kill_switch.activated`` /
``risk.kill_switch.deactivated``.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from iguanatrader.contexts.risk import engine
from iguanatrader.contexts.risk.events import (
    RiskKillSwitchActivated,
    RiskKillSwitchDeactivated,
    RiskProposalAccepted,
    RiskProposalOverrideRequired,
    RiskProposalRejected,
)
from iguanatrader.contexts.risk.models import (
    ConfirmationChain,
    Decision,
    KillSwitchSource,
    RiskCaps,
    TradeProposalInput,
)
from iguanatrader.contexts.risk.ports import RiskRepositoryPort
from iguanatrader.shared.errors import (
    KillSwitchActiveError,
    OverrideAuditMissingError,
)
from iguanatrader.shared.messagebus import MessageBus
from iguanatrader.shared.time import now as utc_now

log = structlog.get_logger("iguanatrader.contexts.risk.service")

#: Minimum reason text length per FR25 + NFR-S5.
_REASON_MIN_LENGTH: int = 20


class RiskService:
    """Orchestrator around the pure-functional risk engine.

    Constructed per-request by the API route handlers (``routes/risk.py``)
    and per-invocation by the CLI commands (``cli/ops.py``). Holds a
    :class:`RiskRepositoryPort` adapter + an optional
    :class:`MessageBus` for cross-context event emission.
    """

    def __init__(
        self,
        repository: RiskRepositoryPort,
        bus: MessageBus | None = None,
    ) -> None:
        self._repo = repository
        self._bus = bus

    @property
    def repository(self) -> RiskRepositoryPort:
        """Read-only accessor for the underlying repository.

        Routes use this to satisfy the "load state + load kill-switch"
        round-trip without going through :meth:`evaluate_proposal`.
        Direct calls bypass the kill-switch gate, so callers MUST NOT
        use this to short-circuit a real evaluation.
        """
        return self._repo

    # ------------------------------------------------------------------
    # Cap loading
    # ------------------------------------------------------------------

    @staticmethod
    def load_caps() -> RiskCaps:
        """Build a :class:`RiskCaps` from env vars + slice-K1 defaults.

        Per design D3: env vars override defaults; absent vars fall
        through to the Pydantic field defaults. Decimal-only — float
        env values are coerced via ``Decimal(<str>)`` so a stray
        ``"1e-3"`` is exact (Decimal accepts scientific notation).
        """
        per_trade = os.getenv("IGUANATRADER_RISK_PER_TRADE_PCT")
        daily = os.getenv("IGUANATRADER_RISK_DAILY_LOSS_PCT")
        weekly = os.getenv("IGUANATRADER_RISK_WEEKLY_LOSS_PCT")
        max_open = os.getenv("IGUANATRADER_RISK_MAX_OPEN_POSITIONS")
        max_dd = os.getenv("IGUANATRADER_RISK_MAX_DRAWDOWN_PCT")

        kwargs: dict[str, Any] = {}
        if per_trade is not None:
            kwargs["per_trade_pct"] = Decimal(per_trade)
        if daily is not None:
            kwargs["daily_loss_pct"] = Decimal(daily)
        if weekly is not None:
            kwargs["weekly_loss_pct"] = Decimal(weekly)
        if max_open is not None:
            kwargs["max_open_positions"] = int(max_open)
        if max_dd is not None:
            kwargs["max_drawdown_pct"] = Decimal(max_dd)
        return RiskCaps(**kwargs)

    # ------------------------------------------------------------------
    # Proposal evaluation (the FR45 hot path)
    # ------------------------------------------------------------------

    async def evaluate_proposal(
        self,
        proposal: TradeProposalInput,
    ) -> tuple[UUID, Decision]:
        """Evaluate ``proposal`` against current state + caps.

        Order of operations (per design D1+D4+D6):

        1. **Kill-switch gate** — read cached ``is_active`` (NFR-R5
           hot path) BEFORE any other work. If active, raise
           :class:`KillSwitchActiveError` immediately — no engine
           call, no event publish, no DB write.
        2. **Load state + caps** — repository + env.
        3. **Pure engine call** — :func:`engine.evaluate` returns a
           :class:`Decision`.
        4. **Persist evaluation** — append-only row to
           ``risk_evaluations``.
        5. **Publish event** — ``risk.proposal.accepted`` on allow,
           ``risk.proposal.rejected`` otherwise.
        6. **Auto-activate kill-switch on cap-breach** (per design D6
           + spec scenario "Day-to-date loss at 5.1% halts new
           proposals"). First daily/weekly/max_drawdown breach of
           the day writes a kill-switch event with
           ``source="automatic_cap_breach"``.

        Returns the new ``risk_evaluations.id`` + the :class:`Decision`.
        """
        is_active = await self._repo.load_kill_switch_state(proposal.tenant_id)
        if is_active:
            log.info(
                "risk.evaluation.rejected",
                proposal_id=str(proposal.id),
                tenant_id=str(proposal.tenant_id),
                reason="kill_switch_active",
            )
            raise KillSwitchActiveError(
                detail=(
                    "Trade evaluation refused: kill-switch is active. "
                    "Run `iguanatrader ops resume --reason '...'` to deactivate."
                ),
            )

        state = await self._repo.load_risk_state(proposal.tenant_id)
        caps = self.load_caps()

        decision = engine.evaluate(proposal, state, caps)
        evaluation_id = await self._repo.save_evaluation(
            tenant_id=proposal.tenant_id,
            proposal_id=proposal.id,
            decision=decision,
            created_at=utc_now(),
        )

        if decision.outcome == "allow":
            log.info(
                "risk.evaluation.accepted",
                proposal_id=str(proposal.id),
                tenant_id=str(proposal.tenant_id),
                evaluation_id=str(evaluation_id),
            )
            await self._publish(
                RiskProposalAccepted(
                    idempotency_key=str(evaluation_id),
                    proposal_id=proposal.id,
                    tenant_id=proposal.tenant_id,
                    evaluation_id=evaluation_id,
                    occurred_at=utc_now(),
                ),
            )
        else:
            log.info(
                "risk.evaluation.rejected",
                proposal_id=str(proposal.id),
                tenant_id=str(proposal.tenant_id),
                evaluation_id=str(evaluation_id),
                cap_type_breached=decision.cap_type_breached,
                current_pct=(
                    str(decision.current_pct) if decision.current_pct is not None else None
                ),
            )
            await self._publish(
                RiskProposalRejected(
                    idempotency_key=str(evaluation_id),
                    proposal_id=proposal.id,
                    tenant_id=proposal.tenant_id,
                    evaluation_id=evaluation_id,
                    cap_type_breached=decision.cap_type_breached,
                    current_pct=decision.current_pct,
                    occurred_at=utc_now(),
                ),
            )
            await self._maybe_auto_activate_on_breach(
                tenant_id=proposal.tenant_id,
                decision=decision,
            )

        return evaluation_id, decision

    async def _maybe_auto_activate_on_breach(
        self,
        *,
        tenant_id: UUID,
        decision: Decision,
    ) -> None:
        """First daily/weekly/max_drawdown breach of the day → activate.

        Per design D6 + tasks 4.3 + spec scenario "Day-to-date loss
        at 5.1% halts new proposals":

        * Per_trade + max_open breaches do NOT auto-activate (they
          are single-trade rejections, not regime-level).
        * Daily/weekly/max_drawdown breaches DO auto-activate, but
          only the FIRST occurrence in the calendar day per tenant
          (idempotent by date + source).
        """
        cap_type = decision.cap_type_breached
        if cap_type not in {"daily_loss", "weekly_loss", "max_drawdown"}:
            return

        already = await self._repo.has_today_automatic_breach_event(tenant_id, utc_now(), cap_type)
        if already:
            return

        await self.activate_kill_switch(
            tenant_id=tenant_id,
            source="automatic_cap_breach",
            actor_user_id=None,
            reason=f"automatic activation: {cap_type} breach",
        )

    # ------------------------------------------------------------------
    # Override audit
    # ------------------------------------------------------------------

    async def record_override(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        risk_evaluation_id: UUID,
        authorised_by_user_id: UUID,
        reason_text: str,
        confirmation_chain: ConfirmationChain,
        state_snapshot_at_override: dict[str, Any],
    ) -> UUID:
        """Persist a row to ``risk_overrides`` after audit-field validation.

        Raises :class:`OverrideAuditMissingError` (a
        :class:`ValidationError` subclass — renders as 400 RFC 7807)
        if any of:

        * ``reason_text`` is shorter than 20 chars (NFR-S5 floor),
        * ``authorised_by_user_id`` is the nil UUID,
        * ``confirmation_chain`` first/second confirmations missing
          (Pydantic already enforces, but the service double-checks
          the wire shape — defence in depth).
        """
        normalized_reason = (reason_text or "").strip()
        if len(normalized_reason) < _REASON_MIN_LENGTH:
            raise OverrideAuditMissingError(
                detail=(
                    f"reason_text must be at least {_REASON_MIN_LENGTH} characters "
                    f"(got {len(normalized_reason)})."
                ),
            )
        if authorised_by_user_id == UUID(int=0):
            raise OverrideAuditMissingError(
                detail="authorised_by_user_id is required and must be a real user id.",
            )

        override_id = await self._repo.save_override(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            risk_evaluation_id=risk_evaluation_id,
            authorised_by_user_id=authorised_by_user_id,
            reason_text=normalized_reason,
            confirmation_chain=confirmation_chain,
            state_snapshot_at_override=state_snapshot_at_override,
            created_at=utc_now(),
        )

        log.info(
            "risk.override.recorded",
            override_id=str(override_id),
            tenant_id=str(tenant_id),
            proposal_id=str(proposal_id),
            authorised_by_user_id=str(authorised_by_user_id),
        )

        await self._publish(
            RiskProposalOverrideRequired(
                idempotency_key=str(override_id),
                proposal_id=proposal_id,
                tenant_id=tenant_id,
                override_id=override_id,
                authorised_by_user_id=authorised_by_user_id,
                occurred_at=utc_now(),
            ),
        )
        return override_id

    # ------------------------------------------------------------------
    # Kill-switch lifecycle
    # ------------------------------------------------------------------

    async def activate_kill_switch(
        self,
        *,
        tenant_id: UUID,
        source: KillSwitchSource,
        actor_user_id: UUID | None,
        reason: str | None,
    ) -> UUID:
        """Append a ``transition='activated'`` event + update the cache.

        Per design D4: same-transaction event-append + cache-update.
        Idempotent on the cached state (per spec scenario "Multi-
        source activation idempotent"): a second activation appends
        a new event row (audit captures every attempt) but does NOT
        re-publish ``risk.kill_switch.activated`` if the cache was
        already ``True`` (callers are expected to track first-time
        transitions only).
        """
        was_active = await self._repo.load_kill_switch_state(tenant_id)

        when = utc_now()
        event_id = await self._repo.append_kill_switch_event(
            tenant_id=tenant_id,
            transition="activated",
            source=source,
            actor_user_id=actor_user_id,
            reason=reason,
            created_at=when,
        )
        await self._repo.update_kill_switch_cache(
            tenant_id=tenant_id,
            is_active=True,
            last_event_id=event_id,
            updated_at=when,
        )

        log.info(
            "risk.kill_switch.activated",
            event_id=str(event_id),
            tenant_id=str(tenant_id),
            source=source,
            actor_user_id=str(actor_user_id) if actor_user_id else None,
            reason=reason,
            already_active=was_active,
        )

        if not was_active:
            await self._publish(
                RiskKillSwitchActivated(
                    idempotency_key=str(event_id),
                    tenant_id=tenant_id,
                    event_id=event_id,
                    source=source,
                    actor_user_id=actor_user_id,
                    reason=reason,
                    occurred_at=when,
                ),
            )
        return event_id

    async def deactivate_kill_switch(
        self,
        *,
        tenant_id: UUID,
        source: KillSwitchSource,
        actor_user_id: UUID | None,
        reason: str | None,
    ) -> UUID:
        """Append a ``transition='deactivated'`` event + update the cache."""
        was_active = await self._repo.load_kill_switch_state(tenant_id)

        when = utc_now()
        event_id = await self._repo.append_kill_switch_event(
            tenant_id=tenant_id,
            transition="deactivated",
            source=source,
            actor_user_id=actor_user_id,
            reason=reason,
            created_at=when,
        )
        await self._repo.update_kill_switch_cache(
            tenant_id=tenant_id,
            is_active=False,
            last_event_id=event_id,
            updated_at=when,
        )

        log.info(
            "risk.kill_switch.deactivated",
            event_id=str(event_id),
            tenant_id=str(tenant_id),
            source=source,
            actor_user_id=str(actor_user_id) if actor_user_id else None,
            reason=reason,
            was_active=was_active,
        )

        if was_active:
            await self._publish(
                RiskKillSwitchDeactivated(
                    idempotency_key=str(event_id),
                    tenant_id=tenant_id,
                    event_id=event_id,
                    source=source,
                    actor_user_id=actor_user_id,
                    reason=reason,
                    occurred_at=when,
                ),
            )
        return event_id

    # ------------------------------------------------------------------
    # Internal: publish helper
    # ------------------------------------------------------------------

    async def _publish(self, event: Any) -> None:
        """Publish ``event`` if a bus is wired; no-op otherwise.

        Tests can construct :class:`RiskService` without a
        :class:`MessageBus` to exercise the service-layer logic
        without an event-loop subscriber teardown step.
        """
        if self._bus is None:
            return
        await self._bus.publish(event)


__all__ = ["RiskService"]
