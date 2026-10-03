"""Decision fingerprints: same inputs give the same fingerprint, whatever the order or scale."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.core.decisions import canonical_json, fingerprint


def test_key_order_does_not_matter() -> None:
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})
    assert fingerprint({"a": 1, "b": [1, 2]}) == fingerprint({"b": [1, 2], "a": 1})


def test_decimal_scale_does_not_change_the_fingerprint() -> None:
    assert fingerprint({"v": Decimal("50000.00")}) == fingerprint({"v": Decimal("50000")})
    assert fingerprint({"v": Decimal("1.50")}) == fingerprint({"v": Decimal("1.5")})
    assert fingerprint({"v": Decimal("49999.99")}) != fingerprint({"v": Decimal("50000")})


def test_decimals_are_written_as_plain_strings() -> None:
    assert canonical_json({"v": Decimal("1E+3")}) == '{"v":"1000"}'
    assert canonical_json({"v": Decimal("0.00000001")}) == '{"v":"0.00000001"}'


def test_floats_are_refused() -> None:
    with pytest.raises(TypeError, match="float"):
        canonical_json({"v": 0.1})


def test_dates_uuids_and_instants_are_stable_text() -> None:
    u = UUID("00000000-0000-0000-0000-000000000001")
    out = canonical_json(
        {"d": date(2027, 1, 1), "u": u, "t": datetime(2027, 3, 31, 23, 30, tzinfo=UTC)}
    )
    assert (
        out
        == '{"d":"2027-01-01","t":"2027-03-31T23:30:00+00:00","u":"00000000-0000-0000-0000-000000000001"}'
    )


def test_naive_datetimes_are_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_json({"t": datetime(2027, 1, 1)})  # noqa: DTZ001


def test_sets_are_sorted_lists_and_lists_keep_order() -> None:
    assert canonical_json({"s": {"b", "a"}}) == '{"s":["a","b"]}'
    assert fingerprint({"l": [1, 2]}) != fingerprint({"l": [2, 1]})


def test_fingerprint_is_32_bytes() -> None:
    assert len(fingerprint({"x": 1})) == 32
