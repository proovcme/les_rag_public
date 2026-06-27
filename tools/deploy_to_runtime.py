"""Выкатка dev → рантайм-клон без ручных cp/патчей.

Рантайм ЛЕС крутится из `/Users/ovc/LES` (НЕ из dev-репо) и **диверговый** (живые
незакоммиченные правки). Поэтому деплой = порт файлов + точечный рестарт (см. SKILL.md).
Этот скрипт классифицирует каждый изменённый файл и копирует только БЕЗОПАСНЫЕ, а дивергентные
(tracked, рантайм ≠ HEAD — напр. app.py/chat.py с рантайм-онли правками) ПРОПУСКАЕТ с предупреждением.

    uv run python -m tools.deploy_to_runtime              # dry-run: что будет
    uv run python -m tools.deploy_to_runtime --apply      # скопировать безопасные
    uv run python -m tools.deploy_to_runtime --apply --restart   # + kickstart нужных сервисов
    uv run python -m tools.deploy_to_runtime --files a.py b.py   # явный список

Классы файла:
  new            — нет в рантайме → копируем
  identical      — байт-в-байт совпадает → пропуск
  session(new)   — untracked (создан в сессии), рантайм = прежняя моя копия → копируем
  clean@HEAD     — tracked, рантайм == git HEAD (без рантайм-дрейфа) → копируем
  DIVERGENT      — tracked, рантайм ≠ HEAD (рантайм-онли правки) → ПРОПУСК, патчить вручную
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]
RT = Path(os.getenv("LES_RUNTIME_HOME", "/Users/ovc/LES"))
# Манифест last-deployed: {path: sha256 файла на момент моей выкатки}. Чинит ложный DIVERGENT —
# tracked-файл, который я уже выкатил, иначе метится «рантайм ≠ HEAD» (а рантайм = МОЯ копия).
MANIFEST = DEV / ".deploy_manifest.json"

ALLOWED_DIRS = ("proxy/", "backend/", "sovushka/", "tools/", "config/", "docs/")
ALLOWED_FILES = {"sovushka_ng.py", "proxy_server.py", "mlx_host.py"}
ALLOWED_SUFFIX = {".py", ".yaml", ".yml", ".json", ".md", ".txt"}


def _sha(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _load_manifest() -> dict[str, str]:
    import json
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_manifest(m: dict[str, str]) -> None:
    import json
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=0), encoding="utf-8")

# путь-префикс → launchd-сервис для рестарта
SERVICE_BY_PREFIX = (
    ("sovushka_ng.py", "com.les.sovushka"),
    ("sovushka/", "com.les.sovushka"),
    ("proxy/", "me.ovc.les.proxy"),
    ("backend/", "me.ovc.les.proxy"),
    ("config/", "me.ovc.les.proxy"),
)


def _git(args: list[str]) -> str:
    return subprocess.run(["git", "-C", str(DEV), *args],
                          capture_output=True, text=True).stdout


def _changed_files() -> list[str]:
    out = _git(["status", "--porcelain"])
    files: list[str] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:                       # переименование
            path = path.split(" -> ", 1)[1]
        files.append(path)
    return files


def _head_bytes(path: str) -> bytes | None:
    r = subprocess.run(["git", "-C", str(DEV), "show", f"HEAD:{path}"],
                       capture_output=True)
    return r.stdout if r.returncode == 0 else None


def _allowed(path: str) -> bool:
    return (path in ALLOWED_FILES or path.startswith(ALLOWED_DIRS)) and Path(path).suffix in ALLOWED_SUFFIX


def classify(path: str, manifest: dict[str, str]) -> tuple[str, bool]:
    """(класс, безопасно_копировать)."""
    dev_p, rt_p = DEV / path, RT / path
    if not dev_p.is_file():
        return "missing-in-dev", False
    if not rt_p.exists():
        return "new", True
    dev_b, rt_b = dev_p.read_bytes(), rt_p.read_bytes()
    if dev_b == rt_b:
        return "identical", False
    if manifest.get(path) == _sha(rt_b):
        return "deployed", True              # рантайм = МОЯ прошлая выкатка (без рантайм-онли правок)
    head = _head_bytes(path)
    if head is None:
        return "session(new)", True          # untracked: рантайм = моя прежняя копия
    if rt_b == head:
        return "clean@HEAD", True            # рантайм без дрейфа → безопасно
    return "DIVERGENT", False                # рантайм-онли правки → патчить вручную


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Выкатка dev → рантайм-клон")
    ap.add_argument("--apply", action="store_true", help="скопировать безопасные (иначе dry-run)")
    ap.add_argument("--restart", action="store_true", help="kickstart затронутых сервисов")
    ap.add_argument("--force", action="store_true",
                    help="копировать и DIVERGENT (мои файлы, рантайм-онли правок нет) + записать в манифест")
    ap.add_argument("--files", nargs="*", help="явный список (иначе git status)")
    args = ap.parse_args(argv)

    candidates = [f for f in (args.files or _changed_files()) if _allowed(f)]
    if not candidates:
        print("Нечего выкатывать (нет изменённых разрешённых файлов).")
        return 0

    manifest = _load_manifest()
    copied: list[str] = []
    services: set[str] = set()
    diverged: list[str] = []
    print(f"Рантайм: {RT}\n{'ВЫКАТКА' if args.apply else 'DRY-RUN (--apply чтобы применить)'}\n")
    for f in sorted(candidates):
        kind, safe = classify(f, manifest)
        forced = (not safe) and kind == "DIVERGENT" and args.force
        ok = safe or forced
        verb = "FORCE-копирую" if forced else "копирую"
        mark = f"→ {verb}" if (ok and args.apply) else ("→ скопирую" if ok else "✗ пропуск")
        print(f"  [{kind:13}] {f}  {mark}")
        if not ok:
            if kind == "DIVERGENT":
                diverged.append(f)
            continue
        if args.apply:
            (RT / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(DEV / f, RT / f)
            manifest[f] = _sha((DEV / f).read_bytes())   # запомнить, что выкатил
            copied.append(f)
        for prefix, svc in SERVICE_BY_PREFIX:
            if f.startswith(prefix):
                services.add(svc)
                break

    print()
    if diverged:
        print("⚠ ДИВЕРГЕНТНЫЕ (патчить вручную Edit'ом, рантайм ≠ HEAD):")
        for f in diverged:
            print(f"    {f}")
    if args.apply:
        if copied:
            _save_manifest(manifest)
        # v0.20 deploy stamp: зафиксировать, что РЕАЛЬНО задеплоено (cp ≠ git HEAD рантайма).
        try:
            from datetime import datetime, timezone
            from proxy.services.version_service import write_deploy_stamp
            sp = write_deploy_stamp(dev_root=DEV, runtime_root=RT,
                                    deployed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    notes=[f"copied {len(copied)} files"])
            print(f"  ⓘ deploy stamp: {sp}")
        except Exception as _e:  # noqa: BLE001
            print(f"  ⚠ deploy stamp не записан: {_e}")
        print(f"Скопировано: {len(copied)}.")
        if args.restart and services:
            uid = os.getuid()
            for svc in sorted(services):
                subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{svc}"])
                print(f"  ↻ рестарт {svc}")
        elif services:
            print(f"Рестарт нужен (добавь --restart): {', '.join(sorted(services))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
