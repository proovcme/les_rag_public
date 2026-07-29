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


def _candidate_evaluations(code, *, decision="selected"):
    return [{
        "candidate_code": code,
        "operation_match": "exact",
        "object_match": "exact",
        "unit_match": "compatible",
        "scope_match": "exact",
        "foreign_resources": [],
        "decision": decision,
        "reason": "модель сравнила открытую карточку с исходной работой",
    }]


def _unbound_evidence(*, queries=None, opened=None):
    return {
        "queries_used": list(queries or ["буквальный поиск", "нормативная формулировка"]),
        "opened_norm_codes": list(opened or []),
        "rejection_reasons": ["состав работ не покрывает исходную операцию"],
        "coverage_checked": "соседние строки не покрывают работу",
    }


def test_norm_binding_cannot_be_selected_by_code():
    with pytest.raises(ValueError, match="code cannot select"):
        NormBinding(
            work_id="w1",
            norm_code="ГЭСН:01-01-001-01",
            selected_by="code",
            selection_kind="exact",
            is_analog=False,
        )


def test_sequential_row_tasks_receive_completed_model_decisions():
    from proxy.smeta_core import document_workflow as workflow

    rows = [
        {"work_id": "w1", "title": "Первая работа", "unit": "шт", "quantity": 1},
        {"work_id": "w2", "title": "Вторая работа", "unit": "м", "quantity": 2},
        {"work_id": "w3", "title": "Третья работа", "unit": "м2", "quantity": 3},
    ]
    received = []

    def runner(work_rows, **_kwargs):
        received.append(work_rows)
        row = work_rows[0]
        work_id = row["work_id"]
        return {
            "selections": {
                work_id: {
                    "norm_code": "",
                    "reason": f"решение {work_id}",
                    "review_status": "model_batch_unbound",
                },
            },
            "browse_trace": {},
            "query_trace": [],
            "model_trace": [],
            "valid_model_rows": 1,
            "agent_trace": {"engine": "qwen_agent", "model_turns": 1},
        }

    result = workflow._run_native_norm_agent(
        rows,
        lambda _messages, _tools: {},
        candidate_limit=8,
        max_turns=6,
        batch_size=1,
        batch_runner=runner,
        accumulate_task_state=True,
    )

    assert [len(batch) for batch in received] == [1, 1, 1]
    assert received[0][0]["task_state"]["completed_decisions"] == []
    assert received[1][0]["task_state"]["completed_decisions"] == [{
        "work_id": "w1",
        "title": "Первая работа",
        "norm_code": "",
        "covered_by_work_id": "",
        "decision": "unbound",
        "reason": "решение w1",
    }]
    assert received[2][0]["task_state"]["completed_rows"] == 2
    assert result["agent_trace"]["batch_size"] == 1
    assert result["agent_trace"]["task_mode"] == "sequential_rows"


def test_sequential_row_mapping_resumes_checkpoint_without_repeating_completed_rows():
    from proxy.smeta_core import document_workflow as workflow

    rows = [
        {"work_id": "w1", "title": "Первая работа", "unit": "шт", "quantity": 1},
        {"work_id": "w2", "title": "Вторая работа", "unit": "м", "quantity": 2},
        {"work_id": "w3", "title": "Третья работа", "unit": "м2", "quantity": 3},
    ]
    resumed_selection = {
        "norm_code": "",
        "reason": "решение w1",
        "review_status": "model_batch_unbound",
    }
    received_work_ids = []
    checkpoints = []

    def runner(work_rows, **_kwargs):
        work_id = str(work_rows[0]["work_id"])
        received_work_ids.append(work_id)
        return {
            "selections": {
                work_id: {
                    "norm_code": "",
                    "reason": f"решение {work_id}",
                    "review_status": "model_batch_unbound",
                },
            },
            "opened_cards": {},
            "browse_trace": {},
            "query_trace": [],
            "catalog_trace": [],
            "model_trace": [],
            "valid_model_rows": 1,
            "agent_trace": {"engine": "qwen_agent", "model_turns": 1},
        }

    result = workflow._run_native_norm_agent(
        rows,
        lambda _messages, _tools: {},
        candidate_limit=8,
        max_turns=6,
        batch_size=1,
        batch_runner=runner,
        accumulate_task_state=True,
        resume_result={
            "selections": {"w1": resumed_selection},
            "opened_cards": {},
            "browse_trace": {},
            "query_trace": [],
            "catalog_trace": [],
            "model_trace": [],
        },
        checkpoint=checkpoints.append,
    )

    assert received_work_ids == ["w2", "w3"]
    assert len(checkpoints) == 2
    assert set(checkpoints[0]["selections"]) == {"w1", "w2"}
    assert checkpoints[0]["remaining_work_ids"] == ["w3"]
    assert result["selections"]["w1"] == resumed_selection
    assert set(result["selections"]) == {"w1", "w2", "w3"}
    assert result["incomplete"] is False


def test_terminal_mapping_emits_only_completed_row_payload():
    from proxy.smeta_core import document_workflow as workflow

    events = []
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 4}],
        candidate_limit=8,
        progress=events.append,
    )
    session.query_trace.append({
        "work_id": "w1",
        "queries": ["буквальный поиск", "нормативная формулировка"],
    })

    result = session.execute(
        "submit_lsr_mapping",
        {"rows": [{
            "work_id": "w1",
            "decision": "unbound",
            "reason": "подходящая норма не найдена",
            "unbound_evidence": _unbound_evidence(),
        }]},
        turn=1,
    )

    assert result == {"ok": True, "rows": 1}
    ready = [event for event in events if event.get("phase") == "row_ready"]
    assert len(ready) == 1
    assert ready[0]["status"] == "done"
    assert ready[0]["row"] == {
        "work_id": "w1",
        "title": "Работа",
        "unit": "шт",
        "quantity": 4,
        "section": "",
        "decision": "unbound",
        "decision_label": "Оставлено без нормы",
        "norm_code": "",
        "covered_by_work_id": "",
        "reason": "подходящая норма не найдена",
    }


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


