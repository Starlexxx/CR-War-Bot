from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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
