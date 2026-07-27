from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import aiosqlite
from aiogram.exceptions import TelegramMigrateToChat

from crwarbot.db.queries import kv_get, kv_set

log = logging.getLogger(__name__)

KV_CHAT_ID = "effective_chat_id"

T = TypeVar("T")


class ChatTarget:
    """The clan chat id, following Telegram's supergroup migrations.

    Upgrading a basic group to a supergroup gives it a brand new id unrelated to
    the old one, and every call against the stale id then fails. Telegram
    reports the replacement in the error, so the new id is recorded and reused
    instead of forcing someone to edit `.env` and restart.
    """

    def __init__(self, conn: aiosqlite.Connection, configured: int) -> None:
        self._conn = conn
        self._configured = configured
        self._cached: int | None = None

    async def get(self) -> int:
        if self._cached is None:
            stored = await kv_get(self._conn, KV_CHAT_ID)
            self._cached = int(stored) if stored else self._configured
        return self._cached

    async def migrate_to(self, new_id: int) -> None:
        old = await self.get()
        if old == new_id:
            return
        self._cached = new_id
        await kv_set(self._conn, KV_CHAT_ID, str(new_id))
        log.warning("clan chat migrated from %s to %s", old, new_id)

    async def call(self, action: Callable[[int], Awaitable[T]]) -> T:
        """Run an API call against the chat, retrying once if it has migrated."""
        try:
            return await action(await self.get())
        except TelegramMigrateToChat as exc:
            await self.migrate_to(exc.migrate_to_chat_id)
            return await action(exc.migrate_to_chat_id)

    async def note_service_message(self, message: Any) -> bool:
        """Record a migration announced by a service message. True if it was one."""
        new_id = getattr(message, "migrate_to_chat_id", None)
        if new_id is None:
            return False
        await self.migrate_to(new_id)
        return True
