from __future__ import annotations

from bot.services.awg import (
    collect_obfuscation,
    extract_section,
    merge_interface,
    render_client_config,
)


FILE_CONF = """
[Interface]
PrivateKey = serverpriv
Address = 10.8.1.1/24
ListenPort = 51820
Jc = 4
Jmin = 40
Jmax = 70
S1 = 20
S2 = 30
S3 = 21
S4 = 12
H1 = 1
H2 = 2
H3 = 3
H4 = 4
I1 = <b 0xc000000001><rc 8><t><r 50>
HeaderProtectionKey = 8Iu83eHDA3fMKKSGaEsVW9Ycd2lYYzc0MYlk1jJTvE4=
ContentPaddingAddition = 17-49
RekeyAfterTime = 111-139
RandomTrailers = on
DisableCookies = off
J1 = 10
Itime = 120

[Peer]
PublicKey = clientpub
AllowedIPs = 10.8.1.2/32
"""

SHOWCONF = """
[Interface]
PrivateKey = serverpriv
ListenPort = 51820
Jc = 5
S1 = 20
S2 = 30
S3 = 21
S4 = 12
H1 = 1
H2 = 2
H3 = 3
H4 = 4
"""


def test_extract_preserves_i1_cps_and_header_key():
    iface = extract_section(FILE_CONF, "Interface")
    assert iface is not None
    assert iface["I1"] == "<b 0xc000000001><rc 8><t><r 50>"
    assert iface["HeaderProtectionKey"] == "8Iu83eHDA3fMKKSGaEsVW9Ycd2lYYzc0MYlk1jJTvE4="
    assert iface["RandomTrailers"] == "on"


def test_merge_prefers_showconf_and_keeps_file_only_3_1_keys():
    file_if = extract_section(FILE_CONF, "Interface")
    show_if = extract_section(SHOWCONF, "Interface")
    merged = merge_interface(file_if, show_if)
    assert merged["Jc"] == "5"  # runtime wins
    assert merged["I1"].startswith("<b 0xc000")  # file fills gap
    assert merged["HeaderProtectionKey"].endswith("=")
    assert merged["RandomTrailers"] == "on"


def test_collect_obfuscation_drops_legacy_and_normalizes_bools():
    merged = merge_interface(
        extract_section(FILE_CONF, "Interface"),
        extract_section(SHOWCONF, "Interface"),
    )
    obf = collect_obfuscation(merged)
    assert "J1" not in obf
    assert "Itime" not in obf
    assert "PrivateKey" not in obf
    assert "ListenPort" not in obf
    assert obf["RandomTrailers"] == "on"
    assert obf["DisableCookies"] == "off"
    assert list(obf)[:4] == ["Jc", "Jmin", "Jmax", "S1"]
    assert "HeaderProtectionKey" in obf
    assert "I1" in obf


def test_hex_header_protection_key_becomes_base64():
    obf = collect_obfuscation({
        "HeaderProtectionKey": "f" * 64,
        "Jc": "4",
    })
    assert obf["HeaderProtectionKey"] != "f" * 64
    assert obf["HeaderProtectionKey"].endswith("=")
    assert len(obf["HeaderProtectionKey"]) == 44


def test_render_client_config_is_awg_3_1():
    obf = collect_obfuscation(extract_section(FILE_CONF, "Interface") or {})
    conf = render_client_config(
        private_key="clientpriv",
        address="10.8.1.2/32",
        dns=["1.1.1.1", "1.0.0.1"],
        mtu=1280,
        obfuscation=obf,
        server_public_key="serverpub",
        preshared_key="psk",
        allowed_ips=["0.0.0.0/0", "::/0"],
        endpoint="vpn.example.com:51820",
        keepalive=25,
    )
    assert "MTU = 1280" in conf
    assert "HeaderProtectionKey = 8Iu83eHDA3fMKKSGaEsVW9Ycd2lYYzc0MYlk1jJTvE4=" in conf
    assert "RandomTrailers = on" in conf
    assert "I1 = <b 0xc000000001><rc 8><t><r 50>" in conf
    assert "J1 =" not in conf
    assert "Itime =" not in conf
    assert conf.index("HeaderProtectionKey") < conf.index("[Peer]")
    assert "PersistentKeepalive = 25" in conf


def test_render_omits_mtu_when_zero():
    conf = render_client_config(
        private_key="k",
        address="10.8.1.2/32",
        dns=["1.1.1.1"],
        mtu=0,
        obfuscation={"Jc": "3"},
        server_public_key="p",
        preshared_key="s",
        allowed_ips=["0.0.0.0/0"],
        endpoint="h:1",
        keepalive=0,
    )
    assert "MTU" not in conf
    assert "PersistentKeepalive" not in conf
