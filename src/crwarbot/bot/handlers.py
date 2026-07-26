from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape

import aiosqlite
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from crwarbot.api.client import SupercellClient
from crwarbot.api.models import CurrentRiverRace
from crwarbot.bot import formatters
from crwarbot.config import Settings
from crwarbot.db import queries
from crwarbot.domain import matching, stats
from crwarbot.domain.periods import Period, PeriodParseError, parse_period
from crwarbot.service import build_debtors, player_aggregates
from crwarbot.worker.poller import Poller

log = logging.getLogger(__name__)

router = Router()

PERIOD_HELP = (
    "Период: <code>war</code>, <code>season</code>, <code>all</code> "
    "или <code>2026-01-01..2026-03-01</code>"
)


@dataclass
class Deps:
    conn: aiosqlite.Connection
    client: SupercellClient
    settings: Settings
    poller: Poller


async def _race(deps: Deps) -> tuple[CurrentRiverRace, int]:
    """Current race, from the poller's cache when it has one."""
    state = deps.poller.state
    if state is not None:
        return state.race, state.season_id
    race = await deps.client.get_current_river_race(deps.settings.cr_clan_tag)
    season_id = await queries.resolve_season_id(deps.conn, race.section_index)
    return race, season_id


def _split_period(args: str | None, *, expect_mode: bool = False) -> tuple[Period, str]:
    tokens = (args or "").split()
    mode = "avg"
    if expect_mode and tokens and tokens[-1].lower() in ("avg", "total"):
        mode = tokens.pop().lower()
    return parse_period(tokens[0] if tokens else None), mode


@router.message(Command("start", "help"))
async def cmd_help(message: Message) -> None:
    await message.answer(formatters.HELP, parse_mode="HTML")


@router.message(Command("link"))
async def cmd_link(message: Message, command: CommandObject, deps: Deps) -> None:
    if not command.args:
        await message.answer("Как пользоваться: <code>/link ник</code>", parse_mode="HTML")
        return

    roster = await queries.get_roster(deps.conn)
    hits = matching.match_roster(command.args, roster)

    if not hits:
        await message.answer(
            f"В клане нет игрока «{escape(command.args)}». Проверь ник или пришли тег вида "
            "<code>#ABC123</code>.",
            parse_mode="HTML",
        )
        return

    user = message.from_user
    assert user is not None

    if len(hits) == 1:
        await _do_link(message, deps, user.id, user.username, user.full_name, hits[0])
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=c.name, callback_data=f"link:{user.id}:{c.player_tag}")]
            for c in hits[:10]
        ]
    )
    await message.answer("Кого из них? ", reply_markup=keyboard)


async def _do_link(
    message: Message,
    deps: Deps,
    tg_user_id: int,
    username: str | None,
    full_name: str | None,
    candidate: matching.Candidate,
) -> None:
    await queries.upsert_link(deps.conn, tg_user_id, candidate.player_tag, username, full_name)
    await message.answer(
        f"Привязано: {escape(candidate.name)} ({escape(candidate.player_tag)})",
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("link:"))
async def cb_link(callback: CallbackQuery, deps: Deps) -> None:
    assert callback.data is not None
    _, owner_id, player_tag = callback.data.split(":", 2)

    if callback.from_user.id != int(owner_id):
        await callback.answer("Это не твой выбор", show_alert=True)
        return

    roster = await queries.get_roster(deps.conn)
    candidate = next((c for c in roster if c.player_tag == player_tag), None)
    if candidate is None:
        await callback.answer("Игрока больше нет в клане", show_alert=True)
        return

    await queries.upsert_link(
        deps.conn,
        callback.from_user.id,
        candidate.player_tag,
        callback.from_user.username,
        callback.from_user.full_name,
    )
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            f"Привязано: {escape(candidate.name)} ({escape(candidate.player_tag)})",
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(Command("unlink"))
async def cmd_unlink(message: Message, deps: Deps) -> None:
    assert message.from_user is not None
    removed = await queries.delete_link(deps.conn, message.from_user.id)
    await message.answer("Привязка снята." if removed else "У тебя не было привязки.")


@router.message(Command("whoami"))
async def cmd_whoami(message: Message, deps: Deps) -> None:
    assert message.from_user is not None
    link = await queries.get_link_by_user(deps.conn, message.from_user.id)
    if link is None:
        await message.answer("Ты не привязан. <code>/link ник</code>", parse_mode="HTML")
        return
    names = await queries.get_member_names(deps.conn)
    name = names.get(link.player_tag, link.player_tag)
    await message.answer(
        f"Ты — {escape(name)} ({escape(link.player_tag)})", parse_mode="HTML"
    )


