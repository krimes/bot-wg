from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.db import Database
from bot.services.awg import AwgError, AwgService, PeerStats

router = Router(name="stats")

ONLINE_THRESHOLD_SEC = 180  # peer считается онлайн, если handshake был ≤ 3 мин назад


@router.message(Command("stats"))
@router.message(F.text == "📊 Статистика")
async def cmd_stats(message: Message, db: Database, awg: AwgService) -> None:
    try:
        peers = await awg.dump()
    except AwgError as exc:
        await message.answer(f"❌ Не удалось получить статистику: <code>{exc}</code>")
        return

    profiles = {p.public_key: p for p in await db.list_profiles()}
    now = int(datetime.now(timezone.utc).timestamp())

    online = 0
    lines: list[str] = []
    for peer in peers:
        prof = profiles.get(peer.public_key)
        name = prof.name if prof else "(не в БД)"
        is_online = peer.latest_handshake and (now - peer.latest_handshake) <= ONLINE_THRESHOLD_SEC
        if is_online:
            online += 1
        marker = "🟢" if is_online else "⚪️"
        hs = _format_handshake(peer.latest_handshake, now)
        lines.append(
            f"{marker} <b>{name}</b> · {_fmt_bytes(peer.rx_bytes)} ↓ / "
            f"{_fmt_bytes(peer.tx_bytes)} ↑ · {hs}"
        )

    if not lines:
        await message.answer("Нет peer'ов на интерфейсе.")
        return

    header = (
        f"📊 <b>Статистика</b>\n"
        f"Всего peer'ов: <b>{len(peers)}</b> · онлайн: <b>{online}</b>\n\n"
    )
    await message.answer(header + "\n".join(lines))


def _format_handshake(ts: int, now: int) -> str:
    if not ts:
        return "handshake: никогда"
    delta = now - ts
    if delta < 60:
        return f"{delta}s назад"
    if delta < 3600:
        return f"{delta // 60}m назад"
    if delta < 86400:
        return f"{delta // 3600}h назад"
    return f"{delta // 86400}d назад"


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} PiB"
