from __future__ import annotations

from functools import lru_cache
from ipaddress import IPv4Network
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    admin_ids: list[int] = Field(alias="ADMIN_IDS", default_factory=list)

    awg_container: str = Field(alias="AWG_CONTAINER", default="amnezia-awg")
    awg_interface: str = Field(alias="AWG_INTERFACE", default="wg0")
    awg_config_path: str = Field(
        alias="AWG_CONFIG_PATH", default="/opt/amnezia/awg/wg0.conf"
    )

    awg_endpoint_host: str = Field(alias="AWG_ENDPOINT_HOST")
    awg_endpoint_port: int | None = Field(alias="AWG_ENDPOINT_PORT", default=None)

    awg_client_subnet: IPv4Network = Field(
        alias="AWG_CLIENT_SUBNET", default=IPv4Network("10.8.1.0/24")
    )
    awg_client_dns: list[str] = Field(
        alias="AWG_CLIENT_DNS", default_factory=lambda: ["1.1.1.1", "1.0.0.1"]
    )
    awg_client_allowed_ips: list[str] = Field(
        alias="AWG_CLIENT_ALLOWED_IPS",
        default_factory=lambda: ["0.0.0.0/0", "::/0"],
    )
    awg_client_keepalive: int = Field(alias="AWG_CLIENT_KEEPALIVE", default=25)

    db_path: Path = Field(alias="DB_PATH", default=Path("awg-bot.db"))

    @field_validator("admin_ids", "awg_client_dns", "awg_client_allowed_ips", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
