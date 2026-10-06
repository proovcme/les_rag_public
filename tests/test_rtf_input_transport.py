"""RTF native evidence reaches upload/catalog/authored VOR without a false green."""
import hashlib
from dataclasses import replace
from pathlib import Path

import openpyxl
import pytest

from backend import converter, rtf_parser
from proxy import config
from proxy.services import attachment_source_catalog_service as catalog_service
from proxy.services import runtime_config_registry_service as registry
from proxy.services import workbook_tool_service as workbook_service
from proxy.services.artifact_revision_service import ArtifactRevisionStore
from proxy.services.chat_attachment_service import preserve_read_attachment
from proxy.services.chat_evidence_application_service import safe_workbook_history_projection
from proxy.services.model_research_tool_service import ModelResearchToolService
from proxy.services.model_source_frame_service import build_model_source_frame
from proxy.services.workflow_checkpoint_service import WorkflowCheckpointService


def _source(tmp_path, monkeypatch, *, flat=False, line_ending="\r\n", value="0", long_name=None):
    path = tmp_path / "Источник «клиент» и 'кавычка'.rtf"
    name = long_name or "Кабель | буквальное значение"
    text = (f"Наименование\tЕд. изм.\tКол-во\tПримечание\t{line_ending}"
            f"{name}\tм\t{value}\t\t{line_ending}")
    raw = br"{\rtf1\ansi\ansicpg1251\trowd header\cell unit\cell qty\cell note\cell\row\trowd name\cell unit\cell qty\cell\cell\row"
    if flat:
        raw += br"\tab"
    raw += br"\clvmgf\clvmrg}"
    path.write_bytes(raw)
    def native(source, timeout, expected_source_sha256):
        assert timeout == 30
        assert expected_source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
        return text, {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                      "native_reader": "windows-richtext"}
    monkeypatch.setattr(rtf_parser, "_native_text", native)
    return path, text


def test_converter_uses_bounded_native_reader_and_preserves_full_unicode_text(tmp_path, monkeypatch):
    source, text = _source(tmp_path, monkeypatch, long_name="Длинное условие " * 800 + "LAST_LITERAL")
    monkeypatch.setattr(converter, "_parse_with_markitdown", lambda *_: pytest.fail("no guessed RTF fallback"))
    monkeypatch.setattr(converter, "_parse_legacy_doc", lambda *_: pytest.fail("no legacy DOC path"))
    monkeypatch.setenv("RAG_MAX_FILE_CHARS", "30")
    assert ".rtf" in converter.SUPPORTED
    assert converter.convert_to_markdown(source, apply_char_limit=False) == text
    assert converter.convert_to_markdown(source) == text[:30]
    assert source.read_bytes().endswith(b"}")


@pytest.mark.parametrize("raw,code", [(br"{\rtf1 truncated", "RTF_UNCLOSED_GROUP"),
    (br"{\rtf1{\object\objdata hidden}}", "RTF_EMBEDDED_OBJECTS_UNSUPPORTED")])
def test_converter_and_catalog_reject_unsafe_rtf_before_native_fallback(tmp_path, monkeypatch, raw, code):
    source = tmp_path / "Небезопасный.rtf"
    source.write_bytes(raw)
    monkeypatch.setattr(rtf_parser, "_native_text", lambda *_: pytest.fail("must fail before native load"))
    for read in (converter.convert_to_markdown, catalog_service.load_tabular_source_catalog):
        with pytest.raises(rtf_parser.RtfParserError, match=code):
            read(source)


def test_catalog_verified_cells_zero_empty_column_and_native_offsets_are_literal(tmp_path, monkeypatch):
    source, text = _source(tmp_path, monkeypatch)
    before = source.read_bytes()
    catalog = catalog_service.load_tabular_source_catalog(source)
    assert catalog.extraction_complete is False
    assert catalog.extraction_warnings == rtf_parser.extract_rtf(source).warnings
    assert "RTF_MERGED_TABLE_GEOMETRY_UNVERIFIED" in catalog.extraction_warnings
    assert catalog.sheets == (("RTF_T1", 2),)
    row = catalog.lookup("RTF_T1!R2")
    assert row.values == ("Кабель | буквальное значение", "м", "0", "")
    assert tuple(cell.raw_value for cell in row.cells) == row.values
    assert row.header_quantity == 0
    assert row.source_order_basis == "rtf_native_text_char_offsets"
    assert text[row.source_start:row.source_end] == "Кабель | буквальное значение\tм\t0\t\t\r\n"
    assert source.read_bytes() == before
    assert catalog.source_file_sha256 == hashlib.sha256(before).hexdigest()
    assert catalog_service.compare_model_row_to_catalog(
        {"source_row": row.locator, "quantity": 0, "unit": "м"}, catalog,
    ) == ["source_extraction_incomplete:RTF_T1!R2"]


