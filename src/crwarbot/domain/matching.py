from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    player_tag: str
    name: str


def _fold(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def match_roster(query: str, roster: Iterable[Candidate]) -> list[Candidate]:
    """Resolve a user-typed nickname or player tag against the clan roster.

    Tries progressively looser rules and returns as soon as one of them hits, so
    an exact nickname is never drowned out by substring matches.
    """
    roster = list(roster)
    raw = query.strip()
    if not raw:
        return []

    if raw.startswith("#"):
        wanted = raw.upper()
        return [c for c in roster if c.player_tag.upper() == wanted]

    tag_hit = [c for c in roster if c.player_tag.upper() == "#" + raw.upper()]
    if tag_hit:
        return tag_hit

    folded = _fold(raw)
    if not folded:
        return []

    for rule in (
        lambda c: _fold(c.name) == folded,
        lambda c: _fold(c.name).startswith(folded),
        lambda c: folded in _fold(c.name),
    ):
        hits = [c for c in roster if rule(c)]
        if hits:
            return sorted(hits, key=lambda c: c.name.lower())

    return []
