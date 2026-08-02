import json

import pytest

from proxy.smeta_core import document_workflow
from proxy.services.rim_agent_action_service import (
    allowed_model_actions,
    model_tool_specs,
    validate_model_action,
)


def _session(**updates):
    return {
        "session_id": "session-1",
        "phase": "mapping",
        "mapping_status": "mapping_selected",
        "pricing_status": "unpriced",
        "display_state": "awaiting_mapping_decisions",
        "head_revision_id": "revision-1",
        "pending_question_id": "",
        **updates,
    }


def test_model_sees_at_most_six_state_scoped_tools_and_never_user_locks():
    actions = allowed_model_actions(_session())
    assert len(actions) == 6
    assert {"search_norms_batch", "read_norms_batch", "submit_lsr_mapping"} <= set(actions)
    assert "lock_mapping" not in actions
    assert "finalize_estimate" not in actions
    specs = model_tool_specs(_session())
    assert [item["function"]["name"] for item in specs] == actions
    search_spec = next(
        item for item in specs if item["function"]["name"] == "search_norms_batch"
    )
    assert "rerank" not in search_spec["function"]["parameters"]["properties"]


def test_vor_phase_exposes_batch_norm_chain_and_draft_revision_tool():
    actions = allowed_model_actions(
        _session(
            phase="vor",
            mapping_status="not_started",
            display_state="awaiting_vor_approval",
        )
    )

    assert actions == [
        "draft_work_schedule",
        "browse_norm_catalog",
        "search_norms_batch",
        "read_norms_batch",
        "submit_lsr_mapping",
        "ask_user",
    ]


def test_server_stamps_session_and_rejects_model_authority_fields():
    result = validate_model_action(
        _session(),
        {
            "action": "search_norms_batch",
            "arguments": {
                "items": [
                    {
                        "work_id": "vor-001",
                        "query": "прокладка кабеля",
                        "search_intent": "key_operation",
                        "scope_mode": "scoped",
                        "base_types": ["ГЭСНм"],
                        "collections": ["10"],
                        "table_codes": ["10-01-001"],
                    }
                ]
            },
            "user_visible_intent": "Ищу кандидатов для выбранной работы.",
        },
    )
    assert result["session_id"] == "session-1"
    assert result["state"] == "awaiting_mapping_decisions"
    assert result["head_revision_id"] == "revision-1"
    with pytest.raises(ValueError, match="server-owned fields"):
        validate_model_action(
            _session(),
            {
                "session_id": "another-session",
                "state": "priced_final",
                "action": "search_norms_batch",
                "arguments": {},
                "user_visible_intent": "Подмена",
            },
        )


def test_pending_question_is_interpreted_in_place_not_restarted():
    session = _session(
        pending_question_id="question-1",
        display_state="awaiting_mapping_decisions",
    )
    assert allowed_model_actions(session) == ["interpret_pending_answer"]
    with pytest.raises(ValueError, match="not allowed"):
        validate_model_action(
            session,
            {
                "action": "search_norms_batch",
                "arguments": {},
                "user_visible_intent": "Новый поиск",
            },
        )


def test_early_question_contract_allows_project_fact_not_coefficient_choice():
    session = _session(
        phase="vor",
        mapping_status="not_started",
        display_state="awaiting_vor_approval",
    )
    result = validate_model_action(
        session,
        {
            "action": "ask_user",
            "arguments": {
                "question_kind": "physical_installation",
                "text": "Как оборудование закрепляется в шкафу?",
                "reason": "Способ монтажа меняет состав работ.",
                "work_ids": ["vor-001"],
                "options": ["на направляющих", "на полке", "пока неизвестно"],
            },
            "user_visible_intent": "Уточняю способ монтажа.",
        },
    )
    assert result["arguments"]["question_kind"] == "physical_installation"
    ask_spec = next(
        item
        for item in model_tool_specs(session)
        if item["function"]["name"] == "ask_user"
    )
    assert ask_spec["function"]["parameters"]["properties"]["question_kind"]["enum"] == [
        "physical_installation",
        "project_condition",
    ]

    with pytest.raises(ValueError, match="question kind is invalid"):
        validate_model_action(
            session,
            {
                "action": "ask_user",
                "arguments": {
                    "question_kind": "coefficient_approval",
                    "text": "Применять коэффициент?",
                    "reason": "Нужно выбрать техническую часть.",
                    "work_ids": ["vor-001"],
                    "options": ["да", "нет"],
                },
                "user_visible_intent": "Уточняю коэффициент.",
            },
        )
    region_question = validate_model_action(
        session,
        {
            "action": "ask_user",
            "arguments": {
                "question_kind": "project_condition",
                "text": "В каком регионе и периоде выполняются работы?",
                "reason": "Регион и период влияют на коэффициенты и цены.",
                "work_ids": ["vor-001"],
                "options": ["Москва, 2026", "Санкт-Петербург, 2026"],
            },
            "user_visible_intent": "Уточняю регион и период.",
        },
    )
    assert region_question["arguments"]["question_kind"] == "project_condition"


def test_pending_answer_normalizes_exact_string_boolean_from_local_model():
    result = validate_model_action(
        _session(
            pending_question_id="question-1",
            display_state="awaiting_mapping_decisions",
        ),
        {
            "action": "interpret_pending_answer",
            "arguments": {
                "answer": {"free_text": "Монтаж внутри шкафа."},
                "needs_clarification": "False",
            },
            "user_visible_intent": "Сохраняю уточнение.",
        },
    )

    assert result["arguments"]["needs_clarification"] is False


def test_model_can_request_but_not_create_final_lock():
    session = _session(
        phase="pricing",
        mapping_status="mapping_locked",
        pricing_status="priced_draft",
        display_state="priced_draft",
    )
    assert "request_final_lock" in allowed_model_actions(session)
    assert "create_user_lock" not in allowed_model_actions(session)


def test_action_arguments_are_schema_validated_before_execution():
    with pytest.raises(ValueError, match="arguments are invalid"):
        validate_model_action(
            _session(),
            {
                "action": "search_norms_batch",
                "arguments": {},
                "user_visible_intent": "Ищу нормы",
            },
        )


