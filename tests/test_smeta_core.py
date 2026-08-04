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


def test_native_batch_resume_drops_completed_previous_batch_tool_session(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    rows = [
        {"work_id": "w1", "title": "Первая работа", "unit": "шт", "quantity": 1},
        {"work_id": "w2", "title": "Вторая работа", "unit": "шт", "quantity": 1},
    ]
    completed = {
        "norm_code": "",
        "reason": "решение w1",
        "review_status": "model_batch_unbound",
    }
    previous_session = workflow.SmetaNormToolSession(
        [rows[0]],
        candidate_limit=4,
        require_scoped_search=True,
    )
    seen = []

    def run_pending(work_rows, _exchange, **kwargs):
        seen.append((str(work_rows[0]["work_id"]), kwargs["resume_checkpoint"]))
        return {
            "selections": {
                "w2": {
                    "norm_code": "",
                    "reason": "решение w2",
                    "review_status": "model_batch_unbound",
                },
            },
            "opened_cards": {},
            "browse_trace": {},
            "query_trace": [],
            "catalog_trace": [],
            "model_trace": [],
            "valid_model_rows": 1,
            "agent_trace": {"engine": "test"},
        }

    monkeypatch.setattr(workflow, "_run_batch_norm_agent", run_pending)
    result = workflow._run_native_norm_agent(
        rows,
        lambda _messages, _tools: {},
        candidate_limit=4,
        max_turns=4,
        batch_size=1,
        resume_result={
            "selections": {"w1": completed},
            "opened_cards": {},
            "browse_trace": {},
            "query_trace": [],
            "catalog_trace": [],
            "model_trace": [],
            "resume_state": {
                "schema": "smeta_norm_agent_resume_v1",
                "tool_session": previous_session.checkpoint_state(),
            },
        },
        require_scoped_search=True,
    )

    assert seen == [("w2", None)]
    assert result["selections"] == {
        "w1": completed,
        "w2": {
            "norm_code": "",
            "reason": "решение w2",
            "review_status": "model_batch_unbound",
        },
    }


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
        "browse_norm_catalog",
        "reuse_norm_catalog_route",
        "search_norms_batch",
        "read_norms_batch",
        "submit_lsr_mapping",
    ]
    catalog_item = tools[0]["function"]["parameters"]["properties"]["items"]["items"]
    assert "table" in catalog_item["properties"]
    assert "scope_reason" in catalog_item["properties"]
    assert "confirm_scope" in catalog_item["properties"]
    assert "passport_evidence" in catalog_item["properties"]
    assert "alternative_collection" not in catalog_item["properties"]
    assert "alternative_evidence" not in catalog_item["properties"]
    assert "comparison_reason" not in catalog_item["properties"]
    assert catalog_item["properties"]["confidence"]["enum"] == ["low", "medium", "high"]
    assert "limit" not in catalog_item["properties"]
    search_item = tools[2]["function"]["parameters"]["properties"]["items"]["items"]
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
                "choose a family, collection, section and official table; then call "
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
                "backend": "typed_sqlite_fts+smeta_norm_qdrant_hybrid+bge_rerank_rrf",
                "retrieval_trace": {
                    "rag_candidates": 12,
                    "reranked": True,
                    "rerank_status": "ok",
                },
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
        }], "rerank": False},
        turn=2,
    )

    assert calls[0]["base_types"] == ["ГЭСН"]
    assert calls[0]["collections"] == ["15"]
    assert calls[0]["rerank"] is True
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
    assert result["rows"][0]["retrieval_backend"].endswith("+bge_rerank_rrf")
    assert result["rows"][0]["retrieval_policy"] == "native_rrf_then_rerank_required"
    assert result["rows"][0]["rerank_status"] == ["ok"]
    assert result["rows"][0]["reranked"] is True
    assert session.query_trace[0]["filters"] == {
        "base_types": ["ГЭСН"], "collections": ["15"], "table_codes": [],
    }
    assert session.query_trace[0]["candidate_codes"] == ["ГЭСН15-04-001-01"]
    assert session.query_trace[0]["retrieval_policy"] == "native_rrf_then_rerank_required"
    assert session.query_trace[0]["rerank_status"] == ["ok"]
    assert session.query_trace[0]["reranked"] is True


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


def test_rim_catalog_must_search_and_read_first_collection_before_expanding(
    monkeypatch,
):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(
        workflow,
        "browse_norm_catalog",
        lambda **kwargs: {
            "level": "table",
            "filters": {
                "family": "ГЭСНм",
                "collection": kwargs.get("collection") or "",
                "table": "",
            },
            "items": [{
                "key": f"{kwargs.get('collection')}-01-001",
                "norm_count": 3,
            }],
            "collection_passport": {
                "title": (
                    "Приборы и средства автоматизации"
                    if kwargs.get("collection") == "11"
                    else "Оборудование связи"
                ),
                "source_ref": f"ФСНБ-2022 · ГЭСНм, сборник {kwargs.get('collection')}",
                "representative_sections": [
                    (
                        "Раздел 1. Приборы"
                        if kwargs.get("collection") == "11"
                        else "Раздел 1. Оборудование связи"
                    )
                ],
            },
        },
    )
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Монтаж шкафа", "unit": "шт", "quantity": 1}],
        candidate_limit=8,
        require_scoped_search=True,
    )
    session.family_catalog_seen.add("w1")
    session.selected_base_types["w1"]["гэснм"] = {
        "family": "ГЭСНм",
        "reason": "Монтаж оборудования",
        "confidence": "high",
    }
    session.selected_collections["w1"].add(("гэснм", "10"))
    session.catalog_seen.add(("w1", "гэснм", "10", ""))
    select_second = {
        "items": [{
            "work_id": "w1",
            "family": "ГЭСНм",
            "collection": "11",
            "scope_reason": "Проверка соседнего сборника",
            "confidence": "medium",
        }]
    }

    before_search = session.execute("browse_norm_catalog", select_second, turn=2)

    assert before_search["rows"][0]["error"] == (
        "selected collection path must be completed before scope expansion"
    )
    assert session.selected_collections["w1"] == {("гэснм", "10")}

    session.query_trace.append({
        "work_id": "w1",
        "filters": {"base_types": ["ГЭСНм"], "collections": ["10"]},
        "candidate_codes": ["ГЭСНм10-01-001-01"],
    })
    before_read = session.execute("browse_norm_catalog", select_second, turn=3)

    assert before_read["rows"][0]["error"] == (
        "candidate cards must be read before scope expansion"
    )

    session.opened["w1"]["ГЭСНм10-01-001-01"] = {"norm_code": "ГЭСНм10-01-001-01"}
    after_read = session.execute("browse_norm_catalog", select_second, turn=4)

    assert after_read["rows"][0]["ok"] is True
    assert after_read["rows"][0]["level"] == "collection_previewed"
    assert ("гэснм", "11") not in session.selected_collections["w1"]

    confirmed = session.execute(
        "browse_norm_catalog",
        {
            "items": [{
                **select_second["items"][0],
                "confirm_scope": True,
                "passport_evidence": "Приборы и средства автоматизации",
            }]
        },
        turn=5,
    )

    assert confirmed["rows"][0]["ok"] is True
    assert confirmed["rows"][0]["level"] == "collection_selected"
    assert ("гэснм", "11") in session.selected_collections["w1"]


def test_rim_repeated_unconfirmed_collection_returns_exact_confirmation_hint(
    monkeypatch,
):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(
        workflow,
        "browse_norm_catalog",
        lambda **_kwargs: {
            "level": "table",
            "filters": {"family": "ГЭСНм", "collection": "08", "table": ""},
            "items": [{"key": "08-01-001", "norm_count": 1}],
            "collection_passport": {
                "title": "Электротехнические установки",
                "source_ref": "ФСНБ-2022 · ГЭСНм, сборник 08 «Электротехнические установки»",
                "representative_sections": ["Отдел 1. Распределительные устройства"],
            },
        },
    )
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Монтаж блока", "unit": "шт", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    session.family_catalog_seen.add("w1")
    session.selected_base_types["w1"]["гэснм"] = {
        "family": "ГЭСНм",
        "reason": "Монтаж оборудования",
        "confidence": "medium",
    }
    args = {"items": [{
        "work_id": "w1",
        "family": "ГЭСНм",
        "collection": "08",
        "scope_reason": "Проверка электротехнического сборника",
        "confidence": "medium",
    }]}

    preview = session.execute("browse_norm_catalog", args, turn=1)
    repeated = session.execute("browse_norm_catalog", args, turn=2)

    assert preview["rows"][0]["level"] == "collection_previewed"
    assert repeated["rows"][0]["ok"] is False
    assert repeated["rows"][0]["next_action"] == (
        "confirm_scope_or_preview_another_collection"
    )
    assert "Электротехнические установки" in repeated["rows"][0]["details"][1]


def test_rim_family_catalog_allows_distinct_model_authored_refinement_query(
    monkeypatch,
):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(
        workflow,
        "browse_norm_catalog",
        lambda **_kwargs: {
            "level": "collection",
            "filters": {"family": "ГЭСНм", "collection": "", "table": ""},
            "items": [
                {
                    "key": "08",
                    "title": "Электротехнические установки",
                    "norm_count": 100,
                    "resource_count": 500,
                    "source_ref": "ФСНБ-2022 · ГЭСНм 08",
                },
                {
                    "key": "10",
                    "title": "Оборудование связи",
                    "norm_count": 100,
                    "resource_count": 500,
                    "source_ref": "ФСНБ-2022 · ГЭСНм 10",
                },
            ],
        },
    )
    queries_seen = []

    def rank_collections(query, **_kwargs):
        queries_seen.append(query)
        return {
            "cards": [{
                "node_id": "catalog:collection:ГЭСНм:10",
                "parent_id": "catalog:family:ГЭСНм",
                "node_type": "collection",
                "cipher": "10",
                "title": "Оборудование связи",
            }],
            "retrieval_trace": {"rerank_status": "ok"},
        }

    monkeypatch.setattr(
        workflow,
        "rank_norm_catalog_collections",
        rank_collections,
    )
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Монтаж блока", "unit": "шт", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    session.family_catalog_seen.add("w1")
    session.selected_base_types["w1"]["гэснм"] = {
        "family": "ГЭСНм",
        "reason": "Монтаж оборудования связи",
        "confidence": "medium",
    }
    session.catalog_seen.add(("w1", "гэснм", "", ""))
    session.catalog_trace.append({
        "work_id": "w1",
        "level": "base_type_selected",
        "filters": {"family": "ГЭСНм", "collection": "", "table": ""},
        "catalog_query": "блок розеток",
    })
    family_node = {
        "node_id": "catalog:family:ГЭСНм",
        "parent_id": "catalog:root",
        "node_type": "family",
        "cipher": "ГЭСНм",
        "title": "Монтаж оборудования",
        "purpose": "Монтаж оборудования и его закрепление.",
    }
    session.catalog_node_registry["w1"][family_node["node_id"]] = family_node
    session.catalog_menus["w1"]["catalog:root"] = [family_node]

    refined = session.execute(
        "continue_norm_catalog",
        {"items": [{
            "work_id": "w1",
            "current_node_id": "catalog:root",
            "selected_node_id": family_node["node_id"],
            "evidence": [{
                "source_node_id": family_node["node_id"],
                "field": "purpose",
                "claim": "Монтаж оборудования.",
            }],
            "rejected_nodes": [],
            "work_features": {
                "domain": "связь",
                "system": "СКС",
                "equipment": "блок",
                "operation": "монтаж",
                "assembly_state": "factory_assembled",
                "installation_context": "в помещении",
                "unknowns": [],
            },
            "catalog_query": "оборудование связи",
            "confidence": "medium",
        }]},
        turn=2,
    )

    assert queries_seen == ["оборудование связи"]
    assert refined["rows"][0]["level"] == "collection"
    assert refined["rows"][0]["items"][0]["cipher"] == "10"


