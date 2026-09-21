"""Выдача клиентского AmneziaWG: общая логика для бота и веб-формы."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from bot.db import Database, Profile
from bot.services.awg import AwgError, AwgService

log = logging.getLogger(__name__)

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,32}$")


class IssueError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(slots=True)
class IssuedWg:
    profile: Profile
    conf: str
    display_name: str


async def is_allowed_web_user(
    telegram_id: int, admin_ids: list[int], db: Database,
) -> bool:
    if telegram_id in admin_ids:
        return True
    rec = await db.get_bot_user(telegram_id)
    return rec is not None and rec.enabled


async def create_wg_profile(
    *,
    db: Database,
    awg: AwgService,
    telegram_id: int,
    display_name: str,
) -> IssuedWg:
    if not NAME_RE.match(display_name):
        raise IssueError(
            "Имя подключения: латиница, цифры, _ или -, длина 2–32."
        )
    db_name = f"{display_name}_{telegram_id}"
    if await db.get_profile_by_name(db_name):
        raise IssueError(f"Профиль «{display_name}» уже существует.")

    server = await awg.server_interface()
    priv, pub = await awg.gen_keypair()
    psk = await awg.gen_psk()
    address = awg.allocate_address(await db.used_addresses())
    await awg.add_peer(public_key=pub, preshared_key=psk, address=address)
    try:
        profile = await db.add_profile(
            name=db_name,
            public_key=pub,
            private_key=priv,
            preshared_key=psk,
            address=address,
            created_by=telegram_id,
        )
    except Exception:
        log.exception("db add_profile failed, removing peer")
        try:
            await awg.remove_peer(pub)
        except AwgError:
            log.exception("peer rollback failed")
        raise
    await awg.register_in_clients_table(
        public_key=pub,
        name=f"{display_name} [tg:{telegram_id}]",
    )
    conf = awg.build_client_config(
        server=server, private_key=priv, preshared_key=psk, address=address,
    )
    return IssuedWg(profile=profile, conf=conf, display_name=display_name)


async def issue_first_web_wg(
    *,
    db: Database,
    awg: AwgService,
    admin_ids: list[int],
    telegram_id: int,
    display_name: str,
) -> IssuedWg:
    if not await is_allowed_web_user(telegram_id, admin_ids, db):
        raise IssueError("Этого человека нет в списке допущенных.")
    existing = await db.list_profiles(created_by=telegram_id)
    if existing:
        raise IssueError(
            "Конфиг уже выдавался этому пользователю. "
            "Повторная генерация через сайт запрещена."
        )
    return await create_wg_profile(
        db=db, awg=awg, telegram_id=telegram_id, display_name=display_name,
    )
