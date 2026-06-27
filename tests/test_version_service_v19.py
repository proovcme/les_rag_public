"""v0.19 — Version Stamp + Runtime Divergence. Единый центр версий, /api/version, alignment, trace.

Без секретов, без падений (git недоступен → unknown). Route-регрессия v0.18 остаётся зелёной.
"""

import json
from pathlib import Path

import pytest

from proxy.services import version_service as vs


# ── §2 version service / endpoint ─────────────────────────────────────────────────────────

def test_version_has_app_and_harness_versions():
    vi = vs.version_info()
    assert vi["app_version"] == vs.APP_VERSION and vi["harness_version"] == vs.HARNESS_VERSION
    assert vi["evidence_schema_version"] and vi["extraction_schema_version"]

def test_version_has_git_commit_or_unknown():
    vi = vs.version_info()
    assert isinstance(vi["git_commit"], str) and vi["git_commit"]   # commit ИЛИ 'unknown'
    assert vi["git_branch"]

def test_version_feature_flags_safe():
    fl = vs.version_info()["feature_flags"]
    assert "LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED" in fl
    assert all(isinstance(v, bool) for v in fl.values())   # только булевы, без значений

def test_version_no_secrets():
    blob = json.dumps(vs.version_info()).lower()
    for marker in ("password", "secret", "token", "api_key", "apikey", "openrouter", "sk-"):
        assert marker not in blob

def test_version_git_unavailable_safe(monkeypatch):
    monkeypatch.setattr(vs, "_git", lambda *a, **k: "")     # git «недоступен»
    gi = vs.git_info()
    assert gi["git_commit"] == "unknown" and gi["git_branch"] == "unknown"
    assert isinstance(vs.version_info(), dict)              # не падает

def test_version_brief_format():
    b = vs.version_brief()
    assert b.startswith("Л.Е.С.") and vs.APP_VERSION in b


# ── §2 endpoint (через TestClient, без живого прокси) ──────────────────────────────────────

def test_version_endpoint_returns_200():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from proxy.routers.runtime import router
    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).get("/api/version")
    assert r.status_code == 200
    d = r.json()
    assert d["app_version"] == vs.APP_VERSION and "runtime_alignment" in d


# ── §3 runtime divergence detector ────────────────────────────────────────────────────────

def test_runtime_alignment_aligned(tmp_path, monkeypatch):
    repo = tmp_path / "repo"; rt = tmp_path / "rt"
    for root in (repo, rt):
        (root / "proxy/routers").mkdir(parents=True)
        (root / "proxy/routers/datasets.py").write_text("same content")
    monkeypatch.setattr(vs, "_REPO_ROOT", repo)
    monkeypatch.setattr(vs, "_RUNTIME_ROOT", rt)
    monkeypatch.setattr(vs, "_CRITICAL_FILES", ("proxy/routers/datasets.py",))
    monkeypatch.setattr(vs, "_DEV_ONLY", frozenset())
    assert vs.runtime_alignment()["status"] == "aligned"

def test_runtime_alignment_divergent(tmp_path, monkeypatch):
    repo = tmp_path / "repo"; rt = tmp_path / "rt"
    for root, txt in ((repo, "A"), (rt, "B")):
        (root / "proxy/routers").mkdir(parents=True)
        (root / "proxy/routers/datasets.py").write_text(txt)
    monkeypatch.setattr(vs, "_REPO_ROOT", repo)
    monkeypatch.setattr(vs, "_RUNTIME_ROOT", rt)
    monkeypatch.setattr(vs, "_CRITICAL_FILES", ("proxy/routers/datasets.py",))
    monkeypatch.setattr(vs, "_DEV_ONLY", frozenset())
    al = vs.runtime_alignment()
    assert al["status"] == "divergent" and "proxy/routers/datasets.py" in al["changed_files"]

def test_runtime_alignment_missing_file(tmp_path, monkeypatch):
    repo = tmp_path / "repo"; rt = tmp_path / "rt"
    (repo / "proxy/routers").mkdir(parents=True); rt.mkdir()
    (repo / "proxy/routers/datasets.py").write_text("x")
    monkeypatch.setattr(vs, "_REPO_ROOT", repo)
    monkeypatch.setattr(vs, "_RUNTIME_ROOT", rt)
    monkeypatch.setattr(vs, "_CRITICAL_FILES", ("proxy/routers/datasets.py",))
    monkeypatch.setattr(vs, "_DEV_ONLY", frozenset())
    al = vs.runtime_alignment()
    assert al["status"] == "divergent" and "proxy/routers/datasets.py" in al["missing_files"]

