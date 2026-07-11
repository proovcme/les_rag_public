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


def test_bind_tool_exposes_no_ambiguous_quantity_multiplier():
    from proxy.smeta_core import document_workflow as workflow

    bind_tool = next(
        item for item in workflow._native_norm_tools()
        if item["function"]["name"] == "bind_norm"
    )
    properties = bind_tool["function"]["parameters"]["properties"]

    assert "quantity_multiplier" not in properties
    assert "operation_repeat_multiplier" not in properties
    assert "accepts no quantity multiplier" in bind_tool["function"]["description"]
    assert properties["decision"]["enum"] == ["selected"]
    assert "decision" in bind_tool["function"]["parameters"]["required"]
    assert properties["technology_check"]["properties"]["conclusion"]["enum"] == [
        "applicable", "applicable_with_limitations"
    ]


def test_analog_without_explicit_resource_review_stays_unresolved(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "name": "Норма-аналог",
        "unit": "100 шт",
        "work_steps": ["Монтаж"],
        "resources": [{"kind": "machine", "code": "91.1", "name": "Кран", "unit": "маш.-ч", "per_unit": 1}],
    })
    monkeypatch.setattr(workflow.fgis_price_service, "resolve_pricebook_path", lambda *_args, **_kwargs: None)

    result = workflow._apply_model_resource_plan(
        [{
            "work_id": "w1", "title": "Монтаж коробки", "unit": "шт", "quantity": 8,
            "norm_code": "ГЭСНм08-02-420-01", "selection_kind": "analog",
        }],
        lambda _messages: '{"rows":[{"work_id":"w1","resource_actions":[]}]}',
        book=None,
        batch_size=4,
        vat_pct=22,
    )

    row = result["rows"][0]
    assert row["resource_review_status"] == "unresolved"
    assert row["resource_bindings"] == []


def test_model_resource_action_contract_is_applied(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "name": "Норма-аналог", "unit": "100 м2", "work_steps": ["Окраска"],
        "resources": [{"kind": "material", "code": "14.1", "name": "Чужая грунтовка", "unit": "кг", "per_unit": 2}],
    })
    monkeypatch.setattr(workflow.fgis_price_service, "resolve_pricebook_path", lambda *_args, **_kwargs: None)
    response = {
        "rows": [{
            "work_id": "w1",
            "resource_review_status": "actions_confirmed",
            "resource_review_reason": "подготовка выполнена отдельной строкой",
            "labor_review_status": "not_present",
            "labor_review_reason": "",
            "machine_review_status": "not_present",
            "machine_review_reason": "",
            "material_review_status": "confirmed",
            "material_review_reason": "материал проверен и исключается как повторный",
            "resource_actions": [{
                "action": "exclude",
                "target_resource_code": "14.1",
                "reason": "не учитывать повторно",
            }],
        }],
    }

    result = workflow._apply_model_resource_plan(
        [{"work_id": "w1", "title": "Окраска", "unit": "м2", "quantity": 10, "norm_code": "ГЭСН15-04-007-04"}],
        lambda _messages: json.dumps(response, ensure_ascii=False),
        book=None,
        batch_size=4,
        vat_pct=22,
    )

    row = result["rows"][0]
    assert row["resource_review_status"] == "actions_confirmed"
    assert row["resource_bindings"][0]["action"] == "exclude"
    assert row["resource_bindings"][0]["target_resource_code"] == "14.1"


