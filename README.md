# AmneziaWG Telegram Bot

Telegram-бот для управления профилями self-hosted **AmneziaWG**.
Бот живёт на том же сервере, где развёрнут AmneziaWG (в Docker-контейнере),
и общается с ним через `docker exec`. Доступ — только для администраторов,
указанных по telegram-id.

## Возможности

- ➕ создать профиль: генерация ключей, выделение IP, добавление peer,
  выдача `.conf` и QR-кода прямо в чат
- 📋 список профилей с карточкой (адрес, дата создания, автор)
- 🗑 удалить профиль (`awg set ... peer ... remove` + правка конфига)
- 📊 статистика по интерфейсу: онлайн/офлайн, трафик, последний handshake
- 🔒 авторизация по `ADMIN_IDS` через middleware
- 🐳 параметры обфускации (`Jc/Jmin/Jmax/S1/S2/H1..H4`) автоматически
  переносятся в клиентский конфиг — это то, что делает AmneziaWG отличным от ванильного WireGuard

## Требования

- Сервер с уже работающим AmneziaWG в Docker (контейнер по умолчанию `amnezia-awg`)
- Доступ к docker socket (бот использует `docker exec`)
- Python 3.11+ (для native-варианта)

## Установка — Docker Compose (рекомендуется)

```bash
git clone <repo> awg-bot && cd awg-bot
cp .env.example .env
nano .env   # заполнить BOT_TOKEN и ADMIN_IDS
docker compose up -d --build
docker compose logs -f awg-bot
```

Контейнер бота монтирует `/var/run/docker.sock`, чтобы вызывать
`docker exec amnezia-awg awg …`.

## Установка — native + systemd

```bash
sudo bash scripts/install.sh
sudo nano /opt/awg-bot/.env
sudo systemctl enable --now awg-bot
sudo journalctl -u awg-bot -f
```

## Конфигурация (.env)

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | токен из @BotFather |
| `ADMIN_IDS` | список telegram-id через запятую |
| `AWG_CONTAINER` | имя docker-контейнера с AmneziaWG |
| `AWG_INTERFACE` | имя wg-интерфейса внутри контейнера (по умолчанию `wg0`) |
| `AWG_CONFIG_PATH` | путь к конфигу внутри контейнера |
| `AWG_ENDPOINT_HOST` | публичный host/IP, который попадёт в клиентский `Endpoint` |
| `AWG_ENDPOINT_PORT` | порт; если пусто — берётся `ListenPort` сервера |
| `AWG_CLIENT_SUBNET` | подсеть для клиентов |
| `AWG_CLIENT_DNS` | DNS-серверы клиента |
| `AWG_CLIENT_ALLOWED_IPS` | `AllowedIPs` клиента (по умолчанию весь трафик) |
| `AWG_CLIENT_KEEPALIVE` | PersistentKeepalive (`0` чтобы отключить) |
| `DB_PATH` | путь к SQLite-файлу с метаданными |
| `LINK_URL` | (опц.) URL, который покажет кнопка в главном меню |
| `LINK_BUTTON_TEXT` | (опц.) текст кнопки-ссылки, по умолчанию `🔗 Ссылка` |

## Команды бота

| Команда | Действие |
|---------|----------|
| `/start`, `/help` | приветствие, главное меню |
| `/new <имя>` | создать новый профиль (имя: `[A-Za-z0-9_-]{2,32}`) |
| `/list` | список профилей |
| `/stats` | статистика по `awg show <iface> dump` |

В меню те же действия доступны кнопками.

## Структура

```
bot/
├── main.py              # точка входа
├── config.py            # pydantic-settings
├── db.py                # aiosqlite-обёртка
├── keyboards.py         # inline + reply клавиатуры
├── middlewares/auth.py  # доступ по ADMIN_IDS
├── handlers/            # common, profiles, stats
└── services/awg.py      # docker exec + парсинг wg-quick конфига
scripts/
├── install.sh           # установка в /opt/awg-bot + systemd
└── awg-bot.service      # systemd unit
```

## Мультитенантность

Каждый telegram-id из `ADMIN_IDS` ведёт собственный изолированный список
профилей:

- в БД имя профиля сохраняется как `<имя>_<telegram_id>` — это даёт
  раздельное пространство имён и позволяет всем админам использовать
  одинаковые «человеческие» имена (`home`, `phone`, `laptop`);
- `/list`, `/stats` и кнопки меню показывают только профили того, кто их вызвал;
- в callback’ах проверяется владелец: даже если кто-то подменит `id` в
  callback_data, чужой профиль не откроется (см.
  `_get_profile_from_cb` в [bot/handlers/profiles.py](bot/handlers/profiles.py));
- IP-адреса остаются глобально уникальными — аллокатор смотрит на всю таблицу.

В UI и в `.conf` суффикс с telegram-id скрыт (карточка показывает «внутреннее
имя» для отладки на сервере).

## Безопасность

- Любой пользователь без `telegram-id` в `ADMIN_IDS` получит `⛔️ Доступ запрещён`
- `.env` исключён из git
- Бот никогда не отправляет приватные ключи никому, кроме админа —
  владельца профиля

## Синхронизация с GUI AmneziaVPN

GUI AmneziaVPN читает список клиентов из отдельного JSON-файла
(`clientsTable`), а не из `wg0.conf`. Чтобы профили, созданные через бота,
появлялись в основном окне «Управление пользователями», бот синхронизирует
этот файл:

- при создании профиля — добавляет запись `{clientId, userData{clientName, creationDate}}`;
- при удалении — убирает её;
- при старте делает бэкфилл: переносит все профили из БД, если их там ещё нет.

Имя клиента в GUI — `<имя> [tg:<telegram_id>]`, чтобы было видно, кто из
админов его создал.

Если в вашем образе AmneziaWG `clientsTable` лежит в другом месте, найдите
его и поправьте `AWG_CLIENTS_TABLE_PATH` в `.env`:

```bash
docker exec amnezia-awg find / -name 'clientsTable*' 2>/dev/null
```

Чтобы отключить синхронизацию — оставьте `AWG_CLIENTS_TABLE_PATH=` пустым.

## Известные ограничения

- Бот ожидает «классический» серверный wg-quick конфиг с одной секцией
  `[Interface]` и нулём или более `[Peer]`
- IP-аллокатор работает в IPv4 и пропускает `.0`, `.1` и `.255`
- Нет ротации/массового удаления — добавьте при необходимости
