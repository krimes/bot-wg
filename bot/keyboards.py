from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from dataclasses import dataclass

from bot.access import is_main_admin
from bot.db import HappProfile, Profile

BTN_NEW_PROFILE = "➕ Добавить профиль"
BTN_NEW_PROFILE_LEGACY = "➕ Новый профиль"
BTN_NEW_WG = "➕ Новый WG"
BTN_NEW_HAPP = "➕ Новый Happ"
BTN_LIST = "📋 Список"
BTN_STATS = "📊 Статистика"
BTN_HELP = "ℹ️ Помощь"
BTN_USERS = "👥 Пользователи"
BTN_BROADCAST = "📣 Рассылка"
BTN_CANCEL = "❌ Отмена"

MENU_BUTTON_TEXTS = frozenset({
    BTN_NEW_PROFILE, BTN_NEW_PROFILE_LEGACY,
    BTN_NEW_WG, BTN_NEW_HAPP, BTN_LIST, BTN_STATS, BTN_HELP,
    BTN_USERS, BTN_BROADCAST, BTN_CANCEL,
})


def main_menu(
    link_button_text: str | None = None,
    *,
    is_main_admin: bool = False,
) -> ReplyKeyboardMarkup:
    """Главное reply-меню. У главного админа — отдельная секция управления."""
    rows = [
        [KeyboardButton(text=BTN_NEW_PROFILE)],
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


def choose_profile_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛡 AmneziaWG", callback_data="new:wg"),
            InlineKeyboardButton(text="📱 Happ", callback_data="new:happ"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="new:cancel")],
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
    if not rows:
        rows.append([InlineKeyboardButton(
            text="Профилей пока нет", callback_data="noop",
        )])
    rows.append([InlineKeyboardButton(
        text="➕ Добавить профиль", callback_data="new:choose",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


@dataclass(slots=True)
class UserListRow:
    telegram_id: int
    title: str
    kind: str  # env | db
    enabled: bool = True
    is_main: bool = False


def _btn_text(text: str) -> str:
    return text if len(text) <= 64 else text[:61] + "..."


def users_list_kb(rows: list[UserListRow]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for row in rows:
        if row.kind == "env":
            mark = "👑" if row.is_main else "🛡"
            cb = f"usr:env:{row.telegram_id}"
        else:
            mark = "✅" if row.enabled else "⏸"
            cb = f"usr:show:{row.telegram_id}"
        buttons.append([InlineKeyboardButton(
            text=_btn_text(f"{mark} {row.title}"),
            callback_data=cb,
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить", callback_data="usr:add")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_to_users_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« К списку", callback_data="usr:list")],
    ])


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
