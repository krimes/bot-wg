"""Xray Amnezia через ``docker exec``.

Как AmneziaWG: клиент дописывается в живой конфиг контейнера, ссылка
собирается из этого же файла. После записи конфиг проверяется
``xray -test``, подменяется и контейнер перезапускается.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
from pathlib import PurePosixPath
from typing import Protocol

log = logging.getLogger(__name__)

PUBLIC_KEY_NAME = "xray_public.key"
SHORT_ID_NAME = "xray_short_id.key"


class XrayError(RuntimeError):
    pass


class XraySettings(Protocol):
    xray_container: str
    xray_config_path: str


class XrayService:
    def __init__(self, settings: XraySettings) -> None:
        self._s = settings

    @property
    def enabled(self) -> bool:
        return bool((self._s.xray_container or "").strip())

    async def _exec(self, *argv: str, input_: str | None = None) -> str:
        if not self.enabled:
            raise XrayError("XRAY_CONTAINER пуст")
        cmd = ["docker", "exec", "-i", self._s.xray_container, *argv]
        log.debug("exec: %s", " ".join(shlex.quote(a) for a in cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if input_ is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input_.encode() if input_ else None)
        if proc.returncode != 0:
            raise XrayError(
                f"{' '.join(argv)} exited with {proc.returncode}: "
                f"{stderr.decode(errors='replace').strip()}"
            )
        return stdout.decode()

    async def server_inbound(self) -> dict:
        """Inbound в форме, которую понимает сборщик ``vless://``.

        ``publicKey`` в ``server.json`` нет — Amnezia кладёт его в
        ``xray_public.key``. Без него ссылка Reality не соберётся.
        """
        raw = await self._exec("cat", self._s.xray_config_path)
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise XrayError(f"{self._s.xray_config_path} не JSON: {exc}") from exc
        if not isinstance(doc, dict):
            raise XrayError(f"{self._s.xray_config_path} не объект")

        data_dir = str(PurePosixPath(self._s.xray_config_path).parent)
        public_key = await self._read_optional(f"{data_dir}/{PUBLIC_KEY_NAME}")
        short_id = await self._read_optional(f"{data_dir}/{SHORT_ID_NAME}")
        return inbound_from_server_config(
            doc, public_key=public_key, short_id=short_id,
        )

    async def _read_optional(self, path: str) -> str:
        try:
            return (await self._exec("cat", path)).strip()
        except XrayError as exc:
            log.debug("не прочитал %s: %s", path, exc)
            return ""

    async def add_client(
        self, *, client_id: str, email: str, host: str, remark: str,
    ) -> str:
        """Дописывает VLESS-клиента в server.json и возвращает ``vless://``."""
        if not host.strip():
            raise XrayError("Задайте XUI_CLIENT_HOST или AWG_ENDPOINT_HOST")
        doc = await self._read_doc()
        share = await self._share_inbound(doc)
        flow = flow_for_stream(share["streamSettings"])
        link = _render_link(
            client_id=client_id, host=host, remark=remark, inbound=share, flow=flow,
        )
        add_vless_client(doc, client_id=client_id, email=email, flow=flow)
        await self._apply_server_config(doc)
        return link

    async def remove_client(self, client_id: str) -> None:
        """Снимает UUID с сервера. Если его уже нет — ничего не перезапускает."""
        doc = await self._read_doc()
        if not remove_vless_client(doc, client_id):
            log.info("uuid %s нет в server.json, перезапуск не нужен", client_id)
            return
        await self._apply_server_config(doc)

    async def client_link(self, *, client_id: str, host: str, remark: str) -> str:
        if not host.strip():
            raise XrayError("Задайте XUI_CLIENT_HOST или AWG_ENDPOINT_HOST")
        share = await self.server_inbound()
        flow = flow_for_stream(share["streamSettings"])
        return _render_link(
            client_id=client_id, host=host, remark=remark, inbound=share, flow=flow,
        )

    async def _read_doc(self) -> dict:
        raw = await self._exec("cat", self._s.xray_config_path)
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise XrayError(f"{self._s.xray_config_path} не JSON: {exc}") from exc
        if not isinstance(doc, dict):
            raise XrayError(f"{self._s.xray_config_path} не объект")
        return doc

    async def _share_inbound(self, doc: dict) -> dict:
        data_dir = str(PurePosixPath(self._s.xray_config_path).parent)
        public_key = await self._read_optional(f"{data_dir}/{PUBLIC_KEY_NAME}")
        short_id = await self._read_optional(f"{data_dir}/{SHORT_ID_NAME}")
        return inbound_from_server_config(
            doc, public_key=public_key, short_id=short_id,
        )

    async def _apply_server_config(self, doc: dict) -> None:
        live = self._s.xray_config_path
        staged = str(PurePosixPath(live).with_name("server.new.json"))
        body = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        await self._write_text(staged, body)
        swapped = False
        try:
            await self._swap_staged(live, staged)
            swapped = True
            await self._restart_container()
            if not await self._is_serving():
                raise XrayError("Xray не поднялся после перезапуска")
        except Exception:
            if swapped:
                restored = await self._restore_backup(live)
                try:
                    await self._restart_container()
                except XrayError:
                    log.exception("не удалось перезапустить Xray после отката")
                if restored:
                    raise XrayError(
                        "Xray не принял новый server.json, вернул предыдущий конфиг"
                    )
            raise
        await self._try_rm(f"{live}.bak")

    async def _write_text(self, path: str, content: str) -> None:
        await self._exec(
            "sh", "-c", f"cat > {shlex.quote(path)}", input_=content,
        )

    async def _swap_staged(self, live: str, staged: str) -> None:
        script = (
            f"LIVE={shlex.quote(live)}\n"
            f"STAGED={shlex.quote(staged)}\n"
            'BACKUP="$LIVE.bak"\n'
            'if [ ! -s "$STAGED" ]; then echo amnezia_apply=missing; exit 0; fi\n'
            'if ! xray -test -format json -config "$STAGED" >/tmp/xray_test.log 2>&1; then\n'
            '  echo amnezia_apply=invalid\n'
            '  rm -f "$STAGED"\n'
            "  exit 0\n"
            "fi\n"
            'if [ -f "$LIVE" ]; then cp "$LIVE" "$BACKUP"; fi\n'
            'mv "$STAGED" "$LIVE"\n'
            "echo amnezia_apply=swapped\n"
        )
        out = await self._exec("sh", "-c", script)
        if "amnezia_apply=swapped" in out:
            return
        if "amnezia_apply=invalid" in out:
            detail = await self._read_optional("/tmp/xray_test.log")
            raise XrayError(f"Xray отверг конфиг: {detail or 'xray -test'}")
        raise XrayError(f"Не удалось подменить server.json: {out.strip()}")

    async def _restore_backup(self, live: str) -> bool:
        script = (
            f"LIVE={shlex.quote(live)}\n"
            'BACKUP="$LIVE.bak"\n'
            'if [ -f "$BACKUP" ]; then cp "$BACKUP" "$LIVE"; echo amnezia_restore=done;\n'
            "else echo amnezia_restore=nobackup; fi\n"
        )
        try:
            out = await self._exec("sh", "-c", script)
        except XrayError:
            log.exception("не удалось откатить %s", live)
            return False
        return "amnezia_restore=done" in out

    async def _restart_container(self) -> None:
        cmd = ["docker", "restart", self._s.xray_container]
        log.info("restart %s", self._s.xray_container)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise XrayError(
                f"docker restart {self._s.xray_container} → {proc.returncode}: "
                f"{stderr.decode(errors='replace').strip()}"
            )

    async def _is_serving(self) -> bool:
        script = (
            "for i in 1 2 3 4 5 6; do\n"
            '  if pgrep xray >/dev/null 2>&1 || ps 2>/dev/null | grep -v grep | grep -q "[x]ray"; then\n'
            "    echo amnezia_serving=yes\n"
            "    exit 0\n"
            "  fi\n"
            "  sleep 1\n"
            "done\n"
            "echo amnezia_serving=no\n"
        )
        try:
            out = await self._exec("sh", "-c", script)
        except XrayError as exc:
            log.warning("не удалось проверить процесс xray: %s", exc)
            return False
        return "amnezia_serving=yes" in out

    async def _try_rm(self, path: str) -> None:
        try:
            await self._exec("rm", "-f", path)
        except XrayError as exc:
            log.debug("не удалил %s: %s", path, exc)


