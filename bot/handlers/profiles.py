from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone

import qrcode
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Message,
)

from bot.config import Settings
from bot.db import Database, Profile
from bot.keyboards import confirm_delete, main_menu, profile_actions, profiles_list
from bot.services.awg import AwgError, AwgService

log = logging.getLogger(__name__)
router = Router(name="profiles")

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,32}$")


class NewProfileSG(StatesGroup):
    waiting_name = State()


# ============================================================
# СПИСОК / ПОКАЗ
# ============================================================


@router.message(Command("list"))
@router.message(F.text == "📋 Список")
async def cmd_list(message: Message, db: Database) -> None:
    profiles = await db.list_profiles(created_by=message.from_user.id)
    if not profiles:
        await message.answer("У вас пока нет профилей. Создайте через /new или кнопку.")
        return
    await message.answer(
        f"Ваших профилей: <b>{len(profiles)}</b>\nВыберите для управления:",
        reply_markup=profiles_list(profiles),
    )


@router.callback_query(F.data == "prof:back")
async def cb_back(call: CallbackQuery, db: Database) -> None:
    profiles = await db.list_profiles(created_by=call.from_user.id)
    await call.message.edit_text(
        f"Ваших профилей: <b>{len(profiles)}</b>\nВыберите для управления:",
        reply_markup=profiles_list(profiles),
    )
    await call.answer()


@router.callback_query(F.data.startswith("prof:show:"))
async def cb_show(call: CallbackQuery, db: Database) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    await call.message.edit_text(
        _profile_card(profile),
        reply_markup=profile_actions(profile.id),
    )
    await call.answer()


# ============================================================
# СОЗДАНИЕ
# ============================================================


@router.message(Command("new"))
async def cmd_new(
    message: Message, command: CommandObject, state: FSMContext,
    db: Database, awg: AwgService, settings: Settings,
) -> None:
    name = (command.args or "").strip()
    if not name:
        await state.set_state(NewProfileSG.waiting_name)
        await message.answer(
            "Введите имя профиля (латиница, цифры, _ или -, длина 2–32):"
        )
        return
    await _create(message, name, db, awg, settings)


@router.message(F.text == "➕ Новый профиль")
async def btn_new(message: Message, state: FSMContext) -> None:
    await state.set_state(NewProfileSG.waiting_name)
    await message.answer(
        "Введите имя профиля (латиница, цифры, _ или -, длина 2–32):"
    )


@router.message(NewProfileSG.waiting_name)
async def step_name(
    message: Message, state: FSMContext,
    db: Database, awg: AwgService, settings: Settings,
) -> None:
    await state.clear()
    await _create(message, (message.text or "").strip(), db, awg, settings)


async def _create(
    message: Message, display_name: str,
    db: Database, awg: AwgService, settings: Settings,
) -> None:
    if not NAME_RE.match(display_name):
        await message.answer(
            "❌ Недопустимое имя. Разрешено: латиница, цифры, <code>_</code>, <code>-</code>, длина 2–32.",
        )
        return

    # В БД храним имя с суффиксом telegram-id владельца — это даёт
    # изолированное пространство имён для каждого админа.
    db_name = f"{display_name}_{message.from_user.id}"
    if await db.get_profile_by_name(db_name):
        await message.answer(f"❌ У вас уже есть профиль <b>{display_name}</b>.")
        return

    status_msg = await message.answer(f"⏳ Создаю профиль <b>{display_name}</b>…")
    try:
        server = await awg.server_interface()
        priv, pub = await awg.gen_keypair()
        psk = await awg.gen_psk()
        address = awg.allocate_address(await db.used_addresses())

        await awg.add_peer(public_key=pub, preshared_key=psk, address=address)

        profile = await db.add_profile(
            name=db_name,
            public_key=pub,
            private_key=priv,
            preshared_key=psk,
            address=address,
            created_by=message.from_user.id,
        )
        # Регистрируем в clientsTable, чтобы peer появился в GUI AmneziaVPN.
        # Помечаем владельца, чтобы админу было видно, чей клиент.
        await awg.register_in_clients_table(
            public_key=pub,
            name=f"{display_name} [tg:{message.from_user.id}]",
        )
        client_conf = awg.build_client_config(
            server=server, private_key=priv, preshared_key=psk, address=address,
        )
    except AwgError as exc:
        log.exception("AWG error creating profile")
        await status_msg.edit_text(f"❌ Ошибка AmneziaWG: <code>{exc}</code>")
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("Unexpected error creating profile")
        await status_msg.edit_text(f"❌ Внутренняя ошибка: <code>{exc}</code>")
        return

    await status_msg.edit_text(
        f"✅ Профиль <b>{profile.display_name}</b> создан\n"
        f"IP: <code>{profile.address}</code>"
    )
    await _send_config_and_qr(message, profile, client_conf)
    await message.answer(
        "Готово.",
        reply_markup=main_menu(
            link_button_text=settings.link_button_text if settings.link_url else None,
        ),
    )


