from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    public_key      TEXT    NOT NULL UNIQUE,
    private_key     TEXT    NOT NULL,
    preshared_key   TEXT    NOT NULL,
    address         TEXT    NOT NULL UNIQUE,
    created_at      TEXT    NOT NULL,
    created_by      INTEGER NOT NULL,
    note            TEXT
);

CREATE INDEX IF NOT EXISTS idx_profiles_created_by ON profiles(created_by);

CREATE TABLE IF NOT EXISTS happ_profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    uuid            TEXT    NOT NULL UNIQUE,
    email           TEXT    NOT NULL UNIQUE,
    sub_id          TEXT    NOT NULL,
    inbound_id      INTEGER NOT NULL,
    created_at      TEXT    NOT NULL,
    created_by      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_happ_profiles_created_by ON happ_profiles(created_by);

CREATE TABLE IF NOT EXISTS bot_users (
    telegram_id     INTEGER PRIMARY KEY,
    name            TEXT,
    username        TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL,
    created_by      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS telegram_profiles (
    telegram_id     INTEGER PRIMARY KEY,
    first_name      TEXT,
    last_name       TEXT,
    username        TEXT,
    updated_at      TEXT    NOT NULL
);
"""


@dataclass(slots=True)
class Profile:
    id: int
    name: str
    public_key: str
    private_key: str
    preshared_key: str
    address: str
    created_at: datetime
    created_by: int
    note: str | None = None

    @property
    def display_name(self) -> str:
        """Имя профиля без суффикса _<telegram_id>, как видит его пользователь."""
        return _display_name(self.name, self.created_by)


@dataclass(slots=True)
class HappProfile:
    id: int
    name: str
    uuid: str
    email: str
    sub_id: str
    inbound_id: int
    created_at: datetime
    created_by: int

    @property
    def display_name(self) -> str:
        return _display_name(self.name, self.created_by)


def _display_name(name: str, created_by: int) -> str:
    suffix = f"_{created_by}"
    return name[: -len(suffix)] if name.endswith(suffix) else name


@dataclass(slots=True)
class BotUser:
    telegram_id: int
    name: str | None
    username: str | None
    enabled: bool
    created_at: datetime
    created_by: int

    @property
    def label(self) -> str:
        if self.name:
            return self.name
        if self.username:
            return f"@{self.username}"
        return str(self.telegram_id)


@dataclass(slots=True)
class TelegramProfile:
    telegram_id: int
    first_name: str | None
    last_name: str | None
    username: str | None
    updated_at: datetime


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._path) as conn:
            await conn.executescript(SCHEMA)
            await conn.commit()

    async def add_profile(
        self,
        *,
        name: str,
        public_key: str,
        private_key: str,
        preshared_key: str,
        address: str,
        created_by: int,
        note: str | None = None,
    ) -> Profile:
        created_at = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._path) as conn:
            cur = await conn.execute(
                """
                INSERT INTO profiles
                    (name, public_key, private_key, preshared_key, address, created_at, created_by, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, public_key, private_key, preshared_key, address, created_at, created_by, note),
            )
            await conn.commit()
            profile_id = cur.lastrowid
        assert profile_id is not None
        return Profile(
            id=profile_id,
            name=name,
            public_key=public_key,
            private_key=private_key,
            preshared_key=preshared_key,
            address=address,
            created_at=datetime.fromisoformat(created_at),
            created_by=created_by,
            note=note,
        )

    async def list_profiles(self, created_by: int | None = None) -> list[Profile]:
        sql = "SELECT * FROM profiles"
        params: tuple = ()
        if created_by is not None:
            sql += " WHERE created_by = ?"
            params = (created_by,)
        sql += " ORDER BY id"
        async with aiosqlite.connect(self._path) as conn:
            conn.row_factory = aiosqlite.Row
            rows = await conn.execute_fetchall(sql, params)
        return [_row_to_profile(row) for row in rows]

    async def get_profile(self, profile_id: int) -> Profile | None:
        async with aiosqlite.connect(self._path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await (await conn.execute(
                "SELECT * FROM profiles WHERE id = ?", (profile_id,)
            )).fetchone()
        return _row_to_profile(row) if row else None

    async def get_profile_by_name(self, name: str) -> Profile | None:
        async with aiosqlite.connect(self._path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await (await conn.execute(
                "SELECT * FROM profiles WHERE name = ?", (name,)
            )).fetchone()
        return _row_to_profile(row) if row else None

    async def used_addresses(self) -> set[str]:
        async with aiosqlite.connect(self._path) as conn:
            rows = await conn.execute_fetchall("SELECT address FROM profiles")
        return {row[0] for row in rows}

    async def delete_profile(self, profile_id: int) -> Profile | None:
        profile = await self.get_profile(profile_id)
        if profile is None:
            return None
        async with aiosqlite.connect(self._path) as conn:
            await conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
            await conn.commit()
        return profile

    async def add_happ_profile(
        self,
        *,
        name: str,
        uuid: str,
        email: str,
        sub_id: str,
        inbound_id: int,
        created_by: int,
    ) -> HappProfile:
        created_at = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._path) as conn:
            cur = await conn.execute(
                """
                INSERT INTO happ_profiles
                    (name, uuid, email, sub_id, inbound_id, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, uuid, email, sub_id, inbound_id, created_at, created_by),
            )
            await conn.commit()
            profile_id = cur.lastrowid
        assert profile_id is not None
        return HappProfile(
            id=profile_id,
            name=name,
            uuid=uuid,
            email=email,
            sub_id=sub_id,
            inbound_id=inbound_id,
            created_at=datetime.fromisoformat(created_at),
            created_by=created_by,
        )

    async def list_happ_profiles(self, created_by: int | None = None) -> list[HappProfile]:
        sql = "SELECT * FROM happ_profiles"
        params: tuple = ()
        if created_by is not None:
            sql += " WHERE created_by = ?"
            params = (created_by,)
        sql += " ORDER BY id"
        async with aiosqlite.connect(self._path) as conn:
            conn.row_factory = aiosqlite.Row
            rows = await conn.execute_fetchall(sql, params)
        return [_row_to_happ(row) for row in rows]

    async def get_happ_profile(self, profile_id: int) -> HappProfile | None:
        async with aiosqlite.connect(self._path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await (await conn.execute(
                "SELECT * FROM happ_profiles WHERE id = ?", (profile_id,)
            )).fetchone()
        return _row_to_happ(row) if row else None

    async def get_happ_profile_by_name(self, name: str) -> HappProfile | None:
        async with aiosqlite.connect(self._path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await (await conn.execute(
                "SELECT * FROM happ_profiles WHERE name = ?", (name,)
            )).fetchone()
        return _row_to_happ(row) if row else None

    async def delete_happ_profile(self, profile_id: int) -> HappProfile | None:
        profile = await self.get_happ_profile(profile_id)
        if profile is None:
            return None
        async with aiosqlite.connect(self._path) as conn:
            await conn.execute("DELETE FROM happ_profiles WHERE id = ?", (profile_id,))
            await conn.commit()
        return profile

    async def add_bot_user(
        self,
        *,
        telegram_id: int,
        name: str | None,
        username: str | None,
        created_by: int,
        enabled: bool = True,
    ) -> BotUser:
        created_at = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._path) as conn:
            await conn.execute(
                """
                INSERT INTO bot_users
                    (telegram_id, name, username, enabled, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (telegram_id, name, username, int(enabled), created_at, created_by),
            )
            await conn.commit()
        return BotUser(
            telegram_id=telegram_id,
            name=name,
            username=username,
            enabled=enabled,
            created_at=datetime.fromisoformat(created_at),
            created_by=created_by,
        )

    async def get_bot_user(self, telegram_id: int) -> BotUser | None:
        async with aiosqlite.connect(self._path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await (await conn.execute(
                "SELECT * FROM bot_users WHERE telegram_id = ?", (telegram_id,)
            )).fetchone()
        return _row_to_bot_user(row) if row else None

    async def list_bot_users(self) -> list[BotUser]:
        async with aiosqlite.connect(self._path) as conn:
            conn.row_factory = aiosqlite.Row
            rows = await conn.execute_fetchall(
                "SELECT * FROM bot_users ORDER BY created_at"
            )
        return [_row_to_bot_user(row) for row in rows]

    async def enabled_bot_user_ids(self) -> list[int]:
        async with aiosqlite.connect(self._path) as conn:
            rows = await conn.execute_fetchall(
                "SELECT telegram_id FROM bot_users WHERE enabled = 1"
            )
        return [row[0] for row in rows]

    async def set_bot_user_enabled(self, telegram_id: int, enabled: bool) -> BotUser | None:
        user = await self.get_bot_user(telegram_id)
        if user is None:
            return None
        async with aiosqlite.connect(self._path) as conn:
            await conn.execute(
                "UPDATE bot_users SET enabled = ? WHERE telegram_id = ?",
                (int(enabled), telegram_id),
            )
            await conn.commit()
        return await self.get_bot_user(telegram_id)

    async def touch_bot_user_profile(
        self,
        telegram_id: int,
        *,
        name: str | None,
        username: str | None,
    ) -> None:
        async with aiosqlite.connect(self._path) as conn:
            await conn.execute(
                "UPDATE bot_users SET name = ?, username = ? WHERE telegram_id = ?",
                (name, username, telegram_id),
            )
            await conn.commit()

    async def upsert_telegram_profile(
        self,
        *,
        telegram_id: int,
        first_name: str | None,
        last_name: str | None,
        username: str | None,
    ) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._path) as conn:
            await conn.execute(
                """
                INSERT INTO telegram_profiles
                    (telegram_id, first_name, last_name, username, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    username = excluded.username,
                    updated_at = excluded.updated_at
                """,
                (telegram_id, first_name, last_name, username, updated_at),
            )
            await conn.commit()

    async def get_telegram_profile(self, telegram_id: int) -> TelegramProfile | None:
        async with aiosqlite.connect(self._path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await (await conn.execute(
                "SELECT * FROM telegram_profiles WHERE telegram_id = ?",
                (telegram_id,),
            )).fetchone()
        return _row_to_tg_profile(row) if row else None

    async def delete_bot_user(self, telegram_id: int) -> BotUser | None:
        user = await self.get_bot_user(telegram_id)
        if user is None:
            return None
        async with aiosqlite.connect(self._path) as conn:
            await conn.execute(
                "DELETE FROM bot_users WHERE telegram_id = ?", (telegram_id,)
            )
            await conn.commit()
        return user


def _row_to_profile(row: aiosqlite.Row) -> Profile:
    return Profile(
        id=row["id"],
        name=row["name"],
        public_key=row["public_key"],
        private_key=row["private_key"],
        preshared_key=row["preshared_key"],
        address=row["address"],
        created_at=datetime.fromisoformat(row["created_at"]),
        created_by=row["created_by"],
        note=row["note"],
    )


def _row_to_happ(row: aiosqlite.Row) -> HappProfile:
    return HappProfile(
        id=row["id"],
        name=row["name"],
        uuid=row["uuid"],
        email=row["email"],
        sub_id=row["sub_id"],
        inbound_id=row["inbound_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        created_by=row["created_by"],
    )


def _row_to_bot_user(row: aiosqlite.Row) -> BotUser:
    return BotUser(
        telegram_id=row["telegram_id"],
        name=row["name"],
        username=row["username"],
        enabled=bool(row["enabled"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        created_by=row["created_by"],
    )


def _row_to_tg_profile(row: aiosqlite.Row) -> TelegramProfile:
    return TelegramProfile(
        telegram_id=row["telegram_id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        username=row["username"],
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
