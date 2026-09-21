from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message

from bot.config import Settings
from bot.keyboards import MENU_BUTTON_TEXTS


class NotMenuButton(BaseFilter):
    """True, если текст не является кнопкой меню — чтобы FSM ввода имени
    не перехватывал «Список», «Happ» и т.д."""

    async def __call__(self, message: Message, settings: Settings) -> bool:
        text = message.text or ""
        if text in MENU_BUTTON_TEXTS:
            return False
        if settings.link_url and text == settings.link_button_text:
            return False
        return True
