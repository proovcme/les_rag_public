#!/bin/bash
# =============================================================================
# run_fixes.sh — Последовательные правки proxy_server.py через Aider
# Запуск: cd ~/Projects/LES_v2 && bash run_fixes.sh
# =============================================================================

set -e  # остановить при ошибке

AIDER="/Users/ovc/Library/Python/3.9/bin/aider"
AIDER_MODEL="ollama_chat/qwen2.5-coder:14b"
AIDER_BASE="http://localhost:11434/v1"
PROXY="proxy_server.py"
COLLECTOR="backend/metrics_collector.py"
ADAPTER="backend/qdrant_adapter.py"
INTERFACE="backend/interface.py"
BACKUP_DIR=".backups/$(date +%Y%m%d_%H%M%S)"

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()   { echo -e "${GREEN}[OK]${NC}   $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }

# =============================================================================
# УТИЛИТЫ
# =============================================================================

check_file() {
  if [ ! -f "$1" ]; then
    fail "Файл не найден: $1"
    exit 1
  fi
}

# Считаем приблизительное количество токенов (1 токен ≈ 4 символа)
count_tokens() {
  local total=0
  for f in "$@"; do
    if [ -f "$f" ]; then
      local chars
      chars=$(wc -c < "$f")
      total=$((total + chars / 4))
    fi
  done
  echo $total
}

check_context() {
  local limit=28000  # оставляем запас до 32k
  local tokens
  tokens=$(count_tokens "$@")
  if [ "$tokens" -gt "$limit" ]; then
    warn "Контекст ~${tokens} токенов — близко к лимиту 32k!"
    warn "Файлы: $*"
    read -p "Продолжить? (y/n): " confirm
    [ "$confirm" = "y" ] || exit 1
  else
    log "Контекст ~${tokens} токенов — OK"
  fi
}

health_check() {
  local status
  status=$(curl -s http://localhost:8050/api/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "unreachable")
  if [ "$status" = "ok" ]; then
    ok "Health: $status"
    return 0
  else
    fail "Health: $status"
    return 1
  fi
}

restart_proxy() {
  log "Перезапуск прокси..."
  docker compose restart proxy
  log "Ждём 8 секунд..."
  sleep 8
  health_check || {
    fail "Прокси не поднялся после рестарта"
    log "Логи:"
    docker logs les-proxy --tail 30
    exit 1
  }
}

run_aider() {
  local msg="$1"
  shift
  local files=("$@")
  "$AIDER" \
    --model "$AIDER_MODEL" \
    --openai-api-base "$AIDER_BASE" \
    --yes-always \
    --no-auto-commits \
    "${files[@]}" \
    --message "$msg"
}

# =============================================================================
# СТАРТ
# =============================================================================

echo ""
echo -e "${CYAN}════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Л.Е.С. — Aider Fix Runner                ${NC}"
echo -e "${CYAN}════════════════════════════════════════════${NC}"
echo ""

# Проверяем что мы в правильной папке
if [ ! -f "$PROXY" ]; then
  fail "proxy_server.py не найден. Запусти скрипт из ~/Projects/LES_v2"
  exit 1
fi

# Проверяем Aider
if [ ! -f "$AIDER" ]; then
  fail "Aider не найден: $AIDER"
  exit 1
fi

# Проверяем все нужные файлы
for f in "$PROXY" "$COLLECTOR" "$ADAPTER" "$INTERFACE"; do
  check_file "$f"
done
ok "Все файлы найдены"

# Проверяем git
if ! git status > /dev/null 2>&1; then
  fail "Не git-репозиторий. Инициализируй git или убери set -e"
  exit 1
fi

# Проверяем нет ли грязных изменений
if ! git diff --quiet; then
  warn "Есть незакоммиченные изменения:"
  git status --short
  read -p "Продолжить? (y/n): " confirm
  [ "$confirm" = "y" ] || exit 1
fi

# =============================================================================
# БЭКАПЫ
# =============================================================================

log "Создаём бэкапы в $BACKUP_DIR ..."
mkdir -p "$BACKUP_DIR/backend"

cp "$PROXY"      "$BACKUP_DIR/$PROXY"
cp "$COLLECTOR"  "$BACKUP_DIR/$COLLECTOR"
cp "$ADAPTER"    "$BACKUP_DIR/$ADAPTER"
cp "$INTERFACE"  "$BACKUP_DIR/$INTERFACE"

ok "Бэкапы созданы:"
ls -lh "$BACKUP_DIR/"
ls -lh "$BACKUP_DIR/backend/"

echo ""
log "Для отката любого файла:"
echo "  cp $BACKUP_DIR/proxy_server.py proxy_server.py"
echo ""

# Начальный health check
log "Проверяем систему перед стартом..."
health_check || warn "Система не отвечает до начала правок — продолжаем"

# =============================================================================
# ЗАДАЧА 1 — Удалить дублирующий import time
# =============================================================================

echo ""
echo -e "${CYAN}── Задача 1/5: Дублирующий import time ──${NC}"
check_context "$PROXY"

run_aider \
  "Remove the duplicate 'import time' statement in proxy_server.py. There are two occurrences: one at the top of the file with other stdlib imports, and one around line 44 after 'job_tracker = {}'. Keep only the first one at the top of the file. Do not change anything else." \
  "$PROXY"

ok "Задача 1 выполнена"
echo ""

# =============================================================================
# ЗАДАЧА 2 — Объединить два startup-обработчика
# =============================================================================

echo -e "${CYAN}── Задача 2/5: Объединить startup-обработчики ──${NC}"
check_context "$PROXY" "$COLLECTOR"

run_aider \
  "In proxy_server.py there are two @app.on_event('startup') handlers: one named 'startup' that initializes rag_backend, and one named 'startup_event' that calls init_db() and creates metrics_loop task. Merge them into a single @app.on_event('startup') async function named 'startup'. The merged function must execute in this order: (1) call init_db(), (2) initialize rag_backend with existing logic including global declaration, (3) create task for metrics_collector_loop(), (4) create task for metrics_loop(). Keep all existing error handling. Remove the now-redundant 'startup_event' function entirely. Do not change backend/metrics_collector.py. Do not change anything else in proxy_server.py." \
  "$PROXY" "$COLLECTOR"

ok "Задача 2 выполнена"
restart_proxy
echo ""

# =============================================================================
# ЗАДАЧА 3 — Очищать /tmp после загрузки
# =============================================================================

echo -e "${CYAN}── Задача 3/5: Очистка /tmp после upload ──${NC}"
check_context "$PROXY"

run_aider \
  "In proxy_server.py in the upload_file endpoint, the inner async function _parse does not clean up the temporary file after parsing. Modify _parse to wrap its existing body in a try/finally block. In the finally clause add: temp_path.unlink(missing_ok=True). Do not change anything else." \
  "$PROXY"

ok "Задача 3 выполнена"
echo ""

# =============================================================================
# ЗАДАЧА 4 — Счётчики new/changed в sync_folder
# =============================================================================

echo -e "${CYAN}── Задача 4/5: Счётчики new/changed в sync ──${NC}"
check_context "$PROXY"

run_aider \
  "In proxy_server.py in the sync_folder function: (1) add a changed_count variable initialized to 0 alongside new_count and skip_count; (2) in the file loop, after checking if dest exists, add a separate is_changed boolean: set it True if dest exists but file size or mtime differs from source; (3) if is_new: increment new_count; elif is_changed: increment changed_count; else: increment skip_count; (4) update the job completion message to include changed_count like: 'Готово. Новых: {new_count}, изменённых: {changed_count}, пропущено: {skip_count}'; (5) add 'changed_files': changed_count to the return dict. Do not change anything else." \
  "$PROXY"

ok "Задача 4 выполнена"
echo ""

# =============================================================================
# ЗАДАЧА 5 — Записывать latency и CRAG в chat_metrics
# =============================================================================

echo -e "${CYAN}── Задача 5/5: chat_metrics latency + CRAG ──${NC}"

# Эта задача самая тяжёлая по контексту — проверяем особо
TOKENS=$(count_tokens "$PROXY" "$ADAPTER" "$INTERFACE")
log "Контекст задачи 5: ~${TOKENS} токенов"

if [ "$TOKENS" -gt 24000 ]; then
  warn "Адаптер большой (${TOKENS} токенов). Запускаем без него — только proxy + interface"
  warn "Aider не будет знать детали retrieve(), но задача этого не требует"
  TASK5_FILES=("$PROXY" "$INTERFACE")
else
  log "Контекст OK — берём все три файла"
  TASK5_FILES=("$PROXY" "$ADAPTER" "$INTERFACE")
fi
check_context "${TASK5_FILES[@]}"

run_aider \
  "In proxy_server.py in the chat endpoint function, add latency measurement and recording into chat_metrics. Changes required: (1) before calling rag_backend.retrieve(), record start time with t_search_start = time.time(); (2) after retrieve() returns, calculate t_search = time.time() - t_search_start; (3) in the NO_DATA branch (when not chunks): append t_search to chat_metrics['latency_search'], append 0.0 to chat_metrics['latency_gen'], increment chat_metrics['crag_fail'] by 1; (4) before calling Ollama generate, record t_gen_start = time.time(); (5) after successful Ollama response: calculate t_gen = time.time() - t_gen_start, append t_search to chat_metrics['latency_search'], append t_gen to chat_metrics['latency_gen'], append resp.json().get('eval_count', 0) to chat_metrics['tokens'], increment chat_metrics['crag_pass'] by 1; (6) after ALL appends in both branches, trim the three lists to last 100 elements: chat_metrics['latency_search'] = chat_metrics['latency_search'][-100:] and same for latency_gen and tokens. Do not change any backend files. Do not change anything else in proxy_server.py." \
  "${TASK5_FILES[@]}"

ok "Задача 5 выполнена"
restart_proxy
echo ""

# =============================================================================
# ФИНАЛЬНАЯ ПРОВЕРКА
# =============================================================================

echo -e "${CYAN}════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Финальная проверка                        ${NC}"
echo -e "${CYAN}════════════════════════════════════════════${NC}"
echo ""

log "Health check..."
health_check

log "Проверяем метрики..."
curl -s http://localhost:8050/api/metrics | python3 -c "
import sys, json
d = json.load(sys.stdin)
s = d.get('system', {})
r = d.get('rag', {})
p = d.get('pipeline', {})
print(f'  CPU:          {s.get(\"cpu\", \"?\")}%')
print(f'  RAM:          {s.get(\"ram_used\", \"?\")} / {s.get(\"ram_total\", \"?\")} GB')
print(f'  Disk:         {s.get(\"disk_used\", \"?\")} / {s.get(\"disk_total\", \"?\")} GB')
print(f'  Ollama RAM:   {s.get(\"ollama_ram\", \"?\")} GB')
print(f'  RAG files:    {r.get(\"files\", \"?\")}')
print(f'  RAG chunks:   {r.get(\"chunks\", \"?\")}')
print(f'  RAG status:   {r.get(\"status\", \"?\")}')
print(f'  Latency data: {len(p.get(\"latency_search\", []))} записей (0 = задача 5 не сработала или чатов ещё не было)')
print(f'  CRAG rate:    {p.get(\"crag_pass_rate\", \"?\")}')
" 2>/dev/null || warn "Не удалось разобрать метрики"

echo ""
log "Проверяем структуру ответа sync (dry-run — только смотрим поля)..."
curl -s http://localhost:8050/api/rag/sources | python3 -c "
import sys, json
sources = json.load(sys.stdin)
print(f'  Источников: {len(sources)}')
for s in sources[:3]:
    print(f'  {s[\"folder\"]}: {s[\"source_files\"]} файлов, {s[\"indexed_files\"]} в индексе, статус: {s[\"dataset_status\"]}')
" 2>/dev/null || warn "Не удалось получить sources"

echo ""
ok "Все задачи выполнены"
echo ""
echo -e "${CYAN}Бэкапы лежат в: $BACKUP_DIR${NC}"
echo -e "${CYAN}Откат:          cp $BACKUP_DIR/proxy_server.py proxy_server.py && docker compose restart proxy${NC}"
echo ""

# Показываем diff итоговых изменений
log "Итоговые изменения в proxy_server.py:"
git diff proxy_server.py | head -120 || true
