from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.config import Settings
from bot.db import Database, HappProfile
from bot.keyboards import (
    BTN_NEW_HAPP,
    confirm_delete_happ,
    happ_actions,
    reply_menu,
)
from bot.qrutil import qr_png
from bot.services.xui import XuiError, XuiService

log = logging.getLogger(__name__)
router = Router(name="happ")

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,32}$")


class NewHappSG(StatesGroup):
    waiting_name = State()


@router.message(Command("happ"))
async def cmd_happ(
    message: Message, command: CommandObject, state: FSMContext,
    db: Database, xui: XuiService, settings: Settings,
) -> None:
    if not xui.enabled:
        await message.answer(
            "❌ 3X-UI не настроен. Задайте <code>XUI_HOST</code> и "
            "<code>XUI_INBOUND_ID</code> в .env."
        )
        return
    name = (command.args or "").strip()
    if not name:
        await state.set_state(NewHappSG.waiting_name)
        await message.answer(
            "Введите имя Happ-профиля (латиница, цифры, _ или -, длина 2–32):"
        )
        return
    await _create(message, name, db, xui, settings)


@router.message(F.text == BTN_NEW_HAPP)
async def btn_new_happ(
    message: Message, state: FSMContext, xui: XuiService,
) -> None:
    if not xui.enabled:
        await message.answer(
            "❌ 3X-UI не настроен. Задайте <code>XUI_HOST</code> и "
            "<code>XUI_INBOUND_ID</code> в .env."
        )
        return
    await state.set_state(NewHappSG.waiting_name)
    await message.answer(
        "Введите имя Happ-профиля (латиница, цифры, _ или -, длина 2–32):"
    )


@router.message(NewHappSG.waiting_name)
async def step_name(
    message: Message, state: FSMContext,
    db: Database, xui: XuiService, settings: Settings,
) -> None:
    await state.clear()
    await _create(message, (message.text or "").strip(), db, xui, settings)


async def _create(
    message: Message, display_name: str,
    db: Database, xui: XuiService, settings: Settings,
) -> None:
    if not xui.enabled:
        await message.answer(
            "❌ 3X-UI не настроен. Задайте <code>XUI_HOST</code> в .env."
        )
        return
    if not NAME_RE.match(display_name):
        await message.answer(
            "❌ Недопустимое имя. Разрешено: латиница, цифры, <code>_</code>, "
            "<code>-</code>, длина 2–32.",
        )
        return

    db_name = f"{display_name}_{message.from_user.id}"
    if await db.get_happ_profile_by_name(db_name):
        await message.answer(f"❌ У вас уже есть Happ-профиль <b>{display_name}</b>.")
        return

    status_msg = await message.answer(f"⏳ Создаю Happ-профиль <b>{display_name}</b>…")
    try:
        created = await xui.add_client(
            display_name=display_name,
            telegram_id=message.from_user.id,
        )
        profile = await db.add_happ_profile(
            name=db_name,
            uuid=created.uuid,
            email=created.email,
            sub_id=created.sub_id,
            inbound_id=created.inbound_id,
            created_by=message.from_user.id,
        )
    except XuiError as exc:
        log.exception("3X-UI error creating happ profile")
        await status_msg.edit_text(f"❌ Ошибка 3X-UI: <code>{html.escape(str(exc))}</code>")
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("Unexpected error creating happ profile")
        await status_msg.edit_text(f"❌ Внутренняя ошибка: <code>{html.escape(str(exc))}</code>")
        return

    await status_msg.edit_text(f"✅ Happ-профиль <b>{profile.display_name}</b> создан")
    await _send_link_and_qr(message, profile, created.vless_link, created.subscription_url)
    await message.answer(
        "Готово. Импортируйте ключ или QR в Happ.",
        reply_markup=reply_menu(settings, message.from_user.id),
    )


