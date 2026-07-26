from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from crwarbot.domain.periods import DECKS_PER_DAY, Period


class WarRowLike(Protocol):
    season_id: int
    section_index: int
    player_tag: str
    fame: int
    decks_used: int
    war_days: int
    war_date: str


@dataclass(frozen=True)
class PlayerAggregate:
    """Everything the stats formulas need about one player over some period."""

    player_tag: str
    name: str
    fame: int
    wars: int
    war_days: int
    decks_used: int

    @property
    def possible_attacks(self) -> int:
        return self.war_days * DECKS_PER_DAY

    @property
    def missed_attacks(self) -> int:
        return max(0, self.possible_attacks - self.decks_used)


@dataclass(frozen=True)
class RatingRow:
    player_tag: str
    name: str
    score: float
    fame: int
    wars: int
    missed_attacks: int


@dataclass(frozen=True)
class DisciplineRow:
    player_tag: str
    name: str
    ratio: float
    decks_used: int
    possible_attacks: int
    missed_attacks: int


def in_period(row: WarRowLike, period: Period, season_id: int, section_index: int) -> bool:
    if period.kind == "all":
        return True
    if period.kind == "war":
        return row.season_id == season_id and row.section_index == section_index
    if period.kind == "season":
        return row.season_id == season_id
    if not row.war_date:
        return False
    return str(period.start) <= row.war_date <= str(period.end)


def aggregate(
    war_rows: Iterable[WarRowLike],
    names: Mapping[str, str],
    period: Period,
    season_id: int,
    section_index: int,
) -> list[PlayerAggregate]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])

    for row in war_rows:
        if not in_period(row, period, season_id, section_index):
            continue
        acc = totals[row.player_tag]
        acc[0] += row.fame
        acc[1] += 1
        acc[2] += row.war_days
        acc[3] += row.decks_used

    return [
        PlayerAggregate(
            player_tag=tag,
            name=names.get(tag, tag),
            fame=fame,
            wars=wars,
            war_days=war_days,
            decks_used=decks_used,
        )
        for tag, (fame, wars, war_days, decks_used) in totals.items()
    ]


def rate(
    aggregates: Iterable[PlayerAggregate],
    miss_penalty: int,
    mode: str = "avg",
) -> list[RatingRow]:
    """Rank players by medals earned.

    `avg` divides by the number of wars the player was actually present for, so
    a newcomer with one strong war is not buried under veterans' totals. Missed
    attacks cost `miss_penalty` medals each.
    """
    rows = []
    for agg in aggregates:
        if mode == "total":
            score = float(agg.fame)
        elif agg.wars:
            score = (agg.fame - miss_penalty * agg.missed_attacks) / agg.wars
        else:
            score = 0.0
        rows.append(
            RatingRow(
                player_tag=agg.player_tag,
                name=agg.name,
                score=score,
                fame=agg.fame,
                wars=agg.wars,
                missed_attacks=agg.missed_attacks,
            )
        )
    rows.sort(key=lambda r: (-r.score, r.name.lower()))
    return rows


def discipline(aggregates: Iterable[PlayerAggregate]) -> list[DisciplineRow]:
    rows = []
    for agg in aggregates:
        possible = agg.possible_attacks
        rows.append(
            DisciplineRow(
                player_tag=agg.player_tag,
                name=agg.name,
                ratio=agg.decks_used / possible if possible else 0.0,
                decks_used=agg.decks_used,
                possible_attacks=possible,
                missed_attacks=agg.missed_attacks,
            )
        )
    rows.sort(key=lambda r: (-r.ratio, -r.possible_attacks, r.name.lower()))
    return rows