def test_flat_rtf_does_not_invent_cells_or_quantities_and_keeps_crlf(tmp_path, monkeypatch):
    source, text = _source(tmp_path, monkeypatch, flat=True, value="7,25")
    catalog = catalog_service.load_tabular_source_catalog(source)
    assert catalog.sheets == (("RTF_TEXT", 2),)
    assert "RTF_TEXT_TABS_AMBIGUOUS_WITH_CELLS" in catalog.extraction_warnings
    assert "RTF_TABLE_BOUNDARIES_UNVERIFIED" in catalog.extraction_warnings
    assert "".join(row.values[0] for row in catalog.rows) == text
    assert all(row.row_classification == "ambiguous" and len(row.cells) == 1 for row in catalog.rows)
    assert all(row.numbers == () and row.header_quantity is None and not row.quantity_column_known
               for row in catalog.rows)
    assert all(text[row.source_start:row.source_end] == row.values[0] for row in catalog.rows)
    assert all(row.source_order_basis == "rtf_native_text_char_offsets" for row in catalog.rows)


def test_empty_optional_basis_preserves_exact_907_legacy_frame_bytes_and_hashes(monkeypatch):
    from proxy.services import model_source_frame_service as frames

    # Frozen pre-RTF row schema: no generic filtering of other empty fields.
    old_fields = ("locator", "sheet", "excel_row", "values", "line", "numbers", "row_id", "sheet_id",
        "cells", "row_classification", "classification_reason", "classification_confidence", "ambiguities",
        "section_context", "hidden_row", "hidden_sheet", "header_quantity", "quantity_column_known",
        "column_headers", "source_start", "source_end")
    row = catalog_service.CatalogRow(locator="PDF_TEXT!R1", sheet="PDF_TEXT", excel_row=1,
        values=("Буквальное условие\r\n",), line="PDF_TEXT!R1: Буквальное условие\r\n", numbers=(),
        row_id="row-legacy", sheet_id="sheet-legacy", source_start=0, source_end=20,
        cells=(catalog_service.CatalogCell(coordinate="A1", column=1, raw_value="Буквальное условие\r\n",
                                          display_value="Буквальное условие\r\n", data_type="s", number_format="General"),))
    catalog = catalog_service.AttachmentSourceCatalog(original_name="Старый источник.pdf",
        sheets=((row.sheet, 1),), rows=(row,), source_file_sha256="1" * 64, source_file_id="src-legacy")
    actual = frames.build_model_source_frame(catalog, [row.locator])
    actual_render = frames.render_model_source_frame(actual)
    original_literal, original_types = frames._literal, frames._literal_types
    def old_literal(value):
        if isinstance(value, catalog_service.CatalogRow):
            return {name: old_literal(getattr(value, name)) for name in old_fields}
        return original_literal(value)
    def old_types(value):
        if isinstance(value, catalog_service.CatalogRow):
            return {name: old_types(getattr(value, name)) for name in old_fields}
        return original_types(value)
    with monkeypatch.context() as old:
        old.setattr(frames, "_literal", old_literal)
        old.setattr(frames, "_literal_types", old_types)
        reconstructed_907 = frames.build_model_source_frame(catalog, [row.locator])
        reconstructed_render = frames.render_model_source_frame(reconstructed_907)
    assert actual.payload_json == reconstructed_907.payload_json
    assert actual.catalog_sha256 == reconstructed_907.catalog_sha256
    assert actual.requested_scope_sha256 == reconstructed_907.requested_scope_sha256
    assert actual.source_frame_sha256 == reconstructed_907.source_frame_sha256
    assert actual_render.payload_json == reconstructed_render.payload_json
    assert actual_render.model_render_sha256 == reconstructed_render.model_render_sha256


def test_nonempty_native_offset_basis_remains_literal_typed_and_hashed(tmp_path, monkeypatch):
    from proxy.services import model_source_frame_service as frames

    source, _text = _source(tmp_path, monkeypatch, flat=True)
    catalog = catalog_service.load_tabular_source_catalog(source)
    row = catalog.rows[0]
    assert frames._literal(row)["source_order_basis"] == "rtf_native_text_char_offsets"
    assert frames._literal_types(row)["source_order_basis"] == "str"
    native = frames.build_model_source_frame(catalog, [row.locator])
    different_basis = replace(catalog, rows=tuple(replace(item, source_order_basis="other_explicit_text_offsets")
                                                for item in catalog.rows))
    alternate = frames.build_model_source_frame(different_basis, [row.locator])
    assert native.catalog_sha256 != alternate.catalog_sha256
    assert native.source_frame_sha256 != alternate.source_frame_sha256


