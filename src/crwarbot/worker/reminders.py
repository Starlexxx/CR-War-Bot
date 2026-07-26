from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import aiosqlite
from aiogram import Bot

from crwarbot.api.models import CurrentRiverRace
from crwarbot.bot import formatters
from crwarbot.db import queries
from crwarbot.domain.periods import WAR_PERIOD_TYPES, daily_reset_after, due_reminders
from crwarbot.service import build_debtors

log = logging.getLogger(__name__)


async def check_and_send(
    bot: Bot,
    conn: aiosqlite.Connection,
    chat_id: int,
    race: CurrentRiverRace,
    season_id: int,
    grace_minutes: int,
    now: datetime | None = None,
) -> list[str]:
    """Send whichever war-day reminders are due, at most once each."""
    if race.period_type not in WAR_PERIOD_TYPES:
        return []

    war_end = race.war_end
    if war_end is None:
        log.warning("currentriverrace has no warEndTime, skipping reminders")
        return []

    now = now or datetime.now(UTC)
    day_end = daily_reset_after(now, war_end)
    already = await queries.sent_reminder_kinds(
        conn, season_id, race.section_index, race.period_index
    )
    due = due_reminders(now, day_end, timedelta(minutes=grace_minutes), already)
    if not due:
        return []

    debtors, _ = await build_debtors(conn, race)
    sent = []
    for kind in due:
        text = formatters.reminder(kind, debtors)
        await bot.send_message(chat_id, text, parse_mode="HTML")
        # Recorded only after Telegram accepted the message, so a network
        # failure retries on the next tick instead of silently skipping the day.
        await queries.mark_reminder_sent(
            conn, season_id, race.section_index, race.period_index, kind
        )
        sent.append(kind)
        log.info("sent reminder %s to %s (%d debtors)", kind, chat_id, len(debtors))

    return sent
