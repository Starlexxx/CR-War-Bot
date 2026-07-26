from __future__ import annotations

import logging

import aiosqlite

from crwarbot.api.client import SupercellClient, normalize_tag
from crwarbot.db import queries

log = logging.getLogger(__name__)


async def backfill_river_race_log(
    conn: aiosqlite.Connection,
    client: SupercellClient,
    clan_tag: str,
    limit: int = 20,
) -> int:
    """Import finished races so the bot has history from its very first run."""
    race_log = await client.get_river_race_log(clan_tag, limit=limit)
    wanted = normalize_tag(clan_tag)
    imported = 0

    for entry in race_log.items:
        standing = next(
            (s for s in entry.standings if normalize_tag(s.clan.tag) == wanted),
            None,
        )
        if standing is None:
            continue

        await queries.upsert_war(
            conn,
            entry.season_id,
            entry.section_index,
            entry.created_date,
            standing.rank,
            standing.clan.fame,
        )
        await queries.ensure_historical_members(
            conn, [(p.tag, p.name) for p in standing.clan.participants if p.name]
        )
        await queries.upsert_war_results(
            conn,
            [
                (
                    entry.season_id,
                    entry.section_index,
                    p.tag,
                    p.fame,
                    p.decks_used,
                    p.boat_attacks,
                )
                for p in standing.clan.participants
            ],
        )
        imported += 1

    log.info("backfilled %d races", imported)
    return imported