def test_candidate_payload_sorts_queries_for_repeatable_fresh_runs(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    seen = {}

    def fake_browse(queries, limit=8, **_kwargs):
        seen["queries"] = list(queries)
        return {
            query: {
                "backend": "rrf",
                "cards": [{
                    "norm_code": f"ГЭСН01-01-00{index}-01",
                    "title": query,
                    "measure_unit": "шт",
                }],
            }
            for index, query in enumerate(queries, 1)
        }

    monkeypatch.setattr(workflow, "browse_norms_many", fake_browse)
    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])

    payload = workflow._candidate_payload(
        {"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1},
        ["яблоко", " абрикос ", "яблоко"],
        limit=5,
    )

    assert seen["queries"] == ["абрикос", "яблоко"]
    assert payload["query"] == ["абрикос", "яблоко"]


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


def test_search_page_caps_catalog_style_limit_without_hiding_next_page(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])
    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "typed_sqlite_fts", "cards": [
            {"norm_code": f"ГЭСН15-01-001-{index:02d}", "title": f"Кандидат {index}", "measure_unit": "м2"}
            for index in range(1, 13)
        ]} for query in queries
    })
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Работа", "unit": "м2", "quantity": 1}],
        candidate_limit=4,
    )

    result = session.execute(
        "search_norms_batch",
        {"items": [{
            "work_id": "w1", "query": "работа", "search_intent": "source_literal", "limit": 100,
        }]},
        turn=1,
    )

    row = result["rows"][0]
    assert row["requested_limit"] == 100
    assert row["page_size"] == 4
    assert len(row["candidates"]) == 4
    assert row["has_more"] is True


def test_batch_agent_exposes_only_rag_read_and_model_submission_tools():
    from proxy.smeta_core.document_workflow import _batch_norm_tools

    tools = _batch_norm_tools()
    names = [(item.get("function") or {}).get("name") for item in tools]

    assert names == [
        "browse_norm_catalog", "search_norms_batch", "read_norms_batch", "submit_lsr_mapping",
    ]
    catalog_item = tools[0]["function"]["parameters"]["properties"]["items"]["items"]
    assert "table" in catalog_item["properties"]
    assert "scope_reason" in catalog_item["properties"]
    assert catalog_item["properties"]["confidence"]["enum"] == ["low", "medium", "high"]
    assert "limit" not in catalog_item["properties"]
    search_item = tools[1]["function"]["parameters"]["properties"]["items"]["items"]
    assert "table_codes" in search_item["properties"]
    assert not {"search_norms", "read_norm", "bind_norm", "finish_norm_selection"}.intersection(names)
    submit = tools[-1]["function"]["parameters"]["properties"]["rows"]["items"]
    assert "quantity_multiplier" not in submit["properties"]
    assert submit["properties"]["decision"]["enum"] == ["bind", "covered_by", "unbound"]
    assert submit["required"] == ["work_id", "decision", "reason"]
    assert "technology_check" in submit["allOf"][0]["then"]["required"]
    assert "candidate_evaluations" in submit["allOf"][0]["then"]["required"]
    comparison = submit["properties"]["candidate_evaluations"]["items"]
    assert comparison["properties"]["decision"]["enum"] == ["selected", "rejected", "uncertain"]
    assert "required" in submit["properties"]["technology_check"]
    assert "unbound_evidence" in submit["properties"]


def test_catalog_tool_exposes_current_typed_collection_scope(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    seen = {}

    def catalog(**kwargs):
        seen.update(kwargs)
        return {
            "level": "collection",
            "filters": {"family": kwargs["family"], "collection": "", "table": ""},
            "items": [{
                "key": "15",
                "norm_count": 120,
                "resource_count": 900,
                "source_example": "Сборник 15. Отделочные работы / Раздел 4",
            }],
        }

    monkeypatch.setattr(workflow, "browse_norm_catalog", catalog)
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Окраска потолков", "unit": "м2", "quantity": 3.2}],
        candidate_limit=8,
    )

    result = session.execute(
        "browse_norm_catalog",
        {"items": [{"work_id": "w1", "family": "ГЭСН", "limit": 5}]},
        turn=1,
    )

    assert result["ok"] is True
    assert result["rows"][0]["level"] == "collection"
    assert result["rows"][0]["items"] == [{
        "key": "15",
        "norm_count": 120,
        "resource_count": 900,
        "source_example": "Сборник 15. Отделочные работы / Раздел 4",
    }]
    assert session.catalog_trace[0]["work_id"] == "w1"
    assert seen["limit"] == 1000


def test_catalog_reaches_official_table_scope_and_suppresses_repeated_page(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    calls = 0

    def catalog(**kwargs):
        nonlocal calls
        calls += 1
        if kwargs.get("family") and kwargs.get("collection"):
            return {
                "level": "table",
                "filters": {"family": "ГЭСН", "collection": "15", "table": ""},
                "items": [{
                    "key": "15-04-001",
                    "norm_count": 7,
                    "resource_count": 30,
                    "source_example": "Таблица ГЭСН 15-04-001",
                }],
            }
        return {
            "level": "family", "filters": {},
            "items": [{"key": "ГЭСН", "norm_count": 100, "resource_count": 200}],
        }

    monkeypatch.setattr(workflow, "browse_norm_catalog", catalog)
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Окраска потолков", "unit": "м2", "quantity": 3.2}],
        candidate_limit=8,
    )

    first = session.execute(
        "browse_norm_catalog", {"items": [{"work_id": "w1"}]}, turn=1,
    )
    repeated = session.execute(
        "browse_norm_catalog", {"items": [{"work_id": "w1"}]}, turn=2,
    )
    selected = session.execute(
        "browse_norm_catalog",
        {"items": [{"work_id": "w1", "family": "ГЭСН", "collection": "15"}]},
        turn=3,
    )

    assert calls == 2
    assert first["rows"][0]["level"] == "family"
    assert repeated["rows"][0]["level"] == "already_seen"
    assert repeated["rows"][0]["items"] == []
    assert selected["rows"][0] == {
        "work_id": "w1",
        "ok": True,
        "level": "table",
        "filters": {"family": "ГЭСН", "collection": "15", "table": ""},
        "items": [{
            "key": "15-04-001",
            "norm_count": 7,
            "resource_count": 30,
            "source_example": "Таблица ГЭСН 15-04-001",
        }],
        "next_action": (
            "choose a family, collection and official table; then call "
            "search_norms_batch with table_codes to receive every row of that table"
        ),
    }


