from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.config import Settings
from bot.db import Database, XrayProfile
from bot.filters import NotMenuButton
from bot.keyboards import (
    BTN_NEW_XRAY,
    confirm_delete_xray,
    reply_menu,
    xray_actions,
)
from bot.qrutil import qr_png
from bot.services.xray import XrayError, XrayService
from bot.services.xui import happ_email

log = logging.getLogger(__name__)
router = Router(name="xray")

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,32}$")
_ASK_NAME = (
    "🛰 <b>Xray</b>\n"
    "Введите имя профиля (латиница, цифры, <code>_</code> или <code>-</code>, 2–32):"
)


class NewXraySG(StatesGroup):
    waiting_name = State()


def public_host(settings: Settings) -> str:
    return (settings.xui_client_host or settings.awg_endpoint_host or "").strip()


@router.message(Command("xray"))
async def cmd_xray(
    message: Message, command: CommandObject, state: FSMContext,
    db: Database, xray: XrayService, settings: Settings,
) -> None:
    if not xray.enabled:
        await message.answer("❌ Xray недоступен: <code>XRAY_CONTAINER</code> пуст.")
        return
    name = (command.args or "").strip()
    if not name:
        await state.set_state(NewXraySG.waiting_name)
        await message.answer(_ASK_NAME)
        return
    await _create(message, name, db, xray, settings)


@router.message(F.text == BTN_NEW_XRAY)
async def btn_new_xray(message: Message, state: FSMContext, xray: XrayService) -> None:
    if not xray.enabled:
        await message.answer("❌ Xray недоступен: <code>XRAY_CONTAINER</code> пуст.")
        return
    await state.set_state(NewXraySG.waiting_name)
    await message.answer(_ASK_NAME)


@router.callback_query(F.data == "new:xray")
async def cb_new_xray(
    call: CallbackQuery, state: FSMContext, xray: XrayService,
) -> None:
    if not xray.enabled:
        await call.message.edit_text("❌ Xray недоступен: <code>XRAY_CONTAINER</code> пуст.")
        await call.answer("Xray не настроен", show_alert=True)
        return
    await state.set_state(NewXraySG.waiting_name)
    await call.message.edit_text(_ASK_NAME)
    await call.answer()


@router.message(NewXraySG.waiting_name, NotMenuButton())
async def step_name(
    message: Message, state: FSMContext,
    db: Database, xray: XrayService, settings: Settings,
) -> None:
    await state.clear()
    await _create(message, (message.text or "").strip(), db, xray, settings)


