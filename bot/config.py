from __future__ import annotations

from functools import lru_cache
from ipaddress import IPv4Network
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


# NoDecode отключает встроенный JSON-парсер pydantic-settings для list[...]-полей,
# чтобы значения вида "1.1.1.1,1.0.0.1" из .env попадали в наш _split_csv валидатор
# как обычная строка, а не отвергались как невалидный JSON.
CSVList = Annotated[list[str], NoDecode]
CSVIntList = Annotated[list[int], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    admin_ids: CSVIntList = Field(alias="ADMIN_IDS", default_factory=list)
    # Если пусто — главный админ = первый ID в ADMIN_IDS.
    main_admin_id: int | None = Field(alias="MAIN_ADMIN_ID", default=None)

    awg_container: str = Field(alias="AWG_CONTAINER", default="amnezia-awg")
    awg_interface: str = Field(alias="AWG_INTERFACE", default="wg0")
    awg_config_path: str = Field(
        alias="AWG_CONFIG_PATH", default="/opt/amnezia/awg/wg0.conf"
    )
    # Путь к clientsTable внутри контейнера — это JSON-список клиентов,
    # который читает GUI AmneziaVPN, чтобы показывать «подключённые устройства».
    # Пустая строка отключает синхронизацию.
    awg_clients_table_path: str = Field(
        alias="AWG_CLIENTS_TABLE_PATH", default="/opt/amnezia/awg/clientsTable"
    )

    awg_endpoint_host: str = Field(alias="AWG_ENDPOINT_HOST")
    awg_endpoint_port: int | None = Field(alias="AWG_ENDPOINT_PORT", default=None)

    awg_client_subnet: IPv4Network = Field(
        alias="AWG_CLIENT_SUBNET", default=IPv4Network("10.8.1.0/24")
    )
    awg_client_dns: CSVList = Field(
        alias="AWG_CLIENT_DNS", default_factory=lambda: ["1.1.1.1", "1.0.0.1"]
    )
    awg_client_allowed_ips: CSVList = Field(
        alias="AWG_CLIENT_ALLOWED_IPS",
        default_factory=lambda: ["0.0.0.0/0", "::/0"],
    )
    awg_client_keepalive: int = Field(alias="AWG_CLIENT_KEEPALIVE", default=25)
    # 1280 — рекомендация AmneziaWG 3.1 (S4 и RandomTrailers иначе фрагментируют).
    # 0 — не писать MTU в клиентский .conf.
    awg_client_mtu: int = Field(alias="AWG_CLIENT_MTU", default=1280)

    db_path: Path = Field(alias="DB_PATH", default=Path("awg-bot.db"))

    # Опциональная ссылка-кнопка в главном меню (например, на скачивание
    # клиента или на чат поддержки). Если LINK_URL пуст — кнопка не показывается.
    link_url: str | None = Field(alias="LINK_URL", default=None)
    link_button_text: str = Field(alias="LINK_BUTTON_TEXT", default="🔗 Ссылка")

    # --- 3X-UI / Happ ---
    # Если XUI_HOST пуст — кнопки Happ отвечают «панель не настроена», WG не трогаем.
    xui_host: str | None = Field(alias="XUI_HOST", default=None)
    xui_web_base_path: str = Field(alias="XUI_WEB_BASE_PATH", default="")
    xui_username: str | None = Field(alias="XUI_USERNAME", default=None)
    xui_password: str | None = Field(alias="XUI_PASSWORD", default=None)
    xui_api_token: str | None = Field(alias="XUI_API_TOKEN", default=None)
    xui_inbound_id: int | None = Field(alias="XUI_INBOUND_ID", default=None)
    xui_client_host: str | None = Field(alias="XUI_CLIENT_HOST", default=None)
    xui_sub_base: str | None = Field(alias="XUI_SUB_BASE", default=None)
    xui_tls_verify: bool = Field(alias="XUI_TLS_VERIFY", default=True)

    # Веб-выдача первого WG-конфига. Пустой WEB_PASSWORD — сайт не поднимается.
    web_password: str | None = Field(alias="WEB_PASSWORD", default=None)
    web_secret: str | None = Field(alias="WEB_SECRET", default=None)
    web_host: str = Field(alias="WEB_HOST", default="0.0.0.0")
    web_port: int = Field(alias="WEB_PORT", default=8080)

    @field_validator("admin_ids", "awg_client_dns", "awg_client_allowed_ips", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator(
        "awg_endpoint_port",
        "link_url",
        "xui_host",
        "xui_username",
        "xui_password",
        "xui_api_token",
        "xui_inbound_id",
        "xui_client_host",
        "xui_sub_base",
        "main_admin_id",
        "web_password",
        "web_secret",
        mode="before",
    )
    @classmethod
    def _empty_str_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    def is_main_admin(self, user_id: int) -> bool:
        from bot.access import is_main_admin as _is_main
        return _is_main(user_id, self.admin_ids, self.main_admin_id)

    def resolved_main_admin_id(self) -> int | None:
        from bot.access import resolve_main_admin_id
        return resolve_main_admin_id(self.admin_ids, self.main_admin_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
