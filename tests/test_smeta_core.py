import hashlib
import json
from pathlib import Path

import pytest

from proxy.smeta_core.contracts import NormBinding, ResourceBinding, ResourceReview, WorkItem
from proxy.smeta_core.integrity import normative_base_integrity
from proxy.smeta_core.workflow import finalize_estimate_result


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _native_call(call_id, name, **arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def _technology_check(**overrides):
    value = {
        "matched_operations": ["Установка элемента"],
        "missing_operations": [],
        "extra_operations": [],
        "foreign_resources": [],
        "overlaps_with_work_ids": [],
        "overlap_resolution": "пересечений нет",
        "conditions_checked": ["измеритель и состав работ"],
        "unresolved_conditions": [],
        "conclusion": "applicable",
    }
    value.update(overrides)
    return value


def test_norm_binding_cannot_be_selected_by_code():
    with pytest.raises(ValueError, match="code cannot select"):
        NormBinding(
            work_id="w1",
            norm_code="ГЭСН:01-01-001-01",
            selected_by="code",
            selection_kind="exact",
            is_analog=False,
        )


def test_candidate_payload_marks_unit_mismatch_without_hiding_candidate(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, limit, **_kwargs: {
        queries[0]: {
            "backend": "sparse",
            "cards": [{
                "norm_code": "ГЭСН01-01-001-01",
                "title": "Комплексная работа",
                "measure_unit": "100 м2",
            }],
        }
    })
    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])

    payload = workflow._candidate_payload(
        {"work_id": "w1", "title": "Комплексная работа", "unit": "шт", "quantity": 1},
        "комплексная работа",
        limit=5,
    )

    assert [item["norm_code"] for item in payload["candidates"]] == ["ГЭСН01-01-001-01"]
    assert payload["candidates"][0]["unit_compatible"] is False


