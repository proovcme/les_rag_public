"""Evidence UI v0.16 — чистые render-хелперы Совушки (без NiceGUI).

Делают видимым evidence-контракт: strip markdown из ячеек, source-chips, статус/бейджи, trace.
Graceful fallback: не unified-ответ → has_evidence=False. Никогда не выдумывают source-link.
"""

from sovushka import answer_render as ar


# ── strip markdown в ячейках ─────────────────────────────────────────────────────────────

def test_table_cells_strip_markdown():
    assert ar.strip_markdown_cell("**Тип котельной**") == "Тип котельной"
    assert ar.strip_markdown_cell("`код`") == "код"
    assert ar.strip_markdown_cell("__жирный__") == "жирный"
    assert ar.strip_markdown_cell("## Заголовок") == "Заголовок"
    assert ar.strip_markdown_cell(None) == ""
    assert ar.strip_markdown_cell(7200) == "7200"

def test_clean_table_rows_strips_keys_and_values():
    rows = [{"**Параметр**": "**Тип**", "Значение": "`Viessmann`"}]
    out = ar.clean_table_rows(rows)
    assert out == [{"Параметр": "Тип", "Значение": "Viessmann"}]


# ── source chips (вместо [Источник 1,2,4]) ───────────────────────────────────────────────

def test_source_chip_docx_paragraph():
    c = ar.source_chip("844a2b53/NTD/СП 327.docx#para85", 1)
    assert c["n"] == 1 and c["file"] == "СП 327.docx" and c["locator"] == "абз.85" and c["has_ref"]

def test_source_chip_xlsx_sheet_row():
    c = ar.source_chip("Ф9.xlsx#Лист1!R12")
    assert c["file"] == "Ф9.xlsx" and "R12" in c["locator"] and c["has_ref"]

def test_source_chip_pdf_page():
    c = ar.source_chip({"source_ref": "Акт.pdf#p3", "source_kind": "extracted_body"})
    assert c["file"] == "Акт.pdf" and c["locator"] == "стр.3" and c["kind"] == "извлечено"

def test_source_chip_no_ref_not_fake_link():
    c = ar.source_chip({"file": "doc.pdf"})   # нет source_ref
    assert c["has_ref"] is False               # chip пометится «без ссылки», не фейк-линк

def test_source_chip_vector_is_weak():
    c = ar.source_chip({"source_ref": "x/y.md#chunk2", "source_kind": "vector_chunk"})
    assert c["weak"] is True

def test_source_chips_numbered():
    chips = ar.source_chips(["a.md#L1", "b.xlsx#Лист!R2"])
    assert [c["n"] for c in chips] == [1, 2]


# ── evidence badges / status / header ────────────────────────────────────────────────────

def test_evidence_badges_canonical_order():
    b = ar.evidence_badges({"COMPUTED": 9, "RETRIEVED": 8, "MISSING": 1, "BLOCKED": 0})
    assert [x["type"] for x in b] == ["RETRIEVED", "COMPUTED", "MISSING"]   # 0 не показываем, порядок канон
    assert b[0]["tone"] == "acc" and b[-1]["tone"] == "warn"

def test_answer_status_tones():
    assert ar.answer_status("complete")["tone"] == "ok"
    assert ar.answer_status("blocked")["tone"] == "err"
    assert ar.answer_status("no_data")["label"] == "НЕТ ДАННЫХ"

def test_header_summary_unified_has_evidence():
    h = ar.header_summary({"intent": "norm_qa", "version": "unified_construction_harness_v0_10",
                           "source_scope": ""}, {"RETRIEVED": 5}, 5, "complete")
    assert h["has_evidence"] and h["status"]["label"] == "ГОТОВО" and h["sources_count"] == 5
    assert h["badges"][0]["type"] == "RETRIEVED" and h["intent"] == "norm_qa"

def test_header_summary_legacy_fallback():
    # старый ответ без evidence/status → has_evidence=False (рендерим по-старому)
    h = ar.header_summary({"channel": "command"}, None, 0, None)
    assert h["has_evidence"] is False

def test_missing_blocked_visible_in_badges():
    b = ar.evidence_badges({"RETRIEVED": 2, "MISSING": 1, "BLOCKED": 1})
    types = [x["type"] for x in b]
    assert "MISSING" in types and "BLOCKED" in types   # видны, не прячутся


