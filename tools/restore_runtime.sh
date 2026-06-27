#!/usr/bin/env bash
# LES runtime RESTORE — обратная к tools/backup_runtime.sh.
# Восстанавливает Qdrant-коллекции (upload снапшотов) + SQLite-метабазу из папки бэкапа.
# По умолчанию .env НЕ трогает (там живые ключи + LES_EMBED_PROFILE) — иначе откатишь профиль/ключ.
#
#   tools/restore_runtime.sh <backup_dir>            # восстановить
#   tools/restore_runtime.sh <backup_dir> --dry-run  # только показать план, ничего не менять
#   tools/restore_runtime.sh <backup_dir> --env      # вместе с .env (осторожно: откатит ключи/профиль)
#
# ВНИМАНИЕ: операция ПЕРЕЗАПИСЫВАЕТ живой индекс и метабазу. Это аварийное восстановление.
set -euo pipefail

LES_HOME="${LES_HOME:-/Users/ovc/LES}"
QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
META_DB="${META_DB:-$LES_HOME/data/les_meta_qwen.db}"
PROXY_LABEL="me.ovc.les.proxy"
PLIST="$HOME/Library/LaunchAgents/$PROXY_LABEL.plist"

SRC="${1:-}"; [ $# -gt 0 ] && shift || true
DRY=0; WITH_ENV=0
for a in "$@"; do case "$a" in --dry-run) DRY=1;; --env) WITH_ENV=1;; esac; done

[ -n "$SRC" ] && [ -d "$SRC" ] || { echo "[restore] укажи существующую папку бэкапа" >&2; exit 1; }
[ -f "$SRC/MANIFEST.txt" ] || echo "[restore] WARN: нет MANIFEST.txt — точно ли это бэкап ЛЕС?" >&2
if [ -f "$SRC/SHA256SUMS.txt" ]; then
  echo "[restore] checksum: проверяю SHA256SUMS.txt…"
  (cd "$SRC" && shasum -a 256 -c SHA256SUMS.txt >/dev/null) || {
    echo "[restore] FAIL: checksum mismatch — восстановление остановлено" >&2
    exit 1
  }
  echo "[restore] checksum: ok"
else
  echo "[restore] WARN: нет SHA256SUMS.txt — целостность архива не проверена" >&2
fi

snaps=()
while IFS= read -r s; do [ -n "$s" ] && snaps+=("$s"); done < <(ls -1 "$SRC"/*.snapshot 2>/dev/null || true)

echo "[restore] источник: $SRC"
for s in "${snaps[@]:-}"; do [ -n "${s:-}" ] && echo "[restore]   снапшот: $(basename "$s") ($(du -h "$s" | cut -f1)) → коллекция $(basename "$s" .snapshot)"; done
if [ -f "$SRC/les_meta_qwen.db" ]; then echo "[restore]   SQLite: les_meta_qwen.db ($(du -h "$SRC/les_meta_qwen.db" | cut -f1)) → $META_DB"; fi
if [ "$WITH_ENV" = 1 ]; then echo "[restore]   .env будет ВОССТАНОВЛЕН (--env): откатит ключи/профиль"; else echo "[restore]   .env НЕ трогаю (живые ключи + LES_EMBED_PROFILE); добавь --env чтобы включить"; fi

if [ "$DRY" = 1 ]; then echo "[restore] DRY-RUN — ничего не изменено."; exit 0; fi

# 1. Qdrant: upload каждого снапшота (recover коллекции). Qdrant должен быть жив.
curl -fsS "$QDRANT_URL/collections" >/dev/null || { echo "[restore] FAIL: Qdrant недоступен ($QDRANT_URL)" >&2; exit 1; }
for s in "${snaps[@]:-}"; do
  [ -n "${s:-}" ] || continue
  col="$(basename "$s" .snapshot)"
  echo "[restore]   Qdrant: $col ← $(basename "$s") (upload, может занять минуту)…"
  if curl -fsS -X POST "$QDRANT_URL/collections/$col/snapshots/upload?priority=snapshot" \
        -H "Content-Type:multipart/form-data" -F "snapshot=@$s" >/dev/null; then
    echo "[restore]     ok"
  else
    echo "[restore]     FAIL: $col не восстановлен" >&2
  fi
done

# 2. SQLite: останавливаем proxy (освободить БД), копируем, поднимаем обратно.
if [ -f "$SRC/les_meta_qwen.db" ]; then
  echo "[restore]   STOP $PROXY_LABEL (освобождаю SQLite)…"
  launchctl bootout "gui/$(id -u)/$PROXY_LABEL" 2>/dev/null || true
  sleep 1
  cp -f "$META_DB" "$META_DB.pre_restore" 2>/dev/null || true   # страховка: текущая БД рядом
  cp -f "$SRC/les_meta_qwen.db" "$META_DB"
  rm -f "$META_DB-wal" "$META_DB-shm"
  echo "[restore]   SQLite восстановлена (прежняя → $META_DB.pre_restore)"
  echo "[restore]   START $PROXY_LABEL…"
  launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl kickstart -k "gui/$(id -u)/$PROXY_LABEL" 2>/dev/null || true
fi

# 3. .env — только по явному флагу.
if [ "$WITH_ENV" = 1 ] && [ -f "$SRC/.env" ]; then
  cp -f "$LES_HOME/.env" "$LES_HOME/.env.pre_restore" 2>/dev/null || true
  cp -f "$SRC/.env" "$LES_HOME/.env" && chmod 600 "$LES_HOME/.env"
  echo "[restore]   .env восстановлен (прежний → .env.pre_restore)"
fi

echo "[restore] OK. Проверь: /api/health (профиль/коллекция) и каталог датасетов."