# ============================================================
# ВЫДАЧА .conf / QR ИЗ СПИСКА
# ============================================================


@router.callback_query(F.data.startswith("prof:conf:"))
async def cb_conf(call: CallbackQuery, db: Database, awg: AwgService) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    try:
        server = await awg.server_interface()
    except AwgError as exc:
        await call.message.answer(f"❌ {exc}")
        await call.answer()
        return
    conf = awg.build_client_config(
        server=server,
        private_key=profile.private_key,
        preshared_key=profile.preshared_key,
        address=profile.address,
    )
    await call.message.answer_document(
        BufferedInputFile(conf.encode(), filename=f"{profile.name}.conf"),
        caption=f"Конфиг для <b>{profile.name}</b>",
    )
    await call.answer()


@router.callback_query(F.data.startswith("prof:qr:"))
async def cb_qr(call: CallbackQuery, db: Database, awg: AwgService) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    try:
        server = await awg.server_interface()
    except AwgError as exc:
        await call.message.answer(f"❌ {exc}")
        await call.answer()
        return
    conf = awg.build_client_config(
        server=server,
        private_key=profile.private_key,
        preshared_key=profile.preshared_key,
        address=profile.address,
    )
    png = _qr_png(conf)
    await call.message.answer_photo(
        BufferedInputFile(png, filename=f"{profile.name}.png"),
        caption=f"QR для <b>{profile.name}</b>",
    )
    await call.answer()


# ============================================================
# УДАЛЕНИЕ
# ============================================================


@router.callback_query(F.data.startswith("prof:del:"))
async def cb_del_ask(call: CallbackQuery, db: Database) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    await call.message.edit_text(
        f"Удалить профиль <b>{profile.display_name}</b> (<code>{profile.address}</code>)?\n"
        "Это действие нельзя отменить.",
        reply_markup=confirm_delete(profile.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("prof:del_yes:"))
async def cb_del_yes(call: CallbackQuery, db: Database, awg: AwgService) -> None:
    profile = await _get_profile_from_cb(call, db)
    if profile is None:
        return
    try:
        await awg.remove_peer(profile.public_key)
    except AwgError as exc:
        await call.message.answer(f"❌ Ошибка AmneziaWG: <code>{exc}</code>")
        await call.answer()
        return
    await awg.unregister_from_clients_table(profile.public_key)
    await db.delete_profile(profile.id)
    await call.message.edit_text(f"🗑 Профиль <b>{profile.display_name}</b> удалён.")
    await call.answer("Удалено")


# ============================================================
# helpers
# ============================================================


async def _get_profile_from_cb(call: CallbackQuery, db: Database) -> Profile | None:
    """Извлекает профиль из callback'а и проверяет, что вызывающий — его владелец.

    Защита от подмены ID в callback_data: даже если другой админ угадает или
    подделает id, доступ ему не откроется.
    """
    try:
        profile_id = int(call.data.rsplit(":", 1)[-1])
    except (ValueError, AttributeError):
        await call.answer("Некорректный запрос", show_alert=True)
        return None
    profile = await db.get_profile(profile_id)
    if profile is None:
        await call.answer("Профиль не найден", show_alert=True)
        return None
    if profile.created_by != call.from_user.id:
        log.warning(
            "user %s tried to access foreign profile %s (owner=%s)",
            call.from_user.id, profile_id, profile.created_by,
        )
        await call.answer("⛔️ Это не ваш профиль", show_alert=True)
        return None
    return profile


def _profile_card(p: Profile) -> str:
    age = datetime.now(timezone.utc) - p.created_at
    days = age.days
    return (
        f"<b>{p.display_name}</b>\n"
        f"ID: <code>{p.id}</code>\n"
        f"Адрес: <code>{p.address}</code>\n"
        f"PublicKey: <code>{p.public_key}</code>\n"
        f"Создан: {p.created_at:%Y-%m-%d %H:%M UTC} ({days} дн. назад)\n"
        f"Внутреннее имя: <code>{p.name}</code>"
    )


async def _send_config_and_qr(message: Message, profile: Profile, conf: str) -> None:
    await message.answer_document(
        BufferedInputFile(conf.encode(), filename=f"{profile.name}.conf"),
        caption="📄 Сохраните этот .conf",
    )
    await message.answer_photo(
        BufferedInputFile(_qr_png(conf), filename=f"{profile.name}.png"),
        caption="📱 Отсканируйте QR в AmneziaWG-клиенте",
    )


def _qr_png(payload: str) -> bytes:
    img = qrcode.make(payload, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
