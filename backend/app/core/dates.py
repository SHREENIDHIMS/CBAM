"""Legal dates are UK dates (CLAUDE.md rule 6, R1-043).

Instants are UTC; legal dates (tax point, deadlines) are `date` computed in Europe/London.
Accounting periods are *data*: the caller passes the periods from reference data, so the
2027-annual / 2028-quarterly switch (SI 2026/830) is never an `if year == 2027` in code.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

LEGAL_TIME_ZONE = ZoneInfo("Europe/London")


class NoAccountingPeriodError(LookupError):
    """No accounting period in the supplied data covers the date. Never guess one."""


def uk_date(instant: datetime) -> date:
    """The UK calendar date of an instant. Use this, never `.date()` on a UTC datetime."""
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("uk_date needs a timezone-aware datetime")
    return instant.astimezone(LEGAL_TIME_ZONE).date()


@dataclass(frozen=True)
class CalendarQuarter:
    year: int
    number: int

    @property
    def start(self) -> date:
        return date(self.year, 3 * (self.number - 1) + 1, 1)

    @property
    def end(self) -> date:
        next_start = (
            date(self.year + 1, 1, 1)
            if self.number == 4
            else date(self.year, 3 * self.number + 1, 1)
        )
        return next_start - timedelta(days=1)


def quarter(d: date) -> CalendarQuarter:
    """Calendar quarter of a date: Q1 Jan-Mar ... Q4 Oct-Dec."""
    return CalendarQuarter(d.year, (d.month - 1) // 3 + 1)


@dataclass(frozen=True)
class AccountingPeriod:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("accounting period ends before it starts")

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end


def calendar_quarters(year: int) -> list[AccountingPeriod]:
    """The four calendar quarters of a year, as period definitions for data loaders/tests."""
    quarters = [CalendarQuarter(year, n) for n in (1, 2, 3, 4)]
    return [AccountingPeriod(q.start, q.end) for q in quarters]


def accounting_period(d: date, periods: Sequence[AccountingPeriod]) -> AccountingPeriod:
    """The accounting period containing `d`, from reference-data `periods`.

    Pass the tax-point date, not the declaration date (CLAUDE.md rule 3).
    """
    ordered = sorted(periods, key=lambda p: p.start)
    for earlier, later in pairwise(ordered):
        if later.start <= earlier.end:
            raise ValueError("accounting periods overlap")
    for period in ordered:
        if period.contains(d):
            return period
    raise NoAccountingPeriodError(f"no accounting period covers {d.isoformat()}")
