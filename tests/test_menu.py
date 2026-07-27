from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest

from crwarbot.api.models import CurrentRiverRace
from crwarbot.bot import handlers, keyboards
from crwarbot.db import queries
from crwarbot.worker.poller import RaceState
from tests.conftest import participant, race_payload

USER = SimpleNamespace(id=42, username="vasya", full_name="Вася П")
OTHER = SimpleNamespace(id=99, username="kolya", full_name="Коля")


class FakeMessage:
    def __init__(self, raise_not_modified=False):
        self.text = "old"
        self.markup = None
        self.answers = []
        self.raise_not_modified = raise_not_modified

    async def edit_text(self, text, parse_mode=None, reply_markup=None):
        if self.raise_not_modified:
            raise TelegramBadRequest(
                method=SimpleNamespace(), message="Bad Request: message is not modified"
            )
        self.text = text
        self.markup = reply_markup

    async def answer(self, text, parse_mode=None, reply_markup=None):
        self.answers.append((text, reply_markup))


class FakeCallback:
    def __init__(self, data, user=USER, message=None):
        self.data = data
        self.from_user = user
        self.message = message or FakeMessage()
        self.alerts = []

    async def answer(self, text=None, show_alert=False):
        self.alerts.append(text)


@pytest.fixture
def deps(conn, settings):
    race = CurrentRiverRace.model_validate(
        race_payload(
            [
                participant("#P1", "Vasya", 900, 4, 4),
                participant("#P2", "Kolya", 300, 2, 2),
            ]
        )
    )
    poller = SimpleNamespace(state=RaceState(race=race, season_id=58))
    return handlers.Deps(conn=conn, client=None, settings=settings, poller=poller)


async def seed(conn):
    await queries.ensure_historical_members(conn, [("#P1", "Vasya"), ("#P2", "Kolya")])
    await conn.execute("UPDATE members SET in_clan = 1")
    await conn.commit()


async def seed_wars(conn):
    """Finished races so the stats renderers have something to show."""
    for section in (0, 1):
        await queries.upsert_war(conn, 58, section, "20260713T101500.000Z", 1, 5000)
        await queries.upsert_war_results(conn, [(58, section, "#P1", 2400, 16, 0)])


