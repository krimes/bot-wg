from __future__ import annotations

import json
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from bot.services.xui import (
    XuiError,
    as_dict,
    build_vless_link,
    client_flow,
    happ_email,
    panel_url,
    subscription_url,
)


REALITY_INBOUND = {
    "id": 1,
    "port": 443,
    "protocol": "vless",
    "remark": "reality-443",
    "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
            "dest": "www.microsoft.com:443",
            "serverNames": ["www.microsoft.com"],
            "privateKey": "SECRET",
            "shortIds": ["a3f1"],
            "settings": {
                "publicKey": "Tx5yj1bRcOPHkdvT2pIAQ2zh0gQ8m4OPdnzqXJxxV3o",
                "fingerprint": "chrome",
                "spiderX": "/",
            },
        },
    },
}


def _qs(link: str) -> dict[str, str]:
    parsed = urlparse(link)
    return {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}


def test_panel_url_joins_host_base_and_path():
    assert panel_url("http://127.0.0.1:2053", "/secret", "panel/api/inbounds/list") == (
        "http://127.0.0.1:2053/secret/panel/api/inbounds/list"
    )


def test_panel_url_without_web_base_path():
    assert panel_url("http://127.0.0.1:2053/", "", "login") == "http://127.0.0.1:2053/login"


def test_happ_email_is_name_plus_telegram_id():
    assert happ_email("phone", 12345) == "phone_12345"


def test_subscription_url_joins_base_and_sub_id():
    assert subscription_url("https://1.2.3.4:2096/sub/", "abc123") == (
        "https://1.2.3.4:2096/sub/abc123"
    )


def test_subscription_url_none_when_base_empty():
    assert subscription_url(None, "abc") is None
    assert subscription_url("", "abc") is None


def test_as_dict_parses_json_string_and_passthrough_object():
    assert as_dict('{"a": 1}') == {"a": 1}
    assert as_dict({"a": 1}) == {"a": 1}


def test_build_vless_link_reality_nested_public_key():
    link = build_vless_link(
        uuid="22222222-3333-4444-9555-666666666666",
        host="vpn.example.com",
        inbound=REALITY_INBOUND,
        remark="phone",
        flow="xtls-rprx-vision",
    )
    parsed = urlparse(link)
    assert parsed.scheme == "vless"
    assert parsed.username == "22222222-3333-4444-9555-666666666666"
    assert parsed.hostname == "vpn.example.com"
    assert parsed.port == 443
    assert unquote(parsed.fragment) == "phone"
    qs = _qs(link)
    assert qs["type"] == "tcp"
    assert qs["encryption"] == "none"
    assert qs["security"] == "reality"
    assert qs["pbk"] == "Tx5yj1bRcOPHkdvT2pIAQ2zh0gQ8m4OPdnzqXJxxV3o"
    assert qs["fp"] == "chrome"
    assert qs["sni"] == "www.microsoft.com"
    assert qs["sid"] == "a3f1"
    assert qs["spx"] == "/"
    assert qs["flow"] == "xtls-rprx-vision"


def test_build_vless_link_reads_public_key_from_reality_root():
    inbound = {
        "port": 443,
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "realitySettings": {
                "publicKey": "ROOTKEY",
                "fingerprint": "firefox",
                "serverNames": ["www.cloudflare.com"],
                "shortIds": ["dead"],
                "spiderX": "/x",
            },
        },
    }
    qs = _qs(build_vless_link(uuid="u", host="h", inbound=inbound, remark="r"))
    assert qs["pbk"] == "ROOTKEY"
    assert qs["fp"] == "firefox"
    assert qs["sni"] == "www.cloudflare.com"
    assert qs["sid"] == "dead"
    assert qs["spx"] == "/x"


def test_build_vless_link_parses_stream_settings_json_string():
    inbound = {
        "port": 8443,
        "streamSettings": json.dumps(REALITY_INBOUND["streamSettings"]),
    }
    link = build_vless_link(uuid="u", host="h.example", inbound=inbound, remark="n")
    parsed = urlparse(link)
    assert parsed.port == 8443
    assert _qs(link)["pbk"] == "Tx5yj1bRcOPHkdvT2pIAQ2zh0gQ8m4OPdnzqXJxxV3o"


