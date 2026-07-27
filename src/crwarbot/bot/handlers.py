from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape

import aiosqlite
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from crwarbot.api.client import SupercellClient
from crwarbot.api.models import CurrentRiverRace
from crwarbot.bot import formatters, keyboards
from crwarbot.config import Settings
from crwarbot.db import queries
from crwarbot.domain import matching, stats
from crwarbot.domain.periods import Period, PeriodParseError, parse_period
from crwarbot.service import build_debtors, player_aggregates
from crwarbot.worker.poller import Poller

log = logging.getLogger(__name__)

router = Router()

Rendered = tuple[str, InlineKeyboardMarkup | None]

PERIOD_HELP = (
    "Период: <code>war</code>, <code>season</code>, <code>all</code> "
    "или <code>2026-01-01..2026-03-01</code>"
)
NOT_LINKED = "Ты не привязан. Нажми «Привязаться» в /menu или напиши <code>/link ник</code>"


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


# --- renderers ----------------------------------------------------------------
# Shared by the typed commands and the inline menu so both always agree.


async def _render_today(deps: Deps) -> Rendered:
    race, _ = await _race(deps)
    debtors, total = await build_debtors(deps.conn, race)
    text = formatters.today(
        debtors, total, race.period_type, finished=race.clan.finish_time is not None
    )
    return text, keyboards.plain()


async def _render_war(deps: Deps) -> Rendered:
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
    return formatters.war_overview(rows, race.clan.fame), keyboards.plain()


async def _render_rating(deps: Deps, period: Period, mode: str) -> Rendered:
    race, season_id = await _race(deps)
    aggregates = await player_aggregates(deps.conn, period, season_id, race.section_index)
    rows = stats.rate(aggregates, deps.settings.miss_penalty, mode)
    return formatters.rating(rows, period, mode), keyboards.rating(period, mode)


async def _render_discipline(deps: Deps, period: Period) -> Rendered:
    race, season_id = await _race(deps)
    aggregates = await player_aggregates(deps.conn, period, season_id, race.section_index)
    rows = stats.discipline(aggregates)
    return formatters.discipline(rows, period), keyboards.discipline(period)


async def _render_player(deps: Deps, player_tag: str, period: Period, owner_id: int) -> Rendered:
    race, season_id = await _race(deps)
    aggregates = await player_aggregates(
        deps.conn, period, season_id, race.section_index, only_current=False
    )
    agg = next((a for a in aggregates if a.player_tag == player_tag), None)
    return formatters.player_stats(agg, period), keyboards.player_stats(period, owner_id)


async def _render_link_picker(deps: Deps, page: int) -> Rendered:
    """Only unclaimed nicknames are offered, so nobody can take another's."""
    roster = await queries.get_roster(deps.conn)
    links = await queries.get_links_by_tag(deps.conn)
    free = [c for c in roster if c.player_tag not in links]

    if not free:
        return "Все ники клана уже привязаны. Освободить свой — «Отвязаться».", keyboards.plain()

    page = max(0, min(page, keyboards.pages(len(free)) - 1))
    return "Выбери свой игровой ник:", keyboards.link_picker(free, page)


async def _render_roster(deps: Deps) -> Rendered:
    roster = await queries.get_roster(deps.conn)
    links = await queries.get_links_by_tag(deps.conn)
    linked = [(c.name, links[c.player_tag]) for c in roster if c.player_tag in links]
    unlinked = [c.name for c in roster if c.player_tag not in links]
    return formatters.roster(linked, unlinked), keyboards.plain()


# --- commands -----------------------------------------------------------------


