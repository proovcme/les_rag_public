#!/usr/bin/env bash
# deploy/pauk/deploy.sh — настройка VPS как тонкого HTTPS relay (П.А.У.К.)
# Запускать с Mac Mini: bash deploy/pauk/deploy.sh
set -e

VPS="root@185.185.71.196"
MAC_ZT="10.195.146.98"
LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CADDY_SRC="$LOCAL/deploy/pauk/Caddyfile"

echo "==> Проверка Mac runtime по ZeroTier"
ssh "$VPS" "curl -fsS http://$MAC_ZT:8050/api/health >/tmp/les_mac_health.json && curl -fsS http://$MAC_ZT:8051 >/dev/null"
ssh "$VPS" "cat /tmp/les_mac_health.json"

echo "==> Установка Caddyfile на VPS"
rsync -az "$CADDY_SRC" "$VPS:/tmp/les.Caddyfile"
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
curl -fsS https://les.ovc.me/api/health

echo "==> Готово"
