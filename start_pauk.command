#!/bin/bash
# ═══════════════════════════════════════════════════════
# start_pauk.command — П.А.У.К. SSH reverse tunnel
# Mac Mini → VPS → les.ovc.me
# ═══════════════════════════════════════════════════════
LES_DIR="$HOME/Projects/LES_v2"
LOG_DIR="$LES_DIR/logs"
PID_FILE="$LOG_DIR/pauk.pid"
LOG_FILE="$LOG_DIR/pauk.log"
VPS="root@185.185.71.196"
KEY="$HOME/.ssh/id_ed25519"

mkdir -p "$LOG_DIR"

echo "═══════════════════════════════════════"
echo "  П.А.У.К. // ЗАПУСК ТУННЕЛЯ"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════"

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

# Запуск туннеля
nohup ssh -N \
    -i "$KEY" \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=no \
    -R 8050:localhost:8050 \
    -R 8051:localhost:8051 \
    "$VPS" >> "$LOG_FILE" 2>&1 &

PAUK_PID=$!
echo $PAUK_PID > "$PID_FILE"
sleep 2

if kill -0 "$PAUK_PID" 2>/dev/null; then
    echo "  ✓ П.А.У.К. UP (PID $PAUK_PID)"
    echo ""
    echo "  les.ovc.me → VPS :8050/:8051 → Mac Mini"
    echo ""
    echo "  Проверка: curl https://les.ovc.me/api/health"
else
    echo "  ✗ Туннель упал — смотри logs/pauk.log"
    cat "$LOG_FILE" | tail -10
fi

echo "═══════════════════════════════════════"
