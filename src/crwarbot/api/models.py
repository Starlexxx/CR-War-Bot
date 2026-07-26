from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

SUPERCELL_TS = "%Y%m%dT%H%M%S.%fZ"


def parse_supercell_ts(value: str) -> datetime:
    """Supercell serialises timestamps as `20260726T101500.000Z`."""
    return datetime.strptime(value, SUPERCELL_TS).replace(tzinfo=UTC)


class ClanMember(BaseModel):
    tag: str
    name: str
    role: str | None = None


class Clan(BaseModel):
    tag: str
    name: str
    member_list: list[ClanMember] = Field(default_factory=list, alias="memberList")


class RiverRaceParticipant(BaseModel):
    tag: str
    name: str = ""
    fame: int = 0
    repair_points: int = Field(0, alias="repairPoints")
    boat_attacks: int = Field(0, alias="boatAttacks")
    decks_used: int = Field(0, alias="decksUsed")
    decks_used_today: int = Field(0, alias="decksUsedToday")


class RiverRaceClan(BaseModel):
    tag: str
    name: str = ""
    fame: int = 0
    # Set once the clan crosses the finish line; absent while the race is live.
    finish_time: str | None = Field(None, alias="finishTime")
    participants: list[RiverRaceParticipant] = Field(default_factory=list)


class CurrentRiverRace(BaseModel):
    state: str = ""
    clan: RiverRaceClan
    section_index: int = Field(0, alias="sectionIndex")
    period_index: int = Field(0, alias="periodIndex")
    period_type: str = Field("training", alias="periodType")
    war_end_time: str | None = Field(None, alias="warEndTime")
    collection_end_time: str | None = Field(None, alias="collectionEndTime")

    @property
    def war_end(self) -> datetime | None:
        return parse_supercell_ts(self.war_end_time) if self.war_end_time else None


class RiverRaceLogStandingClan(BaseModel):
    tag: str
    name: str = ""
    fame: int = 0
    participants: list[RiverRaceParticipant] = Field(default_factory=list)


class RiverRaceLogStanding(BaseModel):
    rank: int = 0
    clan: RiverRaceLogStandingClan


class RiverRaceLogEntry(BaseModel):
    season_id: int = Field(..., alias="seasonId")
    section_index: int = Field(0, alias="sectionIndex")
    created_date: str = Field(..., alias="createdDate")
    standings: list[RiverRaceLogStanding] = Field(default_factory=list)

    @property
    def created(self) -> datetime:
        return parse_supercell_ts(self.created_date)


class RiverRaceLog(BaseModel):
    items: list[RiverRaceLogEntry] = Field(default_factory=list)
