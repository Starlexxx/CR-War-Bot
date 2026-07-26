from datetime import UTC, datetime

import pytest

from crwarbot.api.models import CurrentRiverRace
from crwarbot.db import queries
from crwarbot.worker.reminders import check_and_send
from tests.conftest import participant, race_payload

CHAT = -100500
# warEndTime in the fixture is 2026-07-27 10:15Z, so a war day ends at 10:15Z.
DAY_END = datetime(2026, 7, 26, 10, 15, tzinfo=UTC)
AT_T16 = datetime(2026, 7, 25, 18, 15, tzinfo=UTC)
AT_T4 = datetime(2026, 7, 26, 6, 15, tzinfo=UTC)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.sent.append(text)


def race(participants, period_type="warDay"):
    return CurrentRiverRace.model_validate(
        race_payload(participants, period_type=period_type)
    )


async def seed_member(conn, tag, name):
    await queries.ensure_historical_members(conn, [(tag, name)])


async def test_sends_debtor_list_at_t16(conn):
    r = race([participant("#P1", "One", 900, 4, 4), participant("#P2", "Two", 200, 1, 1)])
    bot = FakeBot()

    sent = await check_and_send(bot, conn, CHAT, r, 58, grace_minutes=30, now=AT_T16)

    assert sent == ["t16"]
    assert "16 ч" in bot.sent[0]
    assert "Two (1/4)" in bot.sent[0]
    assert "One" not in bot.sent[0]


async def test_linked_player_is_mentioned_by_username(conn):
    await seed_member(conn, "#P2", "Two")
    await queries.upsert_link(conn, 42, "#P2", "twoguy", "Two Guy")
    r = race([participant("#P2", "Two", 200, 1, 1)])
    bot = FakeBot()

    await check_and_send(bot, conn, CHAT, r, 58, grace_minutes=30, now=AT_T4)

    assert "@twoguy — Two (1/4)" in bot.sent[0]


async def test_player_without_username_gets_inline_mention(conn):
    await seed_member(conn, "#P2", "Two")
    await queries.upsert_link(conn, 42, "#P2", None, "Two Guy")
    r = race([participant("#P2", "Two", 200, 1, 1)])
    bot = FakeBot()

    await check_and_send(bot, conn, CHAT, r, 58, grace_minutes=30, now=AT_T4)

    assert 'tg://user?id=42' in bot.sent[0]


async def test_second_call_does_not_resend(conn):
    r = race([participant("#P2", "Two", 200, 1, 1)])
    bot = FakeBot()

    await check_and_send(bot, conn, CHAT, r, 58, grace_minutes=30, now=AT_T16)
    again = await check_and_send(bot, conn, CHAT, r, 58, grace_minutes=30, now=AT_T16)

    assert again == []
    assert len(bot.sent) == 1


async def test_everyone_done_still_gets_a_message(conn):
    r = race([participant("#P1", "One", 900, 4, 4)])
    bot = FakeBot()

    await check_and_send(bot, conn, CHAT, r, 58, grace_minutes=30, now=AT_T16)

    assert "Все отыграли" in bot.sent[0]


async def test_training_day_is_skipped(conn):
    r = race([participant("#P1", "One", 0, 0, 0)], period_type="training")
    bot = FakeBot()

    assert await check_and_send(bot, conn, CHAT, r, 58, grace_minutes=30, now=AT_T16) == []
    assert bot.sent == []


async def test_failed_send_is_retried_next_tick(conn):
    class BrokenBot(FakeBot):
        async def send_message(self, chat_id, text, parse_mode=None):
            raise RuntimeError("telegram is down")

    r = race([participant("#P2", "Two", 200, 1, 1)])

    with pytest.raises(RuntimeError):
        await check_and_send(BrokenBot(), conn, CHAT, r, 58, grace_minutes=30, now=AT_T16)

    assert await queries.sent_reminder_kinds(conn, 58, 1, 3) == set()

    bot = FakeBot()
    assert await check_and_send(bot, conn, CHAT, r, 58, grace_minutes=30, now=AT_T16) == ["t16"]
