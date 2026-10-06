"""A model may explicitly create VOR from its input without norm research."""
from __future__ import annotations

import copy
from io import BytesIO
import zipfile

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.lsr_norm_quality_gate_service import lsr_research_query_instruction


_EMPTY_VOR = '{"artifact_kind":"vor","queries":[]}'
_CONDITIONAL_SEARCH = "Если ты решил, что внешний поиск нужен"


@pytest.mark.parametrize("research_round", [0, 1])
def test_sheet_candidates_and_later_research_are_conditional_on_model_choice(research_round):
    snapshot = {"mode": "estimator", "prompt_text": "Saved literal role",
                "skill_text": "Saved literal skill", "revision_id": "saved:1"}
    before = copy.deepcopy(snapshot)
    query = service.sheet_pass_query_instruction(
        snapshot, sheet="Input Ω", sheet_index=1, sheet_count=2,
        research_round=research_round,
    )
    for tail in ("", service._MODEL_RAG_QUERY_REPAIR_INSTRUCTION,
                 service.declared_query_continuation_instruction([], "Unread literal tail Ω")):
        prompt = query + "\n\n" + tail
        assert _CONDITIONAL_SEARCH in prompt
        assert _EMPTY_VOR in prompt
        assert "не требует поиска норм" in prompt
        assert "Код исполнит возвращённые тобой поисковые запросы дословно" in prompt
    assert snapshot == before


def test_research_round_keeps_the_two_query_formats_and_explicit_no_search_vor():
    instruction = lsr_research_query_instruction(1)
    assert instruction.startswith(_CONDITIONAL_SEARCH)
    assert _EMPTY_VOR in instruction
    assert "JSON-конверт" in instruction and "дословные строки запросов" in instruction
    assert "Не повторяй прежние формулировки" in instruction
    assert "Нормы пока не выбирай" in instruction
    assert "каждый с новой строки" not in instruction


@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.asyncio
async def test_actual_explicit_empty_vor_reaches_result_without_any_search(tmp_path, monkeypatch, variant):
    from tests import test_model_rag_sheet_evidence_reads as fixture

    original = fixture._answer
    monkeypatch.setattr(fixture, "_answer", lambda **kwargs: original(**kwargs).replace(
        "artifact_kind: lsr", "artifact_kind: vor").replace("| material |", "| work |"))
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
                                   query_declaration=_EMPTY_VOR)
    assert len(run.requests) == 2 and not run.responses
    assert run.queries == []
    assert len(run.executions) == 1
    assert run.executions[0][0]["tool"] == "build_vor_workbook"
    assert run.result["retrieval_trace"]["actual_model_calls"]["search_executions"] == 0
    system = next(message["content"] for message in run.requests[0].messages
                  if message["role"] == "system")
    assert "Answer only from shown evidence." in system
    assert _EMPTY_VOR in system
    assert service._MODEL_RAG_QUERY_FORMAT_CONTRACT in system


@pytest.mark.parametrize("raw, intentional", [
    (_EMPTY_VOR, True),
    ('{"artifact_kind":"lsr","queries":[]}', False),
    ('{"artifact_kind":"vor","queries":[]', False),
])
def test_explicit_empty_vor_is_distinct_from_invalid_or_empty_lsr(raw, intentional):
    declared = service.read_model_query_response(raw, finish_reason="stop")
    assert declared["intentional_empty"] is intentional