def buttons(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def test_callback_data_round_trips():
    assert keyboards.parse_callback("m:rating:season:total") == ("rating", ["season", "total"])
    assert keyboards.parse_callback("link:42:#ABC") is None


def test_menu_buttons_all_carry_our_prefix():
    for row in keyboards.main_menu().inline_keyboard:
        for button in row:
            assert keyboards.parse_callback(button.callback_data) is not None


async def test_today_button_renders_the_same_as_the_command(conn, deps):
    await seed(conn)
    callback = FakeCallback("m:today")

    await handlers.cb_menu(callback, deps)

    expected, _ = await handlers._render_today(deps)
    assert callback.message.text == expected


async def test_rating_button_marks_the_active_period(conn, deps):
    await seed(conn)
    callback = FakeCallback("m:rating:season:avg")

    await handlers.cb_menu(callback, deps)

    labels = buttons(callback.message.markup)
    assert "· Сезон ·" in labels
    assert "Война" in labels


async def test_switching_mode_keeps_the_period(conn, deps):
    await seed(conn)
    callback = FakeCallback("m:rating:all:total")

    await handlers.cb_menu(callback, deps)

    labels = buttons(callback.message.markup)
    assert "· Всё время ·" in labels
    assert "· Всего ·" in labels


async def test_back_button_returns_to_the_menu(conn, deps):
    callback = FakeCallback("m:menu")

    await handlers.cb_menu(callback, deps)

    assert "Выбери" in callback.message.text
    assert "Кто не отыграл" in buttons(callback.message.markup)


async def test_my_stats_arrives_as_a_new_message(conn, deps):
    # Editing in place would overwrite one member's stats with another's.
    await seed(conn)
    await seed_wars(conn)
    await queries.upsert_link(conn, USER.id, "#P1", "vasya", "Вася")
    callback = FakeCallback("m:me:war")

    await handlers.cb_menu(callback, deps)

    assert callback.message.answers
    assert "Vasya" in callback.message.answers[0][0]
    assert callback.message.text == "old"


async def test_unlinked_user_is_told_to_link(conn, deps):
    await seed(conn)
    callback = FakeCallback("m:me:war")

    await handlers.cb_menu(callback, deps)

    assert "привяжись" in callback.alerts[0]


async def test_period_buttons_belong_to_their_owner(conn, deps):
    await seed(conn)
    await queries.upsert_link(conn, USER.id, "#P1", "vasya", "Вася")
    await queries.upsert_link(conn, OTHER.id, "#P2", "kolya", "Коля")
    callback = FakeCallback(f"m:me:season:{USER.id}", user=OTHER)

    await handlers.cb_menu(callback, deps)

    assert "чужая статистика" in callback.alerts[0]
    assert callback.message.text == "old"


async def test_owner_switching_period_edits_in_place(conn, deps):
    await seed(conn)
    await seed_wars(conn)
    await queries.upsert_link(conn, USER.id, "#P1", "vasya", "Вася")
    callback = FakeCallback(f"m:me:season:{USER.id}", user=USER)

    await handlers.cb_menu(callback, deps)

    assert "Vasya" in callback.message.text
    assert callback.message.answers == []


async def test_menu_offers_a_way_to_link_and_unlink(conn):
    labels = buttons(keyboards.main_menu())
    assert "Привязаться" in labels
    assert "Отвязаться" in labels


async def test_picker_lists_only_unclaimed_nicks(conn, deps):
    await seed(conn)
    await queries.upsert_link(conn, USER.id, "#P1", "vasya", "Вася")
    callback = FakeCallback("m:pick:0")

    await handlers.cb_menu(callback, deps)

    labels = buttons(callback.message.markup)
    assert "Kolya" in labels
    assert "Vasya" not in labels


async def test_picking_a_nick_links_whoever_pressed(conn, deps):
    await seed(conn)
    callback = FakeCallback("m:linkto:#P2", user=OTHER)

    await handlers.cb_menu(callback, deps)

    link = await queries.get_link_by_user(conn, OTHER.id)
    assert link.player_tag == "#P2"
    assert "Привязано: Kolya" in callback.message.text


async def test_nick_claimed_meanwhile_is_refused(conn, deps):
    # The page was rendered before someone else took the nick.
    await seed(conn)
    await queries.upsert_link(conn, USER.id, "#P1", "vasya", "Вася")
    callback = FakeCallback("m:linkto:#P1", user=OTHER)

    await handlers.cb_menu(callback, deps)

    assert "уже занят" in callback.alerts[0]
    assert await queries.get_link_by_user(conn, OTHER.id) is None


async def test_relinking_your_own_nick_is_allowed(conn, deps):
    await seed(conn)
    await queries.upsert_link(conn, USER.id, "#P1", "vasya", "Вася")
    callback = FakeCallback("m:linkto:#P1", user=USER)

    await handlers.cb_menu(callback, deps)

    assert "Привязано" in callback.message.text


async def test_unlink_button_clears_the_link(conn, deps):
    await seed(conn)
    await queries.upsert_link(conn, USER.id, "#P1", "vasya", "Вася")
    callback = FakeCallback("m:unlink")

    await handlers.cb_menu(callback, deps)

    assert await queries.get_link_by_user(conn, USER.id) is None
    assert "снята" in callback.message.text


async def test_unlink_without_a_link_says_so(conn, deps):
    await seed(conn)
    callback = FakeCallback("m:unlink")

    await handlers.cb_menu(callback, deps)

    assert "не было привязки" in callback.alerts[0]


async def test_long_roster_is_paged(conn, deps):
    await queries.ensure_historical_members(
        conn, [(f"#T{i}", f"Player{i:02d}") for i in range(40)]
    )
    await conn.execute("UPDATE members SET in_clan = 1")
    await conn.commit()
    callback = FakeCallback("m:pick:0")

    await handlers.cb_menu(callback, deps)

    labels = buttons(callback.message.markup)
    assert "1/3" in labels
    assert sum(1 for label in labels if label.startswith("Player")) == 16


async def test_page_beyond_the_end_is_clamped(conn, deps):
    await seed(conn)
    callback = FakeCallback("m:pick:99")

    await handlers.cb_menu(callback, deps)

    assert "Выбери свой игровой ник" in callback.message.text


async def test_picker_when_everyone_is_linked(conn, deps):
    await seed(conn)
    await queries.upsert_link(conn, USER.id, "#P1", "vasya", "Вася")
    await queries.upsert_link(conn, OTHER.id, "#P2", "kolya", "Коля")
    callback = FakeCallback("m:pick:0")

    await handlers.cb_menu(callback, deps)

    assert "уже привязаны" in callback.message.text


async def test_pressing_the_active_button_is_not_an_error(conn, deps):
    await seed(conn)
    callback = FakeCallback("m:war", message=FakeMessage(raise_not_modified=True))

    await handlers.cb_menu(callback, deps)

    assert callback.alerts == [None]


async def test_unknown_action_is_ignored(conn, deps):
    callback = FakeCallback("m:bogus")

    await handlers.cb_menu(callback, deps)

    assert callback.message.text == "old"
