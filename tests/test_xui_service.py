from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from bot.services.xui import REALITY_FLOW, HappClient, XuiError, XuiService


INBOUND = {
    "id": 1,
    "port": 443,
    "protocol": "vless",
    "remark": "reality-443",
    "settings": {"encryption": "none", "clients": []},
    "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
            "serverNames": ["www.microsoft.com"],
            "shortIds": ["a3f1"],
            "settings": {
                "publicKey": "PUBKEY",
                "fingerprint": "chrome",
                "spiderX": "/",
            },
        },
    },
}


def _settings(**overrides) -> SimpleNamespace:
    data = dict(
        xui_host="http://127.0.0.1:2053",
        xui_web_base_path="/secret",
        xui_username="admin",
        xui_password="pass",
        xui_api_token=None,
        xui_inbound_id=1,
        xui_client_host="vpn.example.com",
        xui_sub_base="https://vpn.example.com:2096/sub",
        xui_tls_verify=True,
        awg_endpoint_host="fallback.example.com",
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def _service(handler, **overrides) -> XuiService:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return XuiService(_settings(**overrides), http=client)


@pytest.mark.asyncio
async def test_add_client_logs_in_and_posts_vless_client():
    calls: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        calls.append((request.method, path, body))
        if path.endswith("/login"):
            return httpx.Response(200, json={"success": True, "msg": "ok"})
        if path.endswith("/panel/api/inbounds/get/1"):
            return httpx.Response(200, json={"success": True, "obj": INBOUND})
        if path.endswith("/panel/api/inbounds/addClient"):
            return httpx.Response(200, json={"success": True, "msg": "ok"})
        return httpx.Response(404, json={"success": False, "msg": path})

    svc = _service(handler)
    created = await svc.add_client(display_name="phone", telegram_id=42)

    assert isinstance(created, HappClient)
    assert created.email == "phone_42"
    assert created.inbound_id == 1
    assert created.uuid
    assert created.sub_id
    parsed = urlparse(created.vless_link)
    assert parsed.scheme == "vless"
    assert parsed.hostname == "vpn.example.com"
    qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert qs["pbk"] == "PUBKEY"
    assert qs["flow"] == REALITY_FLOW
    assert created.subscription_url == f"https://vpn.example.com:2096/sub/{created.sub_id}"

    methods_paths = [(m, p) for m, p, _ in calls]
    assert ("POST", "/secret/login") in methods_paths
    assert ("GET", "/secret/panel/api/inbounds/get/1") in methods_paths
    add_body = next(b for m, p, b in calls if p.endswith("/addClient"))
    assert add_body["id"] == 1
    client = json.loads(add_body["settings"])["clients"][0]
    assert client["email"] == "phone_42"
    assert client["flow"] == REALITY_FLOW
    assert client["id"] == created.uuid
    assert client["subId"] == created.sub_id
    assert client["tgId"] == "42"


@pytest.mark.asyncio
async def test_add_client_uses_bearer_token_and_skips_login():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.headers.get("Authorization") == "Bearer tok-1"
        if request.url.path.endswith("/panel/api/inbounds/get/1"):
            return httpx.Response(200, json={"success": True, "obj": INBOUND})
        if request.url.path.endswith("/addClient"):
            return httpx.Response(200, json={"success": True})
        return httpx.Response(500)

    svc = _service(handler, xui_api_token="tok-1")
    await svc.add_client(display_name="n", telegram_id=1)
    assert "/secret/login" not in calls


@pytest.mark.asyncio
async def test_delete_client_hits_delclient_path():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"success": True})
        if "delClient" in request.url.path:
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404)

    svc = _service(handler)
    await svc.delete_client(inbound_id=1, uuid="abc-uuid")
    assert any(p.endswith("/panel/api/inbounds/1/delClient/abc-uuid") for p in seen)


@pytest.mark.asyncio
async def test_add_client_does_not_post_when_reality_key_missing():
    posted = {"add": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"success": True})
        if request.url.path.endswith("/panel/api/inbounds/get/1"):
            broken = {
                "id": 1,
                "port": 443,
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {},
                },
            }
            return httpx.Response(200, json={"success": True, "obj": broken})
        if request.url.path.endswith("/addClient"):
            posted["add"] = True
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404)

    svc = _service(handler)
    with pytest.raises(XuiError, match="publicKey"):
        await svc.add_client(display_name="n", telegram_id=1)
    assert posted["add"] is False


@pytest.mark.asyncio
async def test_add_client_requires_inbound_id():
    svc = _service(lambda r: httpx.Response(500), xui_inbound_id=None)
    with pytest.raises(XuiError, match="XUI_INBOUND_ID"):
        await svc.add_client(display_name="n", telegram_id=1)


def test_enabled_false_when_host_empty():
    svc = XuiService(_settings(xui_host=None))
    assert svc.enabled is False


@pytest.mark.asyncio
async def test_traffic_by_emails_reads_client_stats():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"success": True})
        if request.url.path.endswith("/panel/api/inbounds/list"):
            return httpx.Response(200, json={
                "success": True,
                "obj": [{
                    "id": 1,
                    "clientStats": [
                        {"email": "phone_42", "up": 100, "down": 200, "enable": True},
                        {"email": "other", "up": 1, "down": 2, "enable": True},
                    ],
                }],
            })
        return httpx.Response(404)

    svc = _service(handler)
    stats = await svc.traffic_by_emails(["phone_42"])
    assert stats["phone_42"].up == 100
    assert stats["phone_42"].down == 200
    assert "other" not in stats
