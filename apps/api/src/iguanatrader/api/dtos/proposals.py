"""Pydantic v2 DTOs for trade proposals (FR11, FR74).

``ProposalOut`` is the read projection of :class:`TradeProposal`;
``ProposalIn`` is the write shape for any future "manual proposal"
endpoint (T4 confirms; for now the slice plants the shape so the
OpenAPI surface + TS interface are stable).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProposalOut(BaseModel):
    """Read projection of :class:`TradeProposal` (FR11, FR74)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    tenant_id: UUID
    strategy_config_id: UUID
    symbol: str = Field(examples=["SPY"])
    side: str = Field(examples=["buy"])
    quantity: Decimal = Field(examples=[Decimal("10.0")])
    entry_price_indicative: Decimal = Field(examples=[Decimal("450.25")])
    stop_price: Decimal = Field(examples=[Decimal("440.00")])
    confidence_score: Decimal | None = Field(
        default=None,
        examples=[Decimal("0.7500")],
    )
    reasoning: dict[str, Any] = Field(
        examples=[
            {
                "signal_source": "donchian_atr",
                "lookback_bars": 20,
                "stop_rationale": "2x ATR below entry",
                "brief_excerpt": "SPY tested 20-day high; ATR 4.5",
            }
        ],
    )
    research_brief_id: UUID | None = None
    mode: str = Field(examples=["paper"])
    correlation_id: UUID
    created_at: datetime


class ProposalIn(BaseModel):
    """Write shape for a manual proposal (T4 confirms whether endpoint lands)."""

    model_config = ConfigDict(extra="forbid")

    strategy_config_id: UUID
    symbol: str = Field(examples=["SPY"])
    side: str = Field(examples=["buy"])
    quantity: Decimal = Field(examples=[Decimal("10.0")])
    entry_price_indicative: Decimal = Field(examples=[Decimal("450.25")])
    stop_price: Decimal = Field(examples=[Decimal("440.00")])
    confidence_score: Decimal | None = Field(
        default=None,
        examples=[Decimal("0.7500")],
    )
    reasoning: dict[str, Any] = Field(
        examples=[{"manual": True, "operator_note": "discretionary entry"}],
    )
    research_brief_id: UUID | None = None
    mode: str = Field(default="paper", examples=["paper"])


class ProposalListOut(BaseModel):
    """Paginated list wrapper for :class:`ProposalOut`."""

    model_config = ConfigDict(extra="forbid")

    items: list[ProposalOut]
    next_cursor: str | None = None
    total: int | None = None


class ProposalExplainOut(BaseModel):
    """LLM-generated narrative for a proposal (slice ``llm-observability-and-signals``).

    Read-only projection: the route does NOT persist this — every call
    regenerates. Operators receive ``narrative`` for direct rendering;
    ``model`` + ``generated_at`` + token counts are metadata for cost
    transparency in the UI / API logs.
    """

    model_config = ConfigDict(extra="forbid")

    proposal_id: UUID
    narrative: str
    model: str
    generated_at: datetime
    tokens_input: int
    tokens_output: int


class ProposalRiskOut(BaseModel):
    """LLM risk review (informational, does NOT block approval)."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: UUID
    risk_score: int = Field(ge=0, le=100, examples=[42])
    flags: list[str] = Field(
        examples=[["entry above 50d high", "stop tighter than 1x ATR"]],
    )
    rationale: str
    model: str
    generated_at: datetime
    tokens_input: int
    tokens_output: int


__all__ = [
    "ProposalExplainOut",
    "ProposalIn",
    "ProposalListOut",
    "ProposalOut",
    "ProposalRiskOut",
]