def test_vor_draft_rejects_mapping_decisions_and_missing_work_fields():
    session = _session(
        phase="intake",
        mapping_status="not_started",
        display_state="intake_classified",
    )
    with pytest.raises(ValueError, match="arguments are invalid"):
        validate_model_action(
            session,
            {
                "action": "draft_work_schedule",
                "arguments": {
                    "rows": [
                        {
                            "work_id": "vor-001",
                            "decision": "unbound",
                            "reason": "Норма не найдена",
                        }
                    ]
                },
                "user_visible_intent": "Готовлю ВОР.",
            },
        )


def test_rim_search_rejects_global_or_incomplete_model_scope():
    with pytest.raises(ValueError, match="arguments are invalid"):
        validate_model_action(
            _session(),
            {
                "action": "search_norms_batch",
                "arguments": {
                    "items": [
                        {
                            "work_id": "vor-001",
                            "query": "кабель",
                            "search_intent": "key_operation",
                            "scope_mode": "global",
                            "base_types": [],
                            "collections": [],
                            "table_codes": [],
                        }
                    ]
                },
                "user_visible_intent": "Ищу норму.",
            },
        )


def test_rim_search_uses_one_typed_catalog_scope_per_item():
    with pytest.raises(ValueError, match="one selected family"):
        validate_model_action(
            _session(),
            {
                "action": "search_norms_batch",
                "arguments": {
                    "items": [
                        {
                            "work_id": "vor-001",
                            "query": "монтаж и наладка",
                            "search_intent": "key_operation",
                            "scope_mode": "scoped",
                            "base_types": ["ГЭСНм", "ГЭСНп"],
                            "collections": ["10"],
                            "table_codes": ["10-01-001"],
                        }
                    ]
                },
                "user_visible_intent": "Проверяю два типа работ раздельно.",
            },
        )


def test_rim_family_selection_requires_model_reason_and_confidence():
    with pytest.raises(ValueError, match="RIM catalog scope is invalid"):
        validate_model_action(
            _session(),
            {
                "action": "browse_norm_catalog",
                "arguments": {
                    "items": [{"work_id": "vor-001", "family": "ГЭСНм"}],
                },
                "user_visible_intent": "Выбираю тип нормативной базы.",
            },
        )


def test_rim_collection_selection_requires_model_reason_and_confidence():
    with pytest.raises(ValueError, match="RIM catalog scope is invalid"):
        validate_model_action(
            _session(),
            {
                "action": "browse_norm_catalog",
                "arguments": {
                    "items": [{
                        "work_id": "vor-001",
                        "family": "ГЭСНм",
                        "collection": "10",
                    }],
                },
                "user_visible_intent": "Выбираю сборник.",
            },
        )


