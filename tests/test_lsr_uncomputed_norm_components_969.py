"""An advertised but uncomputed component remains a literal, scoped technical gap.

Private RED draft: do not claim verified until executed on the frozen parent.
The actual B1 968 shape is a transport regression, not a golden norm selection.
"""
from copy import deepcopy
import json

from openpyxl import load_workbook
import pytest

from proxy.services import gesn_service, nr_sp_service
from proxy.services.chat_evidence_application_service import (
    compact_estimator_draft_rows, parse_model_rag_result,
)
from proxy.services.lsr_result_readiness_service import build_lsr_result_readiness
from proxy.services.model_lsr_result_contract import model_lsr_result_field_instruction
from proxy.services.rim_lsr_trace_service import (
    build_lsr_trace_from_visible_rows, build_position_trace, positions_from_visible_lsr_rows,
)
from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx


CODE = "ГЭСН11-01-011-01"
REASON = "norm_components_not_calculated"
# Literal field from actual B1 968; deliberately not an endorsed addition.
ACTUAL_COMPONENTS = [{"norm_code": "ГЭСН 11-01-011-04", "evidence_refs": ["Q1.H5"]}]


class _Book:
    def lookup(self, code):
        return {"price_current": 10.0, "unit": "кг"} if code == "FIX-R1" else None


@pytest.fixture
def priced_norm(monkeypatch):
    calls = []
    card = {"code": CODE, "name": "Устройство цементной стяжки", "unit": "100 м2",
            "resources": [{"kind": "material", "code": "FIX-R1", "name": "Fixture material",
                           "unit": "кг", "per_unit": 2.0}]}

    def get_norm(code, **_kwargs):
        calls.append(code)
        assert str(code).replace(" ", "") == CODE, "The calculator must not expand components"
        return deepcopy(card)

    monkeypatch.setattr(gesn_service, "get_norm", get_norm)
    monkeypatch.setattr(nr_sp_service, "resolve", lambda *_args, **_kwargs: {
        "status": "resolved_fixture", "nr_pct": 0.0, "sp_pct": 0.0,
        "basis": "Fixture catalog", "rule_id": "fixture-rule",
    })
    return _Book(), calls


def _row(**changes):
    return {"source_row": "ВОР!R4", "operation_id": "affected-operation", "row_role": "work",
            "title": "Устройство цементной стяжки толщиной 40 мм", "unit": "м2", "quantity": 37.5,
            "norm_code": "ГЭСН 11-01-011-01", "norm_status": "EXACT", "work_row": "ВОР!R4",
            "evidence_refs": ["Q1.H2"], "open_gap": None,
            "action_match": "yes", "object_match": "yes", "condition_match": "yes",
            "unit_compatible": "yes", "composition_covers": "yes",
            "coverage": "Базовая норма на 20 мм. Толщина 40 мм формируется добавлением двух надбавок (по 5 мм) к базе.",
            **changes}


def _position(trace, index=0):
    return trace["sections"][0]["positions"][index]


def _component_warnings(trace):
    return [item for item in trace.get("warnings", []) if item.get("code") == REASON]


def test_actual_b1_shape_is_advertised_and_retained_by_parser_and_deep_compact_audit():
    row = _row(norm_components=deepcopy(ACTUAL_COMPONENTS))
    original = deepcopy(row)
    raw = json.dumps({"artifact_kind": "lsr", "rows": [row]}, ensure_ascii=False)
    assert "norm_components" in model_lsr_result_field_instruction()
    _answer, parsed = parse_model_rag_result(raw)
    assert parsed[0]["norm_components"] == ACTUAL_COMPONENTS
    audit = compact_estimator_draft_rows(parsed)
    assert audit[0]["norm_components"] == ACTUAL_COMPONENTS
    audit[0]["norm_components"][0]["norm_code"] = "Audit edit"
    assert parsed[0]["norm_components"] == original["norm_components"]
    assert row == original


