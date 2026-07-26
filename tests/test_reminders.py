from datetime import UTC, datetime

import pytest

from crwarbot.api.models import CurrentRiverRace
from crwarbot.db import queries
from crwarbot.domain.periods import parse_reset_time
from crwarbot.worker.reminders import check_and_send
from tests.conftest import participant, race_payload

CHAT = -100500
RESET = parse_reset_time("10:15")
DAY_END = datetime(2026, 7, 26, 10, 15, tzinfo=UTC)
AT_T16 = datetime(2026, 7, 25, 18, 15, tzinfo=UTC)
AT_T4 = datetime(2026, 7, 26, 6, 15, tzinfo=UTC)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.sent.append(text)


def race(participants, period_type="warDay", finish_time=None):
    return CurrentRiverRace.model_validate(
        race_payload(participants, period_type=period_type, finish_time=finish_time)
    )


async def seed_roster(conn, members):
    await queries.ensure_historical_members(conn, members)
    await conn.execute("UPDATE members SET in_clan = 1")
    await conn.commit()


async def send(bot, conn, r, now=AT_T16):
    return await check_and_send(
        bot, conn, CHAT, r, 58, grace_minutes=30, reset=RESET, now=now
    )


async def test_sends_debtor_list_at_t16(conn):
    await seed_roster(conn, [("#P1", "One"), ("#P2", "Two")])
    r = race([participant("#P1", "One", 900, 4, 4), participant("#P2", "Two", 200, 1, 1)])
    bot = FakeBot()

    assert await send(bot, conn, r) == ["t16"]
    assert "16 ч" in bot.sent[0]
    assert "Two (1/4)" in bot.sent[0]
    assert "One" not in bot.sent[0]


async def test_players_who_left_the_clan_are_not_nagged(conn):
    # The participants list keeps everyone who touched the race, not just members.
    await seed_roster(conn, [("#P1", "Stays")])
    await queries.ensure_historical_members(conn, [("#GONE", "Left")])
    await conn.execute("UPDATE members SET in_clan = 0 WHERE player_tag = '#GONE'")
    await conn.commit()
    r = race(
        [
            participant("#P1", "Stays", 200, 1, 1),
            participant("#GONE", "Left", 0, 0, 0),
        ]
    )
    bot = FakeBot()

    await send(bot, conn, r)

    assert "Stays" in bot.sent[0]
    assert "Left" not in bot.sent[0]
    assert "(1)" in bot.sent[0]


async def test_finished_race_sends_nothing(conn):
    await seed_roster(conn, [("#P2", "Two")])
    r = race([participant("#P2", "Two", 200, 1, 1)], finish_time="20260726T095105.000Z")
    bot = FakeBot()

    assert await send(bot, conn, r) == []
    assert bot.sent == []


async def test_linked_player_is_mentioned_by_username(conn):
    await seed_roster(conn, [("#P2", "Two")])
    await queries.upsert_link(conn, 42, "#P2", "twoguy", "Two Guy")
    r = race([participant("#P2", "Two", 200, 1, 1)])
    bot = FakeBot()

    await send(bot, conn, r, now=AT_T4)

    assert "@twoguy — Two (1/4)" in bot.sent[0]


async def test_player_without_username_gets_inline_mention(conn):
    await seed_roster(conn, [("#P2", "Two")])
    await queries.upsert_link(conn, 42, "#P2", None, "Two Guy")
    r = race([participant("#P2", "Two", 200, 1, 1)])
    bot = FakeBot()

    await send(bot, conn, r, now=AT_T4)

    assert "tg://user?id=42" in bot.sent[0]


async def test_second_call_does_not_resend(conn):
    await seed_roster(conn, [("#P2", "Two")])
    r = race([participant("#P2", "Two", 200, 1, 1)])
    bot = FakeBot()

    await send(bot, conn, r)
    assert await send(bot, conn, r) == []
    assert len(bot.sent) == 1


async def test_everyone_done_still_gets_a_message(conn):
    await seed_roster(conn, [("#P1", "One")])
    r = race([participant("#P1", "One", 900, 4, 4)])
    bot = FakeBot()

    await send(bot, conn, r)

    assert "Все отыграли" in bot.sent[0]


async def test_training_day_is_skipped(conn):
    await seed_roster(conn, [("#P1", "One")])
    r = race([participant("#P1", "One", 0, 0, 0)], period_type="training")
    bot = FakeBot()

    assert await send(bot, conn, r) == []
    assert bot.sent == []


async def test_failed_send_is_retried_next_tick(conn):
    class BrokenBot(FakeBot):
        async def send_message(self, chat_id, text, parse_mode=None):
            raise RuntimeError("telegram is down")

    await seed_roster(conn, [("#P2", "Two")])
    r = race([participant("#P2", "Two", 200, 1, 1)])

    with pytest.raises(RuntimeError):
        await send(BrokenBot(), conn, r)

    assert await queries.sent_reminder_kinds(conn, 58, 1, 3) == set()

    bot = FakeBot()
    assert await send(bot, conn, r) == ["t16"]
