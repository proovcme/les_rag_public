#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$DIR/logs/sovushka.log"
PID_FILE="$DIR/logs/sovushka.pid"

source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null
cd "$DIR" || { echo "Не могу перейти в $DIR"; exit 1; }
mkdir -p "$DIR/logs"

# Стоп
if [ -f "$PID_FILE" ]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null
    rm -f "$PID_FILE"
fi
lsof -ti :8051 | xargs kill -9 2>/dev/null
sleep 1

# Старт
nohup uv run --project "$DIR" python3 "$DIR/sovushka_ng.py" >> "$LOG" 2>&1 &
echo $! > "$PID_FILE"
sleep 2

kill -0 "$(cat "$PID_FILE")" 2>/dev/null \
    && echo "✓ С.О.В.У.Ш.К.А. UP (PID $(cat "$PID_FILE")) → http://localhost:8051" \
    || echo "✗ Упала — смотри $LOG"