def test_family_continue_accepts_degraded_rerank_when_collection_menu_exists(
    monkeypatch,
):
    """Windows without cross-encoder must not stall family→collection forever."""
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(
        workflow,
        "rank_norm_catalog_collections",
        lambda query, **_kwargs: {
            "cards": [{
                "node_id": "catalog:collection:ГЭСНм:10",
                "parent_id": "catalog:family:ГЭСНм",
                "node_type": "collection",
                "cipher": "10",
                "title": "Оборудование связи",
            }],
            "retrieval_trace": {"rerank_status": "error:RuntimeError"},
        },
    )
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Монтаж шкафа", "unit": "шт", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    family_node = {
        "node_id": "catalog:family:ГЭСНм",
        "parent_id": "catalog:root",
        "node_type": "family",
        "cipher": "ГЭСНм",
        "title": "Монтаж оборудования",
        "purpose": "Монтаж оборудования и его закрепление.",
        "not_for": "строительные работы без монтажа оборудования",
    }
    session.catalog_node_registry["w1"][family_node["node_id"]] = family_node
    session.catalog_menus["w1"]["catalog:root"] = [family_node]
    session.catalog_current_nodes["w1"] = "catalog:root"

    result = session.execute(
        "continue_norm_catalog",
        {"items": [{
            "work_id": "w1",
            "current_node_id": "catalog:root",
            "selected_node_id": family_node["node_id"],
            "evidence": [{
                # Model often cites root; transport remaps to the selected child.
                "source_node_id": "catalog:root",
                "field": "purpose",
                "claim": "Монтаж оборудования.",
            }],
            "rejected_nodes": [],
            "work_features": {
                "domain": "связь",
                "system": "СКС",
                "equipment": "шкаф",
                "operation": "монтаж",
                "assembly_state": "factory_assembled",
                "installation_context": "в помещении",
                "unknowns": [],
            },
            "catalog_query": "оборудование связи",
            "confidence": "medium",
        }]},
        turn=1,
    )

    assert result["rows"][0]["ok"] is True, result["rows"][0]
    assert result["rows"][0]["level"] == "collection"
    assert result["rows"][0]["items"][0]["cipher"] == "10"


def test_catalog_menu_echo_is_rejected_with_decision_example(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Защитное укрытие", "unit": "м2", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    families = [
        {
            "node_id": f"catalog:family:{cipher}",
            "parent_id": "catalog:root",
            "node_type": "family",
            "cipher": cipher,
            "purpose": f"purpose {cipher}",
            "official_name": cipher,
        }
        for cipher in ("ГЭСН", "ГЭСНм", "ГЭСНр")
    ]
    session.catalog_menus["w1"]["catalog:root"] = families
    for node in families:
        session.catalog_node_registry["w1"][node["node_id"]] = node
    session.catalog_current_nodes["w1"] = "catalog:root"

    echoed = session.execute(
        "continue_norm_catalog",
        {"items": [dict(node) for node in families]},
        turn=1,
    )
    assert echoed["ok"] is False
    assert echoed["rows"][0]["error"] == "catalog menu echoed instead of a decision"
    assert '"items"' in echoed["rows"][0]["details"][2]
    assert "selected_node_id" in echoed["rows"][0]["details"][2]

    monkeypatch.setattr(
        workflow,
        "rank_norm_catalog_collections",
        lambda query, **_kwargs: {
            "cards": [{
                "node_id": "catalog:collection:ГЭСН:13",
                "parent_id": "catalog:family:ГЭСН",
                "node_type": "collection",
                "cipher": "13",
                "title": "Защита",
            }],
            "retrieval_trace": {"rerank_status": "fallback_input_order"},
        },
    )
    nested = session.execute(
        "continue_norm_catalog",
        {
            "items": [{
                "work_id": "w1",
                "selected_node_id": "catalog:family:ГЭСН",
                "confidence": "high",
            }],
        },
        turn=2,
    )
    assert nested["rows"][0]["ok"] is True, nested["rows"][0]
    assert nested["rows"][0]["level"] == "collection"

    # Flat top-level args remain accepted as transport (normalized to items[]).
    flat_session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Защитное укрытие", "unit": "м2", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    flat_session.catalog_menus["w1"]["catalog:root"] = families
    for node in families:
        flat_session.catalog_node_registry["w1"][node["node_id"]] = node
    flat_session.catalog_current_nodes["w1"] = "catalog:root"
    flat = flat_session.execute(
        "continue_norm_catalog",
        {
            "work_id": "w1",
            "selected_node_id": "catalog:family:ГЭСН",
            "confidence": "medium",
        },
        turn=1,
    )
    assert flat["rows"][0]["ok"] is True, flat["rows"][0]


def test_reuse_accepts_flat_args_and_auto_search_queries_from_title():
    from proxy.smeta_core import document_workflow as workflow

    assert workflow._search_queries_for_work_row({
        "title": "Защитное укрытие пленка",
    })[0]

    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Защитное укрытие пленка", "unit": "м2", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    cache_id = "route:гэснм:24:24-01:24-01-033"
    session.route_evidence_cache[cache_id] = {
        "cache_id": cache_id,
        "family": "ГЭСНм",
        "collection": "24",
        "section": "24-01",
        "table_code": "24-01-033",
    }
    result = session.execute(
        "reuse_norm_catalog_route",
        {
            "work_id": "w1",
            "cache_id": cache_id,
            # reason omitted — transport drafts one
        },
        turn=1,
    )
    assert result["ok"] is True, result
    assert session.selected_tables["w1"]

    items = workflow._auto_norm_search_items(session)
    assert items
    assert items[0]["table_codes"] == ["24-01-033"]
    assert len(items[0]["queries"]) == 2


def test_family_unbound_is_premature_until_broaden_to_root():
    from proxy.smeta_core import document_workflow as workflow

    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Защитное укрытие", "unit": "м2", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    family = {
        "node_id": "catalog:family:ГЭСНм",
        "parent_id": "catalog:root",
        "node_type": "family",
        "cipher": "ГЭСНм",
        "title": "ГЭСНм",
        "purpose": "монтаж оборудования",
    }
    collection = {
        "node_id": "catalog:collection:ГЭСНм:01",
        "parent_id": "catalog:family:ГЭСНм",
        "node_type": "collection",
        "cipher": "01",
        "title": "Металлообработка",
        "purpose": "оборудование",
    }
    session.catalog_node_registry["w1"][family["node_id"]] = family
    session.catalog_node_registry["w1"][collection["node_id"]] = collection
    session.catalog_menus["w1"]["catalog:family:ГЭСНм"] = [collection]
    session.catalog_current_nodes["w1"] = "catalog:family:ГЭСНм"
    session.selected_base_types["w1"]["гэснм"] = {
        "family": "ГЭСНм",
        "reason": "x",
        "confidence": "high",
        "work_features": {
            "domain": "м", "system": "с", "equipment": "пленка",
            "operation": "монтаж", "assembly_state": "site_assembled",
            "installation_context": "на объекте", "unknowns": [],
        },
    }

    result = session.execute(
        "unbound_norm_catalog",
        {
            "items": [{
                "work_id": "w1",
                "current_node_id": "catalog:family:ГЭСНм",
                "confidence": "high",
                "evidence": [{
                    "source_node_id": "catalog:collection:ГЭСНм:01",
                    "field": "title",
                    "claim": "не укрытие",
                }],
            }],
        },
        turn=1,
    )
    assert result["rows"][0]["ok"] is False
    assert "premature" in result["rows"][0]["error"]


def test_norm_evidence_phase_tools_exclude_browse_and_reuse():
    from proxy.smeta_core import document_workflow as workflow

    names = [
        tool["function"]["name"]
        for tool in workflow._phase_norm_tools(
            "norm_evidence",
            include_route_cache=True,
        )
    ]
    assert "browse_norm_catalog" not in names
    assert "reuse_norm_catalog_route" not in names
    assert names == [
        "search_norms_batch",
        "read_norms_batch",
        "broaden_norm_catalog",
    ]


def test_hybrid_continue_merges_top_level_selected_and_drafts_evidence(monkeypatch):
    """Qwen hybrid shape: selected_node_id outside items[] + sibling-only evidence."""
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(
        workflow,
        "rank_norm_catalog_tables",
        lambda *_args, **_kwargs: {
            "cards": [{
                "node_id": "catalog:table:ГЭСНм:06-04-001",
                "parent_id": "catalog:section:ГЭСНм:06-04",
                "node_type": "table",
                "cipher": "06-04-001",
                "title": "Агрегаты",
            }],
            "retrieval_trace": {"rerank_status": "fallback_input_order"},
        },
    )
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Защитное укрытие", "unit": "м2", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    parent = "catalog:collection:ГЭСНм:06"
    sections = []
    for cipher, title in (
        ("06-01", "КОТЛЫ"),
        ("06-04", "АГРЕГАТЫ ПАРОТУРБИННЫЕ"),
        ("06-05", "ТУРБИННОЕ ВСПОМОГАТЕЛЬНОЕ"),
    ):
        node = {
            "node_id": f"catalog:section:ГЭСНм:{cipher}",
            "parent_id": parent,
            "node_type": "section",
            "cipher": cipher,
            "title": title,
            "purpose": title,
            "source_ref": f"ФСНБ · {cipher}",
        }
        sections.append(node)
        session.catalog_node_registry["w1"][node["node_id"]] = node
    session.catalog_menus["w1"][parent] = sections
    session.catalog_current_nodes["w1"] = parent
    session.selected_base_types["w1"]["гэснм"] = {
        "family": "ГЭСНм",
        "reason": "монтаж",
        "confidence": "medium",
        "work_features": {
            "domain": "монтаж",
            "system": "теплосиловое",
            "equipment": "укрытие",
            "operation": "монтаж",
            "assembly_state": "site_assembled",
            "installation_context": "на объекте",
            "unknowns": [],
        },
    }
    session.selected_collections["w1"].add(("гэснм", "06"))

    chosen = "catalog:section:ГЭСНм:06-04"
    result = session.execute(
        "continue_norm_catalog",
        {
            "items": [{
                "work_id": "w1",
                "current_node_id": parent,
                "confidence": "medium",
                "catalog_query": "защитное укрытие пленка",
                "evidence": [
                    {
                        "source_node_id": "catalog:section:ГЭСНм:06-05",
                        "field": "title",
                        "claim": "не укрытия",
                    },
                    {
                        "source_node_id": "catalog:section:ГЭСНм:06-01",
                        "field": "title",
                        "claim": "котлы",
                    },
                ],
                "rejected_nodes": [
                    {
                        "node_id": "catalog:section:ГЭСНм:06-01",
                        "reason": "котлы не подходят",
                    },
                    {
                        "node_id": "catalog:section:ГЭСНм:06-05",
                        "reason": "турбины не подходят",
                    },
                    {
                        "node_id": chosen,
                        "reason": "ошибочно отвергнут вместе с выбором",
                    },
                ],
            }],
            "selected_node_id": chosen,
        },
        turn=1,
    )
    assert result["rows"][0]["ok"] is True, result["rows"][0]
    assert result["rows"][0]["current_node_id"] == chosen
    assert result["rows"][0]["route_decision"]["selected_node_id"] == chosen
    assert chosen not in {
        entry["node_id"]
        for entry in result["rows"][0]["route_decision"]["rejected_nodes"]
    }


