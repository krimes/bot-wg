from __future__ import annotations

from pathlib import Path

import pytest

from bot.db import Database


@pytest.mark.asyncio
async def test_happ_profile_roundtrip(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    await db.init()

    created = await db.add_happ_profile(
        name="phone_42",
        uuid="u-1",
        email="phone_42",
        sub_id="sub1",
        inbound_id=1,
        created_by=42,
    )
    assert created.display_name == "phone"
    assert created.uuid == "u-1"

    listed = await db.list_happ_profiles(created_by=42)
    assert len(listed) == 1
    assert listed[0].email == "phone_42"
    assert await db.list_happ_profiles(created_by=99) == []

    fetched = await db.get_happ_profile(created.id)
    assert fetched is not None and fetched.sub_id == "sub1"
    assert await db.get_happ_profile_by_name("phone_42") is not None

    deleted = await db.delete_happ_profile(created.id)
    assert deleted is not None
    assert await db.get_happ_profile(created.id) is None


@pytest.mark.asyncio
async def test_wg_profiles_still_work_after_happ_schema(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    await db.init()
    wg = await db.add_profile(
        name="home_1",
        public_key="pub",
        private_key="priv",
        preshared_key="psk",
        address="10.8.1.2/32",
        created_by=1,
    )
    assert wg.display_name == "home"
    assert await db.list_happ_profiles() == []
