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

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

_ensure_docker() {
    if docker info >/dev/null 2>&1; then
        return 0
    fi
    _inf "Docker daemon недоступен, запускаю OrbStack..."
    open -a OrbStack >/dev/null 2>&1 || open -a Docker >/dev/null 2>&1 || true
    for _ in {1..45}; do
        if docker info >/dev/null 2>&1; then
            _ok "Docker daemon готов"
            return 0
        fi
        sleep 2
    done
    _err "Docker daemon не поднялся за 90 секунд"
    return 1
}

_load_env() {
    set -a
    [ -f "$DIR/.env" ] && source "$DIR/.env"
    set +a
    export MLX_URL="${MLX_URL:-http://127.0.0.1:8080}"
    export QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
    export LES_QDRANT_RUNTIME="${LES_QDRANT_RUNTIME:-auto}"
}

_qdrant_bin() {
    if [ -x "$HOME/.local/bin/qdrant" ]; then
        echo "$HOME/.local/bin/qdrant"
    elif command -v qdrant >/dev/null 2>&1; then
        command -v qdrant
    fi
}

_qdrant_runtime() {
    local runtime="${LES_QDRANT_RUNTIME:-auto}"
    if [ "$runtime" = "auto" ]; then
        if [ -n "$(_qdrant_bin)" ]; then
            echo "local"
        else
            echo "docker"
        fi
    else
        echo "$runtime"
    fi
}

_qdrant_health() {
    curl -sf "${QDRANT_URL:-http://127.0.0.1:6333}" >/dev/null 2>&1
}

_start_qdrant_local() {
    local bin="$(_qdrant_bin)"
    if [ -z "$bin" ]; then
        _err "qdrant binary не найден ($HOME/.local/bin/qdrant)"
        return 1
    fi
    if _qdrant_health; then
        _ok "Qdrant local уже доступен"
        return 0
    fi

    if [ -f "$DIR/qdrant_launchd.plist" ]; then
        cp "$DIR/qdrant_launchd.plist" "$HOME/Library/LaunchAgents/me.ovc.les.qdrant.plist"
        launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/me.ovc.les.qdrant.plist" >/dev/null 2>&1 || true
        launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/me.ovc.les.qdrant.plist"
    else
        QDRANT__STORAGE__STORAGE_PATH="$DIR/data/qdrant" \
        QDRANT__SERVICE__HTTP_PORT=6333 \
        QDRANT__SERVICE__GRPC_PORT=6334 \
        nohup "$bin" --disable-telemetry >> "$LOGS/qdrant.log" 2>&1 &
    fi

    for _ in {1..45}; do
        if _qdrant_health; then
            _ok "Qdrant local → ${QDRANT_URL:-http://127.0.0.1:6333}"
            return 0
        fi
        sleep 1
    done
    _err "Qdrant local не поднялся — смотри $LOGS/qdrant.log"
    return 1
}

_start_qdrant_docker() {
    _ensure_docker || return 1
    docker compose up -d qdrant 2>&1 | tail -3
    local compose_status=${PIPESTATUS[0]}
    if [ "$compose_status" -ne 0 ]; then
        _err "docker compose up qdrant завершился с ошибкой"
        return 1
    fi
    sleep 2
    docker ps --format "{{.Names}}" | grep -q "les-qdrant" && _ok "les-qdrant" || _err "les-qdrant не поднялся"
}

_start_qdrant() {
    _load_env
    case "$(_qdrant_runtime)" in
        local) _start_qdrant_local ;;
        docker) _start_qdrant_docker ;;
        *)
            _err "Неизвестный LES_QDRANT_RUNTIME=$LES_QDRANT_RUNTIME (нужно auto/local/docker)"
            return 1
            ;;
    esac
}

_stop_qdrant() {
    launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/me.ovc.les.qdrant.plist" >/dev/null 2>&1 || true
    lsof -tiTCP:6333 -sTCP:LISTEN 2>/dev/null | while read pid; do
        ps -o command= -p "$pid" 2>/dev/null | grep -q "qdrant" && kill "$pid" 2>/dev/null
    done
    if docker info >/dev/null 2>&1; then
        cd "$DIR" && docker compose stop qdrant >/dev/null 2>&1 || true
    fi
}

# ── Статус одного сервиса ────────────────────────────────
_pid_status() {
    local name=$1 pid_file=$2 port=$3
    if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
        _ok "$name (PID $(cat "$pid_file"))"
    elif [ -n "$port" ] && LISTENER="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1)" && [ -n "$LISTENER" ]; then
        echo "$LISTENER" > "$pid_file"
        _ok "$name (PID $LISTENER, найден по :$port)"
    else
        _err "$name не запущен"
    fi
}

