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
    with pytest.raises(ValueError, match="RIM search scope is invalid"):
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
        if not family:
            return {
                "level": "family",
                "filters": {"family": "", "collection": "", "table": ""},
                "items": [{"key": "ГЭСНм", "norm_count": 10, "resource_count": 20}],
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
        return {
            "level": "table",
            "filters": {"family": family, "collection": collection, "table": ""},
            "items": [{"key": "10-01-001", "norm_count": 2, "resource_count": 8}],
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
    base = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСНм",
            "scope_reason": "Работа описывает монтаж оборудования связи.",
            "confidence": "high",
        }]},
        turn=3,
    )
    assert base["rows"][0]["level"] == "base_type_selected"
    assert base["rows"][0]["scope_selection"]["reason"].startswith("Работа")
    assert [item["key"] for item in base["rows"][0]["items"]] == ["10"]
    assert base["rows"][0]["catalog_retrieval_trace"]["rerank_status"] == "ok"
    assert base["rows"][0]["catalog_retrieval_trace"]["retrieval_policy"] == (
        "native_rrf_then_rerank_required"
    )
    preview = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСНм",
            "collection": "10",
        }]},
        turn=4,
    )
    assert preview["rows"][0]["level"] == "collection_previewed"
    catalog = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСНм",
            "collection": "10",
            "scope_reason": "Сборник относится к оборудованию связи.",
            "confidence": "high",
            "confirm_scope": True,
            "passport_evidence": (
                "Раздел 3. Аппаратура уплотнения межстанционных связей"
            ),
        }]},
        turn=5,
    )
    assert catalog["rows"][0]["level"] == "collection_selected"
    assert catalog["rows"][0]["items"] == []
    assert catalog["rows"][0]["collection_passport"]["title"] == "Оборудование связи"
    assert catalog["rows"][0]["scope_selection"]["reason"].startswith("Сборник")
    accepted = session.execute("search_norms_batch", search_args, turn=6)
    assert accepted["rows"][0]["ok"] is True
    assert search_calls[0][1]["base_types"] == ["ГЭСНм"]
    assert search_calls[0][1]["collections"] == []
    assert search_calls[-1][1]["base_types"] == ["ГЭСНм"]
    assert search_calls[-1][1]["collections"] == ["10"]


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
        "browse_norms_many",
        lambda queries, **kwargs: shortlist_calls.append((queries, kwargs)) or {
            query: {
                "cards": [{
                    "norm_code": "ГЭСНм10-01-001-01",
                    "title": "Оборудование связи",
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
                    "scope_reason": "Монтаж оборудования связи.",
                    "confidence": "high",
                },
                {
                    "work_id": "vor-002",
                    "family": "ГЭСНм",
                    "scope_reason": "Монтаж оборудования связи.",
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
        "browse_norms_many",
        lambda queries, **_kwargs: {
            query: {
                "cards": [
                    {
                        "norm_code": "ГЭСНм08-01-001-01",
                        "title": "Трансформатор",
                    },
                    {
                        "norm_code": "ГЭСНм20-01-001-01",
                        "title": "Пульт железнодорожной сигнализации",
                    },
                ],
                "retrieval_trace": {
                    "rerank_status": "ok",
                    "reranked": True,
                    "query_expansion": False,
                },
            }
            for query in queries
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
                "scope_reason": (
                    "Монтаж телекоммуникационного шкафа относится к "
                    "оборудованию связи"
                ),
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
        "official_identity_lexical_plus_norm_rrf_rerank"
    )


def test_rim_batch_search_explicitly_applies_one_confirmed_scope_to_other_rows(
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
                }
                for work_id, query in (
                    ("w1", "шкаф связи"),
                    ("w2", "организатор связи"),
                )
            ]
        },
        turn=4,
    )

    assert all(row["ok"] is True for row in result["rows"])
    assert session.selected_collections["w2"] == {("гэснм", "10")}
    assert session.selected_base_types["w2"]["гэснм"]["selection_owner"] == "model"
    assert session.selected_base_types["w2"]["гэснм"]["applied_by"] == (
        "search_norms_batch"
    )
    shared_trace = [
        row
        for row in session.catalog_trace
        if row.get("phase") == "catalog_scope_applied_by_batch"
    ]
    assert shared_trace == [{
        "phase": "catalog_scope_applied_by_batch",
        "turn": 4,
        "work_id": "w2",
        "level": "scope_selected",
        "filters": {"family": "ГЭСНм", "collection": "10", "table": ""},
        "selection_owner": "model",
        "applied_by": "search_norms_batch",
        "confirmed_by_work_id": "w1",
        "search_intent": "equipment_or_measure",
    }]


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
            "table": "08-02-001",
        }]},
        turn=5,
    )

    assert selected["rows"][0]["ok"] is True
    assert selected["rows"][0]["level"] == "table_selected"
    assert ("гэснм", "08", "08-02-001") in session.selected_tables["vor-001"]