def test_candidate_payload_is_paginated_without_code_side_selection(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])
    search_results = {
        "работа": {
            "backend": "hybrid",
            "cards": [
                {"norm_code": f"ГЭСН01-01-001-{index:02d}", "title": f"Кандидат {index}", "measure_unit": "шт"}
                for index in range(1, 13)
            ],
        }
    }
    work = {"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}

    first = workflow._candidate_payload(work, "работа", limit=5, page=0, search_results=search_results)
    second = workflow._candidate_payload(work, "работа", limit=5, page=1, search_results=search_results)

    assert len(first["candidates"]) == 5
    assert len(second["candidates"]) == 5
    assert {item["norm_code"] for item in first["candidates"]}.isdisjoint(
        {item["norm_code"] for item in second["candidates"]}
    )
    assert first["has_more"] is True
    assert second["page"] == 1


def test_batch_agent_exposes_only_rag_read_and_model_submission_tools():
    from proxy.smeta_core.document_workflow import _batch_norm_tools

    tools = _batch_norm_tools()
    names = [(item.get("function") or {}).get("name") for item in tools]

    assert names == ["search_norms_batch", "read_norms_batch", "submit_lsr_mapping"]
    assert not {"search_norms", "read_norm", "bind_norm", "finish_norm_selection"}.intersection(names)
    submit = tools[-1]["function"]["parameters"]["properties"]["rows"]["items"]
    assert "quantity_multiplier" not in submit["properties"]
    assert submit["properties"]["decision"]["enum"] == ["bind", "covered_by", "unbound"]
    technology = submit["properties"]["technology_check"]
    assert set(technology["required"]) == {
        "matched_operations", "missing_operations", "extra_operations", "foreign_resources",
        "overlaps_with_work_ids", "overlap_resolution", "conditions_checked",
        "unresolved_conditions", "conclusion",
    }
    action = submit["properties"]["resource_actions"]["items"]
    assert "basis_ref" in action["required"]


def test_bind_submission_requires_analog_limits_and_resource_basis_without_questionnaire():
    from proxy.smeta_core.document_workflow import _bind_submission_errors

    incomplete = _bind_submission_errors({
        "selection_kind": "analog",
        "applicability": "close_analog",
        "analog_limitations": [],
        "technology_check": {"conclusion": "applicable"},
        "resource_actions": [{"action": "exclude", "reason": "не нужен"}],
        "reason": "похожая работа",
    })
    assert "analog requires explicit analog_limitations" in incomplete
    assert "resource_actions[0].basis_ref is required" in incomplete

    complete = _bind_submission_errors({
        "selection_kind": "exact",
        "applicability": "exact",
        "analog_limitations": [],
        "technology_check": _technology_check(),
        "resource_actions": [],
        "reason": "состав работ и измеритель совпадают",
    })
    assert complete == []


def test_batch_agent_default_keeps_fifty_rows_in_one_model_conversation():
    from proxy.smeta_core import document_workflow as workflow

    rows = [
        {"work_id": f"w{index:02d}", "title": f"Работа {index}", "unit": "шт", "quantity": index}
        for index in range(1, 51)
    ]
    captured = []

    def exchange(messages, tools):
        payload = json.loads(messages[1]["content"])
        captured.append({
            "payload": payload,
            "tools": [(item.get("function") or {}).get("name") for item in tools],
        })
        return {"tool_calls": [_native_call(
            "submit", "submit_lsr_mapping",
            rows=[
                {"work_id": row["work_id"], "decision": "unbound", "reason": "модель не выбрала норму"}
                for row in payload["work_items"]
            ],
        )]}

    result = workflow._run_native_norm_agent(
        rows,
        exchange,
        candidate_limit=8,
        max_turns=1,
        user_request="Собери ЛСР по всем строкам",
    )

    assert [len(item["payload"]["work_items"]) for item in captured] == [50]
    assert captured[0]["payload"]["all_source_rows_context"] == []
    assert captured[0]["payload"]["user_request"] == "Собери ЛСР по всем строкам"
    assert captured[0]["tools"] == ["search_norms_batch", "read_norms_batch", "submit_lsr_mapping"]
    assert len(result["selections"]) == 50
    assert result["agent_trace"]["turns"] == 1
    assert all(item["review_status"] == "model_batch_unbound" for item in result["selections"].values())


def test_batch_agent_zero_batch_size_gives_model_the_whole_vor():
    from proxy.smeta_core import document_workflow as workflow

    rows = [
        {"work_id": f"w{index}", "title": f"Работа {index}", "unit": "шт", "quantity": 1}
        for index in range(1, 20)
    ]
    payloads = []

    def exchange(messages, _tools):
        payload = json.loads(messages[1]["content"])
        payloads.append(payload)
        return {"tool_calls": [_native_call(
            "submit", "submit_lsr_mapping",
            rows=[
                {"work_id": row["work_id"], "decision": "unbound", "reason": "нет точной нормы"}
                for row in payload["work_items"]
            ],
        )]}

    result = workflow._run_native_norm_agent(
        rows,
        exchange,
        candidate_limit=8,
        batch_size=0,
    )

    assert len(payloads) == 1
    assert len(payloads[0]["work_items"]) == 19
    assert len(result["selections"]) == 19


def test_batch_agent_searches_reads_and_submits_model_choice(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": [{
            "norm_code": "ГЭСН01-01-001-01",
            "title": "Монтаж элемента",
            "measure_unit": "шт",
            "work_steps": ["Установка элемента"],
            "resource_preview": [],
        }]}
        for query in queries
    })
    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "name": "Монтаж элемента", "unit": "шт",
        "work_steps": ["Установка элемента"], "resources": [],
    })
    turns = iter([
        [_native_call("search", "search_norms_batch", items=[{
            "work_id": "w1", "queries": ["монтаж элемента"], "limit": 6,
        }])],
        [_native_call("read", "read_norms_batch", items=[{
            "work_id": "w1", "norm_codes": ["ГЭСН01-01-001-01"],
        }])],
        [_native_call("submit", "submit_lsr_mapping", rows=[{
            "work_id": "w1", "decision": "bind", "norm_code": "ГЭСН01-01-001-01",
            "selection_kind": "exact", "applicability": "exact",
            "analog_limitations": [],
            "technology_check": _technology_check(),
            "resource_actions": [], "reason": "модель выбрала после чтения карточки",
        }])],
    ])
    tool_sets = []

    def exchange(_messages, tools):
        tool_sets.append([(tool.get("function") or {}).get("name") for tool in tools])
        return {"tool_calls": next(turns)}

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Монтаж элемента", "unit": "шт", "quantity": 1}],
        exchange,
        candidate_limit=6,
        max_turns=3,
    )

    assert result["selections"]["w1"]["norm_code"] == "ГЭСН01-01-001-01"
    assert result["selections"]["w1"]["review_status"] == "model_batch"
    assert result["query_trace"][0]["phase"] == "batch_search"
    assert result["agent_trace"]["turns"] == 3
    assert tool_sets[0] == ["search_norms_batch", "read_norms_batch", "submit_lsr_mapping"]
    assert tool_sets[1] == ["search_norms_batch", "read_norms_batch"]
    assert tool_sets[2] == ["search_norms_batch", "read_norms_batch", "submit_lsr_mapping"]


def test_batch_agent_repairs_gemma_nested_work_id_without_changing_choice(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": [{
            "norm_code": "ГЭСН67-01-003-01",
            "title": "Прокладка кабеля",
            "measure_unit": "100 м",
            "work_steps": ["Прокладка кабеля"],
            "resource_preview": [],
        }]}
        for query in queries
    })
    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "name": "Прокладка кабеля", "unit": "100 м",
        "work_steps": ["Прокладка кабеля"], "resources": [],
    })
    check = _technology_check(work_id="w1")
    turns = iter([
        [_native_call("search", "search_norms_batch", items=[{
            "work_id": "w1", "queries": ["прокладка кабеля"],
        }])],
        [_native_call("read", "read_norms_batch", items=[{
            "work_id": "w1", "norm_codes": ["ГЭСН67-01-003-01"],
        }])],
        [_native_call("submit", "submit_lsr_mapping", rows=[{
            "decision": "bind", "norm_code": "ГЭСН67-01-003-01",
            "selection_kind": "exact", "applicability": "exact",
            "analog_limitations": [], "technology_check": check,
            "resource_actions": [], "reason": "состав работ совпадает",
        }])],
    ])

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Прокладка кабеля", "unit": "м", "quantity": 10}],
        lambda _messages, _tools: {"tool_calls": next(turns)},
        candidate_limit=6,
        max_turns=3,
    )

    selection = result["selections"]["w1"]
    assert selection["norm_code"] == "ГЭСН67-01-003-01"
    assert "work_id" not in selection["technology_check"]


