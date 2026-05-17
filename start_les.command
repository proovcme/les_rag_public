#!/bin/bash
# ═══════════════════════════════════════════════════════
# start_les.command — Запуск всей системы Л.Е.С.
# Запускает: Docker → MLX Host → С.О.В.У.Ш.К.А.
# ═══════════════════════════════════════════════════════

cd "$(dirname "$0")"
LES_DIR="$HOME/Projects/LES_v2"
LOG_DIR="$LES_DIR/logs"
SOVUSHKA_PID="$LOG_DIR/sovushka.pid"

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

# Проверка
if docker ps --format "{{.Names}}" | grep -q "les-proxy"; then
    echo "  ✓ les-proxy UP"
else
    echo "  ✗ les-proxy не запустился — проверь docker compose"
fi

if docker ps --format "{{.Names}}" | grep -q "les-qdrant"; then
    echo "  ✓ les-qdrant UP"
else
    echo "  ✗ les-qdrant не запустился"
fi

# ── 2. MLX Host ────────────────────────────
echo ""
echo "[2/3] MLX Host..."
if [ -f "$LES_DIR/start_mlx.command" ]; then
    # Запускаем в фоне через uv
    cd "$LES_DIR"
    nohup uv run python3 mlx_host.py >> "$LOG_DIR/mlx_host.log" 2>&1 &
    MLX_PID=$!
    echo $MLX_PID > "$LOG_DIR/mlx_host.pid"
    sleep 3
    # Проверка
    if curl -sf http://127.0.0.1:8080/api/health > /dev/null 2>&1; then
        echo "  ✓ MLX Host UP (PID $MLX_PID)"
    else
        echo "  ⚠ MLX Host запущен (PID $MLX_PID), ожидает загрузки модели..."
    fi
else
    echo "  ⚠ start_mlx.command не найден — MLX Host не запущен"
fi

# ── 3. С.О.В.У.Ш.К.А. ─────────────────────
echo ""
echo "[3/3] С.О.В.У.Ш.К.А. (NiceGUI)..."

# Убиваем старый процесс если есть
if [ -f "$SOVUSHKA_PID" ]; then
    OLD_PID=$(cat "$SOVUSHKA_PID")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "  Останавливаем предыдущий процесс (PID $OLD_PID)..."
        kill "$OLD_PID"
        sleep 1
    fi
    rm -f "$SOVUSHKA_PID"
fi

cd "$LES_DIR"
nohup python3 sovushka_ng.py >> "$LOG_DIR/sovushka.log" 2>&1 &
SOVUSHKA_PID_VAL=$!
echo $SOVUSHKA_PID_VAL > "$SOVUSHKA_PID"
sleep 2

if kill -0 "$SOVUSHKA_PID_VAL" 2>/dev/null; then
    echo "  ✓ С.О.В.У.Ш.К.А. UP (PID $SOVUSHKA_PID_VAL)"
    echo "  → http://localhost:8051"
else
    echo "  ✗ С.О.В.У.Ш.К.А. упала — смотри logs/sovushka.log"
fi

# ── Итог ───────────────────────────────────
echo ""
echo "═══════════════════════════════════════"
echo "  СИСТЕМА Л.Е.С. ЗАПУЩЕНА"
echo ""
echo "  С.О.В.У.Ш.К.А.: http://localhost:8051"
echo "  les-proxy:       http://localhost:8050"
echo "  MLX Host:        http://127.0.0.1:8080"
echo "═══════════════════════════════════════"
echo ""
echo "Логи: tail -f $LOG_DIR/sovushka.log"
echo ""
