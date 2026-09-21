from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.db import Database
from bot.keyboards import BTN_STATS
from bot.services.awg import AwgError, AwgService, PeerStats
from bot.services.xui import XuiError, XuiService

router = Router(name="stats")

ONLINE_THRESHOLD_SEC = 180  # peer считается онлайн, если handshake был ≤ 3 мин назад


@router.message(Command("stats"))
@router.message(F.text == BTN_STATS)
async def cmd_stats(
    message: Message, db: Database, awg: AwgService, xui: XuiService,
) -> None:
    own_profiles = {
        p.public_key: p
        for p in await db.list_profiles(created_by=message.from_user.id)
    }
    happ_block = await _happ_stats(message.from_user.id, db, xui)
    if not own_profiles and not happ_block:
        await message.answer("У вас нет профилей. Создайте через /new или /happ.")
        return

    parts: list[str] = []
    if own_profiles:
        try:
            peers = await awg.dump()
        except AwgError as exc:
            parts.append(f"📊 <b>AmneziaWG</b>\n❌ <code>{exc}</code>")
        else:
            parts.append(_wg_stats_block(own_profiles, peers))
    if happ_block:
        parts.append(happ_block)
    await message.answer("\n\n".join(parts))


def _wg_stats_block(own_profiles: dict, peers: list[PeerStats]) -> str:
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
        f"📊 <b>AmneziaWG</b>\n"
        f"Профилей: <b>{len(own_profiles)}</b> · "
        f"активно на интерфейсе: <b>{len(own_peers)}</b> · "
        f"онлайн: <b>{online}</b>\n\n"
    )
    body = "\n".join(lines) if lines else "<i>Пока ни одного peer'а на интерфейсе.</i>"
    return header + body


async def _happ_stats(user_id: int, db: Database, xui: XuiService) -> str | None:
    profiles = await db.list_happ_profiles(created_by=user_id)
    if not profiles:
        return None
    if not xui.enabled:
        names = ", ".join(p.display_name for p in profiles)
        return f"📱 <b>Happ</b>\nПрофилей: <b>{len(profiles)}</b> · панель не настроена\n{names}"
    try:
        stats = await xui.traffic_by_emails([p.email for p in profiles])
    except XuiError as exc:
        return f"📱 <b>Happ</b>\nНе удалось получить статистику: <code>{exc}</code>"
    lines = ["📱 <b>Happ</b>"]
    for p in profiles:
        st = stats.get(p.email)
        if st is None:
            lines.append(f"⚪️ <b>{p.display_name}</b> · нет данных")
            continue
        lines.append(
            f"{'🟢' if st.enable else '⚪️'} <b>{p.display_name}</b> · "
            f"{_fmt_bytes(st.down)} ↓ / {_fmt_bytes(st.up)} ↑"
        )
    return "\n".join(lines)


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
