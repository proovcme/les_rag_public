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

APP_VERSION = "5.1.0"                 # пользовательская «маркетинговая» версия ЛЕС
HARNESS_VERSION = "0.24"             # веха roadmap (v0.NN); двигать на смене вехи
# Гранулярная версия «где мы»: 0.<веха>.<фича>.<патч>. Двигать КАЖДУЮ фичу/фикс + строка в
# docs/RELEASE_LEDGER.md. Это основной номер в /api/version и бейдже (см. docs/RELEASE_LEDGER.md).
LES_VERSION = "0.24.0.46"
EVIDENCE_SCHEMA_VERSION = "1.0"
EXTRACTION_SCHEMA_VERSION = "1.0"
RESOURCE_CALC_VERSION = "0.6"

# корни для проверки divergence (можно переопределить env'ом)
_REPO_ROOT = Path(os.getenv("LES_REPO_ROOT", "/Users/ovc/Projects/LES_v2"))
_RUNTIME_ROOT = Path(os.getenv("LES_RUNTIME_HOME", "/Users/ovc/LES"))

# критичные файлы, по которым ловим расхождение repo↔runtime (хэш, не полный diff).
# v0.22: + GUI-файлы (sovushka) — иначе deploy stamp слеп к фронт-правкам и не флипается в stale.
_CRITICAL_FILES = (
    "backend/qdrant_adapter.py",
    "proxy/app.py",
    "proxy/routers/external_radar.py",
    "proxy/routers/datasets.py",
    "proxy/routers/chat.py",
    "proxy/routers/doc_review.py",
    "proxy/routers/runtime.py",
    "proxy/routers/service_sources.py",
    "proxy/routers/notebooks.py",
    "proxy/routers/prompts.py",
    "proxy/services/doc_extract_service.py",
    "proxy/services/context_memory_service.py",
    "proxy/services/lexical_index_service.py",
    "proxy/services/notebook_service.py",
    "proxy/services/prompt_registry_service.py",
    "proxy/services/saferag_service.py",
    "proxy/services/external_radar_service.py",
    "proxy/services/doc_review_service.py",
    "proxy/services/candidate_selection_service.py",
    "proxy/services/estimate_harness_service.py",
    "proxy/services/estimate_math_service.py",
    "proxy/services/sidecar_ops_service.py",
    "proxy/services/deterministic_policy_service.py",
    "proxy/services/glossary_chat_service.py",
    "proxy/services/memory_service.py",
    "proxy/services/notebook_study_service.py",
    "proxy/services/smeta_chat_service.py",
    "proxy/services/service_source_registry.py",
    "proxy/services/scope_service.py",
    "proxy/services/title_block_extract_service.py",
    "proxy/services/version_service.py",
    "proxy/services/workflow_plan_service.py",
    "proxy/routers/chat_history.py",
    "sovushka/pages/chat.py",
    "sovushka/pages/instrumenty.py",
    "sovushka/components/header.py",
    "sovushka/answer_render.py",
    "sovushka/styles.py",
    "sovushka_ng.py",
    "config/service_sources.yaml",
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


# ── deploy stamp (v0.20): что РЕАЛЬНО задеплоено (cp-деплой ≠ git HEAD рантайма) ───────────

DEPLOY_STAMP_NAME = ".les_deploy_stamp.json"
# файлы в хэш-бандле стампа (совпадает с критичными — но стамп фиксирует моментальный снимок деплоя)
DEPLOY_BUNDLE_FILES = _CRITICAL_FILES


def deploy_stamp_path() -> Path:
    return _RUNTIME_ROOT / DEPLOY_STAMP_NAME


def write_deploy_stamp(*, dev_root: Path | None = None, runtime_root: Path | None = None,
                       deployed_at: str = "", deployed_commit: str = "", deployed_branch: str = "",
                       notes: list[str] | None = None) -> Path:
    """Записать deploy stamp в runtime: версии + commit + хэш-бандл реально скопированных файлов.
    Вызывается deploy-тулом на --apply. Хэши берутся из RUNTIME (что фактически лежит)."""
    import json
    dev = Path(dev_root) if dev_root else _code_root()
    rt = Path(runtime_root) if runtime_root else _RUNTIME_ROOT
    if not deployed_commit:
        deployed_commit = _git(["rev-parse", "--short", "HEAD"], dev) or "unknown"
        deployed_branch = deployed_branch or _git(["rev-parse", "--abbrev-ref", "HEAD"], dev) or "unknown"
    bundle: dict[str, str] = {}
    for rel in DEPLOY_BUNDLE_FILES:
        h = _sha(rt / rel)
        if h is not None:
            bundle[rel] = h
    stamp = {
        "les_version": LES_VERSION, "app_version": APP_VERSION, "harness_version": HARNESS_VERSION,
        "deployed_commit": deployed_commit, "deployed_branch": deployed_branch,
        "deployed_at": deployed_at or "unknown", "deployed_by": "local",
        "deploy_method": "copy_files", "file_hash_bundle": bundle, "notes": notes or [],
    }
    p = rt / DEPLOY_STAMP_NAME
    p.write_text(json.dumps(stamp, ensure_ascii=False, indent=2))
    return p


def deploy_stamp() -> dict[str, Any]:
    """Прочитать deploy stamp + сверить хэши с фактическими runtime-файлами. Нет стампа →
    {'status': 'deploy_stamp_missing'} (warning, не падение)."""
    import json
    p = deploy_stamp_path()
    if not p.is_file():
        return {"status": "deploy_stamp_missing",
                "note": "deploy выполнен без стампа — точный состав файлов неизвестен"}
    try:
        st = json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return {"status": "deploy_stamp_unreadable"}
    bundle = st.get("file_hash_bundle") or {}
    mismatch: list[str] = []
    for rel, stored in bundle.items():
        cur = _sha(_RUNTIME_ROOT / rel)
        if cur is not None and cur != stored:
            mismatch.append(rel)         # файл изменён ПОСЛЕ стампа (cp/ручная правка)
    st["status"] = "stale" if mismatch else "ok"
    st["hash_mismatch_files"] = mismatch
    return st


def version_info() -> dict[str, Any]:
    """Полный version-объект для /api/version и version-drawer. Без секретов."""
    gi = git_info()
    try:
        from proxy.services import doc_extract_service as de
        extractor = getattr(de, "EXTRACTOR_VERSION", EXTRACTION_SCHEMA_VERSION)
    except Exception:  # noqa: BLE001
        extractor = EXTRACTION_SCHEMA_VERSION
    align = runtime_alignment()
    ds = deploy_stamp()
    import sys
    return {
        "les_version": LES_VERSION,
        "app_version": APP_VERSION,
        "harness_version": HARNESS_VERSION,
        "deployed_commit": ds.get("deployed_commit", "unknown"),
        "deployed_les_version": ds.get("les_version", "unknown"),
        "deploy_stamp": ds,
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
        "les_version": LES_VERSION,
        "app_version": APP_VERSION,
        "harness_version": HARNESS_VERSION,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "git_commit": gi["git_commit"],
        "git_branch": gi["git_branch"],
        "feature_flags": feature_flags(),
    }


def version_brief() -> str:
    """Короткая строка для бейджа: «Л.Е.С. 5.1.0 · h0.20 · 5ded539»."""
    gi = git_info()
    c = gi["git_commit"]
    return (f"Л.Е.С. {LES_VERSION} · app {APP_VERSION} · h{HARNESS_VERSION}"
            + (f" · {c}" if c and c != "unknown" else ""))
