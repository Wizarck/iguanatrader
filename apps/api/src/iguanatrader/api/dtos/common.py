"""Cross-cutting DTOs (RFC 7807 Problem + ErrorDetail).

Slice 5 (``api-foundation-rfc7807``) plants these as the canonical
TypeScript-emitting models so :command:`openapi-typescript` regenerates
a matching ``Problem`` interface in
``packages/shared-types/src/index.ts`` on every CI run.

The :class:`Problem` model mirrors :meth:`IguanaError.to_problem_dict`
field-for-field (per design D4); FastAPI's exception handler returns the
dict directly with ``media_type="application/problem+json"``, so the
model is consumed by frontend clients (post-typegen) rather than by the
backend itself. ``model_config = ConfigDict(extra="allow")`` keeps
RFC 7807 §3.2 extension members possible (e.g. the rate-limit handler
adds ``retry_after``).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    """Per-field validation context inside a :class:`Problem` body.

    Concrete error subclasses (most often :class:`ValidationError`)
    populate :attr:`Problem.errors` with a list of these — one entry
    per offending field. Frontend renderers can map ``code`` to a
    localised message and ``detail`` to a debug breadcrumb.
    """

    model_config = ConfigDict(extra="forbid")

    field: str | None = None
    code: str
    detail: str | None = None


class Problem(BaseModel):
    """RFC 7807 Problem Details body shape.

    Field-for-field mirror of
    :meth:`iguanatrader.shared.errors.IguanaError.to_problem_dict`.
    The handler in :mod:`iguanatrader.api.errors` returns the dict
    directly; this model exists so OpenAPI lists it as a component
    schema and :command:`openapi-typescript` emits a TypeScript
    ``Problem`` interface for the frontend.

    ``extra="allow"`` accommodates RFC 7807 §3.2 extension members
    (e.g. ``retry_after`` on 429 responses).
    """

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    errors: list[ErrorDetail] | None = None


__all__ = [
    "ErrorDetail",
    "Problem",
]
