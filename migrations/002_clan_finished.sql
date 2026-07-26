-- A war day during which the clan had already crossed the finish line offers no
-- attacks, so it must not count against anyone's attendance.
ALTER TABLE player_snapshots ADD COLUMN clan_finished INTEGER NOT NULL DEFAULT 0;
ALTER TABLE day_results ADD COLUMN clan_finished INTEGER NOT NULL DEFAULT 0;
