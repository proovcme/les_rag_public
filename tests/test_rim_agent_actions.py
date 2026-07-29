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
                "items": [{"key": "10", "norm_count": 10, "resource_count": 20}],
            }
        return {
            "level": "table",
            "filters": {"family": family, "collection": collection, "table": ""},
            "items": [{"key": "10-01-001", "norm_count": 2, "resource_count": 8}],
            "collection_passport": {
                "schema": "smeta_norm_collection_passport_v1",
                "family": family,
                "collection": collection,
                "title": "Оборудование связи",
                "passport_role": "navigation_only",
            },
        }

    monkeypatch.setattr(document_workflow, "browse_norm_catalog", catalog)
    monkeypatch.setattr(
        document_workflow,
        "browse_norms_many",
        lambda queries, **kwargs: search_calls.append((queries, kwargs)) or {
            query: {"cards": [], "backend": "typed_sqlite_fts"}
            for query in queries
        },
    )
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
    catalog = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСНм",
            "collection": "10",
            "scope_reason": "Сборник относится к оборудованию связи.",
            "confidence": "high",
        }]},
        turn=4,
    )
    assert catalog["rows"][0]["level"] == "collection_selected"
    assert catalog["rows"][0]["items"] == []
    assert catalog["rows"][0]["collection_passport"]["title"] == "Оборудование связи"
    assert catalog["rows"][0]["scope_selection"]["reason"].startswith("Сборник")
    accepted = session.execute("search_norms_batch", search_args, turn=5)
    assert accepted["rows"][0]["ok"] is True
    assert search_calls[0][1]["base_types"] == ["ГЭСНм"]
    assert search_calls[0][1]["collections"] == ["10"]


def test_rim_catalog_menu_is_not_duplicated_for_identical_work_scopes(monkeypatch):
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
                "items": [{"key": "34", "norm_count": 20, "resource_count": 40}],
            }
        if not table:
            return {
                "level": "table",
                "filters": {"family": family, "collection": collection, "table": ""},
                "items": [{"key": "34-01-001", "norm_count": 4, "resource_count": 10}],
            }
        return {"level": "norm", "filters": {}, "items": []}

    monkeypatch.setattr(document_workflow, "browse_norm_catalog", catalog)
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

    result = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСН",
            "collection": "34",
            "table": "08-02-001",
        }]},
        turn=4,
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
            return {"level": "collection", "filters": {}, "items": [{"key": "08"}]}
        if not table:
            return {"level": "table", "filters": {}, "items": [{"key": "08-02-001"}]}
        return {
            "level": "norm",
            "filters": {"family": family, "collection": collection, "table": table},
            "items": [{"norm_code": "ГЭСНм08-02-001-01"}],
        }

    monkeypatch.setattr(document_workflow, "browse_norm_catalog", catalog)
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
    selected = session.execute(
        "browse_norm_catalog",
        {"items": [{
            "work_id": "vor-001",
            "family": "ГЭСНм",
            "collection": "08",
            "table": "08-02-001",
        }]},
        turn=4,
    )

    assert selected["rows"][0]["ok"] is True
    assert selected["rows"][0]["level"] == "table_selected"
    assert ("гэснм", "08", "08-02-001") in session.selected_tables["vor-001"]