def test_search_uses_model_selected_collection_and_shows_scope(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    calls = []

    def browse(queries, **kwargs):
        calls.append({"queries": queries, **kwargs})
        collection = (kwargs.get("collections") or [""])[0]
        return {
            query: {
                "backend": "typed_sqlite_fts",
                "cards": [{
                    "norm_code": f"ГЭСН{collection}-04-001-01",
                    "norm_key": f"ГЭСН:{collection}-04-001-01",
                    "edition": "ФСНБ-2022",
                    "base_type": "ГЭСН",
                    "title": "Окраска потолков",
                    "measure_unit": "100 м2",
                    "work_steps": ["Окраска подготовленной поверхности"],
                    "resource_count": 2,
                    "resource_kinds": {"labor": 1, "material": 1},
                    "resource_preview": [{
                        "kind": "material", "code": "01.7", "name": "Краска", "unit": "кг",
                    }],
                    "source_ref": f"Сборник {collection}. Область модели / Раздел 1",
                }],
            }
            for query in queries
        }

    monkeypatch.setattr(workflow, "browse_norms_many", browse)
    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Окраска потолков", "unit": "м2", "quantity": 3.2}],
        candidate_limit=8,
    )

    result = session.execute(
        "search_norms_batch",
        {"items": [{
            "work_id": "w1",
            "query": "окраска потолков водоэмульсионной краской",
            "search_intent": "fsnb_technology",
            "scope_mode": "scoped",
            "base_types": ["ГЭСН"],
            "collections": ["15"],
        }]},
        turn=2,
    )

    assert calls[0]["base_types"] == ["ГЭСН"]
    assert calls[0]["collections"] == ["15"]
    candidate = result["rows"][0]["candidates"][0]
    assert candidate["norm_code"].startswith("ГЭСН15-")
    assert candidate["base_type"] == "ГЭСН"
    assert candidate["collection"] == "15"
    assert candidate["edition"] == "ФСНБ-2022"
    assert candidate["unit_compatible"] is True
    assert candidate["source_ref"].startswith("Сборник 15.")
    assert candidate["work_steps"] == ["Окраска подготовленной поверхности"]
    assert candidate["resource_kinds"] == {"labor": 1, "material": 1}
    assert candidate["resource_preview"][0]["name"] == "Краска"
    assert candidate["matched_query"] == "окраска потолков водоэмульсионной краской"
    assert result["rows"][0]["search_intent"] == "fsnb_technology"
    assert result["rows"][0]["scope_plan"]["schema"] == "smeta_scope_plan_v1"
    assert result["rows"][0]["scope_plan"]["scope_mode"] == "scoped"
    assert result["rows"][0]["scope_plan"]["explicit_scope_mode"] is True
    assert result["rows"][0]["filters"]["collections"] == ["15"]
    assert result["rows"][0]["retrieval_backend"] == "typed_sqlite_fts"
    assert session.query_trace[0]["filters"] == {
        "base_types": ["ГЭСН"], "collections": ["15"], "table_codes": [],
    }
    assert session.query_trace[0]["candidate_codes"] == ["ГЭСН15-04-001-01"]


def test_search_selected_table_returns_complete_menu_and_reranks_other_batches_by_default(
    monkeypatch,
):
    from proxy.smeta_core import document_workflow as workflow

    calls = []
    cards = [
        {
            "norm_code": f"ГЭСНм08-02-001-{index:02d}",
            "norm_key": f"ГЭСНм:08-02-001-{index:02d}",
            "base_type": "ГЭСНм",
            "bare_code": f"08-02-001-{index:02d}",
            "title": f"Вариант {index}",
            "measure_unit": "шт",
        }
        for index in range(1, 7)
    ]

    def browse(queries, **kwargs):
        calls.append({"queries": queries, **kwargs})
        return {
            query: {
                "backend": "official_table_listing",
                "cards": cards,
                "retrieval_trace": {
                    "complete_table": True,
                    "rerank_status": "not_needed_table_listing",
                },
            }
            for query in queries
        }

    monkeypatch.setattr(workflow, "browse_norms_many", browse)
    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Монтаж блока", "unit": "шт", "quantity": 1}],
        candidate_limit=2,
    )

    result = session.execute(
        "search_norms_batch",
        {"items": [{
            "work_id": "w1",
            "query": "варианты выбранной таблицы",
            "search_intent": "fsnb_technology",
            "scope_mode": "scoped",
            "base_types": ["ГЭСНм"],
            "collections": ["08"],
            "table_codes": ["08-02-001"],
        }]},
        turn=2,
    )

    assert calls[0]["table_codes"] == ["08-02-001"]
    assert calls[0]["rerank"] is True
    assert [item["norm_code"] for item in result["rows"][0]["candidates"]] == [
        card["norm_code"] for card in cards
    ]
    assert result["rows"][0]["page_size"] == len(cards)
    assert result["rows"][0]["has_more"] is False
    assert result["rows"][0]["filters"]["table_codes"] == ["08-02-001"]


def test_explicit_scope_plan_rejects_contradictory_transport_without_search(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    calls = []
    monkeypatch.setattr(
        workflow,
        "browse_norms_many",
        lambda queries, **kwargs: calls.append((queries, kwargs)) or {},
    )
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Монтаж блока", "unit": "шт", "quantity": 1}],
        candidate_limit=8,
    )

    missing_scope = session.execute(
        "search_norms_batch",
        {"items": [{
            "work_id": "w1",
            "query": "монтаж блока",
            "search_intent": "fsnb_technology",
            "scope_mode": "scoped",
        }]},
        turn=1,
    )
    filtered_global = session.execute(
        "search_norms_batch",
        {"items": [{
            "work_id": "w1",
            "query": "монтаж блока",
            "search_intent": "fsnb_technology",
            "scope_mode": "global",
            "base_types": ["ГЭСНм"],
            "collections": ["10"],
        }]},
        turn=2,
    )

    assert calls == []
    assert missing_scope["rows"][0]["error"] == "invalid model scope plan"
    assert "requires model-selected" in missing_scope["rows"][0]["details"][0]
    assert filtered_global["rows"][0]["error"] == "invalid model scope plan"
    assert "cannot contain" in filtered_global["rows"][0]["details"][0]


def test_mapping_transport_does_not_rewrite_model_decision():
    from proxy.smeta_core.document_workflow import _normalize_mapping_row_transport

    decision = {
        "selection_kind": "exact",
        "applicability": "close_analog",
        "analog_limitations": ["материал заменить"],
        "resource_actions": [{"action": "replace", "basis_ref": "card:material"}],
    }

    assert _normalize_mapping_row_transport(decision) == decision


def test_terminal_rejects_bind_without_complete_technology_evidence():
    from proxy.smeta_core import document_workflow as workflow

    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Окраска потолков", "unit": "м2", "quantity": 3.2}],
        candidate_limit=8,
    )
    result = session.execute(
        "submit_lsr_mapping",
        {"rows": [{
            "work_id": "w1",
            "decision": "bind",
            "norm_code": "ГЭСН15-04-026-09",
            "selection_kind": "exact",
            "applicability": "exact",
            "technology_check": {},
            "reason": "совпало название",
        }]},
        turn=1,
    )

    assert result["ok"] is False
    assert result["errors"][0]["error"] == "incomplete bind evidence"
    assert "technology_check.matched_operations must be an array" in result["errors"][0]["details"]


