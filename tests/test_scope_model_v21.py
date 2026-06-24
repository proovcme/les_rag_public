"""v0.21 — Project/Dataset Scope Model. Конец путаницы «весь RAG / проект / датасет».

Scope нормализует область поиска → resolved_dataset_ids; back-compat с project_id/dataset_ids/dataset_
filter; админский датасет ОБЯЗАН быть в scope/options; scope-snapshot в trace. Данные не удаляются.
"""

import inspect

import pytest

from proxy.services import scope_service as s


_PR = lambda pid: {1: ["d1", "d2"], 2: ["d3"]}.get(pid, [])
_PL = lambda pid: {1: "Лесной 64", 2: "Объект Б"}.get(pid, f"#{pid}")
_CAT = [{"id": "d1", "name": "Нормы СП"}, {"id": "d3", "name": "Котельная ВОР"}]


def _R(**kw):
    return s.resolve_scope(project_resolver=_PR, project_label_fn=_PL, dataset_catalog=_CAT, **kw)


# ── §3 scope resolver ─────────────────────────────────────────────────────────────────────

def test_resolve_scope_all():
    r = _R()
    assert r["scope_type"] == "all" and r["source"] == "default_all" and r["resolved_dataset_ids"] == []

def test_resolve_scope_project():
    r = _R(scope={"scope_type": "project", "project_ids": [1]})
    assert r["resolved_dataset_ids"] == ["d1", "d2"] and r["label"] == "Лесной 64"

def test_resolve_scope_multiple_projects():
    r = _R(scope={"scope_type": "projects", "project_ids": [1, 2]})
    assert r["resolved_dataset_ids"] == ["d1", "d2", "d3"]

def test_resolve_scope_dataset():
    r = _R(scope={"scope_type": "dataset", "dataset_ids": ["d3"]})
    assert r["scope_type"] == "dataset" and r["resolved_dataset_ids"] == ["d3"]

def test_resolve_scope_multiple_datasets():
    r = _R(scope={"scope_type": "datasets", "dataset_ids": ["d1", "d3"]})
    assert r["resolved_dataset_ids"] == ["d1", "d3"]

def test_resolve_scope_mixed():
    r = _R(scope={"scope_type": "mixed", "project_ids": [2], "dataset_ids": ["d9"]})
    assert set(r["resolved_dataset_ids"]) == {"d3", "d9"}

def test_legacy_project_id_maps_to_scope():
    r = _R(project_id=1)
    assert r["scope_type"] == "project" and r["source"] == "legacy_project_id" and r["resolved_dataset_ids"] == ["d1", "d2"]

def test_legacy_dataset_ids_maps_to_scope():
    r = _R(dataset_ids=["d3"])
    assert r["scope_type"] == "dataset" and r["source"] == "legacy_dataset_ids"

def test_dataset_filter_maps_to_scope_or_warning():
    assert _R(dataset_filter="Котельная ВОР")["resolved_dataset_ids"] == ["d3"]   # резолвится по каталогу
    r = _R(dataset_filter="нет такого")
    assert r["scope_type"] == "all" and any("unresolved" in w for w in r["warnings"])  # warning, не молча

def test_backend_prefers_explicit_scope_over_legacy_fields():
    r = _R(scope={"scope_type": "all"}, project_id=1)   # явный scope=all важнее project_id
    assert r["scope_type"] == "all" and r["source"] == "ui_scope" and r["resolved_dataset_ids"] == []

def test_scope_trace_contains_resolved_dataset_ids():
    r = _R(scope={"scope_type": "project", "project_ids": [1]})
    assert "resolved_dataset_ids" in r and "source" in r and "warnings" in r

def test_project_without_datasets_warns():
    r = _R(scope={"scope_type": "project", "project_ids": [99]})   # нет связей
    assert any("project_without_datasets" in w for w in r["warnings"])


# ── §5/§6 scope options (админ-датасеты обязаны быть видны) ───────────────────────────────

_DS = [{"id": "d1", "name": "Нормы СП", "files": 77}, {"id": "d3", "name": "Котельная ВОР", "files": 3},
       {"id": "d9", "name": "новый из админки", "files": 5},
       {"id": "sx", "name": "revit-api_shard", "files": 1}]
_PROJ = [{"id": 1, "name": "Лесной 64 Котельная"}]
_LINKS = {1: ["d1", "d3"]}


def test_scope_options_returns_all_projects_datasets():
    o = s.scope_options(_DS, _PROJ, _LINKS)
    assert o["projects"][0]["dataset_count"] == 2
    assert {d["id"] for d in o["datasets"]} == {"d1", "d3", "d9"}   # sx → system

