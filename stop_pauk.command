#!/bin/bash
# ═══════════════════════════════════════════════════════
# stop_pauk.command — Остановка П.А.У.К. туннеля
# ═══════════════════════════════════════════════════════
LES_DIR="$HOME/Projects/LES_v2"
PID_FILE="$LES_DIR/logs/pauk.pid"

echo "  П.А.У.К. // ОСТАНОВКА"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "  ✓ Туннель остановлен (PID $PID)"
    else
        echo "  ⚠ Процесс $PID уже не запущен"
    fi
    rm -f "$PID_FILE"
else
    # Fallback: убиваем по паттерну
    pkill -f "ssh.*127.0.0.1:8050:localhost:8050.*185.185.71.196" && echo "  ✓ Туннель остановлен" || echo "  ⚠ Туннель не найден"
fi