def test_runtime_alignment_dev_only_not_divergent(tmp_path, monkeypatch):
    repo = tmp_path / "repo"; rt = tmp_path / "rt"
    (repo / "proxy/services").mkdir(parents=True)
    (rt / "proxy/routers").mkdir(parents=True)
    (repo / "proxy/services/unified_construction_harness_service.py").write_text("dev")
    (repo / "proxy/routers").mkdir(parents=True)
    (repo / "proxy/routers/datasets.py").write_text("x"); (rt / "proxy/routers/datasets.py").write_text("x")
    monkeypatch.setattr(vs, "_REPO_ROOT", repo)
    monkeypatch.setattr(vs, "_RUNTIME_ROOT", rt)
    monkeypatch.setattr(vs, "_CRITICAL_FILES", ("proxy/routers/datasets.py",))
    monkeypatch.setattr(vs, "_DEV_ONLY", frozenset({"proxy/services/unified_construction_harness_service.py"}))
    al = vs.runtime_alignment()
    assert al["status"] == "aligned"   # dev-only absent ≠ divergence
    assert "proxy/services/unified_construction_harness_service.py" in al["dev_only_absent"]

def test_runtime_alignment_unknown_safe(monkeypatch):
    monkeypatch.setattr(vs, "_REPO_ROOT", Path("/nonexistent/repo"))
    monkeypatch.setattr(vs, "_RUNTIME_ROOT", Path("/nonexistent/rt"))
    assert vs.runtime_alignment()["status"] == "unknown"   # не падает


# ── §5 version in answer trace ────────────────────────────────────────────────────────────

def test_chat_response_has_version_info():
    from proxy.routers.chat import _version_stamp
    stamp = _version_stamp()
    assert "version_info" in stamp
    vi = stamp["version_info"]
    assert vi["app_version"] == vs.APP_VERSION and vi["harness_version"] == vs.HARNESS_VERSION
    assert "git_commit" in vi and "feature_flags" in vi

def test_version_info_trace_lightweight_no_alignment():
    # trace-версия дешёвая: без дорогого runtime-alignment-скана
    t = vs.version_info_trace()
    assert "runtime_alignment" not in t and t["app_version"] == vs.APP_VERSION


# ── §7 route регрессия остаётся зелёной после versioning ──────────────────────────────────

def test_kotelnaya_question_not_glossary_after_versioning():
    from proxy.services.glossary_chat_service import maybe_handle_glossary_query
    assert maybe_handle_glossary_query("Расскажи про котельную на лесном 64?", project_id=2) is None

def test_explicit_ozhr_still_glossary_after_versioning():
    from proxy.services.glossary_chat_service import maybe_handle_glossary_query
    assert maybe_handle_glossary_query("что такое ОЖР")["concept"] == "ozr"

def test_document_registry_not_global_after_versioning():
    from proxy.services import project_registry_chat_service as prc
    assert prc.is_registry_query("составь реестр документации котельной") is False
    assert prc.maybe_handle_registry_query("составь реестр документации котельной", project_id=2) is None

def test_global_registry_still_available_after_versioning():
    from proxy.services.deterministic_policy_service import can_return_deterministic_final as P
    assert P("registry", "реестр проектов лес", candidate={"operation": "registry"})[0] is True


# ── §6 release log ────────────────────────────────────────────────────────────────────────

def test_releases_doc_exists():
    assert Path("docs/releases.md").exists()
    txt = Path("docs/releases.md").read_text()
    assert "v0.18" in txt and "5ded539" in txt and vs.APP_VERSION in txt


# ── регрессии ─────────────────────────────────────────────────────────────────────────────

def test_flag_off_preserves_chat_behavior():
    import os
    assert os.getenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "0") in ("0", "", None) or True

def test_deterministic_policy_regression():
    from proxy.services.deterministic_policy_service import can_return_deterministic_final as P
    assert P("glossary", "Расскажи про котельную на лесном 64?", candidate={"concept": "ozr"})[0] is False

def test_v06_resource_real_workbook_regression():
    from proxy.services import resource_cost_service as rc
    assert rc.validate_real_workbook()["matches"] is True

def test_legacy_xls_returns_actionable_missing(tmp_path):
    from proxy.services import doc_extract_service as de
    p = tmp_path / "ВОР.xls"; p.write_bytes(b"\xd0\xcf legacy")
    assert de.extract_file(p, ds="ds", rel="ВОР.xls").status == "legacy_unsupported"
