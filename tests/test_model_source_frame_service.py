"""Literal source packet projection; no inference, retrieval or runtime calls."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from decimal import Decimal
import hashlib
import json

import pytest

from proxy.services.attachment_source_catalog_service import (
    AttachmentSourceCatalog, CatalogCell, CatalogRow,
)


def _render(frame):
    from proxy.services.model_source_frame_service import render_model_source_frame
    return render_model_source_frame(frame)


def _decode_render_rows(render):
    """Independent contract decoder; no application source objects consulted."""
    payload = render.to_payload()
    result = {}
    for record in payload["shown_rows"]:
        row = dict(record)
        text = row["source_text"]
        def text_value(value):
            if "source_value_index" in value:
                return row["values"][value["source_value_index"]]
            if "source_text_span" in value:
                start, end = value["source_text_span"]
                return text[start:end]
            return value["literal"]
        decoded_cells = []
        for cells in row["cells"]:
            cell = dict(payload["cell_constant_fields"], **dict(zip(payload["cell_columns"], cells)))
            cell["display_value"] = text_value(cell["display_value"])
            raw = cell["raw_value"]
            cell["raw_value"] = cell["display_value"] if raw.get("same_as_display") else raw["literal"]
            formula = cell.get("formula")
            if isinstance(formula, dict) and formula.get("same_as_raw"):
                cell["formula"] = cell["raw_value"]
            decoded_cells.append(cell)
        row["cells"] = decoded_cells
        result[row["source_row"]] = row
    return result


def test_model_render_roundtrips_literal_source_and_keeps_audit_immutable():
    catalog = _catalog()
    frame = _builder()(catalog, ["Раздел А!R3", "PDF_TEXT!R1"])
    before = frame.payload_json
    render = _render(frame)
    decoded = _decode_render_rows(render)
    audit = frame.to_payload()
    source = {item["source_row"]: item["catalog_row"] for item in audit["offered_rows"] + audit["reference_rows"]}
    for locator, row in decoded.items():
        original = source[locator]
        assert row["source_text"] == original["line"]
        for name in ["values", "column_headers", "section_context", "ambiguities", "header_quantity", "quantity_column_known", "hidden_row", "hidden_sheet", "source_start", "source_end"]:
            assert row[name] == original[name]
        for cell, original_cell in zip(row["cells"], original["cells"]):
            assert cell == {key: value for key, value in original_cell.items() if key != "data_type"}
    assert frame.payload_json == before and frame.source_frame_sha256 == render.source_frame_sha256
    with pytest.raises(FrozenInstanceError):
        render.payload_json = "changed"
    mutable = render.to_payload()
    mutable["shown_rows"].clear()
    assert render.to_payload()["shown_rows"]


def test_model_render_has_every_reader_locator_once_and_identical_branch_hashes():
    catalog = _catalog()
    first = _render(_builder()(catalog, ["Другой лист!R1", "Раздел А!R3"]))
    second = _render(_builder()(catalog, ["Раздел А!R3", "Другой лист!R1"]))
    payload = first.to_payload()
    assert payload["source_manifest"]["columns"] == ["source_row"]
    locators = [record[0] for record in payload["source_manifest"]["records"]]
    assert locators == [row.locator for row in catalog.rows]
    shown = set(payload["requested_source_rows"] + payload["reference_source_rows"])
    assert set(locators) - shown == set(first.available_not_shown_locators)
    assert "available_not_shown_locators" not in payload
    assert payload["available_content_status"] == "not_in_current_frame"
    assert payload["source_manifest"]["read_source"]["argument"] == "source_row"
    assert first.model_render_sha256 == second.model_render_sha256
    unsigned = dict(payload)
    unsigned.pop("model_render_sha256")
    assert hashlib.sha256(_json_bytes(unsigned)).hexdigest() == first.model_render_sha256


def test_model_render_raw_display_difference_formula_and_tag_collision_are_literal():
    cell = CatalogCell(coordinate="D3", column=4, raw_value={"same_as_display": True}, data_type="s",
        display_value="8.00", formula="=SUM(A1:A2)", cached_formula_value=Decimal("8.00"),
        number_format="0.00", hidden_column=True, merged_range="D3:E3")
    row = replace(_row("Лист!R3", title="8.00"), cells=(cell,), values=("8.00", "missing display literal"))
    decoded = _decode_render_rows(_render(_builder()(_catalog((row,)), [row.locator])))[row.locator]
    assert decoded["cells"][0]["raw_value"] == {"same_as_display": True}
    assert decoded["cells"][0]["display_value"] == "8.00"
    assert decoded["cells"][0]["formula"] == "=SUM(A1:A2)"
    assert decoded["cells"][0]["cached_formula_value"] == {"source_value_type": "decimal", "value": "8.00"}
    assert decoded["cells"][0]["number_format"] == "0.00"
    assert decoded["cells"][0]["hidden_column"] is True
    assert decoded["values"] == ["8.00", "missing display literal"]


def test_model_render_long_literals_are_readable_and_not_repeated_in_cell_metadata():
    text = "Дословный исходный текст\n" + "Z" * 2000
    row = _row("Лист!R3", title=text)
    render = _render(_builder()(_catalog((row,)), [row.locator]))
    # Exact line and direct readable values are intentional; raw/display cell
    # aliases must not create the former third and fourth copies.
    assert render.payload_json.count("Z" * 2000) == 2
    assert render.to_payload()["shown_rows"][0]["values"] == [text]
    decoded = _decode_render_rows(render)[row.locator]
    assert decoded["source_text"] == row.line
    assert decoded["cells"][0]["raw_value"] == text
    assert decoded["cells"][0]["display_value"] == text
    assert decoded["values"] == [text]


def test_model_render_394_row_scope_measures_actual_bytes_and_all_locator_coverage():
    rows = tuple(_row(f"Лист {index // 100 + 1}!R{index % 100 + 1}",
        title=f"Unique source body {index}: " + "literal " * 100) for index in range(394))
    frame = _builder()(_catalog(rows), [row.locator for row in rows[150:156]])
    render = _render(frame)
    payload = render.to_payload()
    assert len(payload["source_manifest"]["records"]) == 394
    assert render.render_bytes == len(render.payload_json.encode("utf-8"))
    assert render.render_bytes < frame.frame_bytes
    assert len(_decode_render_rows(render)) == 6
    assert set(render.available_not_shown_locators) == {row.locator for row in rows[:150] + rows[156:]}
    assert rows[0].line not in render.payload_json
    print(f"source-model-render394 frame_bytes={frame.frame_bytes} render_bytes={render.render_bytes}")


def test_model_render_formula_alias_and_extra_display_span_are_exact_unicode():
    cell = CatalogCell(coordinate="B3", column=2, raw_value="=B1+B2", display_value="=B1+B2",
        data_type="f", formula="=B1+B2", cached_formula_value=12.25, number_format="0.00")
    other = CatalogCell(coordinate="C3", column=3, raw_value="😊 12,25", display_value="😊 12,25",
        data_type="s", number_format="General")
    row = replace(_row("Лист!R3", title="=B1+B2 | 😊 12,25"), cells=(cell, other), values=("=B1+B2",))
    render = _render(_builder()(_catalog((row,)), [row.locator]))
    source = render.to_payload()["shown_rows"][0]
    extra = dict(zip(render.to_payload()["cell_columns"], source["cells"][1]))
    assert "source_text_span" in extra["display_value"]
    start, end = extra["display_value"]["source_text_span"]
    assert source["source_text"][start:end] == "😊 12,25"
    decoded = _decode_render_rows(render)[row.locator]
    assert decoded["cells"][0]["formula"] == "=B1+B2"
    assert decoded["cells"][0]["cached_formula_value"] == 12.25
    assert decoded["cells"][1]["raw_value"] == "😊 12,25"


def test_model_render_plain_quantity_unit_headers_and_missing_quantity_remain_readable():
    rows = (
        replace(_row("Лист!R3", title="Монтаж | м² | 3,20"), values=("Монтаж", "м²", "3,20"),
            column_headers=((1, "Работа"), (2, "Ед. изм."), (3, "Количество")),
            header_quantity=3.2, quantity_column_known=True, ambiguities=()),
        replace(_row("Лист!R4", title="Описание без объёма"), header_quantity=None,
            quantity_column_known=True, ambiguities=("quantity_missing",)),
    )
    payload = _render(_builder()(_catalog(rows), [row.locator for row in rows])).to_payload()
    first, missing = payload["shown_rows"]
    assert first["values"] == ["Монтаж", "м²", "3,20"]
    assert first["column_headers"] == [[1, "Работа"], [2, "Ед. изм."], [3, "Количество"]]
    assert first["header_quantity"] == 3.2
    assert missing["header_quantity"] is None and missing["ambiguities"] == ["quantity_missing"]
    assert not any(key in first for key in ("norm_code", "row_role", "coverage", "work_row"))


def test_model_render_requires_untampered_immutable_audit_frame():
    from proxy.services.model_source_frame_service import ModelSourceFrameError
    frame = _builder()(_catalog(), ["Раздел А!R3"])
    with pytest.raises(ModelSourceFrameError, match="IMMUTABLE_APPLICATION_SOURCE_FRAME_REQUIRED"):
        _render(frame.to_payload())
    payload = frame.to_payload()
    payload["offered_rows"][0]["catalog_row"]["line"] = "silently changed source"
    with pytest.raises(ModelSourceFrameError, match="SOURCE_FRAME_AUDIT_HASH_MISMATCH"):
        _render(replace(frame, payload_json=_json_bytes(payload).decode("utf-8")))


def _builder():
    from proxy.services.model_source_frame_service import build_model_source_frame
    return build_model_source_frame


def _row(locator, *, title="Repeated title", kind="ambiguous", headers=(), section="", start=None, raw=None):
    sheet, number = locator.rsplit("!R", 1)
    cell = CatalogCell(coordinate=f"A{number}", column=1,
        raw_value=title if raw is None else raw, display_value=title,
        data_type="s", number_format="General", formula="=SUM(B1:B2)",
        cached_formula_value=Decimal("2.50"), merged_range="A1:A2", hidden_column=True)
    return CatalogRow(locator=locator, sheet=sheet, excel_row=int(number), values=(title,),
        line=f"{locator}: {title}", numbers=(2.5,), row_id=f"row-{locator}",
        sheet_id=f"sheet-{sheet}", cells=(cell,), row_classification=kind,
        classification_reason="literal catalog annotation", classification_confidence=0.7,
        ambiguities=("source ambiguity",), section_context=section, hidden_row=True,
        column_headers=headers, source_start=start,
        source_end=(start + len(title)) if start is not None else None)


def _catalog(rows=None, **changes):
    rows = rows or (
        _row("Раздел А!R1", title="Наименование", kind="header"),
        _row("Раздел А!R2", title="Раздел первый", kind="section"),
        _row("Раздел А!R3", headers=((1, "Наименование"),), section="Раздел первый"),
        _row("Раздел А!R4", headers=((1, "Наименование"),), section="Раздел первый"),
        _row("Другой лист!R1"),
        _row("PDF_TEXT!R1", title="Literal non-table condition\n" + "X" * 4096, start=120),
    )
    names = list(dict.fromkeys(row.sheet for row in rows))
    catalog = AttachmentSourceCatalog(original_name='Документ "клиент" №1.xlsx',
        sheets=tuple((name, sum(row.sheet == name for row in rows)) for name in names),
        rows=tuple(rows), source_file_sha256="a" * 64, source_file_id="source-original")
    return replace(catalog, **changes)


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_full_manifest_partitions_every_locator_and_keeps_exact_reader_addresses():
    catalog = _catalog()
    frame = _builder()(catalog, ["Раздел А!R3"])
    payload = frame.to_payload()
    manifest = payload["source_manifest"]
    records = [dict(zip(manifest["columns"], record)) for record in manifest["records"]]
    assert [row["source_row"] for row in records] == [row.locator for row in catalog.rows]
    assert frame.requested_locators == ("Раздел А!R3",)
    assert frame.reference_locators == ("Раздел А!R1", "Раздел А!R2")
    assert set(frame.shown_locators).isdisjoint(frame.available_not_shown_locators)
    assert set(frame.shown_locators) | set(frame.available_not_shown_locators) == {r.locator for r in catalog.rows}
    assert manifest["read_source"] == {"tool": "read_source", "argument": "source_row",
        "selector": "exact manifest source_row only", "body": "complete catalog row.line"}
    for row in records:
        original = catalog.lookup(row["source_row"])
        assert original is not None
        assert row["content_sha256"] == hashlib.sha256(original.line.encode("utf-8")).hexdigest()
    assert payload["available_not_shown_locators"] == list(frame.available_not_shown_locators)
    assert payload["source_body_representation"] == "catalog rows; not a byte-identical original-file rendering"


def test_offered_rows_preserve_every_literal_field_and_do_not_choose_professional_roles():
    catalog = _catalog()
    frame = _builder()(catalog, ["Раздел А!R3", "Другой лист!R1"])
    rows = {r["source_row"]: r["catalog_row"] for r in frame.to_payload()["offered_rows"]}
    original = catalog.lookup("Раздел А!R3")
    preserved = rows[original.locator]
    assert preserved["line"] == original.line and preserved["values"] == list(original.values)
    assert preserved["column_headers"] == [[1, "Наименование"]]
    assert preserved["section_context"] == original.section_context
    assert preserved["row_classification"] == "ambiguous"
    assert preserved["classification_reason"] == original.classification_reason
    assert preserved["classification_confidence"] == original.classification_confidence
    assert preserved["numbers"] == list(original.numbers)
    assert preserved["hidden_row"] is True and preserved["hidden_sheet"] is False
    cell = preserved["cells"][0]
    assert cell["raw_value"] == original.cells[0].raw_value
    assert cell["display_value"] == original.cells[0].display_value
    assert cell["formula"] == "=SUM(B1:B2)" and cell["hidden_column"] is True
    assert cell["merged_range"] == "A1:A2" and cell["number_format"] == "General"
    assert cell["cached_formula_value"] == {"source_value_type": "decimal", "value": "2.50"}
    assert not any(key in preserved for key in ("norm_code", "row_role", "coverage", "work_row"))
    assert rows["Другой лист!R1"]["line"] != preserved["line"]  # same title, distinct source row


def test_pdf_text_is_readable_not_discarded_or_clipped_and_offsets_stay_literal():
    catalog = _catalog()
    unshown = _builder()(catalog, ["Раздел А!R3"])
    assert "PDF_TEXT!R1" in unshown.available_not_shown_locators
    assert "X" * 4096 not in unshown.payload_json
    shown = _builder()(catalog, ["PDF_TEXT!R1"])
    row = shown.to_payload()["offered_rows"][0]["catalog_row"]
    assert row["line"] == catalog.lookup("PDF_TEXT!R1").line
    assert row["source_start"] == 120 and row["source_end"] == 120 + len(row["values"][0])
    assert "X" * 4096 in shown.payload_json
    record = dict(zip(shown.to_payload()["source_manifest"]["columns"],
                      shown.to_payload()["source_manifest"]["records"][-1]))
    assert record["source_start"] == 120 and record["source_end"] == row["source_end"]


def test_source_order_and_scope_hash_are_identical_for_baseline_and_candidate():
    catalog = _catalog()
    baseline = _builder()(catalog, ["Другой лист!R1", "Раздел А!R4", "Раздел А!R3"])
    candidate = _builder()(catalog, ["Раздел А!R3", "Раздел А!R4", "Другой лист!R1"])
    assert baseline == candidate
    assert baseline.requested_locators == ("Раздел А!R3", "Раздел А!R4", "Другой лист!R1")
    assert baseline.source_frame_sha256 == candidate.source_frame_sha256
    assert baseline.requested_scope_sha256 == candidate.requested_scope_sha256
    assert baseline.catalog_sha256 == candidate.catalog_sha256
    assert _builder()(catalog, ["Раздел А!R4"]).requested_scope_sha256 != baseline.requested_scope_sha256


def test_complete_pdf_offsets_define_interleaved_source_order_not_sheet_groups():
    rows = (_row("PDF!R1", kind="header", start=0), _row("PDF!R2", start=80),
            _row("PDF_TEXT!R1", start=40))
    frame = _builder()(_catalog(rows), ["PDF!R2", "PDF_TEXT!R1"])
    assert frame.requested_locators == ("PDF_TEXT!R1", "PDF!R2")
    assert frame.to_payload()["source_order_basis"] == "converter_markdown_char_offsets"
    assert [row[0] for row in frame.to_payload()["source_manifest"]["records"]] == ["PDF!R1", "PDF_TEXT!R1", "PDF!R2"]


def test_last_textual_header_and_section_before_each_offered_row_are_retained():
    rows = (_row("Лист!R1", title="Старый заголовок", kind="header"),
            _row("Лист!R2", title="Первая глава", kind="section"), _row("Лист!R3"),
            _row("Лист!R4", title="Новый заголовок", kind="header"),
            _row("Лист!R5", title="1", kind="header"),  # numeric legend does not replace textual header
            _row("Лист!R6", title="Вторая глава", kind="section"), _row("Лист!R7"))
    frame = _builder()(_catalog(rows), ["Лист!R3", "Лист!R7"])
    assert frame.reference_locators == ("Лист!R1", "Лист!R2", "Лист!R4", "Лист!R6")
    references = {r["source_row"]: r["catalog_row"]["line"] for r in frame.to_payload()["reference_rows"]}
    assert references == {r.locator: r.line for r in rows if r.locator in frame.reference_locators}


def test_snapshot_is_immutable_and_fresh_payload_cannot_mutate_original_or_hashes():
    mutable = {"literal": ["original", 2]}
    catalog = _catalog((_row("Лист!R1", raw=mutable),))
    frame = _builder()(catalog, ["Лист!R1"])
    original_json, digest = frame.payload_json, frame.source_frame_sha256
    mutable["literal"][0] = "changed after freeze"
    payload = frame.to_payload()
    payload["offered_rows"][0]["catalog_row"]["cells"][0]["raw_value"]["literal"][0] = "changed copy"
    assert frame.payload_json == original_json and frame.source_frame_sha256 == digest
    assert frame.to_payload()["offered_rows"][0]["catalog_row"]["cells"][0]["raw_value"]["literal"][0] == "original"
    with pytest.raises(FrozenInstanceError):
        frame.payload_json = "changed"


def test_typed_datetime_and_decimal_raw_values_are_explicit_not_silent_string_coercion():
    catalog = _catalog((_row("Лист!R1", raw=datetime(2026, 10, 6, 12, 34, 56)),))
    frame = _builder()(catalog, ["Лист!R1"])
    raw = frame.to_payload()["offered_rows"][0]["catalog_row"]["cells"][0]["raw_value"]
    assert raw == {"source_value_type": "datetime", "value": "2026-10-06T12:34:56", "fold": 0}


def test_literal_dictionary_resembling_typed_value_cannot_collide_with_source_identity():
    typed = _catalog((_row("Лист!R1", raw=Decimal("2.50")),))
    dictionary = _catalog((_row("Лист!R1", raw={"source_value_type": "decimal", "value": "2.50"}),))
    first, second = (_builder()(catalog, ["Лист!R1"]) for catalog in (typed, dictionary))
    assert first.catalog_sha256 != second.catalog_sha256
    assert first.source_frame_sha256 != second.source_frame_sha256
    first_payload, second_payload = first.to_payload(), second.to_payload()
    first_types = first_payload["source_literal_type_registry"][first_payload["offered_rows"][0]["source_literal_types_index"]]
    second_types = second_payload["source_literal_type_registry"][second_payload["offered_rows"][0]["source_literal_types_index"]]
    assert first_types["cells"]["tuple"][0]["raw_value"] == "Decimal"
    assert "mapping" in second_types["cells"]["tuple"][0]["raw_value"]


def test_same_sheet_empty_quantity_descriptors_stay_literal_reference_context():
    rows = (_row("Лист!R1", title="Группа изделий"), _row("Лист!R2", title="Вариант 1"),
            _row("Лист!R3", title="Другая группа"), _row("Другой!R1", title="Условия другого листа"))
    rows = tuple(replace(row, quantity_column_known=True, header_quantity=None)
                 if row.locator in {"Лист!R1", "Лист!R3", "Другой!R1"} else row for row in rows)
    catalog = _catalog(rows)
    frame = _builder()(catalog, ["Лист!R2"])
    assert frame.reference_locators == ("Лист!R1", "Лист!R3")
    assert "Другой!R1" in frame.available_not_shown_locators
    assert frame.requested_locators == ("Лист!R2",)
    for record in frame.to_payload()["reference_rows"]:
        assert record["catalog_row"]["line"] == catalog.lookup(record["source_row"]).line
        assert record["catalog_row"]["row_classification"] == "ambiguous"
        assert record["catalog_row"]["header_quantity"] is None
        assert "governs" not in record and "row_role" not in record


def test_same_source_bytes_changed_catalog_metadata_invalidates_frame_and_catalog_hash():
    catalog = _catalog()
    before = _builder()(catalog, ["Раздел А!R3"])
    rows = list(catalog.rows)
    rows[-1] = replace(rows[-1], hidden_sheet=True)
    after = _builder()(replace(catalog, rows=tuple(rows)), ["Раздел А!R3"])
    assert before.to_payload()["source_manifest"]["source_file_sha256"] == after.to_payload()["source_manifest"]["source_file_sha256"]
    assert before.catalog_sha256 != after.catalog_sha256
    assert before.source_frame_sha256 != after.source_frame_sha256


def test_extraction_warnings_remain_visible_and_not_overridden_by_complete_manifest():
    catalog = _catalog(extraction_complete=False, extraction_warnings=("pdf_unread_visual_content",))
    payload = _builder()(catalog, ["Раздел А!R3"]).to_payload()
    assert payload["source_manifest"]["extraction_complete"] is False
    assert payload["source_manifest"]["extraction_warnings"] == ["pdf_unread_visual_content"]


@pytest.mark.parametrize("offered", [["R3"], ["Раздел А!R3 "], ["Отсутствует!R1"], ["Раздел А!R3", "Раздел А!R3"], [3], [True], None, {"Раздел А!R3": "not a locator sequence"}])
def test_nonliteral_absent_and_duplicate_offered_locators_fail_closed(offered):
    from proxy.services.model_source_frame_service import ModelSourceFrameError
    with pytest.raises(ModelSourceFrameError):
        _builder()(_catalog(), offered)


@pytest.mark.parametrize("changes", [
    {"source_file_sha256": "bad"}, {"source_file_id": ""},
    {"sheets": (("Раздел А", 99), ("Другой лист", 1), ("PDF_TEXT", 1))},
    {"rows": (_row("Лист!R1"), _row("Лист!R1")), "sheets": (("Лист", 2),)},
])
def test_inconsistent_application_catalog_is_not_silently_repaired(changes):
    from proxy.services.model_source_frame_service import ModelSourceFrameError
    with pytest.raises(ModelSourceFrameError):
        _builder()(_catalog(**changes), [])


def test_unrepresentable_literal_metadata_fails_explicitly_without_stringifying_it():
    from proxy.services.model_source_frame_service import ModelSourceFrameError
    with pytest.raises(ModelSourceFrameError, match="SOURCE_METADATA_UNSUPPORTED_LITERAL_TYPE"):
        _builder()(_catalog((_row("Лист!R1", raw=object()),)), ["Лист!R1"])


def test_large_394_row_manifest_has_every_locator_without_repeating_unshown_body_metadata():
    rows = tuple(_row(f"Лист {index // 100 + 1}!R{index % 100 + 1}",
        title=f"Unique source body {index}: " + "literal " * 100) for index in range(394))
    catalog = _catalog(rows)
    frame = _builder()(catalog, [row.locator for row in rows[150:156]])
    payload = frame.to_payload()
    manifest = payload["source_manifest"]
    assert len(manifest["records"]) == 394 and len(frame.requested_locators) == 6
    assert len(frame.available_not_shown_locators) == 388
    assert all(catalog.lookup(record[0]).locator == record[0] for record in manifest["records"])
    assert "raw_value" not in json.dumps(manifest) and rows[0].line not in frame.payload_json
    assert [r["catalog_row"]["line"] for r in payload["offered_rows"]] == [r.line for r in rows[150:156]]
    assert frame.manifest_bytes == len(_json_bytes(manifest))
    assert frame.frame_bytes == len(frame.payload_json.encode("utf-8"))
    assert frame.frame_bytes > frame.manifest_bytes > 0
    contributions = {key: len(_json_bytes({key: value})) - 1 for key, value in payload.items()}
    assert 1 + sum(contributions.values()) == frame.frame_bytes
    assert len(payload["source_literal_type_registry"]) == 1
    assert {row["source_literal_types_index"] for row in payload["offered_rows"]} == {0}
    print(f"source-frame394 manifest_bytes={frame.manifest_bytes} frame_bytes={frame.frame_bytes} sections={contributions}")


def test_builder_accepts_every_explicit_source_role_without_packet_cap_or_selection():
    catalog = _catalog()
    frame = _builder()(catalog, [row.locator for row in catalog.rows])
    assert frame.requested_locators == tuple(row.locator for row in catalog.rows)
    assert not frame.reference_locators and not frame.available_not_shown_locators
    assert len(frame.to_payload()["offered_rows"]) == len(catalog.rows)


@pytest.mark.asyncio
async def test_every_unshown_manifest_locator_is_readable_by_the_existing_bound_reader():
    from proxy.services.model_research_tool_service import ModelResearchToolService
    catalog = _catalog()
    frame = _builder()(catalog, ["Раздел А!R3"])
    reader = ModelResearchToolService(
        retrieve=lambda **_kwargs: pytest.fail("source read must not retrieve"),
        frozen_dataset_ids=(), retrieval_kwargs={},
        fallback=lambda *_args: pytest.fail("source read must not open another path"),
        attachment_catalog=catalog, expected_attachment_sha256=catalog.source_file_sha256)
    for locator in frame.available_not_shown_locators:
        result = await reader.execute({"tool": "read_source", "args": {"source_row": locator}})
        assert result.payload["status"] == "ok"
        assert result.chunks[0].content == catalog.lookup(locator).line
        assert result.chunks[0].meta["source_sha256"] == catalog.source_file_sha256
        assert result.chunks[0].meta["body_complete"] is True


def test_actual_unicode_workbook_bytes_cells_and_source_hash_are_not_changed(tmp_path):
    from openpyxl import Workbook
    from proxy.services.attachment_source_catalog_service import load_tabular_source_catalog
    source = tmp_path / 'Исходник «клиент» с пробелом.xlsx'
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Раздел А"
    sheet.append(["Наименование", "Количество", "Единица измерения"])
    sheet.append(["Изделие с пробелами", 7.25, "шт"])
    sheet.append(["Повторное изделие", "=SUM(B2:B2)", "шт"])
    sheet.column_dimensions["A"].hidden = True
    sheet.row_dimensions[3].hidden = True
    sheet["B2"].number_format = "0.000"
    workbook.create_sheet("Условия").append(["Нетабличное условие: применять проектные решения."])
    workbook.save(source)
    before = source.read_bytes()
    catalog = load_tabular_source_catalog(source)
    assert catalog is not None
    frame = _builder()(catalog, ["Раздел А!R3"])
    assert source.read_bytes() == before
    assert frame.to_payload()["source_manifest"]["source_file_sha256"] == hashlib.sha256(before).hexdigest()
    row = frame.to_payload()["offered_rows"][0]["catalog_row"]
    assert row["cells"][1]["raw_value"] == row["cells"][1]["formula"] == "=SUM(B2:B2)"
    assert row["cells"][0]["hidden_column"] is True and row["hidden_row"] is True
    assert "Условия!R1" in frame.available_not_shown_locators