def test_build_vless_link_maps_raw_network_to_tcp():
    inbound = {
        "port": 443,
        "streamSettings": {
            "network": "raw",
            "security": "reality",
            "realitySettings": {
                "settings": {"publicKey": "K", "fingerprint": "chrome", "spiderX": "/"},
                "serverNames": ["sni.test"],
                "shortIds": ["ab"],
            },
        },
    }
    assert _qs(build_vless_link(uuid="u", host="h", inbound=inbound, remark="r"))["type"] == "tcp"


XHTTP_INBOUND = {
    "port": 443,
    "streamSettings": {
        "network": "xhttp",
        "security": "reality",
        "xhttpSettings": {
            "path": "/a1b2c3d4e5",
            "host": "www.googletagmanager.com",
            "mode": "stream-one",
            "uplinkHTTPMethod": "POST",
            "noGRPCHeader": False,
            "noSSEHeader": False,
            "sessionPlacement": "path",
            "xPaddingBytes": "100-1000",
            "xPaddingObfsMode": False,
            "scMaxEachPostBytes": "1000000-1000000",
            "scMinPostsIntervalMs": "30",
            "scStreamUpServerSecs": "20-80",
            "scMaxBufferedPosts": 30,
            "xmux": {
                "maxConcurrency": "0-0",
                "maxConnections": "0-0",
            },
        },
        "realitySettings": {
            "serverNames": ["www.googletagmanager.com"],
            "shortIds": ["a3f1"],
            "settings": {
                "publicKey": "PUBKEY",
                "fingerprint": "firefox",
                "spiderX": "/",
            },
        },
    },
}


def test_build_vless_link_xhttp_omits_flow_and_default_extra():
    link = build_vless_link(
        uuid="u",
        host="vpn.example.com",
        inbound=XHTTP_INBOUND,
        remark="phone",
        flow="xtls-rprx-vision",
    )
    qs = _qs(link)
    assert qs["type"] == "xhttp"
    assert qs["security"] == "reality"
    assert qs["path"] == "/a1b2c3d4e5"
    assert qs["mode"] == "stream-one"
    assert qs["host"] == "www.googletagmanager.com"
    assert qs["pbk"] == "PUBKEY"
    assert qs["fp"] == "firefox"
    assert qs["sni"] == "www.googletagmanager.com"
    assert "flow" not in qs
    assert "extra" not in qs
    assert client_flow(XHTTP_INBOUND["streamSettings"]) == ""


def test_build_vless_link_xhttp_puts_nondefault_fields_in_extra():
    inbound = {
        "port": 443,
        "streamSettings": {
            "network": "splithttp",
            "security": "reality",
            "xhttpSettings": {
                "path": "/up",
                "mode": "packet-up",
                "extra": {
                    "xPaddingBytes": {"from": 200, "to": 400},
                    "noGRPCHeader": True,
                    "xPaddingObfsMode": True,
                    "xPaddingPlacement": "cookie",
                    "scMinPostsIntervalMs": "100-800",
                    "noSSEHeader": True,
                    "scStreamUpServerSecs": "1-100",
                },
            },
            "realitySettings": {
                "publicKey": "K",
                "serverNames": ["sni.test"],
                "shortIds": ["ab"],
            },
        },
    }
    qs = _qs(build_vless_link(uuid="u", host="h", inbound=inbound, remark="r"))
    assert qs["type"] == "xhttp"
    assert qs["mode"] == "packet-up"
    assert qs["path"] == "/up"
    extra = json.loads(qs["extra"])
    assert extra["mode"] == "packet-up"
    assert extra["xPaddingBytes"] == "200-400"
    assert extra["noGRPCHeader"] is True
    assert extra["xPaddingObfsMode"] is True
    assert extra["xPaddingPlacement"] == "cookie"
    assert extra["scMinPostsIntervalMs"] == "100-800"
    assert "noSSEHeader" not in extra
    assert "scStreamUpServerSecs" not in extra
    assert "flow" not in qs


def test_client_flow_keeps_vision_on_tcp_reality():
    assert client_flow(REALITY_INBOUND["streamSettings"]) == "xtls-rprx-vision"


def test_build_vless_link_rejects_empty_reality_public_key():
    inbound = {
        "port": 443,
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "realitySettings": {"settings": {"publicKey": ""}},
        },
    }
    with pytest.raises(XuiError, match="publicKey"):
        build_vless_link(uuid="u", host="h", inbound=inbound, remark="r")
