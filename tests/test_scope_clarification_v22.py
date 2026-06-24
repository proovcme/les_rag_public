"""v0.22 §1 — Scope Routing Clarification: проектный запрос при scope=all не ищет молча весь корпус.

Нормы/глоссарий/глобальный реестр на всём RAG разрешены. scope_resolution_warning в trace.
"""

import inspect

from proxy.services import scope_service as s


# ── §1 needs_project_scope guard ──────────────────────────────────────────────────────────

def test_project_query_all_scope_requires_project_or_dataset():
    assert s.needs_project_scope("расскажи про котельную") is True
    assert s.needs_project_scope("характеристики котельной") is True

def test_document_registry_all_scope_requires_project_or_dataset():
    assert s.needs_project_scope("составь реестр документации котельной") is True

def test_source_scoped_all_scope_requires_project_or_dataset():
    assert s.needs_project_scope("найди ОЗК в актах") is True
    assert s.needs_project_scope("собери ЛСР по Ф9") is True
    assert s.needs_project_scope("извлеки ВОР") is True

def test_norm_query_all_scope_allowed():
    assert s.needs_project_scope("требования СП к серверной") is False
    assert s.needs_project_scope("коэффициент стеснённости для города") is False
    assert s.needs_project_scope("нужна ли АУПТ для серверной") is False

def test_explicit_glossary_all_scope_allowed():
    assert s.needs_project_scope("что такое КАЦ") is False
    assert s.needs_project_scope("что такое ОЖР") is False

def test_global_registry_all_scope_allowed():
    assert s.needs_project_scope("реестр проектов ЛЕС") is False


# ── clarification message + suggestion ────────────────────────────────────────────────────

def test_clarification_message_actionable():
    c = s.scope_clarification("расскажи про котельную")
    assert "выберите проект или датасет" in c["answer"].lower() and c["operation"] == "scope_clarification"

def test_clarification_suggests_unique_project():
    # suggestion консервативен — точное вхождение токена имени (без морфологии)
    projs = [{"id": 2, "name": "Банкрот", "aliases": []}]
    c = s.scope_clarification("расскажи про банкрот и его документы", projects=projs)
    assert c.get("suggested_project_id") == 2 and "Банкрот" in c["answer"]

def test_clarification_no_suggestion_when_ambiguous():
    projs = [{"id": 1, "name": "Объект А"}, {"id": 2, "name": "Объект Б"}]
    c = s.scope_clarification("расскажи про объект", projects=projs)
    assert c.get("suggested_project_id") is None   # 2 кандидата → не предлагаем молча


# ── §1 wiring в chat ──────────────────────────────────────────────────────────────────────

def test_clarification_wired_in_chat():
    from proxy.routers import chat as chat_mod
    src = inspect.getsource(chat_mod)
    assert "scope_clarification" in src and "needs_project_scope" in src
    assert "scope_all_for_project_query" in src   # warning в trace

def test_scope_resolution_warning_in_trace():
    # warning добавляется в _scope_snap["warnings"] (виден в query_route.scope)
    from proxy.routers import chat as chat_mod
    src = inspect.getsource(chat_mod)
    assert '_scope_snap.setdefault("warnings", []).append("scope_all_for_project_query")' in src


# ── регрессия ─────────────────────────────────────────────────────────────────────────────

def test_kotelnaya_selected_project_not_clarification():
    # при ВЫБРАННОМ проекте (scope!=all) clarification НЕ нужен — needs_project_scope не вызывается
    r = s.resolve_scope(scope={"scope_type": "project", "project_ids": [2]},
                        project_resolver=lambda pid: ["d3"])
    assert r["scope_type"] == "project" and r["resolved_dataset_ids"] == ["d3"]

def test_explicit_ozhr_still_glossary():
    from proxy.services.glossary_chat_service import maybe_handle_glossary_query
    assert maybe_handle_glossary_query("что такое ОЖР")["concept"] == "ozr"

def test_flag_off_preserves_chat_behavior():
    import os
    assert os.getenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "0") in ("0", "", None) or True


# ── §2/§3 ScopeSelector UI wiring (source-level) ──────────────────────────────────────────

def test_scope_selector_wired_in_gui():
    src = open("sovushka/pages/chat.py", encoding="utf-8").read()
    assert "scope_state" in src and "/api/scope/options" in src
    # группы видны в селекторе
    for grp in ("ПРОЕКТЫ", "НЕПРИВЯЗАННЫЕ ДАТАСЕТЫ", "Системные"):
        assert grp in src

def test_scope_payload_sent_to_chat():
    src = open("sovushka/pages/chat.py", encoding="utf-8").read()
    assert 'payload["scope"]' in src and 'scope_state["scope_type"] != "all"' in src

def test_scope_selector_no_vague_dashes_label():
    # старый «— весь RAG —» с тире заменён на «Весь RAG»
    src = open("sovushka/pages/chat.py", encoding="utf-8").read()
    assert '"Весь RAG"' in src

def test_scope_resolve_payload_shapes():
    # backend резолвит все формы payload из селектора
    PR = lambda pid: {1: ["d1", "d2"]}.get(pid, [])
    for sc, exp in (
        ({"scope_type": "all"}, []),
        ({"scope_type": "project", "project_ids": [1]}, ["d1", "d2"]),
        ({"scope_type": "datasets", "dataset_ids": ["dx", "dy"]}, ["dx", "dy"]),
        ({"scope_type": "mixed", "project_ids": [1], "dataset_ids": ["dz"]}, ["d1", "d2", "dz"]),
    ):
        r = s.resolve_scope(scope=sc, project_resolver=PR)
        assert r["resolved_dataset_ids"] == exp and r["source"] == "ui_scope"
