from dataclasses import dataclass

from crwarbot.domain.periods import Period, parse_period
from crwarbot.domain.stats import PlayerAggregate, aggregate, discipline, rate


def agg(tag, name, fame, wars, war_days, decks_used):
    return PlayerAggregate(tag, name, fame, wars, war_days, decks_used)


@dataclass
class Row:
    season_id: int
    section_index: int
    player_tag: str
    fame: int
    decks_used: int
    war_days: int
    war_date: str


def test_avg_normalises_by_wars_played():
    rows = rate(
        [
            agg("#VET", "Veteran", 12000, 10, 40, 160),
            agg("#NEW", "Newcomer", 2000, 1, 4, 16),
        ],
        miss_penalty=50,
    )
    assert [r.player_tag for r in rows] == ["#NEW", "#VET"]
    assert rows[0].score == 2000
    assert rows[1].score == 1200


def test_missed_attacks_cost_medals():
    clean = agg("#A", "Clean", 2000, 1, 4, 16)
    slacker = agg("#B", "Slacker", 2000, 1, 4, 12)
    rows = rate([clean, slacker], miss_penalty=50)
    assert rows[0].player_tag == "#A"
    assert rows[1].score == 2000 - 50 * 4


def test_total_mode_ignores_penalty_and_war_count():
    rows = rate([agg("#A", "A", 5000, 5, 20, 0)], miss_penalty=50, mode="total")
    assert rows[0].score == 5000


def test_player_with_no_wars_scores_zero():
    rows = rate([agg("#A", "A", 0, 0, 0, 0)], miss_penalty=50)
    assert rows[0].score == 0.0


def test_discipline_is_attacks_over_opportunities():
    rows = discipline([agg("#A", "A", 0, 2, 8, 24), agg("#B", "B", 0, 1, 4, 16)])
    assert rows[0].player_tag == "#B"
    assert rows[0].ratio == 1.0
    assert rows[1].ratio == 0.75
    assert rows[1].missed_attacks == 8


def test_aggregate_filters_to_current_war():
    rows = [
        Row(2, 1, "#A", 1000, 12, 4, "2026-07-20"),
        Row(2, 0, "#A", 500, 8, 4, "2026-07-13"),
    ]
    result = aggregate(rows, {"#A": "A"}, Period("war"), season_id=2, section_index=1)
    assert len(result) == 1
    assert result[0].fame == 1000


def test_aggregate_sums_a_season():
    rows = [
        Row(2, 0, "#A", 500, 8, 4, "2026-07-13"),
        Row(2, 1, "#A", 1000, 12, 4, "2026-07-20"),
        Row(1, 3, "#A", 300, 4, 4, "2026-06-29"),
    ]
    result = aggregate(rows, {"#A": "A"}, Period("season"), season_id=2, section_index=1)
    assert result[0].fame == 1500
    assert result[0].wars == 2


def test_aggregate_range_filters_by_war_date():
    rows = [
        Row(2, 0, "#A", 500, 8, 4, "2026-07-13"),
        Row(2, 1, "#A", 1000, 12, 4, "2026-07-20"),
    ]
    period = parse_period("2026-07-15..2026-07-25")
    result = aggregate(rows, {"#A": "A"}, period, season_id=2, section_index=1)
    assert result[0].fame == 1000
