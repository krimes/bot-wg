"""server.json Amnezia → inbound для vless://."""

from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from bot.services.xray import (
    PUBLIC_KEY_NAME,
    SHORT_ID_NAME,
    XrayError,
    XrayService,
    inbound_from_server_config,
)
from bot.services.xui import build_vless_link, client_flow


SERVER_XHTTP = {
    "inbounds": [
        {
            "port": 443,
            "protocol": "vless",
            "settings": {
                "clients": [{"id": "srv", "flow": "xtls-rprx-vision"}],
                "decryption": "none",
            },
            "streamSettings": {
                "network": "xhttp",
                "security": "reality",
                "realitySettings": {
                    "dest": "www.googletagmanager.com:443",
                    "privateKey": "PRIV",
                    "serverNames": ["www.googletagmanager.com"],
                    "shortIds": ["a3f1"],
                },
                "xhttpSettings": {
                    "host": "www.googletagmanager.com",
                    "path": "/a1b2c3d4e5",
                    "mode": "stream-one",
                    "noGRPCHeader": True,
                    "noSSEHeader": True,
                    "sessionIDPlacement": "cookie",
                    "sessionIDKey": "sid",
                    "scMaxEachPostBytes": "1000000-1000000",
                    "scStreamUpServerSecs": "1-100",
                    "scMaxBufferedPosts": 30,
                    "xPaddingObfsMode": True,
                    "xPaddingBytes": "100-1000",
                    "xPaddingKey": "x_padding",
                    "xPaddingHeader": "X-Padding",
                    "xPaddingPlacement": "cookie",
                    "xPaddingMethod": "repeat-x",
                },
            },
        }
    ]
}


def _qs(link: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(link).query, keep_blank_values=True).items()}


def test_inbound_from_server_copies_xhttp_and_injects_public_key():
    inbound = inbound_from_server_config(
        SERVER_XHTTP, public_key="PUBKEY", short_id="ignored",
    )
    assert inbound["port"] == 443
    assert inbound["settings"]["encryption"] == "none"
    assert client_flow(inbound["streamSettings"]) == ""
    link = build_vless_link(
        uuid="u", host="vpn.example.com", inbound=inbound, remark="phone",
    )
    qs = _qs(link)
    assert qs["type"] == "xhttp"
    assert qs["path"] == "/a1b2c3d4e5"
    assert qs["mode"] == "stream-one"
    assert qs["host"] == "www.googletagmanager.com"
    assert qs["pbk"] == "PUBKEY"
    assert qs["sni"] == "www.googletagmanager.com"
    assert qs["sid"] == "a3f1"
    assert qs["fp"] == "chrome"
    assert "flow" not in qs
    extra = json.loads(qs["extra"])
    assert extra["mode"] == "stream-one"
    assert extra["noGRPCHeader"] is True
    assert extra["sessionIDPlacement"] == "cookie"
    assert extra["sessionIDKey"] == "sid"
    assert extra["xPaddingObfsMode"] is True
    assert extra["xPaddingPlacement"] == "cookie"
    assert "noSSEHeader" not in extra
    assert "scStreamUpServerSecs" not in extra
    assert "scMaxBufferedPosts" not in extra
    assert "privateKey" not in qs["extra"]
    assert "xPaddingBytes" not in extra


def test_inbound_uses_short_id_file_when_server_json_has_none():
    doc = json.loads(json.dumps(SERVER_XHTTP))
    doc["inbounds"][0]["streamSettings"]["realitySettings"].pop("shortIds")
    inbound = inbound_from_server_config(doc, public_key="PUB", short_id="file-sid")
    rs = inbound["streamSettings"]["realitySettings"]
    assert rs["shortIds"] == ["file-sid"]
    assert rs["publicKey"] == "PUB"


def test_inbound_refuses_reality_without_public_key():
    with pytest.raises(XrayError, match="publicKey"):
        inbound_from_server_config(SERVER_XHTTP, public_key="", short_id="")


def test_tcp_reality_keeps_vision_flow():
    doc = {
        "inbounds": [{
            "port": "8443",
            "protocol": "vless",
            "settings": {"decryption": "none", "clients": []},
            "streamSettings": {
                "network": "raw",
                "security": "reality",
                "realitySettings": {
                    "serverNames": ["sni.test"],
                    "shortIds": ["ab"],
                },
            },
        }]
    }
    inbound = inbound_from_server_config(doc, public_key="K")
    assert client_flow(inbound["streamSettings"]) == "xtls-rprx-vision"
    qs = _qs(build_vless_link(uuid="u", host="h", inbound=inbound, remark="r"))
    assert qs["type"] == "tcp"
    assert qs["flow"] == "xtls-rprx-vision"
    assert qs["pbk"] == "K"
    assert urlparse(
        build_vless_link(uuid="u", host="h", inbound=inbound, remark="r")
    ).port == 8443


def test_kcp_fields_from_server_go_to_the_link():
    doc = {
        "inbounds": [{
            "port": 443,
            "protocol": "vless",
            "settings": {"decryption": "none"},
            "streamSettings": {
                "network": "kcp",
                "security": "none",
                "kcpSettings": {"mtu": 1350, "tti": 50, "seed": "s"},
            },
        }]
    }
    inbound = inbound_from_server_config(doc)
    qs = _qs(build_vless_link(uuid="u", host="h", inbound=inbound, remark="r"))
    assert qs["type"] == "kcp"
    assert qs["mtu"] == "1350"
    assert qs["tti"] == "50"
    assert qs["seed"] == "s"
    assert "flow" not in qs


class _FakeXray(XrayService):
    def __init__(self, files: dict[str, str]) -> None:
        super().__init__(SimpleNamespace(
            xray_container="amnezia-xray",
            xray_config_path="/opt/amnezia/xray/server.json",
        ))
        self.files = files

    async def _exec(self, *argv: str, input_: str | None = None) -> str:
        if argv[:1] == ("cat",) and argv[1] in self.files:
            return self.files[argv[1]]
        raise XrayError(f"missing {' '.join(argv)}")


@pytest.mark.asyncio
async def test_server_inbound_reads_config_and_key_file():
    data_dir = "/opt/amnezia/xray"
    svc = _FakeXray({
        f"{data_dir}/server.json": json.dumps(SERVER_XHTTP),
        f"{data_dir}/{PUBLIC_KEY_NAME}": "FROM-FILE\n",
        f"{data_dir}/{SHORT_ID_NAME}": "zz",
    })
    inbound = await svc.server_inbound()
    assert inbound["streamSettings"]["realitySettings"]["publicKey"] == "FROM-FILE"
    assert inbound["streamSettings"]["realitySettings"]["shortIds"] == ["a3f1"]
