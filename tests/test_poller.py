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
