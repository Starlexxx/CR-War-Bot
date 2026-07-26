from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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


def daily_reset_after(now: datetime, war_end: datetime) -> datetime:
    """End of the war day that is currently running.

    The game's daily reset is not a fixed constant we can hardcode, but every
    river race ends exactly at one, so `warEndTime`'s time-of-day gives it to us.
    """
    now = now.astimezone(UTC)
    war_end = war_end.astimezone(UTC)
    candidate = now.replace(
        hour=war_end.hour,
        minute=war_end.minute,
        second=war_end.second,
        microsecond=0,
    )
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
