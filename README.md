# AmneziaWG Telegram Bot

Telegram-бот для управления профилями self-hosted **AmneziaWG** и клиентами
**Happ** (VLESS через панель 3X-UI).
Бот живёт на том же сервере, где развёрнут AmneziaWG (в Docker-контейнере),
и общается с ним через `docker exec`. Клиентов Happ создаёт через REST API 3X-UI.
Доступ — только для администраторов, указанных по telegram-id.

## Возможности

- ➕ создать профиль WG: генерация ключей, выделение IP, добавление peer,
  выдача `.conf` и QR-кода прямо в чат
- ➕ создать клиента Happ: UUID в inbound 3X-UI, `vless://` + QR для приложения Happ
- 📋 общий список профилей (WG и Happ) с карточкой
- 🗑 удалить профиль (peer из AmneziaWG или клиент с панели 3X-UI)
- 📊 статистика WG по `awg show` и трафик Happ из 3X-UI
- 🔒 авторизация по `ADMIN_IDS` через middleware
- 🐳 параметры AmneziaWG **3.1** (`Jc/Jmin/Jmax`, `S1–S4`, `H1–H4`, `I1–I5`,
  `HeaderProtectionKey`, `ContentPaddingAddition`, таймеры, `RandomTrailers`,
  `DisableCookies`) копируются в клиентский `.conf`; MTU по умолчанию 1280

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
| `ADMIN_IDS` | список telegram-id через запятую (всегда имеют доступ) |
| `MAIN_ADMIN_ID` | главный админ: пользователи + рассылка. Пусто = первый `ADMIN_IDS` |
| `AWG_CONTAINER` | имя docker-контейнера с AmneziaWG |
| `AWG_INTERFACE` | имя wg-интерфейса внутри контейнера (по умолчанию `wg0`) |
| `AWG_CONFIG_PATH` | путь к конфигу внутри контейнера |
| `AWG_ENDPOINT_HOST` | публичный host/IP, который попадёт в клиентский `Endpoint` |
| `AWG_ENDPOINT_PORT` | порт; если пусто — берётся `ListenPort` сервера |
| `AWG_CLIENT_SUBNET` | подсеть для клиентов |
| `AWG_CLIENT_DNS` | DNS-серверы клиента |
| `AWG_CLIENT_ALLOWED_IPS` | `AllowedIPs` клиента (по умолчанию весь трафик) |
| `AWG_CLIENT_KEEPALIVE` | PersistentKeepalive (`0` чтобы отключить) |
| `AWG_CLIENT_MTU` | MTU в клиентском `.conf` (по умолчанию `1280` для AWG 3.1; `0` — не писать) |
| `DB_PATH` | путь к SQLite-файлу с метаданными |
| `LINK_URL` | (опц.) URL, который покажет кнопка в главном меню |
| `LINK_BUTTON_TEXT` | (опц.) текст кнопки-ссылки, по умолчанию `🔗 Ссылка` |
| `XUI_HOST` | URL панели 3X-UI (`http://host.docker.internal:2053`). Пусто — Happ выключен |
| `XUI_WEB_BASE_PATH` | секретный путь панели, если задан |
| `XUI_API_TOKEN` | API-токен панели (предпочтительнее логина) |
| `XUI_USERNAME` / `XUI_PASSWORD` | логин панели, если токена нет |
| `XUI_INBOUND_ID` | ID inbound VLESS+Reality, в который бот добавляет клиентов |
| `XUI_CLIENT_HOST` | публичный хост в `vless://`; пусто — `AWG_ENDPOINT_HOST` |
| `XUI_SUB_BASE` | (опц.) база подписки, например `https://ip:2096/sub` |
| `XUI_TLS_VERIFY` | проверка TLS сертификата панели, по умолчанию `true` |

## AmneziaWG 3.1

Клиентский `.conf` собирается под стандарт 3.1:

- обфускация берётся из **файла** `wg0.conf` **и** `awg showconf` (union:
  runtime перекрывает, файл добирает `I1–I5` / `HeaderProtectionKey`, которые
  старый `showconf` часто не печатает);
- в конфиг попадают `HeaderProtectionKey`, `ContentPaddingAddition`, таймеры,
  `RandomTrailers`, `DisableCookies`; флаги пишутся как `on`/`off`;
- устаревшие `J1`/`J2`/`J3`/`Itime` отбрасываются — клиент 3.1 их отвергает;
- `HeaderProtectionKey` в hex (UAPI) переводится в base64;
- MTU по умолчанию **1280**.

Сервер и приложение-клиент тоже должны быть 3.1: `HeaderProtectionKey` и
`RandomTrailers` обязаны совпадать на обеих сторонах. Если на сервере этих
ключей нет, бот их не выдумает — конфиг останется 2.0-совместимым.

## Пользователи и рассылка

Доступ к боту:

- все `ADMIN_IDS` из `.env` (нельзя выключить из чата);
- пользователи в таблице `bot_users`, которых добавил **главный админ**.

Главный админ — `MAIN_ADMIN_ID`, иначе первый `ADMIN_IDS`. У него в меню
отдельная секция **👥 Пользователи** и **📣 Рассылка**.

- добавить: кнопка «Добавить», переслать сообщение человека или
  `/useradd 123456789 Имя`;
- выключить / удалить — только записи из базы;
- рассылка копирует любое сообщение (текст, фото, файл) всем, у кого есть
  доступ, кроме отправителя. Человек должен хотя бы раз нажать /start у бота.

У каждого свой список профилей WG/Happ, как и раньше.

## Happ / 3X-UI

Бот **не ставит** панель. На сервере уже должен быть 3X-UI с inbound
**VLESS + Reality** (обычно порт 443, flow `xtls-rprx-vision`).

1. В панели: **Inbounds** — запомните ID нужного inbound.
2. **Settings → Security → API Token** — создайте токен (или используйте логин).
3. В `.env` бота заполните `XUI_HOST`, `XUI_INBOUND_ID`, токен или логин,
   `XUI_CLIENT_HOST` (публичный IP/домен сервера).
4. Если бот в Docker, а панель на хосте:
   `XUI_HOST=http://host.docker.internal:ПОРТ_ПАНЕЛИ`
5. `/happ phone` или кнопка **➕ Новый Happ** — в чат придут `vless://` и QR.
   В Happ: **+ → импорт из буфера / QR**.

WG и Happ независимы: пустой `XUI_HOST` не ломает AmneziaWG.

## Команды бота

| Команда | Действие |
|---------|----------|
| `/start`, `/help` | приветствие, главное меню |
| `/new <имя>` | создать профиль AmneziaWG (имя: `[A-Za-z0-9_-]{2,32}`) |
| `/happ <имя>` | создать клиента Happ в 3X-UI |
| `/list` | список профилей WG и Happ |
| `/stats` | статистика WG и трафик Happ |
| `/users` | *(главный админ)* список пользователей бота |
| `/useradd <id>` | *(главный админ)* добавить пользователя по Telegram ID |
| `/broadcast` | *(главный админ)* рассылка всем, у кого есть доступ |

В меню те же действия доступны кнопками.

## Структура

```
bot/
├── main.py              # точка входа
├── config.py            # pydantic-settings
├── db.py                # aiosqlite-обёртка
├── keyboards.py         # inline + reply клавиатуры
├── middlewares/auth.py  # доступ по ADMIN_IDS
├── handlers/            # common, profiles, happ, stats
└── services/
    ├── awg.py           # docker exec + парсинг wg-quick конфига
    └── xui.py           # REST 3X-UI, сборка vless:// для Happ
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
