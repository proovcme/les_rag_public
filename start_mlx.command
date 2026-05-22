#!/bin/bash
# =============================================================================
# start_mlx.command — Запуск MLX Native Host для Л.Е.С. v3
# Добавить в Login Items: System Settings → General → Login Items
# =============================================================================
source ~/.zprofile 2>/dev/null
source ~/.zshrc 2>/dev/null

PROJECT="~/Projects/LES_v2"
LOG="$PROJECT/logs/mlx_host.log"
PID_FILE="$PROJECT/logs/mlx_host.pid"

mkdir -p "$PROJECT/logs"
cd "$PROJECT"

# Проверяем не запущен ли уже
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "[MLX] Уже запущен (PID $PID)"
        exit 0
    fi
fi

# Создаём/обновляем .venv если нужно (первый раз ~2 мин, потом секунды)
echo "[MLX] Синхронизация окружения..."
uv sync --quiet

export MLX_MODEL="${MLX_MODEL:-mlx-community/Qwen3-14B-4bit}"
export MLX_VAL_MODEL="${MLX_VAL_MODEL:-mlx-community/Qwen3-4B-4bit}"

echo "[MLX] Запускаем MLX Host v3 для Л.Е.С...."
echo "[MLX] Основная:  $MLX_MODEL"
echo "[MLX] Валидатор: $MLX_VAL_MODEL"

# uv run теперь использует .venv проекта — никаких --with
uv run python3 mlx_host.py >> "$LOG" 2>&1 &

echo $! > "$PID_FILE"
echo "[MLX] Запущен. PID: $(cat $PID_FILE) | Лог: $LOG"
