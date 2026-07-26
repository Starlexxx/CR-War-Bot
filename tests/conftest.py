from pathlib import Path

import pytest_asyncio

from crwarbot.config import Settings
from crwarbot.db.connection import apply_migrations, connect

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

CLAN_TAG = "#CLAN"


@pytest_asyncio.fixture
async def conn(tmp_path):
    connection = await connect(tmp_path / "test.db")
    await apply_migrations(connection, MIGRATIONS)
    yield connection
    await connection.close()


@pytest_asyncio.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        telegram_bot_token="123:TEST",
        telegram_chat_id=-100500,
        cr_api_token="token",
        cr_clan_tag=CLAN_TAG,
        cr_api_base_url="https://api.test/v1",
        db_path=tmp_path / "test.db",
        migrations_dir=MIGRATIONS,
        poll_interval_seconds=1,
        roster_interval_seconds=3600,
    )


def clan_payload(members):
    return {
        "tag": CLAN_TAG,
        "name": "Test Clan",
        "memberList": [
            {"tag": tag, "name": name, "role": "member"} for tag, name in members
        ],
    }


def race_payload(participants, period_index=3, period_type="warDay", section_index=1):
    return {
        "state": "full",
        "sectionIndex": section_index,
        "periodIndex": period_index,
        "periodType": period_type,
        "warEndTime": "20260727T101500.000Z",
        "collectionEndTime": "20260724T101500.000Z",
        "clan": {
            "tag": CLAN_TAG,
            "name": "Test Clan",
            "fame": sum(p["fame"] for p in participants),
            "participants": participants,
        },
        "clans": [],
    }


def participant(tag, name, fame, decks_used, decks_used_today):
    return {
        "tag": tag,
        "name": name,
        "fame": fame,
        "repairPoints": 0,
        "boatAttacks": 0,
        "decksUsed": decks_used,
        "decksUsedToday": decks_used_today,
    }


def log_payload(entries):
    return {
        "items": [
            {
                "seasonId": season,
                "sectionIndex": section,
                "createdDate": created,
                "standings": [
                    {
                        "rank": 1,
                        "clan": {
                            "tag": CLAN_TAG,
                            "name": "Test Clan",
                            "fame": sum(p["fame"] for p in participants),
                            "participants": participants,
                        },
                    }
                ],
            }
            for season, section, created, participants in entries
        ]
    }