def test_catalog_stall_forces_mapping_serialization():
    from proxy.smeta_core import document_workflow as workflow

    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Укрытие", "unit": "м2", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    parent = "catalog:collection:ГЭСНм:06"
    node = {
        "node_id": "catalog:section:ГЭСНм:06-04",
        "parent_id": parent,
        "node_type": "section",
        "cipher": "06-04",
        "title": "Агрегаты",
        "purpose": "Агрегаты",
    }
    session.catalog_menus["w1"][parent] = [node]
    session.catalog_node_registry["w1"][node["node_id"]] = node
    session.catalog_current_nodes["w1"] = parent

    last = None
    for turn in range(1, 4):
        last = session.execute(
            "continue_norm_catalog",
            {
                "items": [{
                    "work_id": "w1",
                    "current_node_id": parent,
                    "selected_node_id": "catalog:section:ГЭСНм:06-04",
                    "confidence": "medium",
                    # Deliberately empty evidence after draft would succeed —
                    # force structural fail via unknown selected outside menu.
                    "evidence": [{
                        "source_node_id": "catalog:section:ГЭСНм:99-99",
                        "field": "title",
                        "claim": "missing",
                    }],
                }],
            },
            turn=turn,
        )
    assert last is not None
    assert last.get("catalog_stalled") is True
    assert last.get("force_mapping_serialization") is True


def test_table_continue_truncates_extra_rejected_siblings(monkeypatch):
    """Wide table menus: >6 sibling rejects must not block a valid selection."""
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(
        workflow,
        "rank_norm_catalog_tables",
        lambda *_args, **_kwargs: {"cards": [], "retrieval_trace": {"rerank_status": "ok"}},
    )
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Укрытие", "unit": "м2", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    section_id = "catalog:section:ГЭСН:13-08"
    tables = []
    for index in range(1, 12):
        cipher = f"13-08-{index:03d}"
        node = {
            "node_id": f"catalog:table:ГЭСН:{cipher}",
            "parent_id": section_id,
            "node_type": "table",
            "cipher": cipher,
            "title": f"Таблица {cipher}",
            "purpose": f"Описание {cipher}",
        }
        tables.append(node)
        session.catalog_node_registry["w1"][node["node_id"]] = node
    session.catalog_menus["w1"][section_id] = tables
    session.catalog_current_nodes["w1"] = section_id
    session.selected_base_types["w1"]["гэсн"] = {
        "family": "ГЭСН",
        "reason": "строительные работы",
        "confidence": "medium",
        "work_features": {
            "domain": "строительство",
            "system": "временные",
            "equipment": "пленка",
            "operation": "устройство",
            "assembly_state": "site_assembled",
            "installation_context": "на объекте",
            "unknowns": [],
        },
    }
    session.selected_collections["w1"].add(("гэсн", "13"))
    session.selected_sections["w1"].add(("гэсн", "13", "13-08"))
    chosen = tables[10]["node_id"]
    rejected = [
        {"node_id": node["node_id"], "reason": f"не подходит {node['cipher']}"}
        for node in tables[:11]
        if node["node_id"] != chosen
    ]
    assert len(rejected) > 6

    result = session.execute(
        "continue_norm_catalog",
        {"items": [{
            "work_id": "w1",
            "current_node_id": section_id,
            "selected_node_id": chosen,
            "evidence": [{
                "source_node_id": chosen,
                "field": "title",
                "claim": tables[10]["title"],
            }],
            "rejected_nodes": rejected,
            "confidence": "medium",
            "missing_facts": [],
        }]},
        turn=1,
    )

    assert result["rows"][0]["ok"] is True, result["rows"][0]
    assert result["rows"][0]["level"] == "norm_search"
    assert ("гэсн", "13", tables[10]["cipher"]) in session.selected_tables["w1"]
    assert session.route_evidence_cache == {}
    assert session._completed_route_cache() == []


def test_route_cache_publishes_only_after_bind_not_table_select():
    """Wrong first table must not poison reuse for later VOR rows."""
    from proxy.smeta_core import document_workflow as workflow

    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Укрытие пленка", "unit": "м2", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    session.selected_base_types["w1"]["гэснм"] = {
        "family": "ГЭСНм",
        "reason": "монтаж",
        "confidence": "high",
        "work_features": {
            "domain": "м", "system": "с", "equipment": "пленка",
            "operation": "монтаж", "assembly_state": "site_assembled",
            "installation_context": "на объекте", "unknowns": [],
        },
    }
    session.selected_collections["w1"].add(("гэснм", "06"))
    session.selected_sections["w1"].add(("гэснм", "06", "06-05"))
    session.selected_tables["w1"] = {("гэснм", "06", "06-05-001")}
    assert session._completed_route_cache() == []
    assert session.route_evidence_cache == {}

    code = "ГЭСНм06-05-001-01"
    session.opened["w1"] = {
        code: {
            "norm_code": code,
            "measure_unit": "м2",
            "title": "Укрытие",
        }
    }
    submit = session.execute(
        "submit_lsr_mapping",
        {
            "rows": [{
                "work_id": "w1",
                "decision": "bind",
                "norm_code": code,
                "selection_kind": "exact",
                "applicability": "exact",
                "analog_limitations": [],
                "reason": "карточка совпадает с работой по укрытию",
                "technology_check": _technology_check(),
                "candidate_evaluations": _candidate_evaluations(code),
            }],
        },
        turn=1,
    )
    assert submit["ok"] is True, submit
    cache = session._completed_route_cache()
    assert len(cache) == 1
    assert cache[0]["table_code"] == "06-05-001"
    assert "06-05-001" in next(iter(session.route_evidence_cache))


def test_unbound_does_not_publish_route_for_reuse():
    from proxy.smeta_core import document_workflow as workflow

    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Покраска", "unit": "м2", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    session.selected_tables["w1"] = {("гэснм", "06", "06-05-001")}
    session.route_evidence_cache["route:гэснм:06:06-05:06-05-001"] = {
        "cache_id": "route:гэснм:06:06-05:06-05-001",
        "source_work_id": "w1",
        "family": "ГЭСНм",
        "collection": "06",
        "section": "06-05",
        "table_code": "06-05-001",
    }
    session.query_trace.append({
        "work_id": "w1",
        "queries": ["покраска исходно", "покраска ФСНБ"],
    })
    code = "ГЭСНм06-05-001-01"
    session.opened["w1"] = {
        code: {
            "norm_code": code,
            "measure_unit": "м2",
            "title": "Не то",
        }
    }
    submit = session.execute(
        "submit_lsr_mapping",
        {
            "rows": [{
                "work_id": "w1",
                "decision": "unbound",
                "reason": "открытая карточка не подходит к покраске",
                "unbound_evidence": _unbound_evidence(
                    queries=["покраска исходно", "покраска ФСНБ"],
                    opened=[code],
                ),
            }],
        },
        turn=1,
    )
    assert submit["ok"] is True, submit
    assert session.route_evidence_cache == {}
    assert session._completed_route_cache() == []


def test_mapping_transport_does_not_rewrite_model_decision():
    from proxy.smeta_core.document_workflow import _normalize_mapping_row_transport

    decision = {
        "selection_kind": "exact",
        "applicability": "close_analog",
        "analog_limitations": ["материал заменить"],
        "resource_actions": [{"action": "replace", "basis_ref": "card:material"}],
    }

    assert _normalize_mapping_row_transport(decision) == decision


def test_tool_transport_repairs_only_missing_or_extra_trailing_delimiters():
    from proxy.smeta_core.document_workflow import _tool_arguments, _tool_array_argument

    missing = {"function": {"arguments": '{"items":[{"work_id":"w1"}]'}}
    extra = {"function": {"arguments": '{"items":[{"work_id":"w1"}]}}'}}
    assert _tool_arguments(missing) == {"items": [{"work_id": "w1"}]}
    assert _tool_arguments(extra) == {"items": [{"work_id": "w1"}]}
    assert _tool_array_argument(
        {"rows": '[{"work_id":"w1","decision":"unbound"}]]'}, "rows"
    ) == [{"work_id": "w1", "decision": "unbound"}]


def test_norm_transport_accepts_typographic_dashes_without_changing_card():
    from proxy.smeta_core.document_workflow import _resolve_norm_code_transport

    canonical = "ГЭСНм11-04-027-01"
    available = {canonical: {"norm_code": canonical}}
    assert _resolve_norm_code_transport("ГЭСНм 11–04—027−01", available) == canonical


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


def test_exact_bind_rejects_reason_that_denies_applicability():
    from proxy.smeta_core import document_workflow as workflow

    assert workflow._exact_bind_reason_self_contradiction_errors({
        "selection_kind": "exact",
        "reason": "Норма не применима к монтажу блока аварийного питания",
    })
    assert not workflow._exact_bind_reason_self_contradiction_errors({
        "selection_kind": "analog",
        "reason": "Норма не применима как точная, выбран аналог",
    })
    assert not workflow._exact_bind_reason_self_contradiction_errors({
        "selection_kind": "exact",
        "reason": "Норма применима: операция и объект совпадают",
    })

    code = "ГЭСНр54-01-002-01"
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Монтаж БАП", "unit": "шт", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    session.opened["w1"] = {
        code: {"norm_code": code, "measure_unit": "шт", "title": "Разборка балок"},
    }
    session.candidate_draft_attempts["w1"] = 2
    result = session.execute(
        "submit_lsr_mapping",
        {"rows": [{
            "work_id": "w1",
            "decision": "bind",
            "norm_code": code,
            "selection_kind": "exact",
            "applicability": "exact",
            "analog_limitations": [],
            "reason": (
                "ГЭСНр54-01-002-01 описывает разборку стальных балок, "
                "норма не применима к монтажу БАП"
            ),
            "technology_check": _technology_check(),
            "candidate_evaluations": _candidate_evaluations(code),
        }]},
        turn=1,
    )
    assert result["ok"] is False
    assert result["errors"][0]["error"] == "incomplete bind evidence"
    assert any(
        "denies applicability" in str(detail)
        for detail in result["errors"][0]["details"]
    )
    assert "w1" not in session.accepted_rows


def test_terminal_accepts_one_defensible_opened_candidate_without_forced_comparison(
    monkeypatch,
):
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

    accepted = session.execute(
        "submit_lsr_mapping",
        {"rows": [{**base, "candidate_evaluations": _candidate_evaluations(codes[0])}]},
        turn=3,
    )

    assert accepted == {"ok": True, "rows": 1}
    assert session.accepted_rows["w1"]["candidate_evaluations"] == (
        _candidate_evaluations(codes[0])
    )


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


