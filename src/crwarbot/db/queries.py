from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import aiosqlite

from crwarbot.api.models import Clan
from crwarbot.domain.aggregate import DayResult, Snapshot
from crwarbot.domain.matching import Candidate
from crwarbot.domain.periods import WAR_PERIOD_TYPES

WAR_TYPES_SQL = ", ".join(f"'{t}'" for t in sorted(WAR_PERIOD_TYPES))


def _now() -> str:
    return datetime.now(UTC).isoformat()


# --- kv -----------------------------------------------------------------------


async def kv_get(conn: aiosqlite.Connection, key: str) -> str | None:
    async with conn.execute("SELECT value FROM kv WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    return row["value"] if row else None


async def kv_set(conn: aiosqlite.Connection, key: str, value: str) -> None:
    await conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await conn.commit()


# --- members ------------------------------------------------------------------


async def sync_roster(conn: aiosqlite.Connection, clan: Clan) -> None:
    """Refresh the roster, retiring members who left instead of deleting them."""
    now = _now()
    tags = [m.tag for m in clan.member_list]

    for member in clan.member_list:
        await conn.execute(
            "INSERT INTO members (player_tag, name, role, in_clan, first_seen, last_seen) "
            "VALUES (?, ?, ?, 1, ?, ?) "
            "ON CONFLICT(player_tag) DO UPDATE SET "
            "  name = excluded.name, role = excluded.role, in_clan = 1, "
            "  last_seen = excluded.last_seen",
            (member.tag, member.name, member.role, now, now),
        )

    if tags:
        placeholders = ", ".join("?" * len(tags))
        await conn.execute(
            f"UPDATE members SET in_clan = 0 WHERE in_clan = 1 "
            f"AND player_tag NOT IN ({placeholders})",
            tags,
        )
    await conn.commit()


async def get_roster(conn: aiosqlite.Connection, only_in_clan: bool = True) -> list[Candidate]:
    sql = "SELECT player_tag, name FROM members"
    if only_in_clan:
        sql += " WHERE in_clan = 1"
    sql += " ORDER BY name COLLATE NOCASE"
    async with conn.execute(sql) as cur:
        rows = await cur.fetchall()
    return [Candidate(player_tag=r["player_tag"], name=r["name"]) for r in rows]


async def ensure_historical_members(
    conn: aiosqlite.Connection, members: Sequence[tuple[str, str]]
) -> None:
    """Register players seen only in the race log so their names resolve later.

    Never touches `in_clan`: the roster sync owns that flag.
    """
    now = _now()
    await conn.executemany(
        "INSERT INTO members (player_tag, name, role, in_clan, first_seen, last_seen) "
        "VALUES (?, ?, NULL, 0, ?, ?) ON CONFLICT(player_tag) DO NOTHING",
        [(tag, name, now, now) for tag, name in members],
    )
    await conn.commit()


async def get_member_names(conn: aiosqlite.Connection) -> dict[str, str]:
    async with conn.execute("SELECT player_tag, name FROM members") as cur:
        rows = await cur.fetchall()
    return {r["player_tag"]: r["name"] for r in rows}


# --- links --------------------------------------------------------------------


@dataclass(frozen=True)
class Link:
    tg_user_id: int
    player_tag: str
    tg_username: str | None
    tg_full_name: str | None


def _link(row: aiosqlite.Row) -> Link:
    return Link(
        tg_user_id=row["tg_user_id"],
        player_tag=row["player_tag"],
        tg_username=row["tg_username"],
        tg_full_name=row["tg_full_name"],
    )


async def upsert_link(
    conn: aiosqlite.Connection,
    tg_user_id: int,
    player_tag: str,
    tg_username: str | None,
    tg_full_name: str | None,
) -> None:
    await conn.execute(
        "INSERT INTO links (tg_user_id, player_tag, tg_username, tg_full_name, linked_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(player_tag) DO UPDATE SET "
        "  tg_user_id = excluded.tg_user_id, tg_username = excluded.tg_username, "
        "  tg_full_name = excluded.tg_full_name, linked_at = excluded.linked_at",
        (tg_user_id, player_tag, tg_username, tg_full_name, _now()),
    )
    await conn.commit()


async def delete_link(conn: aiosqlite.Connection, tg_user_id: int, player_tag: str) -> bool:
    cur = await conn.execute(
        "DELETE FROM links WHERE tg_user_id = ? AND player_tag = ?", (tg_user_id, player_tag)
    )
    await conn.commit()
    return cur.rowcount > 0


async def delete_all_links(conn: aiosqlite.Connection, tg_user_id: int) -> int:
    cur = await conn.execute("DELETE FROM links WHERE tg_user_id = ?", (tg_user_id,))
    await conn.commit()
    return cur.rowcount


async def get_links_by_user(conn: aiosqlite.Connection, tg_user_id: int) -> list[Link]:
    """Every game account this person claimed, ordered the way menus list them."""
    async with conn.execute(
        "SELECT l.* FROM links l LEFT JOIN members m ON m.player_tag = l.player_tag "
        "WHERE l.tg_user_id = ? ORDER BY m.name COLLATE NOCASE, l.player_tag",
        (tg_user_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [_link(r) for r in rows]


async def get_links_by_tag(conn: aiosqlite.Connection) -> dict[str, Link]:
    async with conn.execute("SELECT * FROM links") as cur:
        rows = await cur.fetchall()
    return {r["player_tag"]: _link(r) for r in rows}


# --- snapshots ----------------------------------------------------------------


@dataclass(frozen=True)
class RaceContext:
    season_id: int
    section_index: int
    period_index: int
    period_type: str
    clan_finished: bool = False


async def insert_snapshot_if_changed(
    conn: aiosqlite.Connection,
    ctx: RaceContext,
    player_tag: str,
    fame: int,
    decks_used: int,
    decks_used_today: int,
    boat_attacks: int,
) -> bool:
    """Append a snapshot only when the player's state moved.

    A baseline row is always written on the first sighting within a period,
    otherwise a player who attacks zero times all day leaves no trace and cannot
    be told apart from someone who was not in the clan.
    """
    async with conn.execute(
        "SELECT fame, decks_used, decks_used_today, boat_attacks FROM player_snapshots "
        "WHERE season_id = ? AND section_index = ? AND period_index = ? AND player_tag = ? "
        "ORDER BY ts DESC, id DESC LIMIT 1",
        (ctx.season_id, ctx.section_index, ctx.period_index, player_tag),
    ) as cur:
        last = await cur.fetchone()

    if last is not None and (
        last["fame"] == fame
        and last["decks_used"] == decks_used
        and last["decks_used_today"] == decks_used_today
        and last["boat_attacks"] == boat_attacks
    ):
        return False

    await conn.execute(
        "INSERT INTO player_snapshots (ts, season_id, section_index, period_index, period_type, "
        "player_tag, fame, decks_used, decks_used_today, boat_attacks, clan_finished) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            _now(),
            ctx.season_id,
            ctx.section_index,
            ctx.period_index,
            ctx.period_type,
            player_tag,
            fame,
            decks_used,
            decks_used_today,
            boat_attacks,
            int(ctx.clan_finished),
        ),
    )
    return True


async def load_snapshots(
    conn: aiosqlite.Connection, season_id: int, section_index: int
) -> list[Snapshot]:
    async with conn.execute(
        "SELECT ts, season_id, section_index, period_index, period_type, player_tag, "
        "fame, decks_used, decks_used_today, clan_finished FROM player_snapshots "
        "WHERE season_id = ? AND section_index = ? ORDER BY ts",
        (season_id, section_index),
    ) as cur:
        rows = await cur.fetchall()
    return [Snapshot(**dict(r)) for r in rows]


async def upsert_day_results(conn: aiosqlite.Connection, rows: Iterable[DayResult]) -> None:
    await conn.executemany(
        "INSERT INTO day_results (season_id, section_index, period_index, period_type, "
        "player_tag, decks_used_today, fame_end, fame_delta, day_date, clan_finished) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(season_id, section_index, period_index, player_tag) DO UPDATE SET "
        "  period_type = excluded.period_type, "
        "  decks_used_today = excluded.decks_used_today, "
        "  fame_end = excluded.fame_end, fame_delta = excluded.fame_delta, "
        "  day_date = excluded.day_date, clan_finished = excluded.clan_finished",
        [
            (
                r.season_id,
                r.section_index,
                r.period_index,
                r.period_type,
                r.player_tag,
                r.decks_used_today,
                r.fame_end,
                r.fame_delta,
                r.day_date,
                r.clan_finished,
            )
            for r in rows
        ],
    )
    await conn.commit()


# --- wars ---------------------------------------------------------------------


async def upsert_war(
    conn: aiosqlite.Connection,
    season_id: int,
    section_index: int,
    created_date: str,
    clan_rank: int | None,
    clan_fame: int | None,
) -> None:
    await conn.execute(
        "INSERT INTO wars (season_id, section_index, created_date, clan_rank, clan_fame) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(season_id, section_index) DO UPDATE SET "
        "  created_date = excluded.created_date, clan_rank = excluded.clan_rank, "
        "  clan_fame = excluded.clan_fame",
        (season_id, section_index, created_date, clan_rank, clan_fame),
    )


async def upsert_war_results(
    conn: aiosqlite.Connection, rows: Sequence[tuple[int, int, str, int, int, int]]
) -> None:
    await conn.executemany(
        "INSERT INTO war_results (season_id, section_index, player_tag, fame, decks_used, "
        "boat_attacks) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(season_id, section_index, player_tag) DO UPDATE SET "
        "  fame = excluded.fame, decks_used = excluded.decks_used, "
        "  boat_attacks = excluded.boat_attacks",
        rows,
    )
    await conn.commit()


@dataclass(frozen=True)
class WarRow:
    """One player's result in one river race, however we learned about it."""

    season_id: int
    section_index: int
    player_tag: str
    fame: int
    decks_used: int
    war_days: int
    war_date: str


async def load_war_rows(conn: aiosqlite.Connection) -> list[WarRow]:
    """Per-player per-war rows, merging polled days with backfilled log results.

    Medals and attendance come from different sources on purpose.

    `war_results.fame` is Supercell's own weekly total, so medals are exact for
    every race in the log. `war_results.decks_used` is *not* usable for
    attendance: it counts training-day decks too, so a player with 12 war
    attacks and 4 training attacks is indistinguishable from one who played all
    16 war attacks. Attendance therefore only counts war days the bot polled
    itself, and days on which the clan had already finished are excluded because
    no attack was possible on them.
    """
    async with conn.execute(
        f"""
        SELECT d.season_id, d.section_index, d.player_tag,
               MAX(d.fame_end) AS fame,
               SUM(CASE WHEN d.period_type IN ({WAR_TYPES_SQL}) AND d.clan_finished = 0
                        THEN d.decks_used_today ELSE 0 END) AS decks_used,
               SUM(CASE WHEN d.period_type IN ({WAR_TYPES_SQL}) AND d.clan_finished = 0
                        THEN 1 ELSE 0 END) AS war_days,
               MAX(d.day_date) AS war_date
        FROM day_results d
        GROUP BY d.season_id, d.section_index, d.player_tag
        """
    ) as cur:
        day_rows = await cur.fetchall()

    days = {
        (r["season_id"], r["section_index"], r["player_tag"]): WarRow(
            season_id=r["season_id"],
            section_index=r["section_index"],
            player_tag=r["player_tag"],
            fame=r["fame"] or 0,
            decks_used=r["decks_used"] or 0,
            war_days=r["war_days"] or 0,
            war_date=r["war_date"],
        )
        for r in day_rows
    }

    async with conn.execute(
        "SELECT w.season_id, w.section_index, w.player_tag, w.fame, w.decks_used, "
        "       wars.created_date "
        "FROM war_results w LEFT JOIN wars "
        "  ON wars.season_id = w.season_id AND wars.section_index = w.section_index"
    ) as cur:
        log_rows = await cur.fetchall()

    for r in log_rows:
        key = (r["season_id"], r["section_index"], r["player_tag"])
        polled = days.get(key)
        created = r["created_date"]
        war_date = (created[:4] + "-" + created[4:6] + "-" + created[6:8]) if created else ""
        if polled is None:
            # War predates the bot. Medals are trustworthy, attendance is not
            # knowable, so it contributes zero attack opportunities.
            days[key] = WarRow(
                season_id=r["season_id"],
                section_index=r["section_index"],
                player_tag=r["player_tag"],
                fame=r["fame"],
                decks_used=0,
                war_days=0,
                war_date=war_date,
            )
        else:
            days[key] = WarRow(
                season_id=polled.season_id,
                section_index=polled.section_index,
                player_tag=polled.player_tag,
                fame=r["fame"],
                decks_used=polled.decks_used,
                war_days=polled.war_days,
                war_date=polled.war_date or war_date,
            )

    return sorted(days.values(), key=lambda w: (w.season_id, w.section_index, w.player_tag))


async def resolve_season_id(conn: aiosqlite.Connection, current_section: int) -> int:
    """Infer the season id for the running race.

    `currentriverrace` omits `seasonId`, so we anchor on the newest finished race
    in `riverracelog`: a section index that has not advanced past it means the
    season has rolled over. Stored in `kv` and never allowed to go backwards,
    otherwise a stale log response could renumber existing history.
    """
    async with conn.execute(
        "SELECT season_id, section_index FROM wars ORDER BY season_id DESC, "
        "section_index DESC LIMIT 1"
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        inferred = int(await kv_get(conn, "current_season_id") or 0)
    elif current_section > row["section_index"]:
        inferred = row["season_id"]
    else:
        inferred = row["season_id"] + 1

    stored = await kv_get(conn, "current_season_id")
    if stored is not None:
        inferred = max(inferred, int(stored))
    await kv_set(conn, "current_season_id", str(inferred))
    return inferred


# --- reminders ----------------------------------------------------------------


async def sent_reminder_kinds(
    conn: aiosqlite.Connection, season_id: int, section_index: int, period_index: int
) -> set[str]:
    async with conn.execute(
        "SELECT kind FROM reminders_sent WHERE season_id = ? AND section_index = ? "
        "AND period_index = ?",
        (season_id, section_index, period_index),
    ) as cur:
        rows = await cur.fetchall()
    return {r["kind"] for r in rows}


async def mark_reminder_sent(
    conn: aiosqlite.Connection,
    season_id: int,
    section_index: int,
    period_index: int,
    kind: str,
) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO reminders_sent (season_id, section_index, period_index, kind, "
        "sent_at) VALUES (?, ?, ?, ?, ?)",
        (season_id, section_index, period_index, kind, _now()),
    )
    await conn.commit()
