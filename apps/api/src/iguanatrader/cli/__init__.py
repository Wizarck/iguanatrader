"""Operator CLI — Typer auto-discovery (slice 5 ``api-foundation-rfc7807``).

Per design D8: every module dropped under this package (other than
``main`` itself) MUST export a top-level ``app: typer.Typer`` instance
to be picked up by :func:`iguanatrader.cli.main._register_subcommands`.
The discovery loop iterates :func:`pkgutil.iter_modules`, imports each
candidate, and ``add_typer``s its ``app`` attribute under a kebab-case
derivation of the module name (e.g. ``bootstrap_tenant.py`` →
``bootstrap-tenant``).

Slice 5 ships ZERO subcommands. The discovery scaffold lands now so
slice T4 (``bootstrap-tenant``), slice O1 (admin commands), and any
later operator surface plug in by adding a single file —
``app.py`` / ``main.py`` are NOT touched.

Performance contract (per gotcha #29): subcommand modules MUST use
lazy imports for heavy dependencies (numpy, pandas, ib_async, etc.).
The discovery loop imports every module at CLI startup; eager
module-level imports of slow libraries make
``python -m iguanatrader.cli --version`` artificially slow. Wrap heavy
imports inside the command function body.

Entrypoints:

* ``python -m iguanatrader.cli`` — invokes
  :func:`iguanatrader.cli.main.cli_app` via ``__main__.py``.
* ``poetry run iguanatrader`` — same target via the
  ``[tool.poetry.scripts]`` alias declared in ``pyproject.toml``.
"""

from __future__ import annotations