@pytest.mark.asyncio
async def test_saved_partial_model_vor_is_downloadable_without_losing_the_failed_row(tmp_path, monkeypatch):
    from tests import test_model_rag_sheet_evidence_reads as fixture
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService

    original = fixture._answer
    monkeypatch.setattr(fixture, "_answer", lambda **kwargs: original(**kwargs).replace(
        "artifact_kind: lsr", "artifact_kind: vor").replace("| material |", "| work |"))
    run = await fixture._run_sheet(
        tmp_path, monkeypatch, reads=True, malformed_first_packet=True,
        query_declaration='{"artifact_kind":"vor","queries":["S!R2 — Cable A","S!R3 — Cable B"]}',
    )
    trace = run.result["retrieval_trace"]
    store = WorkbookResearchJobService()
    job = store.get(trace["workbook_research_job"]["job_id"])
    assert job["status"] == "paused" and job["remaining"] == ["S!R2"]
    assert len(job["accepted_rows"]) == 1
    assert job["accepted_rows"][0]["source_row"] == "S!R3"
    assert job["accepted_rows"][0]["quantity"] == 3
    assert trace["artifact_target"]["artifact_kind"] == "vor"
    assert trace["artifact_target"]["status"] == "declared"
    assert trace["model_result"]["status"] == "structural_error"
    assert len(run.requests) == 4 and not run.responses
    diagnostic = trace["model_result_transport_diagnostics"][0]
    assert diagnostic["code"] == "MODEL_RESULT_TABLE_ROW_WIDTH_MISMATCH"
    assert diagnostic["decision"]["source_row"] == "S!R2"
    assert diagnostic["decision"] in [proposal["decision"] for proposal in job["unapplied_proposals"]]
    assert len(run.executions) == 1
    call, output = run.executions[0]
    assert call["tool"] == "build_vor_workbook"
    assert call["args"]["draft"] is True
    assert call["args"]["decisions"] == job["accepted_rows"]
    assert output["artifact"]["download_url"]
    assert output["artifact"]["draft"] is True
    assert trace["model_result"]["packaged"] is True
    readiness = trace["result_readiness"]
    assert readiness["artifact_kind"] == "vor_workbook"
    assert readiness["technical_complete"] is False and readiness["vor_complete"] is False
    assert readiness["remaining_locators"] == ["S!R2"]
    assert any(issue["code"] == "WORKBOOK_RESEARCH_INCOMPLETE"
               and issue["remaining_locators"] == ["S!R2"] for issue in output["document_issues"])
    assert all("S!R3" not in issue.get("remaining_locators", []) for issue in output["document_issues"])
    assert store.get(job["job_id"])["accepted_rows"] == job["accepted_rows"]
    assert store.get(job["job_id"])["held_packet"] == job["held_packet"]
    _assert_partial_file(output["artifact"]["revision_id"], remaining="S!R2")
    request_count = len(run.requests)
    resumed = await run.resume_same_request()
    assert len(run.requests) == request_count
    assert resumed["retrieval_trace"]["model_result"]["status"] == "structural_error"
    assert resumed["retrieval_trace"]["model_result"]["packaged"] is True, {
        "target": resumed["retrieval_trace"].get("artifact_target"),
        "model_result": resumed["retrieval_trace"].get("model_result"),
        "saved_kind": store.get(job["job_id"])["task_context"].get("artifact_kind_declaration"),
    }
    assert store.get(job["job_id"])["accepted_rows"] == job["accepted_rows"]


def _assert_partial_file(revision_id, *, remaining):
    import openpyxl
    from backend.runtime_paths import mutable_path
    from proxy.services.artifact_revision_service import ArtifactRevisionStore

    artifacts = ArtifactRevisionStore(mutable_path("storage/artifacts/meta.db"),
                                      mutable_path("storage/artifacts/files"))
    raw = artifacts.read_bytes(revision_id)
    workbook = openpyxl.load_workbook(BytesIO(raw), data_only=False)
    assert "НЕ ЗАВЕРШЁН" in workbook["ВОР"]["A2"].value
    assert workbook["ВОР"]["C4"].value == "Cable B"
    assert workbook["ВОР"]["F4"].value == 3
    assert workbook["ВОР"].max_row == 4
    check = "\n".join(str(cell.value or "") for row in workbook["Проверка"] for cell in row)
    assert remaining in check and "WORKBOOK_RESEARCH_INCOMPLETE" in check
    assert "MODEL_RESULT_TABLE_ROW_WIDTH_MISMATCH" in check
    workbook.close()
    return raw


