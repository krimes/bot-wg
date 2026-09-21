from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.access import format_person_label, merge_recipient_ids
from bot.config import Settings
from bot.db import BotUser, Database
from bot.keyboards import (
    BTN_BROADCAST,
    BTN_CANCEL,
    BTN_USERS,
    MENU_BUTTON_TEXTS,
    UserListRow,
    cancel_kb,
    confirm_broadcast_kb,
    back_to_users_kb,
    confirm_delete_user_kb,
    reply_menu,
    user_actions_kb,
    users_list_kb,
)

log = logging.getLogger(__name__)
router = Router(name="admin")


class MainAdminFilter(BaseFilter):
    async def __call__(self, event: TelegramObject, settings: Settings) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user) and settings.is_main_admin(user.id)


router.message.filter(MainAdminFilter())
router.callback_query.filter(MainAdminFilter())


class AddUserSG(StatesGroup):
    waiting_id = State()


class BroadcastSG(StatesGroup):
    waiting_content = State()
    waiting_confirm = State()


def _menu(message: Message, settings: Settings):
    return reply_menu(settings, message.from_user.id)


# ============================================================
# Пользователи
# ============================================================


@router.message(Command("users"))
@router.message(F.text == BTN_USERS)
async def cmd_users(
    message: Message, state: FSMContext, db: Database, settings: Settings,
) -> None:
    await state.clear()
    rows = await _collect_rows(message.bot, db, settings)
    await message.answer(
        _list_message(rows, settings),
        reply_markup=_menu(message, settings),
    )
    await message.answer("Управление:", reply_markup=users_list_kb(rows))


@router.callback_query(F.data.startswith("usr:env:"))
async def cb_usr_env(
    call: CallbackQuery, db: Database, settings: Settings,
) -> None:
    uid = _cb_int(call)
    if uid is None:
        return
    first, last, uname = await _resolve_names(call.bot, db, uid)
    label = format_person_label(
        first_name=first, last_name=last, username=uname, telegram_id=uid,
    )
    role = "главный админ" if settings.is_main_admin(uid) else "админ из .env"
    nick = f"@{html.escape(uname)}" if uname else "—"
    fio = " ".join(p for p in (first, last) if p) or "—"
    await call.message.edit_text(
        f"<b>{html.escape(label)}</b>\n"
        f"ФИ: {html.escape(fio)}\n"
        f"Ник: {nick}\n"
        f"ID: <code>{uid}</code>\n"
        f"Роль: {role}\n"
        "Удаляется только из ADMIN_IDS в .env.",
        reply_markup=back_to_users_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "usr:list")
async def cb_usr_list(
    call: CallbackQuery, db: Database, settings: Settings,
) -> None:
    rows = await _collect_rows(call.bot, db, settings)
    await call.message.edit_text(
        _list_message(rows, settings),
        reply_markup=users_list_kb(rows),
    )
    await call.answer()


