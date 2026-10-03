import pytest

from app.core.errors import InvalidRequestError
from app.core.pagination import clamp_limit, decode_cursor, encode_cursor


def test_cursor_round_trip() -> None:
    payload = {"k": "2027-03-01", "i": "abc"}
    assert decode_cursor(encode_cursor(payload)) == payload


@pytest.mark.parametrize("bad", ["!!!", "", "bm90LWpzb24", "WzEsMl0"])
def test_bad_cursors_are_refused(bad: str) -> None:
    with pytest.raises(InvalidRequestError):
        decode_cursor(bad)


def test_limit_defaults_and_is_capped_at_200() -> None:
    assert clamp_limit(None) == 50
    assert clamp_limit(1000) == 200
    assert clamp_limit(0) == 1
    assert clamp_limit(25) == 25
