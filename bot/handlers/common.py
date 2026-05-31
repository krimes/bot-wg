from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.keyboards import main_menu

router = Router(name="common")


HELP_TEXT = (
    "🛡 <b>AmneziaWG Manager</b>\n\n"
    "Команды:\n"
    "• /new <code>имя</code> — создать новый профиль\n"
    "• /list — список профилей\n"
    "• /stats — статистика подключений\n"
    "• /help — это сообщение\n\n"
    "Также доступны кнопки меню."
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu())


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu())