def test_analog_component_review_exposes_total_labor_and_blocks_rejected_component(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "code": "ГЭСНм08-03-641-01",
        "name": "Норма-аналог",
        "unit": "шт",
        "work_steps": ["Монтаж"],
        "resources": [
            {"kind": "labor", "code": "1-100-33", "name": "Рабочие", "unit": "чел.-ч", "per_unit": 18},
            {"kind": "material", "code": "01.1", "name": "Коробка", "unit": "шт", "per_unit": 1},
        ],
        "_source_kind": "seed_yaml",
    })
    monkeypatch.setattr(workflow.fgis_price_service, "resolve_pricebook_path", lambda *_args, **_kwargs: None)
    captured = {}

    def complete(messages):
        captured["payload"] = json.loads(messages[1]["content"])["work_rows"][0]
        return json.dumps({"rows": [{
            "work_id": "w1",
            "resource_review_status": "keep_all_confirmed",
            "resource_review_reason": "материалы применимы, труд аналога не защищаем",
            "labor_review_status": "rejected",
            "labor_review_reason": "144 чел.-ч на 8 небольших коробок технологически несоразмерны",
            "machine_review_status": "not_present",
            "machine_review_reason": "",
            "material_review_status": "confirmed",
            "material_review_reason": "изделие соответствует исходной строке",
            "resource_actions": [],
        }]}, ensure_ascii=False)

    result = workflow._apply_model_resource_plan(
        [{
            "work_id": "w1", "title": "Монтаж коробки", "unit": "шт", "quantity": 8,
            "norm_code": "ГЭСНм08-03-641-01", "selection_kind": "analog",
        }],
        complete,
        book=None,
        batch_size=4,
        vat_pct=22,
    )

    assert captured["payload"]["cost_driver_preview"]["labor_hours"] == 144
    assert result["rows"][0]["labor_review_status"] == "rejected"
    assert result["rows"][0]["resource_review_status"] == "unresolved"


def test_unconfirmed_analog_labor_is_excluded_from_known_cost_components(monkeypatch):
    from proxy.smeta_core import calculator
    from proxy.services import gesn_service

    norm = {
        "code": "ГЭСНм08-03-641-01",
        "name": "Норма-аналог",
        "unit": "шт",
        "resources": [
            {"kind": "labor", "code": "1-100-33", "name": "Рабочие", "unit": "чел.-ч", "per_unit": 18},
            {"kind": "material", "code": "01.1", "name": "Коробка", "unit": "шт", "per_unit": 1},
        ],
        "_source_kind": "seed_yaml",
    }
    monkeypatch.setattr(gesn_service, "get_norm", lambda *_args, **_kwargs: norm)
    monkeypatch.setattr(calculator, "_pricebook", lambda _book: None)
    captured = {}

    def build_lsr_trace(positions, **_kwargs):
        captured["positions"] = positions
        return {"sections": [], "summary": {"total": 0.0, "full_amount": None, "flags": []}}

    monkeypatch.setattr(calculator.rim, "build_lsr_trace", build_lsr_trace)
    calculator.calculate_scenario(
        [WorkItem(work_id="w1", title="Монтаж коробки", quantity=8, unit="шт")],
        [NormBinding(
            work_id="w1", norm_code="ГЭСНм08-03-641-01", selected_by="model",
            selection_kind="analog", is_analog=True, reason="аналог",
            analog_limitations=("труд требует проверки",), applicability="close_analog",
        )],
        resource_reviews=[ResourceReview(
            work_id="w1", status="unresolved", selected_by="model", reason="труд отклонен",
            labor_status="rejected", labor_reason="144 чел.-ч несоразмерны",
            machine_status="not_present", material_status="confirmed", material_reason="материал применим",
        )],
    )

    assert [item["kind"] for item in captured["positions"][0]["resources"]] == ["material"]


def test_dominant_position_requires_second_model_confirmation(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "work_steps": ["Монтаж коробки"], "resources": [],
    })
    rows = [{
        "work_id": "w1", "title": "Монтаж коробки", "quantity": 8, "unit": "шт",
        "norm_code": "ГЭСНм08-03-641-01", "selection_kind": "analog",
        "labor_review_status": "confirmed", "labor_review_reason": "первичная проверка",
        "machine_review_status": "not_present", "machine_review_reason": "",
        "material_review_status": "confirmed", "material_review_reason": "первичная проверка",
        "resource_review_status": "keep_all_confirmed", "resource_review_reason": "первичная проверка",
    }]
    preliminary = {
        "sections": [{"positions": [{
            "work_id": "w1",
            "summary": {"known_amount": 196366, "labor_qty": 144, "machinist_qty": 0, "flags": []},
        }]}],
    }

    result = workflow._review_dominant_positions(
        rows,
        preliminary,
        {"w1": []},
        lambda _messages: json.dumps({"rows": [{
            "work_id": "w1", "status": "unresolved",
            "reason": "144 чел.-ч не защищены технологией небольшой коробки",
            "labor_review_status": "rejected",
            "machine_review_status": "not_present",
            "material_review_status": "confirmed",
        }]}, ensure_ascii=False),
    )

    assert result["reviewed_work_ids"] == ["w1"]
    assert rows[0]["dominant_review_status"] == "unresolved"
    assert rows[0]["labor_review_status"] == "rejected"
    assert rows[0]["resource_review_status"] == "unresolved"


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


