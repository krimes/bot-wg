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

from bot.services.xray import XrayService

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
    flow: str | None = None,
) -> str:
    port = int(inbound["port"])
    stream = as_dict(inbound.get("streamSettings"))
    network = _share_network(stream)
    security = stream.get("security") or "none"
    if flow is None:
        flow = client_flow(stream)

    settings = as_dict(inbound.get("settings"))
    encryption = settings.get("encryption") or "none"

    params: dict[str, str] = {
        "type": network,
        "encryption": str(encryption),
        "security": str(security),
    }

    if security == "reality":
        params.update(_reality_query(stream))
    elif security == "tls":
        params.update(_tls_query(stream))

    if network == "xhttp":
        params.update(_xhttp_query(stream))
    elif network == "kcp":
        params.update(_kcp_query(stream))

    if flow and _flow_allowed(network, security):
        params["flow"] = flow

    query = urlencode(params, quote_via=quote, safe="")
    fragment = quote(remark, safe="")
    return f"vless://{uuid}@{_host_port(host, port)}?{query}#{fragment}"


def client_flow(stream: dict) -> str:
    """Vision только на TCP+TLS/Reality. У XHTTP flow пустой."""
    network = _share_network(stream)
    security = str(stream.get("security") or "none")
    if network == "tcp" and security in {"tls", "reality"}:
        return REALITY_FLOW
    return ""


def _share_network(stream: dict) -> str:
    raw = str(stream.get("network") or stream.get("method") or "tcp").lower()
    if raw == "raw":
        return "tcp"
    if raw == "splithttp":
        return "xhttp"
    if raw == "mkcp":
        return "kcp"
    return raw


def _flow_allowed(network: str, security: str) -> bool:
    return network == "tcp" and security in {"tls", "reality"}


def _xhttp_query(stream: dict) -> dict[str, str]:
    raw = as_dict(stream.get("xhttpSettings") or stream.get("splithttpSettings"))
    extra_blob = as_dict(raw.get("extra")) if raw.get("extra") else {}
    cfg = {**extra_blob}
    for key, value in raw.items():
        if key == "extra":
            continue
        if value not in (None, ""):
            cfg[key] = value
    path = str(cfg.get("path") or "/")
    mode = str(cfg.get("mode") or "auto")
    out: dict[str, str] = {"path": path, "mode": mode}
    host = cfg.get("host") or ""
    if isinstance(host, list):
        host = host[0] if host else ""
    if host:
        out["host"] = str(host)
    extra = _xhttp_extra(cfg)
    if extra:
        extra["mode"] = mode
        out["extra"] = json.dumps(extra, separators=(",", ":"), ensure_ascii=False)
    return out


def _xhttp_extra(cfg: dict) -> dict:
    """Только клиентские поля, которые отличаются от дефолта ядра.

    noSSEHeader, scMaxBufferedPosts и scStreamUpServerSecs — серверные,
    в ссылку их не кладём. Дефолтный xPaddingBytes тоже не кладём: лишний
    extra ломает импорт mode у части клиентов.
    """
    extra: dict = {}
    headers = cfg.get("headers") or {}
    if isinstance(headers, dict):
        cleaned = {
            str(k): v
            for k, v in headers.items()
            if str(k).lower() != "host" and v not in (None, "")
        }
        if cleaned:
            extra["headers"] = cleaned

    padding = _norm_range(cfg.get("xPaddingBytes"))
    if padding and padding != "100-1000":
        extra["xPaddingBytes"] = padding

    if _truthy(cfg.get("noGRPCHeader")):
        extra["noGRPCHeader"] = True

    if _truthy(cfg.get("xPaddingObfsMode")):
        extra["xPaddingObfsMode"] = True
        _put_if(extra, "xPaddingKey", cfg.get("xPaddingKey"), skip={"", "x_padding"})
        _put_if(extra, "xPaddingHeader", cfg.get("xPaddingHeader"), skip={"", "X-Padding"})
        _put_if(
            extra, "xPaddingPlacement", cfg.get("xPaddingPlacement"),
            skip={"", "queryInHeader"},
        )
        _put_if(extra, "xPaddingMethod", cfg.get("xPaddingMethod"), skip={"", "repeat-x"})

    _put_if(extra, "sessionPlacement", cfg.get("sessionPlacement"), skip={"", "path"})
    _put_if(extra, "sessionKey", cfg.get("sessionKey"), skip={""})
    # Имена из Xray 26+ / Amnezia 5.1. В server.json лежат именно они.
    _put_if(extra, "sessionIDPlacement", cfg.get("sessionIDPlacement"), skip={"", "path"})
    _put_if(extra, "sessionIDKey", cfg.get("sessionIDKey"), skip={""})
    _put_if(extra, "sessionIDTable", cfg.get("sessionIDTable"), skip={""})
    session_len = _norm_range(cfg.get("sessionIDLength"))
    if session_len and session_len not in {"0", "0-0"}:
        extra["sessionIDLength"] = session_len
    _put_if(extra, "seqPlacement", cfg.get("seqPlacement"), skip={"", "path"})
    _put_if(extra, "seqKey", cfg.get("seqKey"), skip={""})
    method = str(cfg.get("uplinkHTTPMethod") or "")
    if method and method.upper() != "POST":
        extra["uplinkHTTPMethod"] = method
    _put_if(
        extra, "uplinkDataPlacement", cfg.get("uplinkDataPlacement"),
        skip={"", "body"},
    )
    _put_if(extra, "uplinkDataKey", cfg.get("uplinkDataKey"), skip={""})
    chunk = _norm_range(cfg.get("uplinkChunkSize"))
    if chunk and chunk != "0":
        extra["uplinkChunkSize"] = chunk

    each_post = _norm_range(cfg.get("scMaxEachPostBytes"))
    if each_post and each_post not in {"1000000", "1000000-1000000"}:
        extra["scMaxEachPostBytes"] = each_post
    interval = _norm_range(cfg.get("scMinPostsIntervalMs"))
    if interval and interval not in {"30", "30-30"}:
        extra["scMinPostsIntervalMs"] = interval

    xmux = _xmux_extra(cfg.get("xmux"))
    if xmux:
        extra["xmux"] = xmux
    return extra


