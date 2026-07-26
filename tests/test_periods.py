from datetime import UTC, datetime, timedelta

import pytest

from crwarbot.domain.periods import (
    Period,
    PeriodParseError,
    daily_reset_after,
    due_reminders,
    parse_period,
    reminder_target,
)


def test_parse_defaults_to_current_war():
    assert parse_period(None) == Period("war")
    assert parse_period("") == Period("war")


@pytest.mark.parametrize(
    ("arg", "kind"),
    [("war", "war"), ("СЕЗОН", "season"), ("all", "all"), ("Все", "all")],
)
def test_parse_keywords(arg, kind):
    assert parse_period(arg).kind == kind


def test_parse_range_normalises_order():
    period = parse_period("2026-03-01..2026-01-01")
    assert period.kind == "range"
    assert str(period.start) == "2026-01-01"
    assert str(period.end) == "2026-03-01"


def test_parse_rejects_garbage():
    with pytest.raises(PeriodParseError):
        parse_period("last-week")


def test_daily_reset_takes_time_of_day_from_war_end():
    war_end = datetime(2026, 7, 27, 10, 15, tzinfo=UTC)
    now = datetime(2026, 7, 25, 18, 0, tzinfo=UTC)
    assert daily_reset_after(now, war_end) == datetime(2026, 7, 26, 10, 15, tzinfo=UTC)


def test_daily_reset_same_day_when_reset_still_ahead():
    war_end = datetime(2026, 7, 27, 10, 15, tzinfo=UTC)
    now = datetime(2026, 7, 25, 9, 0, tzinfo=UTC)
    assert daily_reset_after(now, war_end) == datetime(2026, 7, 25, 10, 15, tzinfo=UTC)


def test_reminders_fire_at_their_target():
    day_end = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
    grace = timedelta(minutes=30)

    at_t16 = reminder_target(day_end, "t16")
    assert due_reminders(at_t16, day_end, grace, set()) == ["t16"]

    at_t4 = reminder_target(day_end, "t4")
    assert due_reminders(at_t4, day_end, grace, set()) == ["t4"]


def test_reminder_skipped_once_grace_expires():
    day_end = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
    grace = timedelta(minutes=30)
    late = reminder_target(day_end, "t16") + timedelta(minutes=31)
    assert due_reminders(late, day_end, grace, set()) == []


def test_already_sent_reminder_is_not_repeated():
    day_end = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
    at_t16 = reminder_target(day_end, "t16")
    assert due_reminders(at_t16, day_end, timedelta(minutes=30), {"t16"}) == []


def test_nothing_due_between_targets():
    day_end = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
    mid = day_end - timedelta(hours=10)
    assert due_reminders(mid, day_end, timedelta(minutes=30), set()) == []
