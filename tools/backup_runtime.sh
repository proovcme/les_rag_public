#!/usr/bin/env bash
# LES runtime backup — Qdrant snapshots + consistent SQLite metabase copy + .env.
# Цель восстановления: индекс (169k точек) и метабаза не теряются при сбое диска.
# Бэкапы кладутся на отдельный том (по умолчанию USB-SSD /Volumes/Data).
#
#   tools/backup_runtime.sh            # разовый бэкап
#   LES_HOME=/Users/ovc/LES BACKUP_ROOT=/Volumes/Data/les_backups tools/backup_runtime.sh
#
# Ретенция: хранить последние KEEP датированных папок.
set -euo pipefail

LES_HOME="${LES_HOME:-/Users/ovc/LES}"
QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
BACKUP_ROOT="${BACKUP_ROOT:-/Volumes/Data/les_backups}"
KEEP="${KEEP:-5}"
META_DB="${META_DB:-$LES_HOME/data/les_meta_qwen.db}"

ts="$(date +%Y%m%d_%H%M%S)"
dest="$BACKUP_ROOT/$ts"

# Том бэкапа должен быть смонтирован (USB можно отключить) — иначе не льём на корень.
if [ ! -d "$BACKUP_ROOT" ]; then
  if ! mkdir -p "$BACKUP_ROOT" 2>/dev/null; then
    echo "[backup] FAIL: целевой том недоступен: $BACKUP_ROOT" >&2
    exit 1
  fi
fi
mkdir -p "$dest"
echo "[backup] $ts → $dest"

# 1. Qdrant: снапшот каждой коллекции + скачивание в бэкап.
cols="$(curl -fsS "$QDRANT_URL/collections" | python3 -c 'import sys,json;[print(c["name"]) for c in json.load(sys.stdin)["result"]["collections"]]')"
for col in $cols; do
  snap="$(curl -fsS -X POST "$QDRANT_URL/collections/$col/snapshots" | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["name"])')"
  curl -fsS "$QDRANT_URL/collections/$col/snapshots/$snap" -o "$dest/$col.snapshot"
  # подчистить снапшот в живом сторадже (он уже скачан), чтобы не копить на системном томе
  curl -fsS -X DELETE "$QDRANT_URL/collections/$col/snapshots/$snap" >/dev/null || true
  echo "[backup]   qdrant $col → $(du -h "$dest/$col.snapshot" | cut -f1)"
done

# 2. SQLite метабаза — консистентная копия (.backup, а не cp на живой БД).
if [ -f "$META_DB" ]; then
  sqlite3 "$META_DB" ".backup '$dest/les_meta_qwen.db'"
  echo "[backup]   metabase → $(du -h "$dest/les_meta_qwen.db" | cut -f1)"
fi

# 3. .env (конфиг + ключи) — права 600.
if [ -f "$LES_HOME/.env" ]; then
  cp "$LES_HOME/.env" "$dest/.env" && chmod 600 "$dest/.env"
  echo "[backup]   .env скопирован"
fi

# Манифест + ретенция.
{ echo "ts=$ts"; echo "les_home=$LES_HOME"; echo "collections=$cols"; } > "$dest/MANIFEST.txt"
ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null | tail -n +$((KEEP+1)) | while read -r old; do
  echo "[backup]   ретенция: удаляю старый $old"; rm -rf "$old"
done

echo "[backup] OK: $(du -sh "$dest" | cut -f1) в $dest"
