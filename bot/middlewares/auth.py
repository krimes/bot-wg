from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import Settings
from bot.db import Database

log = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    """Пускает ADMIN_IDS из .env и включённых пользователей из таблицы bot_users."""

    def __init__(self, settings: Settings, db: Database) -> None:
        self._s = settings
        self._db = db
        self._env_admins = set(settings.admin_ids)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return None
        uid = user.id
        allowed = uid in self._env_admins
        if not allowed:
            rec = await self._db.get_bot_user(uid)
            allowed = rec is not None and rec.enabled
        if not allowed:
            log.warning("denied access: telegram_id=%s", uid)
            if isinstance(event, Message):
                await event.answer("⛔️ Доступ запрещён.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔️ Доступ запрещён.", show_alert=True)
            return None
        data["is_main_admin"] = self._s.is_main_admin(uid)
        try:
            fio = " ".join(
                p for p in (user.first_name, getattr(user, "last_name", None)) if p
            ) or None
            await self._db.upsert_telegram_profile(
                telegram_id=uid,
                first_name=user.first_name,
                last_name=getattr(user, "last_name", None),
                username=user.username,
            )
            await self._db.touch_bot_user_profile(
                uid, name=fio, username=user.username,
            )
        except Exception:  # noqa: BLE001
            log.exception("failed to refresh telegram profile uid=%s", uid)
        return await handler(event, data)