def test_all_priced_base_is_not_complete_when_authored_components_were_not_calculated(priced_norm):
    book, _calls = priced_norm
    base_row = _row()
    row = _row(norm_components=deepcopy(ACTUAL_COMPONENTS))
    original = deepcopy(row)
    base = build_lsr_trace_from_visible_rows([base_row], pricebook=book)
    trace = build_lsr_trace_from_visible_rows([row], pricebook=book)
    assert base["summary"]["result_status"] == "priced_final"
    assert trace["summary"]["total"] == base["summary"]["total"] == 7.5
    assert trace["summary"]["result_status"] == "priced_partial"
    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["summary"]["preliminary_amount"] == 7.5
    assert trace["summary"]["calculated_positions"] == 0
    assert trace["summary"]["positions_built"] == 1
    pos = _position(trace)
    assert pos["summary"]["full_amount"] is None
    assert pos["summary"]["amount_status"] == "partial"
    assert REASON in pos["summary"]["completeness_reasons"]
    assert trace["row_bindings"][0]["position"]["norm_components"] == ACTUAL_COMPONENTS
    assert trace["row_bindings"][0]["source_row"] == original
    projection = trace["row_projection"][0]
    assert projection["structure_calculated"] is False
    assert projection["position_calculated"] is False
    assert REASON in projection["open_reasons"]
    assert projection["norm_status"] == "EXACT"
    assert projection["norm_code"] == CODE
    assert pos["summary"]["resource_decisions"] == _position(base)["summary"]["resource_decisions"]
    assert row == original


@pytest.mark.parametrize("owner", ["operator", "source"])
def test_attributed_position_price_cannot_complete_uncomputed_components(priced_norm, owner):
    book, _calls = priced_norm
    fields = {"confirmed_price": 2000, "price_kind": "position_total",
              "price_source": "Engineer quotation Q9.H1", "norm_components": deepcopy(ACTUAL_COMPONENTS)}
    if owner == "operator":
        fields["confirmed_by"] = "operator"
    row = _row(**fields)
    original = deepcopy(row)
    trace = build_lsr_trace_from_visible_rows([row], pricebook=book)
    assert trace["summary"]["known_amount"] == 2000
    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["summary"]["preliminary_amount"] == 2000
    assert trace["summary"]["result_status"] == "priced_partial"
    pos = _position(trace)
    assert pos["summary"]["full_amount"] is None
    assert pos["summary"]["operator_price_trace"]["price"] == 2000
    assert pos["summary"]["operator_price_trace"]["status"] == f"{owner}_confirmed_position_price"
    assert next(r for r in pos["rows"] if r["type"] == "position_total")["label"] == "Известная стоимость позиции"
    assert trace["row_projection"][0]["structure_calculated"] is False
    assert row == original


def test_same_source_sibling_is_not_degraded_and_only_affected_operation_is_researched(priced_norm):
    book, _calls = priced_norm
    affected = _row(norm_components=deepcopy(ACTUAL_COMPONENTS))
    neighbor = _row(operation_id="closed-neighbor", quantity=2, unit="м2", title="Independent operation")
    rows = [affected, neighbor]
    original = deepcopy(rows)
    trace = build_lsr_trace_from_visible_rows(rows, pricebook=book)
    assert trace["summary"]["confirmed_amount"] == .4
    assert trace["summary"]["preliminary_amount"] == 7.5
    assert trace["summary"]["calculated_positions"] == 1
    assert trace["row_projection"][1]["position_calculated"] is True
    assert trace["row_projection"][1]["open_reasons"] == []
    readiness = build_lsr_result_readiness(
        packaged=True, rows=rows, row_projection=trace["row_projection"],
        pricing_status=trace["summary"]["result_status"],
        calculated_positions=trace["summary"]["calculated_positions"], job_status="complete",
    )
    assert readiness["research_operation_ids"] == ["affected-operation"]
    assert readiness["estimate_complete"] is False
    assert rows == original


@pytest.mark.parametrize("fields", [{}, {"norm_components": None}, {"norm_components": []}, {"norm_components": ""}])
def test_absent_or_explicit_empty_components_are_no_op(priced_norm, fields):
    book, _calls = priced_norm
    row = _row(**fields)
    trace = build_lsr_trace_from_visible_rows([row], pricebook=book)
    assert trace["summary"]["result_status"] == "priced_final"
    assert trace["summary"]["confirmed_amount"] == 7.5
    assert trace["row_projection"][0]["position_calculated"] is True
    assert _component_warnings(trace) == []


@pytest.mark.parametrize("literal", ["unparsed addition 17 times", {"unexpected": [1, "x"]}, 3, False, [None]])
def test_nonempty_malformed_components_are_literal_diagnostic_only(priced_norm, literal):
    book, _calls = priced_norm
    row = _row(norm_components=deepcopy(literal))
    original = deepcopy(row)
    trace = build_lsr_trace_from_visible_rows([row], pricebook=book)
    assert trace["summary"]["positions_built"] == 1
    assert trace["summary"]["total"] == 7.5
    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["summary"]["result_status"] == "priced_partial"
    warning = _component_warnings(trace)[0]
    assert warning["source_row"] == "ВОР!R4"
    assert warning["work_id"] == "op:affected-operation"
    assert json.loads(warning["reason"].split("JSON: ", 1)[1]) == literal
    assert row == original