@pytest.mark.asyncio
async def test_read_source_and_source_frame_preserve_native_basis_and_all_warnings(tmp_path, monkeypatch):
    source, text = _source(tmp_path, monkeypatch, flat=True)
    catalog = catalog_service.load_tabular_source_catalog(source)
    reader = ModelResearchToolService(retrieve=lambda *_a, **_k: pytest.fail("no RAG for exact source"),
        frozen_dataset_ids=(), retrieval_kwargs={}, fallback=lambda *_: pytest.fail("no fallback"),
        attachment_catalog=catalog, expected_attachment_sha256=catalog.source_file_sha256)
    result = await reader.execute({"tool": "read_source", "args": {"source_row": "RTF_TEXT!R2"}})
    assert result.payload["status"] == "ok" and result.payload["warnings"] == list(catalog.extraction_warnings)
    assert result.payload["trace"]["body_complete"] is True
    assert result.payload["trace"]["source_extraction_complete"] is False
    assert result.payload["trace"]["source_order_basis"] == "rtf_native_text_char_offsets"
    assert result.chunks[0].content == catalog.rows[1].line
    frame = build_model_source_frame(catalog, ["RTF_TEXT!R2"]).to_payload()
    assert frame["source_order_basis"] == "rtf_native_text_char_offsets"
    assert frame["source_manifest"]["extraction_complete"] is False
    assert frame["source_manifest"]["extraction_warnings"] == list(catalog.extraction_warnings)
    facts = catalog_service.catalog_sheet_packet_facts(catalog, "RTF_TEXT", ["RTF_TEXT!R2"])
    assert facts["source_order_basis"] == "rtf_native_text_char_offsets"


def test_upload_policy_and_existing_pickers_register_rtf_without_expanding_override(monkeypatch):
    monkeypatch.delenv("RAG_UPLOAD_SUFFIXES", raising=False)
    assert ".rtf" in config.rag_upload_suffixes()
    assert registry._EXPLICIT_FACTOR_DEFAULTS["RAG_UPLOAD_SUFFIXES"] == ",".join(config.DEFAULT_RAG_UPLOAD_SUFFIXES)
    for filename in ("chat.py", "documents.py"):
        source = (Path(__file__).resolve().parents[1] / "sovushka" / "pages" / filename).read_text(encoding="utf-8")
        assert "accept=.xlsx,.xlsm,.xls,.csv,.pdf,.docx,.rtf" in source
    monkeypatch.setenv("RAG_UPLOAD_SUFFIXES", ".pdf,.xlsx")
    assert config.rag_upload_suffixes() == {".pdf", ".xlsx"}


