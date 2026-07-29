"""v0.22 §1 / v0.286 — Scope hints: проектный запрос при scope=all не душит модель.

Сервис clarification сохранён для UI/ручного уточнения. В chat path это только warning в trace:
RAG/LLM должны получить вопрос и источники, особенно для запросов вроде "расскажи про котельную".
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

def test_scope_clarification_cannot_become_code_final_in_chat():
    from proxy.routers import chat as chat_mod
    src = inspect.getsource(chat_mod)
    assert "needs_project_scope" not in src
    assert "scope_clarification(" not in src
    assert 'reply = {"answer": _clar["answer"], "operation": "scope_clarification"}' not in src
    assert 'channel = "scope_clarification"' not in src

def test_scope_resolution_stays_in_trace_without_code_authored_clarification():
    from proxy.routers import chat as chat_mod
    src = inspect.getsource(chat_mod)
    assert 'query_route_payload["scope"] = _scope_snap' in src
    assert "scope_clarification" not in src


def test_empty_retrieval_no_generic_code_no_data_final():
    from proxy.services import chat_evidence_application_service
    src = inspect.getsource(chat_evidence_application_service._execute_chat_evidence_application)
    assert 'if not chunks and target_file_ref and target_file_ref.get("match_status") in {"matched", "ambiguous"}' in src
    assert "empty_retrieval_model_first_v1" in src


# ── регрессия ─────────────────────────────────────────────────────────────────────────────

def test_kotelnaya_selected_project_not_clarification():
    # при ВЫБРАННОМ проекте (scope!=all) clarification НЕ нужен — needs_project_scope не вызывается
    r = s.resolve_scope(scope={"scope_type": "project", "project_ids": [2]},
                        project_resolver=lambda pid: ["d3"])
    assert r["scope_type"] == "project" and r["resolved_dataset_ids"] == ["d3"]

def test_explicit_ozhr_still_available_as_tool_evidence():
    from proxy.services.glossary_chat_service import glossary_tool_result
    result = glossary_tool_result("что такое ОЖР")
    assert result["concept"] == "ozr" and "answer" not in result

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


def test_scope_selector_no_close_and_reopen_instruction():
    src = open("sovushka/pages/chat.py", encoding="utf-8").read()
    assert "закройте и откройте" not in src
    assert "Обновить список" in src

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
