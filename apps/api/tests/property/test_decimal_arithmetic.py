"""Property test: Money arithmetic preserves precision (no float drift).

Per ``specs/shared-kernel/spec.md``:

    Scenario: Same-currency arithmetic is exact
    WHEN ``Money(Decimal("0.1"), "USD") + Money(Decimal("0.2"), "USD")`` is
    computed THEN the result equals ``Money(Decimal("0.3"), "USD")`` exactly.

This test generalises that to any pair of Decimals: ``a + b - b == a``,
property that fails for IEEE-754 floats but holds for Decimal at any
precision the construction supports.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from iguanatrader.shared.types import Money

# Decimal strategy: bounded magnitude so we don't run into MAX_PREC limits;
# at most 8 fractional digits so the values are representable in any of our
# supported currencies (BTC = 8 places is the max). Allow negatives — money
# has signed semantics (debits / shorts).
_decimals = st.decimals(
    min_value=Decimal("-1000000"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=8,
)


@given(a=_decimals, b=_decimals)
def test_add_then_sub_is_identity(a: Decimal, b: Decimal) -> None:
    """For any pair (a, b): Money(a) + Money(b) - Money(b) == Money(a)."""
    ma = Money(a, "USD")
    mb = Money(b, "USD")
    assert (ma + mb - mb) == ma


@given(a=_decimals, b=_decimals)
def test_add_is_commutative(a: Decimal, b: Decimal) -> None:
    """For any pair (a, b): Money(a) + Money(b) == Money(b) + Money(a)."""
    ma = Money(a, "USD")
    mb = Money(b, "USD")
    assert (ma + mb) == (mb + ma)


@given(a=_decimals)
def test_double_negation_is_identity(a: Decimal) -> None:
    """For any a: -(-Money(a)) == Money(a)."""
    m = Money(a, "USD")
    once = -m
    twice = -once
    assert twice == m


@given(a=_decimals, n=st.integers(min_value=-100, max_value=100))
def test_repeated_add_equals_multiplication(a: Decimal, n: int) -> None:
    """Money(a) added to itself n times equals Money(a) * n.

    This catches accumulation bugs where intermediate quantizations would
    drift the sum away from the analytic product.
    """
    if n == 0:
        pytest.skip("0 multiplication is a separate test concern")
    m = Money(a, "USD")
    if n > 0:
        acc = m
        for _ in range(n - 1):
            acc = acc + m
        assert acc == m * n
    else:
        acc = -m
        for _ in range(-n - 1):
            acc = acc - m
        assert acc == m * n
