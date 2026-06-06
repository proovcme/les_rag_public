#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DRY_RUN=1
PURGE_VENV=0
PURGE_ENV=0
PURGE_RUNTIME=0
PURGE_CORPORA=0
CONFIRM_PURGE_DATA=0
GUI_DOMAIN="gui/$(id -u)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

SERVICES=(
  "me.ovc.les.qdrant:me.ovc.les.qdrant.plist"
  "me.ovc.les.mlx:me.ovc.les.mlx.plist"
  "me.ovc.les.proxy:me.ovc.les.proxy.plist"
  "me.ovc.les.qwen-index-until-done:me.ovc.les.qwen-index-until-done.plist"
  "com.les.sovushka:com.les.sovushka.plist"
)

usage() {
  cat <<'EOF'
Usage: installers/macos/uninstall.sh [options]

Default mode is dry-run. It prints what would be stopped/removed.

Options:
  --confirm              actually stop launchd services and remove LES plists
  --purge-venv           remove .venv
  --purge-env            remove .env
  --purge-runtime-data   remove data, storage, logs, artifacts, snapshots
  --purge-corpora        remove RAG_Content
  --confirm-purge-data   required together with --purge-runtime-data or --purge-corpora
  -h, --help             show help

Data purge is intentionally separate from service uninstall.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --confirm) DRY_RUN=0; shift ;;
    --purge-venv) PURGE_VENV=1; shift ;;
    --purge-env) PURGE_ENV=1; shift ;;
    --purge-runtime-data) PURGE_RUNTIME=1; shift ;;
    --purge-corpora) PURGE_CORPORA=1; shift ;;
    --confirm-purge-data) CONFIRM_PURGE_DATA=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$DRY_RUN" -eq 1 && ( "$PURGE_VENV" -eq 1 || "$PURGE_ENV" -eq 1 || "$PURGE_RUNTIME" -eq 1 || "$PURGE_CORPORA" -eq 1 ) ]]; then
  echo "Refusing purge flags in dry-run mode. Add --confirm to execute." >&2
  exit 2
fi

if [[ ( "$PURGE_RUNTIME" -eq 1 || "$PURGE_CORPORA" -eq 1 ) && "$CONFIRM_PURGE_DATA" -ne 1 ]]; then
  echo "Data purge requires --confirm-purge-data." >&2
  exit 2
fi

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] %q' "$1"
    shift
    printf ' %q' "$@"
    printf '\n'
  else
    "$@" || true
  fi
}

remove_path() {
  local path="$1"
  if [[ -e "$path" || -L "$path" ]]; then
    run rm -rf "$path"
  elif [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] missing: $path"
  fi
}

for item in "${SERVICES[@]}"; do
  label="${item%%:*}"
  plist="${item##*:}"
  agent="$LAUNCH_AGENTS/$plist"
  run launchctl bootout "$GUI_DOMAIN" "$agent"
  remove_path "$agent"
  run launchctl disable "$GUI_DOMAIN/$label"
done

if [[ "$PURGE_VENV" -eq 1 ]]; then
  remove_path "$ROOT/.venv"
fi

if [[ "$PURGE_ENV" -eq 1 ]]; then
  remove_path "$ROOT/.env"
fi

if [[ "$PURGE_RUNTIME" -eq 1 ]]; then
  for path in "$ROOT/data" "$ROOT/storage" "$ROOT/logs" "$ROOT/artifacts" "$ROOT/snapshots"; do
    remove_path "$path"
  done
fi

if [[ "$PURGE_CORPORA" -eq 1 ]]; then
  remove_path "$ROOT/RAG_Content"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Dry-run complete. Re-run with --confirm to execute."
else
  echo "LES macOS uninstall step complete."
fi

