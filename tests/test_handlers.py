from types import SimpleNamespace

import pytest

from crwarbot.api.models import CurrentRiverRace
from crwarbot.bot import handlers
from crwarbot.db import queries
from crwarbot.worker.poller import RaceState
from tests.conftest import participant, race_payload

USER = SimpleNamespace(id=42, username="vasya", full_name="Вася П")


class FakeMessage:
    def __init__(self, from_user=USER):
        self.from_user = from_user
        self.replies: list[str] = []

    async def answer(self, text, parse_mode=None, reply_markup=None):
        self.replies.append(text)
        return SimpleNamespace(text=text, reply_markup=reply_markup)


def cmd(args=None):
    return SimpleNamespace(args=args)


@pytest.fixture
def deps(conn, settings):
    race = CurrentRiverRace.model_validate(
        race_payload(
            [
                participant("#P1", "Vasya", 900, 4, 4),
                participant("#P2", "Kolya", 300, 2, 2),
            ]
        )
    )
    poller = SimpleNamespace(state=RaceState(race=race, season_id=58))
    return handlers.Deps(conn=conn, client=None, settings=settings, poller=poller)


async def seed_roster(conn):
    await queries.ensure_historical_members(conn, [("#P1", "Vasya"), ("#P2", "Kolya")])
    await conn.execute("UPDATE members SET in_clan = 1")
    await conn.commit()


async def test_link_matches_a_single_roster_entry(conn, deps):
    await seed_roster(conn)
    msg = FakeMessage()

    await handlers.cmd_link(msg, cmd("vasya"), deps)

    assert "Привязано" in msg.replies[0]
    link = await queries.get_link_by_user(conn, 42)
    assert link.player_tag == "#P1"


async def test_link_rejects_unknown_nickname(conn, deps):
    await seed_roster(conn)
    msg = FakeMessage()

    await handlers.cmd_link(msg, cmd("stranger"), deps)

    assert "нет игрока" in msg.replies[0]
    assert await queries.get_link_by_user(conn, 42) is None


async def test_link_offers_buttons_when_ambiguous(conn, deps):
    await queries.ensure_historical_members(conn, [("#A", "Vasya"), ("#B", "Vasyan")])
    await conn.execute("UPDATE members SET in_clan = 1")
    await conn.commit()
    msg = FakeMessage()

    await handlers.cmd_link(msg, cmd("vas"), deps)

    assert "Кого из них" in msg.replies[0]
    assert await queries.get_link_by_user(conn, 42) is None


async def test_relinking_frees_the_previous_player_tag(conn, deps):
    await seed_roster(conn)
    await queries.upsert_link(conn, 99, "#P1", "old", "Old")
    msg = FakeMessage()

    await handlers.cmd_link(msg, cmd("vasya"), deps)

    assert await queries.get_link_by_user(conn, 99) is None
    assert (await queries.get_link_by_user(conn, 42)).player_tag == "#P1"


async def test_today_lists_who_still_owes_attacks(conn, deps):
    await seed_roster(conn)
    msg = FakeMessage()

    await handlers.cmd_today(msg, deps)

    assert "Kolya — 2/4" in msg.replies[0]
    assert "Vasya" not in msg.replies[0]


async def test_today_reports_a_finished_race_instead_of_mass_debt(conn, deps):
    await seed_roster(conn)
    race = CurrentRiverRace.model_validate(
        race_payload(
            [participant("#P1", "Vasya", 900, 4, 0), participant("#P2", "Kolya", 300, 2, 0)],
            finish_time="20260726T095105.000Z",
        )
    )
    deps.poller = SimpleNamespace(state=RaceState(race=race, season_id=58))
    msg = FakeMessage()

    await handlers.cmd_today(msg, deps)

    assert "финишировал" in msg.replies[0]
    assert "Kolya" not in msg.replies[0]


async def test_war_lists_participants_by_medals(conn, deps):
    msg = FakeMessage()

    await handlers.cmd_war(msg, deps)

    body = msg.replies[0]
    assert body.index("Vasya") < body.index("Kolya")


async def test_rating_rejects_a_broken_period(conn, deps):
    msg = FakeMessage()

    await handlers.cmd_rating(msg, cmd("last-week"), deps)

    assert "Период" in msg.replies[0]


async def test_rating_reads_backfilled_history(conn, deps):
    await seed_roster(conn)
    await queries.upsert_war(conn, 58, 0, "20260713T101500.000Z", 1, 5000)
    await queries.upsert_war_results(conn, [(58, 0, "#P1", 2400, 16, 0)])
    msg = FakeMessage()

    await handlers.cmd_rating(msg, cmd("season"), deps)

    assert "Vasya" in msg.replies[0]
    assert "2400" in msg.replies[0]


async def test_rating_excludes_players_who_left(conn, deps):
    await seed_roster(conn)
    await queries.ensure_historical_members(conn, [("#GONE", "Ghost")])
    await queries.upsert_war(conn, 58, 0, "20260713T101500.000Z", 1, 5000)
    await queries.upsert_war_results(
        conn, [(58, 0, "#P1", 2400, 16, 0), (58, 0, "#GONE", 9999, 16, 0)]
    )
    msg = FakeMessage()

    await handlers.cmd_rating(msg, cmd("season"), deps)

    assert "Vasya" in msg.replies[0]
    assert "Ghost" not in msg.replies[0]


async def test_stats_still_works_for_a_departed_player(conn, deps):
    await seed_roster(conn)
    await queries.ensure_historical_members(conn, [("#GONE", "Ghost")])
    await queries.upsert_war(conn, 58, 0, "20260713T101500.000Z", 1, 5000)
    await queries.upsert_war_results(conn, [(58, 0, "#GONE", 3300, 16, 0)])
    msg = FakeMessage()

    await handlers.cmd_stats(msg, cmd("Ghost season"), deps)

    assert "3300" in msg.replies[0]


async def test_me_requires_a_link(conn, deps):
    msg = FakeMessage()

    await handlers.cmd_me(msg, cmd(None), deps)

    assert "не привязан" in msg.replies[0]


async def test_roster_separates_linked_from_unlinked(conn, deps):
    await seed_roster(conn)
    await queries.upsert_link(conn, 42, "#P1", "vasya", "Вася")
    msg = FakeMessage()

    await handlers.cmd_roster(msg, deps)

    body = msg.replies[0]
    assert "@vasya" in body
    assert "Kolya" in body.split("Не привязаны:")[1]
