"""Production ``LLMClient`` adapter wrapping the Anthropic Python SDK.

Replaces the deferred-install carry-forward from slice R5 (
:class:`iguanatrader.contexts.research.synthesis.llm_client.AnthropicLLMClient`
documented but not shipped). The fake remains in `llm_client.py` for
unit-test determinism; production composition root constructs this
adapter and passes it into :class:`Synthesizer`.

Per design D1 of deployment-foundation: the model name varies per call
(synthesizer chooses claude-3-5-sonnet vs claude-3-5-haiku per node
profile) so :func:`@cost_meter` is composed dynamically inside
:meth:`complete` rather than as a static decorator on the method.

Slice ``llm-observability-and-signals``: each call ALSO opens a
Langfuse generation span via :func:`start_generation` so the ELIGIA
cross-stack dashboard receives the same observation. ``@cost_meter`` +
Langfuse coexist intentionally — the former persists
:class:`ApiCostEvent` in DB for **tenant billing**, the latter exports
to **shared org-wide observability**; the audiences are disjoint.
The application tag is ``iguanatrader-synthesis`` so synthesis calls
bucket into a stable row of the dashboard's ``Top by Application``
widget (the explainer / risk / journal endpoints add their own tags).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from iguanatrader.contexts.observability.budget import BudgetStatus, check_budget
from iguanatrader.contexts.observability.cost_meter import cost_meter
from iguanatrader.contexts.observability.errors import BudgetExceededError
from iguanatrader.contexts.observability.langfuse_client import start_generation
from iguanatrader.contexts.research.synthesis.llm_client import LLMCompletion
from iguanatrader.shared.contextvars import session_var, tenant_id_var

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

log = structlog.get_logger("iguanatrader.contexts.research.synthesis.anthropic_client")


class AnthropicLLMClient:
    """Async :class:`LLMClient` adapter — thin wrapper over ``messages.create()``.

    Construction takes the API key explicitly; the composition root
    reads it from :class:`SecretEnv.anthropic_api_key`. Adapters
    NEVER read ``os.environ`` directly (anti-pattern §3 of design.md).

    Composition with :func:`@cost_meter` is dynamic-per-call because
    the model name varies per synthesizer invocation. The decorator
    persists one :class:`ApiCostEvent` per call when a request session
    is bound; otherwise the structlog breadcrumb fires (best-effort).
    """

    def __init__(
        self,
        api_key: str,
        *,
        client: AsyncAnthropic | None = None,
        enforce_budget: bool = False,
    ) -> None:
        self._api_key = api_key
        self._client: AsyncAnthropic | None = client
        # Hard per-tenant monthly LLM budget cutoff. OFF by default; the
        # composition factory flips it from IGUANATRADER_LLM_BUDGET_ENFORCE_ENABLED.
        # The adapter itself never reads os.environ (design.md §3).
        self._enforce_budget = enforce_budget

    def _ensure_client(self) -> AsyncAnthropic:
        if self._client is None:
            from anthropic import AsyncAnthropic as _AsyncAnthropic

            self._client = _AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def complete(
        self,
        prompt: str,
        *,
        model: str,
        replay_key: str | None,
        max_tokens: int,
        langfuse_application: str = "iguanatrader-synthesis",
    ) -> LLMCompletion:
        """Issue an Anthropic ``messages.create`` and return an :class:`LLMCompletion`.

        Wraps the per-call body in :func:`@cost_meter` so each invocation
        records an :class:`ApiCostEvent` with the provider+model price.

        ALSO opens a Langfuse generation span tagged
        ``application=langfuse_application``. Default is
        ``iguanatrader-synthesis``; the proposal-advisor / journaling
        services override with ``iguanatrader-explainer`` /
        ``iguanatrader-risk`` / ``iguanatrader-journal`` so each
        application is a distinct bucket in the ELIGIA cost-by-tag
        widgets. The span is closed via ``end(level=DEFAULT|ERROR)``
        after the SDK call returns or raises — exception path uses
        ``level=ERROR`` so the ELIGIA TracesTodayCard ``error`` count
        increments correctly.

        When budget enforcement is on (flag-gated), a hard cutoff is
        checked BEFORE the metered SDK call: a tenant over its monthly cap
        raises :class:`BudgetExceededError` here, so no spend is recorded
        for the blocked call. See :meth:`_enforce_budget_or_raise`.
        """
        if self._enforce_budget:
            await self._enforce_budget_or_raise(model)

        async def _call() -> LLMCompletion:
            gen = start_generation(
                name="anthropic.messages.create",
                model=model,
                application=langfuse_application,
                input_data=prompt,
                metadata={
                    "max_tokens": max_tokens,
                    "replay_key": replay_key,
                },
            )
            try:
                client = self._ensure_client()
                message = await client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = self._extract_text(message)
                usage = message.usage
                cached = bool(getattr(usage, "cache_read_input_tokens", 0))
                completion = LLMCompletion(
                    text=text,
                    tokens_input=int(usage.input_tokens),
                    tokens_output=int(usage.output_tokens),
                    cached=cached,
                    model=model,
                    replay_key=replay_key,
                )
                gen.update(
                    output=text,
                    usage_details={
                        "input": completion.tokens_input,
                        "output": completion.tokens_output,
                        "cache_read_input_tokens": int(
                            getattr(usage, "cache_read_input_tokens", 0) or 0
                        ),
                    },
                )
                gen.end(level="DEFAULT")
                return completion
            except Exception as exc:
                gen.end(
                    level="ERROR",
                    status_message=f"{type(exc).__name__}: {exc!s}",
                )
                raise

        decorated = cost_meter(provider="anthropic", model=model)(_call)
        return await decorated()

    async def _enforce_budget_or_raise(self, model: str) -> None:
        """Hard per-tenant monthly LLM budget cutoff (the "corte duro").

        FAIL-OPEN by construction — the cap caps *spend*, never *trading*:

        - No tenant context or no bound DB session → we cannot price the
          cap, so let the call through (don't block on an infra gap).
        - A budget-check error → log + let the call through (same reason).
        - Only a definitive :class:`BudgetStatus.BLOCK_100` raises.

        Raising here (before the metered SDK call) means the blocked call
        records no cost. Because the entry/exit/journal gates already
        handle exceptions fail-open, a raise turns into "skip the LLM, let
        the deterministic stop/target + human-approval path proceed";
        user-initiated endpoints (brief/explain) surface RFC 7807 402.
        """
        tenant_id = tenant_id_var.get()
        if tenant_id is None or session_var.get() is None:
            return
        try:
            state = await check_budget(tenant_id)
        except Exception as exc:
            # Fail-open: a budget-check failure must never block an LLM call.
            log.warning(
                "observability.budget.check_failed_fail_open",
                tenant_id=str(tenant_id),
                model=model,
                error=str(exc),
            )
            return
        if state.status is BudgetStatus.BLOCK_100:
            log.warning(
                "observability.budget.llm_blocked",
                tenant_id=str(tenant_id),
                model=model,
                percent_used=state.percent_used,
                spent_usd=str(state.spent_usd),
                cap_usd=str(state.cap_usd),
            )
            raise BudgetExceededError(
                detail=(
                    f"Tenant {tenant_id} exceeded the monthly LLM budget cap "
                    f"of {state.cap_usd} USD ({state.percent_used}% used). "
                    "Raise the cap via `iguanatrader admin set-budget` or wait "
                    "for next-month rollover."
                ),
            )

    @staticmethod
    def _extract_text(message: object) -> str:
        """Extract the first text block from an Anthropic ``Message`` response.

        Anthropic returns ``message.content`` as a list of content blocks
        (text / tool_use / etc.). Synthesizer only requests text, so we
        concatenate all ``TextBlock`` entries; defensive against future
        SDK changes that mix block types.
        """
        content = getattr(message, "content", None)
        if not content:
            return ""
        parts: list[str] = []
        for block in content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)


def build_anthropic_llm_client_from_env() -> AnthropicLLMClient:
    """Composition-root helper — builds an :class:`AnthropicLLMClient` from process env.

    Used by the FastAPI lifespan / CLI bootstrap when the operator opts
    into production wiring. Tests construct :class:`AnthropicLLMClient`
    directly with an injected mock client; tests NEVER call this helper.

    This is the single composition point for every production LLM client
    (API routes, brief synthesis, and the daemon's Opus entry/exit
    advisors all funnel through here via ``build_llm_client``), so reading
    the budget-enforce flag here applies the cap uniformly across all gates.
    """
    import os

    from iguanatrader.config.secrets import SecretEnv

    flag = os.environ.get("IGUANATRADER_LLM_BUDGET_ENFORCE_ENABLED", "")
    enforce_budget = flag.strip().lower() in ("1", "true", "yes", "on")
    return AnthropicLLMClient(
        api_key=SecretEnv().anthropic_api_key,
        enforce_budget=enforce_budget,
    )


__all__ = ["AnthropicLLMClient", "build_anthropic_llm_client_from_env"]
