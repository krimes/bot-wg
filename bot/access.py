"""Роли и получатели рассылки — без зависимостей от aiogram/pydantic."""

from __future__ import annotations


def resolve_main_admin_id(admin_ids: list[int], override: int | None) -> int | None:
    if override:
        return override
    return admin_ids[0] if admin_ids else None


def is_main_admin(
    user_id: int, admin_ids: list[int], override: int | None,
) -> bool:
    mid = resolve_main_admin_id(admin_ids, override)
    return mid is not None and user_id == mid


def format_person_label(
    *,
    first_name: str | None,
    last_name: str | None,
    username: str | None,
    telegram_id: int,
) -> str:
    fio = " ".join(p for p in (first_name, last_name) if p) or None
    nick = f"@{username}" if username else None
    parts = [p for p in (fio, nick) if p]
    return " · ".join(parts) if parts else str(telegram_id)


def listed_telegram_ids(admin_ids: list[int], db_user_ids: list[int]) -> list[int]:
    """ADMIN_IDS, затем включённые пользователи БД без дублей."""
    seen: set[int] = set()
    out: list[int] = []
    for uid in [*admin_ids, *db_user_ids]:
        if uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out


def merge_recipient_ids(
    *,
    env_admins: list[int],
    db_user_ids: list[int],
    sender_id: int,
) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for uid in [*env_admins, *db_user_ids]:
        if uid == sender_id or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out
