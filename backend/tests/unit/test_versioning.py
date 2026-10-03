"""R1-045: If-Match header parsing. Mismatch handling is tested against the database."""

import pytest

from app.core.errors import PreconditionRequiredError
from app.core.versioning import etag, parse_if_match


@pytest.mark.parametrize("header", ['"3"', 'W/"3"', "3", ' "3" '])
def test_parse_if_match_accepts_common_forms(header: str) -> None:
    assert parse_if_match(header) == 3


def test_missing_if_match_is_428() -> None:
    with pytest.raises(PreconditionRequiredError) as exc:
        parse_if_match(None)
    assert exc.value.status == 428


@pytest.mark.parametrize("header", ["", "abc", '"-1"', '"0"', "*", '"1", "2"'])
def test_unusable_if_match_is_refused(header: str) -> None:
    with pytest.raises(PreconditionRequiredError):
        parse_if_match(header)


def test_etag_round_trip() -> None:
    assert etag(7) == '"7"'
    assert parse_if_match(etag(7)) == 7
