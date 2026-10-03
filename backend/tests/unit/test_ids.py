import time

from app.core.ids import uuid7


def test_uuid7_version_and_variant() -> None:
    u = uuid7()
    assert u.version == 7
    assert u.variant == "specified in RFC 4122"


def test_uuid7_is_time_ordered_and_unique() -> None:
    first = uuid7()
    time.sleep(0.003)
    second = uuid7()
    assert first < second
    assert len({uuid7() for _ in range(1000)}) == 1000
