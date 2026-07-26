from __future__ import annotations

import aiosqlite

from crwarbot.api.models import CurrentRiverRace
from crwarbot.bot.formatters import Debtor
from crwarbot.db import queries
from crwarbot.domain.periods import DECKS_PER_DAY, Period
from crwarbot.domain.stats import PlayerAggregate, aggregate


async def build_debtors(
    conn: aiosqlite.Connection, race: CurrentRiverRace
) -> tuple[list[Debtor], int]:
    """Players who still owe attacks today, plus the total participant count."""
    links = await queries.get_links_by_tag(conn)
    names = await queries.get_member_names(conn)

    debtors = [
        Debtor(
            player_tag=p.tag,
            name=p.name or names.get(p.tag, p.tag),
            decks_used_today=p.decks_used_today,
            link=links.get(p.tag),
        )
        for p in race.clan.participants
        if p.decks_used_today < DECKS_PER_DAY
    ]
    return debtors, len(race.clan.participants)


async def player_aggregates(
    conn: aiosqlite.Connection,
    period: Period,
    season_id: int,
    section_index: int,
) -> list[PlayerAggregate]:
    war_rows = await queries.load_war_rows(conn)
    names = await queries.get_member_names(conn)
    return aggregate(war_rows, names, period, season_id, section_index)
