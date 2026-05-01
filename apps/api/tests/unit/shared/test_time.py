"""Unit tests for :mod:`iguanatrader.shared.time` — UTC + ISO 8601 helpers.

Covers the spec scenarios for the "Time helpers enforce UTC and ISO 8601"
requirement in ``openspec/changes/shared-primitives/specs/shared-kernel/spec.md``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from iguanatrader.shared.errors import ValidationError
from iguanatrader.shared.time import UTC, format_iso8601, now, parse_iso8601


class TestNow:
    def test_returns_utc_aware_datetime(self) -> None:
        dt = now()
        assert dt.tzinfo is not None
        assert dt.utcoffset() == timedelta(0)
        # Specifically the UTC singleton — not a +00:00 offset that happens to
        # equal UTC. Asserting via tzname avoids being too strict about which
        # tzinfo subclass is used.
        assert dt.tzname() == "UTC"


class TestParseIso8601:
    def test_round_trip_canonical_string_is_identity(self) -> None:
        s = "2026-05-01T10:00:00.123456Z"
        assert format_iso8601(parse_iso8601(s)) == s

    def test_accepts_z_suffix(self) -> None:
        dt = parse_iso8601("2026-05-01T10:00:00.000000Z")
        assert dt == datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)

    def test_accepts_explicit_offset_and_normalises_to_utc(self) -> None:
        # 10:00 in +02:00 == 08:00 UTC.
        dt = parse_iso8601("2026-05-01T10:00:00+02:00")
        assert dt == datetime(2026, 5, 1, 8, 0, 0, tzinfo=UTC)

    def test_rejects_naive_string(self) -> None:
        with pytest.raises(ValidationError, match="naive datetime"):
            parse_iso8601("2026-05-01T10:00:00")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError, match="empty string"):
            parse_iso8601("")

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValidationError, match="not a valid"):
            parse_iso8601("not-a-date")

    def test_rejects_non_str(self) -> None:
        with pytest.raises(ValidationError, match="expected str"):
            parse_iso8601(12345)  # type: ignore[arg-type]


class TestFormatIso8601:
    def test_emits_z_suffix_not_plus_zero(self) -> None:
        dt = datetime(2026, 5, 1, 10, 0, 0, 0, tzinfo=UTC)
        s = format_iso8601(dt)
        assert s.endswith("Z")
        assert "+00:00" not in s

    def test_microsecond_precision_always_present(self) -> None:
        # Even when microsecond == 0 the canonical string carries six digits.
        dt = datetime(2026, 5, 1, 10, 0, 0, 0, tzinfo=UTC)
        assert format_iso8601(dt) == "2026-05-01T10:00:00.000000Z"

    def test_rejects_naive(self) -> None:
        dt = datetime(2026, 5, 1, 10, 0, 0)
        with pytest.raises(ValidationError, match="naive datetime"):
            format_iso8601(dt)

    def test_rejects_non_utc_offset(self) -> None:
        plus_two = timezone(timedelta(hours=2))
        dt = datetime(2026, 5, 1, 10, 0, 0, tzinfo=plus_two)
        with pytest.raises(ValidationError, match="must be UTC"):
            format_iso8601(dt)

    def test_rejects_non_datetime(self) -> None:
        with pytest.raises(ValidationError, match="expected datetime"):
            format_iso8601("2026-05-01")  # type: ignore[arg-type]
