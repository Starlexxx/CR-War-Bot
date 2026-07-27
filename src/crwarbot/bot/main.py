from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import BotCommand

from crwarbot.api.client import SupercellClient
from crwarbot.api.rate_limiter import RateLimiter
from crwarbot.bot.access import AccessMiddleware
from crwarbot.bot.chat import ChatTarget
from crwarbot.bot.handlers import Deps, router
from crwarbot.config import get_settings
from crwarbot.db.connection import apply_migrations, connect
from crwarbot.worker.poller import Poller

log = logging.getLogger(__name__)

# Shown in Telegram's "/" hint, so nobody has to memorise the command list.
COMMANDS = [
    BotCommand(command="menu", description="Кнопки вместо команд"),
    BotCommand(command="today", description="Кто ещё не отыграл сегодня"),
    BotCommand(command="war", description="Медали и атаки в текущей войне"),
    BotCommand(command="rating", description="Рейтинг клана"),
    BotCommand(command="discipline", description="Процент отыгранных атак"),
    BotCommand(command="me", description="Своя статистика"),
    BotCommand(command="stats", description="Статистика игрока по нику"),
    BotCommand(command="link", description="Привязать телеграм к игровому нику"),
    BotCommand(command="unlink", description="Снять привязку"),
    BotCommand(command="whoami", description="Показать свою привязку"),
    BotCommand(command="roster", description="Кто привязан к телеграму"),
    BotCommand(command="help", description="Справка"),
]


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    conn = await connect(settings.db_path)
    await apply_migrations(conn, settings.migrations_dir)

    client = SupercellClient(
        base_url=settings.cr_api_base_url,
        token=settings.cr_api_token,
        rate_limiter=RateLimiter(rate_per_sec=5, max_concurrent=3),
    )
    session = AiohttpSession(proxy=settings.telegram_proxy) if settings.telegram_proxy else None
    if session is not None:
        log.info("routing Telegram through a proxy")
    bot = Bot(token=settings.telegram_bot_token, session=session)
    target = ChatTarget(conn, settings.telegram_chat_id)
    poller = Poller(conn, client, bot, settings, target)

    dispatcher = Dispatcher()
    access = AccessMiddleware(target)
    dispatcher.message.middleware(access)
    dispatcher.callback_query.middleware(access)
    dispatcher.include_router(router)
    dispatcher["deps"] = Deps(conn=conn, client=client, settings=settings, poller=poller)

    await bot.set_my_commands(COMMANDS)

    poll_task = asyncio.create_task(poller.run(), name="poller")
    try:
        await dispatcher.start_polling(bot)
    finally:
        poll_task.cancel()
        await asyncio.gather(poll_task, return_exceptions=True)
        await client.aclose()
        await bot.session.close()
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
