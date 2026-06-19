"""Ярус 2 — агент-роутер + реестр проектов. Без живого LLM (мок) и без сети."""
from __future__ import annotations

import pytest

from proxy.services import agent_router_service as ar
from proxy.services import project_registry_chat_service as reg


# ── реестр ──

@pytest.mark.parametrize("q,hit", [
    ("реестр проектов", True),
    ("какие у нас объекты", True),
    ("покажи общую карту папок", True),
    ("сколько кабеля на L5", False),
])
def test_registry_intent(q, hit):
    assert reg.is_registry_query(q) is hit


def test_registry_answer_shape(monkeypatch):
    monkeypatch.setattr("proxy.services.project_service.build_registry",
                        lambda: {"projects": [{"id": 3, "name": "Котельная", "stage": "РД",
                                               "code": "Ш-1", "address": "СПб", "folders": ["/x"],
                                               "datasets": 0, "has_les_md": True}], "count": 1})
    res = reg.registry_answer()
    assert res["operation"] == "registry" and "Котельная" in res["answer"] and "#3" in res["answer"]


def test_registry_empty(monkeypatch):
    monkeypatch.setattr("proxy.services.project_service.build_registry",
                        lambda: {"projects": [], "count": 0})
    assert reg.registry_answer()["operation"] == "registry_empty"


# ── агент-роутер ──

def test_agent_off_returns_none(monkeypatch):
    monkeypatch.delenv("LES_AGENT_LOOP", raising=False)
    assert ar.maybe_agent_route("реестр проектов") is None


def test_classify_parses_json(monkeypatch):
    monkeypatch.setattr(ar, "_classify", ar._classify)  # ensure real
    monkeypatch.setattr("proxy.services.les_md_service._llm_text", lambda *a, **k: '{"tool": "asbuilt"}')
    assert ar._classify("вытащи объём") == "asbuilt"


def test_classify_bare_name(monkeypatch):
    monkeypatch.setattr("proxy.services.les_md_service._llm_text", lambda *a, **k: "project_registry")
    assert ar._classify("какие объекты") == "project_registry"


def test_agent_routes_to_tool(monkeypatch):
    monkeypatch.setenv("LES_AGENT_LOOP", "true")
    monkeypatch.setattr(ar, "_classify", lambda q: "project_registry")
    monkeypatch.setattr("proxy.services.project_registry_chat_service.registry_answer",
                        lambda: {"answer": "реестр", "operation": "registry"})
    res = ar.maybe_agent_route("что у нас за объекты")
    assert res["agent_tool"] == "project_registry" and res["answer"] == "реестр"


def test_agent_none_tool_falls_back(monkeypatch):
    monkeypatch.setenv("LES_AGENT_LOOP", "true")
    monkeypatch.setattr(ar, "_classify", lambda q: "none")
    assert ar.maybe_agent_route("просто вопрос по нормативам") is None


def test_agent_handler_declines_falls_back(monkeypatch):
    monkeypatch.setenv("LES_AGENT_LOOP", "true")
    monkeypatch.setattr(ar, "_classify", lambda q: "asbuilt")
    monkeypatch.setattr("proxy.services.asbuilt_chat_service.maybe_handle_asbuilt_query",
                        lambda q, project_id=0: None)  # обработчик не смог
    assert ar.maybe_agent_route("вытащи объём без пути") is None
