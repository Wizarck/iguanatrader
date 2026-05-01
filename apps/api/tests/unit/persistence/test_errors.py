"""Persistence error classes — RFC 7807 status codes + IguanaError inheritance."""

from __future__ import annotations

from iguanatrader.persistence.errors import (
    AppendOnlyViolationError,
    JSON1NotAvailableError,
    TenantContextMismatchError,
    TenantContextMissingError,
)
from iguanatrader.shared.errors import (
    ConflictError,
    ForbiddenError,
    IguanaError,
    InternalError,
    ValidationError,
)


def test_tenant_context_missing_inherits_validation_error_with_500() -> None:
    err = TenantContextMissingError("no tenant_id_var")
    assert isinstance(err, ValidationError)
    assert isinstance(err, IguanaError)
    assert err.status == 500
    pd = err.to_problem_dict()
    assert pd["status"] == 500
    assert pd["type"] == "urn:iguanatrader:error:persistence:tenant-context-missing"
    assert pd["title"] == "Tenant Context Missing"
    assert pd["detail"] == "no tenant_id_var"


def test_tenant_context_mismatch_inherits_forbidden_with_403() -> None:
    err = TenantContextMismatchError("expected A got B")
    assert isinstance(err, ForbiddenError)
    assert isinstance(err, IguanaError)
    assert err.status == 403
    pd = err.to_problem_dict()
    assert pd["status"] == 403
    assert pd["type"] == "urn:iguanatrader:error:persistence:tenant-context-mismatch"


def test_append_only_violation_inherits_conflict_with_409() -> None:
    err = AppendOnlyViolationError("UPDATE on audit_log refused")
    assert isinstance(err, ConflictError)
    assert isinstance(err, IguanaError)
    assert err.status == 409
    pd = err.to_problem_dict()
    assert pd["status"] == 409
    assert pd["type"] == "urn:iguanatrader:error:persistence:append-only-violation"


def test_json1_not_available_inherits_internal_with_500() -> None:
    err = JSON1NotAvailableError("Python 3.13 / SQLite 3.45 — see remediation")
    assert isinstance(err, InternalError)
    assert isinstance(err, IguanaError)
    assert err.status == 500
    pd = err.to_problem_dict()
    assert pd["status"] == 500
    assert pd["type"] == "urn:iguanatrader:error:persistence:json1-not-available"


def test_problem_dict_omits_optional_fields_when_unset() -> None:
    err = TenantContextMissingError()
    pd = err.to_problem_dict()
    assert "detail" not in pd
    assert "instance" not in pd
    assert pd.keys() == {"type", "title", "status"}
