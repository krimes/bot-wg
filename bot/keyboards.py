from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from bot.access import is_main_admin
from bot.db import BotUser, HappProfile, Profile

BTN_NEW_WG = "➕ Новый WG"
BTN_NEW_HAPP = "➕ Новый Happ"
BTN_LIST = "📋 Список"
BTN_STATS = "📊 Статистика"
BTN_HELP = "ℹ️ Помощь"
BTN_USERS = "👥 Пользователи"
BTN_BROADCAST = "📣 Рассылка"
BTN_CANCEL = "❌ Отмена"

MENU_BUTTON_TEXTS = frozenset({
    BTN_NEW_WG, BTN_NEW_HAPP, BTN_LIST, BTN_STATS, BTN_HELP,
    BTN_USERS, BTN_BROADCAST,
})


def main_menu(
    link_button_text: str | None = None,
    *,
    is_main_admin: bool = False,
) -> ReplyKeyboardMarkup:
    """Главное reply-меню. У главного админа — отдельная секция управления."""
    rows = [
        [KeyboardButton(text=BTN_NEW_WG), KeyboardButton(text=BTN_NEW_HAPP)],
        [KeyboardButton(text=BTN_LIST), KeyboardButton(text=BTN_STATS)],
        [KeyboardButton(text=BTN_HELP)],
    ]
    if is_main_admin:
        rows.append([
            KeyboardButton(text=BTN_USERS),
            KeyboardButton(text=BTN_BROADCAST),
        ])
    if link_button_text:
        rows.append([KeyboardButton(text=link_button_text)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def reply_menu(settings, user_id: int) -> ReplyKeyboardMarkup:
    return main_menu(
        link_button_text=settings.link_button_text if settings.link_url else None,
        is_main_admin=is_main_admin(user_id, settings.admin_ids, settings.main_admin_id),
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
        input_field_placeholder="Или отмена",
    )


def link_kb(url: str, text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, url=url)],
    ])


def profiles_list(
    wg: list[Profile],
    happ: list[HappProfile] | None = None,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"WG · {p.display_name}", callback_data=f"prof:show:{p.id}"
        )]
        for p in wg
    ]
    for p in happ or []:
        rows.append([InlineKeyboardButton(
            text=f"Happ · {p.display_name}", callback_data=f"happ:show:{p.id}"
        )])
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


def happ_actions(profile_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔑 Ключ", callback_data=f"happ:link:{profile_id}"),
            InlineKeyboardButton(text="📱 QR", callback_data=f"happ:qr:{profile_id}"),
        ],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"happ:del:{profile_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data="prof:back")],
    ])


def confirm_delete_happ(profile_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"happ:del_yes:{profile_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"happ:show:{profile_id}"),
        ],
    ])


def users_list_kb(
    users: list[BotUser],
    env_admins: list[int],
    main_admin_id: int | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for aid in env_admins:
        crown = "👑 " if aid == main_admin_id else ""
        rows.append([InlineKeyboardButton(
            text=f"{crown}🛡 {aid} · .env",
            callback_data="usr:noop",
        )])
    for u in users:
        mark = "✅" if u.enabled else "⏸"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {u.label} · {u.telegram_id}",
            callback_data=f"usr:show:{u.telegram_id}",
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data="usr:add")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_actions_kb(telegram_id: int, enabled: bool) -> InlineKeyboardMarkup:
    toggle = "⏸ Выключить" if enabled else "✅ Включить"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle, callback_data=f"usr:toggle:{telegram_id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"usr:del:{telegram_id}")],
        [InlineKeyboardButton(text="« К списку", callback_data="usr:list")],
    ])


def confirm_delete_user_kb(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Удалить", callback_data=f"usr:del_yes:{telegram_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"usr:show:{telegram_id}"),
        ],
    ])


def confirm_broadcast_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить всем", callback_data="bc:yes"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="bc:no"),
        ],
    ])
