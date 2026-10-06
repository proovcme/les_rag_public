"""The calculator receives the catalog loaded from the original attachment."""
from __future__ import annotations

import copy
import json

import pytest

from proxy.services import attachment_source_catalog_service as catalog_service
from proxy.services import lsr_workbook_adapter_service as adapter
from proxy.services.lsr_source_coverage_service import operation_identity


def _catalog():
    row = catalog_service.CatalogRow(
        locator="PDF!R2", sheet="PDF", excel_row=2,
        values=("Literal source work",), line="PDF!R2: Literal source work",
        numbers=(), row_classification="ambiguous",
    )
    return catalog_service.AttachmentSourceCatalog(
        original_name="source.pdf", sheets=(("PDF", 1),), rows=(row,),
        source_file_id="src_original_attachment",
    )


def test_source_facts_return_the_same_loaded_catalog_without_rewriting_identity(monkeypatch):
    catalog = _catalog()
    calls = []
    monkeypatch.setattr(catalog_service, "load_catalog_from_attachment_id",
                        lambda aid: calls.append(aid) or catalog)
    rows = [{"source_row": f"{catalog.source_file_id}!R2", "row_role": "work",
             "title": "Authored operation", "evidence_refs": ["Q1.H1"]}]
    original = copy.deepcopy(rows)
    identities = [operation_identity(row) for row in rows]

    loaded = adapter._attach_catalog_facts(rows, "read_original")

    assert loaded is catalog
    assert calls == ["read_original"]
    assert [{key: row[key] for key in original[index]} for index, row in enumerate(rows)] == original
    assert rows[0]["_catalog_source_values"] == ["Literal source work"]
    assert [operation_identity(row) for row in rows] == identities


@pytest.mark.asyncio
@pytest.mark.parametrize("with_catalog", [True, False])
async def test_workbook_adapter_passes_original_catalog_once_and_keeps_model_rows(
    tmp_path, monkeypatch, with_catalog,
):
    catalog = _catalog() if with_catalog else None
    loaded_ids = []
    captured = {}
    rows = [{"source_row": "src_original_attachment!R2", "row_role": "work",
             "title": "Authored operation", "evidence_refs": ["Q1.H1"],
             "_catalog_source_locator": "FOREIGN!R9"}]
    original = json.dumps(rows, sort_keys=True)
    identity = operation_identity(rows[0])
    monkeypatch.setattr(catalog_service, "load_catalog_from_attachment_id",
                        lambda aid: loaded_ids.append(aid) or catalog)
    monkeypatch.setattr(adapter, "visible_pricebook_stems", lambda: [])
    monkeypatch.setattr(adapter.fgis_price_service, "resolve_pricebook_path",
                        lambda *_args, **_kwargs: None)

    def calculate(decisions, **kwargs):
        captured["rows"] = decisions
        captured["kwargs"] = kwargs
        return {"schema": "rim_lsr_v1", "sections": [], "row_bindings": [],
                "summary": {"input_rows": len(decisions), "bound_rows": 0}}

    def render(_trace, output_path, **_kwargs):
        output_path.write_bytes(b"reviewable artifact")
        return output_path

    monkeypatch.setattr(adapter, "build_lsr_trace_from_visible_rows", calculate)
    monkeypatch.setattr(adapter, "render_lsr_xlsx", render)

    result = await adapter.build_lsr_workbook_from_decisions(
        tmp_path / "source.xlsx",
        {"decisions": rows, "attachment_id": "read_original", "question": "Build LSR"},
        tmp_path / "result.xlsx", lambda *_args: None,
    )

    assert loaded_ids == ["read_original"]
    assert captured["kwargs"]["source_catalog"] is catalog
    assert captured["rows"][0]["source_row"] == rows[0]["source_row"]
    assert captured["rows"][0]["evidence_refs"] == rows[0]["evidence_refs"]
    assert captured["rows"][0]["_catalog_source_locator"] == "FOREIGN!R9"
    assert operation_identity(captured["rows"][0]) == identity
    assert json.dumps(rows, sort_keys=True) == original
    assert result["file_path"].exists()