def test_batch_agent_accepts_gemma_scalar_norm_code_for_read(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": [{
            "norm_code": "ГЭСН67-01-003-01", "title": "Прокладка кабеля",
            "measure_unit": "100 м", "work_steps": ["Прокладка кабеля"],
            "resource_preview": [],
        }]}
        for query in queries
    })
    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "name": "Прокладка кабеля", "unit": "100 м",
        "work_steps": ["Прокладка кабеля"], "resources": [],
    })
    turns = iter([
        [_native_call("search", "search_norms_batch", items=[{
            "work_id": "w1", "queries": ["прокладка кабеля"],
        }])],
        [_native_call("read", "read_norms_batch", items=[{
            "work_id": "w1", "norm_code": "ГЭСН67-01-003-01",
        }])],
        [_native_call("submit", "submit_lsr_mapping", rows=[{
            "work_id": "w1", "decision": "bind", "norm_code": "ГЭСН67-01-003-01",
            "selection_kind": "exact", "applicability": "exact",
            "analog_limitations": [], "reason": "состав работ совпадает",
        }])],
    ])

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Прокладка кабеля", "unit": "м", "quantity": 10}],
        lambda _messages, _tools: {"tool_calls": next(turns)},
        candidate_limit=6,
        max_turns=3,
    )

    assert result["selections"]["w1"]["norm_code"] == "ГЭСН67-01-003-01"


def test_batch_agent_resolves_colon_display_alias_without_changing_norm_family(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": [{
            "norm_code": "ГЭСН:67-01-003-01", "title": "Прокладка кабеля",
            "measure_unit": "100 м", "work_steps": ["Прокладка кабеля"],
            "resource_preview": [],
        }]}
        for query in queries
    })
    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda code, **_kwargs: {
        "name": code, "unit": "100 м", "work_steps": ["Прокладка кабеля"], "resources": [],
    })
    turns = iter([
        [_native_call("search", "search_norms_batch", items=[{
            "work_id": "w1", "queries": ["прокладка кабеля"],
        }])],
        [_native_call("read", "read_norms_batch", items=[{
            "work_id": "w1", "norm_codes": ["ГЭСН67-01-003-01"],
        }])],
        [_native_call("submit", "submit_lsr_mapping", rows=[{
            "work_id": "w1", "decision": "bind", "norm_code": "ГЭСН67-01-003-01",
            "selection_kind": "exact", "applicability": "exact",
            "analog_limitations": [], "reason": "состав работ совпадает",
        }])],
    ])

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Прокладка кабеля", "unit": "м", "quantity": 10}],
        lambda _messages, _tools: {"tool_calls": next(turns)},
        candidate_limit=6,
        max_turns=3,
    )

    assert result["selections"]["w1"]["norm_code"] == "ГЭСН:67-01-003-01"


def test_norm_card_resources_are_model_opt_in_without_losing_internal_card():
    from proxy.smeta_core.document_workflow import _norm_card_for_model

    card = {
        "norm_code": "ГЭСН67-01-003-01",
        "work_steps": ["Прокладка кабеля"],
        "resources": [
            {"code": "1-100-34", "name": "Рабочий", "kind": "labor", "per_unit": 2.5},
            {"code": "01.7.03", "name": "Кабель", "kind": "material", "per_unit": 101},
        ],
    }

    compact = _norm_card_for_model(card, include_resources=False)
    expanded = _norm_card_for_model(card, include_resources=True)

    assert compact["resource_count"] == 2
    assert compact["resource_kinds"] == {"labor": 1, "material": 1}
    assert "resources" not in compact
    assert expanded["resources"] == card["resources"]
    assert card["resources"][1]["name"] == "Кабель"


def test_exact_mapping_transport_defaults_only_semantically_empty_limitations():
    from proxy.smeta_core.document_workflow import _normalize_mapping_row_transport

    exact = _normalize_mapping_row_transport({"selection_kind": "exact", "norm_code": "ГЭСН01"})
    analog = _normalize_mapping_row_transport({"selection_kind": "analog", "norm_code": "ГЭСН02"})

    assert exact["analog_limitations"] == []
    assert "analog_limitations" not in analog


def test_mapping_transport_uses_models_explicit_analog_and_row_reason():
    from proxy.smeta_core.document_workflow import _normalize_mapping_row_transport

    normalized = _normalize_mapping_row_transport({
        "selection_kind": "exact",
        "applicability": "close_analog",
        "analog_limitations": ["материал заменить"],
        "reason": "состав работ совпадает, материал заменить",
        "resource_actions": [{"action": "replace", "basis_ref": "card:material"}],
    })

    assert normalized["selection_kind"] == "analog"
    assert normalized["resource_actions"][0]["reason"] == normalized["reason"]