def test_low_level_position_honors_the_same_noncomputed_component_gap(priced_norm):
    book, _calls = priced_norm
    position = positions_from_visible_lsr_rows([_row(norm_components=ACTUAL_COMPONENTS)])["positions"][0]
    original = deepcopy(position)
    trace = build_position_trace(position, pricebook=book)
    assert trace["summary"]["amount_status"] == "partial"
    assert trace["summary"]["full_amount"] is None
    assert REASON in trace["summary"]["completeness_reasons"]
    assert position == original


def test_long_literal_roundtrips_in_existing_check_sheet_without_truncation_or_formula(priced_norm, tmp_path):
    book, _calls = priced_norm
    literal = [{"norm_code": "Authored addition", "source": "=HYPERLINK(\"ignored\") " + "Проверка 😀" * 10000}]
    row = _row(norm_components=literal)
    original = deepcopy(row)
    trace = build_lsr_trace_from_visible_rows([row], pricebook=book)
    warnings = _component_warnings(trace)
    assert len(warnings) > 1
    assert [x["fragment"] for x in warnings] == list(range(1, len(warnings) + 1))
    pieces = [x["reason"].split("JSON: ", 1)[1] for x in warnings]
    assert all(len(piece) <= 30000 for piece in pieces)
    assert json.loads("".join(pieces)) == literal
    target = render_lsr_xlsx(trace, tmp_path / "components.xlsx")
    workbook = load_workbook(target, read_only=True, data_only=False)
    try:
        check = workbook["Проверка"]
        actual = [r[3].value for r in check.iter_rows() if r[0].value == REASON]
        assert len(actual) == len(warnings)
        assert json.loads("".join(text.split("JSON: ", 1)[1] for text in actual)) == literal
        assert all("ВОР!R4" in text and "op:affected-operation" in text for text in actual)
        assert any("PRICED_PARTIAL" in str(r[0].value) for r in workbook.worksheets[0].iter_rows())
    finally:
        workbook.close()
    assert row == original


def test_unadvertised_other_field_and_coverage_prose_do_not_activate_component_gap(priced_norm):
    book, _calls = priced_norm
    row = _row(extra_unrecognized_components=ACTUAL_COMPONENTS,
               coverage="A narrative mentions another norm and four repetitions, without a structured request")
    trace = build_lsr_trace_from_visible_rows([row], pricebook=book)
    assert trace["summary"]["result_status"] == "priced_final"
    assert _component_warnings(trace) == []


@pytest.mark.parametrize("quantity", [0, 1])
def test_no_main_norm_keeps_literal_component_audit_without_creating_a_position(
    priced_norm, tmp_path, quantity,
):
    from openpyxl import Workbook
    from proxy.services.attachment_source_catalog_service import load_tabular_source_catalog
    book, calls = priced_norm
    workbook = Workbook()
    workbook.active.title = "ВОР"
    workbook.active.append([])
    workbook.active.append([])
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Literal work", "м2", quantity])
    source = tmp_path / "source.xlsx"
    workbook.save(source)
    workbook.close()
    catalog = load_tabular_source_catalog(source)
    row = _row(norm_code="", norm_status="MISSING", quantity=quantity,
               norm_components=deepcopy(ACTUAL_COMPONENTS), open_gap="Авторский состав не рассчитан")
    original = deepcopy(row)
    trace = build_lsr_trace_from_visible_rows([row], pricebook=book, source_catalog=catalog)
    assert trace["sections"] == []
    assert trace["summary"]["positions_built"] == trace["summary"]["selected_norms"] == 0
    assert trace["summary"]["result_status"] != "priced_final"
    assert trace["summary"]["confirmed_amount"] == 0
    assert not trace["row_bindings"][0].get("charge_not_required")
    assert trace["row_bindings"][0]["status"] == "missing_norm"
    assert trace["row_bindings"][0]["source_row"] == original
    warnings = _component_warnings(trace)
    assert json.loads("".join(x["reason"].split("JSON: ", 1)[1] for x in warnings)) == ACTUAL_COMPONENTS
    assert warnings[0]["source_row"] == "ВОР!R4" and warnings[0]["work_id"] == "op:affected-operation"
    target = render_lsr_xlsx(trace, tmp_path / "uncomputed-no-position.xlsx")
    output = load_workbook(target, read_only=True, data_only=False)
    try:
        audit = [r[3].value for r in output["Проверка"].iter_rows() if r[0].value == REASON]
        assert json.loads("".join(text.split("JSON: ", 1)[1] for text in audit)) == ACTUAL_COMPONENTS
    finally:
        output.close()
    assert calls == [] and row == original


