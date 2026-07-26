CREATE TABLE IF NOT EXISTS members (
    player_tag TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    role       TEXT,
    in_clan    INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS links (
    tg_user_id   INTEGER PRIMARY KEY,
    player_tag   TEXT NOT NULL UNIQUE,
    tg_username  TEXT,
    tg_full_name TEXT,
    linked_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS player_snapshots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               TEXT NOT NULL,
    season_id        INTEGER NOT NULL,
    section_index    INTEGER NOT NULL,
    period_index     INTEGER NOT NULL,
    period_type      TEXT NOT NULL,
    player_tag       TEXT NOT NULL,
    fame             INTEGER NOT NULL,
    decks_used       INTEGER NOT NULL,
    decks_used_today INTEGER NOT NULL,
    boat_attacks     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_snapshots_period
    ON player_snapshots (season_id, section_index, period_index, player_tag, ts);

CREATE INDEX IF NOT EXISTS ix_snapshots_player
    ON player_snapshots (player_tag, ts);

CREATE TABLE IF NOT EXISTS day_results (
    season_id        INTEGER NOT NULL,
    section_index    INTEGER NOT NULL,
    period_index     INTEGER NOT NULL,
    period_type      TEXT NOT NULL,
    player_tag       TEXT NOT NULL,
    decks_used_today INTEGER NOT NULL,
    fame_end         INTEGER NOT NULL,
    fame_delta       INTEGER NOT NULL,
    day_date         TEXT NOT NULL,
    PRIMARY KEY (season_id, section_index, period_index, player_tag)
);

CREATE INDEX IF NOT EXISTS ix_day_results_player
    ON day_results (player_tag, day_date);

CREATE TABLE IF NOT EXISTS wars (
    season_id     INTEGER NOT NULL,
    section_index INTEGER NOT NULL,
    created_date  TEXT NOT NULL,
    clan_rank     INTEGER,
    clan_fame     INTEGER,
    PRIMARY KEY (season_id, section_index)
);

CREATE TABLE IF NOT EXISTS war_results (
    season_id     INTEGER NOT NULL,
    section_index INTEGER NOT NULL,
    player_tag    TEXT NOT NULL,
    fame          INTEGER NOT NULL,
    decks_used    INTEGER NOT NULL,
    boat_attacks  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (season_id, section_index, player_tag)
);

CREATE INDEX IF NOT EXISTS ix_war_results_player
    ON war_results (player_tag);

CREATE TABLE IF NOT EXISTS reminders_sent (
    season_id     INTEGER NOT NULL,
    section_index INTEGER NOT NULL,
    period_index  INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    sent_at       TEXT NOT NULL,
    PRIMARY KEY (season_id, section_index, period_index, kind)
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
