import pytest

from crwarbot.domain.matching import Candidate, match_roster

ROSTER = [
    Candidate("#AAA", "Vasya"),
    Candidate("#BBB", "vasya the great"),
    Candidate("#CCC", "Коля"),
    Candidate("#DDD", "xX_Pro_Xx"),
]


def test_exact_name_wins_over_substring():
    assert match_roster("Vasya", ROSTER) == [Candidate("#AAA", "Vasya")]


def test_case_and_punctuation_are_ignored():
    assert match_roster("xxproxx", ROSTER) == [Candidate("#DDD", "xX_Pro_Xx")]


def test_prefix_can_be_ambiguous():
    hits = match_roster("vas", ROSTER)
    assert {c.player_tag for c in hits} == {"#AAA", "#BBB"}


def test_tag_lookup_with_and_without_hash():
    assert match_roster("#ccc", ROSTER) == [Candidate("#CCC", "Коля")]
    assert match_roster("ccc", ROSTER) == [Candidate("#CCC", "Коля")]


def test_cyrillic_names_match():
    assert match_roster("коля", ROSTER) == [Candidate("#CCC", "Коля")]


@pytest.mark.parametrize("query", ["", "   ", "nobody"])
def test_no_match_returns_empty(query):
    assert match_roster(query, ROSTER) == []