def test_rim_norm_session_requires_catalog_scope_before_batch_search(monkeypatch):
    search_calls = []

    def catalog(**kwargs):
        family = kwargs.get("family") or ""
        collection = kwargs.get("collection") or ""
        section = kwargs.get("section") or ""
        table = kwargs.get("table") or ""
        if not family:
            return {
                "level": "family",
                "filters": {"family": "", "collection": "", "table": ""},
                "items": [{
                    "key": "ГЭСНм",
                    "node_id": "catalog:family:ГЭСНм",
                    "parent_id": "catalog:root",
                    "node_type": "family",
                    "cipher": "ГЭСНм",
                    "purpose": "Монтаж оборудования",
                    "norm_count": 10,
                    "resource_count": 20,
                }],
            }
        if not collection:
            return {
                "level": "collection",
                "filters": {"family": family, "collection": "", "table": ""},
                "items": [
                    {"key": "10", "norm_count": 10, "resource_count": 20},
                    {"key": "11", "norm_count": 8, "resource_count": 16},
                ],
            }
        title = "Оборудование связи" if collection == "10" else "Приборы автоматики"
        if table:
            return {
                "level": "norm",
                "filters": {
                    "family": family,
                    "collection": collection,
                    "section": section,
                    "table": table,
                },
                "items": [{"norm_code": "ГЭСНм10-01-001-01"}],
            }
        if section:
            return {
                "level": "table",
                "filters": {
                    "family": family,
                    "collection": collection,
                    "section": section,
                    "table": "",
                },
                "items": [{
                    "key": "10-01-001",
                    "title": "Оборудование станции",
                    "norm_count": 2,
                    "resource_count": 8,
                }],
            }
        return {
            "level": "section",
            "filters": {
                "family": family,
                "collection": collection,
                "section": "",
                "table": "",
            },
            "items": [{
                "key": "10-01",
                "node_id": "catalog:section:ГЭСНм:10-01",
                "parent_id": "catalog:collection:ГЭСНм:10",
                "node_type": "section",
                "cipher": "10-01",
                "title": "Городская телефонная связь",
                "official_heading": "Отдел 1. Городская телефонная связь",
                "norm_count": 10,
                "resource_count": 20,
            }],
            "collection_passport": {
                "schema": "smeta_norm_collection_passport_v1",
                "family": family,
                "collection": collection,
                "title": title,
                "passport_role": "navigation_only",
                "representative_sections": [
                    "Отдел 1. Городская телефонная связь",
                    "Раздел 1. Станции телефонные",
                    "Раздел 2. Кроссы",
                    "Раздел 3. Аппаратура уплотнения межстанционных связей",
                ],
            },
        }

    monkeypatch.setattr(document_workflow, "browse_norm_catalog", catalog)
    monkeypatch.setattr(
        document_workflow,
        "rank_norm_catalog_collections",
        lambda query, **_kwargs: {
            "cards": [{
                "key": "10",
                "node_id": "catalog:collection:ГЭСНм:10",
                "parent_id": "catalog:family:ГЭСНм",
                "node_type": "collection",
                "cipher": "10",
                "collection": "10",
                "navigation_kind": "collection",
                "title": "Оборудование связи",
            }],
            "retrieval_trace": {
                "rerank_status": "ok",
                "reranked": True,
                "retrieval_policy": "typed_catalog_graph_then_rerank",
            },
        },
    )
    monkeypatch.setattr(
        document_workflow,
        "rank_norm_catalog_tables",
        lambda query, **_kwargs: {
            "cards": [{
                "key": "10-01-001",
                "node_id": "catalog:table:ГЭСНм:10-01-001",
                "parent_id": "catalog:section:ГЭСНм:10-01",
                "node_type": "table",
                "cipher": "10-01-001",
                "navigation_kind": "table",
                "title": "Оборудование станции",
            }],
            "retrieval_trace": {
                "rerank_status": "pool_too_small",
                "reranked": False,
                "retrieval_policy": "typed_catalog_graph_then_rerank",
            },
        },
    )
    def browse_many(queries, **kwargs):
        search_calls.append((queries, kwargs))
        catalog_navigation = not kwargs.get("collections")
        return {
            query: {
                "cards": (
                    [{
                        "norm_code": "ГЭСНм10-01-001-01",
                        "norm_name": "Оборудование связи",
                    }]
                    if catalog_navigation
                    else []
                ),
                "backend": "typed_sqlite_fts+smeta_norm_qdrant_hybrid+bge_rerank_rrf",
                "retrieval_trace": {"rerank_status": "ok"},
            }
            for query in queries
        }

    monkeypatch.setattr(document_workflow, "browse_norms_many", browse_many)
    session = document_workflow.SmetaNormToolSession(
        [{"work_id": "vor-001", "title": "Прокладка кабеля", "unit": "м", "quantity": 10}],
        candidate_limit=5,
        require_scoped_search=True,
    )
    search_args = {
        "items": [
            {
                "work_id": "vor-001",
                "query": "прокладка кабеля",
                "search_intent": "key_operation",
                "scope_mode": "scoped",
                "base_types": ["ГЭСНм"],
                "collections": ["10"],
                "table_codes": ["10-01-001"],
            }
        ]
    }
    rejected = session.execute("search_norms_batch", search_args, turn=1)
    assert rejected["rows"][0]["ok"] is False
    assert "base type selection" in rejected["rows"][0]["details"][0]
    assert search_calls == []

    families = session.execute(
        "browse_norm_catalog",
        {"items": [{"work_id": "vor-001"}]},
        turn=2,
    )
    assert families["rows"][0]["level"] == "family"
    question = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "current_node_id": "catalog:root",
            "decision": "ask",
            "evidence": [{
                "source_node_id": "catalog:family:ГЭСНм",
                "field": "purpose",
                "claim": "Для монтажа оборудования важен способ установки.",
            }],
            "rejected_nodes": [],
            "confidence": "low",
            "missing_facts": ["способ установки"],
            "question": {
                "question_kind": "physical_installation",
                "text": "Как прокладывается кабель?",
                "reason": "Способ прокладки влияет на применимость нормы.",
                "options": ["в лотке", "в трубе", "пока неизвестно"],
            },
        }]},
        turn=3,
    )
    assert question["requires_user_input"] is True
    assert question["pending_question"]["options"] == [
        "в лотке",
        "в трубе",
        "пока неизвестно",
    ]
    invented_jump = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "current_node_id": "catalog:root",
            "decision": "continue",
            "selected_node_id": "catalog:collection:ГЭСНм:10",
            "evidence": [],
            "rejected_nodes": [],
            "confidence": "high",
            "missing_facts": [],
        }]},
        turn=4,
    )
    assert invented_jump["rows"][0]["ok"] is False
    assert "not a child shown" in invented_jump["rows"][0]["error"]
    base = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "current_node_id": "catalog:root",
            "decision": "continue",
            "selected_node_id": "catalog:family:ГЭСНм",
            "evidence": [{
                "source_node_id": "catalog:family:ГЭСНм",
                "field": "purpose",
                "claim": "Вид норм охватывает монтаж оборудования.",
            }],
            "rejected_nodes": [],
            "confidence": "high",
            "missing_facts": [],
            "work_features": {
                "domain": "связь",
                "system": "кабельная система связи",
                "equipment": "кабель",
                "operation": "прокладка",
                "assembly_state": "component",
                "installation_context": "внутри здания",
                "unknowns": [],
            },
            "catalog_query": "кабель прокладка",
        }]},
        turn=5,
    )
    assert base["rows"][0]["ok"] is True
    assert base["rows"][0]["level"] == "collection"
    assert [item["key"] for item in base["rows"][0]["items"]] == ["10"]
    catalog = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "current_node_id": "catalog:family:ГЭСНм",
            "decision": "continue",
            "selected_node_id": "catalog:collection:ГЭСНм:10",
            "evidence": [{
                "source_node_id": "catalog:collection:ГЭСНм:10",
                "field": "title",
                "claim": "Сборник относится к оборудованию связи.",
            }],
            "rejected_nodes": [],
            "confidence": "high",
            "missing_facts": [],
        }]},
        turn=7,
    )
    assert catalog["rows"][0]["level"] == "section"
    assert [item["key"] for item in catalog["rows"][0]["items"]] == ["10-01"]
    broadened = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "current_node_id": "catalog:collection:ГЭСНм:10",
            "decision": "broaden",
            "evidence": [],
            "rejected_nodes": [],
            "confidence": "medium",
            "missing_facts": [],
        }]},
        turn=8,
    )
    assert broadened["rows"][0]["current_node_id"] == "catalog:family:ГЭСНм"
    assert [item["node_id"] for item in broadened["rows"][0]["items"]] == [
        "catalog:collection:ГЭСНм:10"
    ]
    catalog = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "current_node_id": "catalog:family:ГЭСНм",
            "decision": "continue",
            "selected_node_id": "catalog:collection:ГЭСНм:10",
            "evidence": [{
                "source_node_id": "catalog:collection:ГЭСНм:10",
                "field": "title",
                "claim": "Сборник относится к оборудованию связи.",
            }],
            "rejected_nodes": [],
            "confidence": "high",
            "missing_facts": [],
        }]},
        turn=9,
    )
    section = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "current_node_id": "catalog:collection:ГЭСНм:10",
            "decision": "continue",
            "selected_node_id": "catalog:section:ГЭСНм:10-01",
            "evidence": [{
                "source_node_id": "catalog:section:ГЭСНм:10-01",
                "field": "official_heading",
                "claim": "Раздел относится к городской телефонной связи.",
            }],
            "rejected_nodes": [],
            "confidence": "medium",
            "missing_facts": [],
            "catalog_query": "оборудование телефонной станции",
        }]},
        turn=10,
    )
    assert section["rows"][0]["level"] == "table"
    assert [item["key"] for item in section["rows"][0]["items"]] == [
        "10-01-001"
    ]
    table = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "current_node_id": "catalog:section:ГЭСНм:10-01",
            "decision": "continue",
            "selected_node_id": "catalog:table:ГЭСНм:10-01-001",
            "evidence": [{
                "source_node_id": "catalog:table:ГЭСНм:10-01-001",
                "field": "title",
                "claim": "Таблица относится к оборудованию станции.",
            }],
            "rejected_nodes": [],
            "confidence": "medium",
            "missing_facts": [],
        }]},
        turn=11,
    )
    assert table["rows"][0]["level"] == "norm_search"
    accepted = session.execute("search_norms_batch", search_args, turn=12)
    assert accepted["rows"][0]["ok"] is True
    assert search_calls[0][1]["base_types"] == ["ГЭСНм"]
    assert search_calls[0][1]["collections"] == ["10"]
    assert search_calls[0][1]["table_codes"] == ["10-01-001"]


