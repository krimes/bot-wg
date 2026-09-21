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