def test_terminal_requires_model_owned_comparison_for_opened_alternatives(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    codes = ["ГЭСН15-01-001-01", "ГЭСН15-01-001-02"]
    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "typed_sqlite_fts", "cards": [
            {"norm_code": code, "title": f"Кандидат {index}", "measure_unit": "м2"}
            for index, code in enumerate(codes, 1)
        ]} for query in queries
    })
    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda code, **_kwargs: {
        "name": code, "unit": "м2", "work_steps": ["Окраска"], "resources": [],
    })
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Окраска", "unit": "м2", "quantity": 10}],
        candidate_limit=4,
    )
    session.execute(
        "search_norms_batch",
        {"items": [{"work_id": "w1", "query": "окраска", "search_intent": "source_literal"}]},
        turn=1,
    )
    session.execute(
        "read_norms_batch",
        {"items": [{"work_id": "w1", "norm_code": code} for code in codes]},
        turn=2,
    )
    base = {
        "work_id": "w1", "decision": "bind", "norm_code": codes[0],
        "selection_kind": "exact", "applicability": "exact", "analog_limitations": [],
        "technology_check": _technology_check(), "reason": "первый кандидат подходит",
    }

    incomplete = session.execute(
        "submit_lsr_mapping",
        {"rows": [{**base, "candidate_evaluations": _candidate_evaluations(codes[0])}]},
        turn=3,
    )

    assert incomplete["ok"] is False
    assert "compare at least one" in " ".join(incomplete["errors"][0]["details"])

    comparisons = [
        *_candidate_evaluations(codes[0]),
        {
            **_candidate_evaluations(codes[1], decision="rejected")[0],
            "operation_match": "partial",
            "scope_match": "partial",
            "reason": "вторая карточка покрывает только часть операции",
        },
    ]
    accepted = session.execute(
        "submit_lsr_mapping",
        {"rows": [{**base, "candidate_evaluations": comparisons}]},
        turn=4,
    )

    assert accepted == {"ok": True, "rows": 1}
    assert session.accepted_rows["w1"]["candidate_evaluations"] == comparisons


def test_candidate_comparison_tolerates_only_semantically_identical_duplicates():
    from proxy.smeta_core import document_workflow as workflow

    codes = ["ГЭСН15-01-001-01", "ГЭСН15-01-001-02"]
    cards = {code: {"norm_code": code} for code in codes}
    selected = _candidate_evaluations(codes[0])[0]
    rejected = _candidate_evaluations(codes[1], decision="rejected")[0]
    item = {
        "norm_code": codes[0],
        "candidate_evaluations": [
            selected,
            rejected,
            {**selected, "reason": "то же сравнение повторно сериализовано моделью"},
        ],
    }

    assert workflow._candidate_evaluation_errors(
        item, candidates_for_work=cards, opened_for_work=cards,
    ) == []

    conflicting = {
        **item,
        "candidate_evaluations": [
            *item["candidate_evaluations"],
            {**selected, "decision": "rejected"},
        ],
    }
    errors = workflow._candidate_evaluation_errors(
        conflicting, candidates_for_work=cards, opened_for_work=cards,
    )
    assert any("conflicts with an earlier evaluation" in error for error in errors)


def test_read_norm_resources_are_not_truncated_at_thirty(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    code = "ГЭСН15-01-001-01"
    resources = [
        {"code": f"R-{index:02d}", "name": f"Ресурс {index}", "unit": "кг", "kind": "material", "per_unit": 1}
        for index in range(35)
    ]
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "key": "ГЭСН:15-01-001-01", "base_type": "ГЭСН", "name": "Работа", "unit": "м2",
        "work_steps": ["Работа"], "resources": resources,
    })
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Работа", "unit": "м2", "quantity": 1}],
        candidate_limit=4,
    )
    session.candidates["w1"][code] = {
        "norm_code": code, "norm_key": "ГЭСН:15-01-001-01", "base_type": "ГЭСН",
    }

    result = session.execute(
        "read_norms_batch",
        {"items": [{"work_id": "w1", "norm_code": code, "include_resources": True}]},
        turn=1,
    )

    card = result["rows"][0]["norms"][0]
    assert card["resource_count"] == 35
    assert len(card["resources"]) == 35


def test_batch_agent_default_keeps_fifty_rows_in_one_model_conversation(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })

    rows = [
        {"work_id": f"w{index:02d}", "title": f"Работа {index}", "unit": "шт", "quantity": index}
        for index in range(1, 51)
    ]
    captured = []

    calls = 0

    def exchange(messages, tools):
        nonlocal calls
        calls += 1
        payload = json.loads(messages[1]["content"])
        captured.append({
            "payload": payload,
            "tools": [(item.get("function") or {}).get("name") for item in tools],
        })
        if calls == 1:
            return {"tool_calls": [_native_call(
                "search", "search_norms_batch",
                items=[{
                    "work_id": row["work_id"],
                    "queries": [f"{row['title']} исходно", f"{row['title']} ФСНБ"],
                } for row in payload["work_items"]],
            )]}
        return {"tool_calls": [_native_call(
            "submit", "submit_lsr_mapping", rows=[{
                "work_id": row["work_id"], "decision": "unbound", "reason": "модель не выбрала норму",
                "unbound_evidence": _unbound_evidence(
                    queries=[f"{row['title']} исходно", f"{row['title']} ФСНБ"],
                ),
            } for row in payload["work_items"]],
        )]}

    result = workflow._run_native_norm_agent(
        rows,
        exchange,
        candidate_limit=8,
        max_turns=2,
        user_request="Собери ЛСР по всем строкам",
    )

    assert [len(item["payload"]["work_items"]) for item in captured] == [50, 50]
    assert "all_source_rows_context" not in captured[0]["payload"]
    assert captured[0]["payload"]["user_request"] == "Собери ЛСР по всем строкам"
    assert captured[0]["tools"] == [
        "browse_norm_catalog", "search_norms_batch", "read_norms_batch",
    ]
    assert len(result["selections"]) == 50
    assert result["agent_trace"]["turns"] == 2
    assert all(item["review_status"] == "model_batch_unbound" for item in result["selections"].values())


