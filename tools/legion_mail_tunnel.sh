#!/usr/bin/env bash
# Реверс-туннель Мак(ЛЕС) → Легион для Outlook-плагина «В ЛЕС».
#
# Топология: Outlook + Add-in живут на ЛЕГИОНЕ (Windows), ЛЕС — на этом Маке. Обмен ПО SSH
# (а не по прямому ZeroTier-IP) — как просил Олег. Туннель пробрасывает порт ЛЕС на loopback
# Легиона: на Легионе `http://localhost:8050` → (ssh) → 127.0.0.1:8050 этого Мака (ЛЕС).
# Плагин шлёт на http://localhost:8050/api/mail/push — и попадает в локальный ЛЕС через SSH.
#
# Запуск (на Маке, где крутится ЛЕС):  bash tools/legion_mail_tunnel.sh
# Переопределить цель/порт:            LES_LEGION_SSH=legion LES_PORT=8050 bash tools/legion_mail_tunnel.sh
#
# Альтернатива (инициатор — Легион): на Легионе в PowerShell:
#   ssh -N -L 8050:127.0.0.1:8050 mini      # mini = ssh-алиас этого Мака (см. ~/.ssh/config)
set -euo pipefail

LEGION="${LES_LEGION_SSH:-legion}"   # ssh-алиас Легиона (~/.ssh/config: Host legion → 10.195.146.20)
PORT="${LES_PORT:-8050}"

echo "Реверс-туннель ЛЕС: ${LEGION}:${PORT} → 127.0.0.1:${PORT} (этот Мак). Ctrl-C — стоп."
echo "На Легионе плагин шлёт на http://localhost:${PORT} → SSH → локальный ЛЕС."
while true; do
  # -R bind на loopback Легиона (GatewayPorts=no по умолчанию) → доступен только localhost Легиона.
  ssh -N \
      -o ExitOnForwardFailure=yes \
      -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
      -R "127.0.0.1:${PORT}:127.0.0.1:${PORT}" \
      "${LEGION}" || true
  echo "$(date '+%H:%M:%S') туннель разорван — переподключение через 5с…"
  sleep 5
done