@pytest.mark.asyncio
async def test_rtf_upload_exposes_application_warnings_separately_from_exact_native_source(tmp_path, monkeypatch):
    from proxy.routers import datasets
    from proxy.services import chat_attachment_service

    source, text = _source(tmp_path, monkeypatch, flat=True)
    monkeypatch.setattr(chat_attachment_service, "cleanup_expired", lambda: None)
    monkeypatch.setattr(chat_attachment_service, "preserve_read_attachment", lambda *_a, **_k: None)
    monkeypatch.setattr(datasets, "_READ_ATTACH_MAX_CHARS", 100000)
    result = await datasets._prepare_read_attachment(source, source.name, attachment_id="read_123456abcdef")
    assert result["source_extraction_complete"] is False and result["truncated"] is False
    assert result["source_extraction_origin"] == "application/native_rtf_reader"
    assert result["source_extraction_warnings"] == list(rtf_parser.extract_rtf(source).warnings)
    assert result["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["source_text_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert result["source_text_chars"] == len(text)
    assert result["text"].endswith(text)
    for warning in result["source_extraction_warnings"]:
        assert f"[WARN] {warning}" in result["text"]
    monkeypatch.setattr(datasets, "_READ_ATTACH_MAX_CHARS", 100)
    truncated = await datasets._prepare_read_attachment(source, source.name, attachment_id="read_123456abcdef")
    assert truncated["truncated"] is True and truncated["source_extraction_complete"] is False
    assert len(truncated["text"]) == 100
    assert truncated["source_text_sha256"] == result["source_text_sha256"]
    assert truncated["source_extraction_warnings"] == result["source_extraction_warnings"]


@pytest.mark.asyncio
async def test_rtf_upload_reports_native_unavailable_without_claiming_empty_success(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from proxy.routers import datasets

    source = tmp_path / "Документ.rtf"
    source.write_bytes(br"{\rtf1 text}")
    monkeypatch.setattr(rtf_parser, "_native_platform", lambda: "linux")
    for read in (converter.convert_to_markdown, catalog_service.load_tabular_source_catalog):
        with pytest.raises(rtf_parser.RtfParserError, match="RTF_NATIVE_READER_UNAVAILABLE"):
            read(source)
    with pytest.raises(HTTPException) as error:
        await datasets._prepare_read_attachment(source, source.name)
    assert error.value.status_code == 422
    assert "RTF_NATIVE_READER_UNAVAILABLE" in error.value.detail


def _context(tmp_path):
    return workbook_service.WorkbookExecutionContext(session_id="rtf-input", idempotency_key="rtf-input-key",
        model_decision_revision="decision", profile_revision_id="profile", model_identity="fixture", model_preset="fixture",
        attachment_root=tmp_path / "attachments", work_dir=tmp_path / "work",
        checkpoints=WorkflowCheckpointService(tmp_path / "checkpoints.db"),
        artifacts=ArtifactRevisionStore(tmp_path / "artifacts.db", tmp_path / "artifacts"))


@pytest.mark.asyncio
@pytest.mark.parametrize("flat,locator", [(False, "RTF_T1!R2"), (True, "RTF_TEXT!R2")])
async def test_authored_rtf_vor_preserves_decision_but_remains_partial_on_source_gaps(tmp_path, monkeypatch, flat, locator):
    source, _text = _source(tmp_path, monkeypatch, flat=flat)
    meta = preserve_read_attachment(source, attachment_id="read_123456abcdef", original_name=source.name,
                                    root=tmp_path / "attachments")
    context = _context(tmp_path)
    decision = {"source_row": locator, "row_role": "work", "title": "Работа, выбранная моделью", "quantity": 0, "unit": "м"}
    monkeypatch.setattr("proxy.services.spec_to_bor_service.derive_work_for_item",
                        lambda *_a, **_k: pytest.fail("no code professional choice"))
    result = await workbook_service.build_vor_workbook({"attachment_id": meta["attachment_id"], "decisions": [decision]}, context)
    assert result.get("artifact"), result
    assert any(error.startswith("source_extraction_incomplete") for error in result["vor_source_errors"])
    assert result["status"] == "partial"
    assert safe_workbook_history_projection(result)["status"] == "partial"
    artifact_path = context.artifacts.resolve_path(result["artifact"]["revision_id"])
    artifact_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    workbook = openpyxl.load_workbook(artifact_path, data_only=True)
    assert "ЧЕРНОВИК" in workbook.active["A2"].value
    assert workbook.active["C4"].value == decision["title"]
    assert workbook.active["F4"].value == 0
    assert workbook.active["G4"].value == f"{source.name}#{locator}"
    workbook.close()
    assert decision == {"source_row": locator, "row_role": "work", "title": "Работа, выбранная моделью", "quantity": 0, "unit": "м"}
    replay = await workbook_service.build_vor_workbook({"attachment_id": meta["attachment_id"], "decisions": [decision]}, context)
    assert replay["artifact"]["revision_id"] == result["artifact"]["revision_id"]
    assert replay["status"] == "partial"
    assert replay["vor_source_errors"] == result["vor_source_errors"]
    assert safe_workbook_history_projection(replay)["status"] == "partial"
    assert hashlib.sha256(context.artifacts.resolve_path(replay["artifact"]["revision_id"]).read_bytes()).hexdigest() == artifact_sha


@pytest.mark.asyncio
async def test_rtf_cannot_enter_unauthored_vor_or_direct_lsr(tmp_path, monkeypatch):
    source, _text = _source(tmp_path, monkeypatch)
    meta = preserve_read_attachment(source, attachment_id="read_123456abcdef", original_name=source.name,
                                    root=tmp_path / "attachments")
    context = _context(tmp_path)
    result = await workbook_service.build_vor_workbook({"attachment_id": meta["attachment_id"]}, context)
    assert result["code"] == "UNSUPPORTED_ATTACHMENT_TYPE"
    result = await workbook_service.build_lsr_workbook({"attachment_id": meta["attachment_id"], "decisions": [
        {"source_row": "RTF_T1!R2", "row_role": "work", "title": "Работа", "quantity": 0, "unit": "м"}]}, context)
    assert result["code"] == "UNSUPPORTED_ATTACHMENT_TYPE"
