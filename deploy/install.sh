#!/usr/bin/env bash
# Установка и обновление osop.exe на VPS (Debian / Ubuntu).
#
#   curl -fsSL https://raw.githubusercontent.com/ashirovazizz/osop.exe/main/deploy/install.sh -o install.sh
#   sudo bash install.sh                      # сайт на http://<IP сервера>:8081
#   sudo bash install.sh osop.example.ru      # сайт на http://osop.example.ru
#
# Переменные окружения (необязательно):
#   OSOP_PORT=8081          внешний порт, если домен не указан
#   OSOP_PASSWORD=секрет    закрыть сайт паролем (логин: dh)
#   OSOP_EMAIL=you@mail.ru  с доменом: получить HTTPS-сертификат Let's Encrypt
#
# Скрипт можно запускать повторно: он обновит код и перезапустит сервис.
# Другие сайты в nginx он не трогает.
set -euo pipefail

DOMAIN="${1:-}"
PUBLIC_PORT="${OSOP_PORT:-8081}"
APP=/opt/osop-exe
REPO=https://github.com/ashirovazizz/osop.exe.git
APP_PORT=8080
SITE=/etc/nginx/sites-available/osop-exe

[ "$(id -u)" -eq 0 ] || { echo "Запустите через sudo"; exit 1; }
command -v apt-get >/dev/null || { echo "Нужен Debian или Ubuntu (apt-get)"; exit 1; }

echo "==> пакеты: git, python3, nginx"
apt-get update -qq
apt-get install -y -qq git python3 nginx openssl >/dev/null
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
  || { echo "Нужен Python 3.8 или новее"; exit 1; }

echo "==> пользователь osop и код в $APP"
id osop >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin osop
if [ -d "$APP/.git" ]; then
  runuser -u osop -- git -C "$APP" pull --ff-only -q
else
  git clone -q "$REPO" "$APP"
fi
chown -R osop:osop "$APP"

echo "==> сервис systemd"
cat > /etc/systemd/system/osop-exe.service <<EOF
[Unit]
Description=osop.exe
After=network.target

[Service]
User=osop
WorkingDirectory=$APP
Environment=OSOP_HOST=127.0.0.1
Environment=OSOP_PORT=$APP_PORT
ExecStart=/usr/bin/python3 $APP/server.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q osop-exe
systemctl restart osop-exe

echo "==> nginx"
AUTH=""
if [ -n "${OSOP_PASSWORD:-}" ]; then
  printf 'dh:%s\n' "$(openssl passwd -apr1 "$OSOP_PASSWORD")" > /etc/nginx/.osop-htpasswd
  chmod 640 /etc/nginx/.osop-htpasswd
  chown root:www-data /etc/nginx/.osop-htpasswd
  AUTH='auth_basic "osop.exe"; auth_basic_user_file /etc/nginx/.osop-htpasswd;'
fi
if [ -n "$DOMAIN" ]; then
  LISTEN="listen 80;"
  NAME="server_name $DOMAIN;"
else
  LISTEN="listen $PUBLIC_PORT;"
  NAME="server_name _;"
fi
cat > "$SITE" <<EOF
server {
    $LISTEN
    $NAME
    $AUTH
    client_max_body_size 128k;

    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF
ln -sf "$SITE" /etc/nginx/sites-enabled/osop-exe
nginx -t -q
systemctl reload nginx

if [ -z "$DOMAIN" ] && command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  echo "==> открываю порт $PUBLIC_PORT в ufw"
  ufw allow "$PUBLIC_PORT/tcp" >/dev/null
fi

if [ -n "$DOMAIN" ] && [ -n "${OSOP_EMAIL:-}" ]; then
  echo "==> HTTPS через Let's Encrypt"
  apt-get install -y -qq certbot python3-certbot-nginx >/dev/null
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$OSOP_EMAIL" --redirect
fi

sleep 1
if curl -fsS "http://127.0.0.1:$APP_PORT/api/feed" >/dev/null; then
  echo "==> сервис отвечает"
else
  echo "!!! сервис не отвечает, смотрите: journalctl -u osop-exe -n 50"; exit 1
fi

IP="$(curl -fsS4 --max-time 5 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
if [ -n "$DOMAIN" ]; then
  echo "Готово: http${OSOP_EMAIL:+s}://$DOMAIN"
else
  echo "Готово: http://$IP:$PUBLIC_PORT"
fi
echo "Лента: $APP/data/feed.json   Логи: journalctl -u osop-exe"