def test_batch_agent_zero_batch_size_gives_model_the_whole_vor(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })

    rows = [
        {"work_id": f"w{index}", "title": f"Работа {index}", "unit": "шт", "quantity": 1}
        for index in range(1, 20)
    ]
    payloads = []

    calls = 0

    def exchange(messages, _tools):
        nonlocal calls
        calls += 1
        payload = json.loads(messages[1]["content"])
        payloads.append(payload)
        if calls == 1:
            return {"tool_calls": [_native_call(
                "search", "search_norms_batch", items=[{
                    "work_id": row["work_id"],
                    "queries": [f"{row['title']} исходно", f"{row['title']} ФСНБ"],
                } for row in payload["work_items"]],
            )]}
        return {"tool_calls": [_native_call(
            "submit", "submit_lsr_mapping",
            rows=[
                {
                    "work_id": row["work_id"], "decision": "unbound", "reason": "нет точной нормы",
                    "unbound_evidence": _unbound_evidence(
                        queries=[f"{row['title']} исходно", f"{row['title']} ФСНБ"],
                    ),
                }
                for row in payload["work_items"]
            ],
        )]}

    result = workflow._run_native_norm_agent(
        rows,
        exchange,
        candidate_limit=8,
        batch_size=0,
    )

    assert len(payloads) == 2
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
            "candidate_evaluations": _candidate_evaluations("ГЭСН01-01-001-01"),
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
    assert tool_sets[0] == [
        "browse_norm_catalog", "search_norms_batch", "read_norms_batch",
    ]
    assert tool_sets[1] == [
        "browse_norm_catalog", "search_norms_batch", "read_norms_batch",
    ]
    assert tool_sets[2] == [
        "browse_norm_catalog", "search_norms_batch", "read_norms_batch",
    ]


def test_batch_agent_preserves_batch_level_search_page_from_model(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": [
            {"norm_code": f"ГЭСН01-01-001-{index:02d}", "title": f"Кандидат {index}"}
            for index in range(1, 9)
        ]}
        for query in queries
    })
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "name": "Кандидат 5", "unit": "шт",
        "work_steps": ["Монтаж элемента"], "resources": [],
    })
    turns = iter([
        [_native_call(
            "search",
            "search_norms_batch",
            items=[{
                "work_id": "w1",
                "queries": ["монтаж элемента", "установка элемента ФСНБ"],
                "limit": 2,
            }],
            page="2",
        )],
        [_native_call(
            "read", "read_norms_batch",
            items=[{"work_id": "w1", "norm_codes": ["ГЭСН01-01-001-05"]}],
        )],
        [_native_call("submit", "submit_lsr_mapping", rows=[{
            "work_id": "w1", "decision": "unbound", "reason": "решение модели",
            "unbound_evidence": _unbound_evidence(
                queries=["монтаж элемента", "установка элемента ФСНБ"],
                opened=["ГЭСН01-01-001-05"],
            ),
        }])],
    ])

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Монтаж элемента", "unit": "шт", "quantity": 1}],
        lambda _messages, _tools: {"tool_calls": next(turns)},
        candidate_limit=6,
        max_turns=3,
    )

    search_result = result["model_trace"][0]["tool_results"][0]["result"]["rows"][0]
    assert search_result["page"] == 2
    assert [card["norm_code"] for card in search_result["candidates"]] == [
        "ГЭСН01-01-001-05", "ГЭСН01-01-001-06",
    ]


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
            "analog_limitations": [],
            "candidate_evaluations": _candidate_evaluations("ГЭСН67-01-003-01"),
            "technology_check": check,
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
            "analog_limitations": [],
            "candidate_evaluations": _candidate_evaluations("ГЭСН67-01-003-01"),
            "technology_check": _technology_check(),
            "reason": "состав работ совпадает",
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
            "analog_limitations": [],
            "candidate_evaluations": _candidate_evaluations("ГЭСН67-01-003-01"),
            "technology_check": _technology_check(),
            "reason": "состав работ совпадает",
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


def test_batch_agent_preserves_unopened_model_norm_as_row_level_provenance_blocker(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "typed_sqlite_fts", "cards": []} for query in queries
    })

    turns = iter([
            [_native_call("bad", "submit_lsr_mapping", rows=[{
                "work_id": "w1", "decision": "bind", "norm_code": "ГЭСН01-01-999-99",
                "selection_kind": "exact", "applicability": "exact",
                "analog_limitations": [],
                "candidate_evaluations": _candidate_evaluations("ГЭСН01-01-999-99"),
                "technology_check": _technology_check(),
                "reason": "не открыта",
            }])],
        [_native_call("search", "search_norms_batch", items=[{
            "work_id": "w1", "queries": ["работа исходно", "работа ФСНБ"],
        }])],
        [_native_call("safe", "submit_lsr_mapping", rows=[{
            "work_id": "w1", "decision": "unbound", "reason": "нет защищаемой нормы",
            "unbound_evidence": _unbound_evidence(queries=["работа исходно", "работа ФСНБ"]),
        }])],
    ])

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        lambda _messages, _tools: {"tool_calls": next(turns)},
        candidate_limit=5,
        max_turns=3,
    )

    assert result["selections"]["w1"]["norm_code"] == "ГЭСН01-01-999-99"
    assert result["selections"]["w1"]["precalculation_blockers"][0]["code"] == "norm_card_not_opened"
    first_result = result["model_trace"][0]["tool_results"][0]["result"]
    assert first_result["ok"] is True


def test_batch_agent_rejects_unbound_without_two_traced_searches(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    turns = iter([
        [_native_call("search1", "search_norms_batch", items=[{
            "work_id": "w1", "queries": ["буквальный поиск"],
        }])],
        [_native_call("submit1", "submit_lsr_mapping", rows=[{
            "work_id": "w1", "decision": "unbound", "reason": "ничего не найдено",
            "unbound_evidence": _unbound_evidence(queries=["буквальный поиск"]),
        }])],
        [_native_call("search2", "search_norms_batch", items=[{
            "work_id": "w1", "queries": ["нормативная формулировка"],
        }])],
        [_native_call("submit2", "submit_lsr_mapping", rows=[{
            "work_id": "w1", "decision": "unbound", "reason": "защищаемой нормы нет",
            "unbound_evidence": _unbound_evidence(),
        }])],
    ])

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        lambda _messages, _tools: {"tool_calls": next(turns)},
        candidate_limit=5,
        max_turns=4,
    )

    first_submit = result["model_trace"][1]["tool_results"][0]["result"]
    assert first_submit["ok"] is False
    assert first_submit["errors"][0]["error"] == "invalid unbound_evidence"
    assert first_submit["errors"][0]["allowed_evidence"]["queries_used"] == ["буквальный поиск"]
    assert result["selections"]["w1"]["unbound_evidence"]["queries_used"] == [
        "буквальный поиск", "нормативная формулировка",
    ]


