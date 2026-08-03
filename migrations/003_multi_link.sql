-- One person may hold several game accounts, so the tag owns the row now.
CREATE TABLE links_new (
    player_tag   TEXT PRIMARY KEY,
    tg_user_id   INTEGER NOT NULL,
    tg_username  TEXT,
    tg_full_name TEXT,
    linked_at    TEXT NOT NULL
);

INSERT INTO links_new (player_tag, tg_user_id, tg_username, tg_full_name, linked_at)
    SELECT player_tag, tg_user_id, tg_username, tg_full_name, linked_at FROM links;

DROP TABLE links;

ALTER TABLE links_new RENAME TO links;

CREATE INDEX ix_links_tg_user ON links (tg_user_id);