def test_batch_agent_checkpoint_resumes_after_last_tool_without_repeating_search(
    monkeypatch,
):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(
        workflow,
        "browse_norms_many",
        lambda queries, **_kwargs: {
            query: {"backend": "rrf", "cards": []} for query in queries
        },
    )
    checkpoints = []
    first_calls = 0

    def interrupted_exchange(_messages, _tools):
        nonlocal first_calls
        first_calls += 1
        if first_calls == 1:
            return {
                "tool_calls": [
                    _native_call(
                        "search",
                        "search_norms_batch",
                        items=[
                            {
                                "work_id": "w1",
                                "queries": [
                                    "монтаж элемента",
                                    "установка элемента ФСНБ",
                                ],
                            }
                        ],
                    )
                ]
            }
        raise RuntimeError("process interrupted during next model wait")

    rows = [
        {
            "work_id": "w1",
            "title": "Монтаж элемента",
            "unit": "шт",
            "quantity": 1,
        }
    ]
    with pytest.raises(RuntimeError, match="process interrupted"):
        workflow._run_batch_norm_agent(
            rows,
            interrupted_exchange,
            candidate_limit=6,
            max_turns=2,
            checkpoint=checkpoints.append,
        )

    assert first_calls == 2
    checkpoint = checkpoints[-1]
    assert checkpoint["resume_state"]["next_turn"] == 2
    assert checkpoint["query_trace"][0]["queries"] == [
        "монтаж элемента",
        "установка элемента ФСНБ",
    ]
    resumed_calls = 0

    def resumed_exchange(messages, _tools):
        nonlocal resumed_calls
        resumed_calls += 1
        assert all(message.get("role") != "tool" for message in messages)
        assert sum(
            "smeta_norm_agent_working_memory_v1" in str(message.get("content") or "")
            for message in messages
        ) == 1
        resume_status = next(
            json.loads(message["content"])
            for message in reversed(messages)
            if message.get("role") == "user"
            and "smeta_norm_agent_working_memory_v1" in str(message.get("content") or "")
        )
        assert resume_status["remaining_work_ids"] == ["w1"]
        assert "authoritative_budget_remaining" not in resume_status
        assert resume_status["focus_work_id"] == "w1"
        assert "historical tool messages are only an audit log" in (
            resume_status["instruction"]
        )
        return {
            "tool_calls": [
                _native_call(
                    "submit",
                    "submit_lsr_mapping",
                    rows=[
                        {
                            "work_id": "w1",
                            "decision": "unbound",
                            "reason": "После двух поисков точная норма не найдена",
                            "unbound_evidence": _unbound_evidence(
                                queries=[
                                    "монтаж элемента",
                                    "установка элемента ФСНБ",
                                ]
                            ),
                        }
                    ],
                )
            ]
        }

    result = workflow._run_batch_norm_agent(
        rows,
        resumed_exchange,
        candidate_limit=6,
        max_turns=2,
        checkpoint=checkpoints.append,
        resume_checkpoint=checkpoint,
    )

    assert resumed_calls == 1
    assert result["selections"]["w1"]["review_status"] == "model_batch_unbound"
    assert [
        item["tool"] for item in result["agent_trace"]["tool_trajectory"]
    ] == ["search_norms_batch", "submit_lsr_mapping"]


def test_batch_agent_resume_requires_read_before_more_search(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(
        workflow,
        "browse_norms_many",
        lambda queries, **_kwargs: {
            query: {
                "backend": "rrf",
                "cards": [
                    {
                        "norm_code": "ГЭСНм10-07-058-01",
                        "title": "Кандидат шкафа",
                        "unit": "шт",
                        "source_ref": "fsnb.sqlite#guid=1",
                    }
                ],
            }
            for query in queries
        },
    )
    checkpoints = []
    calls = 0

    def interrupted_exchange(_messages, _tools):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "tool_calls": [
                    _native_call(
                        "search",
                        "search_norms_batch",
                        items=[
                            {
                                "work_id": "w1",
                                "queries": ["монтаж шкафа связи"],
                            }
                        ],
                    )
                ]
            }
        raise RuntimeError("interrupt after candidate search")

    rows = [
        {
            "work_id": "w1",
            "title": "Монтаж шкафа связи",
            "unit": "шт",
            "quantity": 1,
        }
    ]
    with pytest.raises(RuntimeError, match="interrupt after candidate search"):
        workflow._run_batch_norm_agent(
            rows,
            interrupted_exchange,
            candidate_limit=6,
            max_turns=2,
            checkpoint=checkpoints.append,
        )

    def inspect_resume(messages, _tools):
        assert sum(
            "smeta_norm_agent_working_memory_v1" in str(message.get("content") or "")
            for message in messages
        ) == 1
        assert all(message.get("role") != "tool" for message in messages)
        resume_status = next(
            json.loads(message["content"])
            for message in reversed(messages)
            if message.get("role") == "user"
            and "smeta_norm_agent_working_memory_v1" in str(message.get("content") or "")
        )
        assert resume_status["must_read_before_more_search"] == ["w1"]
        status = resume_status["work_evidence_status"][0]
        assert status["work_id"] == "w1"
        assert status["is_focus"] is True
        assert status["candidate_codes"] == ["ГЭСНм10-07-058-01"]
        assert status["opened_codes"] == []
        assert status["search_count"] == 1
        assert "Call read_norms_batch" in resume_status["instruction"]
        raise RuntimeError("resume status inspected")

    with pytest.raises(RuntimeError, match="resume status inspected"):
        workflow._run_batch_norm_agent(
            rows,
            inspect_resume,
            candidate_limit=6,
            max_turns=2,
            resume_checkpoint=checkpoints[-1],
        )


def test_batch_agent_resume_requires_navigation_for_selected_collection():
    from proxy.smeta_core import document_workflow as workflow

    rows = [{
        "work_id": "w1",
        "title": "Монтаж блока",
        "unit": "шт",
        "quantity": 1,
    }]
    tool_session = workflow.SmetaNormToolSession(
        rows,
        candidate_limit=4,
        require_scoped_search=True,
    )
    tool_session.selected_base_types["w1"]["гэснм"] = {
        "family": "ГЭСНм",
        "reason": "Монтаж оборудования",
        "confidence": "high",
    }
    tool_session.selected_collections["w1"].add(("гэснм", "20"))
    checkpoint = {
        "resume_state": {
            "schema": "smeta_norm_agent_resume_v1",
            "conversation": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "task"},
            ],
            "tool_session": tool_session.checkpoint_state(),
            "model_trace": [],
            "context_metrics": [],
            "next_turn": 1,
            "structured_mapping_attempts": 0,
            "focus_serialization_pending": False,
            "validation_contract_version": (
                workflow.MAPPING_VALIDATION_CONTRACT_VERSION
            ),
        }
    }

    def inspect_resume(messages, _tools):
        working_memory = next(
            json.loads(message["content"])
            for message in reversed(messages)
            if message.get("role") == "user"
            and "smeta_norm_agent_working_memory_v1"
            in str(message.get("content") or "")
        )
        assert working_memory["must_navigate_selected_scopes"] == [{
            "work_id": "w1",
            "base_type": "ГЭСНм",
            "collection": "20",
            "selected_sections": [],
            "next_action": (
                "select a section if none is selected, then select one "
                "official table from that section"
            ),
        }]
        assert "only phase section_select" in (
            working_memory["instruction"]
        )
        raise RuntimeError("selected scope search requirement inspected")

    with pytest.raises(
        RuntimeError,
        match="selected scope search requirement inspected",
    ):
        workflow._run_batch_norm_agent(
            rows,
            inspect_resume,
            candidate_limit=4,
            max_turns=1,
            resume_checkpoint=checkpoint,
            require_scoped_search=True,
        )