def test_document_workflow_uses_one_native_tool_conversation(monkeypatch, tmp_path):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "intake_vor_pdf", lambda _path: {
        "work_items": [
            {"work_id": "w1", "title": "Монтаж элемента", "unit": "шт", "quantity": 2, "source_refs": ["pdf:p1:r1"]},
            {"work_id": "w2", "title": "Крепление элемента", "unit": "шт", "quantity": 2, "source_refs": ["pdf:p1:r2"]},
        ]
    })
    monkeypatch.setattr(workflow, "_candidate_payload", lambda work, _query, limit, **_kwargs: {
        "work_id": work["work_id"],
        "source": work,
        "candidates": [{"norm_code": "ГЭСН01-01-001-01", "nr_sp_candidates": []}],
    })
    retrieval_batches = []

    def browse_many(queries, limit, **_kwargs):
        retrieval_batches.append(list(queries))
        return {}

    monkeypatch.setattr(workflow, "browse_norms_many", browse_many)
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "name": "Монтаж элемента", "unit": "шт", "work_steps": ["Установка элемента."], "resources": []
    })
    monkeypatch.setattr(workflow.fgis_price_service, "resolve_pricebook_path", lambda *_args, **_kwargs: None)
    captured = {}

    def calculate(rows, **_kwargs):
        captured["rows"] = rows
        return {"summary": {"result_status": "priced_final", "input_rows": 2, "bound_rows": 1, "unbound_rows": 1}}

    monkeypatch.setattr(workflow, "calculate_visible_rows_revision", calculate)
    monkeypatch.setattr(workflow, "render_lsr_xlsx", lambda _trace, path, meta=None: tmp_path.joinpath("out.xlsx").write_text("xlsx"))
    monkeypatch.setattr(
        workflow, "_apply_model_resource_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("resource review must follow first LSR")),
    )
    monkeypatch.setattr(
        workflow, "_review_dominant_positions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("dominant review must follow first LSR")),
    )
    complete_calls = 0

    def complete(messages):
        nonlocal complete_calls
        complete_calls += 1
        system = messages[0]["content"]
        if "управляешь read-only инструментами" in system:
            states = json.loads(messages[1]["content"])["work_states"]
            rows = []
            for state in states:
                work_id = state["work_id"]
                if not state["candidates"]:
                    rows.append({"work_id": work_id, "action": "search_norms", "queries": ["монтаж элемента"]})
                elif not state["opened_norms"]:
                    rows.append({"work_id": work_id, "action": "read_norm", "norm_codes": ["ГЭСН01-01-001-01"]})
                else:
                    rows.append({
                        "work_id": work_id, "action": "select_norm", "norm_code": "ГЭСН01-01-001-01",
                        "selection_kind": "exact", "analog_limitations": [], "reason": "точное соответствие",
                    })
            return json.dumps({"rows": rows}, ensure_ascii=False)
        if "resource_actions" in system:
            captured["resource_evidence"] = json.loads(messages[1]["content"])["work_rows"]
            return json.dumps({"rows": [
                {"work_id": "w1", "resource_review_status": "keep_all_confirmed", "resource_review_reason": "ресурсы соответствуют", "resource_actions": []},
                {"work_id": "w2", "resource_review_status": "unresolved", "resource_review_reason": "норма не выбрана", "resource_actions": []},
            ]}, ensure_ascii=False)
        return '{"rows":[]}'

    turns = iter([
        [_native_call("s1", "search_norms", work_id="w1", queries=["монтаж элемента"]),
         _native_call("s2", "search_norms", work_id="w2", queries=["крепление элемента"])],
        [_native_call("r1", "read_norm", work_id="w1", norm_codes=["ГЭСН01-01-001-01"])],
        [_native_call("b1", "bind_norm", work_id="w1", decision="selected", norm_code="ГЭСН01-01-001-01",
                      selection_kind="exact", applicability="exact", analog_limitations=[],
                      technology_check={"matched_operations":["монтаж"],"missing_operations":[],"extra_operations":[],"foreign_resources":[],"conclusion":"applicable"},
                      reason="точное соответствие"),
         _native_call("u2", "leave_unbound", work_id="w2", reason="учтено основной нормой")],
        [_native_call("f1", "finish_norm_selection")],
    ])

    def exchange(_messages, _tools):
        return {"role": "assistant", "content": None, "tool_calls": next(turns)}

    result = workflow.run_vor_pdf_workflow(tmp_path / "source.pdf", complete, exchange=exchange)

    assert result["schema"] == "smeta_document_workflow_v2"
    assert captured["rows"][0]["norm_code"] == "ГЭСН01-01-001-01"
    assert captured["rows"][1]["norm_code"] == ""
    assert result["resource_plan"]["status"] == "deferred_after_first_lsr"
    assert result["dominant_review"]["status"] == "deferred_after_first_lsr"
    assert complete_calls == 0
    assert result["agent_trace"]["mode"] == "model_direct_rag_tool_loop"
    assert result["agent_trace"]["finished"] is True
    assert len(retrieval_batches) == 1
    assert set(retrieval_batches[0]) == {"монтаж элемента", "крепление элемента"}


