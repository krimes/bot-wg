from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from bot.db import Profile


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Новый профиль"), KeyboardButton(text="📋 Список")],
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def profiles_list(profiles: list[Profile]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"#{p.id} · {p.name}", callback_data=f"prof:show:{p.id}")]
        for p in profiles
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows or [
        [InlineKeyboardButton(text="Профилей пока нет", callback_data="noop")]
    ])


def profile_actions(profile_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 Скачать .conf", callback_data=f"prof:conf:{profile_id}"),
            InlineKeyboardButton(text="📱 QR", callback_data=f"prof:qr:{profile_id}"),
        ],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"prof:del:{profile_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data="prof:back")],
    ])


def confirm_delete(profile_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"prof:del_yes:{profile_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"prof:show:{profile_id}"),
        ],
    ])