def test_phase_scheduler_batches_all_rows_at_the_earliest_phase(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    rows = [
        {"work_id": "w1", "title": "Работа 1", "unit": "шт", "quantity": 1},
        {"work_id": "w2", "title": "Работа 2", "unit": "шт", "quantity": 1},
    ]
    original_execute = workflow.SmetaNormToolSession.execute
    root_calls = []

    def execute(session, name, args, *, turn):
        if name == "browse_norm_catalog" and all(
            set(item) == {"work_id"}
            for item in args.get("items") or []
        ):
            work_ids = [item["work_id"] for item in args["items"]]
            root_calls.append(work_ids)
            session.family_catalog_seen.update(work_ids)
            return {"ok": True, "rows": [
                {"work_id": work_id, "ok": True, "items": []}
                for work_id in work_ids
            ]}
        return original_execute(session, name, args, turn=turn)

    monkeypatch.setattr(workflow.SmetaNormToolSession, "execute", execute)

    def inspect_batch(messages, tools):
        memory = next(
            json.loads(message["content"])
            for message in reversed(messages)
            if "smeta_norm_agent_working_memory_v1"
            in str(message.get("content") or "")
        )
        assert memory["active_phase"] == "family_select"
        assert memory["active_work_ids"] == ["w1", "w2"]
        # family_select: Ollama-safe continue only (ask/broaden/unbound later).
        assert [tool["function"]["name"] for tool in tools] == [
            "continue_norm_catalog",
        ]
        raise RuntimeError("same-phase batch inspected")

    with pytest.raises(RuntimeError, match="same-phase batch inspected"):
        workflow._run_batch_norm_agent(
            rows,
            inspect_batch,
            candidate_limit=4,
            max_turns=1,
            require_scoped_search=True,
        )
    assert root_calls == [["w1", "w2"]]


def test_submit_checkpoints_each_accepted_row_before_the_next():
    from proxy.smeta_core import document_workflow as workflow

    rows = [
        {"work_id": "w1", "title": "Работа 1", "unit": "шт", "quantity": 1},
        {"work_id": "w2", "title": "Работа 2", "unit": "шт", "quantity": 1},
    ]
    snapshots = []
    session = workflow.SmetaNormToolSession(rows, candidate_limit=3)

    def checkpoint(work_id, _selection):
        snapshots.append((work_id, list(session.accepted_rows)))

    session.decision_checkpoint = checkpoint
    for work_id in ("w1", "w2"):
        session.query_trace.extend([
            {"work_id": work_id, "queries": [f"{work_id} literal"], "filters": {}},
            {"work_id": work_id, "queries": [f"{work_id} technology"], "filters": {}},
        ])
    result = session.execute(
        "submit_lsr_mapping",
        {"rows": [
            {
                "work_id": work_id,
                "decision": "unbound",
                "reason": "Защищаемой нормы нет.",
                "unbound_evidence": {
                    "queries_used": [
                        f"{work_id} literal",
                        f"{work_id} technology",
                    ],
                    "opened_norm_codes": [],
                    "rejection_reasons": ["Нет применимой открытой карточки."],
                    "coverage_checked": "Покрытие соседней работой не подтверждено.",
                },
            }
            for work_id in ("w1", "w2")
        ]},
        turn=1,
    )

    assert result == {"ok": True, "rows": 2}
    assert snapshots == [
        ("w1", ["w1"]),
        ("w2", ["w1", "w2"]),
    ]


def test_model_can_reuse_typed_route_cache_without_reusing_norm_decision():
    from proxy.smeta_core import document_workflow as workflow

    route = {
        "cache_id": "route:гэснм:10:10-04:10-04-067",
        "source_work_id": "old-1",
        "family": "ГЭСНм",
        "collection": "10",
        "section": "10-04",
        "table_code": "10-04-067",
        "source": "typed_catalog_trace",
    }
    session = workflow.SmetaNormToolSession(
        [{
            "work_id": "w1",
            "title": "Монтаж шкафа",
            "unit": "шт",
            "quantity": 1,
            "route_evidence_cache": [route],
        }],
        candidate_limit=4,
        require_scoped_search=True,
    )

    result = session.execute(
        "reuse_norm_catalog_route",
        {"items": [{
            "work_id": "w1",
            "cache_id": route["cache_id"],
            "reason": "Та же функциональная система и операция монтажа.",
            "confidence": "high",
        }]},
        turn=2,
    )

    assert result["rows"][0]["level"] == "norm_search"
    assert session.selected_tables["w1"] == {
        ("гэснм", "10", "10-04-067")
    }
    assert session.candidates["w1"] == {}
    assert session.accepted_rows == {}
    assert session.catalog_trace[-1]["selection_owner"] == "model"


def test_compact_route_evidence_cache_keeps_ids_without_bulky_fields():
    from proxy.smeta_core import document_workflow as workflow

    compact = workflow._compact_route_evidence_cache_for_model([{
        "cache_id": "route:гэснм:10:10-04:10-04-067",
        "source_work_id": "old-1",
        "family": "ГЭСНм",
        "collection": "10",
        "section": "10-04",
        "table_code": "10-04-067",
        "passport": {"huge": "payload"},
        "source": "typed_catalog_trace",
    }])

    assert compact == [{
        "cache_id": "route:гэснм:10:10-04:10-04-067",
        "family": "ГЭСНм",
        "collection": "10",
        "section": "10-04",
        "table_code": "10-04-067",
        "source_work_id": "old-1",
    }]


def test_batch_agent_surfaces_reuse_first_when_route_cache_present(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    route = {
        "cache_id": "route:гэснм:10:10-04:10-04-067",
        "source_work_id": "old-1",
        "family": "ГЭСНм",
        "collection": "10",
        "section": "10-04",
        "table_code": "10-04-067",
        "source": "typed_catalog_trace",
    }
    seen_tools = []
    seen_memory = []
    exchange_calls = {"n": 0}

    def exchange(messages, tools):
        exchange_calls["n"] += 1
        seen_tools.append([
            str(((tool.get("function") or {}).get("name") or ""))
            for tool in tools
        ])
        memory = next(
            json.loads(message["content"])
            for message in reversed(messages)
            if message.get("role") == "user"
            and "smeta_norm_agent_working_memory_v1"
            in str(message.get("content") or "")
        )
        seen_memory.append(memory)
        if exchange_calls["n"] == 1:
            return {"tool_calls": [_native_call(
                "reuse-1",
                "reuse_norm_catalog_route",
                items=[{
                    "work_id": "w1",
                    "cache_id": route["cache_id"],
                    "reason": "Та же система и операция",
                    "confidence": "high",
                }],
            )]}
        return {"content": "serialize"}

    def mapping_exchange(_messages, _schema):
        return {"rows": [{
            "work_id": "w1",
            "decision": "unbound",
            "reason": "После reuse применимая норма не найдена",
            "unbound_evidence": {
                "rejection_reasons": ["в таблице нет подходящей карточки"],
                "coverage_checked": "покрытие соседними строками не подтверждено",
            },
        }]}

    result = workflow._run_batch_norm_agent(
        [{
            "work_id": "w1",
            "title": "Монтаж шкафа",
            "unit": "шт",
            "quantity": 1,
            "route_evidence_cache": [route],
        }],
        exchange,
        mapping_exchange=mapping_exchange,
        candidate_limit=5,
        max_turns=2,
        require_scoped_search=False,
    )

    assert "reuse_norm_catalog_route" in seen_tools[0]
    assert seen_memory[0]["route_reuse_first"] is True
    assert seen_memory[0]["route_evidence_cache"][0]["cache_id"] == route["cache_id"]
    assert "reuse_norm_catalog_route" in seen_memory[0]["instruction"]
    assert result["selections"]["w1"]["review_status"] in {
        "model_batch_unbound",
        "model_batch_candidate",
    }


def test_source_batch_progress_reports_sec_per_row(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    monkeypatch.setenv("LES_SMETA_CANDIDATE_DRAFT_MODE", "on")
    monkeypatch.setenv("LES_SMETA_MAPPING_EVIDENCE_REPAIR_TURNS", "2")
    events = []

    def exchange(_messages, _tools):
        return {"content": "serialize"}

    def mapping_exchange(messages, _schema):
        work_id = "w1"
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            try:
                payload = json.loads(str(message.get("content") or "{}"))
            except json.JSONDecodeError:
                continue
            remaining = payload.get("remaining_work_ids") or []
            if remaining:
                work_id = str(remaining[0])
                break
        return {"rows": [{
            "work_id": work_id,
            "decision": "unbound",
            "reason": "Применимая норма не найдена после проверки",
            "unbound_evidence": {
                "rejection_reasons": ["подходящей карточки нет"],
                "coverage_checked": "покрытие соседними строками не подтверждено",
            },
        }]}

    result = workflow._run_native_norm_agent(
        [
            {"work_id": "w1", "title": "Работа 1", "unit": "шт", "quantity": 1},
            {"work_id": "w2", "title": "Работа 2", "unit": "шт", "quantity": 1},
        ],
        exchange,
        mapping_exchange=mapping_exchange,
        candidate_limit=5,
        max_turns=1,
        batch_size=1,
        progress=events.append,
        require_scoped_search=False,
    )

    done_events = [
        event for event in events
        if event.get("phase") == "source_batch" and event.get("status") == "done"
    ]
    assert done_events
    assert done_events[-1]["rows_done"] == 2
    assert done_events[-1]["sec_per_row"] is not None
    assert "с/поз" in str(done_events[-1].get("label") or "")
    assert set(result["selections"]) == {"w1", "w2"}


def test_resume_fingerprint_ignores_growing_transport_route_cache():
    from proxy.smeta_core import document_workflow as workflow

    source = {
        "work_id": "w1",
        "title": "Монтаж шкафа",
        "unit": "шт",
        "quantity": 1,
    }
    before = workflow.SmetaNormToolSession(
        [source],
        candidate_limit=4,
        require_scoped_search=True,
    )
    state = before.checkpoint_state()
    after = workflow.SmetaNormToolSession(
        [{
            **source,
            "task_state": {"completed_rows": 0},
            "route_evidence_cache": [{
                "cache_id": "route:гэснм:10:10-04:10-04-067",
                "source_work_id": "old-1",
                "family": "ГЭСНм",
                "collection": "10",
                "section": "10-04",
                "table_code": "10-04-067",
            }],
        }],
        candidate_limit=4,
        require_scoped_search=True,
    )

    after.restore_checkpoint_state(state)

    assert after.work_fingerprint() == before.work_fingerprint()


def test_compact_catalog_menu_keeps_exact_ids_and_bounds_payload():
    from proxy.smeta_core import document_workflow as workflow

    menu = [
        {
            "node_id": f"node-{index}",
            "parent_id": "root",
            "node_type": "collection",
            "cipher": f"{index:02d}",
            "title": f"Сборник {index}",
            "hierarchy": ["large", "payload"],
            "norm_name_examples": ["large", "payload"],
        }
        for index in range(20)
    ]

    compact = workflow._compact_catalog_menu_for_model(menu, limit=6)

    assert len(compact) == 6
    assert compact[0]["node_id"] == "node-0"
    assert "hierarchy" not in compact[0]
    assert "norm_name_examples" not in compact[0]


def test_global_review_runs_only_connected_conflict_groups(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    rows = [
        {"work_id": "w1", "title": "Работа 1", "unit": "шт", "quantity": 1},
        {"work_id": "w2", "title": "Работа 2", "unit": "шт", "quantity": 1},
        {"work_id": "w3", "title": "Работа 3", "unit": "шт", "quantity": 1},
    ]
    initial = {
        "selections": {
            work_id: {"norm_code": f"Н-{work_id}", "reason": f"initial-{work_id}"}
            for work_id in ("w1", "w2", "w3")
        },
        "opened_cards": {},
        "browse_trace": {},
        "query_trace": [],
        "catalog_trace": [],
        "model_trace": [],
        "agent_trace": {},
    }
    conflict = {
        "conflict_id": "c1",
        "code": "possible_duplicate_norm_binding",
        "severity": "warning",
        "work_ids": ["w1", "w2"],
        "claim": "Проверить возможное дублирование.",
        "evidence": {},
    }
    detections = iter([[conflict], []])
    monkeypatch.setattr(
        workflow,
        "detect_professional_conflicts",
        lambda *_args, **_kwargs: next(detections),
    )
    reviewed_packets = []

    def batch_runner(packet_rows, **_kwargs):
        reviewed_packets.append([row["work_id"] for row in packet_rows])
        return {
            "selections": {
                row["work_id"]: {
                    **row["current_decision"],
                    "reason": f"reviewed-{row['work_id']}",
                }
                for row in packet_rows
            },
            "opened_cards": {},
            "browse_trace": {},
            "query_trace": [],
            "catalog_trace": [],
            "model_trace": [],
            "agent_trace": {},
        }

    result = workflow._run_global_norm_review(
        rows,
        initial,
        lambda _messages, _tools: {},
        mapping_exchange=None,
        candidate_limit=4,
        max_turns=4,
        progress=None,
        user_request="review",
        batch_runner=batch_runner,
    )

    assert reviewed_packets == [["w1", "w2"]]
    assert result["selections"]["w1"]["reason"] == "reviewed-w1"
    assert result["selections"]["w2"]["reason"] == "reviewed-w2"
    assert result["selections"]["w3"] == initial["selections"]["w3"]
    assert result["agent_trace"]["global_review"]["preserved_work_ids"] == ["w3"]


def test_global_review_preserves_initial_when_mapping_repair_fails(monkeypatch):
    """Conflict review must not destroy a completed row-mapping document."""
    from proxy.smeta_core import document_workflow as workflow

    rows = [
        {"work_id": "w1", "title": "Работа 1", "unit": "шт", "quantity": 1},
        {"work_id": "w2", "title": "Работа 2", "unit": "шт", "quantity": 1},
        {"work_id": "w3", "title": "Работа 3", "unit": "шт", "quantity": 1},
    ]
    initial = {
        "selections": {
            "w1": {
                "norm_code": "ГЭСНр54-01-002-01",
                "reason": "initial-w1",
                "review_status": "model_batch_candidate",
            },
            "w2": {
                "norm_code": "ГЭСНр54-01-002-01",
                "reason": "initial-w2",
                "review_status": "model_batch_candidate",
            },
            "w3": {
                "norm_code": "",
                "reason": "initial-w3",
                "review_status": "model_batch_unbound",
            },
        },
        "opened_cards": {},
        "browse_trace": {},
        "query_trace": [],
        "catalog_trace": [],
        "model_trace": [],
        "agent_trace": {},
    }
    conflict = {
        "conflict_id": "c1",
        "code": "possible_duplicate_norm_binding",
        "severity": "warning",
        "work_ids": ["w1", "w2"],
        "claim": "Проверить возможное дублирование.",
        "evidence": {},
    }
    detections = iter([[conflict], [conflict]])
    monkeypatch.setattr(
        workflow,
        "detect_professional_conflicts",
        lambda *_args, **_kwargs: next(detections),
    )

    def batch_runner(_packet_rows, **_kwargs):
        raise RuntimeError(
            "smeta model mapping failed validation after one bounded schema repair"
        )

    result = workflow._run_global_norm_review(
        rows,
        initial,
        lambda _messages, _tools: {},
        mapping_exchange=None,
        candidate_limit=4,
        max_turns=4,
        progress=None,
        user_request="review",
        batch_runner=batch_runner,
    )

    assert result["selections"]["w1"] == initial["selections"]["w1"]
    assert result["selections"]["w2"] == initial["selections"]["w2"]
    assert result["selections"]["w3"] == initial["selections"]["w3"]
    assert result["valid_model_rows"] == 3
    packet_trace = result["agent_trace"]["global_review"]["packets"][0]
    assert packet_trace["status"] == "packet_preserved_after_mapping_failure"


def test_bounded_batches_continue_after_mapping_validation_exhausted():
    from proxy.smeta_core import document_workflow as workflow

    rows = [
        {"work_id": "w1", "title": "Первая", "unit": "шт", "quantity": 1},
        {"work_id": "w2", "title": "Вторая", "unit": "м", "quantity": 2},
        {"work_id": "w3", "title": "Третья", "unit": "м2", "quantity": 3},
    ]
    received = []

    def runner(work_rows, **_kwargs):
        work_id = str(work_rows[0]["work_id"])
        received.append(work_id)
        if work_id == "w2":
            raise workflow.MappingValidationExhausted(
                "smeta model mapping failed validation after one bounded schema repair"
            )
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
            "model_trace": [{"turn": 1, "source": work_id}],
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

    assert received == ["w1", "w2", "w3"]
    assert set(result["selections"]) == {"w1", "w2", "w3"}
    assert result["selections"]["w2"]["review_status"] == "model_batch_open"
    assert not str(result["selections"]["w2"].get("norm_code") or "").strip()
    assert result["incomplete"] is True
    assert result["incomplete_blocker"]["code"] in {
        "batch_failed",
        "rows_skipped_after_mapping_failure",
    }
    assert result["agent_trace"]["status"] == "partial_after_mapping_failure"
    assert any(
        trace.get("status") == "batch_skipped_after_mapping_failure"
        for trace in result["agent_trace"]["batch_traces"]
    )


def test_exact_deny_error_text_is_evidence_repair_marker():
    from proxy.smeta_core import document_workflow as workflow

    errors = workflow._exact_bind_reason_self_contradiction_errors({
        "selection_kind": "exact",
        "reason": "Норма не применима к данной работе",
    })
    assert errors
    text = " ".join(errors)
    assert "denies applicability" in text
    assert "broaden to another table" in text
    source = Path(workflow.__file__).read_text(encoding="utf-8")
    assert "contradicts reason that denies applicability" in source
    assert "smeta_exact_deny_broaden_v1" in source


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
    from proxy.smeta_core.document_workflow import (
        _nested_array_transport,
        _one_item_tool_transport,
        _tool_arguments,
        _tool_array_argument,
        _tool_bool,
    )

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
    assert _nested_array_transport(
        '[{"source_node_id":"catalog:family:ГЭСНм","field":"title","claim":"Монтаж"}]'
    ) == [{
        "source_node_id": "catalog:family:ГЭСНм",
        "field": "title",
        "claim": "Монтаж",
    }]
    assert _nested_array_transport("не массив") == "не массив"
    assert _one_item_tool_transport(
        {
            "work_id": "w1",
            "query": "монтаж шкафа",
            "base_types": '["ГЭСНм"]',
            "collections": '["37"]',
            "table_codes": '["37-01-002"]',
        },
        array_fields=("base_types", "collections", "table_codes"),
    )["items"] == [{
        "work_id": "w1",
        "query": "монтаж шкафа",
        "base_types": ["ГЭСНм"],
        "collections": ["37"],
        "table_codes": ["37-01-002"],
    }]


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


def test_batch_agent_accepts_first_incomplete_unbound_as_candidate(monkeypatch):
    """Avoid a second slow mapping call when unbound evidence is incomplete."""
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
    ])

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        lambda _messages, _tools: {"tool_calls": next(turns)},
        candidate_limit=5,
        max_turns=4,
    )

    first_submit = result["model_trace"][1]["tool_results"][0]["result"]
    assert first_submit["ok"] is True
    assert result["selections"]["w1"]["review_status"] == "model_batch_candidate"
    assert result["selections"]["w1"]["unbound_evidence"]["queries_used"] == [
        "буквальный поиск",
    ]


def test_unbound_without_search_is_rejected_on_first_forced_pass():
    from proxy.smeta_core import document_workflow as workflow

    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Общее изделие", "unit": "шт", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    row = {
        "work_id": "w1",
        "decision": "unbound",
        "reason": "Модель не нашла защищаемую привязку",
        "unbound_evidence": {},
    }

    first = session.execute("submit_lsr_mapping", {"rows": [row]}, turn=1)
    assert first["ok"] is False
    assert first["errors"][0]["error"] == "invalid unbound_evidence"
    assert "w1" not in session.accepted_rows

    # Second identical pass may become candidate (bounded last resort), but the
    # first forced mapping must not close a zero-search row.
    second = session.execute("submit_lsr_mapping", {"rows": [row]}, turn=2)
    assert second["ok"] is True
    assert session.accepted_rows["w1"]["review_status"] == "model_batch_candidate"

    session2 = workflow.SmetaNormToolSession(
        [{"work_id": "w2", "title": "Общее изделие", "unit": "шт", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    session2.query_trace.append({
        "work_id": "w2",
        "queries": ["общее изделие", "общее изделие ФСНБ"],
    })
    with_search = session2.execute(
        "submit_lsr_mapping",
        {"rows": [{**row, "work_id": "w2"}]},
        turn=1,
    )
    assert with_search["ok"] is True
    assert session2.accepted_rows["w2"]["review_status"] == "model_batch_candidate"


def test_post_budget_unbound_promotes_candidate_instead_of_hard_fail(monkeypatch):
    """Local Ollama burns max_turns=10 then must not re-arm evidence repair forever."""
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    monkeypatch.setenv("LES_SMETA_MAPPING_EVIDENCE_REPAIR_TURNS", "2")
    monkeypatch.setenv("LES_SMETA_CANDIDATE_DRAFT_MODE", "on")

    def exchange(_messages, _tools):
        return {"content": "сериализую решение"}

    def mapping_exchange(_messages, _schema):
        return {"rows": [{
            "work_id": "w1",
            "decision": "unbound",
            "reason": "Применимая норма не найдена после проверки",
            "unbound_evidence": {
                "rejection_reasons": ["подходящей карточки нет"],
                "coverage_checked": "покрытие соседними строками не подтверждено",
            },
        }]}

    result = workflow._run_batch_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        exchange,
        mapping_exchange=mapping_exchange,
        candidate_limit=5,
        max_turns=1,
        require_scoped_search=False,
    )

    selection = result["selections"]["w1"]
    assert selection["review_status"] == "model_batch_candidate"
    assert selection["norm_code"] == ""
    assert selection["precalculation_blockers"][0]["code"] == "model_candidate_unbound"


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


def test_unbound_rejects_nonterminal_and_unopened_norm_claims():
    from proxy.smeta_core import document_workflow as workflow

    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Организатор", "unit": "шт", "quantity": 1}],
        candidate_limit=5,
        require_scoped_search=True,
    )
    session.query_trace.extend([
        {
            "work_id": "w1",
            "queries": ["организатор"],
            "filters": {"base_types": ["ГЭСНм"], "collections": ["10"]},
        },
        {
            "work_id": "w1",
            "queries": ["организатор"],
            "filters": {"base_types": ["ГЭСНм"], "collections": ["08"]},
        },
    ])
    session.opened["w1"]["ГЭСНм10-06-034-01"] = {
        "norm_code": "ГЭСНм10-06-034-01",
        "collection": "10",
    }

    result = session.execute(
        "submit_lsr_mapping",
        {"rows": [{
            "work_id": "w1",
            "decision": "unbound",
            "reason": (
                "ГЭСНм08-02-182-04 не подходит; требуется расширенный нормативный поиск "
                "по сборнику 06."
            ),
            "unbound_evidence": {
                "rejection_reasons": ["Открытая карточка не покрывает работу."],
                "coverage_checked": "Покрытие не подтверждено.",
            },
        }]},
        turn=3,
    )

    details = result["errors"][0]["details"]
    assert any("not terminal" in detail for detail in details)
    assert any("not opened" in detail for detail in details)
    assert any("collections without an opened typed card" in detail for detail in details)
    assert session.accepted_rows == {}


def test_compact_unbound_uses_typed_trace_without_repeating_codes():
    from proxy.smeta_core import document_workflow as workflow

    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Организатор", "unit": "шт", "quantity": 1}],
        candidate_limit=5,
        require_scoped_search=True,
    )
    session.query_trace.extend([
        {
            "work_id": "w1",
            "queries": ["организатор"],
            "filters": {"base_types": ["ГЭСНм"], "collections": ["10"]},
        },
        {
            "work_id": "w1",
            "queries": ["организатор"],
            "filters": {"base_types": ["ГЭСНм"], "collections": ["08"]},
        },
    ])
    session.candidates["w1"]["ГЭСНм10-06-034-01"] = {
        "norm_code": "ГЭСНм10-06-034-01",
        "collection": "10",
    }
    session.opened["w1"]["ГЭСНм10-06-034-01"] = {
        "norm_code": "ГЭСНм10-06-034-01",
        "collection": "10",
    }

    result = session.execute(
        "submit_lsr_mapping",
        {"rows": [{
            "work_id": "w1",
            "decision": "unbound",
            "reason": "Открытая карточка не содержит исходную операцию.",
            "unbound_evidence": {
                "rejection_reasons": [
                    "ГЭСНм10-06-034-01 не содержит исходную операцию.",
                ],
                "coverage_checked": "Покрытие соседней строкой не подтверждено.",
            },
        }]},
        turn=3,
    )

    assert result == {"ok": True, "rows": 1}
    evidence = session.accepted_rows["w1"]["unbound_evidence"]
    assert evidence["opened_norm_codes"] == ["ГЭСНм10-06-034-01"]
    assert evidence["queries_used"] == []


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

    # Soft unbound evidence gaps accept as candidate on the first mapping call.
    assert mapping_calls["count"] == 1
    assert result["selections"]["w1"]["review_status"] == "model_batch_candidate"
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
        variants = schema["properties"]["rows"]["items"]["oneOf"]
        variant_work_ids = [
            variant["properties"]["work_id"]["enum"]
            for variant in variants
        ]
        work_ids = max(variant_work_ids, key=len)
        assert all(set(values).issubset(work_ids) for values in variant_work_ids)
        assert all(
            any(work_id in values for values in variant_work_ids)
            for work_id in work_ids
        )
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


