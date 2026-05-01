"""Persistence-layer error classes — extend ``shared.errors.IguanaError`` hierarchy.

Per design decision D9 (slice 3 ``persistence-tenant-enforcement``): persistence-
specific errors live here and not in :mod:`shared.errors` because ``shared/`` knows
nothing about persistence per the slice 2 contract. The four classes map to
RFC 7807 Problem Details with stable ``type`` URIs.
"""

from __future__ import annotations

from typing import ClassVar

from iguanatrader.shared.errors import (
    ConflictError,
    ForbiddenError,
    InternalError,
    ValidationError,
)


class TenantContextMissingError(ValidationError):
    """Raised when a tenant-scoped query/insert runs without ``tenant_id_var`` set.

    Status 500 (rendered as RFC 7807) because this is always a server-side bug —
    the caller forgot to set the tenant context before issuing the query. Surface
    as 500 so the operator notices in logs; do NOT leak the missing-context
    detail to API clients verbatim.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:persistence:tenant-context-missing"
    default_title: ClassVar[str] = "Tenant Context Missing"
    default_status: ClassVar[int] = 500


class TenantContextMismatchError(ForbiddenError):
    """Raised on insert when explicit ``tenant_id`` does not match ``tenant_id_var``.

    Status 403 because the most likely cause is an authorisation gap — code path
    received an attacker-controlled ``tenant_id`` and tried to write across tenant
    boundaries. The listener catches it before the row is persisted.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:persistence:tenant-context-mismatch"
    default_title: ClassVar[str] = "Tenant Context Mismatch"
    default_status: ClassVar[int] = 403


class AppendOnlyViolationError(ConflictError):
    """Raised on UPDATE/DELETE attempts against ``__tablename_is_append_only__`` tables.

    Status 409 because the operation conflicts with the table's invariant. The
    listener catches it at flush time; the BEFORE UPDATE/DELETE database trigger
    (added per-table by future migrations) catches the raw-SQL bypass case.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:persistence:append-only-violation"
    default_title: ClassVar[str] = "Append-Only Violation"
    default_status: ClassVar[int] = 409


class JSON1NotAvailableError(InternalError):
    """Raised at boot when SQLite's JSON1 extension is missing or non-functional.

    Status 500 because the application cannot start without JSON1 (``feature_flags``
    column relies on JSON queries). The error message names the detected Python
    and SQLite versions and the two supported remediation paths.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:persistence:json1-not-available"
    default_title: ClassVar[str] = "JSON1 Extension Not Available"
    default_status: ClassVar[int] = 500