@router.message(Command("today"))
async def cmd_today(message: Message, deps: Deps) -> None:
    race, _ = await _race(deps)
    debtors, total = await build_debtors(deps.conn, race)
    await message.answer(
        formatters.today(debtors, total, race.period_type), parse_mode="HTML"
    )


@router.message(Command("war"))
async def cmd_war(message: Message, deps: Deps) -> None:
    race, _ = await _race(deps)
    names = await queries.get_member_names(deps.conn)
    current = {c.player_tag for c in await queries.get_roster(deps.conn)}
    rows = sorted(
        (
            (p.name or names.get(p.tag, p.tag), p.fame, p.decks_used)
            for p in race.clan.participants
            # Departed players stay listed if they scored, drop out if they did not.
            if p.tag in current or p.fame > 0
        ),
        key=lambda r: (-r[1], r[0].lower()),
    )
    await message.answer(formatters.war_overview(rows, race.clan.fame), parse_mode="HTML")


@router.message(Command("rating"))
async def cmd_rating(message: Message, command: CommandObject, deps: Deps) -> None:
    try:
        period, mode = _split_period(command.args, expect_mode=True)
    except PeriodParseError:
        await message.answer(PERIOD_HELP, parse_mode="HTML")
        return

    race, season_id = await _race(deps)
    aggregates = await player_aggregates(deps.conn, period, season_id, race.section_index)
    rows = stats.rate(aggregates, deps.settings.miss_penalty, mode)
    await message.answer(formatters.rating(rows, period, mode), parse_mode="HTML")


@router.message(Command("discipline"))
async def cmd_discipline(message: Message, command: CommandObject, deps: Deps) -> None:
    try:
        period, _ = _split_period(command.args)
    except PeriodParseError:
        await message.answer(PERIOD_HELP, parse_mode="HTML")
        return

    race, season_id = await _race(deps)
    aggregates = await player_aggregates(deps.conn, period, season_id, race.section_index)
    rows = stats.discipline(aggregates)
    await message.answer(formatters.discipline(rows, period), parse_mode="HTML")


@router.message(Command("me"))
async def cmd_me(message: Message, command: CommandObject, deps: Deps) -> None:
    assert message.from_user is not None
    link = await queries.get_link_by_user(deps.conn, message.from_user.id)
    if link is None:
        await message.answer(
            "Сначала привяжись: <code>/link ник</code>", parse_mode="HTML"
        )
        return
    await _answer_player_stats(message, deps, link.player_tag, command.args)


@router.message(Command("stats"))
async def cmd_stats(message: Message, command: CommandObject, deps: Deps) -> None:
    tokens = (command.args or "").split()
    if not tokens:
        await message.answer("Как пользоваться: <code>/stats ник</code>", parse_mode="HTML")
        return

    roster = await queries.get_roster(deps.conn, only_in_clan=False)
    hits = matching.match_roster(tokens[0], roster)
    if not hits:
        await message.answer(f"Не знаю игрока «{escape(tokens[0])}».", parse_mode="HTML")
        return
    if len(hits) > 1:
        listed = ", ".join(escape(c.name) for c in hits[:10])
        await message.answer(f"Уточни, кто именно: {listed}", parse_mode="HTML")
        return

    await _answer_player_stats(message, deps, hits[0].player_tag, " ".join(tokens[1:]))


async def _answer_player_stats(
    message: Message, deps: Deps, player_tag: str, args: str | None
) -> None:
    try:
        period, _ = _split_period(args)
    except PeriodParseError:
        await message.answer(PERIOD_HELP, parse_mode="HTML")
        return

    race, season_id = await _race(deps)
    aggregates = await player_aggregates(
        deps.conn, period, season_id, race.section_index, only_current=False
    )
    agg = next((a for a in aggregates if a.player_tag == player_tag), None)
    await message.answer(formatters.player_stats(agg, period), parse_mode="HTML")


@router.message(Command("roster"))
async def cmd_roster(message: Message, deps: Deps) -> None:
    roster = await queries.get_roster(deps.conn)
    links = await queries.get_links_by_tag(deps.conn)
    linked = [(c.name, links[c.player_tag]) for c in roster if c.player_tag in links]
    unlinked = [c.name for c in roster if c.player_tag not in links]
    await message.answer(formatters.roster(linked, unlinked), parse_mode="HTML")
