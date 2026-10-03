"""Injected clock (CLAUDE.md rule 6). Business logic never calls now() directly."""

from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from app.core.dates import uk_date


class Clock(Protocol):
    def now(self) -> datetime:
        """The current instant, timezone-aware UTC."""
        ...

    def today_uk(self) -> date:
        """The current UK legal date."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def today_uk(self) -> date:
        return uk_date(self.now())


class FrozenClock:
    """A clock that only moves when told to; for tests and historical replays."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("FrozenClock needs a timezone-aware datetime")
        self._instant = instant.astimezone(UTC)

    def now(self) -> datetime:
        return self._instant

    def today_uk(self) -> date:
        return uk_date(self._instant)

    def advance(self, delta: timedelta) -> None:
        self._instant += delta


def get_clock() -> Clock:
    """FastAPI dependency; tests override it with `app.dependency_overrides`."""
    return SystemClock()
