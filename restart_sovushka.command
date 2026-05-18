#!/bin/bash
cd "$HOME/Projects/LES_v2"
LOG="logs/sovushka.log"
PID_FILE="logs/sovushka.pid"
mkdir -p logs

# Стоп
if [ -f "$PID_FILE" ]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null
    rm -f "$PID_FILE"
fi
lsof -ti :8051 | xargs kill -9 2>/dev/null
sleep 1

# Старт
nohup uv run python3 sovushka_ng.py >> "$LOG" 2>&1 &
echo $! > "$PID_FILE"
sleep 2

kill -0 "$(cat "$PID_FILE")" 2>/dev/null \
    && echo "✓ С.О.В.У.Ш.К.А. UP (PID $(cat "$PID_FILE")) → http://localhost:8051" \
    || echo "✗ Упала — смотри $LOG"
