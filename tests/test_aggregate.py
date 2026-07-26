from crwarbot.domain.aggregate import Snapshot, compute_day_results


def snap(period, ts, fame, today, tag="#A", period_type="warDay"):
    return Snapshot(
        ts=ts,
        season_id=1,
        section_index=0,
        period_index=period,
        period_type=period_type,
        player_tag=tag,
        fame=fame,
        decks_used=0,
        decks_used_today=today,
    )


def test_last_snapshot_of_the_day_wins():
    results = compute_day_results(
        [
            snap(3, "2026-07-24T12:00:00+00:00", 200, 1),
            snap(3, "2026-07-24T20:00:00+00:00", 800, 4),
        ]
    )
    assert len(results) == 1
    assert results[0].fame_end == 800
    assert results[0].decks_used_today == 4
    assert results[0].day_date == "2026-07-24"


def test_fame_delta_is_measured_against_previous_day():
    results = compute_day_results(
        [
            snap(3, "2026-07-24T20:00:00+00:00", 800, 4),
            snap(4, "2026-07-25T20:00:00+00:00", 1500, 4),
        ]
    )
    assert [r.fame_delta for r in results] == [800, 700]


def test_downtime_gap_keeps_medals_instead_of_dropping_them():
    # Day 4 never got polled; its medals land in day 5 rather than vanishing.
    results = compute_day_results(
        [
            snap(3, "2026-07-24T20:00:00+00:00", 800, 4),
            snap(5, "2026-07-26T20:00:00+00:00", 2400, 4),
        ]
    )
    assert [(r.period_index, r.fame_delta) for r in results] == [(3, 800), (5, 1600)]


def test_day_with_zero_attacks_is_still_recorded():
    results = compute_day_results([snap(3, "2026-07-24T10:30:00+00:00", 0, 0)])
    assert len(results) == 1
    assert results[0].decks_used_today == 0
    assert results[0].fame_delta == 0


def test_players_are_tracked_independently():
    results = compute_day_results(
        [
            snap(3, "2026-07-24T20:00:00+00:00", 800, 4, tag="#A"),
            snap(3, "2026-07-24T20:00:00+00:00", 400, 2, tag="#B"),
        ]
    )
    assert {(r.player_tag, r.fame_end) for r in results} == {("#A", 800), ("#B", 400)}
