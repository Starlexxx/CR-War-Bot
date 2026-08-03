import shutil

from crwarbot.db import queries
from crwarbot.db.connection import apply_migrations, connect
from tests.conftest import MIGRATIONS

MULTI_LINK = "003_multi_link.sql"


async def seed_members(conn):
    await queries.ensure_historical_members(conn, [("#P1", "Vasya"), ("#P2", "Kolya")])
    await conn.execute("UPDATE members SET in_clan = 1")
    await conn.commit()


async def test_existing_link_survives_the_multi_account_migration(tmp_path):
    staged = tmp_path / "migrations"
    staged.mkdir()
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name != MULTI_LINK:
            shutil.copy(path, staged)

    connection = await connect(tmp_path / "old.db")
    await apply_migrations(connection, staged)
    await connection.execute(
        "INSERT INTO links (tg_user_id, player_tag, tg_username, tg_full_name, linked_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (42, "#P1", "vasya", "Вася", "2026-08-01T00:00:00+00:00"),
    )
    await connection.commit()

    shutil.copy(MIGRATIONS / MULTI_LINK, staged)
    await apply_migrations(connection, staged)

    links = await queries.get_links_by_user(connection, 42)
    assert [(link.player_tag, link.tg_username) for link in links] == [("#P1", "vasya")]
    await connection.close()


async def test_one_person_may_hold_several_accounts(conn):
    await seed_members(conn)
    await queries.upsert_link(conn, 42, "#P1", "vasya", "Вася")
    await queries.upsert_link(conn, 42, "#P2", "vasya", "Вася")

    links = await queries.get_links_by_user(conn, 42)

    assert [link.player_tag for link in links] == ["#P2", "#P1"]


async def test_claiming_a_tag_moves_it_to_the_new_owner(conn):
    await seed_members(conn)
    await queries.upsert_link(conn, 99, "#P1", "old", "Old")

    await queries.upsert_link(conn, 42, "#P1", "vasya", "Вася")

    assert await queries.get_links_by_user(conn, 99) == []
    assert [link.player_tag for link in await queries.get_links_by_user(conn, 42)] == ["#P1"]


async def test_deleting_one_account_leaves_the_rest(conn):
    await seed_members(conn)
    await queries.upsert_link(conn, 42, "#P1", "vasya", "Вася")
    await queries.upsert_link(conn, 42, "#P2", "vasya", "Вася")

    assert await queries.delete_link(conn, 42, "#P1") is True

    assert [link.player_tag for link in await queries.get_links_by_user(conn, 42)] == ["#P2"]


async def test_deleting_an_account_you_do_not_own_changes_nothing(conn):
    await seed_members(conn)
    await queries.upsert_link(conn, 42, "#P1", "vasya", "Вася")

    assert await queries.delete_link(conn, 99, "#P1") is False

    assert await queries.get_links_by_user(conn, 42) != []


async def test_delete_all_links_reports_how_many_went(conn):
    await seed_members(conn)
    await queries.upsert_link(conn, 42, "#P1", "vasya", "Вася")
    await queries.upsert_link(conn, 42, "#P2", "vasya", "Вася")

    assert await queries.delete_all_links(conn, 42) == 2
    assert await queries.get_links_by_user(conn, 42) == []