def test_native_agent_caches_search_and_keeps_opened_norm_evidence_visible(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    browse_calls = []
    snapshots = []

    def browse_many(queries, **_kwargs):
        browse_calls.append(list(queries))
        return {
            query: {
                "backend": "test",
                "cards": [{"norm_code": "ГЭСН01-01-001-01", "title": "Монтаж", "measure_unit": "шт"}],
                "retrieval_trace": {"embedding_ms": 1, "retrieval_ms": 1, "rerank_ms": 0},
            }
            for query in queries
        }

    monkeypatch.setattr(workflow, "browse_norms_many", browse_many)
    monkeypatch.setattr(workflow, "_candidate_payload", lambda work, _queries, limit, **_kwargs: {
        "work_id": work["work_id"],
        "source": work,
        "backend": "test",
        "candidates": [{
            "norm_code": "ГЭСН01-01-001-01", "title": "Монтаж", "measure_unit": "шт",
            "unit_compatible": True, "nr_sp_candidates": [], "resource_preview": [],
        }],
    })
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "name": "Монтаж", "unit": "шт",
        "work_steps": [f"Операция {index}" for index in range(24)],
        "resources": [
            {"code": f"R-{index}", "name": f"Ресурс {index}", "unit": "шт", "kind": "material", "per_unit": 1}
            for index in range(30)
        ],
    })

    turns = iter([
        [_native_call("s1", "search_norms", work_id="w1", queries=["монтаж элемента"])],
        [_native_call("r1", "read_norm", work_id="w1", norm_codes=["ГЭСН01-01-001-01"])],
        [_native_call("s2", "search_norms", work_id="w1", queries=["монтаж элемента"])],
        [_native_call(
            "b1", "bind_norm", work_id="w1", decision="selected", norm_code="ГЭСН01-01-001-01",
            selection_kind="exact", applicability="exact", analog_limitations=[],
            technology_check={
                "matched_operations": ["монтаж"], "missing_operations": [], "extra_operations": [],
                "foreign_resources": [], "conclusion": "applicable",
            }, reason="точное соответствие",
        )],
        [_native_call("f1", "finish_norm_selection")],
    ])

    def exchange(messages, _tools):
        snapshots.append(json.loads(messages[1]["content"]))
        return {"role": "assistant", "content": None, "tool_calls": next(turns)}

    result = workflow._run_native_norm_agent(
        [{"work_id": "w1", "title": "Монтаж элемента", "unit": "шт", "quantity": 1}],
        exchange,
        candidate_limit=5,
    )

    assert browse_calls == [["монтаж элемента"]]
    assert snapshots[2]["working_set"][0]["opened_norms"][0]["resources"]
    assert snapshots[3]["working_set"][0]["opened_norms"][0]["norm_code"] == "ГЭСН01-01-001-01"
    assert result["agent_trace"]["search_cache_entries"] == 1
    assert sum(item.get("search_cache_hits", 0) for item in result["agent_trace"]["context_metrics"]) == 1