def _covered_pair(component_fields):
    parent = _row(operation_id="closed-parent", title="Parent operation", coverage="Cited parent norm")
    child = _row(source_row="ВОР!R5", operation_id="component-child", title="Included operation",
                 work_row="ВОР!R5", covered_by_work_id="closed-parent",
                 coverage="The cited composition includes this operation", **component_fields)
    return [parent, child]


def test_covered_child_component_is_owner_scoped_technical_gap_not_a_new_charge(priced_norm):
    book, _calls = priced_norm
    rows = _covered_pair({"norm_components": deepcopy(ACTUAL_COMPONENTS)})
    original = deepcopy(rows)
    trace = build_lsr_trace_from_visible_rows(rows, pricebook=book)
    assert trace["summary"]["positions_built"] == trace["summary"]["calculated_positions"] == 1
    assert trace["summary"]["known_amount"] == trace["summary"]["confirmed_amount"] == 7.5
    assert trace["summary"]["preliminary_amount"] == 0
    assert trace["summary"]["result_status"] == "priced_partial"
    assert trace["summary"]["full_amount"] is None
    assert _position(trace)["summary"]["amount_status"] == "complete"
    parent, child = trace["row_bindings"]
    assert parent["readiness"]["position_calculated"] is True
    assert parent["readiness"]["open_reasons"] == []
    assert child["status"] == "covered"
    assert child["covered_by_operation_id"] == "op:closed-parent"
    assert child["readiness"]["structure_calculated"] is False
    assert child["readiness"]["position_calculated"] is False
    assert REASON in child["readiness"]["open_reasons"]
    assert child["source_row"] == original[1]
    warnings = _component_warnings(trace)
    assert len(warnings) == 1 and warnings[0]["work_id"] == "op:component-child"
    assert json.loads(warnings[0]["reason"].split("JSON: ", 1)[1]) == ACTUAL_COMPONENTS
    readiness = build_lsr_result_readiness(
        packaged=True, rows=rows, row_projection=trace["row_projection"],
        pricing_status=trace["summary"]["result_status"],
        calculated_positions=trace["summary"]["calculated_positions"], job_status="complete",
    )
    assert readiness["research_operation_ids"] == ["component-child"]
    assert readiness["gap_states"]["calculation_incomplete"]["count"] == 1
    assert readiness["estimate_complete"] is False
    assert rows == original


@pytest.mark.parametrize("fields", [{}, {"norm_components": None}, {"norm_components": []}, {"norm_components": ""}])
def test_ordinary_covered_child_remains_complete_and_never_researched(priced_norm, fields):
    book, _calls = priced_norm
    rows = _covered_pair(fields)
    original = deepcopy(rows)
    trace = build_lsr_trace_from_visible_rows(rows, pricebook=book)
    assert trace["summary"]["result_status"] == "priced_final"
    assert trace["summary"]["confirmed_amount"] == trace["summary"]["full_amount"] == 7.5
    assert trace["row_bindings"][1]["status"] == "covered"
    assert trace["row_projection"][1]["position_calculated"] is True
    assert _component_warnings(trace) == []
    readiness = build_lsr_result_readiness(
        packaged=True, rows=rows, row_projection=trace["row_projection"],
        pricing_status=trace["summary"]["result_status"],
        calculated_positions=trace["summary"]["calculated_positions"], job_status="complete",
    )
    assert readiness["research_operation_ids"] == []
    assert rows == original


@pytest.mark.parametrize("reasons", [["another_reason"], ["norm_components_not_calculated_extra"], REASON])
def test_financial_covered_exception_requires_exact_listed_technical_reason(reasons):
    from proxy.services.lsr_financial_feedback_service import incomplete_financial_operations
    row = _row(operation_id="component-child")
    projection = {"locator": row["source_row"], "operation_id": "op:component-child",
                  "row_role": "work", "status": "covered", "position_calculated": False,
                  "open_reasons": reasons}
    assert incomplete_financial_operations([row], [projection]) == []
