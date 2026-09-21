from __future__ import annotations

from pathlib import Path

import pytest

from bot.db import Database
from bot.services.awg import ServerInterface
from bot.services.wg_issue import IssueError, issue_first_web_wg, is_allowed_web_user


class FakeAwg:
    def __init__(self) -> None:
        self.peers: list[str] = []

    async def server_interface(self) -> ServerInterface:
        return ServerInterface(public_key="SPUB", listen_port=51820, obfuscation={"Jc": "3"})

    async def gen_keypair(self) -> tuple[str, str]:
        n = len(self.peers) + 1
        return f"PRIV{n}", f"PUB{n}"

    async def gen_psk(self) -> str:
        return "PSK"

    def allocate_address(self, used: set[str]) -> str:
        return "10.8.1.2/32" if "10.8.1.2/32" not in used else "10.8.1.3/32"

    async def add_peer(self, *, public_key: str, preshared_key: str, address: str) -> None:
        self.peers.append(public_key)

    async def register_in_clients_table(self, *, public_key: str, name: str) -> None:
        return None

    def build_client_config(self, **kwargs) -> str:
        return "[Interface]\nPrivateKey = x\n"


@pytest.mark.asyncio
async def test_unknown_telegram_id_rejected(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    await db.init()
    assert await is_allowed_web_user(99, [1], db) is False
    with pytest.raises(IssueError, match="допущенных"):
        await issue_first_web_wg(
            db=db, awg=FakeAwg(), admin_ids=[1], telegram_id=99, display_name="phone",
        )


@pytest.mark.asyncio
async def test_disabled_db_user_rejected(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    await db.init()
    await db.add_bot_user(telegram_id=5, name="A", username=None, created_by=1)
    await db.set_bot_user_enabled(5, False)
    assert await is_allowed_web_user(5, [1], db) is False


@pytest.mark.asyncio
async def test_first_issue_ok_second_fails(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    await db.init()
    awg = FakeAwg()
    first = await issue_first_web_wg(
        db=db, awg=awg, admin_ids=[42], telegram_id=42, display_name="phone",
    )
    assert first.display_name == "phone"
    assert "PrivateKey" in first.conf
    assert len(awg.peers) == 1
    with pytest.raises(IssueError, match="уже выдавался"):
        await issue_first_web_wg(
            db=db, awg=awg, admin_ids=[42], telegram_id=42, display_name="laptop",
        )


@pytest.mark.asyncio
async def test_bad_name_rejected(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    await db.init()
    with pytest.raises(IssueError, match="Имя"):
        await issue_first_web_wg(
            db=db, awg=FakeAwg(), admin_ids=[1], telegram_id=1, display_name="мой телефон",
        )
