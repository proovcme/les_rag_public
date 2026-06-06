#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROFILE="linux-docker"
INIT_ENV=0
FORCE_ENV=0
SYNC=0
START=0
INSTALL_UNITS=0
ENABLE_UNITS=0

usage() {
  cat <<'EOF'
Usage: installers/linux/install.sh [options]

Options:
  --profile <linux-docker|linux-systemd|server-remote-model>
  --init-env          create .env from env.example if missing
  --force-env         overwrite .env from env.example
  --sync              run uv sync
  --start             start services for docker profile
  --install-units     install user systemd units for linux-systemd profile
  --enable-units      enable installed user systemd units
  -h, --help          show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="${2:-}"; shift 2 ;;
    --init-env) INIT_ENV=1; shift ;;
    --force-env) FORCE_ENV=1; shift ;;
    --sync) SYNC=1; shift ;;
    --start) START=1; shift ;;
    --install-units) INSTALL_UNITS=1; shift ;;
    --enable-units) ENABLE_UNITS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$PROFILE" in
  linux-docker|linux-systemd|server-remote-model) ;;
  *) echo "Unsupported profile: $PROFILE" >&2; exit 2 ;;
esac

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

cd "$ROOT"
require uv
require python3

mkdir -p data storage logs RAG_Content artifacts artifacts/backups

if [[ "$INIT_ENV" -eq 1 || "$FORCE_ENV" -eq 1 ]]; then
  if [[ -f .env && "$FORCE_ENV" -ne 1 ]]; then
    echo ".env exists"
  else
    cp env.example .env
    echo ".env created from env.example"
  fi
fi

if [[ "$SYNC" -eq 1 ]]; then
  uv sync
fi

uv run lesctl doctor --profile "$PROFILE"

if [[ "$PROFILE" == "linux-docker" ]]; then
  require docker
  if [[ "$START" -eq 1 ]]; then
    docker compose -f installers/linux/docker-compose.yml --project-directory "$ROOT" up -d qdrant proxy ui
  fi
fi

if [[ "$PROFILE" == "linux-systemd" ]]; then
  require systemctl
  if [[ "$INSTALL_UNITS" -eq 1 || "$ENABLE_UNITS" -eq 1 ]]; then
    unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$unit_dir"
    sed "s#__LES_ROOT__#$ROOT#g" installers/linux/systemd/les-proxy.service > "$unit_dir/les-proxy.service"
    sed "s#__LES_ROOT__#$ROOT#g" installers/linux/systemd/les-ui.service > "$unit_dir/les-ui.service"
    systemctl --user daemon-reload
    echo "Installed user units into $unit_dir"
  fi
  if [[ "$ENABLE_UNITS" -eq 1 ]]; then
    systemctl --user enable les-proxy les-ui
  fi
fi

echo "LES $PROFILE install step complete."