def _put_if(extra: dict, key: str, value, *, skip: set[str]) -> None:
    if value is None:
        return
    text = str(value).strip()
    if text not in skip:
        extra[key] = text


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _norm_range(value) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, dict):
        left = value.get("from", value.get("From", value.get("left", value.get("Left"))))
        right = value.get("to", value.get("To", value.get("right", value.get("Right"))))
        if left in (None, "") and right in (None, ""):
            return ""
        if right in (None, "") or str(left) == str(right):
            return _num_text(left)
        return f"{_num_text(left)}-{_num_text(right)}"
    if isinstance(value, (int, float)):
        return _num_text(value)
    text = str(value).strip().replace(" ", "")
    if "-" in text:
        left, right = text.split("-", 1)
        if left == right:
            return left
    return text


def _num_text(value) -> str:
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


def _xmux_extra(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    out: dict = {}
    for key in (
        "maxConcurrency",
        "maxConnections",
        "cMaxReuseTimes",
        "hMaxRequestTimes",
        "hMaxReusableSecs",
        "hKeepAlivePeriod",
    ):
        text = _norm_range(value.get(key))
        if text and text not in {"0", "0-0"}:
            raw = value.get(key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                out[key] = int(raw) if raw == int(raw) else raw
            else:
                out[key] = text if not isinstance(raw, str) else raw
    return out or None


def _kcp_query(stream: dict) -> dict[str, str]:
    """Поля mKCP из серверного streamSettings. Дефолты ядра не выдумываем."""
    kcp = as_dict(stream.get("kcpSettings"))
    out: dict[str, str] = {}
    header = kcp.get("header")
    if isinstance(header, dict):
        header_type = header.get("type")
        if header_type not in (None, "", "none"):
            out["headerType"] = str(header_type)
    seed = kcp.get("seed")
    if seed not in (None, ""):
        out["seed"] = str(seed)
    for key in ("mtu", "tti", "uplinkCapacity", "downlinkCapacity"):
        value = kcp.get(key)
        if value not in (None, ""):
            out[key] = str(value)
    return out


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
        xray: XrayService | None = None,
    ) -> None:
        self._s = settings
        self._xray = xray
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            timeout=20.0,
            verify=settings.xui_tls_verify,
        )
        self._logged_in = bool(settings.xui_api_token)

    async def _share_inbound(self, panel_inbound: dict) -> dict:
        """Транспорт ссылки: контейнер Amnezia, если он задан.

        Панель по-прежнему хранит клиента. Порт, Reality и XHTTP — из
        ``server.json``, как обфускация WG берётся из ``wg0.conf``.
        """
        if self._xray is not None and self._xray.enabled:
            return await self._xray.server_inbound()
        return panel_inbound

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
        panel = await self.get_inbound(inbound_id)
        inbound = await self._share_inbound(panel)
        host = self._s.xui_client_host or self._s.awg_endpoint_host
        if not host:
            raise XuiError("Задайте XUI_CLIENT_HOST или AWG_ENDPOINT_HOST")
        flow = client_flow(as_dict(inbound.get("streamSettings")))
        # Проверяем конфиг до создания клиента — иначе на панели останется сирота.
        build_vless_link(
            uuid="00000000-0000-0000-0000-000000000000",
            host=host,
            inbound=inbound,
            remark=display_name,
            flow=flow,
        )
        email = happ_email(display_name, telegram_id)
        client_uuid = str(uuid4())
        sub_id = secrets.token_hex(8)
        payload = {
            "id": inbound_id,
            "settings": json.dumps({
                "clients": [{
                    "id": client_uuid,
                    "flow": flow,
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
            flow=flow,
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
        panel = await self.get_inbound(inbound_id)
        inbound = await self._share_inbound(panel)
        host = self._s.xui_client_host or self._s.awg_endpoint_host
        if not host:
            raise XuiError("Задайте XUI_CLIENT_HOST или AWG_ENDPOINT_HOST")
        return build_vless_link(
            uuid=uuid,
            host=host,
            inbound=inbound,
            remark=remark,
            flow=client_flow(as_dict(inbound.get("streamSettings"))),
        )


def _json_body(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        return {"success": False, "msg": resp.text}
    return data if isinstance(data, dict) else {"success": False, "msg": str(data)}
