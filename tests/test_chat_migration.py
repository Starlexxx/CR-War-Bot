from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramMigrateToChat

from crwarbot.bot.access import DENIED_TEXT, AccessMiddleware
from crwarbot.bot.chat import ChatTarget

OLD_CHAT = -900100200
NEW_CHAT = -1009876543210


def migrate_error():
    # Telegram reports the replacement id inside the error, and the new id is
    # unrelated to the old one, so it cannot be derived.
    return TelegramMigrateToChat(
        method=SimpleNamespace(),
        message="group chat was upgraded to a supergroup chat",
        migrate_to_chat_id=NEW_CHAT,
    )


async def test_call_follows_the_migration_and_retries(conn):
    target = ChatTarget(conn, OLD_CHAT)
    seen = []

    async def action(chat_id):
        seen.append(chat_id)
        if chat_id == OLD_CHAT:
            raise migrate_error()
        return "ok"

    assert await target.call(action) == "ok"
    assert seen == [OLD_CHAT, NEW_CHAT]
    assert await target.get() == NEW_CHAT


async def test_migration_survives_a_restart(conn):
    await ChatTarget(conn, OLD_CHAT).migrate_to(NEW_CHAT)
    assert await ChatTarget(conn, OLD_CHAT).get() == NEW_CHAT


async def test_service_message_records_the_migration(conn):
    target = ChatTarget(conn, OLD_CHAT)
    message = SimpleNamespace(migrate_to_chat_id=NEW_CHAT)

    assert await target.note_service_message(message) is True
    assert await target.get() == NEW_CHAT


async def test_ordinary_message_is_not_mistaken_for_a_migration(conn):
    target = ChatTarget(conn, OLD_CHAT)

    assert await target.note_service_message(SimpleNamespace(text="/help")) is False
    assert await target.get() == OLD_CHAT


class MigratingBot:
    def __init__(self):
        self.calls = []

    async def get_chat_member(self, chat_id, user_id):
        self.calls.append(chat_id)
        if chat_id == OLD_CHAT:
            raise migrate_error()
        return SimpleNamespace(status="member")


class FakeMessage:
    def __init__(self, user_id, chat_id, chat_type):
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(id=chat_id, type=chat_type)
        self.replies = []

    async def answer(self, text, **kwargs):
        self.replies.append(text)


@pytest.fixture
def gate(conn):
    return AccessMiddleware(ChatTarget(conn, OLD_CHAT))


async def run(mw, event, bot):
    async def handler(e, data):
        return "handled"

    return await mw(handler, event, {"bot": bot})


async def test_member_is_not_locked_out_by_a_migrated_chat(conn, gate):
    # Regression: after the group became a supergroup every membership check
    # raised, and the bot told real members they were strangers.
    bot = MigratingBot()
    msg = FakeMessage(385730505, 385730505, "private")

    assert await run(gate, msg, bot) == "handled"
    assert msg.replies == []
    assert bot.calls == [OLD_CHAT, NEW_CHAT]


async def test_group_messages_resume_after_migration_is_learned(conn, gate):
    bot = MigratingBot()
    # The supergroup's messages arrive under the new id, unknown at first.
    assert await run(gate, FakeMessage(1, NEW_CHAT, "supergroup"), bot) is None

    # One DM teaches the bot the new id...
    await run(gate, FakeMessage(2, 2, "private"), bot)

    # ...and the group works from then on.
    assert await run(gate, FakeMessage(1, NEW_CHAT, "supergroup"), bot) == "handled"


async def test_stranger_is_still_refused_after_migration(conn, gate):
    class GoneBot(MigratingBot):
        async def get_chat_member(self, chat_id, user_id):
            self.calls.append(chat_id)
            if chat_id == OLD_CHAT:
                raise migrate_error()
            return SimpleNamespace(status="left")

    msg = FakeMessage(999, 999, "private")
    assert await run(gate, msg, GoneBot()) is None
    assert msg.replies == [DENIED_TEXT]
