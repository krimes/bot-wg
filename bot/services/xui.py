"""Клиент 3X-UI: создание VLESS-клиентов и сборка ссылок для Happ."""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote, urlencode
from uuid import uuid4

import httpx

log = logging.getLogger(__name__)

REALITY_FLOW = "xtls-rprx-vision"


class XuiError(RuntimeError):
    pass


@dataclass(slots=True)
class HappClient:
    uuid: str
    email: str
    sub_id: str
    inbound_id: int
    vless_link: str
    subscription_url: str | None


@dataclass(slots=True)
class ClientTraffic:
    email: str
    up: int
    down: int
    enable: bool = True


def panel_url(host: str, web_base_path: str, *segments: str) -> str:
    host = host.rstrip("/")
    base = (web_base_path or "").strip("/")
    extra = "/".join(s.strip("/") for s in segments if s)
    parts = [host]
    if base:
        parts.append(base)
    if extra:
        parts.append(extra)
    return "/".join(parts)


def happ_email(display_name: str, telegram_id: int) -> str:
    return f"{display_name}_{telegram_id}"


def subscription_url(base: str | None, sub_id: str) -> str | None:
    if not base or not base.strip():
        return None
    return f"{base.rstrip('/')}/{sub_id}"


def as_dict(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return {}
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise XuiError("Ожидался JSON-объект")
        return parsed
    raise XuiError(f"Не могу разобрать JSON: {type(value).__name__}")


def build_vless_link(
    *,
    uuid: str,
    host: str,
    inbound: dict,
    remark: str,
    flow: str = REALITY_FLOW,
) -> str:
    port = int(inbound["port"])
    stream = as_dict(inbound.get("streamSettings"))
    network = stream.get("network") or "tcp"
    if network == "raw":
        network = "tcp"
    security = stream.get("security") or "none"

    settings = as_dict(inbound.get("settings"))
    encryption = settings.get("encryption") or "none"

    params: dict[str, str] = {
        "type": str(network),
        "encryption": str(encryption),
        "security": str(security),
    }

    if security == "reality":
        params.update(_reality_query(stream))
    elif security == "tls":
        params.update(_tls_query(stream))

    if flow and _flow_allowed(network, security):
        params["flow"] = flow

    query = urlencode(params, quote_via=quote, safe="")
    fragment = quote(remark, safe="")
    return f"vless://{uuid}@{_host_port(host, port)}?{query}#{fragment}"


def _flow_allowed(network: str, security: str) -> bool:
    return network == "tcp" and security in {"tls", "reality"}


def _reality_query(stream: dict) -> dict[str, str]:
    rs = as_dict(stream.get("realitySettings"))
    nested = as_dict(rs.get("settings"))
    pbk = nested.get("publicKey") or rs.get("publicKey") or ""
    if not pbk:
        raise XuiError("В inbound нет Reality publicKey — ссылка для Happ будет сломана")
    fp = nested.get("fingerprint") or rs.get("fingerprint") or "chrome"
    spx = nested.get("spiderX") or rs.get("spiderX") or "/"
    sni = _first_server_name(rs, nested)
    short_ids = rs.get("shortIds") or []
    sid = short_ids[0] if short_ids else ""
    out = {"pbk": str(pbk), "fp": str(fp)}
    if sni:
        out["sni"] = sni
    out["sid"] = str(sid)
    out["spx"] = str(spx)
    return out


def _tls_query(stream: dict) -> dict[str, str]:
    ts = as_dict(stream.get("tlsSettings"))
    nested = as_dict(ts.get("settings"))
    out: dict[str, str] = {}
    sni = ts.get("serverName") or nested.get("serverName") or ""
    if sni:
        out["sni"] = str(sni)
    fp = nested.get("fingerprint") or ts.get("fingerprint")
    if fp:
        out["fp"] = str(fp)
    alpn = ts.get("alpn") or []
    if isinstance(alpn, list) and alpn:
        out["alpn"] = ",".join(str(a) for a in alpn)
    return out


def _first_server_name(rs: dict, nested: dict) -> str:
    names = rs.get("serverNames") or []
    if isinstance(names, str):
        names = [n.strip() for n in names.split(",") if n.strip()]
    if names:
        return str(names[0])
    return str(nested.get("serverName") or rs.get("serverName") or "")


def _host_port(host: str, port: int) -> str:
    host = host.strip("[]")
    if ":" in host:
        return f"[{host}]:{port}"
    return f"{host}:{port}"


class XuiSettings(Protocol):
    xui_host: str | None
    xui_web_base_path: str
    xui_username: str | None
    xui_password: str | None
    xui_api_token: str | None
    xui_inbound_id: int | None
    xui_client_host: str | None
    xui_sub_base: str | None
    xui_tls_verify: bool
    awg_endpoint_host: str


class XuiService:
    def __init__(
        self,
        settings: XuiSettings,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._s = settings
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            timeout=20.0,
            verify=settings.xui_tls_verify,
        )
        self._logged_in = bool(settings.xui_api_token)

    @property
    def enabled(self) -> bool:
        return bool(self._s.xui_host)

    def subscription_for(self, sub_id: str) -> str | None:
        return subscription_url(self._s.xui_sub_base, sub_id)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _url(self, *segments: str) -> str:
        if not self._s.xui_host:
            raise XuiError("3X-UI не настроен: задайте XUI_HOST")
        return panel_url(self._s.xui_host, self._s.xui_web_base_path, *segments)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._s.xui_api_token:
            headers["Authorization"] = f"Bearer {self._s.xui_api_token}"
        return headers

    async def _login(self) -> None:
        if self._s.xui_api_token:
            self._logged_in = True
            return
        if not self._s.xui_username or not self._s.xui_password:
            raise XuiError("Задайте XUI_API_TOKEN или XUI_USERNAME/XUI_PASSWORD")
        resp = await self._http.post(
            self._url("login"),
            json={"username": self._s.xui_username, "password": self._s.xui_password},
            headers={"Accept": "application/json"},
        )
        data = _json_body(resp)
        if resp.status_code >= 400 or data.get("success") is False:
            raise XuiError(f"Логин в 3X-UI не удался: {data.get('msg') or resp.text}")
        self._logged_in = True

    async def _request(self, method: str, *segments: str, **kwargs: Any) -> dict:
        if not self._logged_in:
            await self._login()
        url = self._url(*segments)
        kwargs.setdefault("headers", self._headers())
        resp = await self._http.request(method, url, **kwargs)
        if resp.status_code == 401 and not self._s.xui_api_token:
            self._logged_in = False
            await self._login()
            resp = await self._http.request(method, url, **kwargs)
        data = _json_body(resp)
        if resp.status_code >= 400 or data.get("success") is False:
            raise XuiError(data.get("msg") or f"{method} {url} → {resp.status_code}")
        return data

    async def get_inbound(self, inbound_id: int) -> dict:
        data = await self._request("GET", f"panel/api/inbounds/get/{inbound_id}")
        obj = data.get("obj")
        if not isinstance(obj, dict):
            raise XuiError(f"Inbound {inbound_id} не найден")
        return obj

    async def add_client(self, *, display_name: str, telegram_id: int) -> HappClient:
        if not self.enabled:
            raise XuiError("3X-UI не настроен: задайте XUI_HOST")
        inbound_id = self._s.xui_inbound_id
        if not inbound_id:
            raise XuiError("XUI_INBOUND_ID не задан")
        inbound = await self.get_inbound(inbound_id)
        host = self._s.xui_client_host or self._s.awg_endpoint_host
        if not host:
            raise XuiError("Задайте XUI_CLIENT_HOST или AWG_ENDPOINT_HOST")
        # Проверяем inbound до создания клиента — иначе на панели останется сирота.
        build_vless_link(
            uuid="00000000-0000-0000-0000-000000000000",
            host=host,
            inbound=inbound,
            remark=display_name,
            flow=REALITY_FLOW,
        )
        email = happ_email(display_name, telegram_id)
        client_uuid = str(uuid4())
        sub_id = secrets.token_hex(8)
        payload = {
            "id": inbound_id,
            "settings": json.dumps({
                "clients": [{
                    "id": client_uuid,
                    "flow": REALITY_FLOW,
                    "email": email,
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": 0,
                    "enable": True,
                    "tgId": str(telegram_id),
                    "subId": sub_id,
                    "comment": display_name,
                    "reset": 0,
                }],
            }),
        }
        await self._request("POST", "panel/api/inbounds/addClient", json=payload)
        link = build_vless_link(
            uuid=client_uuid,
            host=host,
            inbound=inbound,
            remark=display_name,
            flow=REALITY_FLOW,
        )
        return HappClient(
            uuid=client_uuid,
            email=email,
            sub_id=sub_id,
            inbound_id=inbound_id,
            vless_link=link,
            subscription_url=subscription_url(self._s.xui_sub_base, sub_id),
        )

    async def delete_client(self, *, inbound_id: int, uuid: str) -> None:
        await self._request(
            "POST", f"panel/api/inbounds/{inbound_id}/delClient/{uuid}",
        )

    async def traffic_by_emails(self, emails: list[str]) -> dict[str, ClientTraffic]:
        wanted = set(emails)
        if not wanted:
            return {}
        data = await self._request("GET", "panel/api/inbounds/list")
        obj = data.get("obj") or []
        result: dict[str, ClientTraffic] = {}
        for inbound in obj:
            if not isinstance(inbound, dict):
                continue
            for row in inbound.get("clientStats") or []:
                email = row.get("email")
                if email in wanted and email not in result:
                    result[email] = ClientTraffic(
                        email=email,
                        up=int(row.get("up") or 0),
                        down=int(row.get("down") or 0),
                        enable=bool(row.get("enable", True)),
                    )
        return result

    async def rebuild_link(self, *, uuid: str, inbound_id: int, remark: str) -> str:
        inbound = await self.get_inbound(inbound_id)
        host = self._s.xui_client_host or self._s.awg_endpoint_host
        if not host:
            raise XuiError("Задайте XUI_CLIENT_HOST или AWG_ENDPOINT_HOST")
        return build_vless_link(
            uuid=uuid,
            host=host,
            inbound=inbound,
            remark=remark,
            flow=REALITY_FLOW,
        )


def _json_body(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        return {"success": False, "msg": resp.text}
    return data if isinstance(data, dict) else {"success": False, "msg": str(data)}
