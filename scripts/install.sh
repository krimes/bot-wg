#!/usr/bin/env bash
# Установка AmneziaWG Telegram Bot на сервер (native + systemd).
# Использование: запустить от root в распакованной копии репозитория.
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/awg-bot}"
SERVICE_NAME="awg-bot"

if [[ $EUID -ne 0 ]]; then
    echo "Этот скрипт нужно запускать от root." >&2
    exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Устанавливаю в $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r "$SRC_DIR/bot" "$INSTALL_DIR/"
cp "$SRC_DIR/requirements.txt" "$INSTALL_DIR/"
[[ -f "$INSTALL_DIR/.env" ]] || cp "$SRC_DIR/.env.example" "$INSTALL_DIR/.env"

echo "==> Готовлю virtualenv"
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

mkdir -p /var/lib/awg-bot

echo "==> Устанавливаю systemd unit"
cp "$SRC_DIR/scripts/awg-bot.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload

cat <<EOF

Установка завершена.

1) Отредактируйте конфиг:    nano $INSTALL_DIR/.env
2) Запустите:                 systemctl enable --now $SERVICE_NAME
3) Логи:                      journalctl -u $SERVICE_NAME -f

EOF
