"""Unit tests for :mod:`iguanatrader.shared.errors` — IguanaError + RFC 7807."""

from __future__ import annotations

import pytest
from iguanatrader.shared.errors import (
    AuthError,
    ConflictError,
    CurrencyMismatchError,
    ForbiddenError,
    IguanaError,
    IntegrationError,
    InternalError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)


class TestSubclassDefaults:
    """Each subclass owns a stable type URI + default title + status code."""

    def test_validation_error_status_400(self) -> None:
        e = ValidationError("field 'symbol' missing")
        assert e.status == 400
        assert e.type == "urn:iguanatrader:error:validation"
        assert e.title == "Validation Error"
        assert e.detail == "field 'symbol' missing"

    def test_auth_error_status_401(self) -> None:
        assert AuthError().status == 401
        assert AuthError().type == "urn:iguanatrader:error:auth"

    def test_forbidden_error_status_403(self) -> None:
        assert ForbiddenError().status == 403

    def test_not_found_error_status_404(self) -> None:
        assert NotFoundError().status == 404

    def test_conflict_error_status_409(self) -> None:
        assert ConflictError().status == 409

    def test_rate_limit_error_status_429(self) -> None:
        assert RateLimitError().status == 429

    def test_integration_error_status_502(self) -> None:
        assert IntegrationError().status == 502

    def test_internal_error_status_500(self) -> None:
        assert InternalError().status == 500

    def test_each_subclass_has_unique_type_uri(self) -> None:
        # Currency mismatch shares the validation status code (400) but
        # MUST carry its own type URI so clients can distinguish.
        types = {
            cls(detail="x").type
            for cls in (
                ValidationError,
                AuthError,
                ForbiddenError,
                NotFoundError,
                ConflictError,
                RateLimitError,
                IntegrationError,
                InternalError,
                CurrencyMismatchError,
            )
        }
        assert len(types) == 9


class TestToProblemDict:
    def test_minimal_keys_only(self) -> None:
        e = NotFoundError()
        # No detail, no instance set — only the canonical 3 keys present.
        assert e.to_problem_dict() == {
            "type": "urn:iguanatrader:error:not-found",
            "title": "Not Found",
            "status": 404,
        }

    def test_with_detail_and_instance(self) -> None:
        e = NotFoundError(
            "trade 42 does not exist",
            instance="urn:iguanatrader:trade:42",
        )
        d = e.to_problem_dict()
        assert d == {
            "type": "urn:iguanatrader:error:not-found",
            "title": "Not Found",
            "status": 404,
            "detail": "trade 42 does not exist",
            "instance": "urn:iguanatrader:trade:42",
        }

    def test_no_extra_keys(self) -> None:
        # The handler in slice 5 serialises this dict directly; any extra key
        # would leak internal state. Lock the public surface here.
        e = ValidationError("x")
        e.to_problem_dict()
        assert set(e.to_problem_dict().keys()).issubset(
            {"type", "title", "status", "detail", "instance"}
        )

    def test_overrides_via_constructor(self) -> None:
        e = ValidationError(
            "x",
            title="Custom Title",
            status=422,
            instance="urn:iguanatrader:request:abc",
        )
        d = e.to_problem_dict()
        assert d["title"] == "Custom Title"
        assert d["status"] == 422
        assert d["instance"] == "urn:iguanatrader:request:abc"


class TestHierarchy:
    def test_all_subclasses_inherit_iguana_error(self) -> None:
        for cls in (
            ValidationError,
            AuthError,
            ForbiddenError,
            NotFoundError,
            ConflictError,
            RateLimitError,
            IntegrationError,
            InternalError,
            CurrencyMismatchError,
        ):
            assert issubclass(cls, IguanaError)

    def test_currency_mismatch_inherits_validation(self) -> None:
        # Documented in design D3 / D4: cross-currency math is a 400.
        assert issubclass(CurrencyMismatchError, ValidationError)

    def test_subclass_can_be_caught_as_iguana_error(self) -> None:
        with pytest.raises(IguanaError):
            raise NotFoundError("x")
