from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

WAR_PERIOD_TYPES = frozenset({"warDay", "colosseum"})
DECKS_PER_DAY = 4

REMINDER_OFFSETS: dict[str, timedelta] = {
    "t16": timedelta(hours=16),
    "t4": timedelta(hours=4),
}

_RANGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")

PeriodKind = Literal["war", "season", "all", "range"]


class PeriodParseError(ValueError):
    pass


@dataclass(frozen=True)
class Period:
    kind: PeriodKind
    start: date | None = None
    end: date | None = None

    def label(self) -> str:
        return {
            "war": "текущая война",
            "season": "сезон",
            "all": "всё время",
        }.get(self.kind, f"{self.start} — {self.end}")


def parse_period(arg: str | None) -> Period:
    """Parse a user-supplied period argument.

    Accepts `war`, `season`, `all`, or an inclusive `YYYY-MM-DD..YYYY-MM-DD` range.
    """
    if not arg:
        return Period("war")

    token = arg.strip().lower()
    aliases = {
        "war": "war", "война": "war", "кв": "war",
        "season": "season", "сезон": "season",
        "all": "all", "всё": "all", "все": "all",
    }
    if token in aliases:
        return Period(aliases[token])  # type: ignore[arg-type]

    m = _RANGE_RE.match(token)
    if not m:
        raise PeriodParseError(arg)

    start = date.fromisoformat(m.group(1))
    end = date.fromisoformat(m.group(2))
    if start > end:
        start, end = end, start
    return Period("range", start, end)


def parse_reset_time(value: str) -> time:
    """Parse an `HH:MM` daily reset time."""
    hour, minute = value.split(":")
    return time(hour=int(hour), minute=int(minute), tzinfo=UTC)


def resolve_reset_time(
    war_end: datetime | None, observed: str | None, configured: str
) -> time:
    """Pick the most trustworthy source for the daily reset time.

    `currentriverrace` is documented to carry `warEndTime`, whose time-of-day is
    exactly a daily reset, but live responses often omit it. Second best is a
    reset the poller has actually watched happen (`periodIndex` incrementing),
    which is accurate to the poll interval. The configured value is only a
    bootstrap for the first day of operation.
    """
    if war_end is not None:
        return war_end.astimezone(UTC).timetz().replace(second=0, microsecond=0)
    if observed:
        return parse_reset_time(observed)
    return parse_reset_time(configured)


def daily_reset_after(now: datetime, reset: time) -> datetime:
    """End of the war day that is currently running."""
    now = now.astimezone(UTC)
    candidate = now.replace(hour=reset.hour, minute=reset.minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def reminder_target(day_end: datetime, kind: str) -> datetime:
    return day_end - REMINDER_OFFSETS[kind]


def due_reminders(
    now: datetime,
    day_end: datetime,
    grace: timedelta,
    already_sent: set[str],
) -> list[str]:
    """Reminder kinds that should fire right now, newest deadline first.

    The grace window lets a reminder survive a short outage without waking the
    chat hours late with a deadline that has already passed.
    """
    due = []
    for kind in REMINDER_OFFSETS:
        if kind in already_sent:
            continue
        target = reminder_target(day_end, kind)
        if target <= now < target + grace:
            due.append(kind)
    return sorted(due, key=lambda k: REMINDER_OFFSETS[k])
