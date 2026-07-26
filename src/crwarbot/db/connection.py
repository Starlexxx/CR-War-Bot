from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)


async def connect(db_path: Path) -> aiosqlite.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.commit()
    return conn


async def apply_migrations(conn: aiosqlite.Connection, migrations_dir: Path) -> None:
    await conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
    await conn.commit()

    async with conn.execute("SELECT name FROM schema_migrations") as cur:
        applied = {row["name"] for row in await cur.fetchall()}

    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in applied:
            continue
        log.info("applying migration %s", path.name)
        await conn.executescript(path.read_text())
        await conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (path.name,))
        await conn.commit()
