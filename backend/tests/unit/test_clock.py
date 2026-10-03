from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.clock import FrozenClock, SystemClock


def test_frozen_clock_returns_fixed_utc_instant_and_uk_date() -> None:
    clock = FrozenClock(datetime(2027, 3, 31, 23, 30, tzinfo=UTC))
    assert clock.now() == datetime(2027, 3, 31, 23, 30, tzinfo=UTC)
    assert clock.today_uk() == date(2027, 4, 1)


def test_frozen_clock_can_advance() -> None:
    clock = FrozenClock(datetime(2027, 1, 1, tzinfo=UTC))
    clock.advance(timedelta(days=30))
    assert clock.today_uk() == date(2027, 1, 31)


def test_frozen_clock_refuses_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FrozenClock(datetime(2027, 1, 1))  # noqa: DTZ001


def test_system_clock_is_utc_aware() -> None:
    assert SystemClock().now().tzinfo is not None
