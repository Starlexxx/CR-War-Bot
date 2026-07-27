from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

from crwarbot.bot.mentions import mention_with_game_name
from crwarbot.db.queries import Link
from crwarbot.domain.periods import DECKS_PER_DAY, Period
from crwarbot.domain.stats import DisciplineRow, PlayerAggregate, RatingRow

MEDAL = "🏅"
PLACES = {1: "🥇", 2: "🥈", 3: "🥉"}


@dataclass(frozen=True)
class Debtor:
    player_tag: str
    name: str
    decks_used_today: int
    link: Link | None


def reminder(kind: str, debtors: Sequence[Debtor]) -> str:
    hours = {"t16": 16, "t4": 4}[kind]
    head = f"⚔️ До конца дня войны — {hours} ч"

    if not debtors:
        return f"{head}\n\nВсе отыграли. Ни одной пропущенной атаки."

    lines = [head, "", f"Не отыграли ({len(debtors)}):"]
    linked = [d for d in debtors if d.link is not None]
    unlinked = [d for d in debtors if d.link is None]

    for d in linked + unlinked:
        used = d.decks_used_today
        lines.append(f"{mention_with_game_name(d.name, d.link)} ({used}/{DECKS_PER_DAY})")

    if unlinked:
        lines += ["", "Не привязаны к телеграму. Привязаться: /link &lt;ник&gt;"]

    return "\n".join(lines)


def today(
    debtors: Sequence[Debtor],
    total_participants: int,
    period_type: str,
    finished: bool = False,
) -> str:
    if period_type not in ("warDay", "colosseum"):
        return "Сейчас день тренировки — атаки войны не считаются."

    if finished:
        # Everyone shows 0/4 once the boat is home, which would read as a
        # clan-wide no-show if reported as debt.
        return "🏁 Клан уже финишировал гонку. Атак на сегодня больше нет."

    done = total_participants - len(debtors)
    if not debtors:
        return f"✅ Все отыграли ({done}/{total_participants})."

    lines = [f"Отыграли {done} из {total_participants}.", "", "Остались:"]
    for d in sorted(debtors, key=lambda x: (x.decks_used_today, x.name.lower())):
        lines.append(f"• {escape(d.name)} — {d.decks_used_today}/{DECKS_PER_DAY}")
    return "\n".join(lines)


def war_overview(rows: Sequence[tuple[str, int, int]], clan_fame: int) -> str:
    """rows: (name, fame, decks_used) sorted by caller."""
    lines = [f"⚔️ Текущая война — {MEDAL} {clan_fame} у клана", ""]
    for i, (name, fame, decks) in enumerate(rows, start=1):
        lines.append(f"{i}. {escape(name)} — {MEDAL} {fame} ({decks} атак)")
    return "\n".join(lines)


def rating(rows: Sequence[RatingRow], period: Period, mode: str) -> str:
    if not rows:
        return f"Нет данных за период: {period.label()}."

    title = "медали за войну" if mode == "avg" else "медали всего"
    lines = [f"🏆 Рейтинг — {title} ({period.label()})", ""]
    for i, r in enumerate(rows, start=1):
        place = PLACES.get(i, f"{i}.")
        if mode == "avg":
            detail = f"{r.score:.0f} за войну · {MEDAL} {r.fame} · войн {r.wars}"
            if r.missed_attacks:
                detail += f" · пропусков {r.missed_attacks}"
            if r.observed_days:
                detail += f" · дней в зачёте {r.observed_days}"
        else:
            detail = f"{MEDAL} {r.fame} · войн {r.wars}"
        lines.append(f"{place} {escape(r.name)} — {detail}")
    return "\n".join(lines)


def discipline(rows: Sequence[DisciplineRow], period: Period) -> str:
    # Attendance needs war days the bot actually watched; the race log backfill
    # cannot supply them, so early on there is nothing to rank.
    rows = [r for r in rows if r.possible_attacks]
    if not rows:
        return (
            f"Нет данных по атакам за период: {period.label()}.\n\n"
            "Посещаемость считается только по боевым дням, которые бот наблюдал сам. "
            "История из API даёт медали, но не атаки."
        )

    lines = [f"📋 Дисциплина ({period.label()})", ""]
    for i, r in enumerate(rows, start=1):
        place = PLACES.get(i, f"{i}.")
        lines.append(
            f"{place} {escape(r.name)} — {r.ratio * 100:.0f}% "
            f"({r.decks_used}/{r.possible_attacks}, пропущено {r.missed_attacks})"
        )
    return "\n".join(lines)


def player_stats(agg: PlayerAggregate | None, period: Period) -> str:
    if agg is None or agg.wars == 0:
        return f"Нет данных за период: {period.label()}."

    avg = agg.fame / agg.wars
    lines = [
        f"📊 {escape(agg.name)} ({period.label()})",
        "",
        f"{MEDAL} медалей: {agg.fame}",
        f"Войн: {agg.wars} · в среднем {avg:.0f} за войну",
    ]

    if agg.possible_attacks:
        ratio = agg.decks_used / agg.possible_attacks
        lines.append(f"Атак: {agg.decks_used}/{agg.possible_attacks} ({ratio * 100:.0f}%)")
        lines.append(f"Пропущено атак: {agg.missed_attacks}")
    else:
        lines.append("Атаки: нет данных — бот не наблюдал ни одного боевого дня")

    return "\n".join(lines)


def roster(linked: Sequence[tuple[str, Link]], unlinked: Sequence[str]) -> str:
    lines = [f"👥 Привязано {len(linked)} из {len(linked) + len(unlinked)}"]
    if linked:
        lines += ["", "Привязаны:"]
        for name, link in sorted(linked, key=lambda x: x[0].lower()):
            handle = f"@{escape(link.tg_username)}" if link.tg_username else "без username"
            lines.append(f"• {escape(name)} — {handle}")
    if unlinked:
        lines += ["", "Не привязаны:"]
        lines += [f"• {escape(n)}" for n in sorted(unlinked, key=str.lower)]
    return "\n".join(lines)


MENU = """<b>CRWarBot</b>

Выбери, что показать. Команды тоже работают — список по кнопке «/» рядом с полем ввода."""

HELP = """<b>CRWarBot</b>

Привязка:
/link &lt;ник или тег&gt; — связать телеграм с игровым аккаунтом
/unlink — снять привязку
/whoami — показать текущую привязку

Война:
/today — кто ещё не отыграл сегодня
/war — медали и атаки в текущей войне

Меню:
/menu — кнопки вместо команд

Статистика:
/me [период] — своя статистика
/stats &lt;ник&gt; [период] — статистика игрока
/rating [период] [avg|total] — рейтинг клана
/discipline [период] — процент отыгранных атак
/roster — кто привязан к телеграму

Период: <code>war</code> (по умолчанию), <code>season</code>, <code>all</code> \
или <code>2026-01-01..2026-03-01</code>"""
