"""An exported document stays primary beside inventory/notebook navigation."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests import test_model_rag_sheet_evidence_reads as fixture


NOTEBOOK = {"title": "Инженерный блокнот", "mode": "markdown", "content": "Literal notebook"}
INVENTORY = {"file_count": 0, "document_count": 0,
             "inventory": {"files": [], "folders": {}, "by_ext": [], "total": 0, "indexed": 0}}


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("kind", ["vor", "lsr"])
@pytest.mark.parametrize("navigation", ["inventory", "notebook", "both"])
async def test_same_workbook_primary_in_export_history_job_and_final(tmp_path, monkeypatch, variant, kind, navigation):
    original_run = service.run_chat_evidence_application
    async def with_inventory(request, runtime, boundary):
        return await original_run(replace(request, inventory_requested=navigation in {"inventory", "both"}), runtime, boundary)
    monkeypatch.setattr(service, "run_chat_evidence_application", with_inventory)
    monkeypatch.setattr(service, "build_project_summary", lambda *args, **kwargs: INVENTORY)
    monkeypatch.setattr(service, "format_project_inventory_prompt", lambda *args, **kwargs: "Literal auxiliary inventory")
    monkeypatch.setattr(service, "format_project_inventory_context", lambda *args, **kwargs: "Literal complete auxiliary inventory")
    original_project = service.project_final_artifact_carriers
    def optional_notebook_producer(response, **carriers):
        # The current notebook producer is inactive. Inject its optional output
        # only at the real projection boundary; model requests/results stay real
        # existing fixture turns, without inventing a notebook inference route.
        if navigation in {"notebook", "both"}:
            carriers["notebook_artifact"] = deepcopy(NOTEBOOK)
        return original_project(response, **carriers)
    monkeypatch.setattr(service, "project_final_artifact_carriers", optional_notebook_producer)
    params = {}
    if kind == "vor":
        params = {"query_declaration": '{"artifact_kind":"vor","queries":[]}',
                  "final_answer": json.dumps({"artifact_kind": "vor", "rows": [
                      {"source_row": "S!R2", "row_role": "work", "title": "Cable A", "unit": "m", "quantity": 12},
                      {"source_row": "S!R3", "row_role": "work", "title": "Cable B", "unit": "m", "quantity": 3},
                  ]})}
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant, **params)
    assert len(run.executions) == 1 and len(run.requests) == 2 and not run.responses
    artifact = run.histories[-1]["artifact"]
    assert artifact["artifact_kind"] == kind + "_workbook"
    assert artifact.get("download_url") and artifact.get("revision_id") and artifact.get("sha256")
    if variant == "B1_CANDIDATE":
        job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
        assert artifact["revision_id"] in {job["document"].get("draft_revision_id"), job["document"].get("final_revision_id")}
    assert run.result["artifact"] == artifact
    assert run.result["retrieval_trace"]["model_result"]["packaged"] is True
    if navigation in {"inventory", "both"}:
        assert run.result["project_inventory"] == INVENTORY
        auxiliary = run.result["project_inventory_artifact"]
        assert auxiliary["title"] == "Реестр файлов" and auxiliary["project_inventory"] == INVENTORY
        assert auxiliary["content"] == "```text\nLiteral complete auxiliary inventory\n```"
    if navigation in {"notebook", "both"}:
        assert run.result["notebook_artifact"] == NOTEBOOK


@pytest.mark.parametrize("navigation", ["none", "inventory", "notebook", "both"])
@pytest.mark.parametrize("workbook", [None, {}, {"artifact_kind": "vor_workbook", "revision_id": ""}])
def test_no_issued_document_keeps_legacy_primary_choice(navigation, workbook):
    original_primary = {"mode": "markdown", "content": "Existing primary"}
    inventory_artifact = {"title": "Реестр файлов", "content": "Literal inventory", "project_inventory": INVENTORY}
    notebook = deepcopy(NOTEBOOK) if navigation in {"notebook", "both"} else None
    inventory = inventory_artifact if navigation in {"inventory", "both"} else None
    response = {"artifact": original_primary}
    before = deepcopy((workbook, notebook, inventory))
    service.project_final_artifact_carriers(response, workbook_artifact=workbook,
        notebook_artifact=notebook, project_inventory_artifact=inventory)
    expected = inventory if inventory is not None else notebook if notebook is not None else original_primary
    assert response["artifact"] == expected
    assert "project_inventory_artifact" not in response
    if notebook is not None and inventory is not None:
        assert response["notebook_artifact"] == notebook
    assert (workbook, notebook, inventory) == before


def test_issued_document_and_auxiliary_payloads_are_not_rewritten():
    document = {"revision_id": "rev_exact", "artifact_kind": "vor_workbook", "sha256": "literal-sha",
                "draft_rows": [{"operation_id": "op0", "quantity": 0, "calc_quantity": None}], "custom": "literal"}
    inventory = {"title": "Реестр файлов", "content": "Exact | inventory"}
    before = deepcopy((document, NOTEBOOK, inventory))
    response = {}
    service.project_final_artifact_carriers(response, workbook_artifact=document,
        notebook_artifact=NOTEBOOK, project_inventory_artifact=inventory)
    assert response["artifact"] is document
    assert response["notebook_artifact"] is NOTEBOOK and response["project_inventory_artifact"] is inventory
    assert (document, NOTEBOOK, inventory) == before