def test_price_candidate_menus_are_sent_to_model_in_one_batch():
    from proxy.smeta_core import document_workflow as workflow

    calls = []
    items = [
        {
            "choice_id": f"price-{index}",
            "action": {"resource_name": f"Материал {index}", "unit": "шт"},
            "candidates": [
                {"code": f"C-{index}", "name": f"Материал {index}", "unit": "шт", "price_current_eff": 10},
            ],
        }
        for index in range(1, 11)
    ]

    def complete(messages):
        payload = json.loads(messages[1]["content"])
        calls.append(payload)
        return json.dumps({
            "rows": [
                {
                    "choice_id": item["choice_id"],
                    "resource_code": item["candidates"][0]["code"],
                    "needs_kac": False,
                    "reason": "точное совпадение",
                }
                for item in payload["items"]
            ]
        }, ensure_ascii=False)

    choices, _raw = workflow._choose_price_candidates_batch(items, complete)

    assert len(calls) == 1
    assert len(calls[0]["items"]) == 10
    assert choices["price-10"]["resource_code"] == "C-10"


def test_document_execution_budget_scales_to_fifty_rows():
    from proxy.smeta_core.document_workflow import document_execution_budget

    small = document_execution_budget(19)
    fifty = document_execution_budget(50)

    assert small == {
        "source_rows": 19, "batches": 1, "max_calls": 16, "deadline_sec": 360.0,
    }
    assert fifty["source_rows"] == 50
    assert fifty["batches"] == 3
    assert fifty["max_calls"] >= 24
    assert fifty["deadline_sec"] >= 600


def test_bind_norm_machine_contract_does_not_require_review_gate():
    from proxy.smeta_core.document_workflow import _native_norm_tools

    bind_tool = next(
        item for item in _native_norm_tools()
        if (item.get("function") or {}).get("name") == "bind_norm"
    )
    required = set(bind_tool["function"]["parameters"]["required"])

    assert required == {"work_id", "decision", "norm_code", "selection_kind", "reason"}
    assert "technology_check" not in required
    assert "applicability" not in required
    assert "resource_review_status" not in bind_tool["function"]["parameters"]["properties"]


def test_native_agent_keeps_fifty_rows_in_one_model_owned_workflow():
    from proxy.smeta_core import document_workflow as workflow

    rows = [
        {"work_id": f"w{index:02d}", "title": f"Работа {index}", "unit": "шт", "quantity": index}
        for index in range(1, 51)
    ]
    payload_sizes = []
    turn = 0

    def exchange(messages, _tools):
        nonlocal turn
        turn += 1
        payload = json.loads(messages[1]["content"])
        payload_sizes.append(len(payload["working_set"]))
        if turn == 1:
            return {"tool_calls": [
                _native_call(f"u-{row['work_id']}", "leave_unbound", work_id=row["work_id"], reason="модель не выбрала норму")
                for row in rows
            ]}
        return {"tool_calls": [_native_call("finish", "finish_norm_selection")]}

    result = workflow._run_native_norm_agent(rows, exchange, candidate_limit=8)

    assert payload_sizes == [50, 0]
    assert len(result["selections"]) == 50
    assert all(item["review_status"] == "native_agent_unbound" for item in result["selections"].values())
    assert result["agent_trace"]["finished"] is True


