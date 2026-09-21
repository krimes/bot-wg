from __future__ import annotations

from pathlib import Path

import pytest

from bot.db import Database


@pytest.mark.asyncio
async def test_bot_user_roundtrip(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    await db.init()

    created = await db.add_bot_user(
        telegram_id=100,
        name="Alice",
        username="alice",
        created_by=1,
    )
    assert created.enabled is True
    assert created.telegram_id == 100

    fetched = await db.get_bot_user(100)
    assert fetched is not None and fetched.name == "Alice"
    listed = await db.list_bot_users()
    assert len(listed) == 1

    await db.set_bot_user_enabled(100, False)
    assert (await db.get_bot_user(100)).enabled is False

    deleted = await db.delete_bot_user(100)
    assert deleted is not None
    assert await db.get_bot_user(100) is None


@pytest.mark.asyncio
async def test_enabled_user_ids_skips_disabled(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    await db.init()
    await db.add_bot_user(telegram_id=1, name="a", username=None, created_by=9)
    await db.add_bot_user(telegram_id=2, name="b", username=None, created_by=9)
    await db.set_bot_user_enabled(2, False)
    assert await db.enabled_bot_user_ids() == [1]
