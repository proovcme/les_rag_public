"""Generic VOR workflow boundaries; no client document identities or answers."""
import copy
import json

import pytest

from proxy.services import chat_evidence_application_service as service


@pytest.mark.parametrize("query", [
    "[Source Ω!R8] Installation of an item",
    "Устройство слоя [тип А]",
    "Устройство узла {вариант}",
    '"Quoted literal query Ω"',
    "search_sources('Literal item Ω')",
])
def test_explicit_json_queries_are_literals_not_a_second_document_transport(query):
    raw = json.dumps({"artifact_kind": "vor", "queries": [query, "Other literal operation"],
                      "commentary": "This explanation is never a search."}, ensure_ascii=False)
    declared = service.read_model_query_response(raw)
    assert [item.text for item in declared["queries"]] == [query, "Other literal operation"]
    assert not declared["accompanying_answer"]
    assert declared["commentary"] == "This explanation is never a search."


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_sheet_progress_does_not_claim_norm_research_before_any_query(tmp_path, monkeypatch, variant):
    from tests import test_model_rag_sheet_evidence_reads as fixture

    events = []
    boundary = service.ResponseBoundary

    async def sink(event):
        events.append(copy.deepcopy(event))

    monkeypatch.setattr(service, "ResponseBoundary", lambda **kwargs: boundary(**{**kwargs, "token_sink": sink}))
    original = fixture._answer
    monkeypatch.setattr(fixture, "_answer", lambda **kwargs: original(**kwargs).replace(
        "artifact_kind: lsr", "artifact_kind: vor").replace("| material |", "| work |"))
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
                                   query_declaration='{"artifact_kind":"vor","queries":[]}')
    progress = [event["data"] for event in events if event["event"] == "tool_progress"]
    assert progress
    if variant == "B1_CANDIDATE":
        assert "обработка строк" in progress[0]["label"]
    else:
        assert not any("Лист «" in event["label"] for event in progress)
    assert all("поиск норм" not in event["label"] for event in progress)
    assert not run.queries
    assert run.executions[0][0]["tool"] == "build_vor_workbook"


def test_vor_readiness_reports_invalid_supply_links_without_inventing_work():
    rows = [
        {"source_row": "Раздел Ω!R2", "row_role": "work", "title": "Самостоятельная операция",
         "unit": "шт", "quantity": 2, "open_gap": ""},
        {"source_row": "Раздел Ω!R3", "row_role": "material", "title": "Отдельное изделие",
         "unit": "шт", "quantity": 2, "work_row": "Раздел Ω!R3", "open_gap": ""},
    ]
    before = copy.deepcopy(rows)
    readiness = service.build_vor_result_readiness(rows=rows, has_file=True, remaining_locators=[],
        catalog_work_count=2, model_errors=[])
    assert not readiness["vor_complete"]
    assert readiness["row_integrity_issues"][0]["code"] == "invalid_work_relationship"
    assert readiness["open_questions"]
    assert rows == before


@pytest.mark.asyncio
async def test_vor_export_exposes_relationship_errors_and_retains_authored_rows(tmp_path):
    import openpyxl
    from proxy.services.workbook_tool_service import _default_vor_adapter

    source = tmp_path / "Исходник 'Ω'.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.title = "Раздел Ω"
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Самостоятельная операция", "шт", 2])
    workbook.active.append(["Отдельное изделие", "шт", 2])
    workbook.save(source)
    workbook.close()
    rows = [
        {"source_row": "Раздел Ω!R2", "row_role": "work", "title": "Самостоятельная операция",
         "unit": "шт", "quantity": 2, "open_gap": ""},
        {"source_row": "Раздел Ω!R3", "row_role": "material", "title": "Отдельное изделие",
         "unit": "шт", "quantity": 2, "work_row": "Раздел Ω!R3", "open_gap": ""},
    ]
    before = copy.deepcopy(rows)
    target = tmp_path / "Результат Ω.xlsx"
    result = await _default_vor_adapter(source, {"decisions": rows}, target, lambda *args: None)
    assert any(issue["code"] == "invalid_work_relationship" for issue in result["document_issues"])
    output = openpyxl.load_workbook(target, data_only=False)
    try:
        assert "НЕ ЗАВЕРШЁН" in output["ВОР"]["A2"].value
        assert output["ВОР"]["C5"].value == "Отдельное изделие"
        assert output["ВОР"]["J5"].value == "material"
        assert output["ВОР"]["F5"].value == 2
        assert "invalid_work_relationship" in str(list(output["Проверка"].values))
    finally:
        output.close()
    assert rows == before