# ── Запуск MLX (общий для старта и watchdog) ─────────────
_launch_mlx() {
    source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null
    # Грузим .env чтобы подхватить MLX_MODEL / MLX_VAL_MODEL
    _load_env
    nohup uv run --project "$DIR" python3 "$DIR/mlx_host.py" >> "$LOGS/mlx_host.log" 2>&1 &
    echo $! > "$LOGS/mlx_host.pid"
}

_launch_proxy() {
    source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null
    _load_env
    uv sync --quiet --group coreml --project "$DIR"
    if [ -f "$DIR/proxy_launchd.plist" ]; then
        cp "$DIR/proxy_launchd.plist" "$HOME/Library/LaunchAgents/me.ovc.les.proxy.plist"
        launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/me.ovc.les.proxy.plist" >/dev/null 2>&1 || true
        launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/me.ovc.les.proxy.plist"
        sleep 1
        launchctl list | awk '/me\.ovc\.les\.proxy/ {print $1}' > "$LOGS/proxy.pid"
    else
        nohup "$DIR/.venv/bin/python3" -m uvicorn proxy_server:app --host 0.0.0.0 --port 8050 >> "$LOGS/proxy.log" 2>&1 &
        echo $! > "$LOGS/proxy.pid"
        disown $! 2>/dev/null || true
    fi
}

# ── MLX Watchdog (запускается фоном при старте) ───────────
# Каждые 30 сек проверяет PID + /api/health, перезапускает если упал.
_mlx_watchdog() {
    local _dir="$DIR" _logs="$LOGS"
    while true; do
        sleep 30
        [ -f "$_logs/mlx_watchdog.stop" ] && { rm -f "$_logs/mlx_watchdog.stop"; exit 0; }
        pid_ok=false
        [ -f "$_logs/mlx_host.pid" ] && kill -0 "$(cat "$_logs/mlx_host.pid")" 2>/dev/null && pid_ok=true
        if ! $pid_ok; then
            echo "[$(date '+%H:%M:%S')] [WATCHDOG] MLX упал (OOM?) — перезапускаю..." >> "$_logs/mlx_host.log"
            source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null
            set -a; [ -f "$_dir/.env" ] && source "$_dir/.env"; set +a
            nohup uv run --project "$_dir" python3 "$_dir/mlx_host.py" >> "$_logs/mlx_host.log" 2>&1 &
            echo $! > "$_logs/mlx_host.pid"
        fi
    done
}

_start_watchdog() {
    if launchctl list | grep -q "me.ovc.les.mlx"; then
        _ok "MLX LaunchAgent me.ovc.les.mlx"
        return
    fi
    if [ -f "$LOGS/mlx_watchdog.pid" ] && kill -0 "$(cat "$LOGS/mlx_watchdog.pid")" 2>/dev/null; then
        return
    fi
    rm -f "$LOGS/mlx_watchdog.pid"
    nohup "$DIR/les.command" mlx-watchdog >> "$LOGS/mlx_host.log" 2>&1 &
    echo $! > "$LOGS/mlx_watchdog.pid"
    disown $! 2>/dev/null || true
    _ok "MLX Watchdog (PID $(cat "$LOGS/mlx_watchdog.pid"))"
}

_stop_watchdog() {
    touch "$LOGS/mlx_watchdog.stop"
    if [ -f "$LOGS/mlx_watchdog.pid" ]; then
        kill "$(cat "$LOGS/mlx_watchdog.pid")" 2>/dev/null
        rm -f "$LOGS/mlx_watchdog.pid" "$LOGS/mlx_watchdog.stop"
    fi
}

# ── СТОП ────────────────────────────────────────────────
do_stop() {
    header "ОСТАНОВКА"

    _stop_watchdog

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

    # Proxy host
    cd "$DIR" && docker compose stop proxy >/dev/null 2>&1 || true
    launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/me.ovc.les.proxy.plist" >/dev/null 2>&1 || true
    if [ -f "$LOGS/proxy.pid" ]; then
        kill "$(cat "$LOGS/proxy.pid")" 2>/dev/null
        rm -f "$LOGS/proxy.pid"
    fi
    lsof -ti :8050 | xargs kill -9 2>/dev/null
    _ok "les-proxy host остановлен"

    # Qdrant
    _stop_qdrant
    _ok "Qdrant остановлен"
}

