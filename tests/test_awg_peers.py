from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.services.awg import (
    AwgError,
    AwgService,
    ServerInterface,
    interface_from_config_path,
    runtime_set_needs_reload,
)


def test_interface_name_follows_awg0_conf_not_legacy_env():
    assert interface_from_config_path(
        "/opt/amnezia/awg/awg0.conf", "wg0",
    ) == "awg0"
    assert interface_from_config_path("/opt/amnezia/awg/wg0.conf", "wg0") == "wg0"


def test_protocol_not_supported_asks_for_reload():
    message = (
        "awg set wg0 peer KEY preshared-key /dev/stdin allowed-ips 10.8.1.2/32 "
        "exited with 1: Unable to modify interface: Protocol not supported"
    )
    assert runtime_set_needs_reload(message)
    assert not runtime_set_needs_reload("Invalid argument")


class _MemAwg(AwgService):
    def __init__(self, fail: str | None) -> None:
        super().__init__(SimpleNamespace(
            awg_container="amnezia-awg2",
            awg_interface="wg0",
            awg_config_path="/opt/amnezia/awg/awg0.conf",
            awg_clients_table_path="",
        ))
        self.fail = fail
        self.calls: list[tuple[str, ...]] = []
        self.conf = "[Interface]\nPrivateKey = x\nListenPort = 443\n"

    async def _exec(self, *argv: str, input_: str | None = None) -> str:
        self.calls.append(argv)
        if argv[:3] == ("awg", "set", "awg0") and self.fail:
            raise AwgError(self.fail)
        if argv[:1] == ("cat",):
            return self.conf
        if argv[:2] == ("sh", "-c") and "printf" in argv[2]:
            self.conf += argv[2]
            return ""
        if argv[:2] == ("sh", "-c") and argv[2].startswith("cat >"):
            return ""
        return ""


@pytest.mark.asyncio
async def test_add_peer_uses_awg0_and_reloads_when_kernel_refuses():
    svc = _MemAwg(
        "awg set awg0 peer exited with 1: "
        "Unable to modify interface: Protocol not supported"
    )
    await svc.add_peer(
        public_key="PUBKEY", preshared_key="PSK", address="10.8.1.2/32",
    )
    assert svc.calls[0][:3] == ("awg", "set", "awg0")
    assert any("awg-quick up" in " ".join(call) for call in svc.calls)
    assert "PUBKEY" in svc.conf


@pytest.mark.asyncio
async def test_add_peer_does_not_reload_on_other_errors():
    svc = _MemAwg("awg set exited with 1: Invalid argument")
    with pytest.raises(AwgError, match="Invalid argument"):
        await svc.add_peer(
            public_key="PUBKEY", preshared_key="PSK", address="10.8.1.2/32",
        )
    assert all("awg-quick" not in " ".join(call) for call in svc.calls)


def test_build_client_config_puts_env_i1_into_conf():
    svc = AwgService(SimpleNamespace(
        awg_endpoint_port=None,
        awg_client_dns=["1.1.1.1"],
        awg_client_mtu=1280,
        awg_client_allowed_ips=["0.0.0.0/0"],
        awg_endpoint_host="vpn.example",
        awg_client_keepalive=25,
        awg_i1="<b 0xc000000001>",
        awg_config_path="/opt/amnezia/awg/awg0.conf",
        awg_interface="awg0",
    ))
    conf = svc.build_client_config(
        server=ServerInterface(public_key="P", listen_port=51820, obfuscation={"Jc": "3"}),
        private_key="c",
        preshared_key="s",
        address="10.8.1.2/32",
    )
    assert "I1 = <b 0xc000000001>" in conf
    assert conf.index("Jc") < conf.index("I1")


class _I1Awg(AwgService):
    def __init__(self) -> None:
        super().__init__(SimpleNamespace(
            awg_container="amnezia-awg2",
            awg_interface="wg0",
            awg_config_path="/opt/amnezia/awg/awg0.conf",
            awg_clients_table_path="",
            awg_i1="<b 0xc000000001>",
        ))
        self.conf = (
            "[Interface]\n"
            "PrivateKey = serverpriv\n"
            "ListenPort = 51820\n"
            "# I1 = commented\n"
            "Jc = 4\n"
            "\n"
            "[Peer]\n"
            "PublicKey = p\n"
        )
        self.reloads = 0

    async def _exec(self, *argv: str, input_: str | None = None) -> str:
        if argv[:1] == ("cat",):
            return self.conf
        if argv[:2] == ("sh", "-c") and "cat >" in argv[2]:
            self.conf = input_ or ""
            return ""
        if argv[:2] == ("sh", "-c") and "awg-quick up" in argv[2]:
            self.reloads += 1
            return ""
        if argv[:2] == ("awg", "pubkey"):
            return "PUB\n"
        if argv[:2] == ("awg", "showconf"):
            return "[Interface]\nPrivateKey = serverpriv\nListenPort = 51820\nJc = 4\n"
        return ""


@pytest.mark.asyncio
async def test_server_interface_writes_missing_i1_and_reloads_once():
    svc = _I1Awg()
    server = await svc.server_interface()
    assert server.obfuscation["I1"] == "<b 0xc000000001>"
    assert "# I1 = commented" in svc.conf
    assert "\nI1 = <b 0xc000000001>\n" in svc.conf
    assert svc.reloads == 1
    await svc.server_interface()
    assert svc.reloads == 1


@pytest.mark.asyncio
async def test_add_peer_keeps_live_set_when_kernel_accepts():
    svc = _MemAwg(None)
    await svc.add_peer(
        public_key="PUBKEY", preshared_key="PSK", address="10.8.1.2/32",
    )
    assert svc.calls[0][:3] == ("awg", "set", "awg0")
    assert all("awg-quick" not in " ".join(call) for call in svc.calls)
    assert "PUBKEY" in svc.conf
