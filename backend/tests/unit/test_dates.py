"""R1-043: legal dates are UK dates; quarters and accounting periods come from data."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.dates import (
    AccountingPeriod,
    NoAccountingPeriodError,
    accounting_period,
    calendar_quarters,
    quarter,
    uk_date,
)


def test_r1_043_bst_evening_is_next_uk_day() -> None:
    """31 Mar 2027 23:30 UTC is 00:30 BST on 1 Apr, so the UK date is 1 Apr (Q2)."""
    instant = datetime(2027, 3, 31, 23, 30, tzinfo=UTC)
    assert uk_date(instant) == date(2027, 4, 1)
    assert quarter(uk_date(instant)).number == 2


def test_r1_043_gmt_evening_is_same_uk_day() -> None:
    """31 Dec 2027 23:30 UTC is GMT, so the UK date is still 31 Dec (Q4)."""
    instant = datetime(2027, 12, 31, 23, 30, tzinfo=UTC)
    assert uk_date(instant) == date(2027, 12, 31)
    assert quarter(uk_date(instant)).number == 4


def test_r1_043_non_utc_instant_is_converted() -> None:
    plus_ten = timezone(timedelta(hours=10))
    assert uk_date(datetime(2027, 6, 1, 8, 0, tzinfo=plus_ten)) == date(2027, 5, 31)


def test_r1_043_naive_datetime_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        uk_date(datetime(2027, 1, 1, 12, 0))  # noqa: DTZ001 - the point of the test


def test_leap_day_is_q1() -> None:
    q = quarter(date(2028, 2, 29))
    assert (q.year, q.number) == (2028, 1)
    assert q.start == date(2028, 1, 1)
    assert q.end == date(2028, 3, 31)


@given(st.dates(min_value=date(2020, 1, 1), max_value=date(2040, 12, 31)))
def test_quarter_contains_its_date(d: date) -> None:
    q = quarter(d)
    assert q.start <= d <= q.end
    assert 1 <= q.number <= 4


def _periods_with_transition() -> list[AccountingPeriod]:
    """Fixture shaped like SI 2026/830 reg 2: 2027 one annual period, 2028 quarters.
    Source: legislation.gov.uk/uksi/2026/830/made (read 2026-10-03). Test fixture only;
    the real periods are reference data (CLAUDE.md rule 1)."""
    return [
        AccountingPeriod(date(2027, 1, 1), date(2027, 12, 31)),
        *calendar_quarters(2028),
        *calendar_quarters(2029),
    ]


def test_accounting_period_annual_then_quarterly() -> None:
    periods = _periods_with_transition()
    assert accounting_period(date(2027, 8, 15), periods) == AccountingPeriod(
        date(2027, 1, 1), date(2027, 12, 31)
    )
    assert accounting_period(date(2028, 5, 1), periods) == AccountingPeriod(
        date(2028, 4, 1), date(2028, 6, 30)
    )


def test_accounting_period_boundaries() -> None:
    periods = _periods_with_transition()
    assert accounting_period(date(2027, 12, 31), periods).end == date(2027, 12, 31)
    assert accounting_period(date(2028, 1, 1), periods).end == date(2028, 3, 31)


def test_accounting_period_outside_data_is_an_error_not_a_guess() -> None:
    with pytest.raises(NoAccountingPeriodError):
        accounting_period(date(2031, 1, 1), _periods_with_transition())


def test_overlapping_periods_are_refused() -> None:
    bad = [AccountingPeriod(date(2027, 1, 1), date(2027, 12, 31)), *calendar_quarters(2027)]
    with pytest.raises(ValueError, match="overlap"):
        accounting_period(date(2027, 5, 1), bad)
