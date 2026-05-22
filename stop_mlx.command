#!/bin/bash
PID_FILE="~/Projects/LES_v2/logs/mlx_host.pid"
if [ -f "$PID_FILE" ]; then
    kill $(cat "$PID_FILE") 2>/dev/null && echo "[MLX] Остановлен"
    rm -f "$PID_FILE"
else
    pkill -f mlx_host.py && echo "[MLX] Остановлен (pkill)"
fi
