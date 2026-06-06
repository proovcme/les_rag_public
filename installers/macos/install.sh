#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INIT_ENV=0
FORCE_ENV=0
SYNC=1
START=0
INCLUDE_UI=0

usage() {
  cat <<'EOF'
Usage: installers/macos/install.sh [options]

Options:
  --init-env      create .env from env.example if missing
  --force-env     overwrite .env from env.example
  --no-sync       skip uv sync
  --start         start LES launchd services after install
  --include-ui    include Sovushka UI when starting
  -h, --help      show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --init-env) INIT_ENV=1; shift ;;
    --force-env) FORCE_ENV=1; shift ;;
    --no-sync) SYNC=0; shift ;;
    --start) START=1; shift ;;
    --include-ui) INCLUDE_UI=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

cd "$ROOT"
command -v uv >/dev/null 2>&1 || { echo "Missing uv" >&2; exit 1; }

if [[ "$SYNC" -eq 1 ]]; then
  uv sync
fi

install_args=(install --profile mac-native)
if [[ "$INIT_ENV" -eq 1 ]]; then
  install_args+=(--init-env)
fi
if [[ "$FORCE_ENV" -eq 1 ]]; then
  install_args+=(--force-env)
fi
uv run lesctl "${install_args[@]}"

if [[ "$START" -eq 1 ]]; then
  start_args=(start --profile mac-native --memory-preflight)
  if [[ "$INCLUDE_UI" -eq 1 ]]; then
    start_args+=(--include-ui)
  fi
  uv run lesctl "${start_args[@]}"
fi

echo "LES mac-native install step complete."