def test_unbound_provenance_is_aligned_only_to_real_tool_trace(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    turns = iter([
        [_native_call("search", "search_norms_batch", items=[{
            "work_id": "w1",
            "queries": ["реальный буквальный", "реальный ФСНБ"],
        }])],
        [_native_call("submit", "submit_lsr_mapping", rows=[{
            "work_id": "w1",
            "decision": "unbound",
            "reason": "защищаемой нормы нет",
            "unbound_evidence": {
                "queries_used": ["выдуманный поиск"],
                "opened_norm_codes": ["ГЭСН00-00-000-00"],
                "rejection_reasons": ["поиск не дал применимой карточки"],
                "coverage_checked": "покрытие соседней строкой не подтверждено",
            },
        }])],
    ])

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        lambda _messages, _tools: {"tool_calls": next(turns)},
        candidate_limit=5,
        max_turns=2,
    )

    evidence = result["selections"]["w1"]["unbound_evidence"]
    assert evidence["queries_used"] == ["реальный буквальный", "реальный ФСНБ"]
    assert evidence["opened_norm_codes"] == []
    assert "выдуманный поиск" not in json.dumps(result["query_trace"], ensure_ascii=False)


def test_forced_mapping_gets_one_bounded_schema_repair(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    mapping_calls = {"count": 0}

    def exchange(_messages, _tools):
        return {"tool_calls": [_native_call("search", "search_norms_batch", items=[{
            "work_id": "w1",
            "queries": ["буквальный поиск", "нормативный поиск"],
        }])]}

    def mapping_exchange(_messages, _schema):
        mapping_calls["count"] += 1
        evidence = {
            "queries_used": ["буквальный поиск", "нормативный поиск"],
            "opened_norm_codes": [],
            "rejection_reasons": ["применимая норма не найдена"],
        }
        if mapping_calls["count"] > 1:
            evidence["coverage_checked"] = "покрытие другими строками не подтверждено"
        return {"rows": [{
            "work_id": "w1",
            "decision": "unbound",
            "reason": "защищаемой нормы нет",
            "unbound_evidence": evidence,
        }]}

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        exchange,
        mapping_exchange=mapping_exchange,
        candidate_limit=5,
        max_turns=1,
    )

    assert mapping_calls["count"] == 2
    assert result["selections"]["w1"]["review_status"] == "model_batch_unbound"
    assert "search-preflight-harness" not in json.dumps(
        result["model_trace"],
        ensure_ascii=False,
    )


def test_forced_mapping_serializes_large_result_in_transport_chunks(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setenv("LES_SMETA_DOCUMENT_MAPPING_CHUNK", "8")
    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    rows = [
        {"work_id": f"w{index}", "title": f"Работа {index}", "unit": "шт", "quantity": 1}
        for index in range(1, 10)
    ]

    def exchange(_messages, _tools):
        return {"tool_calls": [_native_call(
            "search",
            "search_norms_batch",
            items=[
                {
                    "work_id": row["work_id"],
                    "queries": [
                        f"{row['title']} буквально",
                        f"{row['title']} нормативно",
                    ],
                }
                for row in rows
            ],
        )]}

    mapping_batches = []

    def mapping_exchange(_messages, schema):
        work_ids = schema["properties"]["rows"]["items"]["properties"]["work_id"]["enum"]
        mapping_batches.append(list(work_ids))
        return {"rows": [
            {
                "work_id": work_id,
                "decision": "unbound",
                "reason": "модель не выбрала норму",
                "unbound_evidence": _unbound_evidence(
                    queries=[
                        f"Работа {work_id[1:]} буквально",
                        f"Работа {work_id[1:]} нормативно",
                    ],
                ),
            }
            for work_id in work_ids
        ]}

    result = workflow._run_native_norm_agent(
        rows,
        exchange,
        mapping_exchange=mapping_exchange,
        candidate_limit=5,
        max_turns=1,
    )

    assert mapping_batches == [
        [f"w{index}" for index in range(1, 9)],
        ["w9"],
    ]
    assert set(result["selections"]) == {f"w{index}" for index in range(1, 10)}


def test_mapping_timeout_stops_without_identical_retry_and_saves_checkpoint(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    mapping_calls = 0
    checkpoints = []

    def exchange(_messages, _tools):
        return {"tool_calls": [_native_call(
            "search",
            "search_norms_batch",
            items=[{
                "work_id": "w1",
                "queries": ["буквальный поиск", "нормативный поиск"],
            }],
        )]}

    def mapping_exchange(_messages, _schema):
        nonlocal mapping_calls
        mapping_calls += 1
        raise TimeoutError("structured mapping timed out")

    with pytest.raises(workflow.MappingTransportTimeout):
        workflow._run_native_norm_agent(
            [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
            exchange,
            mapping_exchange=mapping_exchange,
            candidate_limit=5,
            max_turns=1,
            checkpoint=checkpoints.append,
        )

    assert mapping_calls == 1
    assert checkpoints
    assert checkpoints[-1]["incomplete"] is True
    assert checkpoints[-1]["incomplete_blocker"]["code"] == "structured_mapping_timeout"


def test_batch_agent_preserves_model_norm_and_leaves_unit_check_to_calculation(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    bad_code = "ГЭСН01-01-001-01"
    good_code = "ГЭСН01-01-001-02"
    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": [
            {"norm_code": bad_code, "title": "Прокладка линии", "measure_unit": "100 м"},
            {"norm_code": good_code, "title": "Установка элемента", "measure_unit": "шт"},
        ]} for query in queries
    })
    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda code, **_kwargs: {
        "name": "Прокладка линии" if code == bad_code else "Установка элемента",
        "unit": "100 м" if code == bad_code else "шт",
        "work_steps": ["Монтаж"],
        "resources": [],
    })
    turns = iter([
        [_native_call("search", "search_norms_batch", items=[{
            "work_id": "w1", "queries": ["монтаж элемента"],
        }])],
        [_native_call("read-bad", "read_norms_batch", items=[{
            "work_id": "w1", "norm_codes": [bad_code, good_code],
        }])],
        [_native_call("submit-bad", "submit_lsr_mapping", rows=[{
            "work_id": "w1", "decision": "bind", "norm_code": bad_code,
            "selection_kind": "analog", "applicability": "close_analog",
            "analog_limitations": ["измеритель требует проверки"],
            "candidate_evaluations": [
                *_candidate_evaluations(bad_code),
                {
                    **_candidate_evaluations(good_code, decision="rejected")[0],
                    "operation_match": "partial",
                    "reason": "модель предпочла другой открытый измеритель",
                },
            ],
            "technology_check": _technology_check(conclusion="applicable_with_limitations"),
            "reason": "модель пробует аналог",
        }])],
        [_native_call("read-good", "read_norms_batch", items=[{
            "work_id": "w1", "norm_codes": [good_code],
        }])],
        [_native_call("submit-good", "submit_lsr_mapping", rows=[{
            "work_id": "w1", "decision": "bind", "norm_code": good_code,
            "selection_kind": "exact", "applicability": "exact", "analog_limitations": [],
            "candidate_evaluations": _candidate_evaluations(good_code),
            "technology_check": _technology_check(), "reason": "единица и операция совпадают",
        }])],
    ])

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Монтаж элемента", "unit": "шт", "quantity": 8}],
        lambda _messages, _tools: {"tool_calls": next(turns)},
        candidate_limit=5,
        max_turns=5,
    )

    submitted = result["model_trace"][2]["tool_results"][0]["result"]
    assert submitted["ok"] is True
    assert result["selections"]["w1"]["norm_code"] == bad_code