def test_batch_mapping_timeout_does_not_consume_schema_repair(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
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

    with pytest.raises(workflow.MappingTransportTimeout):
        workflow._run_batch_norm_agent(
            [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
            exchange,
            mapping_exchange=lambda _messages, _schema: (
                _ for _ in ()
            ).throw(TimeoutError("structured mapping timed out")),
            candidate_limit=5,
            max_turns=1,
            checkpoint=checkpoints.append,
        )

    checkpoint = checkpoints[-1]
    assert checkpoint["incomplete_blocker"]["code"] == "structured_mapping_timeout"
    assert checkpoint["resume_state"]["structured_mapping_attempts"] == 0

    result = workflow._run_batch_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        exchange,
        mapping_exchange=lambda _messages, _schema: {
            "rows": [
                {
                    "work_id": "w1",
                    "decision": "unbound",
                    "reason": "После двух поисков точная норма не найдена",
                    "unbound_evidence": _unbound_evidence(
                        queries=["буквальный поиск", "нормативный поиск"],
                    ),
                }
            ]
        },
        candidate_limit=5,
        max_turns=1,
        resume_checkpoint=checkpoint,
    )

    assert result["selections"]["w1"]["review_status"] == "model_batch_unbound"


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


def test_rim_terminal_rejects_opened_card_with_incompatible_unit():
    from proxy.smeta_core import document_workflow as workflow

    bad_code = "ГЭСНм10-06-034-03"
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Блок розеток", "unit": "шт.", "quantity": 2}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    card = {
        "norm_code": bad_code,
        "title": "Шкаф телефонный распределительный",
        "measure_unit": "шкаф",
        "work_steps": ["Установка и монтаж"],
    }
    session.candidates["w1"][bad_code] = card
    session.opened["w1"][bad_code] = card

    result = session.execute(
        "submit_lsr_mapping",
        {"rows": [{
            "work_id": "w1",
            "decision": "bind",
            "norm_code": bad_code,
            "selection_kind": "exact",
            "applicability": "exact",
            "analog_limitations": [],
            "candidate_evaluations": _candidate_evaluations(bad_code),
            "technology_check": _technology_check(),
            "reason": "модель считает карточку точной",
        }]},
        turn=1,
    )

    assert result["ok"] is False
    assert (
        "selected typed card unit is incompatible with the source work unit"
        in result["errors"][0]["details"]
    )
    assert session.accepted_rows == {}