def test_tool_array_transport_unwraps_qwen_double_serialization():
    from proxy.smeta_core.document_workflow import _tool_arguments, _tool_array_argument, _tool_bool

    args = {
        "items": '[{"work_id":"w1","norm_codes":["ГЭСН67-01-003-01"]}]',
        "include_resources": "True",
    }

    assert _tool_array_argument(args, "items") == [
        {"work_id": "w1", "norm_codes": ["ГЭСН67-01-003-01"]}
    ]
    assert _tool_bool(args["include_resources"]) is True
    assert _tool_bool("False") is False
    assert _tool_array_argument({"items": json.dumps(args["items"])}, "items") == _tool_array_argument(args, "items")
    python_call = {"function": {"arguments": "{'items': '[{\"work_id\": \"w1\"}]'}"}}
    assert _tool_arguments(python_call)["items"].startswith("[")


def test_tool_array_transport_accepts_qwen_mapping_alias_only_when_declared():
    from proxy.smeta_core.document_workflow import _tool_array_argument

    args = {"mapping": '[{"work_id":"w1","decision":"unbound","reason":"нет нормы"}]'}
    assert _tool_array_argument(args, "rows") == []
    assert _tool_array_argument(args, "rows", aliases=("mapping",)) == [{
        "work_id": "w1", "decision": "unbound", "reason": "нет нормы",
    }]


def test_tool_array_transport_closes_only_missing_trailing_array_delimiter():
    from proxy.smeta_core.document_workflow import _tool_array_argument

    truncated = '[{"work_id":"w1","norm_codes":["ГЭСН17-01-010-01"]}'
    assert _tool_array_argument({"items": truncated}, "items") == [{
        "work_id": "w1", "norm_codes": ["ГЭСН17-01-010-01"],
    }]
    assert _tool_array_argument({"items": '[{"work_id":"w1"}] garbage'}, "items") == []


def test_batch_agent_rejects_unopened_norm_without_selecting_for_model(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "typed_sqlite_fts", "cards": []} for query in queries
    })

    turns = iter([
        [_native_call("bad", "submit_lsr_mapping", rows=[{
            "work_id": "w1", "decision": "bind", "norm_code": "ГЭСН01-01-999-99",
            "selection_kind": "exact", "reason": "не открыта",
        }])],
        [_native_call("safe", "submit_lsr_mapping", rows=[{
            "work_id": "w1", "decision": "unbound", "reason": "нет защищаемой нормы",
        }])],
    ])

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        lambda _messages, _tools: {"tool_calls": next(turns)},
        candidate_limit=5,
        max_turns=2,
    )

    assert result["selections"]["w1"]["norm_code"] == ""
    first_result = result["model_trace"][0]["tool_results"][0]["result"]
    assert first_result["ok"] is False
    assert "opened by the model" in first_result["errors"][0]["error"]


def test_batch_agent_resolves_models_exact_submitted_norm_without_reselecting(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    selected_code = "ГЭСН01-01-001-01"
    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "typed_sqlite_fts", "cards": [{
            "norm_code": selected_code,
            "title": "Работа",
            "measure_unit": "шт",
            "source_ref": "base.sqlite#norm",
        }]}
        for query in queries
    })
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda code, **_kwargs: {
        "name": "Работа", "unit": "шт", "work_steps": ["Работа"], "resources": [],
    } if code == selected_code else None)

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        lambda _messages, _tools: {"tool_calls": [_native_call(
            "submit", "submit_lsr_mapping", rows=[{
                "work_id": "w1", "decision": "bind", "norm_code": selected_code,
                "selection_kind": "exact", "applicability": "exact",
                "analog_limitations": [], "reason": "модель выбрала точную норму",
            }],
        )]},
        candidate_limit=5,
        max_turns=1,
    )

    assert result["selections"]["w1"]["norm_code"] == selected_code
    assert result["browse_trace"]["w1"][-1]["mode"] == "model_submitted_exact_lookup"