def test_rim_phase_exposes_simple_route_tools_instead_of_conditional_union():
    tools = document_workflow._phase_norm_tools(
        "section_select",
        active_work_ids=["w1"],
        current_node_ids={"w1": "catalog:collection:ГЭСНм:10"},
        visible_child_node_ids={
            "w1": ["catalog:section:ГЭСНм:10:10-01"],
        },
        visible_evidence_fields=["title", "source_ref"],
    )
    names = [tool["function"]["name"] for tool in tools]

    assert names == [
        "continue_norm_catalog",
        "ask_norm_catalog_fact",
        "broaden_norm_catalog",
        "unbound_norm_catalog",
    ]
    ask_item = tools[1]["function"]["parameters"]["properties"]["items"]["items"]
    assert "question" in ask_item["required"]
    assert "selected_node_id" not in ask_item["properties"]
    assert "decision" not in ask_item["properties"]
    continue_item = tools[0]["function"]["parameters"]["properties"]["items"][
        "items"
    ]
    assert "selected_node_id" in continue_item["required"]
    assert "catalog_query" in continue_item["properties"]
    assert "catalog_query" in continue_item["required"]
    items_schema = tools[0]["function"]["parameters"]["properties"]["items"]
    assert items_schema["maxItems"] == 1
    assert continue_item["properties"]["work_id"]["enum"] == ["w1"]
    assert continue_item["properties"]["current_node_id"]["enum"] == [
        "catalog:collection:ГЭСНм:10",
    ]
    assert continue_item["properties"]["selected_node_id"]["enum"] == [
        "catalog:section:ГЭСНм:10:10-01",
    ]
    assert continue_item["properties"]["evidence"]["items"]["properties"][
        "source_node_id"
    ]["enum"] == ["catalog:section:ГЭСНм:10:10-01"]
    assert continue_item["properties"]["evidence"]["items"]["properties"][
        "field"
    ]["enum"] == ["title", "source_ref"]
    assert continue_item["properties"]["rejected_nodes"]["items"]["properties"][
        "node_id"
    ]["enum"] == ["catalog:section:ГЭСНм:10:10-01"]

    family_continue = document_workflow._phase_norm_tools("family_select")[0][
        "function"
    ]["parameters"]["properties"]["items"]["items"]
    assert {"work_features", "catalog_query"}.issubset(family_continue["required"])

    for phase in ("collection", "table_select"):
        route_continue = document_workflow._phase_norm_tools(phase)[0]["function"][
            "parameters"
        ]["properties"]["items"]["items"]
        assert "catalog_query" not in route_continue["required"]


def test_family_phase_does_not_block_on_known_or_unknown_assembly_state():
    prompt = document_workflow.smeta_phase_instruction("family_select")

    assert "означает `site_assembled`" in prompt
    assert "не блокируют выбор вида норм" in prompt
    assert "обязательно выбери один" in prompt
    assert "`ask_norm_catalog_fact`" in prompt


def test_collection_phase_requires_child_evidence_not_parent_passport():
    prompt = document_workflow.smeta_phase_instruction("collection")

    assert "выбранный дочерний сборник" in prompt
    assert "паспорт семейства является только контекстом пути" in prompt
    assert "не может быть evidence выбора сборника" in prompt


def test_collection_route_accepts_model_choice_with_five_rejected_siblings(
    monkeypatch,
):
    work_id = "vor-0001"
    family_id = "catalog:family:ГЭСНм"
    choices = [
        ("10", "Оборудование связи"),
        ("32", "Оборудование предприятий электронной промышленности"),
        ("40", "Дополнительное перемещение оборудования"),
        ("37", "Оборудование общего назначения"),
        ("08", "Электротехнические установки"),
        ("36", "Оборудование коммунального хозяйства"),
    ]
    children = [
        {
            "node_id": f"catalog:collection:ГЭСНм:{code}",
            "parent_id": family_id,
            "node_type": "collection",
            "cipher": code,
            "title": title,
            "source_ref": f"ФСНБ-2022 · ГЭСНм {code}",
        }
        for code, title in choices
    ]
    monkeypatch.setattr(
        document_workflow,
        "browse_norm_catalog",
        lambda **_kwargs: {
            "items": [],
            "level": "section",
        },
    )
    session = document_workflow.SmetaNormToolSession(
        [{
            "work_id": work_id,
            "title": "Монтаж телекоммуникационного шкафа",
            "unit": "шт.",
            "quantity": 2,
        }],
        candidate_limit=6,
        require_scoped_search=True,
    )
    session.family_catalog_seen.add(work_id)
    session.selected_base_types[work_id] = {
        "гэснм": {"family": "ГЭСНм", "confidence": "high"}
    }
    session.catalog_current_nodes[work_id] = family_id
    session.catalog_menus[work_id] = {family_id: children}
    session.catalog_node_registry[work_id] = {
        family_id: {
            "node_id": family_id,
            "parent_id": "catalog:root",
            "node_type": "family",
            "cipher": "ГЭСНм",
            "title": "Монтаж оборудования",
        },
        **{child["node_id"]: child for child in children},
    }
    selected_id = "catalog:collection:ГЭСНм:10"
    result = session.execute(
        "continue_norm_catalog",
        {
            "work_id": work_id,
            "current_node_id": family_id,
            "selected_node_id": selected_id,
            "evidence": json.dumps(
                [
                    {
                        "source_node_id": "catalog:collection:ГЭСНм:37",
                        "field": "title",
                        "claim": "Оборудование общего назначения",
                    },
                    {
                        "source_node_id": selected_id,
                        "field": "title",
                        "claim": "Оборудование связи",
                    },
                ],
                ensure_ascii=False,
            ),
            "rejected_nodes": json.dumps([
                    {
                        "node_id": child["node_id"],
                        "reason": f"{child['title']} не соответствует СКС",
                    }
                    for child in children
                    if child["node_id"] != selected_id
                ], ensure_ascii=False),
            "confidence": "high",
            "missing_facts": "[]",
        },
        turn=2,
    )

    assert result["rows"][0]["ok"] is True
    assert result["rows"][0]["route_decision"]["selected_node_id"] == selected_id
    assert result["rows"][0]["route_decision"]["evidence"][0][
        "source_node_id"
    ] == selected_id
    assert session.selected_collections[work_id] == {("гэснм", "10")}


