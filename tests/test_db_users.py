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


@pytest.mark.asyncio
async def test_telegram_profile_upsert(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    await db.init()
    await db.upsert_telegram_profile(
        telegram_id=7, first_name="Иван", last_name="Петров", username="ivan",
    )
    row = await db.get_telegram_profile(7)
    assert row is not None
    assert row.first_name == "Иван"
    assert row.username == "ivan"
    await db.upsert_telegram_profile(
        telegram_id=7, first_name="Ваня", last_name=None, username="vanya",
    )
    row = await db.get_telegram_profile(7)
    assert row.first_name == "Ваня"
    assert row.last_name is None
    assert row.username == "vanya"


@pytest.mark.asyncio
async def test_touch_bot_user_profile(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    await db.init()
    await db.add_bot_user(telegram_id=5, name=None, username=None, created_by=1)
    await db.touch_bot_user_profile(5, name="Иван Петров", username="ivan")
    user = await db.get_bot_user(5)
    assert user is not None
    assert user.name == "Иван Петров"
    assert user.username == "ivan"
