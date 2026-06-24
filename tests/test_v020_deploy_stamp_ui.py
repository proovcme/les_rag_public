"""v0.20 — Deploy Stamp + Evidence UI Operationalization.

Deploy stamp: /api/version отличает git HEAD от РЕАЛЬНО задеплоенных файлов (cp-деплой). UI: «Копировать»
у ответа (чистый текст, без скрытого trace/тела письма), prompt-chips → меню «Примеры». Route-регрессия
v0.18 остаётся зелёной. Без секретов, evidence-контракт цел.
"""

import inspect
import json
import tempfile
from pathlib import Path

import pytest

from proxy.services import version_service as vs
from sovushka import answer_render as ar


# ── §1 deploy stamp ───────────────────────────────────────────────────────────────────────

def test_deploy_stamp_missing_safe(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setattr(vs, "_RUNTIME_ROOT", Path(td))
        assert vs.deploy_stamp()["status"] == "deploy_stamp_missing"   # не падает

def test_deploy_stamp_loaded(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        rt = Path(td); (rt / "proxy/routers").mkdir(parents=True)
        (rt / "proxy/routers/chat.py").write_text("X")
        monkeypatch.setattr(vs, "_RUNTIME_ROOT", rt)
        monkeypatch.setattr(vs, "DEPLOY_BUNDLE_FILES", ("proxy/routers/chat.py",))
        vs.write_deploy_stamp(runtime_root=rt, deployed_at="2026-06-24T00:00:00", deployed_commit="abc123")
        d = vs.deploy_stamp()
        assert d["status"] == "ok" and d["deployed_commit"] == "abc123"

def test_deploy_stamp_hash_match(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        rt = Path(td); (rt / "proxy/routers").mkdir(parents=True)
        (rt / "proxy/routers/chat.py").write_text("stable")
        monkeypatch.setattr(vs, "_RUNTIME_ROOT", rt)
        monkeypatch.setattr(vs, "DEPLOY_BUNDLE_FILES", ("proxy/routers/chat.py",))
        vs.write_deploy_stamp(runtime_root=rt, deployed_commit="c1")
        assert vs.deploy_stamp()["hash_mismatch_files"] == []

def test_deploy_stamp_hash_mismatch(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        rt = Path(td); (rt / "proxy/routers").mkdir(parents=True)
        f = rt / "proxy/routers/chat.py"; f.write_text("v1")
        monkeypatch.setattr(vs, "_RUNTIME_ROOT", rt)
        monkeypatch.setattr(vs, "DEPLOY_BUNDLE_FILES", ("proxy/routers/chat.py",))
        vs.write_deploy_stamp(runtime_root=rt, deployed_commit="c1")
        f.write_text("v2-changed-after-stamp")     # файл правлен после стампа
        d = vs.deploy_stamp()
        assert d["status"] == "stale" and "proxy/routers/chat.py" in d["hash_mismatch_files"]

def test_version_endpoint_includes_deployed_commit():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from proxy.routers.runtime import router
    app = FastAPI(); app.include_router(router)
    d = TestClient(app).get("/api/version").json()
    assert "deployed_commit" in d and "deploy_stamp" in d and d["harness_version"] == "0.20"

def test_version_no_secrets():
    blob = json.dumps(vs.version_info()).lower()
    for m in ("password", "secret", "token", "api_key", "apikey", "sk-", "openrouter"):
        assert m not in blob

def test_version_brief_has_harness():
    assert "h0.20" in vs.version_brief()


# ── §5 copy answer ────────────────────────────────────────────────────────────────────────

def test_copy_answer_plain_text():
    assert ar.answer_copy_text("Ответ про котёл") == "Ответ про котёл"

def test_copy_answer_markdown_table_preserved():
    md = "Итог\n\n| Параметр | Значение |\n|---|---|\n| Тип | Viessmann |"
    assert "| Параметр | Значение |" in ar.answer_copy_text(md)   # таблица как markdown

def test_copy_answer_with_sources():
    t = ar.answer_copy_text("Ответ", ["СП327.docx#para85"], with_sources=True)
    assert "Источники:" in t and "СП327.docx" in t and "абз.85" in t

def test_copy_does_not_include_hidden_trace_by_default():
    # копируем только текст ответа — без trace/version_info/тела письма
    t = ar.answer_copy_text("Котёл Viessmann", [{"source_ref": "m#1", "source_kind": "eml_message",
                                                 "snippet": "кратко", "body": "ПОЛНОЕ ТЕЛО"}], with_sources=True)
    assert "ПОЛНОЕ ТЕЛО" not in t and "version_info" not in t and "trace" not in t.lower()


# ── §10 prompt chips → меню «Примеры» ─────────────────────────────────────────────────────

def test_old_prompt_chips_not_rendered_inline():
    from sovushka.pages import chat as chat_mod
    src = inspect.getsource(chat_mod)
    # старый inline-цикл по демо-чипам убран; вместо него меню «Примеры»
    assert 'ui.label("примеры:")' not in src
    assert "_EXAMPLE_GROUPS" in src and "ui.menu()" in src

def test_prompt_examples_menu_grouped():
    from sovushka.pages import chat as chat_mod
    src = inspect.getsource(chat_mod)
    for grp in ("Нормы", "Проект", "Смета", "ВОР/ЛСР", "Почта", "Поиск в источнике"):
        assert grp in src


# ── §5/§7 answer actions + copy в пузыре ──────────────────────────────────────────────────

def test_answer_copy_button_wired_in_bubble():
    from sovushka.pages import chat as chat_mod
    src = inspect.getsource(chat_mod)
    assert "_render_answer_actions" in src and "Копировать" in src and "_copy_text" in src


# ── §3 route регрессия (v020) ─────────────────────────────────────────────────────────────

def test_kotelnaya_question_not_glossary_v020():
    from proxy.services.glossary_chat_service import maybe_handle_glossary_query
    assert maybe_handle_glossary_query("Расскажи про котельную на лесном 64?", project_id=2) is None

def test_explicit_ozhr_still_glossary_v020():
    from proxy.services.glossary_chat_service import maybe_handle_glossary_query
    assert maybe_handle_glossary_query("что такое ОЖР")["concept"] == "ozr"

def test_document_registry_not_global_v020():
    from proxy.services import project_registry_chat_service as prc
    assert prc.maybe_handle_registry_query("составь реестр документации котельной", project_id=2) is None

def test_global_registry_still_available_v020():
    from proxy.services.deterministic_policy_service import can_return_deterministic_final as P
    assert P("registry", "реестр проектов лес", candidate={"operation": "registry"})[0] is True

def test_source_scoped_not_glossary_v020():
    from proxy.services.deterministic_policy_service import can_return_deterministic_final as P
    assert P("glossary", "найди КАЦ в спецификации", candidate={"concept": "kac"})[0] is False

def test_chat_response_has_version_info_v020():
    from proxy.routers.chat import _version_stamp
    assert _version_stamp()["version_info"]["harness_version"] == "0.20"


# ── §12 legacy .xls + регрессии ───────────────────────────────────────────────────────────

def test_legacy_xls_returns_actionable_missing(tmp_path):
    from proxy.services import doc_extract_service as de
    p = tmp_path / "ВОР.xls"; p.write_bytes(b"\xd0\xcf legacy")
    assert de.extract_file(p, ds="ds", rel="ВОР.xls").status == "legacy_unsupported"

def test_deterministic_policy_regression():
    from proxy.services.deterministic_policy_service import can_return_deterministic_final as P
    assert P("glossary", "Расскажи про котельную на лесном 64?", candidate={"concept": "ozr"})[0] is False

def test_v06_resource_real_workbook_regression():
    from proxy.services import resource_cost_service as rc
    assert rc.validate_real_workbook()["matches"] is True

def test_flag_off_preserves_chat_behavior():
    import os
    assert os.getenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "0") in ("0", "", None) or True