async def _create(
    message: Message, display_name: str,
    db: Database, xray: XrayService, settings: Settings,
) -> None:
    if not xray.enabled:
        await message.answer("❌ Xray недоступен: <code>XRAY_CONTAINER</code> пуст.")
        return
    if not NAME_RE.match(display_name):
        await message.answer(
            "❌ Недопустимое имя. Разрешено: латиница, цифры, <code>_</code>, "
            "<code>-</code>, длина 2–32.",
        )
        return

    db_name = f"{display_name}_{message.from_user.id}"
    if await db.get_xray_profile_by_name(db_name):
        await message.answer(f"❌ У вас уже есть Xray-профиль <b>{display_name}</b>.")
        return

    status_msg = await message.answer(f"⏳ Создаю Xray-профиль <b>{display_name}</b>…")
    client_id = str(uuid4())
    email = happ_email(display_name, message.from_user.id)
    try:
        link = await xray.add_client(
            client_id=client_id,
            email=email,
            host=public_host(settings),
            remark=display_name,
        )
    except XrayError as exc:
        log.exception("error creating xray profile")
        await status_msg.edit_text(f"❌ Ошибка Xray: <code>{html.escape(str(exc))}</code>")
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("Unexpected error creating xray profile")
        await status_msg.edit_text(f"❌ Внутренняя ошибка: <code>{html.escape(str(exc))}</code>")
        return

    try:
        profile = await db.add_xray_profile(
            name=db_name,
            uuid=client_id,
            email=email,
            created_by=message.from_user.id,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("db insert failed after xray client was added")
        rolled_back = await _try_remove(xray, client_id)
        note = "Клиент с сервера снят." if rolled_back else "Клиент мог остаться в server.json."
        await status_msg.edit_text(
            f"❌ Не записал профиль в базу: <code>{html.escape(str(exc))}</code>\n{note}"
        )
        return

    await status_msg.edit_text(f"✅ Xray-профиль <b>{profile.display_name}</b> создан")
    await _send_link_and_qr(message, profile, link)
    await message.answer(
        "Готово. Импортируйте ключ или QR в Happ или другой Xray-клиент.",
        reply_markup=reply_menu(settings, message.from_user.id),
    )


@router.callback_query(F.data.startswith("xray:show:"))
async def cb_show(call: CallbackQuery, db: Database) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    await call.message.edit_text(
        _xray_card(profile),
        reply_markup=xray_actions(profile.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("xray:link:"))
async def cb_link(
    call: CallbackQuery, db: Database, xray: XrayService, settings: Settings,
) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    try:
        link = await xray.client_link(
            client_id=profile.uuid,
            host=public_host(settings),
            remark=profile.display_name,
        )
    except XrayError as exc:
        await call.message.answer(f"❌ {html.escape(str(exc))}")
        await call.answer()
        return
    await call.message.answer(
        f"🔑 <b>{profile.display_name}</b>\n<code>{html.escape(link)}</code>"
    )
    await call.answer()


@router.callback_query(F.data.startswith("xray:qr:"))
async def cb_qr(
    call: CallbackQuery, db: Database, xray: XrayService, settings: Settings,
) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    try:
        link = await xray.client_link(
            client_id=profile.uuid,
            host=public_host(settings),
            remark=profile.display_name,
        )
    except XrayError as exc:
        await call.message.answer(f"❌ {html.escape(str(exc))}")
        await call.answer()
        return
    await call.message.answer_photo(
        BufferedInputFile(qr_png(link), filename=f"{profile.name}.png"),
        caption=f"📱 QR для Xray · <b>{profile.display_name}</b>",
    )
    await call.answer()


@router.callback_query(F.data.startswith("xray:del:"))
async def cb_del_ask(call: CallbackQuery, db: Database) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    await call.message.edit_text(
        f"Удалить Xray-профиль <b>{profile.display_name}</b>?\n"
        "UUID будет снят с Amnezia Xray, контейнер перезапустится.",
        reply_markup=confirm_delete_xray(profile.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("xray:del_yes:"))
async def cb_del_yes(call: CallbackQuery, db: Database, xray: XrayService) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    try:
        await xray.remove_client(profile.uuid)
    except XrayError as exc:
        await call.message.answer(f"❌ Ошибка Xray: <code>{html.escape(str(exc))}</code>")
        await call.answer()
        return
    await db.delete_xray_profile(profile.id)
    await call.message.edit_text(f"🗑 Xray-профиль <b>{profile.display_name}</b> удалён.")
    await call.answer("Удалено")


async def _get_profile_from_cb(call: CallbackQuery, db: Database) -> XrayProfile | None:
    try:
        profile_id = int(call.data.rsplit(":", 1)[-1])
    except (ValueError, AttributeError):
        await call.answer("Некорректный запрос", show_alert=True)
        return None
    profile = await db.get_xray_profile(profile_id)
    if profile is None:
        await call.answer("Профиль не найден", show_alert=True)
        return None
    if profile.created_by != call.from_user.id:
        log.warning(
            "user %s tried to access foreign xray profile %s (owner=%s)",
            call.from_user.id, profile_id, profile.created_by,
        )
        await call.answer("⛔️ Это не ваш профиль", show_alert=True)
        return None
    return profile


def _xray_card(p: XrayProfile) -> str:
    age = datetime.now(timezone.utc) - p.created_at
    return (
        f"<b>Xray · {p.display_name}</b>\n"
        f"ID: <code>{p.id}</code>\n"
        f"Email: <code>{p.email}</code>\n"
        f"UUID: <code>{p.uuid}</code>\n"
        f"Создан: {p.created_at:%Y-%m-%d %H:%M UTC} ({age.days} дн. назад)"
    )


async def _send_link_and_qr(message: Message, profile: XrayProfile, link: str) -> None:
    await message.answer(
        f"🔑 Ключ Xray (<b>{profile.display_name}</b>):\n"
        f"<code>{html.escape(link)}</code>"
    )
    await message.answer_photo(
        BufferedInputFile(qr_png(link), filename=f"{profile.name}.png"),
        caption="📱 Отсканируйте QR в Xray-клиенте",
    )


async def _try_remove(xray: XrayService, client_id: str) -> bool:
    try:
        await xray.remove_client(client_id)
    except XrayError:
        log.exception("не удалось снять uuid %s после ошибки базы", client_id)
        return False
    return True
