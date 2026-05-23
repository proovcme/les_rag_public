#!/bin/bash
# =============================================================================
# start_mlx.command — Запуск MLX Native Host для Л.Е.С. v3
# Добавить в Login Items: System Settings → General → Login Items
# =============================================================================
source ~/.zprofile 2>/dev/null
source ~/.zshrc 2>/dev/null
set -u

PROJECT="/Users/ovc/Projects/LES_v2"
LOG="$PROJECT/logs/mlx_host.log"
PID_FILE="$PROJECT/logs/mlx_host.pid"
PORT="${MLX_PORT:-8080}"

mkdir -p "$PROJECT/logs"
cd "$PROJECT"

# Проверяем не запущен ли уже
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null && lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "[MLX] Уже запущен (PID $PID)"
        exit 0
    fi
    rm -f "$PID_FILE"
fi

OLD_LISTENERS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$OLD_LISTENERS" ]; then
    echo "[MLX] Порт $PORT уже слушает другой процесс: $OLD_LISTENERS"
    exit 1
fi

# Создаём/обновляем .venv если нужно (первый раз ~2 мин, потом секунды)
echo "[MLX] Синхронизация окружения..."
if ! uv sync --quiet; then
    echo "[MLX] uv sync не удался; запуск остановлен"
    exit 1
fi

export MLX_MODEL="${MLX_MODEL:-mlx-community/Qwen3.5-9B-MLX-4bit}"
export MLX_VAL_MODEL="${MLX_VAL_MODEL:-mlx-community/Qwen3-4B-Instruct-2507-4bit}"

echo "[MLX] Запускаем MLX Host v3 для Л.Е.С...."
echo "[MLX] Основная:  $MLX_MODEL"
echo "[MLX] Валидатор: $MLX_VAL_MODEL"

# После uv sync запускаем напрямую из .venv, без uv-wrapper в runtime.
nohup "$PROJECT/.venv/bin/python3" mlx_host.py >> "$LOG" 2>&1 &

MLX_PID=$!
echo "$MLX_PID" > "$PID_FILE"

for _ in $(seq 1 90); do
    if ! kill -0 "$MLX_PID" 2>/dev/null; then
        echo "[MLX] Процесс завершился до открытия порта — последние строки лога:"
        tail -30 "$LOG"
        rm -f "$PID_FILE"
        exit 1
    fi
    if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
        echo "[MLX] Запущен. PID: $MLX_PID | Лог: $LOG"
        exit 0
    fi
    sleep 1
done

echo "[MLX] Процесс жив, но /api/health на порту $PORT не ответил за 90с — последние строки лога:"
tail -30 "$LOG"
rm -f "$PID_FILE"
exit 1
