from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from crwarbot.bot.chat import ChatTarget

log = logging.getLogger(__name__)

MEMBER_STATUSES = frozenset({"creator", "administrator", "member", "restricted"})

ALLOW_TTL_SECONDS = 600
DENY_TTL_SECONDS = 60

DENIED_TEXT = "Этот бот только для участников клановой беседы."


class AccessMiddleware(BaseMiddleware):
    """Restrict the bot to members of the clan chat, in groups and in DMs alike.

    Membership is resolved with `getChatMember` against the configured chat and
    cached, since otherwise every command would cost an extra Telegram round
    trip. Denials expire quickly so that someone who has just been added does
    not stay locked out for ten minutes.
    """

    def __init__(self, target: ChatTarget) -> None:
        self._target = target
        self._cache: dict[int, tuple[bool, float]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # A Message carries `chat` directly; a CallbackQuery only through the
        # message it is attached to.
        chat = getattr(event, "chat", None)
        if chat is None:
            chat = getattr(getattr(event, "message", None), "chat", None)

        if await self._target.note_service_message(event):
            return None

        if chat is not None and chat.type in ("group", "supergroup"):
            if chat.id != await self._target.get():
                # Someone dragged the bot into an unrelated group.
                return None
            return await handler(event, data)

        user = getattr(event, "from_user", None)
        if user is None:
            return None

        if await self.is_member(data["bot"], user.id):
            return await handler(event, data)

        await self._refuse(event)
        return None

    async def _refuse(self, event: TelegramObject) -> None:
        if hasattr(event, "chat"):
            await event.answer(DENIED_TEXT)
        else:
            await event.answer(DENIED_TEXT, show_alert=True)

    async def is_member(self, bot: Any, user_id: int) -> bool:
        cached = self._cache.get(user_id)
        now = time.monotonic()
        if cached is not None and cached[1] > now:
            return cached[0]

        try:
            member = await self._target.call(
                lambda chat_id: bot.get_chat_member(chat_id, user_id)
            )
            allowed = member.status in MEMBER_STATUSES
            if member.status == "restricted":
                allowed = bool(getattr(member, "is_member", False))
        except Exception:
            log.warning("membership check failed for %s, denying", user_id, exc_info=True)
            allowed = False

        ttl = ALLOW_TTL_SECONDS if allowed else DENY_TTL_SECONDS
        self._cache[user_id] = (allowed, now + ttl)
        return allowed
