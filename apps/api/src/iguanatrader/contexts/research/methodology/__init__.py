"""Methodology pure functions — slice R5 design D1.

Each methodology lives in its own module exposing one top-level
``score(features) -> MethodologyResult`` function. The synthesizer
consumes :data:`METHODOLOGY_REGISTRY` to dispatch by methodology name.

Pure-functional contract: same input → same output, no I/O, no globals,
no LLM. The LLM consumes the :class:`MethodologyResult` for prose
narration in :mod:`iguanatrader.contexts.research.synthesis.synthesizer`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal

from iguanatrader.contexts.research.methodology.base import (
    MethodologyResult,
    PillarScore,
)
from iguanatrader.contexts.research.methodology.canslim import score as canslim_score
from iguanatrader.contexts.research.methodology.magic_formula import (
    score as magic_formula_score,
)
from iguanatrader.contexts.research.methodology.multi_factor import (
    score as multi_factor_score,
)
from iguanatrader.contexts.research.methodology.qarp import score as qarp_score
from iguanatrader.contexts.research.methodology.three_pillar import (
    score as three_pillar_score,
)

ScoreFn = Callable[[Mapping[str, Decimal | None]], MethodologyResult]

#: Hardcoded registry of methodology name → pure scoring function.
#: Adding a 6th methodology requires a code edit here + a new module.
METHODOLOGY_REGISTRY: dict[str, ScoreFn] = {
    "three_pillar": three_pillar_score,
    "canslim": canslim_score,
    "magic_formula": magic_formula_score,
    "qarp": qarp_score,
    "multi_factor": multi_factor_score,
}


__all__ = [
    "METHODOLOGY_REGISTRY",
    "MethodologyResult",
    "PillarScore",
    "ScoreFn",
]
