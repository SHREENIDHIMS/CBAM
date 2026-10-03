"""R1-044: Decimal only, explicit rounding mode, decimals serialised as strings."""

import json
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from app.core.money import DecimalStr, dumps, quantize, to_decimal


def test_quantize_requires_a_mode() -> None:
    with pytest.raises(TypeError):
        quantize(Decimal("1.234"), places=2)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("raw", "mode", "expected"),
    [
        ("1.999", ROUND_DOWN, "1.99"),
        ("1.995", ROUND_HALF_UP, "2.00"),
        ("1.994", ROUND_HALF_UP, "1.99"),
        ("0.499", ROUND_HALF_UP, "0.50"),
        ("-1.999", ROUND_DOWN, "-1.99"),
    ],
)
def test_quantize_modes(raw: str, mode: str, expected: str) -> None:
    assert quantize(Decimal(raw), places=2, mode=mode) == Decimal(expected)


def test_quantize_accepts_mode_name_from_reference_data() -> None:
    assert quantize(Decimal("2.999"), places=2, mode="ROUND_DOWN") == Decimal("2.99")


def test_quantize_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="rounding mode"):
        quantize(Decimal("1"), places=2, mode="ROUND_SIDEWAYS")


def test_to_decimal_refuses_float() -> None:
    with pytest.raises(TypeError, match="float"):
        to_decimal(0.1)  # type: ignore[arg-type]
    assert to_decimal("0.1") == Decimal("0.1")
    assert to_decimal(3) == Decimal(3)


def test_large_values_keep_full_precision() -> None:
    value = Decimal("123456789012345678901234.12345678")
    assert quantize(value, places=8, mode=ROUND_DOWN) == value


@given(st.decimals(min_value=Decimal("-1000000"), max_value=Decimal("1000000"), places=6))
def test_round_down_never_increases_magnitude(value: Decimal) -> None:
    assert abs(quantize(value, places=2, mode=ROUND_DOWN)) <= abs(value)


class _Row(BaseModel):
    net_mass_kg: DecimalStr


def test_json_decimals_are_strings_and_round_trip_unchanged() -> None:
    row = _Row(net_mass_kg=Decimal("48200.000000"))
    text = row.model_dump_json()
    assert json.loads(text) == {"net_mass_kg": "48200.000000"}
    assert _Row.model_validate_json(text).net_mass_kg == Decimal("48200.000000")


def test_no_scientific_notation() -> None:
    assert json.loads(dumps({"x": Decimal("1E+3")})) == {"x": "1000"}
    assert json.loads(dumps({"x": Decimal("0.00000001")})) == {"x": "0.00000001"}