def test_scoped_agent_prepares_root_without_spending_a_model_turn():
    checkpoints = []
    calls = 0

    def inspect_first_model_call(messages, tools):
        nonlocal calls
        calls += 1
        working_memory = next(
            json.loads(message["content"])
            for message in reversed(messages)
            if message.get("role") == "user"
            and "smeta_norm_agent_working_memory_v1"
            in str(message.get("content") or "")
        )
        assert working_memory["active_phase"] == "family_select"
        assert working_memory["work_evidence_status"][0][
            "catalog_current_node_id"
        ] == "catalog:root"
        assert len(
            working_memory["work_evidence_status"][0][
                "catalog_visible_children"
            ]
        ) == 5
        assert "authoritative_budget_remaining" not in working_memory
        assert all(message.get("role") != "tool" for message in messages)
        assert [tool["function"]["name"] for tool in tools] == [
            "continue_norm_catalog",
            "ask_norm_catalog_fact",
            "broaden_norm_catalog",
            "unbound_norm_catalog",
        ]
        raise RuntimeError("first model call inspected")

    with pytest.raises(RuntimeError, match="first model call inspected"):
        document_workflow._run_batch_norm_agent(
            [{
                "work_id": "vor-001",
                "title": "Монтаж шкафа связи",
                "unit": "шт",
                "quantity": 1,
            }],
            inspect_first_model_call,
            candidate_limit=4,
            max_turns=1,
            checkpoint=checkpoints.append,
            require_scoped_search=True,
        )

    assert calls == 1
    assert checkpoints[-1]["catalog_trace"][0]["level"] == "family"


def test_rim_catalog_menu_is_not_duplicated_for_identical_work_scopes(monkeypatch):
    shortlist_calls = []

    def catalog(**kwargs):
        if not kwargs.get("family"):
            return {
                "level": "family",
                "filters": {"family": "", "collection": "", "table": ""},
                "items": [
                    {
                        "key": "ГЭСНм",
                        "norm_count": 17780,
                        "resource_count": 90000,
                        "purpose": "Монтаж оборудования.",
                    }
                ],
            }
        return {
            "level": "collection",
            "filters": {"family": "ГЭСНм", "collection": "", "table": ""},
            "items": [
                {
                    "key": "10",
                    "norm_count": 1467,
                    "resource_count": 10986,
                    "source_example": "Сборник 10. Оборудование связи",
                }
            ],
        }

    monkeypatch.setattr(document_workflow, "browse_norm_catalog", catalog)
    monkeypatch.setattr(
        document_workflow,
        "rank_norm_catalog_collections",
        lambda query, **kwargs: shortlist_calls.append((query, kwargs)) or {
            "cards": [{
                "key": "10",
                "collection": "10",
                "navigation_kind": "collection",
                "title": "Оборудование связи",
            }],
            "retrieval_trace": {
                "rerank_status": "ok",
                "reranked": True,
                "retrieval_policy": "typed_catalog_graph_then_rerank",
            },
        },
    )
    session = document_workflow.SmetaNormToolSession(
        [
            {"work_id": "vor-001", "title": "Монтаж шкафа", "unit": "шт.", "quantity": 2},
            {
                "work_id": "vor-002",
                "title": "Монтаж организатора",
                "unit": "шт.",
                "quantity": 8,
            },
        ],
        candidate_limit=5,
        require_scoped_search=True,
    )

    families = session.execute(
        "browse_norm_catalog",
        {
            "items": [
                {"work_id": "vor-001"},
                {"work_id": "vor-002"},
            ]
        },
        turn=1,
    )
    assert families["rows"][0]["items"][0]["purpose"] == "Монтаж оборудования."
    assert families["rows"][1]["shared_items_with_work_id"] == "vor-001"

    result = session.execute(
        "browse_norm_catalog",
        {
            "items": [
                {
                    "work_id": "vor-001",
                        "family": "ГЭСНм",
                        "work_features": {
                            "domain": "связь", "system": "СКС",
                            "equipment": "шкаф", "operation": "монтаж",
                            "assembly_state": "unknown",
                            "installation_context": "в помещении",
                            "unknowns": ["комплектность"],
                        },
                        "scope_reason": "Монтаж оборудования связи.",
                        "catalog_query": "оборудование связи",
                        "confidence": "high",
                },
                {
                    "work_id": "vor-002",
                        "family": "ГЭСНм",
                        "work_features": {
                            "domain": "связь", "system": "СКС",
                            "equipment": "организатор", "operation": "монтаж",
                            "assembly_state": "component",
                            "installation_context": "в шкафу",
                            "unknowns": [],
                        },
                        "scope_reason": "Монтаж оборудования связи.",
                        "catalog_query": "оборудование связи",
                        "confidence": "high",
                },
            ]
        },
        turn=2,
    )

    assert result["rows"][0]["level"] == "base_type_selected"
    assert result["rows"][0]["items"][0]["key"] == "10"
    assert result["rows"][1]["items"] == []
    assert result["rows"][1]["shared_items_with_work_id"] == "vor-001"
    assert len(shortlist_calls) == 1