def test_batch_agent_keeps_valid_rows_while_model_repairs_only_rejected_row(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": [{
            "norm_code": "ГЭСН01-01-001-01", "title": "Работа 1",
            "measure_unit": "шт", "work_steps": ["Работа"], "resource_preview": [],
        }]}
        for query in queries
    })
    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "name": "Работа 1", "unit": "шт", "work_steps": ["Работа"], "resources": [],
    })
    turns = iter([
        [_native_call("search", "search_norms_batch", items=[
            {"work_id": "w1", "queries": ["работа 1"]},
            {"work_id": "w2", "queries": ["работа 2"]},
        ])],
        [_native_call("read", "read_norms_batch", items=[{
            "work_id": "w1", "norm_codes": ["ГЭСН01-01-001-01"],
        }])],
        [_native_call("submit1", "submit_lsr_mapping", rows=[
            {"work_id": "w1", "decision": "bind", "norm_code": "ГЭСН01-01-001-01",
             "selection_kind": "exact", "applicability": "exact", "reason": "совпадает"},
            {"work_id": "w2", "decision": "bind", "norm_code": "ГЭСН01-01-999-99",
             "selection_kind": "exact", "applicability": "exact", "reason": "не открыта"},
        ])],
        [_native_call("submit2", "submit_lsr_mapping", rows=[{
            "work_id": "w2", "decision": "unbound", "reason": "точной нормы нет",
        }])],
    ])

    result = workflow._run_native_norm_agent(
        [
            {"work_id": "w1", "title": "Работа 1", "unit": "шт", "quantity": 1},
            {"work_id": "w2", "title": "Работа 2", "unit": "шт", "quantity": 1},
        ],
        lambda _messages, _tools: {"tool_calls": next(turns)},
        candidate_limit=3,
        max_turns=4,
    )

    assert result["selections"]["w1"]["norm_code"] == "ГЭСН01-01-001-01"
    assert result["selections"]["w2"]["norm_code"] == ""
    retry = result["model_trace"][2]["tool_results"][0]["result"]
    assert retry["accepted_work_ids"] == ["w1"]
    assert retry["remaining_work_ids"] == ["w2"]


def test_batch_agent_has_configurable_transport_turn_budget():
    from proxy.smeta_core import document_workflow as workflow

    calls = 0

    def exchange(_messages, _tools):
        nonlocal calls
        calls += 1
        return {"tool_calls": [_native_call(f"unknown-{calls}", "unknown_tool")]}

    with pytest.raises(RuntimeError, match="within 2 model turns"):
        workflow._run_native_norm_agent(
            [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
            exchange,
            candidate_limit=5,
            max_turns=2,
        )
    assert calls == 2


def test_batch_agent_reports_model_wait_before_and_after_each_turn():
    from proxy.smeta_core import document_workflow as workflow

    events = []
    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        lambda _messages, _tools: {"tool_calls": [_native_call(
            "submit", "submit_lsr_mapping",
            rows=[{"work_id": "w1", "decision": "unbound", "reason": "нет точной нормы"}],
        )]},
        candidate_limit=5,
        progress=events.append,
    )

    waits = [event for event in events if event.get("phase") == "model_wait"]
    assert [(event["status"], event["turn"]) for event in waits] == [("started", 1), ("done", 1)]
    assert result["selections"]["w1"]["norm_code"] == ""


