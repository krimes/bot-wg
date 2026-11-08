from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.services.awg import (
    AwgError,
    AwgService,
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


@pytest.mark.asyncio
async def test_add_peer_keeps_live_set_when_kernel_accepts():
    svc = _MemAwg(None)
    await svc.add_peer(
        public_key="PUBKEY", preshared_key="PSK", address="10.8.1.2/32",
    )
    assert svc.calls[0][:3] == ("awg", "set", "awg0")
    assert all("awg-quick" not in " ".join(call) for call in svc.calls)
    assert "PUBKEY" in svc.conf
