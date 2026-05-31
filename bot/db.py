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
        suffix = f"_{self.created_by}"
        return self.name[: -len(suffix)] if self.name.endswith(suffix) else self.name


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