def test_rim_collection_compass_keeps_official_title_match_when_norm_hits_miss_it(
    monkeypatch,
):
    def catalog(**kwargs):
        if not kwargs.get("family"):
            return {
                "level": "family",
                "filters": {"family": "", "collection": "", "table": ""},
                "items": [{"key": "ГЭСНм", "purpose": "Монтаж оборудования"}],
            }
        return {
            "level": "collection",
            "filters": {"family": "ГЭСНм", "collection": "", "table": ""},
            "items": [
                {
                    "key": "08",
                    "title": "Электротехнические установки",
                    "purpose": "Электротехнические установки",
                },
                {
                    "key": "10",
                    "title": "Оборудование связи",
                    "purpose": "Официальный сборник ГЭСНм 10: Оборудование связи",
                    "typical_scope": ["Оборудование связи"],
                },
                {
                    "key": "20",
                    "title": "Оборудование сигнализации на железнодорожном транспорте",
                    "purpose": "Железнодорожная сигнализация",
                },
            ],
        }

    monkeypatch.setattr(document_workflow, "browse_norm_catalog", catalog)
    monkeypatch.setattr(
        document_workflow,
        "rank_norm_catalog_collections",
        lambda _query, **_kwargs: {
            "cards": [
                {
                    "key": "10",
                    "collection": "10",
                    "navigation_kind": "collection",
                    "title": "Оборудование связи",
                },
                {
                    "key": "08",
                    "collection": "08",
                    "navigation_kind": "collection",
                    "title": "Электротехнические установки",
                },
                {
                    "key": "20",
                    "collection": "20",
                    "navigation_kind": "collection",
                    "title": "Железнодорожная сигнализация",
                },
            ],
            "retrieval_trace": {
                "rerank_status": "ok",
                "reranked": True,
                "retrieval_policy": "typed_catalog_graph_then_rerank",
            },
        },
    )
    session = document_workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Монтаж шкафа связи", "unit": "шт", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    session.execute(
        "browse_norm_catalog",
        {"items": [{"work_id": "w1"}]},
        turn=1,
    )

    result = session.execute(
        "browse_norm_catalog",
        {
            "items": [{
                "work_id": "w1",
                "family": "ГЭСНм",
                    "work_features": {
                        "domain": "связь", "system": "СКС",
                        "equipment": "телекоммуникационный шкаф",
                        "operation": "монтаж",
                        "assembly_state": "unknown",
                        "installation_context": "в помещении",
                        "unknowns": ["комплектность"],
                    },
                    "scope_reason": (
                        "Монтаж телекоммуникационного шкафа относится к "
                        "оборудованию связи"
                    ),
                    "catalog_query": "оборудование связи",
                    "confidence": "high",
            }]
        },
        turn=2,
    )

    row = result["rows"][0]
    keys = [item["key"] for item in row["items"]]
    assert keys[0] == "10"
    assert set(keys[:3]) == {"08", "10", "20"}
    assert row["items"][0]["catalog_compass_score"] > 0
    assert row["catalog_retrieval_trace"]["collection_compass_policy"] == (
        "official_catalog_graph_plus_rerank"
    )


def test_rim_batch_search_never_copies_one_rows_catalog_route_to_another(
    monkeypatch,
):
    monkeypatch.setattr(
        document_workflow,
        "browse_norms_many",
        lambda queries, **kwargs: {
            query: {
                "cards": [],
                "backend": (
                    "typed_sqlite_fts+smeta_norm_qdrant_hybrid+bge_rerank_rrf"
                ),
                "retrieval_trace": {
                    "rerank_status": "ok",
                    "reranked": True,
                },
            }
            for query in queries
        },
    )
    session = document_workflow.SmetaNormToolSession(
        [
            {"work_id": "w1", "title": "Монтаж шкафа", "unit": "шт", "quantity": 1},
            {"work_id": "w2", "title": "Монтаж организатора", "unit": "шт", "quantity": 2},
        ],
        candidate_limit=5,
        require_scoped_search=True,
    )
    session.selected_base_types["w1"]["гэснм"] = {
        "family": "ГЭСНм",
        "reason": "Оборудование связи",
        "confidence": "high",
    }
    session.selected_collections["w1"].add(("гэснм", "10"))
    session.selected_sections["w1"].add(("гэснм", "10", "10-01"))
    session.selected_tables["w1"].add(("гэснм", "10", "10-01-001"))

    result = session.execute(
        "search_norms_batch",
        {
            "items": [
                {
                    "work_id": work_id,
                    "query": query,
                    "search_intent": "equipment_or_measure",
                    "scope_mode": "scoped",
                    "base_types": ["ГЭСНм"],
                    "collections": ["10"],
                    "table_codes": ["10-01-001"],
                }
                for work_id, query in (
                    ("w1", "шкаф связи"),
                    ("w2", "организатор связи"),
                )
            ]
        },
        turn=4,
    )

    by_work = {row["work_id"]: row for row in result["rows"]}
    assert by_work["w1"]["ok"] is True
    assert by_work["w2"]["ok"] is False
    assert "explicit model-owned base type selection" in by_work["w2"]["details"][0]
    assert session.selected_collections["w2"] == set()
    assert session.selected_base_types["w2"] == {}


def test_rim_rejects_more_than_two_full_cards_in_one_model_turn():
    session = document_workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Монтаж шкафа", "unit": "шт", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )

    result = session.execute(
        "read_norms_batch",
        {
            "items": [
                {"work_id": "w1", "norm_code": code}
                for code in (
                    "ГЭСНм10-01-001-01",
                    "ГЭСНм10-01-001-02",
                    "ГЭСНм10-01-001-03",
                )
            ]
        },
        turn=1,
    )

    assert result["ok"] is False
    assert "limited to two full typed cards" in result["error"]
    assert session.evidence_usage["read_calls"] == 0
    assert session.evidence_usage["opened_cards"] == 0