def test_ten_fgis_material_choices_cost_one_model_call(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "name": "Монтаж", "unit": "шт", "work_steps": ["Монтаж"], "resources": [],
    })

    class Pricebook:
        def browse(self, query, limit=12):
            index = query.rsplit(" ", 1)[-1]
            return [{
                "code": f"C-{index}", "name": query, "unit": "шт",
                "price_current_eff": 100, "region": "СПб", "quarter": "2кв2026", "match": "exact",
            }]

    monkeypatch.setattr(workflow.fgis_price_service, "resolve_pricebook_path", lambda *_args, **_kwargs: "prices.parquet")
    monkeypatch.setattr(workflow.fgis_price_service, "get_pricebook", lambda *_args, **_kwargs: Pricebook())
    stages = []

    def complete(messages):
        system = messages[0]["content"]
        payload = json.loads(messages[1]["content"])
        if "Для каждой уже выбранной нормы" in system:
            stages.append("resource")
            return json.dumps({"rows": [{
                "work_id": item["work_id"],
                "resource_review_status": "actions_confirmed",
                "resource_review_reason": "добавлен проектный материал",
                "labor_review_status": "not_present", "labor_review_reason": "",
                "machine_review_status": "not_present", "machine_review_reason": "",
                "material_review_status": "not_present", "material_review_reason": "",
                "resource_actions": [{
                    "action": "add", "resource_name": f"Материал {item['work_id'][1:]}", "unit": "шт",
                    "quantity_basis": "source_work", "price_query": f"Материал {item['work_id'][1:]}",
                    "reason": "материал задан исходником",
                }],
            } for item in payload["work_rows"]]}, ensure_ascii=False)
        if "Независимо выбери строку ФГИС" in system:
            stages.append("price")
            return json.dumps({"rows": [{
                "choice_id": item["choice_id"],
                "resource_code": item["candidates"][0]["code"],
                "needs_kac": False, "reason": "точное совпадение",
            } for item in payload["items"]]}, ensure_ascii=False)
        raise AssertionError(system)

    rows = [{
        "work_id": f"w{index}", "title": f"Работа {index}", "unit": "шт", "quantity": 1,
        "norm_code": f"ГЭСН01-01-001-{index:02d}", "selection_kind": "exact",
    } for index in range(1, 11)]

    result = workflow._apply_model_resource_plan(
        rows, complete, book=None, batch_size=20, vat_pct=22,
    )

    assert stages == ["resource", "price"]
    assert len(result["model_trace"]) == 1
    assert len(result["price_model_trace"]) == 1
    assert len(result["price_trace"]) == 10


def test_document_workflow_fails_closed_when_model_returns_no_json(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "intake_vor_pdf", lambda _path: {
        "work_items": [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}]
    })
    monkeypatch.setattr(workflow, "_candidate_payload", lambda work, _query, limit, **_kwargs: {
        "work_id": work["work_id"], "source": work, "candidates": []
    })
    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, limit, **_kwargs: {})

    with pytest.raises(RuntimeError, match="stopped before finish_norm_selection"):
        workflow.run_vor_pdf_workflow(
            "source.pdf",
            lambda _messages: "",
            exchange=lambda _messages, _tools: {"role": "assistant", "content": "done"},
        )


def test_norm_agent_rejects_code_outside_opened_candidates(monkeypatch, tmp_path):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "intake_vor_pdf", lambda _path: {
        "work_items": [{
            "work_id": "w1", "title": "Монтаж устройства", "unit": "шт", "quantity": 1,
            "section": "ЭОМ", "source_refs": ["pdf:p1:r1"],
        }]
    })
    monkeypatch.setattr(workflow, "_candidate_payload", lambda work, _query, limit, **_kwargs: {
        "work_id": work["work_id"], "source": work,
        "candidates": [{"norm_code": "ГЭСНм08-03-575-01", "measure_unit": "шт", "nr_sp_candidates": []}],
    })
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "name": "Установка устройства", "unit": "шт", "resources": [],
    })
    monkeypatch.setattr(workflow.fgis_price_service, "resolve_pricebook_path", lambda *_args, **_kwargs: None)
    captured = {}

    def calculate(rows, **_kwargs):
        captured["rows"] = rows
        return {"summary": {"result_status": "priced_final", "input_rows": 1, "bound_rows": 1}}

    monkeypatch.setattr(workflow, "calculate_visible_rows_revision", calculate)
    monkeypatch.setattr(workflow, "render_lsr_xlsx", lambda _trace, path, meta=None: Path(path).write_text("xlsx"))

    def complete(messages):
        system = messages[0]["content"]
        if "управляешь read-only инструментами" in system:
            payload = json.loads(messages[1]["content"])
            step = payload["step"]
            if step == 1:
                return '{"rows":[{"work_id":"w1","action":"search_norms","queries":["установка устройства"]}]}'
            if step < payload["max_steps"]:
                return '{"rows":[{"work_id":"w1","action":"select_norm","norm_code":"ГЭСНм08-03-999-99","selection_kind":"exact","analog_limitations":[],"reason":"чужой код"}]}'
            return '{"rows":[{"work_id":"w1","action":"unbound","reason":"нет защищаемой нормы"}]}'
        if "resource_actions" in system:
            return '{"rows":[{"work_id":"w1","resource_review_status":"keep_all_confirmed","resource_review_reason":"ресурсы соответствуют","resource_actions":[]}]}'
        return '{"rows":[]}'

    turns = iter([
        [_native_call("s1", "search_norms", work_id="w1", queries=["установка устройства"])],
        [_native_call("r1", "read_norm", work_id="w1", norm_codes=["ГЭСНм08-03-575-01"])],
        [_native_call("b1", "bind_norm", work_id="w1", decision="selected", norm_code="ГЭСНм08-03-999-99",
                      selection_kind="exact", applicability="exact", analog_limitations=[],
                      technology_check={"matched_operations":["монтаж"],"missing_operations":[],"extra_operations":[],"foreign_resources":[],"conclusion":"applicable"},
                      reason="чужой код")],
        [_native_call("u1", "leave_unbound", work_id="w1", reason="нет защищаемой нормы")],
        [_native_call("f1", "finish_norm_selection")],
    ])

    def exchange(_messages, _tools):
        return {"role": "assistant", "content": None, "tool_calls": next(turns)}

    result = workflow.run_vor_pdf_workflow(
        tmp_path / "source.pdf", complete, exchange=exchange,
        out_xlsx=tmp_path / "out.xlsx", out_report=tmp_path / "out.json",
    )

    assert captured["rows"][0]["norm_code"] == ""
    assert result["selections"]["w1"]["reason"] == "нет защищаемой нормы"


