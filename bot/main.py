from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import get_settings
from bot.db import Database
from bot.handlers import router as root_router
from bot.middlewares.auth import AccessMiddleware
from bot.services.awg import AwgService
from bot.services.xui import XuiService


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def main() -> None:
    _setup_logging()
    log = logging.getLogger("awg-bot")
    settings = get_settings()

    if not settings.admin_ids:
        log.error("ADMIN_IDS пуст — бот никого не пустит. Заполните .env.")
        sys.exit(1)

    db = Database(settings.db_path)
    await db.init()

    awg = AwgService(settings)
    xui = XuiService(settings)

    # Бэкфилл: убеждаемся, что все профили из БД присутствуют в clientsTable.
    # Это нужно при первом запуске после апгрейда или если файл GUI был очищен.
    if settings.awg_clients_table_path:
        try:
            for p in await db.list_profiles():
                await awg.register_in_clients_table(
                    public_key=p.public_key,
                    name=f"{p.display_name} [tg:{p.created_by}]",
                )
            log.info("clientsTable backfill complete")
        except Exception:  # noqa: BLE001
            log.exception("clientsTable backfill failed (non-fatal)")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    auth = AccessMiddleware(settings, db)
    dp.message.middleware(auth)
    dp.callback_query.middleware(auth)

    # Прокидываем зависимости в handler'ы через workflow_data
    dp["db"] = db
    dp["awg"] = awg
    dp["xui"] = xui
    dp["settings"] = settings

    dp.include_router(root_router)

    log.info(
        "Bot started. admins=%s main_admin=%s container=%s iface=%s xui=%s inbound=%s",
        settings.admin_ids,
        settings.resolved_main_admin_id(),
        settings.awg_container,
        settings.awg_interface,
        bool(settings.xui_host),
        settings.xui_inbound_id,
    )
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await xui.aclose()


if __name__ == "__main__":
    asyncio.run(main())