def test_batch_agent_stops_after_four_invalid_mapping_corrections():
    from proxy.smeta_core import document_workflow as workflow

    calls = 0

    def exchange(_messages, _tools):
        nonlocal calls
        calls += 1
        return {"tool_calls": [_native_call(
            f"submit-{calls}",
            "submit_lsr_mapping",
            rows=[{"work_id": "w1", "decision": "unbound", "reason": ""}],
        )]}

    with pytest.raises(RuntimeError, match="after 4 correction attempts"):
        workflow._run_batch_norm_agent(
            [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
            exchange,
            candidate_limit=5,
        )

    assert calls == 4


def test_batch_agent_fails_closed_when_model_returns_no_tools():
    from proxy.smeta_core import document_workflow as workflow

    calls = 0

    def exchange(_messages, _tools):
        nonlocal calls
        calls += 1
        return {
            "role": "assistant",
            "content": "",
            "_les_done_reason": "length",
            "_les_eval_count": 900,
        }

    with pytest.raises(RuntimeError, match="done_reason=length, eval_count=900"):
        workflow._run_native_norm_agent(
            [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
            exchange,
            candidate_limit=5,
        )
    assert calls == 1


def test_document_workflow_passes_neighbor_context_and_calculates_once(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "intake_vor_document", lambda _path: {"work_items": [
        {"work_id": "w1", "title": "Прокладка кабеля", "unit": "м", "quantity": 10, "section": "ЭОМ"},
        {"work_id": "w2", "title": "Монтаж трубы", "unit": "м", "quantity": 10, "section": "ЭОМ"},
    ]})
    calculations = []
    monkeypatch.setattr(workflow, "calculate_visible_rows_revision", lambda rows, **_kwargs: (
        calculations.append(rows) or {"summary": {"input_rows": len(rows), "bound_rows": 0}}
    ))
    seen = {}

    def exchange(messages, _tools):
        payload = json.loads(messages[1]["content"])
        seen.update({item["work_id"]: item for item in payload["work_items"]})
        return {"tool_calls": [_native_call("submit", "submit_lsr_mapping", rows=[
            {"work_id": item["work_id"], "decision": "unbound", "reason": "нет нормы"}
            for item in payload["work_items"]
        ])]}

    result = workflow.run_vor_pdf_workflow(
        "source.pdf", exchange=exchange,
    )

    assert seen["w1"]["neighbor_context"][0]["work_id"] == "w2"
    assert seen["w2"]["neighbor_context"][0]["work_id"] == "w1"
    assert len(calculations) == 1
    assert "dominant_review" not in result


def test_xlsx_vor_intake_preserves_all_rows_and_sheet_provenance(tmp_path):
    import openpyxl

    from proxy.smeta_core.source_intake import intake_vor_document

    source = tmp_path / "СКС.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "СКС"
    sheet.append(["№ п/п", "Наименование работ и затрат", "Ед. изм.", "Объём", "Цена"])
    sheet.append([1, "Раздел 1. СКС", None, None, 0])
    sheet.append([2, "Оборудование", None, None, 0])
    sheet.append([3, "Шкаф телекоммуникационный", "шт.", 2, None])
    sheet.append([4, "Кабель витая пара", "м", 1200, None])
    workbook.save(source)

    intake = intake_vor_document(source)

    assert intake["source_kind"] == "xlsx"
    assert intake["work_item_count"] == 2
    assert [row["work_id"] for row in intake["work_items"]] == ["vor-0001", "vor-0002"]
    assert intake["work_items"][0]["section"] == "Оборудование"
    assert intake["work_items"][0]["source_row"] == 4
    assert "#sheet=СКС;table=1;row=4" in intake["work_items"][0]["source_refs"][0]
    assert intake["work_items"][1]["quantity"] == 1200.0
















@pytest.mark.parametrize(
    ("source_quantity", "source_unit", "norm_unit", "expected_factor", "expected_norm_quantity"),
    [
        (8.0, "шт", "шт", 1.0, 8.0),
        (3.2, "м2", "100 м2", 0.01, 0.032),
        (160.0, "м", "100 м", 0.01, 1.6),
        (160.0, "м", "100 м труб", 0.01, 1.6),
        (160.0, "м", "100 м кабеля", 0.01, 1.6),
        (3.2, "м2", "100 м2 поверхности", 0.01, 0.032),
    ],
)
def test_norm_quantity_has_one_explicit_unit_conversion(
    monkeypatch, source_quantity, source_unit, norm_unit, expected_factor, expected_norm_quantity
):
    from proxy.smeta_core import norm_validator
    from proxy.smeta_core.contracts import WorkItem

    monkeypatch.setattr(norm_validator.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "code": "ГЭСН01-01-001-01",
        "name": "Работа",
        "unit": norm_unit,
        "_source_kind": "seed_yaml",
    })
    work = WorkItem(work_id="w1", title="Работа", quantity=source_quantity, unit=source_unit)
    binding = NormBinding(
        work_id="w1",
        norm_code="ГЭСН01-01-001-01",
        selected_by="model",
        selection_kind="exact",
        is_analog=False,
    )

    result = norm_validator.validate_binding(work, binding)

    assert result["physical_quantity"] == source_quantity
    assert result["unit_conversion_factor"] == pytest.approx(expected_factor)
    assert result["norm_quantity"] == pytest.approx(expected_norm_quantity)






























def test_invalid_resource_binding_is_row_blocker_not_whole_lsr_crash():
    from proxy.smeta_core.workflow import calculate_visible_rows

    trace = calculate_visible_rows([
        {
            "work_id": "w1",
            "title": "Устройство кровли",
            "unit": "м2",
            "quantity": 10,
            "norm_code": "ГЭСН12-01-034-02",
            "selection_kind": "exact",
            "resource_bindings": [
                {"action": "add", "selected_by": "model", "resource_name": "", "unit": ""},
            ],
        }
    ])

    assert trace["summary"]["bound_rows"] == 1
    assert trace["summary"]["result_status"] == "priced_partial"
    assert any(item["code"] == "resource_binding_contract_rejected" for item in trace["blockers"])


def test_reuse_preserves_target_norm_resource_without_synthetic_unit():
    from proxy.smeta_core.calculator import _apply_resource_bindings

    resources, problems = _apply_resource_bindings(
        [{"code": "01.1", "name": "Панель", "unit": "м2", "per_unit": 1.25, "price": 500}],
        [ResourceBinding(
            work_id="w1",
            action="reuse",
            selected_by="model",
            target_resource_code="01.1",
            reason="панели сняты с сохранением",
        )],
        work_qty=2,
    )

    assert problems == []
    assert resources == [{
        "code": "01.1",
        "name": "Панель",
        "unit": "м2",
        "per_unit": 1.25,
        "price": 0.0,
        "price_source_ref": "reuse decision",
        "resource_binding": {
            "action": "reuse",
            "selected_by": "model",
            "reason": "панели сняты с сохранением",
            "source_refs": [],
            "price_source_ref": "reuse decision",
        },
    }]


def test_normative_base_is_quarantined_without_semantic_report(tmp_path):
    base = tmp_path / "base.sqlite"
    manifest = tmp_path / "manifest.json"
    base.write_bytes(b"not-a-real-db")
    manifest.write_text(json.dumps({"source": {"sha256": "source-revision"}}), encoding="utf-8")

    result = normative_base_integrity(
        base_path=base,
        manifest_path=manifest,
        report_path=tmp_path / "missing-integrity.json",
    )

    assert result["status"] == "quarantined"
    assert result["trusted_for_pricing"] is False
    assert result["trusted_for_navigation"] is False
    assert "semantic integrity report is missing" in result["reasons"]


def test_normative_base_requires_zero_failure_checks_and_matching_hashes(tmp_path):
    base = tmp_path / "base.sqlite"
    manifest = tmp_path / "manifest.json"
    report = tmp_path / "integrity.json"
    base.write_bytes(b"verified-test-base")
    manifest.write_text(json.dumps({"source": {"sha256": "source-revision"}}), encoding="utf-8")
    report.write_text(
        json.dumps(
            {
                "schema": "les_smeta_base_integrity_v1",
                "verdict": "passed",
                "source_sha256": "source-revision",
                "base_sha256": _sha(base),
                    "checks": {
                        "cross_family_contamination": {"failures": 0},
                        "orphan_resources": {"failures": 0},
                        "duplicate_norm_keys": {"failures": 0},
                        "resource_parent_mismatch": {"failures": 0},
                        "empty_machine_base": {"failures": 0},
                        "missing_provenance": {"failures": 0},
                        "fts_coverage": {"failures": 0},
                        "minimum_norms": {"failures": 0},
                },
            }
        ),
        encoding="utf-8",
    )

    result = normative_base_integrity(base_path=base, manifest_path=manifest, report_path=report)

    assert result["status"] == "trusted"
    assert result["trusted_for_pricing"] is True
    assert result["trusted_for_navigation"] is True
    assert result["reasons"] == []


def test_missing_historical_provenance_allows_navigation_but_not_final_pricing(tmp_path):
    base = tmp_path / "base.sqlite"
    manifest = tmp_path / "manifest.json"
    report = tmp_path / "integrity.json"
    base.write_bytes(b"structurally-valid-navigation-base")
    manifest.write_text(json.dumps({"source": {"sha256": "source-revision"}}), encoding="utf-8")
    checks = {
        "cross_family_contamination": {"failures": 0},
        "orphan_resources": {"failures": 0},
        "duplicate_norm_keys": {"failures": 0},
        "resource_parent_mismatch": {"failures": 0},
        "empty_machine_base": {"failures": 0},
        "missing_provenance": {"failures": 7},
        "fts_coverage": {"failures": 0},
        "minimum_norms": {"failures": 0},
    }
    report.write_text(json.dumps({
        "schema": "les_smeta_base_integrity_v1",
        "verdict": "failed",
        "source_sha256": "source-revision",
        "base_sha256": _sha(base),
        "checks": checks,
    }), encoding="utf-8")

    result = normative_base_integrity(base_path=base, manifest_path=manifest, report_path=report)

    assert result["trusted_for_navigation"] is True
    assert result["navigation_reasons"] == []
    assert result["trusted_for_pricing"] is False
    assert "required check failed: missing_provenance=7" in result["reasons"]


def test_normative_base_manifest_floor_blocks_small_but_structurally_valid_base(tmp_path):
    base = tmp_path / "base.sqlite"
    manifest = tmp_path / "manifest.json"
    report = tmp_path / "integrity.json"
    base.write_bytes(b"small-structured-base")
    manifest.write_text(json.dumps({
        "source": {"sha256": "source-revision"},
        "minimum_norms": 40_000,
        "output": {"norms": 171},
    }), encoding="utf-8")
    report.write_text(json.dumps({
        "schema": "les_smeta_base_integrity_v1",
        "verdict": "passed",
        "source_sha256": "source-revision",
        "base_sha256": _sha(base),
        "checks": {
            "cross_family_contamination": {"failures": 0},
            "orphan_resources": {"failures": 0},
            "duplicate_norm_keys": {"failures": 0},
            "resource_parent_mismatch": {"failures": 0},
            "empty_machine_base": {"failures": 0},
            "missing_provenance": {"failures": 0},
            "fts_coverage": {"failures": 0},
        },
    }), encoding="utf-8")

    result = normative_base_integrity(base_path=base, manifest_path=manifest, report_path=report)

    assert result["trusted_for_pricing"] is False
    assert result["trusted_for_navigation"] is False
    assert "171 < 40000" in " ".join(result["reasons"])


def test_finality_is_blocked_for_quarantined_normative_source():
    result = finalize_estimate_result(
        {
            "computed": [
                {
                    "code": "ГЭСН:01-01-001-01",
                    "norm_source_kind": "structured_sqlite",
                    "norm_source_integrity": {"trusted_for_pricing": False},
                }
            ],
            "total_status": "complete",
            "partial_total": {"grand_total": 123.45},
            "final_total": {"grand_total": 123.45},
            "blockers": [],
        },
        source_status={
            "sources": [
                {
                    "id": "gesn_base",
                    "status": "quarantined_blocking",
                    "integrity": {"reasons": ["cross-family contamination"]},
                }
            ]
        },
    )

    assert result["total_status"] == "partial"
    assert result["final_total"] is None
    assert result["evidence_status"] == "blocked"
    assert result["calculation_status"] == "unsafe_source"
    assert result["partial_total"]["unverified_due_to_source_quarantine"] is True
    assert result["workflow_result"]["schema"] == "smeta_workflow_result_v1"


def test_verified_seed_position_is_not_blocked_by_unrelated_quarantined_base():
    result = finalize_estimate_result(
        {
            "computed": [{"code": "ГЭСН:12-01-034-02", "norm_source_kind": "seed_yaml"}],
            "total_status": "complete",
            "partial_total": {"grand_total": 11813.04},
            "final_total": {"grand_total": 11813.04},
            "blockers": [],
        },
        source_status={"sources": [{"id": "gesn_base", "status": "quarantined_blocking"}]},
    )

    assert result["total_status"] == "complete"
    assert result["final_total"]["grand_total"] == 11813.04
    assert result["evidence_status"] == "supported"
    assert result["calculation_status"] == "complete"


def test_invalid_model_choice_never_falls_back_to_first_candidate():
    from proxy.services import estimate_harness_service as harness

    candidate = {
        "norm_code": "ГЭСН:01-01-001-01",
        "title": "Strong first hit",
        "measure_unit": "100 м3",
        "score_total": 99.0,
        "applicability_status": "accepted",
        "unit_compatible": True,
    }
    selected, index, trace = harness._model_select_candidate(
        item={"work": "Работа", "work_family": "earthworks"},
        search={"selection": {"shortlist": [candidate]}},
        candidates=[candidate],
        messages=[],
        complete=lambda _messages: "{}",
    )

    assert selected is None
    assert index == -1
    assert trace["status"] == "invalid"
    assert trace["selected_code"] == ""


def test_norm_browser_returns_cards_without_code_selected_norm(monkeypatch):
    from proxy.smeta_core import norm_browser

    class Row:
        code = "ГЭСН:12-01-034-02"
        title = "Устройство кровли"
        measure_unit = "100 м2"

        @staticmethod
        def profile():
            return {"work_steps": ["укладка"]}

    monkeypatch.setattr(norm_browser, "search_rows", lambda _words: [Row()])
    monkeypatch.setattr(norm_browser, "_typed_cards", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(norm_browser, "_rag_cards_many", lambda queries, **_kwargs: {query: [] for query in queries})
    monkeypatch.setattr(
        norm_browser,
        "normative_base_integrity",
        lambda **_kwargs: {"status": "quarantined", "trusted_for_pricing": False},
    )

    result = norm_browser.browse_norms("устройство кровли")

    assert result["selection_owner"] == "model_or_user"
    assert result["selected_code"] == ""
    assert result["cards"][0]["norm_code"] == "ГЭСН:12-01-034-02"


def test_norm_browser_fuses_typed_and_dedicated_rag_candidates(monkeypatch, tmp_path):
    from proxy.smeta_core import norm_browser

    lexical = [
        {"norm_code": "ГЭСН01-01-001-01", "title": "Лексический", "measure_unit": "шт"},
        {"norm_code": "ГЭСН01-01-002-01", "title": "Общий", "measure_unit": "шт"},
    ]
    semantic = [
        {"norm_code": "ГЭСН01-01-002-01", "title": "Общий", "measure_unit": "шт"},
        {"norm_code": "ГЭСН01-01-003-01", "title": "Семантический", "measure_unit": "шт"},
    ]
    monkeypatch.setattr(norm_browser, "_typed_cards", lambda *_args, **_kwargs: lexical)
    monkeypatch.setattr(
        norm_browser,
        "_rag_cards_many",
        lambda queries, **_kwargs: {query: semantic for query in queries},
    )
    monkeypatch.setattr(norm_browser, "_rerank_cards", lambda _query, cards, limit: (cards[:limit], False))
    monkeypatch.setattr(
        norm_browser,
        "normative_base_integrity",
        lambda **_kwargs: {"status": "trusted", "trusted_for_pricing": True},
    )

    result = norm_browser.browse_norms("смысловой запрос", limit=3, base_path=tmp_path / "base.sqlite")

    assert "smeta_norm_qdrant_hybrid" in result["backend"]
    assert [card["norm_code"] for card in result["cards"]] == [
        "ГЭСН01-01-002-01",
        "ГЭСН01-01-001-01",
        "ГЭСН01-01-003-01",
    ]
    assert result["selected_code"] == ""


def test_structured_norm_from_unverified_base_cannot_be_priced_final(monkeypatch, tmp_path):
    from proxy.services import rim_lsr_trace_service as rim

    base = tmp_path / "unverified.sqlite"
    base.write_bytes(b"unverified")
    monkeypatch.setattr(
        rim.gesn_service,
        "get_norm",
        lambda _code: {
            "code": "ГЭСН01-01-001-01",
            "name": "Тестовая работа",
            "unit": "1 м3",
            "resources": [
                {"kind": "labor", "name": "Рабочий", "unit": "чел.-ч", "per_unit": 1, "price": 100}
            ],
            "_source_kind": "structured_sqlite",
            "_source_path": str(base),
        },
    )

    trace = rim.build_lsr_trace([{"code": "ГЭСН01-01-001-01", "qty": 1}])

    assert trace["summary"]["total"] > 0
    assert trace["summary"]["result_status"] == "priced_partial"
    assert any("база в карантине" in flag for flag in trace["summary"]["flags"])