def inbound_from_server_config(
    doc: dict,
    *,
    public_key: str = "",
    short_id: str = "",
) -> dict:
    """Первый VLESS inbound ``server.json`` → словарь для ссылки Happ."""
    inbound = _vless_inbound(doc)
    port = inbound.get("port")
    if port in (None, ""):
        raise XrayError("В server.json у VLESS inbound нет port")
    stream = inbound.get("streamSettings")
    if not isinstance(stream, dict):
        raise XrayError("В server.json у VLESS inbound нет streamSettings")
    stream = dict(stream)
    security = str(stream.get("security") or "none")
    if security == "reality":
        stream["realitySettings"] = _with_reality_public_key(
            stream.get("realitySettings"),
            public_key=public_key.strip(),
            short_id=short_id.strip(),
        )
    settings = inbound.get("settings") if isinstance(inbound.get("settings"), dict) else {}
    encryption = settings.get("encryption") or settings.get("decryption") or "none"
    return {
        "port": port,
        "protocol": inbound.get("protocol") or "vless",
        "settings": {"encryption": encryption},
        "streamSettings": stream,
    }


def _vless_inbound(doc: dict) -> dict:
    inbounds = doc.get("inbounds")
    if not isinstance(inbounds, list) or not inbounds:
        raise XrayError("В server.json нет inbounds")
    objects = [item for item in inbounds if isinstance(item, dict)]
    if not objects:
        raise XrayError("В server.json нет inbounds")
    for item in objects:
        if str(item.get("protocol") or "").lower() == "vless":
            return item
    return objects[0]


