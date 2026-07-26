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
    """Players who still owe attacks today, plus the current-member count.

    The participants list keeps everyone who touched this race, including the
    dozens who have since left the clan, so it must be intersected with the
    roster. Otherwise a reminder names people who cannot attack for us any more.
    """
    links = await queries.get_links_by_tag(conn)
    names = await queries.get_member_names(conn)
    current = {c.player_tag for c in await queries.get_roster(conn)}

    active = [p for p in race.clan.participants if p.tag in current]
    debtors = [
        Debtor(
            player_tag=p.tag,
            name=p.name or names.get(p.tag, p.tag),
            decks_used_today=p.decks_used_today,
            link=links.get(p.tag),
        )
        for p in active
        if p.decks_used_today < DECKS_PER_DAY
    ]
    return debtors, len(active)


async def player_aggregates(
    conn: aiosqlite.Connection,
    period: Period,
    season_id: int,
    section_index: int,
    only_current: bool = True,
) -> list[PlayerAggregate]:
    """Aggregate war results over a period.

    Leaderboards restrict to the current roster: the race log backfill drags in
    every player who passed through the clan (160 of them against 49 members on
    a real clan), and ranking ex-members is noise. Single-player lookups keep
    them, so history stays readable after someone leaves.
    """
    war_rows = await queries.load_war_rows(conn)
    names = await queries.get_member_names(conn)

    if only_current:
        current = {c.player_tag for c in await queries.get_roster(conn)}
        war_rows = [r for r in war_rows if r.player_tag in current]

    return aggregate(war_rows, names, period, season_id, section_index)