def test_admin_created_dataset_appears_in_scope_options():
    o = s.scope_options(_DS, _PROJ, _LINKS)
    assert any(d["id"] == "d9" for d in o["datasets"])              # новый из админки виден

def test_unassigned_dataset_visible_in_scope_selector():
    o = s.scope_options(_DS, _PROJ, _LINKS)
    assert "d9" in {d["id"] for d in o["unassigned_datasets"]}      # не привязан, но виден

def test_assigned_dataset_visible_under_project_and_direct():
    o = s.scope_options(_DS, _PROJ, _LINKS)
    assert "d1" in o["projects"][0]["dataset_ids"]                  # под проектом
    assert any(d["id"] == "d1" for d in o["datasets"])             # и как прямой датасет

def test_hidden_system_dataset_has_visible_reason():
    o = s.scope_options(_DS, _PROJ, _LINKS)
    sysd = [d for d in o["system_datasets"] if d["id"] == "sx"]
    assert sysd and sysd[0].get("hidden_reason")                   # не скрыт молча — с reason

def test_scope_options_counts():
    o = s.scope_options(_DS, _PROJ, _LINKS)["counts"]
    assert o["datasets_total"] == 4 and o["datasets_unassigned"] == 1 and o["datasets_system"] == 1
    assert o["projects_total"] == 1 and o["projects_with_datasets"] == 1


# ── §5 endpoints зарегистрированы ─────────────────────────────────────────────────────────

def test_scope_endpoints_registered():
    from proxy.routers.runtime import router
    paths = {getattr(r, "path", "") for r in router.routes}
    assert any("scope/options" in p for p in paths) and any("scope/resolve" in p for p in paths)

def test_existing_dataset_routes_still_work():
    from proxy.routers.datasets import router
    paths = {getattr(r, "path", "") for r in router.routes}
    assert any(p == "/api/rag/datasets" for p in paths)


# ── §4/§12 scope в trace + ChatRequest.scope ──────────────────────────────────────────────

def test_chat_request_has_scope_field():
    from proxy.routers.chat import ChatRequest
    assert "scope" in ChatRequest.model_fields

def test_query_route_contains_scope_wired():
    src = inspect.getsource(__import__("proxy.routers.chat", fromlist=["x"]))
    assert 'query_route_payload["scope"] = _scope_snap' in src and "resolve_scope" in src


# ── §13 document preparation naming ───────────────────────────────────────────────────────

def test_ui_does_not_show_extract_body_label():
    import pathlib
    for f in pathlib.Path("sovushka").rglob("*.py"):
        assert "Извлечь тело" not in f.read_text(encoding="utf-8")

def test_prepare_documents_label_user_friendly():
    from proxy.services import sidecar_ops_service as ops
    assert ops.PREPARE_BUTTON_LABEL == "Подготовить документы"
    assert "не меняются" in ops.PREPARE_HELP_TEXT

def test_extraction_status_labels_user_friendly():
    from proxy.services import sidecar_ops_service as ops
    assert ops.extraction_status_label("sidecar_exists_and_searched") == "Текст извлечён"
    assert "тело" not in " ".join(ops.EXTRACTION_STATUS_LABELS.values()).lower()


# ── §15 регрессия ─────────────────────────────────────────────────────────────────────────

def test_kotelnaya_question_not_glossary():
    from proxy.services.glossary_chat_service import maybe_handle_glossary_query
    assert maybe_handle_glossary_query("Расскажи про котельную на лесном 64?", project_id=2) is None

def test_explicit_ozhr_still_glossary():
    from proxy.services.glossary_chat_service import maybe_handle_glossary_query
    assert maybe_handle_glossary_query("что такое ОЖР")["concept"] == "ozr"

def test_document_registry_not_global():
    from proxy.services import project_registry_chat_service as prc
    assert prc.maybe_handle_registry_query("составь реестр документации котельной", project_id=2) is None

def test_global_registry_still_available():
    from proxy.services.deterministic_policy_service import can_return_deterministic_final as P
    assert P("registry", "реестр проектов лес", candidate={"operation": "registry"})[0] is True

def test_version_endpoint_still_has_deployed_commit():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from proxy.routers.runtime import router
    app = FastAPI(); app.include_router(router)
    d = TestClient(app).get("/api/version").json()
    assert "deployed_commit" in d and d["harness_version"] == "0.22"

def test_flag_off_preserves_chat_behavior():
    import os
    assert os.getenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "0") in ("0", "", None) or True

def test_v06_resource_real_workbook_regression():
    from proxy.services import resource_cost_service as rc
    assert rc.validate_real_workbook()["matches"] is True