# ── СТАРТ ────────────────────────────────────────────────
do_start() {
    header "ЗАПУСК"
    source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null
    cd "$DIR" || { _err "Не могу перейти в $DIR"; return 1; }
    mkdir -p "$LOGS"

    # 1. Qdrant
    echo -e "\n${B}[1/4] Qdrant ($(_qdrant_runtime))...${D}"
    _start_qdrant || return 1

    # 2. MLX Host
    echo -e "\n${B}[2/4] MLX Host...${D}"
    if [ -f "$LOGS/mlx_host.pid" ] && kill -0 "$(cat "$LOGS/mlx_host.pid")" 2>/dev/null; then
        _inf "MLX уже запущен (PID $(cat "$LOGS/mlx_host.pid"))"
    elif MLX_LISTENER="$(lsof -tiTCP:8080 -sTCP:LISTEN 2>/dev/null | head -1)" && [ -n "$MLX_LISTENER" ]; then
        echo "$MLX_LISTENER" > "$LOGS/mlx_host.pid"
        _inf "MLX уже слушает :8080 (PID $MLX_LISTENER)"
    else
        uv sync --quiet --group coreml --project "$DIR"
        _launch_mlx
        sleep 3
        curl -sf http://127.0.0.1:8080/api/health > /dev/null \
            && _ok "MLX Host (PID $(cat "$LOGS/mlx_host.pid"))" \
            || _inf "MLX запущен (PID $(cat "$LOGS/mlx_host.pid")), модель грузится..."
    fi
    _start_watchdog

    # 3. Proxy host
    echo -e "\n${B}[3/4] les-proxy host...${D}"
    if [ -f "$LOGS/proxy.pid" ] && kill -0 "$(cat "$LOGS/proxy.pid")" 2>/dev/null; then
        _inf "les-proxy уже запущен (PID $(cat "$LOGS/proxy.pid"))"
    elif PROXY_LISTENER="$(lsof -tiTCP:8050 -sTCP:LISTEN 2>/dev/null | head -1)" && [ -n "$PROXY_LISTENER" ]; then
        echo "$PROXY_LISTENER" > "$LOGS/proxy.pid"
        _inf "les-proxy уже слушает :8050 (PID $PROXY_LISTENER)"
    else
        docker compose stop proxy >/dev/null 2>&1 || true
        lsof -ti :8050 | xargs kill -9 2>/dev/null; sleep 1
        _launch_proxy
        sleep 3
        curl -sf http://127.0.0.1:8050/api/health > /dev/null \
            && _ok "les-proxy host (PID $(cat "$LOGS/proxy.pid")) → http://localhost:8050" \
            || _err "les-proxy host не поднялся — смотри $LOGS/proxy.log"
    fi

    # 4. С.О.В.У.Ш.К.А.
    echo -e "\n${B}[4/4] С.О.В.У.Ш.К.А....${D}"
    if UI_LISTENER="$(lsof -tiTCP:8051 -sTCP:LISTEN 2>/dev/null | head -1)" && [ -n "$UI_LISTENER" ]; then
        echo "$UI_LISTENER" > "$LOGS/sovushka.pid"
        _ok "С.О.В.У.Ш.К.А. уже слушает :8051 (PID $UI_LISTENER)"
    else
        nohup uv run --project "$DIR" python3 "$DIR/sovushka_ng.py" >> "$LOGS/sovushka.log" 2>&1 &
        echo $! > "$LOGS/sovushka.pid"
        sleep 2
        kill -0 "$(cat "$LOGS/sovushka.pid")" 2>/dev/null \
            && _ok "С.О.В.У.Ш.К.А. (PID $(cat "$LOGS/sovushka.pid")) → http://localhost:8051" \
            || _err "Упала — смотри $LOGS/sovushka.log"
    fi

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
    nohup uv run --project "$DIR" python3 "$DIR/sovushka_ng.py" >> "$LOGS/sovushka.log" 2>&1 &
    echo $! > "$LOGS/sovushka.pid"
    sleep 2
    kill -0 "$(cat "$LOGS/sovushka.pid")" 2>/dev/null \
        && _ok "UP (PID $(cat "$LOGS/sovushka.pid")) → http://localhost:8051" \
        || _err "Упала — смотри $LOGS/sovushka.log"
}

# ── СТАТУС ───────────────────────────────────────────────
do_status() {
    header "СТАТУС"
    _load_env
    _pid_status "С.О.В.У.Ш.К.А. :8051" "$LOGS/sovushka.pid" 8051
    _pid_status "les-proxy host  :8050" "$LOGS/proxy.pid" 8050
    _pid_status "MLX Host        :8080" "$LOGS/mlx_host.pid" 8080
    launchctl list | grep -q "me.ovc.les.mlx" \
        && _ok "MLX LaunchAgent me.ovc.les.mlx" \
        || _pid_status "MLX Watchdog   " "$LOGS/mlx_watchdog.pid"
    _qdrant_health && _ok "Qdrant ${QDRANT_URL}" || _err "Qdrant недоступен"
    if docker info >/dev/null 2>&1; then
        docker ps --format "{{.Names}}\t{{.Status}}" | grep "^les-" | while read line; do
            _ok "Docker  $line"
        done
    fi
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
    mlx-watchdog) _mlx_watchdog ;;
    menu)     show_menu  ;;
    *)        echo "Использование: $0 {start|stop|restart|sovushka|status}"; exit 1 ;;
esac
