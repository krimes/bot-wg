from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, CommandStart
from aiogram.types import Message

from bot.config import Settings
from bot.keyboards import link_kb, main_menu

router = Router(name="common")


class LinkButtonFilter(BaseFilter):
    """Срабатывает на reply-кнопку из main_menu, текст которой совпадает с
    LINK_BUTTON_TEXT. Settings достаём из workflow_data — поэтому работает
    динамически, без хардкода текста кнопки в фильтре."""

    async def __call__(self, message: Message, settings: Settings) -> bool:
        return bool(settings.link_url) and message.text == settings.link_button_text


def _help_text(settings: Settings) -> str:
    lines = [
        "🛡 <b>AmneziaWG Manager</b>\n",
        "Команды:",
        "• /new <code>имя</code> — создать новый профиль",
        "• /list — список профилей",
        "• /stats — статистика подключений",
    ]
    if settings.link_url:
        lines.append("• /link — полезная ссылка")
    lines += ["• /help — это сообщение", "", "Также доступны кнопки меню."]
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(message: Message, settings: Settings) -> None:
    await message.answer(
        _help_text(settings),
        reply_markup=main_menu(
            link_button_text=settings.link_button_text if settings.link_url else None,
        ),
    )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message, settings: Settings) -> None:
    await message.answer(
        _help_text(settings),
        reply_markup=main_menu(
            link_button_text=settings.link_button_text if settings.link_url else None,
        ),
    )


# --- Ссылка: команда /link и кнопка в reply-меню ---

@router.message(Command("link"))
async def cmd_link(message: Message, settings: Settings) -> None:
    await _send_link(message, settings)


@router.message(LinkButtonFilter())
async def btn_link(message: Message, settings: Settings) -> None:
    await _send_link(message, settings)


async def _send_link(message: Message, settings: Settings) -> None:
    if not settings.link_url:
        await message.answer("Ссылка не настроена администратором.")
        return
    await message.answer(
        f"🔗 <b>{settings.link_button_text}</b>",
        reply_markup=link_kb(settings.link_url, settings.link_button_text),
        disable_web_page_preview=True,
    )
