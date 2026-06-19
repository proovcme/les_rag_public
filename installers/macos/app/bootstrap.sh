#!/usr/bin/env bash
# LES.app first-run / launch bootstrap.
#
# Lives inside LES.app/Contents/Resources/bootstrap.sh and is invoked by the
# bundle executable (Contents/MacOS/LES). No terminal required: progress is
# surfaced via macOS notifications, failures via a dialog; full detail goes to
# ~/Library/Logs/LES/bootstrap.log.
#
# Strategy (per HANDOFF plan): lightweight bootstrap that reuses the existing
# runtime — install uv if missing, uv sync --extra mac-mlx, download model
# weights on first run, then `lesctl start --include-ui` and open the browser.
set -uo pipefail

APP_TITLE="ЛЕС · Совушка"
UI_URL="http://127.0.0.1:8051/les"

RES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # …/Contents/Resources
RUNTIME_TEMPLATE="$RES_DIR/runtime"                       # bundled clean code export

INSTALL_DIR="${LES_HOME:-$HOME/Library/Application Support/LES}"
LOG_DIR="$HOME/Library/Logs/LES"
LOG="$LOG_DIR/bootstrap.log"

mkdir -p "$LOG_DIR"
exec >>"$LOG" 2>&1
echo "===== $(date '+%Y-%m-%d %H:%M:%S') bootstrap start ====="
echo "RES_DIR=$RES_DIR INSTALL_DIR=$INSTALL_DIR"

notify() {
  /usr/bin/osascript -e "display notification \"$1\" with title \"$APP_TITLE\"" >/dev/null 2>&1 || true
}

fail() {
  echo "FAIL: $1"
  /usr/bin/osascript -e "display dialog \"ЛЕС не смог запуститься: $1\n\nПодробности в логе:\n$LOG\" buttons {\"OK\"} default button 1 with title \"ЛЕС — ошибка\" with icon stop" >/dev/null 2>&1 || true
  exit 1
}

# --- 1. Ensure uv -----------------------------------------------------------
UV=""
ensure_uv() {
  local p
  for p in "$(command -v uv 2>/dev/null)" "$HOME/.local/bin/uv" "/opt/homebrew/bin/uv" "/usr/local/bin/uv"; do
    if [ -n "$p" ] && [ -x "$p" ]; then UV="$p"; echo "uv found: $UV"; return; fi
  done
  notify "Устанавливаю uv (первый запуск)…"
  echo "installing uv…"
  /usr/bin/curl -LsSf https://astral.sh/uv/install.sh | sh || fail "не удалось установить uv"
  for p in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [ -x "$p" ]; then UV="$p"; break; fi
  done
  [ -n "$UV" ] && [ -x "$UV" ] || fail "uv установлен, но не найден в PATH"
  echo "uv installed: $UV"
}
ensure_uv

# --- 2. First run: materialize runtime into a writable install dir ----------
if [ ! -f "$INSTALL_DIR/pyproject.toml" ]; then
  [ -d "$RUNTIME_TEMPLATE" ] || fail "в пакете нет рантайма ($RUNTIME_TEMPLATE)"
  notify "Первый запуск: разворачиваю ЛЕС…"
  echo "copying runtime template → $INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"
  /usr/bin/rsync -a "$RUNTIME_TEMPLATE/" "$INSTALL_DIR/" || fail "копирование рантайма не удалось"
fi
cd "$INSTALL_DIR" || fail "нет каталога установки $INSTALL_DIR"

# --- 3. Environment (uv sync with the mac MLX extra) ------------------------
# Bare `uv sync` evicts mlx-lm (see memory runtime-uv-sync-mlx-extra) → always
# pass --extra mac-mlx.
notify "Готовлю окружение…"
echo "uv sync --extra mac-mlx"
"$UV" sync --extra mac-mlx || fail "uv sync не удался"

# --- 4. .env + runtime directories ------------------------------------------
"$UV" run lesctl init --profile mac-native >/dev/null 2>&1 || true

# --- 5. Model weights (download-on-first-run, idempotent) -------------------
notify "Проверяю модели…"
echo "onboard models"
"$UV" run python tools/onboard_models.py || fail "загрузка моделей не удалась"

# --- 6. Start the stack -----------------------------------------------------
notify "Запускаю службы…"
echo "lesctl start"
"$UV" run lesctl start --profile mac-native --include-ui --memory-preflight || fail "не удалось поднять службы"

# --- 7. Open the UI ---------------------------------------------------------
/usr/bin/open "$UI_URL" || true
notify "Совушка готова."
echo "===== $(date '+%Y-%m-%d %H:%M:%S') bootstrap done ====="
exit 0
