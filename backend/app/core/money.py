"""Decimal only (CLAUDE.md rule 5, R1-044). No float anywhere in money, mass, emissions or FX."""

import decimal
import json
from decimal import (
    ROUND_05UP,
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
)
from typing import Annotated, Any

from pydantic import PlainSerializer

# Precision 38 and half-even as the *context* default only; every legal rounding names
# its mode explicitly, taken from the rule's reference data.
decimal.getcontext().prec = 38
decimal.getcontext().rounding = ROUND_HALF_EVEN

_MODES = {
    m: m
    for m in (
        ROUND_UP,
        ROUND_DOWN,
        ROUND_CEILING,
        ROUND_FLOOR,
        ROUND_HALF_UP,
        ROUND_HALF_DOWN,
        ROUND_HALF_EVEN,
        ROUND_05UP,
    )
}


def to_decimal(value: str | int | Decimal) -> Decimal:
    """Parse numbers from strings or ints. Floats are refused."""
    if isinstance(value, float):
        raise TypeError("float is not allowed for money, mass, emissions or FX; use str or Decimal")
    return Decimal(value)


def quantize(value: Decimal, *, places: int, mode: str) -> Decimal:
    """Round `value` to `places` decimal places. `mode` is required on purpose."""
    if mode not in _MODES:
        raise ValueError(f"unknown rounding mode {mode!r}")
    exponent = Decimal(1).scaleb(-places)
    return value.quantize(exponent, rounding=_MODES[mode], context=decimal.Context(prec=60))


def decimal_to_str(value: Decimal) -> str:
    """Plain notation, never scientific."""
    return format(value, "f")


# Pydantic field type: Decimal in Python, string in JSON (API convention).
DecimalStr = Annotated[Decimal, PlainSerializer(decimal_to_str, return_type=str, when_used="json")]


def _default(obj: Any) -> str:
    if isinstance(obj, Decimal):
        return decimal_to_str(obj)
    raise TypeError(f"{type(obj).__name__} is not JSON serialisable")


def dumps(obj: Any) -> str:
    """JSON dump that emits Decimals as strings."""
    return json.dumps(obj, default=_default)