# ── trace summary (компактно, без чувствительного) ───────────────────────────────────────

def test_trace_summary_compact():
    s = ar.trace_summary({"intent": "norm_qa", "searched_tiers": ["extracted_body", "lexical_chunk"],
                          "adapter_statuses": {"vector": "unavailable"}, "sources_count": 5})
    assert "route: norm_qa" in s and "extracted_body" in s and "sources: 5" in s

def test_trace_summary_no_mail_body():
    # trace не содержит тел писем (только статусы)
    s = ar.trace_summary({"intent": "mail_entity_search", "adapter_statuses": {"mail": "unavailable"}})
    assert "body" not in s.lower() and "mail=unavailable" in s

def test_trace_summary_empty():
    assert ar.trace_summary(None) == "" and ar.trace_summary({}) == ""


# ── v0.17 evidence-пакет хелперы (citation / sections / conflict) ─────────────────────────

def test_citation_artifact_created():
    art = ar.citation_artifact([{"source_ref": "СП327.docx#para85", "source_kind": "extracted_body",
                                 "snippet": "огнестойкость R45"}])
    assert art["type"] == "citations" and art["count"] == 1 and art["items"][0]["has_ref"]
    assert art["items"][0]["snippet"] == "огнестойкость R45"

def test_citation_no_ref_warning_not_fake_link():
    art = ar.citation_artifact([{"file": "doc.pdf"}])   # нет source_ref
    assert art["items"][0]["has_ref"] is False and art["items"][0]["source_ref"] == ""

def test_citation_mail_snippet_only():
    art = ar.citation_artifact([{"source_ref": "m#id1", "source_kind": "eml_message",
                                 "snippet": "кратко", "body": "ПОЛНОЕ ТЕЛО ПИСЬМА"}])
    assert "ПОЛНОЕ ТЕЛО" not in str(art)   # полное тело письма не попадает в цитату

def test_citation_drawer_item_opens_file_like_refs():
    item = ar.citation_drawer_item({"source_ref": "RAG_Content/NTD/SP.docx#para85",
                                    "source_kind": "extracted_body",
                                    "snippet": "фрагмент"}, 3)
    assert item["n"] == 3
    assert item["open_url"].startswith("/lite-api/rag/file/raw?path=RAG_Content")
    assert item["location"] == "para85"
    assert item["snippet"] == "фрагмент"

def test_citation_drawer_item_disabled_without_ref():
    item = ar.citation_drawer_item({"file": "doc.pdf"})
    assert item["open_url"] == ""
    assert "нет source_ref" in item["unavailable_reason"].lower()

def test_citation_drawer_item_weak_source_does_not_fake_open():
    item = ar.citation_drawer_item({"source_ref": "db/chunk.md#chunk2", "source_kind": "vector_chunk"})
    assert item["weak"] is True
    assert item["open_url"] == ""
    assert "vector" in item["unavailable_reason"]

def test_group_evidence_sections_order_and_missing_visible():
    from proxy.services.evidence_contract import EvidenceItem, EvidenceType, block_of
    blocks = [block_of(EvidenceType.MISSING, "M", [EvidenceItem(EvidenceType.MISSING, "x", status="missing")]),
              block_of(EvidenceType.RETRIEVED, "R",
                       [EvidenceItem(EvidenceType.RETRIEVED, "y", source_refs=["сп.docx#p1"], status="ok")])]
    secs = ar.group_evidence_sections(blocks)
    assert [s["type"] for s in secs] == ["RETRIEVED", "MISSING"]   # канон-порядок, MISSING виден
    assert secs[1]["title"] == "Не хватает"

def test_conflict_block_visible_with_sources():
    cb = ar.conflict_block([{"label": "Вариант А", "value": "2291 кВт", "sources": ["сп.docx#p1"]},
                            {"label": "Вариант Б", "value": "1045 кВт", "sources": ["письмо#id5"]}])
    assert cb and len(cb["variants"]) == 2 and cb["variants"][0]["chips"][0]["n"] == 1

def test_conflict_block_none_for_single_value():
    assert ar.conflict_block([{"label": "A", "value": "1", "sources": []}]) is None
