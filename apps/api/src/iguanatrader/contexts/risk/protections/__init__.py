"""Five pure-function protections composed by the risk engine.

Per slice K1 design D2: each module under this package exports a
single top-level callable

    ``evaluate(proposal: TradeProposalInput, state: RiskState, caps: RiskCaps) -> Decision``

The engine in :mod:`iguanatrader.contexts.risk.engine` composes them
in fixed order — ``per_trade → daily → weekly → max_open →
max_drawdown`` — and returns the first non-allow decision (short-
circuit semantics).

Each protection is purely functional: NO ``import datetime``, NO
``import time``, NO SQLAlchemy, NO HTTP. The
:mod:`tests.unit.contexts.risk.test_engine_purity` AST check enforces
this for the engine module; the same hygiene applies here by
convention so a future "import the protections in the property test
fixture" stays clean.
"""

from __future__ import annotations
