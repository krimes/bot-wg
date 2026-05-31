from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

log = logging.getLogger(__name__)


class AdminOnlyMiddleware(BaseMiddleware):
    """Пропускает только пользователей, чей telegram-id есть в admin_ids."""

    def __init__(self, admin_ids: list[int]) -> None:
        self._admins = set(admin_ids)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id not in self._admins:
            uid = user.id if user else None
            log.warning("denied access: telegram_id=%s", uid)
            if isinstance(event, Message):
                await event.answer("⛔️ Доступ запрещён.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔️ Доступ запрещён.", show_alert=True)
            return None
        return await handler(event, data)
