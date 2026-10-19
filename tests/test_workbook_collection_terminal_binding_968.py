"""A literal terminal member ID never changes the server-owned collection scope."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from proxy.services import model_workbook_terminal_transport_service as transport
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests import test_attachment_collection_965 as collections
from tests import test_model_rag_sheet_evidence_reads as fixture


MARKER = "COLLECTION_TERMINAL_LITERAL_968"


def _collection(tmp_path):
    return collections._parent(tmp_path, [
        collections._child(tmp_path, 1, values=[["Cable A", "m", 0], ["Cable B", "m", 12]]),
        collections._child(tmp_path, 2, name="Other.xlsx", values=[["Unknown", "m", None], ["Other", "m", 4]]),
    ])


def _rows(catalog, member):
    return [{"source_row": locator, "row_role": "work", "work_row": "", "title": row.values[1],
             "unit": row.values[2], "quantity": row.header_quantity, "open_gap": "",
             "coverage": 'Literal "description"\nkept'}
            for locator in catalog.work_locators()
            if locator.startswith(member + "::") for row in [catalog.lookup(locator)]]


async def _run_collection(tmp_path, monkeypatch, *, variant, use_root=False, kind="vor", declared=True):
    _, metadata, catalog = _collection(tmp_path)
    member = catalog.source_members[0]["attachment_id"]
    authored = _rows(catalog, member)
    if kind == "lsr":
        for row in authored:
            row.update(norm_code="", norm_status="MISSING", open_gap="Norm not selected", evidence_refs=[])
    else:
        for row in authored:
            row.pop("work_row")
            row.pop("open_gap")
    literal = json.dumps({"attachment_id": metadata["attachment_id"] if use_root else member,
                          "decisions": authored}, ensure_ascii=False)
    native = {"id": "literal-terminal-968", "type": "function", "function": {
        "name": f"build_{kind}_workbook", "arguments": literal}}
    original = fixture.InferenceResponse

    def response(*args, **kwargs):
        if kwargs.get("text") == MARKER:
            return InferenceResponse(text="", tool_calls=(native,), finish_reason="tool_calls", usage={})
        return original(*args, **kwargs)

    monkeypatch.setattr(fixture, "preserve_read_attachment", lambda *a, **kw: metadata)
    monkeypatch.setattr(fixture, "InferenceResponse", response)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration=json.dumps({**({"artifact_kind": kind} if declared else {}),
                                      "queries": [] if kind == "vor" and declared else ["Literal model query"]}),
        final_answer=MARKER, budget_stop_at=3,
        question=f"Build {kind.upper()}" + ("; Санкт-Петербург, 3 квартал 2026" if kind == "lsr" else ""))
    return run, metadata, catalog, authored, literal


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("kind", ["vor", "lsr"])
async def test_owned_member_terminal_keeps_root_pack_and_full_collection_remaining(tmp_path, monkeypatch, variant, kind):
    run, root, catalog, authored, literal = await _run_collection(tmp_path, monkeypatch, variant=variant, kind=kind)
    assert len(run.executions) == 1, run.result
    call, result = run.executions[0]
    assert call["args"]["attachment_id"] == root["attachment_id"]
    assert result["source"]["sha256"] == root["sha256"]
    assert len(result["source"]["collection_members"]) == 2
    assert [{key: row[key] for key in authored[index]} for index, row in enumerate(call["args"]["decisions"])] == authored
    assert call["args"]["decisions"][0]["quantity"] == 0
    receipt = run.result["retrieval_trace"]["workbook_terminal_transport"][0]
    assert receipt["raw_arguments"] == literal
    assert receipt["attachment_binding"] == {
        "provided_attachment_id": catalog.source_members[0]["attachment_id"],
        "root_attachment_id": root["attachment_id"],
        "binding_kind": "verified_collection_member_alias", "source_sha256": root["sha256"],
    }
    if variant == "B1_CANDIDATE":
        job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
        assert job["identity"]["attachment_id"] == root["attachment_id"]
        assert job["identity"]["source_sha256"] == root["sha256"]
        assert {row["source_row"] for row in job["accepted_rows"]} == {row["source_row"] for row in authored}
        assert set(job["remaining"]) == set(catalog.work_locators()) - {row["source_row"] for row in authored}
        assert job["status"] == "paused"
        assert len(run.requests) == 3
    else:
        assert len(run.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
async def test_root_terminal_is_unchanged_and_root_id_is_in_plain_admitted_instruction(tmp_path, monkeypatch, declared):
    run, root, _catalog, _authored, literal = await _run_collection(
        tmp_path, monkeypatch, variant="B0_DIRECT", use_root=True, declared=declared)
    assert run.executions[0][0]["args"]["attachment_id"] == root["attachment_id"]
    assert run.result["retrieval_trace"]["workbook_terminal_transport"][0]["raw_arguments"] == literal
    messages = "\n".join(str(message.get("content", "")) for message in run.requests[1].messages)
    assert f'attachment_id={json.dumps(root["attachment_id"])}' in messages
    assert "ID участника" in messages


@pytest.mark.parametrize("fault", ["foreign_id", "foreign_existing_member", "other_member_rows", "unqualified",
                                  "unknown_row", "empty", "missing_source", "ambiguous_member", "origin_sha",
                                  "ambiguous_origin", "no_collection"])
def test_member_alias_rejects_any_scope_ambiguity_without_changing_authored_values(tmp_path, fault):
    _, root, catalog = _collection(tmp_path)
    member = catalog.source_members[0]["attachment_id"]
    arguments = {"attachment_id": member, "decisions": _rows(catalog, member)}
    if fault == "foreign_id":
        arguments["attachment_id"] = "read_ffffffffffff"
    elif fault == "foreign_existing_member":
        arguments["attachment_id"] = collections._child(tmp_path, 3)["attachment_id"]
    elif fault == "other_member_rows":
        arguments["decisions"] += _rows(catalog, catalog.source_members[1]["attachment_id"])
    elif fault == "unqualified":
        arguments["decisions"][0]["source_row"] = "Раздел!R2"
    elif fault == "unknown_row":
        arguments["decisions"][0]["source_row"] = member + "::Раздел!R999"
    elif fault == "empty":
        arguments["decisions"] = []
    elif fault == "missing_source":
        arguments["decisions"][0].pop("source_row")
    elif fault == "ambiguous_member":
        catalog = replace(catalog, source_members=(*catalog.source_members, catalog.source_members[0]))
    elif fault == "origin_sha":
        origins = deepcopy(catalog.source_row_origins)
        origins[1]["source_file_sha256"] = "0" * 64
        catalog = replace(catalog, source_row_origins=origins)
    elif fault == "ambiguous_origin":
        catalog = replace(catalog, source_row_origins=(*catalog.source_row_origins, catalog.source_row_origins[1]))
    elif fault == "no_collection":
        catalog = replace(catalog, source_members=())
    native = {"id": "literal", "type": "function", "function": {
        "name": "build_vor_workbook", "arguments": json.dumps(arguments, ensure_ascii=False)}}
    decoded = transport.decode_workbook_terminal_response([native])
    before = deepcopy(decoded)
    with pytest.raises(transport.WorkbookTerminalTransportError, match="WORKBOOK_TERMINAL_ATTACHMENT_MISMATCH"):
        transport.workbook_terminal_attachment_binding(decoded,
            root_attachment_id=root["attachment_id"], source_catalog=catalog)
    assert decoded == before


def test_exact_root_never_narrows_decisions_to_one_member(tmp_path):
    _, root, catalog = _collection(tmp_path)
    authored = [row for member in catalog.source_members for row in _rows(catalog, member["attachment_id"])]
    native = {"id": "literal", "type": "function", "function": {"name": "build_vor_workbook",
        "arguments": {"attachment_id": root["attachment_id"], "decisions": authored}}}
    decoded = transport.decode_workbook_terminal_response([native])
    before = deepcopy(decoded)
    binding = transport.workbook_terminal_attachment_binding(decoded,
        root_attachment_id=root["attachment_id"], source_catalog=catalog)
    assert binding["binding_kind"] == "request_root"
    assert binding["root_attachment_id"] == root["attachment_id"]
    assert decoded == before
    assert any(row["quantity"] is None for row in decoded.envelope["rows"])


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("declared", [False, True])
async def test_single_file_admitted_terminal_instruction_keeps_previous_bytes(tmp_path, monkeypatch, variant, declared):
    from tests import test_vor_native_terminal_workflow_962 as native_fixture

    native_fixture._native_response(monkeypatch)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration=json.dumps({**({"artifact_kind": "vor"} if declared else {}),
                                      "queries": [] if declared else ["Literal model source query"]}),
        final_answer=native_fixture.MARKER, question="Собери ВОР")
    assert len(run.requests) == 2 and len(run.executions) == 1
    admitted = "\n".join(str(message.get("content", "")) for message in run.requests[1].messages)
    previous = ("\nЕсли пользователь не задал формат ответа, завершённые строки ВОР можно передать "
        "в build_vor_workbook через decisions. Это итоговые решения, не новый поиск и не "
        "непосредственная упаковка. source_row и work_row — буквальные предложенные адреса; "
        "operation_id и expected_revision сохраняй из прежних решений. Явный формат пользователя сохраняется.")
    assert (previous in admitted) is declared
    assert "Контекст упаковки всего прикреплённого исходника:" not in admitted
    assert 'attachment_id="read_123456abcdef"' not in admitted