def _with_reality_public_key(raw, *, public_key: str, short_id: str) -> dict:
    rs = dict(raw) if isinstance(raw, dict) else {}
    nested = rs.get("settings") if isinstance(rs.get("settings"), dict) else {}
    has_key = bool(nested.get("publicKey") or rs.get("publicKey"))
    if not has_key:
        if not public_key:
            raise XrayError(
                "В server.json нет Reality publicKey, и файл xray_public.key пуст"
            )
        rs["publicKey"] = public_key
    short_ids = rs.get("shortIds") or []
    if not short_ids and not rs.get("shortId") and short_id:
        rs["shortIds"] = [short_id]
    return rs


def flow_for_stream(stream: dict) -> str:
    from bot.services.xui import client_flow

    return client_flow(stream)


def _render_link(
    *, client_id: str, host: str, remark: str, inbound: dict, flow: str,
) -> str:
    from bot.services.xui import build_vless_link

    return build_vless_link(
        uuid=client_id, host=host, inbound=inbound, remark=remark, flow=flow,
    )


def add_vless_client(
    doc: dict, *, client_id: str, email: str, flow: str,
) -> None:
    """Дописывает клиента в первый VLESS inbound. Как Amnezia: id и flow.

    ``email`` нужен, чтобы отличать клиентов бота в логе Xray. Пустой flow
    не пишем: на XHTTP и mKCP ядро его не принимает.
    """
    inbound = _vless_inbound(doc)
    settings = inbound.get("settings")
    if not isinstance(settings, dict):
        settings = {}
        inbound["settings"] = settings
    clients = settings.get("clients")
    if not isinstance(clients, list):
        clients = []
        settings["clients"] = clients
    for item in clients:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") == client_id:
            raise XrayError("Этот UUID уже есть в server.json")
        if email and item.get("email") == email:
            raise XrayError("Клиент с таким именем уже есть в server.json")
    entry: dict = {"id": client_id}
    if email:
        entry["email"] = email
    if flow:
        entry["flow"] = flow
    clients.append(entry)


def remove_vless_client(doc: dict, client_id: str) -> bool:
    """Снимает UUID. False — клиента не было, конфиг не менялся."""
    inbound = _vless_inbound(doc)
    settings = inbound.get("settings")
    if not isinstance(settings, dict):
        return False
    clients = settings.get("clients")
    if not isinstance(clients, list):
        return False
    kept = []
    removed = False
    for item in clients:
        if isinstance(item, dict) and str(item.get("id") or "") == client_id:
            removed = True
            continue
        kept.append(item)
    if removed:
        settings["clients"] = kept
    return removed