def test_batch_agent_does_not_force_extra_read_after_model_submits_norm(monkeypatch):
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

    turns = iter([
        [_native_call("early", "submit_lsr_mapping", rows=[{
            "work_id": "w1", "decision": "bind", "norm_code": selected_code,
            "selection_kind": "exact", "applicability": "exact", "analog_limitations": [],
            "candidate_evaluations": _candidate_evaluations(selected_code),
            "technology_check": _technology_check(), "reason": "модель выбрала точную норму",
        }])],
        [_native_call("search", "search_norms_batch", items=[{
            "work_id": "w1", "queries": ["работа"],
        }])],
        [_native_call("read", "read_norms_batch", items=[{
            "work_id": "w1", "norm_codes": [selected_code],
        }])],
        [_native_call("submit", "submit_lsr_mapping", rows=[{
                "work_id": "w1", "decision": "bind", "norm_code": selected_code,
                "selection_kind": "exact", "applicability": "exact",
                "analog_limitations": [],
                "candidate_evaluations": _candidate_evaluations(selected_code),
                "technology_check": _technology_check(),
                "reason": "модель выбрала точную норму",
        }])],
    ])

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        lambda _messages, _tools: {"tool_calls": next(turns)},
        candidate_limit=5,
        max_turns=4,
    )

    assert result["selections"]["w1"]["norm_code"] == selected_code
    first = result["model_trace"][0]["tool_results"][0]["result"]
    assert first["ok"] is True
    assert result["selections"]["w1"]["precalculation_blockers"][0]["code"] == "norm_card_not_opened"