@router.callback_query(F.data == "usr:add")
async def cb_usr_add(call: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await state.set_state(AddUserSG.waiting_id)
    await call.message.answer(
        "Пришлите <b>числовой Telegram ID</b> или перешлите сообщение этого человека.\n"
        "Можно: <code>123456789 Имя</code>",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.message(Command("useradd"))
async def cmd_useradd(
    message: Message, command: CommandObject, db: Database, settings: Settings,
) -> None:
    raw = (command.args or "").strip()
    parts = raw.split(maxsplit=1)
    if not parts or not parts[0].isdigit():
        await message.answer("Использование: <code>/useradd 123456789 Иван</code>")
        return
    tid = int(parts[0])
    name = parts[1].strip() if len(parts) > 1 else None
    await _save_user(message, db, settings, tid, name, None)


@router.message(AddUserSG.waiting_id, F.text == BTN_CANCEL)
@router.message(AddUserSG.waiting_id, F.text.in_(MENU_BUTTON_TEXTS))
async def add_user_cancel(
    message: Message, state: FSMContext, settings: Settings,
) -> None:
    await state.clear()
    await message.answer("Добавление отменено.", reply_markup=_menu(message, settings))


@router.message(AddUserSG.waiting_id)
async def add_user_id(
    message: Message, state: FSMContext, db: Database, settings: Settings,
) -> None:
    parsed = _parse_new_user(message)
    if parsed is None:
        await message.answer(
            "Нужен Telegram ID (цифры) или пересланное сообщение. Либо ❌ Отмена."
        )
        return
    await state.clear()
    await _save_user(message, db, settings, *parsed)


@router.callback_query(F.data.startswith("usr:show:"))
async def cb_usr_show(call: CallbackQuery, db: Database) -> None:
    uid = _cb_int(call)
    if uid is None:
        return
    user = await db.get_bot_user(uid)
    if user is None:
        await call.answer("Пользователь не найден", show_alert=True)
        return
    first, last, uname = await _resolve_names(call.bot, db, uid, stored=user)
    label = format_person_label(
        first_name=first, last_name=last, username=uname, telegram_id=uid,
    )
    status = "включён" if user.enabled else "выключен"
    nick = f"@{html.escape(uname)}" if uname else "—"
    fio = " ".join(p for p in (first, last) if p) or "—"
    await call.message.edit_text(
        f"<b>{html.escape(label)}</b>\n"
        f"ФИ: {html.escape(fio)}\n"
        f"Ник: {nick}\n"
        f"ID: <code>{user.telegram_id}</code>\n"
        f"Статус: {status}\n"
        f"Добавлен: {user.created_at:%Y-%m-%d %H:%M UTC}",
        reply_markup=user_actions_kb(user.telegram_id, user.enabled),
    )
    await call.answer()


@router.callback_query(F.data.startswith("usr:toggle:"))
async def cb_usr_toggle(call: CallbackQuery, db: Database) -> None:
    uid = _cb_int(call)
    if uid is None:
        return
    user = await db.get_bot_user(uid)
    if user is None:
        await call.answer("Пользователь не найден", show_alert=True)
        return
    updated = await db.set_bot_user_enabled(uid, not user.enabled)
    assert updated is not None
    verb = "включён" if updated.enabled else "выключен"
    await call.message.edit_text(
        f"Пользователь <b>{html.escape(updated.label)}</b> {verb}.",
        reply_markup=user_actions_kb(updated.telegram_id, updated.enabled),
    )
    await call.answer(verb)


@router.callback_query(F.data.startswith("usr:del:"))
async def cb_usr_del_ask(call: CallbackQuery, db: Database) -> None:
    uid = _cb_int(call)
    if uid is None:
        return
    user = await db.get_bot_user(uid)
    if user is None:
        await call.answer("Пользователь не найден", show_alert=True)
        return
    await call.message.edit_text(
        f"Удалить <b>{html.escape(user.label)}</b> (<code>{uid}</code>)?\n"
        "Доступ к боту пропадет. Профили WG/Happ останутся на сервере.",
        reply_markup=confirm_delete_user_kb(uid),
    )
    await call.answer()


@router.callback_query(F.data.startswith("usr:del_yes:"))
async def cb_usr_del_yes(
    call: CallbackQuery, db: Database, settings: Settings,
) -> None:
    uid = _cb_int(call)
    if uid is None:
        return
    deleted = await db.delete_bot_user(uid)
    if deleted is None:
        await call.answer("Уже удалён", show_alert=True)
        return
    rows = await _collect_rows(call.bot, db, settings)
    await call.message.edit_text(
        f"🗑 {html.escape(deleted.label)} удалён.\n\n" + _list_message(rows, settings),
        reply_markup=users_list_kb(rows),
    )
    await call.answer("Удалено")


# ============================================================
# Рассылка
# ============================================================


@router.message(Command("broadcast"))
@router.message(F.text == BTN_BROADCAST)
async def cmd_broadcast(
    message: Message, state: FSMContext, db: Database, settings: Settings,
) -> None:
    await state.set_state(BroadcastSG.waiting_content)
    n = len(await _recipients(db, settings, message.from_user.id))
    await message.answer(
        f"Пришлите сообщение для рассылки (текст, фото, файл).\n"
        f"Получателей: <b>{n}</b> (все, у кого есть доступ, кроме вас).",
        reply_markup=cancel_kb(),
    )


@router.message(BroadcastSG.waiting_content, F.text == BTN_CANCEL)
@router.message(BroadcastSG.waiting_content, F.text.in_(MENU_BUTTON_TEXTS))
@router.message(BroadcastSG.waiting_confirm, F.text == BTN_CANCEL)
@router.message(BroadcastSG.waiting_confirm, F.text.in_(MENU_BUTTON_TEXTS))
async def broadcast_cancel(
    message: Message, state: FSMContext, settings: Settings,
) -> None:
    await state.clear()
    await message.answer("Рассылка отменена.", reply_markup=_menu(message, settings))


@router.message(BroadcastSG.waiting_content)
async def broadcast_content(
    message: Message, state: FSMContext, db: Database, settings: Settings,
) -> None:
    recipients = await _recipients(db, settings, message.from_user.id)
    if not recipients:
        await state.clear()
        await message.answer(
            "Некому отправлять — нет других пользователей.",
            reply_markup=_menu(message, settings),
        )
        return
    await state.set_state(BroadcastSG.waiting_confirm)
    await state.update_data(
        from_chat_id=message.chat.id,
        message_id=message.message_id,
        recipients=recipients,
    )
    await message.answer(
        f"Отправить это сообщение <b>{len(recipients)}</b> получателям?",
        reply_markup=confirm_broadcast_kb(),
    )


@router.callback_query(BroadcastSG.waiting_confirm, F.data == "bc:no")
async def broadcast_no(
    call: CallbackQuery, state: FSMContext, settings: Settings,
) -> None:
    await state.clear()
    await call.message.answer("Рассылка отменена.", reply_markup=reply_menu(settings, call.from_user.id))
    await call.answer("Отменено")


@router.callback_query(BroadcastSG.waiting_confirm, F.data == "bc:yes")
async def broadcast_yes(
    call: CallbackQuery, state: FSMContext, settings: Settings,
) -> None:
    data = await state.get_data()
    await state.clear()
    from_chat_id = data.get("from_chat_id")
    message_id = data.get("message_id")
    recipients: list[int] = data.get("recipients") or []
    if not from_chat_id or not message_id or not recipients:
        await call.message.answer(
            "Нечего отправлять.",
            reply_markup=reply_menu(settings, call.from_user.id),
        )
        await call.answer()
        return

    await call.message.answer(f"⏳ Рассылаю {len(recipients)}…")
    ok = 0
    failed = 0
    bot = call.bot
    for uid in recipients:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=from_chat_id,
                message_id=message_id,
            )
            ok += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 0.1)
            try:
                await bot.copy_message(
                    chat_id=uid,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                )
                ok += 1
            except Exception:  # noqa: BLE001
                failed += 1
                log.exception("broadcast retry failed uid=%s", uid)
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            failed += 1
            log.info("broadcast skip uid=%s: %s", uid, exc)
        except Exception:  # noqa: BLE001
            failed += 1
            log.exception("broadcast failed uid=%s", uid)
        await asyncio.sleep(0.05)

    await call.message.answer(
        f"📣 Готово.\nДоставлено: <b>{ok}</b>\nНе доставлено: <b>{failed}</b>",
        reply_markup=reply_menu(settings, call.from_user.id),
    )
    await call.answer("Готово")