def test_complete_vor_does_not_require_norms_or_prices_and_accepts_zero():
    rows = [{"source_row": "Input!R2", "row_role": "work", "title": "Explicit source operation",
             "unit": "m", "quantity": 0, "open_gap": ""}]
    readiness = service.build_vor_result_readiness(rows=rows, has_file=True, remaining_locators=[],
        catalog_work_count=1, model_errors=[])
    assert readiness["vor_complete"] and readiness["row_integrity_issues"] == []


def test_failed_decoded_query_reply_remains_diagnosable_but_no_search_vor_is_not_failure():
    raw = '{"artifact_kind":"lsr","queries":[],"commentary":"Literal note"}'
    parsed = service.declared_query_output_diagnostics(raw, service.read_model_query_response(raw))
    diagnostic = {"declared_parse": parsed, "finish_reason": "stop"}
    service.add_rejected_query_visible_diagnostics(diagnostic, raw)
    assert diagnostic["rejected_visible_final"]["text"] == raw
    no_search = '{"artifact_kind":"vor","queries":[]}'
    diagnostic = {"declared_parse": service.declared_query_output_diagnostics(
        no_search, service.read_model_query_response(no_search))}
    service.add_rejected_query_visible_diagnostics(diagnostic, no_search)
    assert "rejected_visible_final" not in diagnostic


def test_header_only_file_is_not_reported_as_a_complete_vor():
    readiness = service.build_vor_result_readiness(
        rows=[{"source_row": "Input!R1", "row_role": "header", "title": "Раздел"}],
        has_file=True, remaining_locators=[], catalog_work_count=1, model_errors=[])
    assert not readiness["vor_complete"]
    assert readiness["open_questions"]


def test_readiness_uses_the_same_catalog_aliases_as_the_exporter():
    from types import SimpleNamespace

    class Catalog:
        def lookup(self, value):
            locator = {"sheet!r2": "Sheet!R2", "sheet!r3": "Sheet!R3"}.get(str(value).lower())
            return SimpleNamespace(locator=locator) if locator else None

    rows = [
        {"source_row": "Sheet!R2", "row_role": "work", "title": "Operation",
         "quantity": 2, "unit": "шт"},
        {"source_row": "Sheet!R3", "row_role": "material", "title": "Item",
         "quantity": 2, "unit": "шт", "work_row": "sheet!r2"},
    ]
    readiness = service.build_vor_result_readiness(rows=rows, has_file=True, remaining_locators=[],
        catalog_work_count=2, model_errors=[], source_catalog=Catalog())
    assert readiness["vor_complete"] and readiness["row_integrity_issues"] == []


@pytest.mark.parametrize("role", ["work", "works", "работа"])
def test_readiness_accepts_existing_work_role_aliases_without_rewriting_them(role):
    rows = [{"source_row": "Input!R2", "row_role": role, "title": "Explicit operation",
             "quantity": 1, "unit": "m"}]
    readiness = service.build_vor_result_readiness(rows=rows, has_file=True, remaining_locators=[],
        catalog_work_count=1, model_errors=[])
    assert readiness["vor_complete"] and readiness["open_questions"] == []
    assert rows[0]["row_role"] == role
