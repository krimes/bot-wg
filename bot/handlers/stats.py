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

    # Только профили текущего админа — чужие peer'ы не показываем.
    own_profiles = {
        p.public_key: p
        for p in await db.list_profiles(created_by=message.from_user.id)
    }
    if not own_profiles:
        await message.answer("У вас нет профилей. Создайте через /new.")
        return

    now = int(datetime.now(timezone.utc).timestamp())
    own_peers = [p for p in peers if p.public_key in own_profiles]

    online = 0
    lines: list[str] = []
    for peer in own_peers:
        prof = own_profiles[peer.public_key]
        is_online = peer.latest_handshake and (now - peer.latest_handshake) <= ONLINE_THRESHOLD_SEC
        if is_online:
            online += 1
        marker = "🟢" if is_online else "⚪️"
        hs = _format_handshake(peer.latest_handshake, now)
        lines.append(
            f"{marker} <b>{prof.display_name}</b> · {_fmt_bytes(peer.rx_bytes)} ↓ / "
            f"{_fmt_bytes(peer.tx_bytes)} ↑ · {hs}"
        )

    header = (
        f"📊 <b>Ваша статистика</b>\n"
        f"Ваших профилей: <b>{len(own_profiles)}</b> · "
        f"активно на интерфейсе: <b>{len(own_peers)}</b> · "
        f"онлайн: <b>{online}</b>\n\n"
    )
    body = "\n".join(lines) if lines else "<i>Пока ни одного peer'а на интерфейсе.</i>"
    await message.answer(header + body)


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
