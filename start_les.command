#!/bin/bash
# ═══════════════════════════════════════════════════════
# start_les.command — Запуск всей системы Л.Е.С.
# Запускает: Docker → MLX Host → С.О.В.У.Ш.К.А.
# ═══════════════════════════════════════════════════════
cd "$(dirname "$0")"
LES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$LES_DIR/logs"
SOVUSHKA_PID_FILE="$LOG_DIR/sovushka.pid"
mkdir -p "$LOG_DIR"

echo "═══════════════════════════════════════"
echo "  Л.Е.С. // СТАРТ СИСТЕМЫ"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════"

# ── 1. Docker ──────────────────────────────
echo ""
echo "[1/3] Docker контейнеры..."
cd "$LES_DIR"
docker compose up -d 2>&1 | tail -5
sleep 2

docker ps --format "{{.Names}}" | grep -q "les-proxy"  && echo "  ✓ les-proxy UP"  || echo "  ✗ les-proxy не запустился"
docker ps --format "{{.Names}}" | grep -q "les-qdrant" && echo "  ✓ les-qdrant UP" || echo "  ✗ les-qdrant не запустился"

# ── 2. MLX Host ────────────────────────────
echo ""
echo "[2/3] MLX Host..."
cd "$LES_DIR"

# Убиваем старый процесс по PID файлу
if [ -f "$LOG_DIR/mlx_host.pid" ]; then
    OLD=$(cat "$LOG_DIR/mlx_host.pid")
    kill "$OLD" 2>/dev/null && echo "  Остановлен старый MLX (PID $OLD)"
    rm -f "$LOG_DIR/mlx_host.pid"
fi

uv sync --quiet
nohup uv run python3 mlx_host.py >> "$LOG_DIR/mlx_host.log" 2>&1 &
MLX_PID=$!
echo $MLX_PID > "$LOG_DIR/mlx_host.pid"
sleep 3

curl -sf http://127.0.0.1:8080/api/health > /dev/null 2>&1 \
    && echo "  ✓ MLX Host UP (PID $MLX_PID)" \
    || echo "  ⚠ MLX Host запущен (PID $MLX_PID), ожидает загрузки модели..."

# ── 3. С.О.В.У.Ш.К.А. ─────────────────────
echo ""
echo "[3/3] С.О.В.У.Ш.К.А. (NiceGUI)..."

# Убиваем ВСЁ что держит порт 8051 — гвоздями
echo "  Очищаем порт 8051..."
lsof -ti :8051 | xargs kill -9 2>/dev/null
sleep 1

cd "$LES_DIR"
nohup uv run python3 sovushka_ng.py >> "$LOG_DIR/sovushka.log" 2>&1 &
SOVUSHKA_PID=$!
echo $SOVUSHKA_PID > "$SOVUSHKA_PID_FILE"
sleep 2

kill -0 "$SOVUSHKA_PID" 2>/dev/null \
    && echo "  ✓ С.О.В.У.Ш.К.А. UP (PID $SOVUSHKA_PID) → http://localhost:8051" \
    || echo "  ✗ С.О.В.У.Ш.К.А. упала — смотри logs/sovushka.log"

# ── Итог ───────────────────────────────────
echo ""
echo "═══════════════════════════════════════"
echo "  СИСТЕМА Л.Е.С. ЗАПУЩЕНА"
echo ""
echo "  С.О.В.У.Ш.К.А.: http://localhost:8051"
echo "  les-proxy:       http://localhost:8050"
echo "  MLX Host:        http://127.0.0.1:8080"
echo "═══════════════════════════════════════"
echo "  Логи: tail -f $LOG_DIR/sovushka.log"
echo ""
