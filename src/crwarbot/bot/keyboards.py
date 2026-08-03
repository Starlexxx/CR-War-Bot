from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from crwarbot.domain.matching import Candidate
from crwarbot.domain.periods import Period

PREFIX = "m"

PERIODS = (("war", "Война"), ("season", "Сезон"), ("all", "Всё время"))
MODES = (("avg", "За войну"), ("total", "Всего"))

CURRENT = "· {} ·"


def _cb(action: str, *parts: str | int) -> str:
    return ":".join([PREFIX, action, *(str(p) for p in parts)])


def parse_callback(data: str) -> tuple[str, list[str]] | None:
    """Split `m:action:arg:arg` into its parts, or None if it is not ours."""
    chunks = data.split(":")
    if len(chunks) < 2 or chunks[0] != PREFIX:
        return None
    return chunks[1], chunks[2:]


def _mark(label: str, active: bool) -> str:
    return CURRENT.format(label) if active else label


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Кто не отыграл", callback_data=_cb("today")),
                InlineKeyboardButton(text="Текущая война", callback_data=_cb("war")),
            ],
            [
                InlineKeyboardButton(text="Рейтинг", callback_data=_cb("rating", "war", "avg")),
                InlineKeyboardButton(text="Дисциплина", callback_data=_cb("disc", "war")),
            ],
            [
                InlineKeyboardButton(text="Моя статистика", callback_data=_cb("me", "war")),
                InlineKeyboardButton(text="Привязки", callback_data=_cb("roster")),
            ],
            [
                InlineKeyboardButton(text="Привязаться", callback_data=_cb("pick", 0)),
                InlineKeyboardButton(text="Отвязаться", callback_data=_cb("unlink")),
            ],
            [InlineKeyboardButton(text="Помощь", callback_data=_cb("help"))],
        ]
    )


def _back_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="‹ Меню", callback_data=_cb("menu"))]


def _period_row(action: str, period: Period, *tail: str | int) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            text=_mark(label, period.kind == kind),
            callback_data=_cb(action, kind, *tail),
        )
        for kind, label in PERIODS
    ]


def rating(period: Period, mode: str) -> InlineKeyboardMarkup:
    modes = [
        InlineKeyboardButton(
            text=_mark(label, mode == value),
            callback_data=_cb("rating", period.kind, value),
        )
        for value, label in MODES
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[_period_row("rating", period, mode), modes, _back_row()]
    )


def discipline(period: Period) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[_period_row("disc", period), _back_row()])


def player_stats(period: Period, owner_id: int) -> InlineKeyboardMarkup:
    # The owner id keeps one member's period buttons from rewriting another's
    # stats in a shared chat.
    return InlineKeyboardMarkup(
        inline_keyboard=[_period_row("me", period, owner_id), _back_row()]
    )


def plain() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[_back_row()])


def unlink_picker(accounts: Sequence[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Own accounts as (name, tag), two per row. Nobody has enough to need paging."""
    rows = [
        [
            InlineKeyboardButton(text=name, callback_data=_cb("unlinkone", tag))
            for name, tag in accounts[i : i + 2]
        ]
        for i in range(0, len(accounts), 2)
    ]
    rows.append([InlineKeyboardButton(text="Отвязать все", callback_data=_cb("unlinkall"))])
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


PICK_PAGE_SIZE = 16


def pages(total: int) -> int:
    return max(1, -(-total // PICK_PAGE_SIZE))


def link_picker(candidates: Sequence[Candidate], page: int) -> InlineKeyboardMarkup:
    """Nicknames to claim, two per row, paged so a 50-man clan still fits."""
    start = page * PICK_PAGE_SIZE
    chunk = candidates[start : start + PICK_PAGE_SIZE]

    rows = [
        [
            InlineKeyboardButton(text=c.name, callback_data=_cb("linkto", c.player_tag))
            for c in chunk[i : i + 2]
        ]
        for i in range(0, len(chunk), 2)
    ]

    total = pages(len(candidates))
    if total > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="‹", callback_data=_cb("pick", page - 1)))
        nav.append(
            InlineKeyboardButton(text=f"{page + 1}/{total}", callback_data=_cb("pick", page))
        )
        if page + 1 < total:
            nav.append(InlineKeyboardButton(text="›", callback_data=_cb("pick", page + 1)))
        rows.append(nav)

    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)