def test_terminal_rejects_exact_bind_that_declares_missing_operations():
    from proxy.smeta_core import document_workflow as workflow

    code = "ГЭСНм10-01-052-07"
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Установка блока розеток", "unit": "шт.", "quantity": 4}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    card = {
        "norm_code": code,
        "title": "Кроссировка в шкафу",
        "measure_unit": "10 шт",
        "work_steps": ["Кроссировка"],
    }
    session.candidates["w1"][code] = card
    session.opened["w1"][code] = card

    result = session.execute(
        "submit_lsr_mapping",
        {"rows": [{
            "work_id": "w1",
            "decision": "bind",
            "norm_code": code,
            "selection_kind": "exact",
            "applicability": "exact",
            "analog_limitations": [],
            "candidate_evaluations": _candidate_evaluations(code),
            "technology_check": _technology_check(
                missing_operations=["Установка блока розеток"],
            ),
            "reason": "модель одновременно назвала норму точной и указала пропуск",
        }]},
        turn=1,
    )

    assert result["ok"] is False
    assert any(
        "selection_kind exact contradicts missing operations" in detail
        for detail in result["errors"][0]["details"]
    )
    assert session.accepted_rows == {}


def test_terminal_rejects_exact_bind_when_model_marks_selected_object_none():
    from proxy.smeta_core import document_workflow as workflow

    code = "ГЭСНм37-01-002-05"
    session = workflow.SmetaNormToolSession(
        [{
            "work_id": "w1",
            "title": "Шкаф напольный телекоммуникационный",
            "unit": "шт.",
            "quantity": 2,
        }],
        candidate_limit=4,
        require_scoped_search=True,
    )
    card = {
        "norm_code": code,
        "title": "Монтаж сосудов без механизмов массой до 1 т",
        "measure_unit": "шт.",
        "work_steps": ["Монтаж сосуда"],
    }
    session.candidates["w1"][code] = card
    session.opened["w1"][code] = card
    evaluations = _candidate_evaluations(code)
    evaluations[0]["object_match"] = "none"

    result = session.execute(
        "submit_lsr_mapping",
        {"rows": [{
            "work_id": "w1",
            "decision": "bind",
            "norm_code": code,
            "selection_kind": "exact",
            "applicability": "exact",
            "analog_limitations": [],
            "candidate_evaluations": evaluations,
            "technology_check": _technology_check(),
            "reason": "Модель назвала норму точной, но сама отвергла объект",
        }]},
        turn=1,
    )

    assert result["ok"] is False
    assert any(
        "selected candidate contradicts bind" in detail
        for detail in result["errors"][0]["details"]
    )
    assert session.accepted_rows == {}


def test_terminal_rejects_exact_bind_without_source_card_object_anchor():
    from proxy.smeta_core import document_workflow as workflow

    code = "ГЭСНм37-01-002-05"
    session = workflow.SmetaNormToolSession(
        [{
            "work_id": "w1",
            "title": "Шкаф напольный телекоммуникационный",
            "unit": "шт.",
            "quantity": 2,
        }],
        candidate_limit=4,
        require_scoped_search=True,
    )
    card = {
        "norm_code": code,
        "title": "Монтаж сосудов без механизмов массой до 1 т",
        "measure_unit": "шт.",
        "work_steps": ["Монтаж сосуда"],
    }
    session.candidates["w1"][code] = card
    session.opened["w1"][code] = card

    result = session.execute(
        "submit_lsr_mapping",
        {"rows": [{
            "work_id": "w1",
            "decision": "bind",
            "norm_code": code,
            "selection_kind": "exact",
            "applicability": "exact",
            "analog_limitations": [],
            "candidate_evaluations": _candidate_evaluations(code),
            "technology_check": _technology_check(),
            "reason": "Модель объявила разные объекты точным совпадением",
        }]},
        turn=1,
    )

    assert result["ok"] is False
    assert any(
        "share no distinctive term" in detail
        for detail in result["errors"][0]["details"]
    )
    assert session.accepted_rows == {}


def test_terminal_rejects_self_overlap_in_technology_check():
    from proxy.smeta_core import document_workflow as workflow

    assert (
        "technology_check.overlaps_with_work_ids cannot contain its own work_id"
        in workflow._technology_check_errors(
            {
                "selection_kind": "exact",
                "applicability": "exact",
                "analog_limitations": [],
                "technology_check": _technology_check(
                    overlaps_with_work_ids=["w1"],
                ),
            },
            work_id="w1",
        )
    )


def test_repeated_typed_semantic_conflict_becomes_visible_candidate_draft():
    from proxy.smeta_core import document_workflow as workflow

    code = "GESNm37-01-002-05"
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "telecommunication cabinet", "unit": "pcs", "quantity": 2}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    card = {
        "norm_code": code,
        "title": "installation of vessels without mechanisms",
        "measure_unit": "pcs",
        "work_steps": ["installation of vessel"],
    }
    session.candidates["w1"][code] = card
    session.opened["w1"][code] = card
    evaluations = _candidate_evaluations(code)
    evaluations[0]["object_match"] = "none"
    row = {
        "work_id": "w1",
        "decision": "bind",
        "norm_code": code,
        "selection_kind": "exact",
        "applicability": "exact",
        "analog_limitations": [],
        "candidate_evaluations": evaluations,
        "technology_check": _technology_check(),
        "reason": "the model insists on this opened typed card",
    }

    first = session.execute("submit_lsr_mapping", {"rows": [row]}, turn=1)
    second = session.execute("submit_lsr_mapping", {"rows": [row]}, turn=2)

    assert first["ok"] is False
    assert second["ok"] is True
    selection = session.accepted_rows["w1"]
    assert selection["norm_code"] == code
    assert selection["review_status"] == "model_batch_candidate"
    assert selection["candidate_validation_errors"]
    assert selection["precalculation_blockers"][0]["code"] == "model_candidate_mapping"
    assert selection["precalculation_blockers"][0]["memory_eligible"] is False


def test_repeated_hard_unit_conflict_never_becomes_candidate_draft():
    from proxy.smeta_core import document_workflow as workflow

    code = "GESNm10-01-001-01"
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "cable", "unit": "m", "quantity": 10}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    card = {
        "norm_code": code,
        "title": "equipment installation",
        "measure_unit": "pcs",
        "work_steps": ["installation"],
    }
    session.candidates["w1"][code] = card
    session.opened["w1"][code] = card
    row = {
        "work_id": "w1",
        "decision": "bind",
        "norm_code": code,
        "selection_kind": "exact",
        "applicability": "exact",
        "analog_limitations": [],
        "candidate_evaluations": _candidate_evaluations(code),
        "technology_check": _technology_check(),
        "reason": "model choice",
    }

    first = session.execute("submit_lsr_mapping", {"rows": [row]}, turn=1)
    second = session.execute("submit_lsr_mapping", {"rows": [row]}, turn=2)

    assert first["ok"] is False
    assert second["ok"] is False
    assert session.accepted_rows == {}
    assert any(
        "unit is incompatible" in detail
        for detail in second["errors"][0]["details"]
    )


def test_repeated_comparison_serialization_conflict_becomes_candidate_draft():
    from proxy.smeta_core import document_workflow as workflow

    selected_code = "GESNm11-07-001-05"
    unopened_code = "GESNm11-07-001-02"
    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "cable organizer", "unit": "pcs", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    selected_card = {
        "norm_code": selected_code,
        "title": "measurement circuit panel",
        "measure_unit": "pcs",
        "work_steps": ["installation"],
    }
    session.candidates["w1"][selected_code] = selected_card
    session.candidates["w1"][unopened_code] = {
        "norm_code": unopened_code,
        "title": "air supply unit",
        "measure_unit": "pcs",
    }
    session.opened["w1"][selected_code] = selected_card
    evaluations = _candidate_evaluations(selected_code, decision="rejected")
    evaluations.append(_candidate_evaluations(unopened_code, decision="rejected")[0])
    row = {
        "work_id": "w1",
        "decision": "bind",
        "norm_code": selected_code,
        "selection_kind": "exact",
        "applicability": "exact",
        "analog_limitations": [],
        "candidate_evaluations": evaluations,
        "technology_check": _technology_check(),
        "reason": "model selected the opened typed card despite comparison serialization",
    }

    first = session.execute("submit_lsr_mapping", {"rows": [row]}, turn=1)
    second = session.execute("submit_lsr_mapping", {"rows": [row]}, turn=2)

    assert first["ok"] is False
    assert second["ok"] is True
    selection = session.accepted_rows["w1"]
    assert selection["norm_code"] == selected_code
    assert selection["review_status"] == "model_batch_candidate"
    assert any(
        "must mark the submitted norm" in detail
        for detail in selection["candidate_validation_errors"]
    )


