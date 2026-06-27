#!/usr/bin/env bash
# deploy/pauk/deploy.sh — настройка VPS как тонкого HTTPS relay (П.А.У.К.)
# Запускать с Mac Mini: bash deploy/pauk/deploy.sh
set -e

VPS="${VPS:-root@<public-vps-ip>}"
APP_HOST="${APP_HOST:-<app-host-vpn-ip>}"
PUBLIC_URL="${PUBLIC_URL:-https://<your-domain>}"
LES_DOMAIN="${LES_DOMAIN:-${PUBLIC_URL#https://}}"
LES_DOMAIN="${LES_DOMAIN#http://}"
LES_DOMAIN="${LES_DOMAIN%%/*}"
LES_TRUSTED_CIDR="${LES_TRUSTED_CIDR:-127.0.0.0/8}"
LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CADDY_SRC="$LOCAL/deploy/pauk/Caddyfile"
TMP_CADDY="$(mktemp)"
trap 'rm -f "$TMP_CADDY"' EXIT

case "$VPS $APP_HOST $PUBLIC_URL $LES_DOMAIN" in
  *"<"*)
    echo "Set VPS, APP_HOST and PUBLIC_URL before deploy." >&2
    echo "Example: VPS=root@203.0.113.10 APP_HOST=10.0.0.5 PUBLIC_URL=https://les.example.com LES_TRUSTED_CIDR=10.0.0.0/24 bash deploy/pauk/deploy.sh" >&2
    exit 2
    ;;
esac

echo "==> Проверка app runtime по private network"
ssh "$VPS" "curl -fsS http://$APP_HOST:8050/api/health >/tmp/les_mac_health.json && curl -fsS http://$APP_HOST:8051 >/dev/null"
ssh "$VPS" "cat /tmp/les_mac_health.json"

echo "==> Установка Caddyfile на VPS"
sed \
  -e "s|{{LES_DOMAIN}}|$LES_DOMAIN|g" \
  -e "s|{{LES_APP_HOST}}|$APP_HOST|g" \
  -e "s|{{LES_TRUSTED_CIDR}}|$LES_TRUSTED_CIDR|g" \
  "$CADDY_SRC" > "$TMP_CADDY"
rsync -az "$TMP_CADDY" "$VPS:/tmp/les.Caddyfile"
ssh "$VPS" "caddy validate --config /tmp/les.Caddyfile && install -m 0644 /tmp/les.Caddyfile /etc/caddy/Caddyfile && systemctl reload caddy"

echo "==> Выключение устаревших app-сервисов на VPS"
ssh "$VPS" '
  systemctl disable --now les_proxy sovushka 2>/dev/null || true
  for port in 8050 8051; do
    pid=$(ss -ltnp 2>/dev/null | sed -n "s/.*:$port .*pid=\([0-9]*\).*/\1/p" | head -n 1)
    if [ -n "$pid" ]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
'

echo "==> Проверка"
ssh "$VPS" "ss -ltnp | grep -E ':8050|:8051' && exit 1 || true"
curl -fsS "$PUBLIC_URL/api/health"

echo "==> Готово"
