from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Snapshot:
    ts: str
    season_id: int
    section_index: int
    period_index: int
    period_type: str
    player_tag: str
    fame: int
    decks_used: int
    decks_used_today: int
    clan_finished: int = 0


@dataclass(frozen=True)
class DayResult:
    season_id: int
    section_index: int
    period_index: int
    period_type: str
    player_tag: str
    decks_used_today: int
    fame_end: int
    fame_delta: int
    day_date: str
    clan_finished: int


def compute_day_results(snapshots: Iterable[Snapshot]) -> list[DayResult]:
    """Collapse raw snapshots into one row per player per war day.

    The last snapshot of a period is that day's final state. `fame_delta` is
    measured against the previous period that actually has data, so a gap left
    by downtime shifts medals into the surviving day rather than losing them.
    """
    by_player: dict[tuple[int, int, str], dict[int, Snapshot]] = defaultdict(dict)

    for snap in snapshots:
        key = (snap.season_id, snap.section_index, snap.player_tag)
        latest = by_player[key].get(snap.period_index)
        if latest is None or snap.ts >= latest.ts:
            by_player[key][snap.period_index] = snap

    results: list[DayResult] = []
    for periods in by_player.values():
        previous_fame = 0
        for period_index in sorted(periods):
            snap = periods[period_index]
            results.append(
                DayResult(
                    season_id=snap.season_id,
                    section_index=snap.section_index,
                    period_index=period_index,
                    period_type=snap.period_type,
                    player_tag=snap.player_tag,
                    decks_used_today=snap.decks_used_today,
                    fame_end=snap.fame,
                    fame_delta=snap.fame - previous_fame,
                    day_date=snap.ts[:10],
                    clan_finished=snap.clan_finished,
                )
            )
            previous_fame = snap.fame

    results.sort(key=lambda r: (r.season_id, r.section_index, r.period_index, r.player_tag))
    return results