def test_agent_context_compacts_search_but_keeps_latest_typed_read():
    conversation = [
        {
            "role": "tool",
            "name": "search_norms_batch",
            "content": json.dumps({
                "ok": True,
                "rows": [{
                    "work_id": "w1",
                    "ok": True,
                    "candidates": [{
                        "norm_code": "ГЭСНм10-01-001-01",
                        "title": "Кандидат с длинной навигационной карточкой",
                        "measure_unit": "шт.",
                        "resources": [{"name": "не должен остаться в shortlist"}],
                    }],
                }],
            }, ensure_ascii=False),
        },
        {
            "role": "tool",
            "name": "read_norms_batch",
            "content": json.dumps({
                "ok": True,
                "rows": [{
                    "work_id": "w1",
                    "ok": True,
                    "norms": [{
                        "norm_code": "ГЭСНм10-01-001-01",
                        "title": "Полная typed-карточка",
                        "resources": [{"name": "Сохраняемый ресурс"}],
                    }],
                }],
            }, ensure_ascii=False),
        },
    ]

    document_workflow._prune_stale_tool_evidence(conversation)

    compact_search = json.loads(conversation[0]["content"])
    assert conversation[0]["_les_compressed"] is True
    assert compact_search["rows"][0]["candidates"] == [{
        "norm_code": "ГЭСНм10-01-001-01",
        "title": "Кандидат с длинной навигационной карточкой",
        "measure_unit": "шт.",
        "candidate_rank": None,
    }]
    assert "resources" not in compact_search["rows"][0]["candidates"][0]
    assert conversation[1].get("_les_compressed") is None
    assert "Сохраняемый ресурс" in conversation[1]["content"]


def test_model_request_shape_profiles_cache_prefix_and_working_memory():
    working_memory = {
        "working_memory_contract": "smeta_norm_agent_working_memory_v1",
        "work_evidence_status": [
            {"catalog_visible_children": [{"node_id": "a"}, {"node_id": "b"}]}
        ],
    }
    conversation = [
        {"role": "system", "content": "stable system"},
        {"role": "user", "content": "five rows"},
        {
            "role": "user",
            "content": json.dumps(working_memory, ensure_ascii=False),
        },
    ]
    tools = [{"type": "function", "function": {"name": "navigate"}}]

    profile = document_workflow._model_request_shape(conversation, tools)

    assert profile["visible_children_count"] == 2
    assert profile["working_memory_bytes"] == len(
        conversation[-1]["content"].encode("utf-8")
    )
    assert profile["prompt_bytes"] > profile["working_memory_bytes"]
    assert len(profile["system_sha256"]) == 64
    assert len(profile["tool_schema_sha256"]) == 64
    assert len(profile["stable_prefix_sha256"]) == 64


def test_one_row_mapping_chunk_serializes_focus_before_later_rows():
    session = document_workflow.SmetaNormToolSession(
        [
            {"work_id": "w1", "title": "Первая работа", "unit": "шт", "quantity": 1},
            {"work_id": "w2", "title": "Вторая работа", "unit": "шт", "quantity": 1},
        ],
        candidate_limit=4,
    )
    session.opened["w1"]["ГЭСНм10-01-001-01"] = {
        "norm_code": "ГЭСНм10-01-001-01",
    }

    blocked = document_workflow._focus_serialization_guard(
        session,
        {"items": [{"work_id": "w2", "norm_code": "ГЭСНм10-01-002-01"}]},
        mapping_chunk=1,
    )
    allowed_focus = document_workflow._focus_serialization_guard(
        session,
        {"items": [{"work_id": "w1", "norm_code": "ГЭСНм10-01-001-01"}]},
        mapping_chunk=1,
    )
    allowed_batch = document_workflow._focus_serialization_guard(
        session,
        {"items": [{"work_id": "w2", "norm_code": "ГЭСНм10-01-002-01"}]},
        mapping_chunk=8,
    )

    assert blocked == {
        "ok": False,
        "error": (
            "finish and serialize the current focus work before "
            "using evidence tools for later rows"
        ),
        "focus_work_id": "w1",
        "deferred_work_ids": ["w2"],
        "next_action": (
            "end the tool loop now; LES will request your own "
            "structured mapping for the focus work_id"
        ),
    }
    assert allowed_focus is None
    assert allowed_batch is None


def test_unbound_accepts_same_query_across_two_confirmed_scopes():
    session = document_workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Монтаж шкафа", "unit": "шт", "quantity": 1}],
        candidate_limit=4,
    )
    session.query_trace.extend([
        {
            "work_id": "w1",
            "queries": ["монтаж шкафа"],
            "filters": {"base_types": ["ГЭСНм"], "collections": ["10"]},
        },
        {
            "work_id": "w1",
            "queries": ["монтаж шкафа"],
            "filters": {"base_types": ["ГЭСНм"], "collections": ["08"]},
        },
    ])
    session.opened["w1"]["ГЭСНм10-01-001-01"] = {
        "norm_code": "ГЭСНм10-01-001-01",
    }

    errors = session._unbound_evidence_errors(
        "w1",
        reason="Открытые карточки относятся к другим объектам монтажа",
        evidence={
            "queries_used": ["монтаж шкафа"],
            "opened_norm_codes": ["ГЭСНм10-01-001-01"],
            "rejection_reasons": ["Чужой объект монтажа"],
            "coverage_checked": "Соседняя работа шкаф не покрывает",
        },
    )

    assert errors == []


def test_rim_requires_read_after_candidates_instead_of_reopening_catalog():
    session = document_workflow.SmetaNormToolSession(
        [
            {"work_id": "w1", "title": "Монтаж шкафа", "unit": "шт", "quantity": 1},
            {"work_id": "w2", "title": "Монтаж панели", "unit": "шт", "quantity": 1},
        ],
        candidate_limit=4,
        require_scoped_search=True,
    )
    for work_id in ("w1", "w2"):
        session.candidates[work_id]["ГЭСНм10-01-001-01"] = {
            "norm_code": "ГЭСНм10-01-001-01",
            "title": "Кандидат",
        }
    session.opened["w1"]["ГЭСНм10-01-001-01"] = {
        "norm_code": "ГЭСНм10-01-001-01",
        "title": "Открытая карточка первой строки",
    }

    result = session.execute(
        "browse_norm_catalog",
        {
            "items": [{
                "work_id": "w1",
                "family": "ГЭСНм",
                "collection": "08",
            }]
        },
        turn=2,
    )

    assert result["ok"] is False
    row = result["rows"][0]
    assert row["ok"] is False
    assert row["next_action"] == "read_norms_batch"
    assert "work_ids: w2" in row["details"][0]


