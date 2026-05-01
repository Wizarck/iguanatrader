"""UTC-only datetime helpers with strict ISO 8601 semantics.

Per design decision D5 (slice 2 ``shared-primitives``): every datetime
that crosses a module boundary in iguanatrader is timezone-aware UTC.
Naive datetimes are a bug-factory in trading systems where market hours,
fill timestamps, and audit trails MUST be unambiguous.

Format contract (single representation everywhere — also enforced by the
project's ``ISO 8601 single date format`` memory feedback):

    ``YYYY-MM-DDTHH:MM:SS.ffffffZ``

* Microsecond precision (Python's native :func:`datetime.datetime`
  resolution).
* ``Z`` suffix, never ``+00:00``. RFC 3339 explicitly permits both;
  picking one keeps logs/diff-grepping deterministic.

API:

* :func:`now` — UTC-aware ``datetime`` for the current moment.
* :func:`parse_iso8601` — raises :class:`ValidationError` on naive
  input or non-ISO strings.
* :func:`format_iso8601` — emits the canonical string representation;
  raises :class:`ValidationError` if input is naive or non-UTC.
"""

from __future__ import annotations

from datetime import UTC as UTC
from datetime import datetime, timedelta

from iguanatrader.shared.errors import ValidationError

# `UTC as UTC` is the explicit re-export form required by mypy's
# `no_implicit_reexport`. Listed in `__all__` below for documentation;
# downstream callers import as `from iguanatrader.shared.time import UTC`.

_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"
_ZERO = timedelta(0)


def now() -> datetime:
    """Return the current moment as a timezone-aware UTC ``datetime``."""
    return datetime.now(UTC)


def parse_iso8601(s: str) -> datetime:
    """Parse a canonical ISO 8601 string into a UTC-aware ``datetime``.

    Accepts:

    * ``YYYY-MM-DDTHH:MM:SS[.ffffff]Z``
    * ``YYYY-MM-DDTHH:MM:SS[.ffffff]+00:00`` (and other UTC-equivalent
      offsets — converted to UTC on the way out).

    Rejects naive strings (no offset and no ``Z``) with
    :class:`ValidationError`. Rejects malformed strings with the same
    exception.
    """
    if not isinstance(s, str):
        raise ValidationError(f"expected str, got {type(s).__name__}")
    if not s:
        raise ValidationError("empty string is not a valid ISO 8601 datetime")

    # Python's :meth:`datetime.fromisoformat` accepts trailing 'Z' from
    # 3.11 onward. Defensive rewrite kept for clarity / older runtimes.
    candidate = s
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValidationError(f"not a valid ISO 8601 datetime: {s!r}") from exc

    if dt.tzinfo is None:
        raise ValidationError(f"naive datetime not allowed; expected UTC offset or Z suffix: {s!r}")

    # Normalise to UTC. Reject offsets that point to a different zone but
    # only after we've converted them — preserves the timestamp's wall-clock
    # meaning. (E.g. "...+02:00" is accepted and converted to UTC.)
    return dt.astimezone(UTC)


def format_iso8601(dt: datetime) -> str:
    """Render a UTC-aware ``datetime`` into the canonical ISO 8601 form.

    Raises :class:`ValidationError` if ``dt`` is naive or non-UTC.

    The output always uses the ``Z`` suffix and has microsecond
    precision — even for instants whose microsecond component is zero
    (so byte-equality comparisons of formatted strings are safe).
    """
    if not isinstance(dt, datetime):
        raise ValidationError(f"expected datetime, got {type(dt).__name__}")
    if dt.tzinfo is None:
        raise ValidationError("naive datetime not allowed; expected UTC tzinfo")
    if dt.utcoffset() != _ZERO:
        raise ValidationError(
            f"datetime must be UTC; got offset {dt.utcoffset()!r}. "
            "Convert with `dt.astimezone(timezone.utc)` before formatting."
        )
    return dt.strftime(_FMT)


__all__ = ["UTC", "format_iso8601", "now", "parse_iso8601"]
