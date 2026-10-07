"""Customs-data coverage calendar (R1-054): which days of a client's "Get customs data" reports
are loaded, which are missing, and which overlap. Pure functions: no database, clock or network.

These are PRODUCT rules, not law. The one number that comes from HMRC guidance, how many of the
latest days are never available yet, is an INPUT (`unavailable_latest_days`, reference data
`customs_data_service`): when it is None no day is ever treated as "not yet available", so the
calendar can only show more gaps, never fewer (CLAUDE.md rules 1 and 2).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

LOADED = "loaded"
LOADED_WITH_ERRORS = "loaded_with_errors"
GAP = "gap"
NOT_YET_AVAILABLE = "not_yet_available"

# Bounds the work of one calendar (one pass per day). A product limit, not a legal number.
MAX_RANGE_DAYS = 2000

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass(frozen=True)
class Window:
    """The days one completed report batch covers (both ends included)."""

    batch_id: str
    covered_from: date
    covered_to: date
    has_errors: bool = False


@dataclass(frozen=True)
class Period:
    covered_from: date
    covered_to: date
    state: str

    @property
    def days(self) -> int:
        return (self.covered_to - self.covered_from).days + 1


@dataclass(frozen=True)
class Overlap:
    covered_from: date
    covered_to: date
    batch_ids: tuple[str, ...]


@dataclass(frozen=True)
class Calendar:
    periods: tuple[Period, ...]
    overlaps: tuple[Overlap, ...]

    @property
    def gaps(self) -> tuple[Period, ...]:
        return tuple(p for p in self.periods if p.state == GAP)

    @property
    def complete(self) -> bool:
        """True when no day is missing or loaded with errors. Days HMRC has not yet made
        available do not count against it."""
        return all(p.state in (LOADED, NOT_YET_AVAILABLE) for p in self.periods)


def build_calendar(
    windows: Sequence[Window],
    *,
    tracking_from: date,
    range_from: date,
    range_to: date,
    today: date,
    unavailable_latest_days: int | None,
) -> Calendar:
    """Day-by-day state of the range, merged into periods.

    Only days from `tracking_from` (the first day to cover) up to `today` are looked at. A day is
    `loaded` when a clean report covers it, `loaded_with_errors` when only reports with rejected
    rows do, `not_yet_available` when it is one of the latest `unavailable_latest_days` days
    (only when that rule is active) and nothing covers it, and otherwise a `gap`. Days covered by
    two or more reports are listed as overlaps; that is normal, not a fault.
    """
    if range_to < range_from:
        raise ValueError("range_to is before range_from")
    start = max(range_from, tracking_from)
    end = min(range_to, today)
    if end < start:
        return Calendar((), ())
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"a calendar covers at most {MAX_RANGE_DAYS} days")
    length = (end - start).days + 1
    batches: list[list[Window]] = [[] for _ in range(length)]
    for window in windows:
        first = max(window.covered_from, start)
        last = min(window.covered_to, end)
        for offset in range((first - start).days, (last - start).days + 1):
            batches[offset].append(window)
    hidden_after = (
        today - timedelta(days=unavailable_latest_days)
        if unavailable_latest_days is not None
        else None
    )
    periods: list[Period] = []
    overlaps: list[Overlap] = []
    for offset in range(length):
        day = start + timedelta(days=offset)
        covering = batches[offset]
        if any(not w.has_errors for w in covering):
            state = LOADED
        elif covering:
            state = LOADED_WITH_ERRORS
        elif hidden_after is not None and day > hidden_after:
            state = NOT_YET_AVAILABLE
        else:
            state = GAP
        if periods and periods[-1].state == state:
            periods[-1] = Period(periods[-1].covered_from, day, state)
        else:
            periods.append(Period(day, day, state))
        if len(covering) > 1:
            ids = tuple(sorted(w.batch_id for w in covering))
            if (
                overlaps
                and overlaps[-1].batch_ids == ids
                and overlaps[-1].covered_to == (day - timedelta(days=1))
            ):
                overlaps[-1] = Overlap(overlaps[-1].covered_from, day, ids)
            else:
                overlaps.append(Overlap(day, day, ids))
    return Calendar(tuple(periods), tuple(overlaps))


def previous_month(day: date) -> tuple[date, date]:
    """First and last day of the calendar month before the one `day` is in."""
    last = day.replace(day=1) - timedelta(days=1)
    return last.replace(day=1), last


def month_key(first_day: date) -> str:
    return f"{first_day.year:04d}-{first_day.month:02d}"


def month_label(first_day: date) -> str:
    return f"{_MONTHS[first_day.month - 1]} {first_day.year}"


def fetch_due_date(month_last_day: date, unavailable_latest_days: int | None) -> date:
    """The day a month's report can be requested: once the month's last day is past the lag, and
    never before the first of the next month."""
    lag = unavailable_latest_days or 0
    return max(month_last_day + timedelta(days=lag), month_last_day + timedelta(days=1))


def gap_key(gap_start: date) -> str:
    """Identifies one gap by its first day, so a growing gap keeps one open task."""
    return f"coverage_gap:{gap_start.isoformat()}"


def month_task_key(first_day: date) -> str:
    return f"fetch_month:{month_key(first_day)}"
