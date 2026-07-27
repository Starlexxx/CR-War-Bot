from types import SimpleNamespace

from crwarbot.bot.access import DENIED_TEXT, AccessMiddleware

CLAN_CHAT = -1001234567890
OTHER_CHAT = -111


class FakeBot:
    def __init__(self, statuses):
        self.statuses = statuses
        self.calls = 0

    async def get_chat_member(self, chat_id, user_id):
        self.calls += 1
        status = self.statuses.get(user_id)
        if status is None:
            raise RuntimeError("user not found")
        if isinstance(status, tuple):
            return SimpleNamespace(status=status[0], is_member=status[1])
        return SimpleNamespace(status=status)


class FakeMessage:
    def __init__(self, user_id, chat_id, chat_type):
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(id=chat_id, type=chat_type)
        self.replies = []

    async def answer(self, text, **kwargs):
        self.replies.append(text)


class FakeCallback:
    def __init__(self, user_id, message):
        self.from_user = SimpleNamespace(id=user_id)
        self.message = message
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)


async def run(mw, event, bot):
    seen = []

    async def handler(e, data):
        seen.append(e)
        return "handled"

    result = await mw(handler, event, {"bot": bot})
    return result, seen


async def test_clan_member_is_served_in_dm():
    mw = AccessMiddleware(CLAN_CHAT)
    bot = FakeBot({7: "member"})
    msg = FakeMessage(7, 7, "private")

    result, seen = await run(mw, msg, bot)

    assert result == "handled"
    assert len(seen) == 1


async def test_stranger_is_refused_in_dm():
    mw = AccessMiddleware(CLAN_CHAT)
    bot = FakeBot({7: "left"})
    msg = FakeMessage(7, 7, "private")

    result, seen = await run(mw, msg, bot)

    assert result is None
    assert seen == []
    assert msg.replies == [DENIED_TEXT]


async def test_unknown_user_is_refused():
    # getChatMember raises for someone who was never in the chat.
    mw = AccessMiddleware(CLAN_CHAT)
    bot = FakeBot({})
    msg = FakeMessage(99, 99, "private")

    result, _ = await run(mw, msg, bot)

    assert result is None
    assert msg.replies == [DENIED_TEXT]


async def test_banned_user_is_refused():
    mw = AccessMiddleware(CLAN_CHAT)
    bot = FakeBot({7: "kicked"})
    msg = FakeMessage(7, 7, "private")

    result, _ = await run(mw, msg, bot)
    assert result is None


async def test_restricted_but_still_in_chat_is_served():
    mw = AccessMiddleware(CLAN_CHAT)
    bot = FakeBot({7: ("restricted", True)})
    msg = FakeMessage(7, 7, "private")

    result, _ = await run(mw, msg, bot)
    assert result == "handled"


async def test_restricted_and_gone_is_refused():
    mw = AccessMiddleware(CLAN_CHAT)
    bot = FakeBot({7: ("restricted", False)})
    msg = FakeMessage(7, 7, "private")

    result, _ = await run(mw, msg, bot)
    assert result is None


async def test_clan_group_needs_no_per_user_lookup():
    mw = AccessMiddleware(CLAN_CHAT)
    bot = FakeBot({})
    msg = FakeMessage(7, CLAN_CHAT, "supergroup")

    result, _ = await run(mw, msg, bot)

    assert result == "handled"
    assert bot.calls == 0


async def test_foreign_group_is_ignored_silently():
    mw = AccessMiddleware(CLAN_CHAT)
    bot = FakeBot({7: "member"})
    msg = FakeMessage(7, OTHER_CHAT, "supergroup")

    result, seen = await run(mw, msg, bot)

    assert result is None
    assert seen == []
    assert msg.replies == []


async def test_membership_is_cached():
    mw = AccessMiddleware(CLAN_CHAT)
    bot = FakeBot({7: "member"})

    await run(mw, FakeMessage(7, 7, "private"), bot)
    await run(mw, FakeMessage(7, 7, "private"), bot)

    assert bot.calls == 1


async def test_callback_from_stranger_gets_an_alert():
    mw = AccessMiddleware(CLAN_CHAT)
    bot = FakeBot({7: "left"})
    callback = FakeCallback(7, FakeMessage(7, 7, "private"))

    result, seen = await run(mw, callback, bot)

    assert result is None
    assert seen == []
    assert callback.answers == [DENIED_TEXT]