def test_rim_rejects_inconsistent_table_before_retrieval(monkeypatch):
    def catalog(**kwargs):
        family = kwargs.get("family") or ""
        collection = kwargs.get("collection") or ""
        table = kwargs.get("table") or ""
        if not family:
            return {
                "level": "family",
                "filters": {},
                "items": [{"key": "ГЭСН", "norm_count": 100, "resource_count": 200}],
            }
        if not collection:
            return {
                "level": "collection",
                "filters": {"family": family, "collection": "", "table": ""},
                "items": [
                    {"key": "34", "norm_count": 20, "resource_count": 40},
                    {"key": "33", "norm_count": 10, "resource_count": 20},
                ],
            }
        if not table:
            title = "Сооружения связи" if collection == "34" else "Линии связи"
            return {
                "level": "table",
                "filters": {"family": family, "collection": collection, "table": ""},
                "items": [{"key": "34-01-001", "norm_count": 4, "resource_count": 10}],
                "collection_passport": {"title": title},
            }
        return {"level": "norm", "filters": {}, "items": []}

    monkeypatch.setattr(document_workflow, "browse_norm_catalog", catalog)
    monkeypatch.setattr(
        document_workflow,
        "browse_norms_many",
        lambda queries, **kwargs: {
            query: {
                "cards": [{
                    "norm_code": "ГЭСН34-01-001-01",
                    "title": "Сооружения связи",
                }],
                "retrieval_trace": {
                    "rerank_status": "ok",
                    "reranked": True,
                },
            }
            for query in queries
        },
    )
    session = document_workflow.SmetaNormToolSession(
        [{"work_id": "vor-001", "title": "Работа", "unit": "шт", "quantity": 1}],
        candidate_limit=5,
        require_scoped_search=True,
    )
    session.selected_base_types["vor-001"]["гэсн"] = {
        "family": "ГЭСН",
        "reason": "Строительная работа",
        "confidence": "medium",
    }
    session.selected_collections["vor-001"].add(("гэсн", "34"))
    session.execute(
        "browse_norm_catalog", {"items": [{"work_id": "vor-001"}]}, turn=1,
    )
    session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСН",
            "scope_reason": "Модель считает работу строительной.",
            "confidence": "medium",
        }]},
        turn=2,
    )
    session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСН",
            "collection": "34",
            "scope_reason": "Модель считает сборник релевантным сооружениям связи.",
            "confidence": "medium",
        }]},
        turn=3,
    )
    session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСН",
            "collection": "34",
            "scope_reason": "Модель считает сборник релевантным сооружениям связи.",
            "confidence": "medium",
            "confirm_scope": True,
            "passport_evidence": "Сооружения связи",
        }]},
        turn=4,
    )

    result = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСН",
            "collection": "34",
            "table": "08-02-001",
        }]},
        turn=5,
    )

    assert result["rows"][0]["ok"] is False
    assert result["rows"][0]["error"] == "table does not belong to the selected collection"
    assert "encodes collection '08'" in result["rows"][0]["details"][0]


def test_rim_accepts_table_only_inside_selected_typed_scope(monkeypatch):
    def catalog(**kwargs):
        family = kwargs.get("family") or ""
        collection = kwargs.get("collection") or ""
        table = kwargs.get("table") or ""
        if not family:
            return {"level": "family", "filters": {}, "items": [{"key": "ГЭСНм"}]}
        if not collection:
            return {
                "level": "collection",
                "filters": {},
                "items": [{"key": "08"}, {"key": "10"}],
            }
        if not table:
            title = (
                "Электротехнические установки"
                if collection == "08"
                else "Оборудование связи"
            )
            return {
                "level": "table",
                "filters": {},
                "items": [{"key": f"{collection}-02-001"}],
                "collection_passport": {"title": title},
            }
        return {
            "level": "norm",
            "filters": {"family": family, "collection": collection, "table": table},
            "items": [{"norm_code": "ГЭСНм08-02-001-01"}],
        }

    monkeypatch.setattr(document_workflow, "browse_norm_catalog", catalog)
    monkeypatch.setattr(
        document_workflow,
        "browse_norms_many",
        lambda queries, **kwargs: {
            query: {
                "cards": [{
                    "norm_code": "ГЭСНм08-02-001-01",
                    "title": "Электротехнические установки",
                }],
                "retrieval_trace": {
                    "rerank_status": "ok",
                    "reranked": True,
                },
            }
            for query in queries
        },
    )
    session = document_workflow.SmetaNormToolSession(
        [{"work_id": "vor-001", "title": "Монтаж блока", "unit": "шт", "quantity": 1}],
        candidate_limit=5,
        require_scoped_search=True,
    )
    session.selected_base_types["vor-001"]["гэснм"] = {
        "family": "ГЭСНм",
        "reason": "Монтаж оборудования",
        "confidence": "high",
    }
    session.selected_collections["vor-001"].add(("гэснм", "08"))
    session.selected_sections["vor-001"].add(("гэснм", "08", "08-02"))
    session.execute("browse_norm_catalog", {"items": [{"work_id": "vor-001"}]}, turn=1)
    session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСНм",
            "scope_reason": "Монтаж оборудования.",
            "confidence": "high",
        }]},
        turn=2,
    )
    session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСНм",
            "collection": "08",
            "scope_reason": "Работа относится к электротехнической установке.",
            "confidence": "high",
        }]},
        turn=3,
    )
    session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСНм",
            "collection": "08",
            "scope_reason": "Работа относится к электротехнической установке.",
            "confidence": "high",
            "confirm_scope": True,
            "passport_evidence": "Электротехнические установки",
        }]},
        turn=4,
    )
    selected = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСНм",
            "collection": "08",
            "section": "08-02",
            "table": "08-02-001",
        }]},
        turn=5,
    )

    assert selected["rows"][0]["ok"] is True
    assert selected["rows"][0]["level"] == "table_selected"
    assert ("гэснм", "08", "08-02-001") in session.selected_tables["vor-001"]