def test_query_navigation_receives_same_section_neighbors(monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    monkeypatch.setattr(workflow, "intake_vor_pdf", lambda _path: {
        "work_items": [
            {"work_id": "w1", "title": "Прокладка кабеля", "unit": "м", "quantity": 10, "section": "ЭОМ"},
            {"work_id": "w2", "title": "Прокладка трубы ПВХ", "unit": "м", "quantity": 10, "section": "ЭОМ"},
        ]
    })
    candidate_seen = []

    def candidate_payload(work, _query, limit, **_kwargs):
        candidate_seen.append(work)
        return {"work_id": work["work_id"], "source": work, "candidates": []}

    monkeypatch.setattr(workflow, "_candidate_payload", candidate_payload)
    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, limit, **_kwargs: {})
    monkeypatch.setattr(workflow, "calculate_visible_rows_revision", lambda rows, **_kwargs: {
        "summary": {"result_status": "priced_partial", "input_rows": len(rows), "bound_rows": 0}
    })
    monkeypatch.setattr(workflow, "render_lsr_xlsx", lambda *_args, **_kwargs: None)
    seen = []

    def complete(messages):
        if "управляешь read-only инструментами" in messages[0]["content"]:
            payload = json.loads(messages[1]["content"])
            seen.extend(payload["work_states"])
            if payload["step"] < payload["max_steps"]:
                return json.dumps({"rows": [
                    {"work_id": state["work_id"], "action": "search_norms", "queries": [state["source"]["title"]]}
                    for state in payload["work_states"]
                ]}, ensure_ascii=False)
            return json.dumps({"rows": [
                {"work_id": state["work_id"], "action": "unbound", "reason": "нет кандидатов"}
                for state in payload["work_states"]
            ]}, ensure_ascii=False)
        return '{"rows":[]}'

    turns = iter([
        [_native_call("s1", "search_norms", work_id="w1", queries=["Прокладка кабеля"]),
         _native_call("s2", "search_norms", work_id="w2", queries=["Прокладка трубы ПВХ"])],
        [_native_call("u1", "leave_unbound", work_id="w1", reason="нет кандидатов"),
         _native_call("u2", "leave_unbound", work_id="w2", reason="нет кандидатов")],
        [_native_call("f1", "finish_norm_selection")],
    ])

    def exchange(messages, _tools):
        if not seen:
            seen.extend(
                item["source"]
                for item in json.loads(messages[1]["content"])["working_set"]
            )
        return {"role": "assistant", "content": None, "tool_calls": next(turns)}

    workflow.run_vor_pdf_workflow("source.pdf", complete, exchange=exchange)

    assert seen[0]["neighbor_context"][0]["work_id"] == "w2"
    assert seen[1]["neighbor_context"][0]["work_id"] == "w1"
    assert candidate_seen[0]["neighbor_context"][0]["work_id"] == "w2"


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