@router.callback_query(F.data.startswith("happ:show:"))
async def cb_show(call: CallbackQuery, db: Database) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    await call.message.edit_text(
        _happ_card(profile),
        reply_markup=happ_actions(profile.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("happ:link:"))
async def cb_link(call: CallbackQuery, db: Database, xui: XuiService) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    try:
        link = await xui.rebuild_link(
            uuid=profile.uuid,
            inbound_id=profile.inbound_id,
            remark=profile.display_name,
        )
    except XuiError as exc:
        await call.message.answer(f"❌ {exc}")
        await call.answer()
        return
    sub = _sub_line(xui, profile)
    await call.message.answer(
        f"🔑 <b>{profile.display_name}</b>\n<code>{html.escape(link)}</code>{sub}"
    )
    await call.answer()


@router.callback_query(F.data.startswith("happ:qr:"))
async def cb_qr(call: CallbackQuery, db: Database, xui: XuiService) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    try:
        link = await xui.rebuild_link(
            uuid=profile.uuid,
            inbound_id=profile.inbound_id,
            remark=profile.display_name,
        )
    except XuiError as exc:
        await call.message.answer(f"❌ {exc}")
        await call.answer()
        return
    await call.message.answer_photo(
        BufferedInputFile(qr_png(link), filename=f"{profile.name}.png"),
        caption=f"📱 QR для Happ · <b>{profile.display_name}</b>",
    )
    await call.answer()


@router.callback_query(F.data.startswith("happ:del:"))
async def cb_del_ask(call: CallbackQuery, db: Database) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    await call.message.edit_text(
        f"Удалить Happ-профиль <b>{profile.display_name}</b>?\n"
        "Клиент будет снят с 3X-UI. Это нельзя отменить.",
        reply_markup=confirm_delete_happ(profile.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("happ:del_yes:"))
async def cb_del_yes(
    call: CallbackQuery, db: Database, xui: XuiService,
) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    try:
        await xui.delete_client(inbound_id=profile.inbound_id, uuid=profile.uuid)
    except XuiError as exc:
        await call.message.answer(f"❌ Ошибка 3X-UI: <code>{html.escape(str(exc))}</code>")
        await call.answer()
        return
    await db.delete_happ_profile(profile.id)
    await call.message.edit_text(f"🗑 Happ-профиль <b>{profile.display_name}</b> удалён.")
    await call.answer("Удалено")


async def _get_profile_from_cb(call: CallbackQuery, db: Database) -> HappProfile | None:
    try:
        profile_id = int(call.data.rsplit(":", 1)[-1])
    except (ValueError, AttributeError):
        await call.answer("Некорректный запрос", show_alert=True)
        return None
    profile = await db.get_happ_profile(profile_id)
    if profile is None:
        await call.answer("Профиль не найден", show_alert=True)
        return None
    if profile.created_by != call.from_user.id:
        log.warning(
            "user %s tried to access foreign happ profile %s (owner=%s)",
            call.from_user.id, profile_id, profile.created_by,
        )
        await call.answer("⛔️ Это не ваш профиль", show_alert=True)
        return None
    return profile


def _happ_card(p: HappProfile) -> str:
    age = datetime.now(timezone.utc) - p.created_at
    return (
        f"<b>Happ · {p.display_name}</b>\n"
        f"ID: <code>{p.id}</code>\n"
        f"Email: <code>{p.email}</code>\n"
        f"UUID: <code>{p.uuid}</code>\n"
        f"Inbound: <code>{p.inbound_id}</code>\n"
        f"Создан: {p.created_at:%Y-%m-%d %H:%M UTC} ({age.days} дн. назад)"
    )


def _sub_line(xui: XuiService, profile: HappProfile) -> str:
    url = xui.subscription_for(profile.sub_id)
    if not url:
        return ""
    return f"\n\nПодписка:\n<code>{html.escape(url)}</code>"


async def _send_link_and_qr(
    message: Message,
    profile: HappProfile,
    link: str,
    sub_url: str | None,
) -> None:
    extra = f"\n\nПодписка:\n<code>{html.escape(sub_url)}</code>" if sub_url else ""
    await message.answer(
        f"🔑 Ключ для Happ (<b>{profile.display_name}</b>):\n"
        f"<code>{html.escape(link)}</code>{extra}"
    )
    await message.answer_photo(
        BufferedInputFile(qr_png(link), filename=f"{profile.name}.png"),
        caption="📱 Отсканируйте QR в Happ",
    )
