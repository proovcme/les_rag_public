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


def test_rim_norm_session_requires_catalog_scope_before_batch_search(monkeypatch):
    search_calls = []
    monkeypatch.setattr(
        document_workflow,
        "browse_norm_catalog",
        lambda **_kwargs: {
            "level": "table",
            "filters": {"family": "ГЭСНм", "collection": "10", "table": ""},
            "items": [],
        },
    )
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
    assert "browse_norm_catalog first" in rejected["rows"][0]["details"][0]
    assert search_calls == []

    session.execute(
        "browse_norm_catalog",
        {"items": [{"work_id": "vor-001", "family": "ГЭСНм", "collection": "10"}]},
        turn=2,
    )
    accepted = session.execute("search_norms_batch", search_args, turn=3)
    assert accepted["rows"][0]["ok"] is True
    assert search_calls[0][1]["base_types"] == ["ГЭСНм"]
    assert search_calls[0][1]["collections"] == ["10"]
