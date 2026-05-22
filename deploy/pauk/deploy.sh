#!/usr/bin/env bash
# deploy/pauk/deploy.sh — синхронизация кода репо → VPS (П.А.У.К.)
# Запускать с Mac Mini: bash deploy/pauk/deploy.sh
set -e

VPS="root@185.185.71.196"
REMOTE="/root/les_v2"
LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "==> Синхронизация кода: $LOCAL → $VPS:$REMOTE"

rsync -avz --delete \
  --exclude='.env' \
  --exclude='.git/' \
  --exclude='.DS_Store' \
  --exclude='.aider*' \
  --exclude='.claude/' \
  --exclude='.nicegui/' \
  --exclude='.pytest_cache/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='/data/' \
  --exclude='/storage/' \
  --exclude='/RAG_Content/' \
  --exclude='/logs/' \
  --exclude='/legacy/' \
  --exclude='.venv/' \
  --exclude='uv.lock' \
  --exclude='qdrant_visualizer/data.js' \
  --exclude='mlx_host.py' \
  --exclude='les.command' \
  --exclude='pauk_launchd.plist' \
  --exclude='start_pauk.command' \
  --exclude='stop_pauk.command' \
  --exclude='restart_sovushka.command' \
  "$LOCAL/" "$VPS:$REMOTE/"

echo "==> Перезапуск сервисов на VPS"
ssh "$VPS" "systemctl restart les_proxy && systemctl restart sovushka"

echo "==> Проверка"
sleep 3
ssh "$VPS" "systemctl is-active les_proxy && systemctl is-active sovushka"
ssh "$VPS" "curl -s http://localhost:8050/api/health"

echo "==> Готово"