def test_structured_mapping_schema_excludes_unit_incompatible_bind_codes():
    from proxy.smeta_core import document_workflow as workflow

    schema = workflow._mapping_output_schema(
        ["w1"],
        allowed_bind_codes={"w1": ["ГЭСНм10-01-001-01"]},
    )
    variants = schema["properties"]["rows"]["items"]["oneOf"]
    bind = next(
        variant
        for variant in variants
        if variant["properties"]["decision"]["enum"] == ["bind"]
        and variant["properties"]["selection_kind"]["enum"] == ["exact"]
    )

    assert bind["properties"]["work_id"]["enum"] == ["w1"]
    assert bind["properties"]["norm_code"]["enum"] == ["ГЭСНм10-01-001-01"]
    assert bind["properties"]["applicability"]["enum"] == ["exact"]
    assert bind["properties"]["analog_limitations"]["maxItems"] == 0
    analog = next(
        variant
        for variant in variants
        if variant["properties"]["decision"]["enum"] == ["bind"]
        and variant["properties"]["selection_kind"]["enum"] == ["analog"]
    )
    assert analog["properties"]["applicability"]["enum"] == [
        "close_analog", "weak_analog",
    ]
    assert analog["properties"]["analog_limitations"]["minItems"] == 1

    no_bind_schema = workflow._mapping_output_schema(
        ["w1"],
        allowed_bind_codes={"w1": []},
    )
    assert all(
        variant["properties"]["decision"]["enum"] != ["bind"]
        for variant in no_bind_schema["properties"]["rows"]["items"]["oneOf"]
    )


def test_structured_mapping_schema_excludes_impossible_self_coverage():
    from proxy.smeta_core import document_workflow as workflow

    one_row = workflow._mapping_output_schema(
        ["w1"],
        allowed_bind_codes={"w1": []},
        allowed_coverage_targets={"w1": []},
    )
    assert [
        variant["properties"]["decision"]["enum"]
        for variant in one_row["properties"]["rows"]["items"]["oneOf"]
    ] == [["unbound"]]

    two_rows = workflow._mapping_output_schema(
        ["w1", "w2"],
        allowed_bind_codes={"w1": [], "w2": []},
        allowed_coverage_targets={"w1": ["w2"], "w2": ["w1"]},
    )
    covered = [
        variant
        for variant in two_rows["properties"]["rows"]["items"]["oneOf"]
        if variant["properties"]["decision"]["enum"] == ["covered_by"]
    ]
    assert len(covered) == 2
    assert covered[0]["properties"]["work_id"]["enum"] == ["w1"]
    assert covered[0]["properties"]["covered_by_work_id"]["enum"] == ["w2"]


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

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        exchange,
        candidate_limit=5,
        max_turns=2,
    )
    assert calls == 2
    assert result["incomplete"] is True
    assert result["incomplete_blocker"] == {
        "code": "mapping_turns_exhausted",
        "reason": "smeta model did not submit mapping within 2 model turns",
        "remaining_work_ids": ["w1"],
    }


def test_native_batch_resume_restores_in_progress_typed_checkpoint():
    from proxy.smeta_core import document_workflow as workflow

    rows = [
        {"work_id": "w1", "title": "Работа 1", "unit": "шт", "quantity": 1},
        {"work_id": "w2", "title": "Работа 2", "unit": "шт", "quantity": 1},
    ]
    session = workflow.SmetaNormToolSession(
        [rows[0]],
        candidate_limit=4,
        require_scoped_search=True,
    )
    session.family_catalog_seen.add("w1")
    resume = {
        "selections": {},
        "resume_state": {
            "schema": "smeta_norm_agent_resume_v1",
            "conversation": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "task"},
            ],
            "tool_session": session.checkpoint_state(),
            "model_trace": [],
            "context_metrics": [],
            "next_turn": 7,
            "structured_mapping_attempts": 0,
            "focus_serialization_pending": False,
            "validation_contract_version": (
                workflow.MAPPING_VALIDATION_CONTRACT_VERSION
            ),
        },
    }

    def inspect_resume(messages, _tools):
        memory = next(
            json.loads(message["content"])
            for message in reversed(messages)
            if message.get("role") == "user"
            and "smeta_norm_agent_working_memory_v1"
            in str(message.get("content") or "")
        )
        assert memory["active_phase"] == "family_select"
        raise RuntimeError("in-progress batch checkpoint restored")

    with pytest.raises(
        RuntimeError,
        match="in-progress batch checkpoint restored",
    ):
        workflow._run_native_norm_agent(
            rows,
            inspect_resume,
            candidate_limit=4,
            max_turns=8,
            batch_size=1,
            resume_result=resume,
            require_scoped_search=True,
        )


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
    variants = seen["schema"]["properties"]["rows"]["items"]["oneOf"]
    assert all(
        variant["properties"]["work_id"]["enum"] == ["w1"]
        for variant in variants
    )
    unbound_variant = next(
        variant for variant in variants
        if variant["properties"]["decision"]["enum"] == ["unbound"]
    )
    assert set(
        unbound_variant["properties"]["unbound_evidence"]["properties"]
    ) == {"rejection_reasons", "coverage_checked"}
    assert (
        unbound_variant["properties"]["unbound_evidence"]
        ["properties"]["rejection_reasons"]["maxItems"]
        == 3
    )
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

    def exchange(_messages, _tools):
        nonlocal calls
        calls += 1
        return {"tool_calls": [_native_call(
            f"search-{calls}",
            "search_norms_batch",
            items=[{
                "work_id": "w1",
                "queries": ["буквальный поиск", "нормативная формулировка"],
                "page": 1,
            }],
        )]}

    def mapping_exchange(messages, _schema):
        nonlocal mapping_calls
        mapping_calls += 1
        assert any(
            "identical deterministic request" in str(message.get("content") or "")
            for message in messages
        )
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

    assert calls == 2
    assert mapping_calls == 1
    assert result["selections"]["w1"]["reason"] == "решение модели"


def test_batch_agent_returns_to_tools_when_unbound_needs_more_evidence(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    exchange_calls = 0
    mapping_calls = 0

    def exchange(messages, _tools):
        nonlocal exchange_calls
        exchange_calls += 1
        if exchange_calls == 1:
            return {"tool_calls": [_native_call(
                "search-1", "search_norms_batch",
                items=[{"work_id": "w1", "queries": ["буквальный поиск"]}],
            )]}
        if exchange_calls == 2:
            return {"content": "Данных достаточно для вывода."}
        # After failed unbound: second distinct search (identical retry would
        # force mapping with only one query and skip the repair path).
        working_memory = next(
            json.loads(message["content"])
            for message in reversed(messages)
            if message.get("role") == "user"
            and "smeta_norm_agent_working_memory_v1"
            in str(message.get("content") or "")
        )
        assert (
            working_memory["last_submit_validation"][0]["details"][0]
            == "unbound requires at least two distinct query or scoped-search strategies"
        )
        return {"tool_calls": [_native_call(
            "search-2", "search_norms_batch",
            items=[{
                "work_id": "w1",
                "queries": ["нормативная формулировка"],
            }],
        )]}

    def mapping_exchange(_messages, _schema):
        nonlocal mapping_calls
        mapping_calls += 1
        return {"rows": [{
            "work_id": "w1",
            "decision": "unbound",
            "reason": "После выполненных поисков применимая норма не найдена",
            "unbound_evidence": _unbound_evidence(),
        }]}

    result = workflow._run_batch_norm_agent(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        exchange,
        mapping_exchange=mapping_exchange,
        candidate_limit=5,
        max_turns=5,
    )

    # First incomplete unbound becomes a visible candidate — no second mapping.
    assert exchange_calls == 2
    assert mapping_calls == 1
    assert result["selections"]["w1"]["review_status"] == "model_batch_candidate"
    assert "буквальный поиск" in set(
        result["selections"]["w1"]["unbound_evidence"]["queries_used"]
    )


def test_batch_agent_returns_to_tools_after_terminal_budget_for_positive_unopened_reference(
    monkeypatch,
):
    """A semantic validation error needs tools, not another JSON-only guess."""
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setenv("LES_SMETA_MAPPING_EVIDENCE_REPAIR_TURNS", "1")
    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": []} for query in queries
    })
    exchange_calls = 0
    mapping_calls = 0

    def exchange(messages, _tools):
        nonlocal exchange_calls
        exchange_calls += 1
        if exchange_calls == 1:
            return {"content": "Готов зафиксировать решение."}
        working_memory = next(
            json.loads(message["content"])
            for message in reversed(messages)
            if message.get("role") == "user"
            and "smeta_norm_agent_working_memory_v1"
            in str(message.get("content") or "")
        )
        assert working_memory["last_submit_validation"][0]["resolver_hint"][
            "reason_suggests_positive_applicability"
        ] is True
        return {"tool_calls": [_native_call(
            "search-after-terminal-validation",
            "search_norms_batch",
            items=[{
                "work_id": "w1",
                "queries": ["монтаж шкафа", "установка оборудования"],
            }],
        )]}

    def mapping_exchange(_messages, _schema):
        nonlocal mapping_calls
        mapping_calls += 1
        if mapping_calls == 1:
            return {"rows": [{
                "work_id": "w1",
                "decision": "covered_by",
                "covered_by_work_id": "w1",
                "reason": "Норма ГЭСНм 11-04-027 подходит для монтажа",
            }]}
        return {"rows": [{
            "work_id": "w1",
            "decision": "unbound",
            "reason": "После двух проверенных поисков применимая карточка не найдена",
            "unbound_evidence": _unbound_evidence(
                queries=["монтаж шкафа", "установка оборудования"]
            ),
        }]}

    result = workflow._run_batch_norm_agent(
        [{"work_id": "w1", "title": "Шкаф", "unit": "шт", "quantity": 1}],
        exchange,
        mapping_exchange=mapping_exchange,
        candidate_limit=5,
        max_turns=1,
    )

    assert exchange_calls == 2
    assert mapping_calls == 2
    assert result["selections"]["w1"]["review_status"] == "model_batch_unbound"


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


def test_xlsx_estimate_intake_reads_ko_vo_header_below_contract_preamble(tmp_path):
    """Printed сметный расчёт: long title block + «Ко-во» quantity column."""
    import openpyxl

    from proxy.smeta_core.source_intake import intake_vor_document

    source = tmp_path / "Сметный_расчет_№1.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Сметный расчет"
    for _ in range(17):
        sheet.append([None])
    sheet.append([
        "№ п/п", "Обоснование", "Наименование работ и затрат", "Ед. изм.",
        "Ко-во", "Цена за ед.  руб.", "Стоимость, руб.",
    ])
    sheet.append(["Материалы", "Работа", "Материалы", "Работа", "Общая стоимость"])
    sheet.append(list(range(1, 11)))
    sheet.append([1, "Договорная цена", "Кабельный ввод IP68", "шт.", 3, 0, 0])
    sheet.append([2, '- " -', "DIN-рейка, 35мм", "м.", 5, 0, 0])
    workbook.save(source)

    intake = intake_vor_document(source)

    assert intake["work_item_count"] == 2
    assert intake["work_items"][0]["title"] == "Кабельный ввод IP68"
    assert intake["work_items"][0]["unit"] == "шт."
    assert intake["work_items"][0]["quantity"] == 3.0
    assert intake["work_items"][1]["quantity"] == 5.0
    assert not any(issue.get("code") == "vor_header_not_found" for issue in intake["issues"])
















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
