from __future__ import annotations

from pathlib import Path

import pytest

from bot.db import Database


@pytest.mark.asyncio
async def test_xray_profile_roundtrip(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    await db.init()

    created = await db.add_xray_profile(
        name="phone_42",
        uuid="u-1",
        email="phone_42",
        created_by=42,
    )
    assert created.display_name == "phone"
    listed = await db.list_xray_profiles(created_by=42)
    assert [row.uuid for row in listed] == ["u-1"]
    assert await db.list_xray_profiles(created_by=99) == []
    assert await db.get_xray_profile_by_name("phone_42") is not None

    deleted = await db.delete_xray_profile(created.id)
    assert deleted is not None
    assert await db.get_xray_profile(created.id) is None
