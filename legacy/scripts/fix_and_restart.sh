#!/bin/zsh
# ─────────────────────────────────────────────────────────────
# fix_and_restart.sh — фикс BGE-M3 + перезапуск MLX Host
# Запуск: bash ~/Projects/LES_v2/fix_and_restart.sh
# ─────────────────────────────────────────────────────────────

set -e
PROJECT="$HOME/Projects/LES_v2"
LOG="$PROJECT/logs/mlx_host.log"

echo "══════════════════════════════════════════"
echo " Л.Е.С. // fix_and_restart.sh"
echo "══════════════════════════════════════════"

# ── 1. Останавливаем старый процесс ──────────
echo ""
echo "► [1/4] Останавливаем MLX Host..."
cd "$PROJECT"

if [ -f logs/mlx_host.pid ]; then
    OLD_PID=$(cat logs/mlx_host.pid)
    if kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID"
        echo "   Убит PID $OLD_PID"
        sleep 2
    else
        echo "   PID $OLD_PID уже мёртв"
    fi
    rm -f logs/mlx_host.pid
fi

# На всякий случай — добиваем по имени
pkill -f "mlx_host.py" 2>/dev/null && echo "   pkill mlx_host.py — OK" || echo "   (нечего убивать)"
sleep 1

# ── 2. Обновляем mlx-embedding-models ────────
echo ""
echo "► [2/4] Обновляем mlx-embedding-models..."

# uv run гарантирует правильное окружение проекта
uv run pip install --upgrade mlx-embedding-models 2>&1 | tail -5

# Проверяем версию
echo -n "   Версия: "
uv run python3 -c "import mlx_embedding_models; print(getattr(mlx_embedding_models, '__version__', 'unknown'))"

# ── 3. Быстрый тест encode ───────────────────
echo ""
echo "► [3/4] Тест EmbeddingModel.encode..."
uv run python3 - <<'PYEOF'
try:
    from mlx_embedding_models.embedding import EmbeddingModel
    m = EmbeddingModel.from_registry("bge-m3")
    v = m.encode(["тест соединения"])
    dim = len(v[0].tolist()) if hasattr(v[0], "tolist") else len(list(v[0]))
    print(f"   ✓ BGE-M3 OK — dim={dim}")
except Exception as e:
    print(f"   ✗ ОШИБКА: {e}")
    exit(1)
PYEOF

# ── 4. Запускаем MLX Host ─────────────────────
echo ""
echo "► [4/4] Запускаем MLX Host..."
mkdir -p logs
nohup uv run python3 mlx_host.py >> "$LOG" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > logs/mlx_host.pid
echo "   PID $NEW_PID → $LOG"

# ── Ждём и проверяем ─────────────────────────
echo ""
echo "► Ждём запуска (15 сек)..."
sleep 15

echo ""
echo "► Проверка /api/health..."
HEALTH=$(curl -s --max-time 5 http://127.0.0.1:8080/api/health 2>/dev/null)

if echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print('   ✓ MLX Host UP'); print('   main:', d.get('main_model',{}).get('path','?')); print('   embed:', d.get('embedding','?'))" 2>/dev/null; then
    echo ""
    echo "► Проверка /api/embeddings..."
    EMB=$(curl -s --max-time 10 -X POST http://127.0.0.1:8080/api/embeddings \
        -H "Content-Type: application/json" \
        -d '{"model":"bge-m3","prompt":"тест соединения"}' 2>/dev/null)
    echo "$EMB" | python3 -c "
import sys,json
d=json.load(sys.stdin)
e=d.get('embedding',[])
if e:
    print(f'   ✓ /api/embeddings OK — dim={len(e)}')
else:
    print(f'   ✗ Пустой ответ: {d}')
" 2>/dev/null || echo "   ✗ Ошибка разбора ответа: $EMB"
else
    echo "   ✗ MLX Host не ответил за 15 сек. Смотри лог:"
    tail -20 "$LOG"
fi

echo ""
echo "══════════════════════════════════════════"
echo " Готово. Хвост лога:"
echo "══════════════════════════════════════════"
tail -10 "$LOG"
