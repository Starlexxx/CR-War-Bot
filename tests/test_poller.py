import httpx
import pytest
import respx

from crwarbot.api.client import SupercellClient
from crwarbot.db import queries
from crwarbot.worker.poller import Poller
from tests.conftest import (
    clan_payload,
    log_payload,
    participant,
    race_payload,
)

BASE = "https://api.test/v1"
CLAN = "%23CLAN"


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.sent.append((chat_id, text))


def mock_api(router, race, members=(("#P1", "One"), ("#P2", "Two")), log_entries=()):
    router.get(f"{BASE}/clans/{CLAN}").mock(
        return_value=httpx.Response(200, json=clan_payload(members))
    )
    router.get(f"{BASE}/clans/{CLAN}/currentriverrace").mock(
        return_value=httpx.Response(200, json=race)
    )
    router.get(f"{BASE}/clans/{CLAN}/riverracelog").mock(
        return_value=httpx.Response(200, json=log_payload(log_entries))
    )


@pytest.fixture
def client(settings):
    return SupercellClient(settings.cr_api_base_url, settings.cr_api_token)


@respx.mock
async def test_tick_records_snapshots_and_day_results(conn, settings, client):
    race = race_payload(
        [
            participant("#P1", "One", 900, 4, 4),
            participant("#P2", "Two", 300, 2, 2),
        ]
    )
    mock_api(respx.mock, race)

    bot = FakeBot()
    state = await Poller(conn, client, bot, settings).tick()

    snapshots = await queries.load_snapshots(conn, state.season_id, 1)
    assert {s.player_tag for s in snapshots} == {"#P1", "#P2"}

    async with conn.execute("SELECT player_tag, fame_end, decks_used_today FROM day_results") as c:
        rows = {r["player_tag"]: (r["fame_end"], r["decks_used_today"]) for r in await c.fetchall()}
    assert rows == {"#P1": (900, 4), "#P2": (300, 2)}


@respx.mock
async def test_unchanged_player_does_not_write_a_second_snapshot(conn, settings, client):
    race = race_payload([participant("#P1", "One", 900, 4, 4)])
    mock_api(respx.mock, race)

    poller = Poller(conn, client, FakeBot(), settings)
    state = await poller.tick()
    await poller.tick()

    snapshots = await queries.load_snapshots(conn, state.season_id, 1)
    assert len(snapshots) == 1


@respx.mock
async def test_roster_sync_retires_departed_members(conn, settings, client):
    race = race_payload([participant("#P1", "One", 900, 4, 4)])
    mock_api(respx.mock, race, members=(("#P1", "One"),))

    await Poller(conn, client, FakeBot(), settings).tick()

    await queries.upsert_link(conn, 1, "#GONE", "ghost", "Ghost")
    async with conn.execute("SELECT player_tag, in_clan FROM members") as c:
        rows = {r["player_tag"]: r["in_clan"] for r in await c.fetchall()}
    assert rows == {"#P1": 1}


@respx.mock
async def test_backfill_imports_finished_wars(conn, settings, client):
    race = race_payload([participant("#P1", "One", 100, 1, 1)])
    mock_api(
        respx.mock,
        race,
        log_entries=[
            (57, 0, "20260713T101500.000Z", [participant("#P1", "One", 2000, 16, 0)]),
        ],
    )

    await Poller(conn, client, FakeBot(), settings).tick()

    async with conn.execute("SELECT season_id, section_index, fame FROM war_results") as c:
        rows = [tuple(r) for r in await c.fetchall()]
    assert rows == [(57, 0, 2000)]


@respx.mock
async def test_season_id_rolls_over_when_sections_restart(conn, settings, client):
    race = race_payload([participant("#P1", "One", 100, 1, 1)], section_index=0)
    mock_api(
        respx.mock,
        race,
        log_entries=[
            (57, 3, "20260713T101500.000Z", [participant("#P1", "One", 2000, 16, 0)]),
        ],
    )

    state = await Poller(conn, client, FakeBot(), settings).tick()
    assert state.season_id == 58


@respx.mock
async def test_first_rollover_pins_down_the_reset_time(conn, settings, client):
    # The API never tells us when a war day ends, so the poller has to watch for it.
    day_one = race_payload([participant("#P1", "One", 100, 1, 1)], period_index=19)
    mock_api(respx.mock, day_one)
    poller = Poller(conn, client, FakeBot(), settings)
    await poller.tick()
    assert await queries.kv_get(conn, "observed_reset_utc") is None

    respx.mock.get(f"{BASE}/clans/{CLAN}/currentriverrace").mock(
        return_value=httpx.Response(
            200, json=race_payload([participant("#P1", "One", 0, 0, 0)], period_index=20)
        )
    )
    await poller.tick()

    observed = await queries.kv_get(conn, "observed_reset_utc")
    assert observed is not None and len(observed) == 5


@respx.mock
async def test_day_after_the_clan_finished_is_not_an_attack_opportunity(
    conn, settings, client
):
    # Regression: the bot started mid-race after the clan had already finished.
    # Everyone showed decksUsedToday=0, which was read as four missed attacks.
    race = race_payload(
        [participant("#P1", "One", 2150, 12, 0)],
        period_index=20,
        finish_time="20260726T095105.000Z",
    )
    mock_api(respx.mock, race, members=(("#P1", "One"),))

    await Poller(conn, client, FakeBot(), settings).tick()

    rows = await queries.load_war_rows(conn)
    assert [(r.war_days, r.decks_used) for r in rows] == [(0, 0)]


@respx.mock
async def test_backfilled_war_contributes_medals_but_no_attendance(conn, settings, client):
    # war_results.decks_used counts training decks too, so it cannot be trusted
    # for attendance even though its fame is exact.
    race = race_payload([participant("#P1", "One", 100, 1, 1)], section_index=1)
    mock_api(
        respx.mock,
        race,
        members=(("#P1", "One"),),
        log_entries=[
            (57, 0, "20260713T101500.000Z", [participant("#P1", "One", 2550, 16, 0)]),
        ],
    )

    await Poller(conn, client, FakeBot(), settings).tick()

    backfilled = [r for r in await queries.load_war_rows(conn) if r.section_index == 0]
    assert len(backfilled) == 1
    assert backfilled[0].fame == 2550
    assert (backfilled[0].war_days, backfilled[0].decks_used) == (0, 0)


@respx.mock
async def test_training_day_sends_no_reminder(conn, settings, client):
    race = race_payload(
        [participant("#P1", "One", 0, 0, 0)],
        period_index=1,
        period_type="training",
    )
    mock_api(respx.mock, race)

    bot = FakeBot()
    await Poller(conn, client, bot, settings).tick()
    assert bot.sent == []
