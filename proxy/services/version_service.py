"""version_service (v0.19) — ЕДИНЫЙ центр версий ЛЕС: product/harness/schema + git + флаги + runtime-
divergence. Чтобы оператор сразу видел, ЧТО запущено и какой commit откатывать. Без секретов, без падений.

Версии берутся отсюда (не хардкодятся по UI). `/api/version` отдаёт version_info(); чат кладёт version_info
в trace; бейдж в шапке показывает version_brief().
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── центральные версии ────────────────────────────────────────────────────────────────────

APP_VERSION = "5.1.0"                 # пользовательская версия ЛЕС
HARNESS_VERSION = "0.19"             # внутренний строительный контур (unified harness)
EVIDENCE_SCHEMA_VERSION = "1.0"
EXTRACTION_SCHEMA_VERSION = "1.0"
RESOURCE_CALC_VERSION = "0.6"

# корни для проверки divergence (можно переопределить env'ом)
_REPO_ROOT = Path(os.getenv("LES_REPO_ROOT", "/Users/ovc/Projects/LES_v2"))
_RUNTIME_ROOT = Path(os.getenv("LES_RUNTIME_HOME", "/Users/ovc/LES"))

# критичные файлы, по которым ловим расхождение repo↔runtime (хэш, не полный diff)
_CRITICAL_FILES = (
    "proxy/routers/datasets.py",
    "proxy/routers/chat.py",
    "proxy/services/doc_extract_service.py",
    "proxy/services/sidecar_ops_service.py",
    "proxy/services/deterministic_policy_service.py",
    "proxy/services/glossary_chat_service.py",
    "proxy/services/version_service.py",
)
# файлы, которых в рантайме намеренно НЕТ (flag-OFF, dev-only) — их отсутствие НЕ divergence
_DEV_ONLY = frozenset({
    "proxy/services/unified_construction_harness_service.py",
})

# безопасные флаги (булевы, без секретов)
_SAFE_FLAGS = (
    "LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED",
    "LES_ALLOW_RUNTIME_SIDECAR_WRITE",
    "LES_ROUTER_PRIMARY",
    "LES_AGENT_LOOP",
    "LES_EXTERNAL_ALLOW_ANY",
)


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _code_root() -> Path:
    """Корень дерева, из которого реально исполняется код (для git/build_time)."""
    return Path(__file__).resolve().parents[2]


def _git(args: list[str], cwd: Path) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=4)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def git_info() -> dict[str, Any]:
    """commit/branch/dirty из дерева исполняемого кода. Нет git → 'unknown' (не падаем)."""
    root = _code_root()
    commit = _git(["rev-parse", "--short", "HEAD"], root) or "unknown"
    full = _git(["rev-parse", "HEAD"], root) or "unknown"
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], root) or "unknown"
    dirty = bool(_git(["status", "--porcelain"], root))
    return {"git_commit": commit, "git_commit_full": full, "git_branch": branch, "repo_dirty": dirty}


def _build_time() -> str:
    """Приближение времени сборки/деплоя — mtime модуля (когда выкатили этот файл)."""
    try:
        ts = Path(__file__).stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        return "unknown"


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else None
    except Exception:  # noqa: BLE001
        return None


def runtime_alignment() -> dict[str, Any]:
    """Расхождение repo↔runtime по критичным файлам (хэш). status: aligned|divergent|unknown.
    Не падает, не делает дорогой полный diff."""
    if not _REPO_ROOT.exists() or not _RUNTIME_ROOT.exists():
        return {"status": "unknown", "reason": "repo_or_runtime_path_unavailable",
                "repo_root": str(_REPO_ROOT), "runtime_root": str(_RUNTIME_ROOT),
                "changed_files": [], "missing_files": []}
    changed: list[str] = []
    missing: list[str] = []
    dev_only_absent: list[str] = []
    checked = 0
    for rel in tuple(_CRITICAL_FILES) + tuple(_DEV_ONLY):
        rp, xp = _REPO_ROOT / rel, _RUNTIME_ROOT / rel
        rh, xh = _sha(rp), _sha(xp)
        if rh is None and xh is None:
            continue
        if xh is None:
            (dev_only_absent if rel in _DEV_ONLY else missing).append(rel)
            continue
        checked += 1
        if rh is not None and rh != xh:
            changed.append(rel)
    if checked == 0 and not missing:
        status = "unknown"
    elif changed or missing:          # реальное расхождение по деплоящимся файлам
        status = "divergent"
    else:
        status = "aligned"            # dev-only-отсутствие не считается расхождением
    return {"status": status, "repo_root": str(_REPO_ROOT), "runtime_root": str(_RUNTIME_ROOT),
            "changed_files": changed, "missing_files": missing,
            "dev_only_absent": dev_only_absent, "checked": checked}


def feature_flags() -> dict[str, bool]:
    return {name: _flag(name) for name in _SAFE_FLAGS}


def version_info() -> dict[str, Any]:
    """Полный version-объект для /api/version и version-drawer. Без секретов."""
    gi = git_info()
    try:
        from proxy.services import doc_extract_service as de
        extractor = getattr(de, "EXTRACTOR_VERSION", EXTRACTION_SCHEMA_VERSION)
    except Exception:  # noqa: BLE001
        extractor = EXTRACTION_SCHEMA_VERSION
    align = runtime_alignment()
    import sys
    return {
        "app_version": APP_VERSION,
        "harness_version": HARNESS_VERSION,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "extraction_schema_version": EXTRACTION_SCHEMA_VERSION,
        "resource_calc_version": RESOURCE_CALC_VERSION,
        "git_commit": gi["git_commit"],
        "git_commit_full": gi["git_commit_full"],
        "git_branch": gi["git_branch"],
        "repo_dirty": gi["repo_dirty"],
        "build_time": _build_time(),
        "runtime_path": str(_RUNTIME_ROOT),
        "python": sys.version.split()[0],
        "feature_flags": feature_flags(),
        "runtime_alignment": align,
        "components": {
            "proxy": APP_VERSION,
            "harness": HARNESS_VERSION,
            "extractor": str(extractor),
            "resource_calc": RESOURCE_CALC_VERSION,
            "evidence": EVIDENCE_SCHEMA_VERSION,
        },
    }


def version_info_trace() -> dict[str, Any]:
    """Лёгкий version_info для trace каждого ответа (без runtime-divergence-сканов, дёшево)."""
    gi = git_info()
    return {
        "app_version": APP_VERSION,
        "harness_version": HARNESS_VERSION,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "git_commit": gi["git_commit"],
        "git_branch": gi["git_branch"],
        "feature_flags": feature_flags(),
    }


def version_brief() -> str:
    """Короткая строка для бейджа: «Л.Е.С. 5.1.0 · 5ded539»."""
    gi = git_info()
    c = gi["git_commit"]
    return f"Л.Е.С. {APP_VERSION}" + (f" · {c}" if c and c != "unknown" else "")
