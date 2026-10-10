from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction

from ..exceptions import GraphMineError
from ..inputs import finite_number


def timestamp(value):
    if type(value) is int:
        return Fraction(value)
    if isinstance(value, str):
        try:
            date = datetime.fromisoformat(value)
            if date.tzinfo is None:
                raise ValueError("missing timezone")
            delta = date.astimezone(timezone.utc) - datetime(
                1970, 1, 1, tzinfo=timezone.utc
            )
            return Fraction(delta.days * 86400 + delta.seconds) + Fraction(
                delta.microseconds, 1_000_000
            )
        except (ValueError, OverflowError) as exc:
            raise GraphMineError(
                "Timestamps must be integer epochs or timezone-aware ISO datetimes"
            ) from exc
    raise GraphMineError("Missing or invalid edge timestamp")


def number(value):
    value = Fraction(value)
    try:
        return value.numerator if value.denominator == 1 else float(value)
    except OverflowError as exc:
        raise GraphMineError(
            "Rational result exceeds finite JSON numeric range"
        ) from exc


def nonnegative_fraction(value, name):
    return Fraction(finite_number(value, name, nonnegative=True))