@pytest.mark.asyncio
async def test_public_repack_of_partial_vor_keeps_issues_draft_and_replays_without_inference(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tests import test_model_rag_sheet_evidence_reads as fixture
    from proxy.routers import chat
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService

    original = fixture._answer
    monkeypatch.setattr(fixture, "_answer", lambda **kwargs: original(**kwargs).replace(
        "artifact_kind: lsr", "artifact_kind: vor").replace("| material |", "| work |"))
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=True, malformed_first_packet=True,
                                  query_declaration='{"artifact_kind":"vor","queries":["Cable A","Cable B"]}')
    store = WorkbookResearchJobService()
    job = store.get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    request = chat.LsrRepackRequest(session_id=job["identity"]["session_id"], job_id=job["job_id"])
    request_count = len(run.requests)
    first = await chat.repack_lsr_without_model(request, _user=SimpleNamespace())
    payload = first["result"]
    assert first["model_called"] is False and len(run.requests) == request_count
    assert payload["artifact"]["artifact_kind"] == "vor_workbook"
    assert payload["artifact"]["draft"] is True
    assert payload["status"] == "partial"
    assert payload["document_issues"]
    assert any(issue["code"] == "MODEL_RESULT_TABLE_ROW_WIDTH_MISMATCH"
               and issue["diagnostic"]["decision"]["source_row"] == "S!R2"
               for issue in payload["document_issues"])
    first_bytes = _assert_partial_file(payload["artifact"]["revision_id"], remaining="S!R2")
    replay = await chat.repack_lsr_without_model(request, _user=SimpleNamespace())
    assert replay["model_called"] is False and len(run.requests) == request_count
    assert replay["result"]["artifact"]["revision_id"] == payload["artifact"]["revision_id"]
    assert _assert_partial_file(replay["result"]["artifact"]["revision_id"], remaining="S!R2") == first_bytes
    assert replay["harvested"]["artifact"]["result_readiness"]["technical_complete"] is False
    assert store.get(job["job_id"])["accepted_rows"] == job["accepted_rows"]
    assert store.get(job["job_id"])["held_packet"] == job["held_packet"]


@pytest.mark.asyncio
async def test_conflicting_model_document_kind_cannot_auto_package_saved_partial_vor(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tests import test_model_rag_sheet_evidence_reads as fixture
    from proxy.routers import chat

    original = fixture._answer
    monkeypatch.setattr(fixture, "_answer", lambda **kwargs: original(**kwargs).replace(
        "artifact_kind: lsr", "artifact_kind: vor\nartifact_kind: lsr"))
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=True, malformed_first_packet=True)
    trace = run.result["retrieval_trace"]
    assert trace["artifact_target"]["status"] == "conflict"
    assert not run.executions
    request_count = len(run.requests)
    with pytest.raises(service.HTTPException) as error:
        await chat.repack_lsr_without_model(chat.LsrRepackRequest(
            session_id="sheet-session", job_id=trace["workbook_research_job"]["job_id"]),
            _user=SimpleNamespace())
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "ARTIFACT_KIND_UNRESOLVED"
    assert error.value.detail["model_called"] is False
    assert len(run.requests) == request_count and not run.executions


def test_complete_vor_layout_without_draft_or_issues_is_unchanged(tmp_path):
    from proxy.services.bor_service import source_rows_to_vor_xlsx

    rows = [{"name": "Literal work", "unit": "m", "qty": 2.75, "row_role": "work",
             "source_file": "Input Ω.xlsx", "pos": "Ω!R7"}]
    before = copy.deepcopy(rows)
    default = tmp_path / "default.xlsx"
    explicit = tmp_path / "explicit.xlsx"
    source_rows_to_vor_xlsx(rows, default)
    source_rows_to_vor_xlsx(rows, explicit, draft=False, document_issues=[])
    with zipfile.ZipFile(default) as first, zipfile.ZipFile(explicit) as second:
        assert first.namelist() == second.namelist()
        assert first.read("xl/worksheets/sheet1.xml") == second.read("xl/worksheets/sheet1.xml")
        assert first.read("xl/workbook.xml") == second.read("xl/workbook.xml")
    assert rows == before


def test_explicit_draft_cannot_be_ready_even_when_no_locator_is_remaining():
    arguments = {"rows": [{"source_row": "Input!R2", "row_role": "work", "title": "Literal work"}],
                 "has_file": True, "remaining_locators": [], "catalog_work_count": 1,
                 "model_errors": []}
    assert service.build_vor_result_readiness(**arguments)["technical_complete"] is True
    draft = service.build_vor_result_readiness(**arguments, draft=True)
    assert draft["technical_complete"] is False and draft["vor_complete"] is False
    notice = service.format_lsr_packaged_notice(readiness=draft, artifact_kind="vor_workbook")
    assert "Промежуточный ВОР" in notice and "работа не завершена" in notice
