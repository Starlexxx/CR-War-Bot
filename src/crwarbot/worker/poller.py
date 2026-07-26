from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import aiosqlite
from aiogram import Bot

from crwarbot.api.client import SupercellClient
from crwarbot.api.models import CurrentRiverRace
from crwarbot.config import Settings
from crwarbot.db import queries
from crwarbot.domain.aggregate import compute_day_results
from crwarbot.domain.periods import resolve_reset_time
from crwarbot.worker.backfill import backfill_river_race_log
from crwarbot.worker.reminders import check_and_send

log = logging.getLogger(__name__)

BACKFILL_INTERVAL_SECONDS = 6 * 3600
LAST_PERIOD_KEY = "last_period_index"
OBSERVED_RESET_KEY = "observed_reset_utc"


@dataclass
class RaceState:
    race: CurrentRiverRace
    season_id: int


class Poller:
    """Single background loop: snapshot the race, roll up days, fire reminders.

    Reminders ride on the poll tick rather than a separate one-minute timer. The
    30-minute grace window in `due_reminders` is far wider than the poll
    interval, so nothing is missed and there is one less moving part.
    """

    def __init__(
        self,
        conn: aiosqlite.Connection,
        client: SupercellClient,
        bot: Bot,
        settings: Settings,
    ) -> None:
        self._conn = conn
        self._client = client
        self._bot = bot
        self._settings = settings
        self._last_roster = 0.0
        self._last_backfill = 0.0
        self._state: RaceState | None = None

    @property
    def state(self) -> RaceState | None:
        return self._state

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("poll tick failed")
            await asyncio.sleep(self._settings.poll_interval_seconds)

    async def tick(self) -> RaceState:
        now = time.monotonic()
        clan_tag = self._settings.cr_clan_tag

        if now - self._last_roster >= self._settings.roster_interval_seconds:
            clan = await self._client.get_clan(clan_tag)
            await queries.sync_roster(self._conn, clan)
            self._last_roster = now

        if now - self._last_backfill >= BACKFILL_INTERVAL_SECONDS:
            await backfill_river_race_log(self._conn, self._client, clan_tag)
            self._last_backfill = now

        race = await self._client.get_current_river_race(clan_tag)
        season_id = await queries.resolve_season_id(self._conn, race.section_index)
        ctx = queries.RaceContext(
            season_id=season_id,
            section_index=race.section_index,
            period_index=race.period_index,
            period_type=race.period_type,
        )

        changed = 0
        for p in race.clan.participants:
            if await queries.insert_snapshot_if_changed(
                self._conn, ctx, p.tag, p.fame, p.decks_used, p.decks_used_today, p.boat_attacks
            ):
                changed += 1
        await self._conn.commit()

        snapshots = await queries.load_snapshots(self._conn, season_id, race.section_index)
        await queries.upsert_day_results(self._conn, compute_day_results(snapshots))

        await self._observe_reset(race.period_index)

        log.info(
            "poll: season=%s section=%s period=%s (%s), %d snapshots written",
            season_id,
            race.section_index,
            race.period_index,
            race.period_type,
            changed,
        )

        observed = await queries.kv_get(self._conn, OBSERVED_RESET_KEY)
        reset = resolve_reset_time(
            race.war_end, observed, self._settings.war_day_reset_utc
        )

        await check_and_send(
            self._bot,
            self._conn,
            self._settings.telegram_chat_id,
            race,
            season_id,
            self._settings.reminder_grace_minutes,
            reset,
        )

        self._state = RaceState(race=race, season_id=season_id)
        return self._state

    async def _observe_reset(self, period_index: int) -> None:
        """Learn the real daily reset time by watching `periodIndex` advance.

        The API does not tell us when a war day ends, so the first rollover the
        bot witnesses pins the reset down to within one poll interval. That beats
        the configured guess from then on.
        """
        previous = await queries.kv_get(self._conn, LAST_PERIOD_KEY)
        await queries.kv_set(self._conn, LAST_PERIOD_KEY, str(period_index))

        if previous is None or int(previous) == period_index:
            return

        stamp = datetime.now(UTC).strftime("%H:%M")
        await queries.kv_set(self._conn, OBSERVED_RESET_KEY, stamp)
        log.info("observed war day rollover to period %s at %s UTC", period_index, stamp)
