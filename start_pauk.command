#!/bin/bash
# ═══════════════════════════════════════════════════════
# start_pauk.command — П.А.У.К. аварийный SSH reverse tunnel
#
# Основной транспорт: ZeroTier. В штатном режиме Caddy на VPS проксирует
# les.ovc.me напрямую на Mac Mini:
#   /api/* -> 10.195.146.98:8050
#   /*     -> 10.195.146.98:8051
#
# Туннель нужен только как ручной аварийный режим, если ZeroTier недоступен:
# он публикует Mac :8050/:8051 как VPS localhost :8050/:8051.
# На время аварии Caddyfile нужно переключить на 127.0.0.1.
# ═══════════════════════════════════════════════════════
LES_DIR="$HOME/Projects/LES_v2"
LOG_DIR="$LES_DIR/logs"
PID_FILE="$LOG_DIR/pauk.pid"
LOG_FILE="$LOG_DIR/pauk.log"
VPS="root@185.185.71.196"
KEY="$HOME/.ssh/id_ed25519"

mkdir -p "$LOG_DIR"

echo "═══════════════════════════════════════"
echo "  П.А.У.К. // РЕЗЕРВНЫЙ SSH-ТУННЕЛЬ"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════"

if [ "${LES_ENABLE_SSH_TUNNEL:-0}" != "1" ]; then
    echo "  Основной транспорт сейчас ZeroTier, SSH-туннель выключен."
    echo "  Для аварийного режима запусти:"
    echo "    LES_ENABLE_SSH_TUNNEL=1 $0"
    echo ""
    echo "  Проверка ZeroTier с VPS:"
    echo "    ssh $VPS 'curl -s http://10.195.146.98:8050/api/health'"
    echo "    ssh $VPS 'curl -I http://10.195.146.98:8051'"
    echo "═══════════════════════════════════════"
    exit 0
fi

# Убиваем старый процесс
if [ -f "$PID_FILE" ]; then
    OLD=$(cat "$PID_FILE")
    kill "$OLD" 2>/dev/null && echo "  Остановлен старый туннель (PID $OLD)"
    rm -f "$PID_FILE"
fi

# Проверяем что SSH-ключ есть
if [ ! -f "$KEY" ]; then
    echo "  ✗ SSH ключ не найден: $KEY"
    exit 1
fi

# Запуск туннеля. В Codex/launchd обычный background child может умереть
# вместе с родительским shell, поэтому ssh должен демонизироваться сам.
ssh -f -n -N \
    -i "$KEY" \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=no \
    -R 127.0.0.1:8050:127.0.0.1:8050 \
    -R 127.0.0.1:8051:127.0.0.1:8051 \
    "$VPS" >> "$LOG_FILE" 2>&1

sleep 2
PAUK_PID=$(pgrep -f "ssh -f -n -N.*127.0.0.1:8050:127.0.0.1:8050" | head -1)
[ -n "$PAUK_PID" ] && echo "$PAUK_PID" > "$PID_FILE"

if [ -n "$PAUK_PID" ] && kill -0 "$PAUK_PID" 2>/dev/null; then
    echo "  ✓ П.А.У.К. UP (PID $PAUK_PID)"
    echo ""
    echo "  VPS 127.0.0.1:8050/:8051 → Mac Mini les-proxy/UI"
    echo "  Не забудь временно переключить Caddy на 127.0.0.1."
    echo ""
    echo "  Проверка: ssh $VPS 'curl -s http://127.0.0.1:8050/api/health'"
else
    echo "  ✗ Туннель упал — смотри logs/pauk.log"
    cat "$LOG_FILE" | tail -10
fi

echo "═══════════════════════════════════════"