# ============================================================
# helpers
# ============================================================


def _list_message(rows: list[UserListRow], settings: Settings) -> str:
    db_n = sum(1 for r in rows if r.kind == "db")
    enabled = sum(1 for r in rows if r.kind == "db" and r.enabled)
    lines = [
        "<b>👥 Пользователи бота</b>",
        f".env: <b>{len(settings.admin_ids)}</b> · в базе: <b>{db_n}</b> · "
        f"включено: <b>{enabled}</b>",
        "",
    ]
    for row in rows:
        if row.kind == "env":
            mark = "👑" if row.is_main else "🛡"
            tag = " · .env"
        else:
            mark = "✅" if row.enabled else "⏸"
            tag = "" if row.enabled else " · выкл"
        lines.append(f"{mark} {html.escape(row.title)}{tag}")
        lines.append(f"<code>{row.telegram_id}</code>")
        lines.append("")
    if not rows:
        lines.append("Пока никого нет.")
    return "\n".join(lines).rstrip()


async def _collect_rows(bot: Bot, db: Database, settings: Settings) -> list[UserListRow]:
    db_users = await db.list_bot_users()
    env_ids = set(settings.admin_ids)
    main_id = settings.resolved_main_admin_id()
    rows: list[UserListRow] = []
    for aid in settings.admin_ids:
        first, last, uname = await _resolve_names(bot, db, aid)
        rows.append(UserListRow(
            telegram_id=aid,
            title=format_person_label(
                first_name=first, last_name=last, username=uname, telegram_id=aid,
            ),
            kind="env",
            is_main=aid == main_id,
        ))
    for user in db_users:
        if user.telegram_id in env_ids:
            continue
        first, last, uname = await _resolve_names(bot, db, user.telegram_id, stored=user)
        rows.append(UserListRow(
            telegram_id=user.telegram_id,
            title=format_person_label(
                first_name=first, last_name=last, username=uname,
                telegram_id=user.telegram_id,
            ),
            kind="db",
            enabled=user.enabled,
        ))
    return rows


