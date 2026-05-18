#!/bin/bash
# ═══════════════════════════════════════════════════════
#  les.command — Управление системой Л.Е.С.
#  Использование:
#    ./les.command           — интерактивное меню
#    ./les.command start     — запустить всё
#    ./les.command stop      — остановить всё
#    ./les.command restart   — перезапустить всё
#    ./les.command sovushka  — перезапустить только UI
#    ./les.command status    — состояние сервисов
# ═══════════════════════════════════════════════════════

DIR="$HOME/Projects/LES_v2"
LOGS="$DIR/logs"
mkdir -p "$LOGS"

# ── Цвета ───────────────────────────────────────────────
G="\033[0;32m"; R="\033[0;31m"; Y="\033[0;33m"; D="\033[0m"; B="\033[1m"

_ok()  { echo -e "  ${G}✓${D} $1"; }
_err() { echo -e "  ${R}✗${D} $1"; }
_inf() { echo -e "  ${Y}·${D} $1"; }

header() {
    echo -e "\n${B}═══════════════════════════════════════${D}"
    echo -e "${B}  Л.Е.С. // $1${D}"
    echo -e "${B}═══════════════════════════════════════${D}"
}

# ── Статус одного сервиса ────────────────────────────────
_pid_status() {
    local name=$1 pid_file=$2 port=$3
    if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
        _ok "$name (PID $(cat "$pid_file"))"
    else
        _err "$name не запущен"
    fi
}

# ── СТОП ────────────────────────────────────────────────
do_stop() {
    header "ОСТАНОВКА"

    # С.О.В.У.Ш.К.А.
    if [ -f "$LOGS/sovushka.pid" ]; then
        kill "$(cat "$LOGS/sovushka.pid")" 2>/dev/null
        rm -f "$LOGS/sovushka.pid"
    fi
    lsof -ti :8051 | xargs kill -9 2>/dev/null
    _ok "С.О.В.У.Ш.К.А. остановлена"

    # MLX Host
    if [ -f "$LOGS/mlx_host.pid" ]; then
        kill "$(cat "$LOGS/mlx_host.pid")" 2>/dev/null
        rm -f "$LOGS/mlx_host.pid"
    fi
    _ok "MLX Host остановлен"

    # Docker
    cd "$DIR" && docker compose stop 2>&1 | tail -2
    _ok "Docker остановлен"
}

# ── СТАРТ ────────────────────────────────────────────────
do_start() {
    header "ЗАПУСК"
    cd "$DIR"
    source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null

    # 1. Docker
    echo -e "\n${B}[1/3] Docker...${D}"
    docker compose up -d 2>&1 | tail -3
    sleep 2
    docker ps --format "{{.Names}}" | grep -q "les-proxy"  && _ok "les-proxy"  || _err "les-proxy не поднялся"
    docker ps --format "{{.Names}}" | grep -q "les-qdrant" && _ok "les-qdrant" || _err "les-qdrant не поднялся"

    # 2. MLX Host
    echo -e "\n${B}[2/3] MLX Host...${D}"
    if [ -f "$LOGS/mlx_host.pid" ] && kill -0 "$(cat "$LOGS/mlx_host.pid")" 2>/dev/null; then
        _inf "MLX уже запущен (PID $(cat "$LOGS/mlx_host.pid"))"
    else
        uv sync --quiet
        export MLX_MODEL="${MLX_MODEL:-mlx-community/Qwen3-14B-4bit}"
        export MLX_VAL_MODEL="${MLX_VAL_MODEL:-mlx-community/Qwen3-4B-4bit}"
        nohup uv run python3 mlx_host.py >> "$LOGS/mlx_host.log" 2>&1 &
        echo $! > "$LOGS/mlx_host.pid"
        sleep 3
        curl -sf http://127.0.0.1:8080/api/health > /dev/null \
            && _ok "MLX Host (PID $(cat "$LOGS/mlx_host.pid"))" \
            || _inf "MLX запущен (PID $(cat "$LOGS/mlx_host.pid")), модель грузится..."
    fi

    # 3. С.О.В.У.Ш.К.А.
    echo -e "\n${B}[3/3] С.О.В.У.Ш.К.А....${D}"
    lsof -ti :8051 | xargs kill -9 2>/dev/null; sleep 1
    nohup uv run python3 sovushka_ng.py >> "$LOGS/sovushka.log" 2>&1 &
    echo $! > "$LOGS/sovushka.pid"
    sleep 2
    kill -0 "$(cat "$LOGS/sovushka.pid")" 2>/dev/null \
        && _ok "С.О.В.У.Ш.К.А. (PID $(cat "$LOGS/sovushka.pid")) → http://localhost:8051" \
        || _err "Упала — смотри $LOGS/sovushka.log"

    echo ""
    _ok "http://localhost:8051"
}

