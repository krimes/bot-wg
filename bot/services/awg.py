"""Обёртка над AmneziaWG, развёрнутым в Docker-контейнере.

Все операции выполняются через ``docker exec`` в контейнер ``AWG_CONTAINER``.
Используем awg-utils (форк wg-tools от Amnezia): команды ``awg``, ``awg-quick``.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone

from bot.config import Settings

log = logging.getLogger(__name__)


class AwgError(RuntimeError):
    pass


@dataclass(slots=True)
class ServerInterface:
    """[Interface]-секция серверного конфига, нужная для клиентского peer."""

    public_key: str
    listen_port: int
    # AmneziaWG-обфускация. Если их нет — это обычный WireGuard.
    obfuscation: dict[str, str]


@dataclass(slots=True)
class PeerStats:
    public_key: str
    endpoint: str | None
    allowed_ips: str
    latest_handshake: int  # unix ts, 0 если не было
    rx_bytes: int
    tx_bytes: int


# Параметры обфускации AmneziaWG, которые нужно переносить из server -> client.
OBFUSCATION_KEYS = ("Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4")


class AwgService:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    # ---------- docker exec ----------

    async def _exec(self, *argv: str, input_: str | None = None) -> str:
        """Запускает команду внутри контейнера AmneziaWG, возвращает stdout."""
        cmd = ["docker", "exec", "-i", self._s.awg_container, *argv]
        log.debug("exec: %s", " ".join(shlex.quote(a) for a in cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if input_ is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input_.encode() if input_ else None)
        if proc.returncode != 0:
            raise AwgError(
                f"{' '.join(argv)} exited with {proc.returncode}: "
                f"{stderr.decode(errors='replace').strip()}"
            )
        return stdout.decode()

    async def _sh(self, script: str) -> str:
        """Запускает шелл-скрипт внутри контейнера (нужен пайп между awg и awg pubkey)."""
        return await self._exec("sh", "-c", script)

    # ---------- ключи ----------

    async def gen_keypair(self) -> tuple[str, str]:
        """Возвращает (private_key, public_key)."""
        priv = (await self._exec("awg", "genkey")).strip()
        pub = (await self._exec("awg", "pubkey", input_=priv + "\n")).strip()
        return priv, pub

    async def gen_psk(self) -> str:
        return (await self._exec("awg", "genpsk")).strip()

    # ---------- чтение серверного конфига ----------

    async def read_server_config(self) -> str:
        return await self._exec("cat", self._s.awg_config_path)

    async def write_server_config(self, content: str) -> None:
        await self._exec(
            "sh",
            "-c",
            f"cat > {shlex.quote(self._s.awg_config_path)}",
            input_=content,
        )

    async def server_interface(self) -> ServerInterface:
        conf = await self.read_server_config()
        interface = _extract_section(conf, "Interface")
        if interface is None:
            raise AwgError("В серверном конфиге нет секции [Interface]")

        priv = interface.get("PrivateKey")
        if not priv:
            raise AwgError("В [Interface] нет PrivateKey")
        pub = (await self._exec("awg", "pubkey", input_=priv + "\n")).strip()

        port_str = interface.get("ListenPort")
        if not port_str:
            raise AwgError("В [Interface] нет ListenPort")

        obfuscation = {k: interface[k] for k in OBFUSCATION_KEYS if k in interface}
        return ServerInterface(
            public_key=pub,
            listen_port=int(port_str),
            obfuscation=obfuscation,
        )

    # ---------- выделение IP ----------

    def allocate_address(self, used: set[str]) -> str:
        """Возвращает свободный IP/32 в client-подсети."""
        net = self._s.awg_client_subnet
        used_ips = {ipaddress.ip_address(addr.split("/")[0]) for addr in used}
        # пропускаем .0 (network), .1 (обычно сервер) и .255 (broadcast)
        for host in net.hosts():
            if host == net.network_address + 1:
                continue
            if host in used_ips:
                continue
            return f"{host}/32"
        raise AwgError("В подсети не осталось свободных адресов")

    # ---------- peer-операции ----------

    async def add_peer(
        self, *, public_key: str, preshared_key: str, address: str
    ) -> None:
        """Добавляет peer в running-конфиг и переписывает файл."""
        # 1) рантайм
        await self._exec(
            "awg", "set", self._s.awg_interface,
            "peer", public_key,
            "preshared-key", "/dev/stdin",
            "allowed-ips", address,
            input_=preshared_key + "\n",
        )
        # 2) персистентный конфиг — дописываем peer-блок в файл
        block = (
            f"\n[Peer]\n"
            f"PublicKey = {public_key}\n"
            f"PresharedKey = {preshared_key}\n"
            f"AllowedIPs = {address}\n"
        )
        await self._exec(
            "sh", "-c",
            f"printf %s {shlex.quote(block)} >> {shlex.quote(self._s.awg_config_path)}",
        )

    async def remove_peer(self, public_key: str) -> None:
        # 1) убрать из рантайма
        await self._exec(
            "awg", "set", self._s.awg_interface, "peer", public_key, "remove"
        )
        # 2) переписать конфиг без этого peer
        conf = await self.read_server_config()
        new_conf = _remove_peer_block(conf, public_key)
        await self.write_server_config(new_conf)

    # ---------- AmneziaVPN clientsTable ----------
    #
    # GUI AmneziaVPN на сервере показывает клиентов из JSON-файла clientsTable
    # рядом с конфигом WireGuard. Чтобы peer'ы, созданные ботом, появлялись в
    # окне приложения, дублируем их в этот файл.
    # Все операции best-effort: при любой ошибке логируем и не падаем.

    async def register_in_clients_table(self, *, public_key: str, name: str) -> None:
        if not self._s.awg_clients_table_path:
            return
        try:
            data = await self._read_clients_table()
            if any(item.get("clientId") == public_key for item in data):
                return  # уже зарегистрирован
            data.append({
                "clientId": public_key,
                "userData": {
                    "clientName": name,
                    "creationDate": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                },
            })
            await self._write_clients_table(data)
        except Exception:  # noqa: BLE001
            log.exception("clientsTable: не удалось добавить %s", public_key)

    async def unregister_from_clients_table(self, public_key: str) -> None:
        if not self._s.awg_clients_table_path:
            return
        try:
            data = await self._read_clients_table()
            new = [item for item in data if item.get("clientId") != public_key]
            if len(new) != len(data):
                await self._write_clients_table(new)
        except Exception:  # noqa: BLE001
            log.exception("clientsTable: не удалось удалить %s", public_key)

    async def _read_clients_table(self) -> list[dict]:
        path = self._s.awg_clients_table_path
        # cat вернёт ошибку, если файла нет — считаем это пустой таблицей
        try:
            raw = await self._exec("cat", path)
        except AwgError as exc:
            log.info("clientsTable: файл %s не найден (%s) — стартуем с пустой", path, exc)
            return []
        raw = raw.strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("clientsTable: %s содержит невалидный JSON, пропускаю", path)
            return []
        return data if isinstance(data, list) else []

    async def _write_clients_table(self, data: list[dict]) -> None:
        path = self._s.awg_clients_table_path
        content = json.dumps(data, indent=4, ensure_ascii=False)
        # atomic write: пишем во временный файл и переименовываем
        tmp = f"{path}.tmp"
        await self._exec(
            "sh", "-c",
            f"cat > {shlex.quote(tmp)} && mv {shlex.quote(tmp)} {shlex.quote(path)}",
            input_=content,
        )

    # ---------- статистика ----------

    async def dump(self) -> list[PeerStats]:
        """``awg show <iface> dump`` — табличный машинный вывод."""
        raw = await self._exec("awg", "show", self._s.awg_interface, "dump")
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        if not lines:
            return []
        # Первая строка — interface (priv, pub, listen-port, fwmark).
        # Далее по строке на peer: pub, psk, endpoint, allowed-ips, latest-handshake, rx, tx, keepalive
        peers: list[PeerStats] = []
        for ln in lines[1:]:
            cols = ln.split("\t")
            if len(cols) < 8:
                continue
            peers.append(
                PeerStats(
                    public_key=cols[0],
                    endpoint=cols[2] if cols[2] != "(none)" else None,
                    allowed_ips=cols[3],
                    latest_handshake=int(cols[4] or 0),
                    rx_bytes=int(cols[5] or 0),
                    tx_bytes=int(cols[6] or 0),
                )
            )
        return peers

    # ---------- клиентский конфиг ----------

    def build_client_config(
        self,
        *,
        server: ServerInterface,
        private_key: str,
        preshared_key: str,
        address: str,
    ) -> str:
        s = self._s
        port = s.awg_endpoint_port or server.listen_port
        lines = [
            "[Interface]",
            f"PrivateKey = {private_key}",
            f"Address = {address}",
            f"DNS = {', '.join(s.awg_client_dns)}",
        ]
        # Параметры обфускации AmneziaWG обязательно должны попасть в клиент.
        for k in OBFUSCATION_KEYS:
            if k in server.obfuscation:
                lines.append(f"{k} = {server.obfuscation[k]}")
        lines += [
            "",
            "[Peer]",
            f"PublicKey = {server.public_key}",
            f"PresharedKey = {preshared_key}",
            f"AllowedIPs = {', '.join(s.awg_client_allowed_ips)}",
            f"Endpoint = {s.awg_endpoint_host}:{port}",
        ]
        if s.awg_client_keepalive > 0:
            lines.append(f"PersistentKeepalive = {s.awg_client_keepalive}")
        return "\n".join(lines) + "\n"


# ============================================================
# Парсинг wg-quick конфига
# ============================================================

_SECTION_RE = re.compile(r"^\[(?P<name>\w+)\]\s*$")


def _extract_section(conf: str, name: str) -> dict[str, str] | None:
    """Возвращает первую секцию [name] как dict (порядок ключей не сохраняется)."""
    result: dict[str, str] | None = None
    in_section = False
    for raw in conf.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _SECTION_RE.match(line)
        if m:
            if in_section:
                return result
            in_section = m.group("name") == name
            if in_section:
                result = {}
            continue
        if in_section and "=" in line and result is not None:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def _remove_peer_block(conf: str, public_key: str) -> str:
    """Удаляет [Peer]-секцию с указанным PublicKey, сохраняя остальное."""
    out: list[str] = []
    current: list[str] = []
    is_peer = False
    matches_pub = False

    def flush() -> None:
        nonlocal current, is_peer, matches_pub
        if not (is_peer and matches_pub):
            out.extend(current)
        current = []
        is_peer = False
        matches_pub = False

    for raw in conf.splitlines():
        m = _SECTION_RE.match(raw.strip())
        if m:
            flush()
            is_peer = m.group("name") == "Peer"
            current.append(raw)
            continue
        current.append(raw)
        if is_peer and "=" in raw:
            k, _, v = raw.partition("=")
            if k.strip() == "PublicKey" and v.strip() == public_key:
                matches_pub = True
    flush()
    # схлопываем подряд идущие пустые строки до двух максимум
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).rstrip() + "\n"