def test_batch_agent_preserves_each_model_row_without_rewriting_it(monkeypatch):
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
            {"work_id": "w2", "queries": ["работа 2", "работа 2 ФСНБ"]},
        ])],
        [_native_call("read", "read_norms_batch", items=[
            {"work_id": "w1", "norm_codes": ["ГЭСН01-01-001-01"]},
            {"work_id": "w2", "norm_codes": ["ГЭСН01-01-001-01"]},
        ])],
        [_native_call("submit1", "submit_lsr_mapping", rows=[
            {"work_id": "w1", "decision": "bind", "norm_code": "ГЭСН01-01-001-01",
             "selection_kind": "exact", "applicability": "exact", "analog_limitations": [],
             "candidate_evaluations": _candidate_evaluations("ГЭСН01-01-001-01"),
             "technology_check": _technology_check(), "reason": "совпадает"},
            {"work_id": "w2", "decision": "bind", "norm_code": "ГЭСН01-01-999-99",
             "selection_kind": "exact", "applicability": "exact", "analog_limitations": [],
             "candidate_evaluations": _candidate_evaluations("ГЭСН01-01-999-99"),
             "technology_check": _technology_check(), "reason": "не открыта"},
        ])],
        [_native_call("submit2", "submit_lsr_mapping", rows=[{
            "work_id": "w2", "decision": "unbound", "reason": "точной нормы нет",
            "unbound_evidence": _unbound_evidence(
                queries=["работа 2", "работа 2 ФСНБ"], opened=["ГЭСН01-01-001-01"],
            ),
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
    assert result["selections"]["w2"]["norm_code"] == "ГЭСН01-01-999-99"
    submitted = result["model_trace"][2]["tool_results"][0]["result"]
    assert submitted == {"ok": True, "rows": 2}


def test_batch_agent_accepts_clean_incremental_row_submissions(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    turns = iter([
        [_native_call("search", "search_norms_batch", items=[
            {"work_id": "w1", "queries": ["работа 1", "работа 1 ФСНБ"]},
            {"work_id": "w2", "queries": ["работа 2", "работа 2 ФСНБ"]},
        ])],
        [_native_call("submit1", "submit_lsr_mapping", rows=[{
            "work_id": "w1", "decision": "unbound", "reason": "нет точной нормы",
            "unbound_evidence": _unbound_evidence(queries=["работа 1", "работа 1 ФСНБ"]),
        }])],
        [_native_call("submit2", "submit_lsr_mapping", rows=[{
            "work_id": "w2", "decision": "unbound", "reason": "нет точной нормы",
            "unbound_evidence": _unbound_evidence(queries=["работа 2", "работа 2 ФСНБ"]),
        }])],
    ])

    result = workflow._run_native_norm_agent(
        [
            {"work_id": "w1", "title": "Работа 1", "unit": "шт", "quantity": 1},
            {"work_id": "w2", "title": "Работа 2", "unit": "шт", "quantity": 1},
        ],
        lambda _messages, _tools: {"tool_calls": next(turns)},
        candidate_limit=3,
        max_turns=3,
    )

    assert list(result["selections"]) == ["w1", "w2"]
    first_submit = result["model_trace"][1]["tool_results"][0]["result"]
    assert first_submit == {
        "ok": True,
        "complete": False,
        "accepted_work_ids": ["w1"],
        "remaining_work_ids": ["w2"],
    }


def test_batch_agent_has_configurable_transport_turn_budget():
    from proxy.smeta_core import document_workflow as workflow

    calls = 0

    def exchange(_messages, _tools):
        nonlocal calls
        calls += 1
        return {"tool_calls": [_native_call(f"unknown-{calls}", "unknown_tool", sequence=calls)]}

    with pytest.raises(RuntimeError, match="within 2 model turns"):
        workflow._run_native_norm_agent(
            [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
            exchange,
            candidate_limit=5,
            max_turns=2,
        )
    assert calls == 2


def test_batch_agent_stops_on_identical_deterministic_tool_call():
    from proxy.smeta_core import document_workflow as workflow

    calls = 0

    def exchange(_messages, _tools):
        nonlocal calls
        calls += 1
        return {"tool_calls": [_native_call(
            f"search-{calls}",
            "search_norms_batch",
            items=[{"work_id": "w1", "queries": ["тот же запрос"], "page": 1}],
        )]}

    with pytest.raises(RuntimeError, match="repeated the same deterministic tool call"):
        workflow._run_native_norm_agent(
            [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
            exchange,
            candidate_limit=5,
        )

    assert calls == 2


def test_batch_agent_does_not_coerce_model_after_prose(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    calls = 0

    def exchange(_messages, _tools):
        nonlocal calls
        calls += 1
        return {"content": "Поиск завершён, точной нормы нет.", "_les_done_reason": "stop"}

    with pytest.raises(RuntimeError, match="model_text=Поиск завершён, точной нормы нет"):
        workflow._run_native_norm_agent(
            [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
            exchange,
            candidate_limit=5,
            max_turns=2,
        )

    assert calls == 1


def test_batch_agent_serializes_same_model_decision_after_prose(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })

    seen = {}

    def mapping_exchange(messages, schema):
        seen["messages"] = messages
        seen["schema"] = schema
        return {"rows": [{
            "work_id": "w1",
            "decision": "unbound",
            "reason": "модель не нашла достаточного основания",
            "unbound_evidence": _unbound_evidence(),
        }], "_les_model": "qwen3.5:9b"}

    calls = 0

    def exchange(_messages, _tools):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"tool_calls": [_native_call(
                "search", "search_norms_batch", items=[{
                    "work_id": "w1",
                    "queries": ["буквальный поиск", "нормативная формулировка"],
                }],
            )]}
        return {
            "content": "Поиск завершён.",
            "thinking": "Сопоставил свидетельства.",
            "_les_done_reason": "stop",
        }

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        exchange,
        mapping_exchange=mapping_exchange,
        candidate_limit=5,
    )

    assert result["selections"]["w1"]["reason"] == "модель не нашла достаточного основания"
    assert seen["schema"]["properties"]["rows"]["items"]["properties"]["work_id"]["enum"] == ["w1"]
    assert any(
        message.get("thinking") == "Сопоставил свидетельства."
        for message in seen["messages"]
    )
    assert any(message.get("role") == "user" and "output_schema" in str(message.get("content"))
               for message in seen["messages"])
    assert any(item.get("transport") == "structured_mapping" for item in result["model_trace"])


def test_batch_agent_serializes_after_repeated_tool_feedback(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    calls = 0
    mapping_calls = 0

    def exchange(messages, _tools):
        nonlocal calls
        calls += 1
        if calls == 3:
            assert "identical deterministic request" in messages[-1]["content"]
        return {"tool_calls": [_native_call(
            f"search-{calls}",
            "search_norms_batch",
            items=[{
                "work_id": "w1",
                "queries": ["буквальный поиск", "нормативная формулировка"],
                "page": 1,
            }],
        )]}

    def mapping_exchange(_messages, _schema):
        nonlocal mapping_calls
        mapping_calls += 1
        return {"rows": [{
            "work_id": "w1", "decision": "unbound", "reason": "решение модели",
            "unbound_evidence": _unbound_evidence(),
        }]}

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        exchange,
        mapping_exchange=mapping_exchange,
        candidate_limit=5,
    )

    assert calls == 3
    assert mapping_calls == 1
    assert result["selections"]["w1"]["reason"] == "решение модели"


def test_batch_agent_structures_model_decision_at_tool_turn_budget(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    tool_turns = 0

    def exchange(_messages, _tools):
        nonlocal tool_turns
        tool_turns += 1
        return {"tool_calls": [_native_call(
            f"search-{tool_turns}", "search_norms_batch",
            items=[{"work_id": "w1", "query": f"вариант {tool_turns}"}],
        )]}

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        exchange,
        mapping_exchange=lambda _messages, _schema: {"rows": [{
            "work_id": "w1", "decision": "unbound", "reason": "решение модели по evidence",
            "unbound_evidence": _unbound_evidence(queries=["вариант 1", "вариант 2"]),
        }]},
        candidate_limit=5,
        max_turns=2,
    )

    assert tool_turns == 2
    assert result["selections"]["w1"]["reason"] == "решение модели по evidence"
    assert result["agent_trace"]["turns"] == 3
    assert result["agent_trace"]["context_metrics"][-1]["structured_mapping"] is True


def test_batch_agent_reports_model_wait_before_and_after_each_turn(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })

    events = []
    calls = 0

    def exchange(_messages, _tools):
        nonlocal calls
        calls += 1
        assert {str((tool.get("function") or {}).get("name") or "") for tool in _tools} == {
            "browse_norm_catalog", "search_norms_batch", "read_norms_batch",
        }
        if calls == 1:
            return {"tool_calls": [_native_call(
                "search", "search_norms_batch", items=[{
                    "work_id": "w1", "queries": ["работа исходно", "работа ФСНБ"],
                }],
            )]}
        return {"tool_calls": [_native_call(
            "submit", "submit_lsr_mapping", rows=[{
                "work_id": "w1", "decision": "unbound", "reason": "нет точной нормы",
                "unbound_evidence": _unbound_evidence(queries=["работа исходно", "работа ФСНБ"]),
            }],
        )]}

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        exchange,
        candidate_limit=5,
        progress=events.append,
    )

    waits = [event for event in events if event.get("phase") == "model_wait"]
    assert [(event["status"], event["turn"]) for event in waits] == [
        ("started", 1), ("done", 1), ("started", 2), ("done", 2),
    ]
    assert result["selections"]["w1"]["norm_code"] == ""


def test_batch_agent_stops_repeated_empty_transport_submission_immediately():
    from proxy.smeta_core import document_workflow as workflow

    calls = 0

    def exchange(_messages, _tools):
        nonlocal calls
        calls += 1
        return {"tool_calls": [_native_call(
            f"submit-{calls}",
            "submit_lsr_mapping",
            rows=[],
        )]}

    with pytest.raises(RuntimeError, match="repeated the same deterministic tool call"):
        workflow._run_batch_norm_agent(
            [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
            exchange,
            candidate_limit=5,
        )

    assert calls == 2


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
    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    seen = {}
    calls = 0

    def exchange(messages, _tools):
        nonlocal calls
        calls += 1
        payload = json.loads(messages[1]["content"])
        seen.update({item["work_id"]: item for item in payload["work_items"]})
        if calls == 1:
            return {"tool_calls": [_native_call("search", "search_norms_batch", items=[{
                "work_id": item["work_id"],
                "queries": [f"{item['title']} исходно", f"{item['title']} ФСНБ"],
            } for item in payload["work_items"]])]}
        return {"tool_calls": [_native_call("submit", "submit_lsr_mapping", rows=[
            {
                "work_id": item["work_id"], "decision": "unbound", "reason": "нет нормы",
                "unbound_evidence": _unbound_evidence(
                    queries=[f"{item['title']} исходно", f"{item['title']} ФСНБ"],
                ),
            }
            for item in payload["work_items"]
        ])]}

    result = workflow.run_vor_pdf_workflow(
        "source.pdf", exchange=exchange, require_global_review=False,
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
    monkeypatch.setattr(
        norm_browser,
        "_rerank_cards",
        lambda _query, cards, limit: (cards[:limit], False, "pool_too_small"),
    )
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