# ── ТОЛЬКО СОВУШКА ──────────────────────────────────────
do_sovushka() {
    header "ПЕРЕЗАПУСК С.О.В.У.Ш.К.А."
    cd "$DIR"
    [ -f "$LOGS/sovushka.pid" ] && kill "$(cat "$LOGS/sovushka.pid")" 2>/dev/null
    lsof -ti :8051 | xargs kill -9 2>/dev/null
    rm -f "$LOGS/sovushka.pid"
    sleep 1
    nohup uv run python3 sovushka_ng.py >> "$LOGS/sovushka.log" 2>&1 &
    echo $! > "$LOGS/sovushka.pid"
    sleep 2
    kill -0 "$(cat "$LOGS/sovushka.pid")" 2>/dev/null \
        && _ok "UP (PID $(cat "$LOGS/sovushka.pid")) → http://localhost:8051" \
        || _err "Упала — смотри $LOGS/sovushka.log"
}

# ── СТАТУС ───────────────────────────────────────────────
do_status() {
    header "СТАТУС"
    _pid_status "С.О.В.У.Ш.К.А. :8051" "$LOGS/sovushka.pid"
    _pid_status "MLX Host        :8080" "$LOGS/mlx_host.pid"
    docker ps --format "{{.Names}}\t{{.Status}}" | grep "^les-" | while read line; do
        _ok "Docker  $line"
    done
    echo ""
    curl -sf http://localhost:8050/api/health > /dev/null \
        && _ok "API /health → OK" || _err "API /health → недоступен"
    curl -sf http://127.0.0.1:8080/api/health > /dev/null \
        && _ok "MLX /health → OK" || _err "MLX /health → недоступен (модель грузится?)"
}

# ── МЕНЮ ────────────────────────────────────────────────
show_menu() {
    header "УПРАВЛЕНИЕ СИСТЕМОЙ"
    echo ""
    echo -e "  ${B}1)${D} Запустить всё          (start)"
    echo -e "  ${B}2)${D} Остановить всё         (stop)"
    echo -e "  ${B}3)${D} Перезапустить всё      (restart)"
    echo -e "  ${B}4)${D} Перезапустить UI       (sovushka)"
    echo -e "  ${B}5)${D} Статус                 (status)"
    echo -e "  ${B}q)${D} Выход"
    echo ""
    read -rp "  Выбор: " choice
    case "$choice" in
        1|start)   do_start   ;;
        2|stop)    do_stop    ;;
        3|restart) do_stop; sleep 1; do_start ;;
        4|sovushka) do_sovushka ;;
        5|status)  do_status  ;;
        q|Q)       exit 0 ;;
        *) echo "Неизвестная команда" ;;
    esac
}

# ── Точка входа ──────────────────────────────────────────
case "${1:-menu}" in
    start)    do_start   ;;
    stop)     do_stop    ;;
    restart)  do_stop; sleep 1; do_start ;;
    sovushka) do_sovushka ;;
    status)   do_status  ;;
    menu)     show_menu  ;;
    *)        echo "Использование: $0 {start|stop|restart|sovushka|status}"; exit 1 ;;
esac
