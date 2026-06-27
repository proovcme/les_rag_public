#!/usr/bin/env bash
# Периодический контроль здоровья LES: lesctl doctor → health.log, алерт при FAIL,
# ротация runtime-логов (truncate-in-place, чтобы не ломать launchd KeepAlive).
# Запускается по расписанию (launchd me.ovc.les.doctor).
set -uo pipefail

LES_HOME="${LES_HOME:-/Users/ovc/LES}"
HEALTH_LOG="${HEALTH_LOG:-$LES_HOME/logs/health.log}"
UV="${UV:-/Users/ovc/.local/bin/uv}"
MAXLOG="${MAXLOG:-104857600}"   # 100 МБ
KEEPLOG="${KEEPLOG:-20000000}"  # оставлять хвост 20 МБ

cd "$LES_HOME" 2>/dev/null || exit 0
ts="$(date '+%Y-%m-%d %H:%M:%S')"

out="$("$UV" run lesctl doctor --json 2>/dev/null || true)"
summary="$(printf '%s' "$out" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print("doctor_parse_error"); sys.exit(0)
checks = d.get("checks", [])
fails = [c["name"] for c in checks if c.get("status") == "fail"]
warns = [c["name"] for c in checks if c.get("status") == "warn"]
head = "FAIL" if fails else "OK"
print(f"{head} fail={len(fails)} warn={len(warns)}" + (" :: " + ", ".join(fails) if fails else ""))
' 2>/dev/null)"
[ -z "$summary" ] && summary="doctor_run_error"

echo "[$ts] $summary" >> "$HEALTH_LOG"
case "$summary" in
  FAIL*|doctor_*)
    osascript -e "display notification \"$summary\" with title \"LES doctor — внимание\"" 2>/dev/null || true
    ;;
esac

# Ротация runtime-логов: оставить хвост KEEPLOG, truncate в тот же inode (launchd дописывает дальше).
for f in "$LES_HOME"/logs/proxy.log "$LES_HOME"/logs/mlx_host.log "$LES_HOME"/logs/qdrant.log "$LES_HOME"/logs/sovushka.log; do
  [ -f "$f" ] || continue
  sz="$(stat -f%z "$f" 2>/dev/null || echo 0)"
  if [ "$sz" -gt "$MAXLOG" ]; then
    tail -c "$KEEPLOG" "$f" > "$f.tmp" 2>/dev/null && cat "$f.tmp" > "$f" && rm -f "$f.tmp"
  fi
done
