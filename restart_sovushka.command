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
OLD_LISTENERS="$(lsof -tiTCP:8051 -sTCP:LISTEN 2>/dev/null)"
if [ -n "$OLD_LISTENERS" ]; then
    kill -9 $OLD_LISTENERS 2>/dev/null
fi
if command -v screen >/dev/null 2>&1; then
    screen -S les-sovushka -X quit 2>/dev/null
fi
sleep 1

# Старт
if command -v screen >/dev/null 2>&1; then
    screen -dmS les-sovushka bash -lc "cd '$DIR' && exec '$DIR/.venv/bin/python3' '$DIR/sovushka_ng.py' >> '$LOG' 2>&1"
    echo "screen:les-sovushka" > "$PID_FILE"
else
    nohup "$DIR/.venv/bin/python3" "$DIR/sovushka_ng.py" >> "$LOG" 2>&1 &
    echo $! > "$PID_FILE"
fi
sleep 2

SOV_PID="$(lsof -tiTCP:8051 -sTCP:LISTEN 2>/dev/null | head -n 1)"
if [ -n "$SOV_PID" ]; then
    echo "$SOV_PID" > "$PID_FILE"
    echo "✓ С.О.В.У.Ш.К.А. UP (PID $SOV_PID) → http://localhost:8051"
else
    echo "✗ Упала — смотри $LOG"
fi
