#!/bin/bash
# stop_les.command — Остановка системы Л.Е.С.

cd "$(dirname "$0")"
LES_DIR="$HOME/Projects/LES_v2"
LOG_DIR="$LES_DIR/logs"

echo "═══════════════════════════════════════"
echo "  Л.Е.С. // ОСТАНОВКА СИСТЕМЫ"
echo "═══════════════════════════════════════"

# С.О.В.У.Ш.К.А.
if [ -f "$LOG_DIR/sovushka.pid" ]; then
    PID=$(cat "$LOG_DIR/sovushka.pid")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "  ✓ С.О.В.У.Ш.К.А. остановлена (PID $PID)"
    fi
    rm -f "$LOG_DIR/sovushka.pid"
fi

# MLX Host
if [ -f "$LOG_DIR/mlx_host.pid" ]; then
    PID=$(cat "$LOG_DIR/mlx_host.pid")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "  ✓ MLX Host остановлен (PID $PID)"
    fi
    rm -f "$LOG_DIR/mlx_host.pid"
fi

# Docker
cd "$LES_DIR"
docker compose stop 2>&1 | tail -3
echo "  ✓ Docker контейнеры остановлены"
echo "═══════════════════════════════════════"