async def _resolve_names(
    bot: Bot,
    db: Database,
    telegram_id: int,
    stored: BotUser | None = None,
) -> tuple[str | None, str | None, str | None]:
    first = last = uname = None
    try:
        chat = await bot.get_chat(telegram_id)
        first = chat.first_name
        last = chat.last_name
        uname = chat.username
    except Exception:  # noqa: BLE001
        log.debug("get_chat failed uid=%s", telegram_id, exc_info=True)
    if first or last or uname:
        try:
            await db.upsert_telegram_profile(
                telegram_id=telegram_id,
                first_name=first,
                last_name=last,
                username=uname,
            )
        except Exception:  # noqa: BLE001
            log.exception("profile upsert failed uid=%s", telegram_id)
        return first, last, uname
    cached = await db.get_telegram_profile(telegram_id)
    if cached and (cached.first_name or cached.last_name or cached.username):
        return cached.first_name, cached.last_name, cached.username
    if stored:
        return stored.name, None, stored.username
    return None, None, None


async def _recipients(db: Database, settings: Settings, sender_id: int) -> list[int]:
    return merge_recipient_ids(
        env_admins=settings.admin_ids,
        db_user_ids=await db.enabled_bot_user_ids(),
        sender_id=sender_id,
    )


async def _save_user(
    message: Message,
    db: Database,
    settings: Settings,
    telegram_id: int,
    name: str | None,
    username: str | None,
) -> None:
    menu = _menu(message, settings)
    if telegram_id <= 0:
        await message.answer("Некорректный Telegram ID.", reply_markup=menu)
        return
    if telegram_id == message.from_user.id:
        await message.answer("Себя добавлять не нужно.", reply_markup=menu)
        return
    if telegram_id in settings.admin_ids:
        await message.answer(
            f"<code>{telegram_id}</code> уже админ из .env.",
            reply_markup=menu,
        )
        return
    if await db.get_bot_user(telegram_id):
        await message.answer(
            f"<code>{telegram_id}</code> уже есть в базе.",
            reply_markup=menu,
        )
        return
    user = await db.add_bot_user(
        telegram_id=telegram_id,
        name=name,
        username=username,
        created_by=message.from_user.id,
    )
    await message.answer(
        f"✅ Добавлен <b>{html.escape(user.label)}</b>\n"
        f"ID: <code>{user.telegram_id}</code>\n\n"
        "Пусть откроет бота и нажмёт /start — иначе рассылка до него не дойдёт.",
        reply_markup=menu,
    )


def _parse_new_user(message: Message) -> tuple[int, str | None, str | None] | None:
    if message.forward_from:
        u = message.forward_from
        if u.is_bot:
            return None
        name = " ".join(p for p in (u.first_name, u.last_name) if p) or None
        return u.id, name, u.username
    text = (message.text or "").strip()
    if not text:
        return None
    parts = text.split(maxsplit=1)
    if not parts[0].isdigit():
        return None
    tid = int(parts[0])
    if tid <= 0:
        return None
    name = parts[1].strip() if len(parts) > 1 else None
    return tid, name, None


def _cb_int(call: CallbackQuery) -> int | None:
    try:
        return int(call.data.rsplit(":", 1)[-1])
    except (ValueError, AttributeError):
        return None