@router.message(Command("start", "help"))
async def cmd_help(message: Message) -> None:
    await message.answer(formatters.HELP, parse_mode="HTML", reply_markup=keyboards.main_menu())


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer(formatters.MENU, parse_mode="HTML", reply_markup=keyboards.main_menu())


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
    edit = getattr(callback.message, "edit_text", None)
    if edit is not None:
        await edit(
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
        await message.answer(NOT_LINKED, parse_mode="HTML")
        return
    names = await queries.get_member_names(deps.conn)
    name = names.get(link.player_tag, link.player_tag)
    await message.answer(f"Ты — {escape(name)} ({escape(link.player_tag)})", parse_mode="HTML")


@router.message(Command("today"))
async def cmd_today(message: Message, deps: Deps) -> None:
    await _reply(message, await _render_today(deps))


@router.message(Command("war"))
async def cmd_war(message: Message, deps: Deps) -> None:
    await _reply(message, await _render_war(deps))


@router.message(Command("rating"))
async def cmd_rating(message: Message, command: CommandObject, deps: Deps) -> None:
    try:
        period, mode = _split_period(command.args, expect_mode=True)
    except PeriodParseError:
        await message.answer(PERIOD_HELP, parse_mode="HTML")
        return
    await _reply(message, await _render_rating(deps, period, mode))


@router.message(Command("discipline"))
async def cmd_discipline(message: Message, command: CommandObject, deps: Deps) -> None:
    try:
        period, _ = _split_period(command.args)
    except PeriodParseError:
        await message.answer(PERIOD_HELP, parse_mode="HTML")
        return
    await _reply(message, await _render_discipline(deps, period))


@router.message(Command("me"))
async def cmd_me(message: Message, command: CommandObject, deps: Deps) -> None:
    assert message.from_user is not None
    link = await queries.get_link_by_user(deps.conn, message.from_user.id)
    if link is None:
        await message.answer(NOT_LINKED, parse_mode="HTML")
        return
    try:
        period, _ = _split_period(command.args)
    except PeriodParseError:
        await message.answer(PERIOD_HELP, parse_mode="HTML")
        return
    await _reply(
        message, await _render_player(deps, link.player_tag, period, message.from_user.id)
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message, command: CommandObject, deps: Deps) -> None:
    assert message.from_user is not None
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

    try:
        period, _ = _split_period(" ".join(tokens[1:]))
    except PeriodParseError:
        await message.answer(PERIOD_HELP, parse_mode="HTML")
        return

    text, _ = await _render_player(deps, hits[0].player_tag, period, message.from_user.id)
    await message.answer(text, parse_mode="HTML")


@router.message(Command("roster"))
async def cmd_roster(message: Message, deps: Deps) -> None:
    await _reply(message, await _render_roster(deps))


async def _reply(message: Message, rendered: Rendered) -> None:
    text, markup = rendered
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


# --- inline menu --------------------------------------------------------------


@router.callback_query(lambda c: c.data and c.data.startswith(f"{keyboards.PREFIX}:"))
async def cb_menu(callback: CallbackQuery, deps: Deps) -> None:
    assert callback.data is not None
    parsed = keyboards.parse_callback(callback.data)
    if parsed is None:
        await callback.answer()
        return

    action, args = parsed

    if action == "linkto":
        await _link_from_menu(callback, deps, args[0])
        return
    if action == "unlink":
        await _unlink_from_menu(callback, deps)
        return
    if action == "pick":
        await _edit(callback, await _render_link_picker(deps, int(args[0]) if args else 0))
        return

    # Everything below is a statistics view keyed by a period.
    period = parse_period(args[0]) if args else parse_period(None)

    if action == "menu":
        rendered: Rendered = (formatters.MENU, keyboards.main_menu())
    elif action == "help":
        rendered = (formatters.HELP, keyboards.plain())
    elif action == "today":
        rendered = await _render_today(deps)
    elif action == "war":
        rendered = await _render_war(deps)
    elif action == "rating":
        rendered = await _render_rating(deps, period, args[1] if len(args) > 1 else "avg")
    elif action == "disc":
        rendered = await _render_discipline(deps, period)
    elif action == "roster":
        rendered = await _render_roster(deps)
    elif action == "me":
        await _answer_me(callback, deps, period, args)
        return
    else:
        await callback.answer()
        return

    await _edit(callback, rendered)


async def _link_from_menu(callback: CallbackQuery, deps: Deps, player_tag: str) -> None:
    roster = await queries.get_roster(deps.conn)
    candidate = next((c for c in roster if c.player_tag == player_tag), None)
    if candidate is None:
        await callback.answer("Игрока больше нет в клане", show_alert=True)
        return

    links = await queries.get_links_by_tag(deps.conn)
    taken = links.get(player_tag)
    if taken is not None and taken.tg_user_id != callback.from_user.id:
        # Someone claimed it between rendering the page and the tap.
        await callback.answer("Этот ник уже занят", show_alert=True)
        await _edit(callback, await _render_link_picker(deps, 0))
        return

    user = callback.from_user
    await queries.upsert_link(deps.conn, user.id, player_tag, user.username, user.full_name)
    await _edit(
        callback,
        (
            f"Привязано: {escape(candidate.name)} ({escape(player_tag)})",
            keyboards.plain(),
        ),
    )


async def _unlink_from_menu(callback: CallbackQuery, deps: Deps) -> None:
    removed = await queries.delete_link(deps.conn, callback.from_user.id)
    if not removed:
        await callback.answer("У тебя не было привязки", show_alert=True)
        return
    await _edit(callback, ("Привязка снята.", keyboards.plain()))


async def _answer_me(
    callback: CallbackQuery, deps: Deps, period: Period, args: list[str]
) -> None:
    """Personal stats: a fresh message per person, buttons usable only by them."""
    owner_id = int(args[1]) if len(args) > 1 else callback.from_user.id
    if len(args) > 1 and owner_id != callback.from_user.id:
        await callback.answer("Это чужая статистика, нажми «Моя статистика»", show_alert=True)
        return

    link = await queries.get_link_by_user(deps.conn, callback.from_user.id)
    if link is None:
        await callback.answer("Сначала привяжись: кнопка «Привязаться»", show_alert=True)
        return

    text, markup = await _render_player(deps, link.player_tag, period, callback.from_user.id)
    if len(args) > 1:
        await _edit(callback, (text, markup))
        return

    answer = getattr(callback.message, "answer", None)
    if answer is not None:
        await answer(text, parse_mode="HTML", reply_markup=markup)
    await callback.answer()


async def _edit(callback: CallbackQuery, rendered: Rendered) -> None:
    text, markup = rendered
    edit = getattr(callback.message, "edit_text", None)
    if edit is None:
        await callback.answer()
        return
    try:
        await edit(text, parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest as exc:
        # Pressing the already-selected button changes nothing; that is not an error.
        if "message is not modified" not in str(exc):
            raise
    await callback.answer()
