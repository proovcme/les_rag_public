import asyncio
import hashlib
import inspect
import json
import sqlite3
import time
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import openpyxl
import pytest

from proxy.routers import chat
from proxy.services import chat_evidence_application_service as service
from proxy.services.chat_attachment_service import preserve_read_attachment
from proxy.services.model_answer_table_service import citation_mark_length
from proxy.services.tool_harness_service import ToolHarness
from proxy.services.web_research_config_service import WebResearchConfig


@pytest.mark.parametrize("answer", [
    "| source_row | title | unit | quantity | norm_code | nr_sp_rule_id |\n"
    "| --- | --- | --- | --- | --- | --- |\n"
    "| СКС!R69 | Прокладка труб | м | 1200 | ГЭСНм08-02-409-09 | nrsp-49.3 |",
    "source_row=СКС!R69, title=Прокладка труб, unit=м, quantity=1200, norm_code=ГЭСНм08-02-409-09, nr_sp_rule_id=nrsp-49.3",
    "Строка 69\nsource_row: СКС!R69\ntitle: Прокладка труб\nunit: м\nquantity: 1200\nnorm_code: ГЭСНм08-02-409-09\nnr_sp_rule_id: nrsp-49.3",
    "Строка 69 — Прокладка труб; unit: м; quantity: 1200; norm_code: ГЭСНм08-02-409-09; nr_sp_rule_id: nrsp-49.3",
])
def test_model_accrual_rule_survives_visible_formats_and_review_projection(answer):
    parsed = service.parse_model_rag_result(answer)
    assert parsed is not None
    row = parsed[1][0]
    assert row["nr_sp_rule_id"] == "nrsp-49.3"
    assert service.compact_estimator_draft_rows([row])[0]["nr_sp_rule_id"] == "nrsp-49.3"


def test_typed_card_body_is_deferred_instead_of_truncated_to_a_prefix():
    """An identity pointer never masquerades as a partially delivered card."""
    prefix = "Шифр: ГЭСНм08-02-409-09\n" + "Условия и основание НР/СП. " * 32 + "nrsp-49.3"
    hit = SimpleNamespace(content=prefix + "Обзор ресурсов. " * 140,
                          doc_id="card", doc_name="smeta_norm_cards.v1", score=1,
                          meta={"minimum_evidence_body_chars": len(prefix)})
    # Two distinct sources must each reserve their required prefix. Exact
    # duplicates have a separate sharing contract below.
    other = SimpleNamespace(**{**vars(hit), "doc_id": "other-card"})
    query_hits = [("прокладка труб", [hit, other])]
    headers = service.model_rag_evidence_header_chars(query_hits, hits_per_query=2)
    groups, chunks, omitted = service.build_model_rag_evidence_groups(
        query_hits, max_chars=headers + len(prefix) + 100, hits_per_query=2)
    assert chunks and omitted == ["Q1.H1", "Q1.H2"]
    assert all(chunk.meta["body_status"] == "deferred_capacity" for chunk in chunks)
    assert all(chunk.meta["card_body_shown"] is False for chunk in chunks)
    assert all(not chunk.content.startswith(prefix) for chunk in chunks)
    assert len("\n\n".join(groups)) <= headers + len(prefix) + 100


def test_query_page_preserves_whole_candidate_bodies_and_query_cursor():
    hits = [SimpleNamespace(content=f"code-{i}: " + "x" * 3000,
                            doc_id=str(i), doc_name="cards", score=1,
                            meta={"minimum_evidence_body_chars": 480}) for i in range(12)]
    queries = [("first", hits[:6]), ("second", hits[6:])]
    first_groups, _first_chunks, _ = service.build_model_rag_evidence_groups(
        queries[:1], max_chars=100000, hits_per_query=6)
    budget = len("\n\n".join(first_groups)) + 2000
    included, deferred, omitted = service.select_model_rag_query_hits_for_budget(
        queries, max_chars=budget, hits_per_query=6, require_card_bodies=True)
    assert [q for q, _ in included] == ["first"]
    assert [q for q, _ in deferred] == ["second"]
    assert omitted == []
    groups, chunks, omitted = service.build_model_rag_evidence_groups(
        included, max_chars=budget, hits_per_query=6)
    assert [c.doc_id for c in chunks] == [str(i) for i in range(6)]
    assert all(c.content == hits[i].content for i, c in enumerate(chunks))
    assert all(c.meta["body_status"] == "full" for c in chunks)
    assert omitted == []
    assert len("\n\n".join(groups)) <= budget


def test_evidence_page_keeps_decided_rows_pending_until_retrieved_tail_is_delivered():
    held = service.model_rag_evidence_page_state(
        sheet="other sheet", packet=["other sheet!R17"],
        leftover_query_hits=[("unaltered model query", [])],
        query_offset=6, query_provenance={"unaltered model query": "model"},
        query_addresses={"unaltered model query": ["other sheet!R17"]})
    assert held["locators"] == ["other sheet!R17"]  # even after a terminal MISSING
    assert held["queries"] == ["unaltered model query"]
    assert held["query_offset"] == 6
    assert held["query_addresses"]["unaltered model query"] == ["other sheet!R17"]
    assert service.model_rag_evidence_page_state(
        sheet="other sheet", packet=["other sheet!R17"], leftover_query_hits=[],
        query_offset=7, query_provenance={}, query_addresses={}) == {}


def test_prior_evidence_page_exposes_only_authored_decisions_and_their_exact_cards():
    rows = [{"source_row": "S!R2", "row_role": "work", "norm_code": "01-02-003-04",
             "evidence_refs": ["Q1.H6"], "evidence_bindings": {"Q1.H6": "durable-card"}}]
    card = SimpleNamespace(content="exact previously shown card", doc_name="cards", doc_id="a", score=1,
                           meta={"global_evidence_id": "durable-card", "model_evidence_ref": "Q1.H6"})
    other = SimpleNamespace(content="unselected card", meta={"global_evidence_id": "unselected"})
    payload, retained = service.model_rag_prior_page_context(rows, [card, other])
    assert retained == [card]
    assert payload["prior_model_decisions"][0]["norm_code"] == "01-02-003-04"
    assert payload["prior_model_decisions"][0]["evidence_bindings"] == {"Q1.H6": "durable-card"}
    assert payload["previously_shown_cited_evidence"][0]["content"] == card.content
    assert "unselected card" not in json.dumps(payload)


def test_prior_model_context_does_not_repeat_application_diagnostics_as_model_choices():
    row = {"source_row": "Any!R2", "operation_id": "op_1", "row_role": "work", "title": "Authored operation",
           "norm_code": "01-02-003-04", "norm_status": "NEEDS_RESEARCH", "condition_match": "unknown",
           "open_gap": "authored condition question", "evidence_refs": ["Q1.H1"],
           "evidence_bindings": {"Q1.H1": "card-id"}, "confirmed_price": 0,
           "_quality_gate": {"technical_dump": "x" * 20000}, "_evidence_check": {"technical_dump": "y" * 20000},
           "quality_message": "application-derived message"}
    card = SimpleNamespace(content="complete cited evidence", meta={"global_evidence_id": "card-id", "model_evidence_ref": "Q1.H1"})
    payload, retained = service.model_rag_prior_page_context([row], [card])
    decision = payload["prior_model_decisions"][0]
    for key in ("operation_id", "norm_code", "norm_status", "condition_match", "open_gap", "evidence_refs", "evidence_bindings", "confirmed_price"):
        assert decision[key] == row[key]
    assert not {"_quality_gate", "_evidence_check", "quality_message"} & decision.keys()
    assert retained == [card] and payload["previously_shown_cited_evidence"][0]["content"] == card.content
    assert row["_evidence_check"]["technical_dump"] == "y" * 20000  # durable source is untouched


@pytest.mark.parametrize("chosen,expected", [
    ("ГЭСНм08-03-593-19", False), ("ГЭСНм08-03-593-12", True),
])
def test_prior_page_exposes_literal_citation_comparison_without_rewriting_choice(chosen, expected):
    row = {"source_row": "Любой лист!R2", "operation_id": "op_authored", "row_role": "work",
           "norm_code": chosen, "norm_status": "EXACT", "evidence_refs": ["Q9.H1"],
           "evidence_bindings": {"Q9.H1": "immutable-card"},
           "_evidence_check": {"code_not_in_refs": not expected, "technical_dump": "x" * 20000}}
    before = json.dumps(row, ensure_ascii=False)
    card = SimpleNamespace(content="Шифр: ГЭСНм08-03-593-12\nПолная карточка без изменений.",
                           doc_name="cards", meta={"global_evidence_id": "immutable-card", "model_evidence_ref": "Q9.H1"})
    payload, retained = service.model_rag_prior_page_context([row], [card])
    facts = payload["prior_result_structural_facts"][0]
    assert facts["source_row"] == row["source_row"] and facts["operation_id"] == "op_authored"
    assert facts["norm_reference"] == {"selected_code": chosen, "cited_ciphers": ["ГЭСНм08-03-593-12"],
                                       "code_in_refs": expected, "unresolved_refs": []}
    assert payload["prior_model_decisions"][0]["norm_code"] == chosen
    assert payload["prior_model_decisions"][0]["norm_status"] == "EXACT"
    assert payload["previously_shown_cited_evidence"][0]["content"] == card.content
    assert retained == [card] and "technical_dump" not in json.dumps(payload)
    assert json.dumps(row, ensure_ascii=False) == before


def test_prior_page_unknown_citation_is_not_false_confirmation_from_stale_diagnostics():
    row = {"source_row": "S!R2", "row_role": "work", "norm_code": "ГЭСНм08-03-593-19",
           "evidence_refs": ["Q9.H1"], "evidence_bindings": {"Q9.H1": "absent-card"},
           "_evidence_check": {"code_not_in_refs": False, "cited_ciphers": ["ГЭСНм08-03-593-19"]}}
    payload, _ = service.model_rag_prior_page_context([row], [])
    facts = payload["prior_result_structural_facts"][0]["norm_reference"]
    assert facts == {"selected_code": row["norm_code"], "cited_ciphers": [],
                     "code_in_refs": None, "unresolved_refs": ["Q9.H1"]}
    assert payload["prior_model_decisions"][0]["norm_code"] == row["norm_code"]


def test_prior_page_never_replays_stale_norm_diagnostics_for_a_row_without_a_norm():
    row = {"source_row": "S!R2", "row_role": "material", "norm_code": "",
           "_evidence_check": {"technical_dump": "previous norm diagnostics"}}
    before = json.dumps(row)
    payload, _ = service.model_rag_prior_page_context([row], [])
    assert payload["prior_result_structural_facts"] == []
    assert payload["prior_model_decisions"][0]["norm_code"] == ""
    assert json.dumps(row) == before


def test_prior_page_compares_with_the_immutable_binding_when_a_handle_is_reused():
    row = {"source_row": "S!R2", "norm_code": "ГЭСНм08-03-593-12", "evidence_refs": ["Q1.H1"],
           "evidence_bindings": {"Q1.H1": "old-card"}}
    old = SimpleNamespace(content="Шифр: ГЭСНм08-03-593-12", doc_name="cards",
                          meta={"global_evidence_id": "old-card", "model_evidence_ref": "Q1.H1"})
    new = SimpleNamespace(content="Шифр: ГЭСНм08-03-593-19", doc_name="cards",
                          meta={"global_evidence_id": "new-card", "model_evidence_ref": "Q1.H1"})
    payload, retained = service.model_rag_prior_page_context([row], [new, old])
    reference = payload["prior_result_structural_facts"][0]["norm_reference"]
    assert reference["code_in_refs"] is True
    assert reference["cited_ciphers"] == ["ГЭСНм08-03-593-12"]
    assert retained == [old]
    assert payload["prior_model_decisions"][0]["evidence_bindings"] == row["evidence_bindings"]


def test_prior_page_reports_unconfirmed_material_quantity_without_changing_source_or_role(tmp_path):
    from proxy.services.attachment_source_catalog_service import load_tabular_source_catalog
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Любой лист"
    for values in (["№ п/п", "Наименование", "Ед. изм.", "Кол-во"],
                   ["5.4", "Скоба для трубы", "", ""], ["", "- Ø20 мм", "шт.", 100]):
        sheet.append(values)
    source = tmp_path / "Разреженная спецификация.xlsx"
    book.save(source)
    catalog = load_tabular_source_catalog(source)
    rows = [{"source_row": "Любой лист!R2", "operation_id": "op_material", "row_role": "material",
             "title": "Модельное решение", "quantity": 100, "unit": "шт."},
            {"source_row": "Любой лист!R3", "row_role": "material", "quantity": 100, "unit": "шт."},
            {"source_row": "Любой лист!R2", "row_role": "header", "quantity": None, "unit": ""}]
    before = json.dumps(rows, ensure_ascii=False)
    payload, _ = service.model_rag_prior_page_context(rows, [], source_catalog=catalog)
    facts = payload["prior_result_structural_facts"]
    assert len(facts) == 1 and facts[0]["operation_id"] == "op_material"
    observed = facts[0]["source_comparison"]
    assert "source_quantity_unconfirmed:Любой лист!R2" in observed["errors"]
    assert observed["quantity_column_known"] is True and observed["source_quantity"] is None
    assert observed["model_quantity"] == 100
    assert payload["prior_model_decisions"][0]["row_role"] == "material"
    assert json.dumps(rows, ensure_ascii=False) == before
    assert catalog.lookup("Любой лист!R2").header_quantity is None


@pytest.mark.parametrize("quantity,unit", [(0.8, "км"), (800, "м")])
def test_prior_page_does_not_report_a_source_gap_for_equivalent_measures(tmp_path, quantity, unit):
    from proxy.services.attachment_source_catalog_service import load_tabular_source_catalog
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Источник"
    sheet.append(["Наименование", "Ед. изм.", "Кол-во"])
    sheet.append(["Ресурс", "м", 800])
    source = tmp_path / "Единицы.xlsx"
    book.save(source)
    catalog = load_tabular_source_catalog(source)
    row = {"source_row": "Источник!R2", "row_role": "material", "quantity": quantity, "unit": unit}
    payload, _ = service.model_rag_prior_page_context([row], [], source_catalog=catalog)
    assert payload["prior_result_structural_facts"] == []
    assert payload["prior_model_decisions"][0]["quantity"] == quantity
    assert payload["prior_model_decisions"][0]["unit"] == unit


def test_page_cursor_and_cached_cards_survive_restart_with_terminal_model_rows(tmp_path):
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService
    svc = WorkbookResearchJobService(tmp_path / "state.sqlite")
    identity = svc.identity(session_id="test", attachment_id="read_123456abcdef", source_sha256="a" * 64,
                            dataset_ids=[], profile_revision_id="factory", model_identity="qwen", question="LSR")
    job = svc.begin_or_resume(identity)
    held = service.model_rag_evidence_page_state(
        sheet="S", packet=["S!R2"], leftover_query_hits=[("second query", [])],
        query_offset=5, query_provenance={"second query": "derived"}, query_addresses={"second query": ["S!R2"]})
    row = {"source_row": "S!R2", "row_role": "work", "norm_status": "MISSING", "open_gap": "model reason"}
    svc.record_search_cache(job["job_id"], {"second query": [{"content": "exact card", "meta": {}}]})
    svc.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2"], accepted_rows=[row],
                      evidence=[], remaining=[], held_packet=held)
    svc.pause(job["job_id"], remaining=["S!R2"])
    reopened = WorkbookResearchJobService(tmp_path / "state.sqlite").begin_or_resume(identity)
    assert reopened["held_packet"] == held
    assert reopened["accepted_rows"][0]["norm_status"] == "MISSING"
    assert reopened["accepted_rows"][0]["open_gap"] == "model reason"
    assert service.restore_query_hits_from_cache(held["queries"], reopened["query_cache"])[0][1][0].content == "exact card"


def test_measurement_attributes_omitted_refs_after_page_offset():
    result = service.model_rag_query_measurement(pass_hits=[("second query", [])],
                                               omitted_refs=["Q7.H6"], query_offset=6)
    assert result["queries"][0]["cards_omitted"] == 1


def test_surplus_explanatory_cell_never_moves_unit_quantity_or_norm_status():
    answer = (
        "| source_row | row_role | work_row | title | unit | quantity | norm_code | norm_status | open_gap | evidence_refs |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| S!R7 | unresolved | S!R7 | Устройство проёма | шт. | 12 | | NEEDS_RESEARCH | insufficient_source_data | Не заданы условия | Q4.H6 |"
    )
    diagnostics = []
    assert service.parse_model_rag_result(answer, diagnostics=diagnostics) == (answer, [])
    assert diagnostics[0]["decision"]["raw_line"] == answer.splitlines()[-1]
    assert diagnostics[0]["decision"]["raw_cells"][8:] == [
        "insufficient_source_data", "Не заданы условия", "Q4.H6",
    ]
    escaped_answer = answer.replace("insufficient_source_data | Не заданы условия",
                                    r"insufficient_source_data \| Не заданы условия")
    row = service.parse_model_rag_result(escaped_answer)[1][0]
    assert row["title"] == "Устройство проёма"
    assert row["unit"] == "шт."
    assert row["quantity"] == 12
    assert row.get("norm_code", "") == ""
    assert row["norm_status"] == "NEEDS_RESEARCH"
    assert "insufficient_source_data" in row["open_gap"] and "Не заданы условия" in row["open_gap"]


def test_prior_operation_identity_is_visible_and_roundtrips_without_model_chosen_revision():
    previous = {"operation_id": "op_existing", "revision": 2, "source_row": "S!R7", "title": "Work", "unit": "м", "quantity": 12, "norm_code": "01-02-003-04"}
    compact = service.compact_estimator_draft_rows([previous])[0]
    assert compact["operation_id"] == "op_existing"
    answer = "source_row=S!R7, operation_id=op_existing, title=Work, unit=м, quantity=12, norm_code=01-02-003-04"
    row = service.parse_model_rag_result(answer)[1][0]
    assert row["operation_id"] == "op_existing"
    assert "revision" not in row


def test_duplicate_card_bodies_are_shared_with_all_query_hit_refs_intact():
    content = ("Шифр: 01-02-003-04\nExact conditions. " * 40).rstrip()
    hit = SimpleNamespace(content=content, doc_id="same-card", doc_name="cards", score=1,
                          meta={"source_ref": "base#1", "minimum_evidence_body_chars": len(content)})
    queries = [(f"query {i}", [hit]) for i in range(8)]
    complete_groups, _chunks, _ = service.build_model_rag_evidence_groups(
        queries, max_chars=100000, hits_per_query=1)
    budget = len("\n\n".join(complete_groups))
    included, deferred, omitted = service.select_model_rag_query_hits_for_budget(
        queries, max_chars=budget, hits_per_query=1, require_card_bodies=True)
    assert len(included) == 8 and deferred == [] and omitted == []
    groups, chunks, omitted = service.build_model_rag_evidence_groups(
        included, max_chars=budget, hits_per_query=1)
    rendered = "\n\n".join(groups)
    assert rendered.count(content) == 1
    assert len(rendered) <= budget
    assert [chunk.meta["model_evidence_ref"] for chunk in chunks] == [f"Q{i}.H1" for i in range(1, 9)]
    assert all(chunk.content == content for chunk in chunks)
    assert omitted == []


def test_equal_card_text_from_distinct_sources_is_never_shared():
    content = "conditions " * 70
    hits = [SimpleNamespace(content=content, doc_id="card", doc_name="cards", score=1,
                            meta={"source_ref": source}) for source in ("edition-a#1", "edition-b#1")]
    groups, chunks, omitted = service.build_model_rag_evidence_groups(
        [("query", hits)], max_chars=10000, hits_per_query=2)
    assert "\n\n".join(groups).count(content.rstrip()) == 2
    assert not any(c.meta.get("shared_evidence_ref") for c in chunks)
    assert not omitted


def test_existing_operation_revision_survives_checkpoint_and_next_page(tmp_path):
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService
    svc = WorkbookResearchJobService(tmp_path / "state.sqlite")
    job = svc.begin_or_resume(svc.identity(session_id="test", attachment_id="read_123456abcdef", source_sha256="a" * 64,
                                         dataset_ids=[], profile_revision_id="factory", model_identity="qwen", question="LSR"))
    first = {"source_row": "S!R7", "row_role": "work", "title": "Work", "unit": "м", "quantity": 12, "norm_status": "MISSING"}
    job = svc.record_packet(job["job_id"], sheet="S", packet_locators=["S!R7"], accepted_rows=[first], evidence=[], remaining=["S!R7"])
    context, _ = service.model_rag_prior_page_context(job["accepted_rows"], [])
    op = context["prior_model_decisions"][0]["operation_id"]
    second = service.parse_model_rag_result(
        f"source_row=S!R7, operation_id={op}, row_role=work, title=Clarified work, unit=м, quantity=12, norm_code=, norm_status=NEEDS_RESEARCH"
    )[1][0]
    assert not service.validate_model_rag_result_structure([second], [], expected_source_rows=1,
                                                         validate_evidence_refs=False, existing_operation_rows=job["accepted_rows"])
    job = svc.record_packet(job["job_id"], sheet="S", packet_locators=["S!R7"], accepted_rows=[second], evidence=[], remaining=[])
    assert len(job["accepted_rows"]) == 1
    assert job["accepted_rows"][0]["operation_id"] == op
    assert job["accepted_rows"][0]["revision"] == 2
    assert job["accepted_rows"][0]["title"] == "Clarified work"
    assert [r["revision"] for r in svc.list_revisions(job["job_id"], op)] == [1, 2]


def test_prior_page_shares_exact_cited_body_without_losing_immutable_refs():
    cards = [SimpleNamespace(content="same exact body", doc_id="a", doc_name="cards", score=1,
                             meta={"global_evidence_id": f"immutable-{i}", "model_evidence_ref": f"Q{i}.H1"})
             for i in (1, 2)]
    rows = [{"source_row": "S!R7", "evidence_bindings": {"Q1.H1": "immutable-1", "Q2.H1": "immutable-2"}}]
    payload, retained = service.model_rag_prior_page_context(rows, cards)
    evidence = payload["previously_shown_cited_evidence"]
    assert retained == cards
    assert [e["global_evidence_id"] for e in evidence] == ["immutable-1", "immutable-2"]
    assert evidence[0]["content"] == "same exact body"
    assert "immutable-1" in evidence[1]["content"]
    assert json.dumps(payload).count("same exact body") == 1


@pytest.mark.parametrize("operation_id,source_row,error", [
    ("invented", "S!R7", "unknown_operation_id:S!R7:invented"),
    ("op_known", "S!R8", "operation_source_mismatch:S!R8:op_known"),
])
def test_operation_identity_cannot_be_invented_or_moved(operation_id, source_row, error):
    prior = {"operation_id": "op_known", "source_row": "S!R7", "row_role": "work"}
    current = {"operation_id": operation_id, "source_row": source_row, "row_role": "material"}
    errors = service.validate_model_rag_result_structure([current], [], expected_source_rows=1,
                                                       existing_operation_rows=[prior])
    assert error in errors


def test_invalid_operation_identity_never_drops_other_operations_on_same_source():
    rows = [{"source_row": "S!R7", "row_role": "material", "title": "Valid material"},
            {"source_row": "S!R7", "row_role": "material", "title": "Other", "operation_id": "invented"}]
    errors = service.validate_model_rag_result_structure(rows, [], expected_source_rows=1, existing_operation_rows=[])
    catalog = SimpleNamespace(lookup=lambda key: SimpleNamespace(sheet="S", locator="S!R7"))
    kept = service.sheet_pass_keep_rows(rows, sheet="S", catalog=catalog, errors=errors)
    assert kept == [rows[0]]



def test_web_reader_is_visible_only_in_explicit_extended_request_snapshot():
    tools = ["web_search", "web_read", "filesystem_search"]

    simple = service.web_tools_for_request(
        tools,
        WebResearchConfig("simple", "", "", ""),
    )
    extended = service.web_tools_for_request(
        tools,
        WebResearchConfig(
            "extended",
            "http://127.0.0.1:8888",
            "http://127.0.0.1:11235",
            "",
        ),
    )

    assert simple == ["web_search", "filesystem_search"]
    assert extended == tools


def test_web_tool_sources_replace_search_snippet_with_read_page_provenance():
    tool_results = [
        {
            "tool": "web_search",
            "result": {
                "results": [
                    {
                        "title": "Каталог",
                        "snippet": "Краткая выдача",
                        "url": "https://public.example/material",
                        "domain": "public.example",
                    }
                ]
            },
            "sources": [
                {
                    "kind": "web",
                    "title": "Каталог",
                    "url": "https://public.example/material",
                    "domain": "public.example",
                }
            ],
        },
        {
            "tool": "web_read",
            "result": {
                "title": "Каталог материалов",
                "text": "Полный текст страницы",
                "final_url": "https://public.example/material",
                "retrieved_at": "2026-09-02T10:00:00+00:00",
            },
            "sources": [
                {
                    "kind": "web_page",
                    "title": "Каталог материалов",
                    "url": "https://public.example/material",
                }
            ],
        },
    ]

    source_map = service.web_source_map_from_tool_results(tool_results)

    assert len(source_map) == 1
    assert source_map[0]["label"] == "Источник 1"
    assert source_map[0]["snippet"] == "Полный текст страницы"
    assert source_map[0]["locator"] == {
        "kind": "web_result",
        "url": "https://public.example/material",
        "title": "Каталог материалов",
        "retrieved_at": "2026-09-02T10:00:00+00:00",
        "excerpt": "Полный текст страницы",
    }


def test_attachment_workbook_tools_survive_restrictive_model_shortlist():
    tools = [
        "dataset_map",
        "search_sources",
        "read_source",
        "read_excel_source",
        "search_project_tables",
        "read_project_table",
        "build_lsr_workbook",
        "build_vor_workbook",
    ]

    ordered = service.prioritize_workbook_tools(tools, workbook_phase=True)
    shortlist = ToolHarness().shortlist(
        "Собери ЛСР",
        allowed_tools=ordered,
        limit=5,
        dataset_ids=("selected",),
        workflow_phase="draft",
        model_preset="qwen-9b-restrictive",
        runtime_available=frozenset(tools),
        attachment_ids=("read_123456abcdef",),
    )

    assert ordered[:2] == ["build_lsr_workbook", "build_vor_workbook"]
    assert set(ordered) == set(tools)
    assert [item["name"] for item in shortlist["tools"][:2]] == [
        "build_lsr_workbook",
        "build_vor_workbook",
    ]


def test_workbook_artifact_intent_narrows_visible_tools_by_operator_noun():
    tools = [
        "search_sources",
        "read_source",
        "build_lsr_workbook",
        "build_vor_workbook",
    ]

    assert service.workbook_artifact_intent("Собери ВОР из спецификации") == "vor"
    assert service.workbook_artifact_intent("сделай ведомость объёмов работ") == "vor"
    assert service.workbook_artifact_intent("Собери смету") == "lsr"
    # Code retains both capabilities when target and input nouns are mixed.
    assert service.workbook_artifact_intent("Собери ЛСР из прикреплённого ВОР") == "both"
    assert service.workbook_artifact_intent("что видно в документе") == "both"

    # A bare ВОР request must not keep the priced ЛСР tool visible.
    vor_only = service.prioritize_workbook_tools(
        tools, workbook_phase=True, question="Собери проверяемый ВОР"
    )
    assert vor_only == ["build_vor_workbook", "search_sources", "read_source"]
    assert "build_lsr_workbook" not in vor_only

    # A sole ЛСР mention keeps only the priced workbook tool.
    lsr_only = service.prioritize_workbook_tools(
        tools, workbook_phase=True, question="Собери ЛСР"
    )
    assert "build_lsr_workbook" in lsr_only
    assert "build_vor_workbook" not in lsr_only

    # Unspecified artifact keeps both visible for the model to decide.
    both = service.prioritize_workbook_tools(
        tools, workbook_phase=True, question="что видно в документе"
    )
    assert {"build_lsr_workbook", "build_vor_workbook"} <= set(both)

    # Outside the workbook phase nothing is narrowed.
    assert service.prioritize_workbook_tools(
        tools, workbook_phase=False, question="Собери ВОР"
    ) == tools


def test_tool_selector_request_declares_bound_attachment_without_copying_its_text():
    payload = service.tool_selector_request_payload(
        question="build workbook",
        mode="estimator",
        dataset_ids=[],
        target_file_ref={},
        round_no=1,
        attachment_id="read_123456abcdef",
    )

    assert payload["attachment"] == {
        "bound": True,
        "attachment_id": "read_123456abcdef",
    }
    assert "attachment_context" not in payload


def test_native_model_tool_schemas_preserve_registered_contract():
    schemas = service.native_model_tool_schemas(
        [
            {
                "name": "search_sources",
                "summary": "Search selected sources",
                "input_schema": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                    "additionalProperties": False,
                },
            }
        ]
    )

    assert schemas == [
        {
            "type": "function",
            "function": {
                "name": "search_sources",
                "description": "Search selected sources",
                "parameters": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                    "additionalProperties": False,
                },
            },
        }
    ]


def test_model_authored_search_batch_is_not_cut_to_five_calls():
    raw = json.dumps(
        {
            "calls": [
                {"tool": "search_sources", "args": {"q": f"work item {index}"}}
                for index in range(10)
            ]
        }
    )

    calls = chat._parse_model_tool_calls(
        raw,
        allowed_tools={"search_sources"},
        max_calls=48,
    )

    assert [call["args"]["q"] for call in calls] == [
        f"work item {index}" for index in range(10)
    ]


def test_model_rag_batch_does_not_accept_a_legacy_json_protocol():
    queries = [f"точный запрос {index}" for index in range(30)]

    assert service.parse_model_rag_queries(
        json.dumps({"queries": queries}, ensure_ascii=False)
    ) == []


def test_model_rag_batch_reads_plain_model_authored_lines_without_a_row_limit():
    queries = [f"точный запрос {index}" for index in range(30)]

    assert service.parse_model_rag_queries("\n".join(queries)) == queries


def test_existing_estimator_profile_keeps_model_authored_query_workflow_without_new_flag():
    assert service.profile_uses_model_driven_retrieval(
        {
            "revision_id": "user:profile:estimator:legacy",
            "mode": "estimator",
            "rag_policy": {"grounded": True, "system_datasets": ["smeta"]},
        }
    ) is True
    assert service.profile_uses_model_driven_retrieval(
        {"mode": "search", "rag_policy": {"grounded": True}}
    ) is False


def test_sheet_packet_prompts_do_not_request_the_whole_sheet_again():
    query = service.sheet_pass_query_instruction(
        {"mode": "estimator"}, sheet="Другой раздел", sheet_index=2, sheet_count=10,
    )
    assert "только по исходным строкам текущего пакета" in query
    assert "Манифест" in query
    answer = service.sheet_pass_question_tail(
        "Собери ЛСР", sheet="Другой раздел", sheet_index=2, sheet_count=10,
        remaining_work=["Другой раздел!R300"],
    )
    assert "Другой раздел!R300" in answer
    assert "по всем строкам ЭТОГО листа" not in answer
    assert "все строки текущего листа" not in answer
    assert "новые и изменённые операции текущего пакета" in answer
    assert "неизменённые операции сохраняются приложением" in answer


def test_only_estimator_model_rag_uses_the_dedicated_smeta_catalog():
    assert service.profile_uses_smeta_norm_retrieval({"mode": "estimator"}) is True
    assert service.profile_uses_smeta_norm_retrieval(
        {
            "mode": "search",
            "rag_policy": {"model_authored_initial_query": True},
        }
    ) is False


def test_model_rag_evidence_keeps_configured_candidates_for_every_model_query():
    query_hits = []
    for query_index in range(1, 31):
        hits = [
            SimpleNamespace(
                content=(
                    f"Шифр: ГЭСН{query_index:02d}-00-000-{hit_index:02d} "
                    f"Наименование: кандидат {hit_index} " + "состав работ " * 80
                ),
                doc_id=f"doc-{query_index}-{hit_index}",
                doc_name="smeta_norm_cards.v1",
                score=1.0 / hit_index,
                meta={"dataset_id": "smeta", "norm_key": f"fixture-{query_index}-{hit_index}",
                      "norm_code": f"ГЭСН{query_index:02d}-00-000-{hit_index:02d}",
                      "title": f"кандидат {hit_index}", "measure_unit": "m"},
            )
            for hit_index in range(1, 9)
        ]
        query_hits.append((f"работа {query_index}", hits))

    groups, chunks, omitted_refs = service.build_model_rag_evidence_groups(
        query_hits,
        max_chars=70_000,
        hits_per_query=4,
    )

    rendered = "\n\n".join(groups)
    assert len(groups) == 30
    assert len(chunks) == 120
    assert "[Поисковый запрос Q30] работа 30" in rendered
    assert '"Q30.H4"' in rendered
    assert "ГЭСН30-00-000-04" in rendered
    assert "ГЭСН30-00-000-05" not in rendered
    assert len(rendered) <= 70_000
    assert omitted_refs
    assert set(omitted_refs) == {c.meta["model_evidence_ref"] for c in chunks
                                if c.meta["body_status"] == "deferred_capacity"}
    assert all(c.content == query_hits[c.meta["model_query_index"] - 1][1][c.meta["model_hit_index"] - 1].content
               for c in chunks if c.meta["body_status"] == "full")


def _query_hits_with_long_headers(query_count: int, *, title: str):
    hits = [
        SimpleNamespace(
            content="Шифр: ГЭСН01-01-001-01 " + "состав " * 40,
            doc_id="doc-1",
            doc_name="smeta_norm_cards.v1",
            score=0.9,
            meta={"dataset_id": "smeta"},
        )
        for _ in range(6)
    ]
    return [(title, hits) for _ in range(query_count)]


def test_model_rag_query_cursor_and_actual_index_are_budgeted_separately():
    query_hits = _query_hits_with_long_headers(
        20,
        title="Hyperline TTR-4281-DD-RAL7035 шкаф напольный 19-дюймовый 42U разобранный",
    )
    header_tax = service.model_rag_evidence_header_chars(
        query_hits[:3],
        hits_per_query=6,
    )
    included, leftover, trim_omitted = service.select_model_rag_query_hits_for_budget(
        query_hits,
        max_chars=header_tax,
        hits_per_query=6,
    )

    assert trim_omitted == []
    assert len(included) == 3
    assert len(leftover) == 17
    assert leftover[0][0] == query_hits[3][0]

    groups, chunks, omitted_refs = service.build_model_rag_evidence_groups(
        query_hits,
        max_chars=header_tax,
        hits_per_query=6,
    )

    assert 0 < len(groups) <= 3
    assert "[Поисковый запрос Q1]" in groups[0]
    assert "[Поисковый запрос Q4]" not in "\n\n".join(groups)
    assert "Q4.H1" in omitted_refs
    assert len("\n\n".join(groups)) <= header_tax
    assert len(chunks) < 18  # the identity index also has an explicit cost

    prefix_groups, _prefix_chunks, prefix_omitted = service.build_model_rag_evidence_groups(
        included,
        max_chars=header_tax,
        hits_per_query=6,
    )
    assert len(prefix_groups) <= 3
    assert len("\n\n".join(prefix_groups)) <= header_tax
    assert all(not ref.startswith("Q4") for ref in prefix_omitted)


def test_model_rag_evidence_explicitly_defers_an_identity_that_cannot_fit():
    query_hits = _query_hits_with_long_headers(
        2,
        title="кабель витая пара категория 6a экран F/UTP",
    )
    one_query_tax = service.model_rag_evidence_header_chars(
        query_hits[:1],
        hits_per_query=6,
    )
    groups, chunks, omitted_refs = service.build_model_rag_evidence_groups(
        query_hits,
        max_chars=max(1, one_query_tax // 4),
        hits_per_query=6,
    )

    assert groups == [] and chunks == []
    assert omitted_refs == [f"Q{q}.H{h}" for q in (1, 2) for h in range(1, 7)]


def test_model_rag_evidence_empty_budget_omits_queries_without_raising():
    query_hits = _query_hits_with_long_headers(4, title="шкаф 42U")
    groups, chunks, omitted_refs = service.build_model_rag_evidence_groups(
        query_hits,
        max_chars=0,
        hits_per_query=6,
    )

    assert groups == []
    assert chunks == []
    assert omitted_refs[0] == "Q1.H1"
    assert "Q4.H6" in omitted_refs


def test_model_rag_group_char_budget_matches_governor_two_chars_per_token():
    assert service.model_rag_group_char_budget(
        context_chars_limit=120000,
        remaining_group_tokens=2000,
    ) == 4000
    assert service.model_rag_group_char_budget(
        context_chars_limit=1000,
        remaining_group_tokens=2000,
    ) == 1000
    assert service.model_rag_group_char_budget(
        context_chars_limit=120000,
        remaining_group_tokens=0,
    ) == 0


def test_model_rag_source_map_preserves_typed_locator_and_evidence_handle():
    chunk = service._ModelRagEvidenceChunk(
        content="Шифр и состав работы",
        doc_id="",
        doc_name="smeta_norm_cards.v1",
        score=0.75,
        meta={
            "dataset_id": "smeta-dataset",
            "norm_code": "ГЭСН01-01-001-01",
            "source_ref": "fsnb#norm=ГЭСН01-01-001-01",
            "model_evidence_ref": "Q3.H2",
        },
    )

    source_map = service._model_rag_source_map([chunk])

    assert source_map[0]["evidence_ref"] == "Q3.H2"
    assert source_map[0]["source_ref"] == "fsnb#norm=ГЭСН01-01-001-01"
    assert source_map[0]["locator"]["kind"] == "norm_card"
    assert source_map[0]["locator"]["card_code"] == "ГЭСН01-01-001-01"


def test_model_rag_result_preserves_all_rows_and_domain_fields_unchanged():
    rows = [
        {
            "source_row": index,
            "title": f"Работа {index}",
            "unit": "шт.",
            "quantity": index,
            "norm_code": f"ГЭСНм00-00-000-{index:02d}",
        }
        for index in range(1, 31)
    ]

    answer = "\n".join(
        [
            "Готово",
            "",
            "| source_row | section | title | unit | quantity | norm_code | analogue | coverage | coefficient | evidence_refs |",
            "|---:|---|---|---|---:|---|---|---|---:|---|",
            *[
                f"| {index} | | Работа {index} | шт. | {index} | "
                f"ГЭСНм00-00-000-{index:02d} | | | | Источник {index} |"
                for index in range(1, 31)
            ],
        ]
    )

    assert service.parse_model_rag_result(answer) == (answer, rows)


def test_model_rag_result_decoder_has_no_regex_or_language_router():
    source = inspect.getsource(service.parse_model_rag_result)

    assert "re." not in source
    assert "question" not in source
    assert "row_schema" not in source


def test_vor_notice_does_not_require_norms_or_prices():
    notice = service.format_lsr_packaged_notice(
        filename="ВОР.xlsx", artifact_kind="vor_workbook",
        pricing_status="norm_selection_required", norms_status="model_norms_partial",
        readiness={"schema":"les.vor-result-readiness.v1", "open_questions":[]},
    )
    assert notice == "ВОР сформирован. Файл: ВОР.xlsx."
    assert "ЛСР" not in notice


def test_vor_readiness_keeps_model_open_questions_separate_from_delivery():
    rows = [{"source_row": "PDF!R25", "row_role": "unresolved", "title": "Коробка",
             "unit": "шт", "quantity": 8, "open_gap": "Нужно уточнение назначения"}]
    ready = service.build_vor_result_readiness(
        rows=rows, has_file=True, remaining_locators=[], catalog_work_count=1,
        model_errors=[],
    )
    assert ready["technical_complete"] is True
    assert ready["vor_complete"] is False
    assert ready["open_questions"] == ["Коробка: Нужно уточнение назначения"]
    assert rows[0]["row_role"] == "unresolved" and rows[0]["quantity"] == 8
    notice = service.format_lsr_packaged_notice(filename="ВОР.xlsx", artifact_kind="vor_workbook", readiness=ready)
    assert "Открытые вопросы" in notice


def test_vor_readiness_does_not_require_norms_for_complete_work_volumes():
    ready = service.build_vor_result_readiness(
        rows=[{"source_row": "Лист!R7", "row_role": "work", "title": "Установка", "unit": "шт", "quantity": 2}],
        has_file=True, remaining_locators=[], catalog_work_count=1, model_errors=[],
    )
    assert ready["vor_complete"] is True and ready["open_questions"] == []


def test_vor_readiness_preserves_structural_errors_and_unreached_rows():
    ready = service.build_vor_result_readiness(
        rows=[], has_file=True, remaining_locators=["Другой!R3"], catalog_work_count=1,
        model_errors=["source_missing:Другой!R3", "norm_code_not_found:X"],
    )
    assert ready["technical_complete"] is False and ready["vor_complete"] is False
    assert ready["open_questions"] == ["source_missing:Другой!R3"]


def test_model_runtime_facts_show_the_real_date_and_inventory_without_selecting_prices(monkeypatch):
    from datetime import datetime, timezone
    from proxy.services import fgis_price_service
    monkeypatch.setattr(fgis_price_service, "available_pricebooks", lambda: [
        "C:/private/Книги/sankt-peterburg_3kv2026.parquet",
        "C:/private/Книги/Москва 'квартал'.parquet",
    ])
    facts = service.model_runtime_facts(
        {"mode": "estimator"}, observed_at=datetime(2026, 9, 30, 19, 0, tzinfo=timezone.utc),
    )
    assert facts["utc_date"] == "2026-09-30"
    assert facts["installed_pricebook_files"] == ["sankt-peterburg_3kv2026", "Москва 'квартал'"]
    assert not any(key in facts for key in ("selected_book", "price", "norm_code", "applicability"))
    assert "private" not in json.dumps(facts)
    prompt = service.profile_system_prompt({"mode": "estimator", "prompt_text": "Estimate"}, strict=False)
    assert "sankt-peterburg_3kv2026" in prompt and '"utc_date"' in prompt


def test_non_estimator_runtime_facts_do_not_read_pricebooks(monkeypatch):
    from proxy.services import fgis_price_service
    monkeypatch.setattr(fgis_price_service, "available_pricebooks", lambda: pytest.fail("non-estimator must not read books"))
    facts = service.model_runtime_facts({"mode": "search"})
    assert "utc_date" in facts and "installed_pricebook_files" not in facts


def test_empty_pricebook_inventory_is_exposed_without_inventing_a_default(monkeypatch):
    from proxy.services import fgis_price_service
    monkeypatch.setattr(fgis_price_service, "available_pricebooks", lambda: [])
    facts = service.model_runtime_facts({"mode": "estimator"})
    assert facts["installed_pricebook_files"] == []
    assert facts["installed_pricebook_file_count"] == 0 and facts["pricebook_inventory_complete"] is True


def test_large_pricebook_inventory_is_bounded_and_explicitly_partial(monkeypatch):
    from proxy.services import fgis_price_service
    books = [f"C:/catalog/region_{index:04}_price_period_2026.parquet" for index in range(1000)]
    monkeypatch.setattr(fgis_price_service, "available_pricebooks", lambda: books)
    facts = service.model_runtime_facts({"mode": "estimator"})
    assert len(json.dumps(facts["installed_pricebook_files"], ensure_ascii=False)) <= 2048
    assert facts["installed_pricebook_file_count"] == 1000
    assert facts["pricebook_inventory_complete"] is False
    assert set(facts["installed_pricebook_files"]) <= {Path(path).stem for path in books}


def test_model_inline_assignments_keep_explicit_decisions_and_decimal_comma():
    answer = "ВК!R41: source_row=ВК!R41, row_role=work, work_row=ВК!R41, title=Монтаж изделия, исполнение A, unit=шт, quantity=2,5, norm_code=CUSTOM-41, norm_status=ANALOGUE_CANDIDATE, open_gap=Нужна проверка комплектации, evidence_refs=Q2.H3"
    parsed = service.parse_model_rag_result(answer)
    assert parsed is not None
    assert parsed[0] == answer
    assert parsed[1] == [{
        "source_row": "ВК!R41", "row_role": "work", "work_row": "ВК!R41",
        "title": "Монтаж изделия, исполнение A", "unit": "шт", "quantity": 2.5,
        "norm_code": "CUSTOM-41", "norm_status": "ANALOGUE_CANDIDATE",
        "open_gap": "Нужна проверка комплектации", "evidence_refs": ["Q2.H3"],
    }]


def test_final_binding_keeps_original_card_across_packet_local_alias_collisions():
    def chunk(code, identity):
        return SimpleNamespace(content=f"Шифр: {code}", doc_name="cards", meta={
            "model_evidence_ref": "Q1.H1", "global_evidence_id": identity,
            "model_query_text": identity,
        })
    first = chunk("ГЭСН01-01-001-01", "first")
    second = chunk("ГЭСН01-01-001-02", "second")
    authored = {"source_row": "АР!R7", "norm_code": "ГЭСН01-01-001-02", "evidence_refs": ["Q1.H1"]}
    saved = service.bind_row_evidence_ids([authored], [second])[0]
    final = service.bind_row_evidence_ids([saved], [first, second])[0]
    assert final["norm_code"] == authored["norm_code"]
    assert final["evidence_bindings"] == {"Q1.H1": "second"}
    assert final["_evidence_check"]["cited_ciphers"] == ["ГЭСН01-01-001-02"]
    assert final["_evidence_check"]["code_not_in_refs"] is False
    unbound = service.bind_row_evidence_ids([authored], [first, second])[0]
    assert unbound["evidence_bindings"] == {}
    assert unbound["_evidence_check"]["unresolved_refs"] == ["Q1.H1"]
    missing = service.bind_row_evidence_ids([saved], [first])[0]
    assert missing["evidence_bindings"] == {"Q1.H1": "second"}
    assert missing["_evidence_check"]["unresolved_refs"] == ["Q1.H1"]


def test_review_cited_card_remains_bindable_beside_new_packet_cards():
    old = SimpleNamespace(content="Шифр: ГЭСН01-01-001-01", doc_name="cards", meta={
        "model_evidence_ref": "Q18.H2", "global_evidence_id": "old-card"})
    hit = SimpleNamespace(content="Шифр: ГЭСН01-01-001-02", doc_id="new-card",
                          doc_name="cards", score=1, meta={})
    offset = service.model_rag_next_query_offset([old])
    groups, chunks, _ = service.build_model_rag_evidence_groups(
        [("unaltered model query", [hit])], max_chars=10000, hits_per_query=1,
        query_offset=offset, evidence_namespace="new-packet")
    assert "Q19.H1" in groups[0]
    # The model preserves the old citation in a new visible answer without
    # repeating the application's evidence_bindings dictionary.
    authored = {"source_row": "Any!R6", "norm_code": "ГЭСН01-01-001-01",
                "evidence_refs": ["Q18.H2"]}
    bound = service.bind_row_evidence_ids([authored], [old, *chunks])[0]
    assert bound["evidence_bindings"] == {"Q18.H2": "old-card"}
    assert bound["_evidence_check"]["citation_checkable"] is True
    assert bound["_evidence_check"]["code_not_in_refs"] is False
    assert hit.content == "Шифр: ГЭСН01-01-001-02"


def test_query_cursor_survives_durable_evidence_roundtrip_without_renaming_old_refs():
    chunk = service._ModelRagEvidenceChunk(content="full card", doc_id="a", doc_name="cards", score=1,
        meta={"model_evidence_ref": "Q104.H6", "global_evidence_id": "durable"})
    restored = service.evidence_chunk_from_record(service.durable_evidence_record(chunk))
    assert service.model_rag_next_query_offset([restored]) == 104
    assert service.model_rag_next_query_offset([]) == 0
    assert restored.meta["model_evidence_ref"] == "Q104.H6"


@pytest.mark.parametrize("answer", [
    "ВК!R42: source_row=ВК!R41, title=Работа, unit=шт, norm_code=X",
    "source_row=ВК!R41, title=A, unit=шт, norm_code=X, norm_code=Y",
    "Предлагаю source_row=ВК!R41, title=Работа, unit=шт, norm_code=X",
    "source_row=ВК!R41, title=Работа, norm_code=X",
])
def test_ambiguous_or_prose_inline_result_is_not_a_decision(answer):
    assert service.parse_model_rag_result(answer) is None


def test_chat_application_does_not_replace_the_configured_model_for_memory_pressure():
    source = inspect.getsource(service._execute_chat_evidence_application)

    assert "memory_aware_provider" not in source


def test_model_rag_result_preserves_explicit_row_identity_and_norm_code_verbatim():
    answer = """| source_row | title | unit | quantity | norm_code | evidence_refs |
|---:|---|---|---:|---|---|
| 42 | Работа модели | шт. | 3 | ГЭСН:26-01-055-01 (выбор Qwen) | Q2.H4 |
| 7 | Другая работа | м | 8 | CUSTOM-NORM-A | Q1.H2 |
"""

    parsed = service.parse_model_rag_result(answer)

    assert parsed is not None
    assert parsed[0] == answer
    assert parsed[1] == [
        {
            "source_row": 42,
            "title": "Работа модели",
            "unit": "шт.",
            "quantity": 3,
            "norm_code": "ГЭСН:26-01-055-01 (выбор Qwen)",
            "evidence_refs": ["Q2.H4"],
        },
        {
            "source_row": 7,
            "title": "Другая работа",
            "unit": "м",
            "quantity": 8,
            "norm_code": "CUSTOM-NORM-A",
            "evidence_refs": ["Q1.H2"],
        },
    ]


def test_model_rag_packaging_requires_complete_rows_and_real_matching_evidence():
    evidence = [
        SimpleNamespace(
            meta={"model_evidence_ref": "Q1.H2", "norm_code": "ГЭСН26-01-055-01"}
        ),
        SimpleNamespace(
            meta={"model_evidence_ref": "Q2.H4", "norm_code": "ГЭСНм08-02-146-01"}
        ),
    ]
    rows = [
        {"source_row": 1, "norm_code": "ГЭСН:26-01-055-01", "evidence_refs": ["Q1.H2"]},
        {"source_row": 2, "norm_code": "ГЭСНм08-02-146-01", "evidence_refs": ["Q2.H4"]},
    ]

    assert service.validate_model_rag_result_structure(
        rows,
        evidence,
        expected_source_rows=2,
    ) == []

    errors = service.validate_model_rag_result_structure(
        [
            {"source_row": 1, "norm_code": "ГЭСН26-01-055-99", "evidence_refs": ["Q1.H2"]},
            {"source_row": 1, "norm_code": "ГЭСН26-01-055-99", "evidence_refs": ["Q1.H2"]},
            {"source_row": 1, "norm_code": "ГЭСНм08-02-146-01", "evidence_refs": ["Q9.H9"]},
        ],
        evidence,
        expected_source_rows=2,
    )

    # Duplicate means the fully identical decision was authored twice;
    # distinct content on one locator is the legal two-operations pattern (1.1).
    assert "duplicate_source_row:1" in errors
    assert "missing_source_row:2" not in errors
    assert "unknown_evidence_ref:Q9.H9" in errors
    assert "norm_code_not_in_referenced_evidence:1" in errors


def test_material_and_work_same_locator_are_not_duplicate_decisions():
    evidence = [
        SimpleNamespace(
            meta={"model_evidence_ref": "Q1.H1", "norm_code": "ГЭСНм10-06-001-01"}
        ),
    ]
    rows = [
        {
            "source_row": "СКС!R28",
            "row_role": "material",
            "work_row": "СКС!R28",
            "title": "Кабель",
            "unit": "м",
            "quantity": 400,
            "norm_code": "-",
            "evidence_refs": ["Q1.H1"],
        },
        {
            "source_row": "СКС!R28",
            "row_role": "work",
            "work_row": "СКС!R28",
            "title": "Прокладка кабеля",
            "unit": "м",
            "quantity": 400,
            "norm_code": "ГЭСНм10-06-001-01",
            "evidence_refs": ["Q1.H1"],
        },
    ]
    errors = service.validate_model_rag_result_structure(
        rows,
        evidence,
        expected_source_rows=1,
    )
    assert "duplicate_source_row:СКС!R28" not in errors
    assert service.model_rag_row_kind(rows[0]) == "material"
    assert service.model_rag_row_kind(rows[1]) == "work"

    catalog = SimpleNamespace(
        lookup=lambda key: SimpleNamespace(sheet="СКС")
        if str(key).startswith("СКС!")
        else None
    )
    kept = service.sheet_pass_keep_rows(
        rows, sheet="СКС", catalog=catalog, errors=errors
    )
    assert len(kept) == 2
    assert {row["row_role"] for row in kept} == {"material", "work"}

    merged = service.merge_model_rag_rows([], rows)
    assert len(merged) == 2
    # Redelivery of an identical packet never creates new operations.
    again = service.merge_model_rag_rows(merged, [dict(rows[0]), dict(rows[1])])
    assert len(again) == 2
    assert again[0]["title"] == "Кабель"
    # A distinct material decision on the same locator is a second operation,
    # not something "first-wins per role" may drop (defect 1.1).
    amended = service.merge_model_rag_rows(
        merged,
        [{**rows[0], "title": "другой материал"}],
    )
    assert len(amended) == 3
    # A known operation_id marks the same operation: redelivering it with
    # revised content never adds another card (revision is the job service).
    existing = service.merge_model_rag_rows(
        [],
        [{**rows[0], "operation_id": "op_mat_1"}],
    )
    refined = service.merge_model_rag_rows(
        existing,
        [{**rows[0], "operation_id": "op_mat_1", "title": "уточнённый кабель"}],
    )
    assert len(refined) == 1
    assert refined[0]["title"] == "Кабель"


def test_markdown_title_with_pipe_still_parses_row():
    answer = (
        "| source_row | row_role | title | unit | quantity | norm_code | evidence_refs |\n"
        "|---|---|---|---|---|---|---|\n"
        "| СКС!R6 | material | Шкаф 19\" \\| 800x1000 \\| Hyperline | шт. | 2 | - | Q1.H1 |\n"
        "| СКС!R6 | work | Монтаж шкафа | шт. | 2 | ГЭСНм10-01-055-01 | Q1.H1 |\n"
    )
    parsed = service.parse_model_rag_result(answer)
    assert parsed is not None
    _md, rows = parsed
    assert len(rows) >= 2
    roles = {str(row.get("row_role")) for row in rows}
    assert "material" in roles and "work" in roles
    material = next(row for row in rows if row.get("row_role") == "material")
    assert material["title"] == 'Шкаф 19" | 800x1000 | Hyperline'
    work = next(row for row in rows if row.get("row_role") == "work")
    assert work.get("norm_code") == "ГЭСНм10-01-055-01"


@pytest.mark.parametrize("separator_count", [1, 6, 7, 8])
def test_model_rag_table_separator_width_does_not_drop_decisions(separator_count):
    header = "| source_row | row_role | title | unit | quantity | norm_code | evidence_refs |\n"
    body = (
        "| Sheet!R6 | material | Cabinet | pcs | 2 | - | Q1.H1 |\n"
        "| Sheet!R6 | work | Install cabinet | pcs | 2 | CODE-01 | Q1.H1 |\n"
    )
    expected = service.parse_model_rag_result(header + "|" + "---|" * 7 + "\n" + body)
    actual = service.parse_model_rag_result(header + "|" + "---|" * separator_count + "\n" + body)
    assert actual is not None and expected is not None
    assert actual[1] == expected[1]
    assert len(actual[1]) == 2
    assert actual[1][1]["norm_code"] == "CODE-01"


def test_model_rag_result_does_not_infer_rows_from_prose():
    answer = """### Раздел 1. Демонтажные работы ЭОМ
**Строка 1: Защитное укрытие пленкой, 116 м².**
* **Выбранный аналог:** `ГЭСН26-01-055-01` (Установка пароизоляционного слоя из пленки).
* **Обоснование:** Ближайший по составу работ аналог [Q1.H2].

### Раздел 2. Монтажные работы ЭОМ
**Строка 1: Монтаж блока аварийного питания, 16 шт.**
* **Выбранный аналог:** `ГЭСНм34-01-071-01` (Светильник с аварийным питанием).
* **Обоснование:** Аналог по сложности монтажа Q7.H1; Q7.H3.
"""

    assert service.parse_model_rag_result(answer) is None


def test_model_rag_result_reads_tables_whose_divider_uses_short_dashes():
    """One alignment dash is markdown, not an ambiguous answer (task § 1, § 3).

    Build 8007b38a raised the divider minimum to three dashes, and the installed
    store then held two real model answers in the ``|:--|`` style whose whole
    decision table the reader threw away: chat row 53 (38 rows, ВОР!R4…ВОР!R41)
    and, in a different shape, chat row 330.  Blocker § 1 is explicit that an
    unread answer is a technical defect and must not be reported as "no norm",
    and § 3 requires the reader to keep the fields the model did present.  The
    unambiguous part of a table is the header mapping plus a divider that marks a
    separator in every column — the dash count is presentation.
    """

    answer = """**Инженерный вердикт:** цены не найдены, строки всё равно ниже.

| № | source_row | section | title | unit | quantity | norm_code | analogue | coverage | coefficient | evidence_refs |
|:--|:-----------|:--------|:------|:-----|:---------|:----------|:---------|:----------|:------------|:--------------|
| 1 | ВОР!R4 | Раздел 1 | Светильник | шт | 25 | ГЭСНм08-03-609-02 | прямое | полное | 1 | Q1.H2 |
| 2 | ВОР!R5 | Раздел 1 | Бра | шт | 4 |  | аналог | частичное | 1 | Q2.H1 |
"""

    parsed = service.parse_model_rag_result(answer)

    assert parsed is not None
    visible, rows = parsed
    assert visible == answer
    assert [row["source_row"] for row in rows] == ["ВОР!R4", "ВОР!R5"]
    assert rows[0]["norm_code"] == "ГЭСНм08-03-609-02"
    assert rows[0]["evidence_refs"] == ["Q1.H2"]
    # An empty cell stays empty: the reader does not fill a decision in.
    assert "norm_code" not in rows[1]


def test_model_rag_result_reads_a_table_marked_by_the_models_own_citation():
    """A [Источник N] mark glued to a table line is presentation, not a lost row.

    The prompt itself orders the model to cite with ``[Источник N]`` numbers, and
    the installed 35B sometimes writes that mark in front of the table it opens
    with.  Chat row 506 is exactly that answer: the header line began with
    ``[Источник 1] |``, so the reader returned None and the two decisions the
    model made for АР!R49 and АР!R64 never reached the document.  Reading the
    table must not touch the authored answer or a single cell value, and a bracket
    that is not a citation stays inside its cell.
    """

    answer = (
        "[Источник 1] | source_row | row_role | work_row | title | unit | quantity "
        "| norm_code | norm_status | open_gap | evidence_refs |\n"
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
        "| АР!R49 | work | АР!R49 | Кабель-канал 40x40 мм | м | 24 "
        "| ГЭСН15-04-007-08 | ANALOGUE_CANDIDATE | [Q4.H1] аналог по составу | Q4.H1 |\n"
        "| АР!R64 | work | АР!R64 | Розетка двойная | шт | 6 "
        "| ГЭСН34-01-016-02 | ANALOGUE_CANDIDATE | Совпадает единица | Q5.H1 |\n"
    )

    parsed = service.parse_model_rag_result(answer)

    assert parsed is not None
    visible, rows = parsed
    assert visible == answer
    assert [row["source_row"] for row in rows] == ["АР!R49", "АР!R64"]
    assert [row["norm_code"] for row in rows] == ["ГЭСН15-04-007-08", "ГЭСН34-01-016-02"]
    assert [row["norm_status"] for row in rows] == ["ANALOGUE_CANDIDATE", "ANALOGUE_CANDIDATE"]
    assert [row["evidence_refs"] for row in rows] == [["Q4.H1"], ["Q5.H1"]]
    # The citation mark only opened the line; a bracket inside a cell is kept as
    # the model wrote it, so no model content disappears with the prefix.
    assert rows[0]["open_gap"].startswith("[Q4.H1]")


def test_model_rag_result_reads_tables_written_without_outer_pipes():
    """The outer pipes are optional in markdown (chat row 330).

    That answer opened most of its per-section tables as
    ``source_row | row_role | …`` with a ``--- | --- | …`` rule under it, and the
    reader stopped at the first line without a leading pipe, so every section below
    the first table was never read.  A prose line that merely contains a pipe is
    still not a row: a line narrower than the table and not opened as one ends the
    table instead of being padded into a decision.
    """

    answer = (
        "| source_row | title | unit | norm_code |\n"
        "|---|---|---|---|\n"
        "| АР!R23 | Штукатурка существующих колонн | м2 | ГЭСН15-02-026-03 |\n"
        "\n"
        "ПТ!R9: Автоматическое пожаротушение и внутренний противопожарный водопровод\n"
        "source_row | row_role | work_row | title | unit | quantity | norm_code "
        "| norm_status | open_gap | evidence_refs\n"
        "--- | --- | --- | --- | --- | --- | --- | --- | --- | ---\n"
        "ПТ!R9 | header | ПТ!R9 | Автоматическое пожаротушение |  |  |  |  "
        "| Раздел, не требует монтажной нормы | \n"
        "ПТ!R10: эта строка — пояснение, а не позиция таблицы\n"
    )

    parsed = service.parse_model_rag_result(answer)

    assert parsed is not None
    _visible, rows = parsed
    assert [row["source_row"] for row in rows] == ["АР!R23", "ПТ!R9"]
    assert rows[1]["row_role"] == "header"
    assert rows[1]["open_gap"] == "Раздел, не требует монтажной нормы"


def test_model_rag_result_keeps_a_non_citation_bracket_as_a_cell():
    """Only the citation mark is stripped, never a value the model put in brackets."""

    assert citation_mark_length("[Q4.H1] | source_row | title |") == 0
    assert citation_mark_length("[Источник 12] | source_row | title |") == len(
        "[Источник 12]"
    )
    # A handle that opens a line is a cell, so the row carries one column more than
    # the header and the reader reports ambiguity instead of relabelling the model's
    # own text.
    answer = (
        "| source_row | title | unit | norm_code |\n"
        "|---|---|---|---|\n"
        "| [Q4.H1] | Кабель | м | ГЭСН15-04-007-08 |\n"
    )
    parsed = service.parse_model_rag_result(answer)
    assert parsed is not None
    assert parsed[1][0]["source_row"] == "[Q4.H1]"



def test_model_rag_result_rejects_noncontract_norm_header():
    answer = """### Раздел 1. Осветительная аппаратура
| № | Наименование работ (из ВОР) | Ед. изм. | Кол-во | Норматив монтажа (norm_code) | Аналог/Примечание | Coverage (покрытие) | Evidence_refs |
|---|---|---|---|---|---|---|---|
| 1 | Светильник светодиодный | шт. | 25 | ГЭСНм08-03-609-02 | Прямое соответствие | Частичное | Q1.H2 |
"""

    parsed = service.parse_model_rag_result(answer)

    assert parsed is None


def test_model_rag_result_does_not_treat_vor_spec_as_lsr_decisions():
    answer = """
### 1. Осветительная аппаратура

| Наименование и техническая характеристика | Ед. изм. | Количество (подтверждено) | Источник данных | Статус |
| :--- | :---: | :---: | :---: | :---: |
| Светильник светодиодный накладной, IP65, 30 Вт | шт. | 25 | Спецификация, поз. 1.1 | Подтверждено |
"""
    parsed = service.parse_model_rag_result(answer)
    assert parsed is None


def test_model_rag_result_does_not_treat_source_note_table_as_lsr_decisions():
    answer = """
### 1. Осветительная аппаратура

| Наименование и техническая характеристика | Ед. изм. | Кол-во (из источника) | Источник данных | Примечание |
| :--- | :---: | :---: | :---: | :--- |
| Светильник светодиодный накладной, IP65, 30 Вт | шт. | 25 | [Источник 1] | Позиция 1.1 |
"""
    parsed = service.parse_model_rag_result(answer)
    assert parsed is None


def test_model_rag_result_reads_explicit_multiline_labelled_blocks():
    answer = """**Строка 1**
* **source_row**: 1
* **section**: Демонтаж
* **title**: Демонтаж керамической плитки со стен
* **unit**: м2
* **quantity**: 24
* **norm_code**: ГЭСНр63-03-001-05
* **analogue**: Нет
* **coverage**: Полное соответствие
* **coefficient**: 1.0
* **evidence_refs**: Q6.H4, Q13.H5

**Строка 2**
- **source_row**: 2
- **title**: Окраска стен
- **unit**: м2
- **quantity**: 60
- **norm_code**: ГЭСН15-04-007-05
- **coverage**: Полное соответствие
- **evidence_refs**: Q3.H2; Q8.H5
"""

    assert service.parse_model_rag_result(answer) == (
        answer,
        [
            {
                "source_row": 1,
                "section": "Демонтаж",
                "title": "Демонтаж керамической плитки со стен",
                "unit": "м2",
                "quantity": 24,
                "norm_code": "ГЭСНр63-03-001-05",
                "analogue": "Нет",
                "coverage": "Полное соответствие",
                "coefficient": 1,
                "evidence_refs": ["Q6.H4", "Q13.H5"],
            },
            {
                "source_row": 2,
                "title": "Окраска стен",
                "unit": "м2",
                "quantity": 60,
                "norm_code": "ГЭСН15-04-007-05",
                "coverage": "Полное соответствие",
                "evidence_refs": ["Q3.H2", "Q8.H5"],
            },
        ],
    )


def test_model_rag_result_reads_titled_blocks_and_keeps_explicit_missing_quantity():
    """Regression: a natural model heading must not hide its explicit row fields."""

    answer = """### Строка 984: Шкаф Hyperline (2 шт.)
* **source_row:** 984
* **section:** Оборудование
* **title:** Шкаф напольный 19-дюймовый
* **unit:** шт.
* **quantity:** 2
* **norm_code:** ГЭСНм10-01-055-01 (выбор Qwen)
* **analogue:** Шкаф металлический
* **coverage:** Монтаж шкафа
* **evidence_refs:** Q1.H3, Q4.H2

### Строка 1024: Кабельнесущая продукция
* **source_row:** 1024
* **section:** Подзаголовок
* **title:** Кабельнесущая продукция
* **unit:** —
* **quantity:** —
* **norm_code:** —
* **analogue:** —
* **coverage:** Группировка материалов
* **evidence_refs:** Q3.H1
"""

    assert service.parse_model_rag_result(answer) == (
        answer,
        [
            {
                "source_row": 984,
                "section": "Оборудование",
                "title": "Шкаф напольный 19-дюймовый",
                "unit": "шт.",
                "quantity": 2,
                "norm_code": "ГЭСНм10-01-055-01 (выбор Qwen)",
                "analogue": "Шкаф металлический",
                "coverage": "Монтаж шкафа",
                "evidence_refs": ["Q1.H3", "Q4.H2"],
            },
            {
                "source_row": 1024,
                "section": "Подзаголовок",
                "title": "Кабельнесущая продукция",
                "unit": "—",
                "norm_code": "—",
                "analogue": "—",
                "coverage": "Группировка материалов",
                "evidence_refs": ["Q3.H1"],
            },
        ],
    )


def test_model_rag_result_reads_source_row_explicit_in_block_heading():
    answer = """### Строка 1 (source_row=1)
* **section:** Демонтаж
* **title:** Разборка облицовки стен
* **unit:** м2
* **quantity:** 24
* **norm_code:** ГЭСНр63-03-001-05
* **coverage:** Полное покрытие
* **coefficient:** 1.0 (без дополнительных коэффициентов)
* **evidence_refs:** Q4.H1
"""

    parsed = service.parse_model_rag_result(answer)

    assert parsed is not None
    assert parsed[0] == answer
    assert parsed[1] == [{
        "source_row": 1,
        "section": "Демонтаж",
        "title": "Разборка облицовки стен",
        "unit": "м2",
        "quantity": 24,
        "norm_code": "ГЭСНр63-03-001-05",
        "coverage": "Полное покрытие",
        "coefficient": 1,
        "evidence_refs": ["Q4.H1"],
    }]


def test_model_rag_result_reads_explicit_labelled_lines_without_semantic_repair():
    answer = """Строка 1 — Прокладка контрольного кабеля; раздел: Монтаж; ед. изм.: м; количество: 120; norm_code: ГЭСНм08-02-146-01; аналог: Кабель контрольный; обоснование: прямое соответствие составу; коэффициент: 1; evidence: Q1.H2.
Строка 2 — Монтаж шкафа управления; раздел: Автоматика; ед. изм.: шт.; количество: 2; norm_code: ГЭСНм11-03-001-01; аналог: Шкаф управления; обоснование: совпадают измеритель и операции; evidence_refs: Q2.H1, Q2.H3."""

    assert service.parse_model_rag_result(answer) == (
        answer,
        [
            {
                "source_row": 1,
                "title": "Прокладка контрольного кабеля",
                "section": "Монтаж",
                "unit": "м",
                "quantity": 120,
                "norm_code": "ГЭСНм08-02-146-01",
                "analogue": "Кабель контрольный",
                "coverage": "прямое соответствие составу",
                "coefficient": 1,
                "evidence_refs": ["Q1.H2"],
            },
            {
                "source_row": 2,
                "title": "Монтаж шкафа управления",
                "section": "Автоматика",
                "unit": "шт.",
                "quantity": 2,
                "norm_code": "ГЭСНм11-03-001-01",
                "analogue": "Шкаф управления",
                "coverage": "совпадают измеритель и операции",
                "evidence_refs": ["Q2.H1", "Q2.H3"],
            },
        ],
    )


def test_model_rag_queries_ignore_only_plain_text_presentation_wrappers():
    raw = (
        "Вот список поисковых запросов.\n"
        "```text\n"
        '"демонтаж кабеля в гофре"\n'
        '"монтаж аварийного светильника"\n'
        "```"
    )

    assert service.parse_model_rag_queries(raw) == [
        "демонтаж кабеля в гофре",
        "монтаж аварийного светильника",
    ]


def test_model_rag_queries_liberally_unwrap_model_written_search_call_lines():
    raw = (
        "Сейчас сформирую запросы.\n"
        'search_sources "демонтаж штукатурки со стен"\n'
        'search_sources("монтаж воздуховодов круглого сечения")\n'
        "Это все запросы."
    )

    assert service.parse_model_rag_queries(raw) == [
        "демонтаж штукатурки со стен",
        "монтаж воздуховодов круглого сечения",
    ]


def test_model_rag_result_reads_an_ordinary_russian_table_with_combined_norm_cell():
    answer = """| № п/п | Наименование работ (из ВОР) | Ед. изм. | Кол-во | Нормативная база (Шифр нормы) | Обоснование выбора и аналог | Примечания к составу работ |
|:---:|:---|:---:|:---:|:---|:---|:---|
| **Раздел 1. Демонтажные работы** | | | | | | |
| 1 | Защитное укрытие | м² | 116 | **ГЭСН26-01-055-01**<br>[Q3.H2] | Аналог: пароизоляционный слой | Материал отдельно |
| 2 | Разработка проема | шт. | 10 | *(Нет прямого аналога)*<br>Аналог: **ГЭСН15-02-035-03**<br>[Q6.H1] | Аналог по составу | Обратная операция |
"""

    diagnostics = []
    parsed = service.parse_model_rag_result(answer, diagnostics=diagnostics)

    assert parsed is not None
    assert parsed[0] == answer
    assert parsed[1] == []
    assert [item["display_ordinal"] for item in diagnostics] == ["1", "2"]
    assert all(item["code"] == "MODEL_RESULT_SOURCE_LOCATOR_MISSING" for item in diagnostics)
    assert [{k: v for k, v in item["decision"].items()
             if k not in {"raw_line", "raw_cells", "table_header"}} for item in diagnostics] == [
        {
            "section": "Раздел 1. Демонтажные работы",
            "title": "Защитное укрытие",
            "unit": "м²",
            "quantity": 116,
            "norm_code": "ГЭСН26-01-055-01<br>[Q3.H2]",
            "analogue": "Аналог: пароизоляционный слой",
            "coverage": "Материал отдельно",
            "evidence_refs": ["Q3.H2"],
        },
        {
            "section": "Раздел 1. Демонтажные работы",
            "title": "Разработка проема",
            "unit": "шт.",
            "quantity": 10,
            "norm_code": "*(Нет прямого аналога)*<br>Аналог: ГЭСН15-02-035-03<br>[Q6.H1]",
            "analogue": "Аналог по составу",
            "coverage": "Обратная операция",
            "evidence_refs": ["Q6.H1"],
        },
    ]


def test_model_rag_result_collects_every_ordinary_table_across_sections():
    answer = """### Раздел 1. Демонтаж
| № пп | Наименование работ | Ед. изм. | Кол-во | Нормативная база (Norm Code) | Обоснование выбора и аналог | Примечания к выбору |
|:---|:---|:---:|:---:|:---|:---|:---|
| 1 | Работа 1 | м² | 116 | **ГЭСН26-02-010-02** | Аналог 1 | **Evidence:** Q1.H3 |

### Раздел 2. Монтаж
| № пп | Наименование работ | Ед. изм. | Кол-во | Нормативная база (Norm Code) | Обоснование выбора и аналог | Примечания к выбору |
|:---|:---|:---:|:---:|:---|:---|:---|
| 1 | Работа 2 | шт. | 10 | **ГЭСН17-01-010-01** | Аналог 2 | **Evidence:** Q3.H3 |
| 2 | Работа 3 | м | 160 | **ГЭСНм08-02-146-02** | Аналог 3 | **Evidence:** Q9.H4 |
"""

    diagnostics = []
    parsed = service.parse_model_rag_result(answer, diagnostics=diagnostics)

    assert parsed is not None
    assert parsed[0] == answer
    assert parsed[1] == []
    assert [item["display_ordinal"] for item in diagnostics] == ["1", "1", "2"]
    assert all("source_row" not in item["decision"] for item in diagnostics)
    assert [item["decision"]["section"] for item in diagnostics] == [
        "Раздел 1. Демонтаж",
        "Раздел 2. Монтаж",
        "Раздел 2. Монтаж",
    ]
    assert [item["decision"]["norm_code"] for item in diagnostics] == [
        "ГЭСН26-02-010-02",
        "ГЭСН17-01-010-01",
        "ГЭСНм08-02-146-02",
    ]
    assert [item["decision"]["evidence_refs"] for item in diagnostics] == [
        ["Q1.H3"],
        ["Q3.H3"],
        ["Q9.H4"],
    ]


def test_model_rag_result_accepts_the_models_short_ordinary_column_names():
    answer = """### Раздел 1. Работы
| № пп | Наименование | Ед. изм. | Кол-во | Примечание | norm_code (Шифр) | Аналог/Обоснование | Coverage (Соответствие) | Coefficient (Кэф.) | Evidence_refs |
|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|
| 1 | Работа | м² | 116 | Текст модели | ГЭСН26-01-055-01 | Аналог модели | Частичное | 1.0 | [Q1.H2] |
"""

    diagnostics = []
    parsed = service.parse_model_rag_result(answer, diagnostics=diagnostics)

    assert parsed is not None
    assert parsed[1] == []
    assert [item["display_ordinal"] for item in diagnostics] == ["1"]
    assert [{k: v for k, v in item["decision"].items()
             if k not in {"raw_line", "raw_cells", "table_header"}} for item in diagnostics] == [
        {
            "section": "Раздел 1. Работы",
            "title": "Работа",
            "unit": "м²",
            "quantity": 116,
            "norm_code": "ГЭСН26-01-055-01",
            "analogue": "Аналог модели",
            "coverage": "Частичное",
            "coefficient": 1,
            "evidence_refs": ["Q1.H2"],
        }
    ]


def test_model_rag_result_accepts_maxim_explicit_headers_and_missing_numbers():
    answer = """| № | Наименование | Ед. изм. | Кол-во | Нормативный код (ГЭСН/ЕР) | Коэфф. | Примечание | Evidence_refs |
|---:|---|---|---:|---|---|---|---|
| 1 | Кабель модели | м | 12 | CUSTOM-NORM-A | — | Текст Qwen | Q3.H2 |
| 2 | Плёнка модели | м2 |  | CUSTOM-NORM-B | 1/100 | Нет прямого аналога | Q4.H1 |
"""

    diagnostics = []
    assert service.parse_model_rag_result(answer, diagnostics=diagnostics) == (answer, [])
    assert [item["display_ordinal"] for item in diagnostics] == ["1", "2"]
    assert [{k: v for k, v in item["decision"].items()
             if k not in {"raw_line", "raw_cells", "table_header"}} for item in diagnostics] == [
            {
                "title": "Кабель модели",
                "unit": "м",
                "quantity": 12,
                "norm_code": "CUSTOM-NORM-A",
                "coverage": "Текст Qwen",
                "evidence_refs": ["Q3.H2"],
            },
            {
                "title": "Плёнка модели",
                "unit": "м2",
                "norm_code": "CUSTOM-NORM-B",
                "coefficient": 0.01,
                "coverage": "Нет прямого аналога",
                "evidence_refs": ["Q4.H1"],
            },
        ]


@pytest.mark.parametrize("field", ["quantity", "calc_quantity", "conversion_factor", "confirmed_price"])
def test_model_rag_result_preserves_invalid_numeric_cell_without_losing_other_rows(field):
    header = ["source_row", "title", "unit", "norm_code", field]
    answer = "\n".join([
        "| " + " | ".join(header) + " |",
        "|---|---|---|---|---|",
        "| R1 | First work | m | NORM-1 | 2 |",
        "| R2 | Second work | m | NORM-2 | 305 m * 120 pcs |",
        "| R3 | Third work | m | NORM-3 | 4 |",
    ])
    visible, rows = service.parse_model_rag_result(answer)
    assert visible == answer
    assert [row["source_row"] for row in rows] == ["R1", "R2", "R3"]
    assert [row[field] for row in rows] == [2, "305 m * 120 pcs", 4]
    assert [row["norm_code"] for row in rows] == ["NORM-1", "NORM-2", "NORM-3"]


def test_model_rag_result_preserves_non_numeric_coefficient_text_unchanged():
    answer = """| source_row | title | unit | quantity | norm_code | coefficient | evidence_refs |
|---:|---|---|---:|---|---|---|
| 1 | Работа модели | м2 | 24 | ГЭСНр63-03-001-05 | 1/100 = 0.24 | Q4.H1 |
"""

    assert service.parse_model_rag_result(answer) == (
        answer,
        [{
            "source_row": 1,
            "title": "Работа модели",
            "unit": "м2",
            "quantity": 24,
            "norm_code": "ГЭСНр63-03-001-05",
            "coefficient": "1/100 = 0.24",
            "evidence_refs": ["Q4.H1"],
        }],
    )


def test_model_rag_result_rejects_missing_cells_without_padding():
    answer = """| № | Наименование | Ед. изм. | Кол-во | Нормативный код (ГЭСН/ЕР) | Коэфф. | Примечание |
|---:|---|---|---:|---|---|---|
| 7 | Работа модели | шт. | 3 | CUSTOM-NORM-A |
"""

    diagnostics = []
    assert service.parse_model_rag_result(answer, diagnostics=diagnostics) == (answer, [])
    assert diagnostics[0]["code"] == "MODEL_RESULT_TABLE_ROW_WIDTH_MISMATCH"
    assert diagnostics[0]["expected_cells"] == 7 and diagnostics[0]["actual_cells"] == 5
    assert diagnostics[0]["decision"]["raw_cells"] == [
        "7", "Работа модели", "шт.", "3", "CUSTOM-NORM-A",
    ]
    assert "norm_status" not in diagnostics[0]["decision"]


def test_estimator_draft_projection_never_invents_source_row_or_decision():
    rows = service.compact_estimator_draft_rows([
        {
            "source_row": 42,
            "title": "Кабель",
            "quantity": 12,
            "unit": "м",
            "norm_code": "CUSTOM-NORM-A",
            "analogue": "Аналог Qwen",
        },
        {
            "title": "Строка без идентичности",
            "norm_code": "CUSTOM-NORM-B",
        },
    ])

    assert rows == [{
        "work_id": "42",
        "source_row": 42,
        "section": "",
        "title": "Кабель",
        "quantity": 12,
        "unit": "м",
        "norm_code": "CUSTOM-NORM-A",
        "analogue": "Аналог Qwen",
    }]


def test_workbook_filename_projection_keeps_basename_and_drops_paths():
    assert service._safe_workbook_filename("LSR_source_2026-09-01_2147.xlsx") == (
        "LSR_source_2026-09-01_2147.xlsx"
    )
    assert service._safe_workbook_filename("C:/private/workbook.xlsx") == ""
    assert service._safe_workbook_filename("artifact.xlsx") == ""


async def _async_append(target, value):
    target.append(value)


async def _fake_workbook_execution(call, context, progress, _events):
    assert call["tool"] in {"build_lsr_workbook", "build_vor_workbook"}
    assert context["attachment_id"] == "read_123456abcdef"
    await progress({
        "call_id": call.get("call_id") or "workbook-call-1",
        "checkpoint_id": "cp-1",
        "phase": "rows",
        "completed": 3,
        "total": 10,
        "label": "Собираю строки ВОР",
    })
    return {
        "schema": "les.workbook_tool_result.v1",
        "tool": call["tool"],
        "status": "complete",
        "artifact": {
            "revision_id": "rev-2",
            "artifact_id": "artifact-1",
            "revision_no": 2,
            "filename": "vor-r2.xlsx",
            "download_url": "/api/artifacts/rev-2/download",
            "source_scope": ["attachment:read_123456abcdef"],
            "decision_checkpoint_id": "cp-1",
        },
        "source": {"attachment_id": "read_123456abcdef", "sha256": "a" * 64},
        "checkpoint": {"checkpoint_id": "cp-1", "status": "complete"},
        "missing": [],
        "blockers": [],
    }


async def _tracked_workbook_execution(call, context, progress, events, calls):
    calls.append(call)
    return await _fake_workbook_execution(call, context, progress, events)


async def _rejected_workbook_execution(call, calls):
    calls.append(call)
    return {
        "schema": "les.workbook_tool_result.v1",
        "tool": "build_vor_workbook",
        "status": "rejected",
        "code": "TOOL_SCOPE_VIOLATION",
        "message": "foreign attachment must not execute",
        "missing": [],
        "blockers": [],
    }


def test_workbook_result_harvests_revision_retry_and_checkpoint():
    harvested = service.harvest_workbook_tool_result(
        {
            "schema": "les.workbook_tool_result.v1",
            "tool": "build_vor_workbook",
            "status": "complete",
            "artifact": {
                "revision_id": "rev-2",
                "artifact_id": "artifact-1",
                "revision_no": 2,
                "filename": "vor-r2.xlsx",
                "download_url": "/api/artifacts/rev-2/download",
                "source_scope": ["attachment:read_123456abcdef"],
                "decision_checkpoint_id": "cp-1",
            },
            "source": {"attachment_id": "read_123456abcdef", "sha256": "a" * 64},
            "checkpoint": {"checkpoint_id": "cp-1", "status": "complete"},
        }
    )

    assert harvested["artifact"]["revision_id"] == "rev-2"
    assert harvested["attachment_retry"]["attachment_id"] == "read_123456abcdef"
    assert harvested["source"] == {
        "attachment_id": "read_123456abcdef",
        "sha256": "a" * 64,
    }
    assert harvested["attachment_retry"]["preserved"] is True
    assert harvested["checkpoint"]["checkpoint_id"] == "cp-1"


def test_workbook_harvest_rejects_artifact_without_bound_attachment_checkpoint_lineage():
    harvested = service.harvest_workbook_tool_result(
        {
            "schema": "les.workbook_tool_result.v1",
            "tool": "build_vor_workbook",
            "status": "complete",
            "artifact": {
                "revision_id": "rev-2",
                "artifact_id": "artifact-1",
                "source_scope": ["attachment:read_foreign"],
                "decision_checkpoint_id": "cp-other",
            },
            "source": {"attachment_id": "read_123456abcdef"},
            "checkpoint": {"checkpoint_id": "cp-1", "status": "complete"},
        }
    )

    assert harvested == {}


@pytest.mark.asyncio
async def test_workbook_packaging_retries_same_decisions_and_checkpoint_only_once():
    calls = []

    async def executor(call, context, progress):
        calls.append((call, context, progress))
        attempt = len(calls)
        return {
            "schema": "les.workbook_tool_result.v1",
            "tool": "build_lsr_workbook",
            "status": "failed" if attempt == 1 else "complete",
            "code": "WORKBOOK_GENERATION_FAILED" if attempt == 1 else "",
            "checkpoint": {
                "checkpoint_id": "cp-stable",
                "status": "failed" if attempt == 1 else "complete",
                "resumed": attempt == 2,
            },
        }

    call = {
        "tool": "build_lsr_workbook",
        "args": {"decisions": [{"source_row": 1, "norm_code": "ГЭСН-1"}]},
    }
    payload, traces = await service.execute_workbook_with_bounded_retry(
        executor,
        call,
        {"session_id": "s1"},
        None,
    )

    assert len(calls) == 2
    assert calls[0][0] is call and calls[1][0] is call
    assert payload["status"] == "complete"
    assert traces == [
        {
            "tool": "build_lsr_workbook",
            "attempt": 1,
            "status": "failed",
            "code": "WORKBOOK_GENERATION_FAILED",
            "checkpoint_id": "cp-stable",
            "resumed": False,
        },
        {
            "tool": "build_lsr_workbook",
            "attempt": 2,
            "status": "complete",
            "code": "",
            "checkpoint_id": "cp-stable",
            "resumed": True,
        },
    ]


def test_workbook_history_projection_redacts_failures_paths_and_unbounded_results():
    raw = {
        "schema": "les.workbook_tool_result.v1",
        "tool": "build_vor_workbook",
        "status": "failed",
        "code": "WORKBOOK_GENERATION_FAILED",
        "message": "adapter failed at C:/private/workbook.xlsx",
        "artifact": {
            "artifact_id": "art-1",
            "revision_id": "rev-1",
            "download_url": "/api/artifacts/rev-1/download",
            "source_scope": ["attachment:read_123456abcdef"],
            "decision_checkpoint_id": "cp-1",
            "filename": "C:/private/workbook.xlsx",
            "tool_calls": [{"private": "unbounded result"}],
        },
        "checkpoint": {"checkpoint_id": "cp-1", "status": "failed"},
        "source": {"attachment_id": "read_123456abcdef", "name": "C:/private/source.xlsx"},
        "blockers": ["RuntimeError: private filesystem detail"],
        "result": {"raw": "unbounded result"},
    }

    safe = service.safe_workbook_history_projection(raw)

    assert safe == {
        "schema": "les.workbook_tool_result.v1",
        "tool": "build_vor_workbook",
        "status": "failed",
        "code": "WORKBOOK_GENERATION_FAILED",
        "artifact": {
            "artifact_id": "art-1",
            "revision_id": "rev-1",
            "download_url": "/api/artifacts/rev-1/download",
            "source_scope": ["attachment:read_123456abcdef"],
            "decision_checkpoint_id": "cp-1",
        },
        "checkpoint": {"checkpoint_id": "cp-1", "status": "failed"},
        "source": {"attachment_id": "read_123456abcdef"},
    }
    serialized = json.dumps(safe, ensure_ascii=False)
    assert "private" not in serialized
    assert "unbounded result" not in serialized
    assert "RuntimeError" not in serialized


@pytest.mark.asyncio
async def test_chat_workbook_executor_builds_revision_and_streams_checkpoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Раздел", "Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["ОВ", "Воздуховод", "м", 12.5])
    workbook.save(source)
    workbook.close()
    attachment = preserve_read_attachment(
        source,
        attachment_id="read_123456abcdef",
        original_name="source.xlsx",
        root=attachment_root,
    )
    progress = []

    async def on_progress(event):
        progress.append(event)

    result = await chat._execute_chat_workbook_tool(
        {
            "call_id": "call-1",
            "tool": "build_vor_workbook",
            "args": {"attachment_id": attachment["attachment_id"], "decisions": [{
                "source_row": "Sheet!R2", "row_role": "work", "title": "Монтаж воздуховода",
                "unit": "м", "quantity": 12.5, "coverage": "Монтаж по исходной спецификации",
            }]},
        },
        {
            "session_id": "session-1",
            "question": "Собери ВОР",
            "attachment_id": attachment["attachment_id"],
            "dataset_ids": [],
            "project_id": None,
            "profile_revision_id": "profile-1",
            "model_identity": "qwen-local",
            "model_preset": "qwen-9b",
        },
        on_progress,
    )

    assert result["status"] == "complete"
    assert result["artifact"]["revision_no"] == 1
    assert result["source"]["attachment_id"] == attachment["attachment_id"]
    assert f"attachment:{attachment['attachment_id']}" in result["artifact"]["source_scope"]
    assert result["artifact"]["decision_checkpoint_id"] == result["checkpoint"]["checkpoint_id"]
    assert progress[-1]["checkpoint_id"] == result["checkpoint"]["checkpoint_id"]
    assert progress[-1]["label"] == "Собираю строки ВОР"
    assert Path("storage/artifacts/meta.db").is_file()


@pytest.mark.asyncio
async def test_chat_lsr_executor_runs_thin_model_decision_adapter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Воздуховод", "м", 12.5])
    workbook.save(source)
    workbook.close()
    attachment = preserve_read_attachment(
        source,
        attachment_id="read_123456abcdef",
        original_name="source.xlsx",
        root=attachment_root,
    )
    decisions = [{
        "source_row": 1,
        "section": "ОВ",
        "title": "Монтаж воздуховода",
        "unit": "м",
        "quantity": 12.5,
        "norm_code": "ГЭСН20-01-001-01",
        "evidence_refs": ["dataset:fsnb:card:20-01-001-01"],
    }]

    def calculate(rows, **_kwargs):
        # The adapter may stamp technical catalog facts, never rewrite model cells.
        stripped = [
            {k: v for k, v in item.items() if not str(k).startswith("_catalog_source")}
            for item in rows
        ]
        assert stripped == decisions
        return {
            "schema": "rim_lsr_v1",
            "sections": [],
            "summary": {"input_rows": 1, "bound_rows": 1, "flags": []},
            "row_bindings": [{"row": 1, "status": "bound"}],
        }

    def render(_trace, output_path, **_kwargs):
        workbook = openpyxl.Workbook()
        workbook.active.append(["ЛСР"])
        workbook.save(output_path)
        workbook.close()
        return output_path

    monkeypatch.setattr(
        "proxy.services.lsr_workbook_adapter_service.build_lsr_trace_from_visible_rows",
        calculate,
    )
    monkeypatch.setattr(
        "proxy.services.lsr_workbook_adapter_service.render_lsr_xlsx",
        render,
    )

    result = await chat._execute_chat_workbook_tool(
        {
            "call_id": "call-lsr-1",
            "tool": "build_lsr_workbook",
            "args": {"attachment_id": attachment["attachment_id"], "decisions": decisions},
        },
        {
            "session_id": "session-1",
            "question": "Собери ЛСР",
            "attachment_id": attachment["attachment_id"],
            "dataset_ids": ["fsnb"],
            "project_id": None,
            "profile_revision_id": "profile-1",
            "model_identity": "qwen-local",
            "model_preset": "qwen-9b",
        },
        lambda _event: asyncio.sleep(0),
    )

    assert result["status"] == "complete"
    assert result["tool"] == "build_lsr_workbook"
    assert result["source"]["rows"] == 1
    assert "dataset:fsnb" in result["artifact"]["source_scope"]
    assert result["blockers"] == []


@pytest.mark.asyncio
async def test_chat_lsr_executor_accepts_operator_confirmed_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Кабель", "м", 10])
    workbook.save(source)
    workbook.close()
    attachment = preserve_read_attachment(
        source,
        attachment_id="read_123456abcdef",
        original_name="source.xlsx",
        root=attachment_root,
    )
    decisions = [{
        "source_row": "СКС!R2",
        "title": "Кабель",
        "unit": "м",
        "quantity": 10,
        "norm_code": "10-06-024-01",
    }]
    overlays = {"СКС!R2": {"confirmed_price": 125.5, "price_source": "КАЦ"}}
    captured = {}

    def calculate(rows, **kwargs):
        captured["rows"] = rows
        captured["kwargs"] = kwargs
        return {
            "schema": "rim_lsr_v1",
            "sections": [],
            "summary": {"input_rows": 1, "bound_rows": 1, "flags": []},
            "row_bindings": [{"row": "СКС!R2", "status": "bound"}],
        }

    def render(_trace, output_path, **_kwargs):
        workbook = openpyxl.Workbook()
        workbook.active.append(["ЛСР"])
        workbook.save(output_path)
        workbook.close()
        return output_path

    monkeypatch.setattr(
        "proxy.services.lsr_workbook_adapter_service.build_lsr_trace_from_visible_rows",
        calculate,
    )
    monkeypatch.setattr(
        "proxy.services.lsr_workbook_adapter_service.render_lsr_xlsx",
        render,
    )

    result = await chat._execute_chat_workbook_tool(
        {
            "call_id": "call-lsr-confirmed",
            "tool": "build_lsr_workbook",
            "args": {
                "attachment_id": attachment["attachment_id"],
                "question": "Собери ЛСР",
                "decisions": decisions,
                "confirmed_data": overlays,
            },
        },
        {
            "session_id": "session-1",
            "question": "Собери ЛСР",
            "attachment_id": attachment["attachment_id"],
            "dataset_ids": [],
            "project_id": None,
            "profile_revision_id": "profile-1",
            "model_identity": "qwen-local",
            "model_preset": "qwen-9b",
        },
        lambda _event: asyncio.sleep(0),
    )

    assert result.get("code") != "TOOL_SCHEMA_INVALID"
    assert result["status"] == "complete"
    assert captured["rows"] == decisions
    assert captured["kwargs"]["confirmed_data"] == overlays


@pytest.mark.asyncio
async def test_chat_lsr_executor_repack_without_progress_sink(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Кабель", "м", 10])
    workbook.save(source)
    workbook.close()
    attachment = preserve_read_attachment(
        source,
        attachment_id="read_123456abcdef",
        original_name="source.xlsx",
        root=attachment_root,
    )
    decisions = [{
        "source_row": "СКС!R2",
        "title": "Кабель",
        "unit": "м",
        "quantity": 10,
        "norm_code": "10-06-024-01",
    }]

    def calculate(rows, **kwargs):
        return {
            "schema": "rim_lsr_v1",
            "sections": [],
            "summary": {"input_rows": 1, "bound_rows": 1, "flags": []},
            "row_bindings": [{"row": "СКС!R2", "status": "bound"}],
        }

    def render(_trace, output_path, **_kwargs):
        workbook = openpyxl.Workbook()
        workbook.active.append(["ЛСР"])
        workbook.save(output_path)
        workbook.close()
        return output_path

    monkeypatch.setattr(
        "proxy.services.lsr_workbook_adapter_service.build_lsr_trace_from_visible_rows",
        calculate,
    )
    monkeypatch.setattr(
        "proxy.services.lsr_workbook_adapter_service.render_lsr_xlsx",
        render,
    )

    result = await chat._execute_chat_workbook_tool(
        {
            "call_id": "call-lsr-repack",
            "tool": "build_lsr_workbook",
            "args": {
                "attachment_id": attachment["attachment_id"],
                "decisions": decisions,
                "confirmed_data": {},
            },
        },
        {
            "session_id": "session-1",
            "question": "Собери ЛСР",
            "attachment_id": attachment["attachment_id"],
            "dataset_ids": [],
            "project_id": None,
            "profile_revision_id": "profile-1",
            "model_identity": "qwen-local",
            "model_preset": "qwen-9b",
        },
        None,
    )

    assert result.get("code") != "WORKBOOK_GENERATION_FAILED"
    assert result["status"] == "complete"


@pytest.mark.asyncio
async def test_chat_lsr_executor_keeps_overflow_workbook_for_operator(tmp_path, monkeypatch):
    from dataclasses import replace

    from proxy.services.tool_contract_service import ResultBudget
    from proxy.services import workbook_tool_service as workbook_tools

    monkeypatch.chdir(tmp_path)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Кабель", "м", 10])
    workbook.save(source)
    workbook.close()
    attachment = preserve_read_attachment(
        source,
        attachment_id="read_123456abcdef",
        original_name="source.xlsx",
        root=attachment_root,
    )
    decisions = [{
        "source_row": "СКС!R2",
        "title": "Кабель",
        "unit": "м",
        "quantity": 10,
        "norm_code": "10-06-024-01",
        "coverage": "x" * 400,
    }]
    monkeypatch.setattr(
        workbook_tools,
        "BUILD_LSR_WORKBOOK",
        replace(
            workbook_tools.BUILD_LSR_WORKBOOK,
            result_budget=ResultBudget(max_chars=80, max_items=1),
        ),
    )

    def calculate(rows, **kwargs):
        return {
            "schema": "rim_lsr_v1",
            "sections": [],
            "summary": {"input_rows": 1, "bound_rows": 1, "flags": []},
            "row_bindings": [{"row": "СКС!R2", "status": "bound"}],
        }

    def render(_trace, output_path, **_kwargs):
        book = openpyxl.Workbook()
        book.active.append(["ЛСР"])
        book.save(output_path)
        book.close()
        return output_path

    monkeypatch.setattr(
        "proxy.services.lsr_workbook_adapter_service.build_lsr_trace_from_visible_rows",
        calculate,
    )
    monkeypatch.setattr(
        "proxy.services.lsr_workbook_adapter_service.render_lsr_xlsx",
        render,
    )

    result = await chat._execute_chat_workbook_tool(
        {
            "call_id": "call-lsr-overflow",
            "tool": "build_lsr_workbook",
            "args": {
                "attachment_id": attachment["attachment_id"],
                "decisions": decisions,
            },
        },
        {
            "session_id": "session-overflow",
            "question": "Собери ЛСР",
            "attachment_id": attachment["attachment_id"],
            "dataset_ids": [],
            "project_id": None,
            "profile_revision_id": "profile-1",
            "model_identity": "qwen-local",
            "model_preset": "qwen-9b",
        },
        None,
    )

    assert result.get("execution", {}).get("status") == "overflow"
    assert result["status"] == "complete"
    assert result["artifact"]["download_url"]


@pytest.mark.asyncio
async def test_chat_workbook_executor_rejects_model_dataset_outside_chat_scope(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Кабель", "м", 2])
    workbook.save(source)
    workbook.close()
    preserve_read_attachment(
        source,
        attachment_id="read_123456abcdef",
        original_name="source.xlsx",
        root=attachment_root,
    )

    async def on_progress(_event):
        raise AssertionError("rejected execution must not start")

    result = await chat._execute_chat_workbook_tool(
        {
            "tool": "build_vor_workbook",
            "args": {
                "attachment_id": "read_123456abcdef",
                "dataset_ids": ["foreign-dataset"],
            },
        },
        {
            "session_id": "session-1",
            "question": "Собери ВОР",
            "attachment_id": "read_123456abcdef",
            "dataset_ids": [],
            "project_id": None,
            "profile_revision_id": "profile-1",
            "model_identity": "qwen-local",
            "model_preset": "qwen-9b",
        },
        on_progress,
    )

    assert result["code"] == "TOOL_SCOPE_VIOLATION"
    assert "artifact" not in result
    assert not Path("storage/workbook_checkpoints.db").exists()
    assert not Path("storage/artifacts/meta.db").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_dataset_ids", "expected_status"),
    ((["selected-a"], "rejected"), (["selected-b", "selected-a"], "complete")),
)
async def test_chat_workbook_executor_binds_exact_request_dataset_scope(
    tmp_path, monkeypatch, model_dataset_ids, expected_status
):
    """A workbook artifact always records the full server-owned request scope."""
    monkeypatch.chdir(tmp_path)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Кабель", "м", 2])
    workbook.save(source)
    workbook.close()
    attachment = preserve_read_attachment(
        source,
        attachment_id="read_123456abcdef",
        original_name="source.xlsx",
        root=attachment_root,
    )

    async def on_progress(_event):
        return None

    result = await chat._execute_chat_workbook_tool(
        {
            "tool": "build_vor_workbook",
            "args": {
                "attachment_id": attachment["attachment_id"],
                "dataset_ids": model_dataset_ids,
                "decisions": [{"source_row": "Sheet!R2", "row_role": "work",
                               "title": "Прокладка кабеля", "unit": "м", "quantity": 2}],
            },
        },
        {
            "session_id": "session-1",
            "question": "Собери ВОР",
            "attachment_id": attachment["attachment_id"],
            "dataset_ids": ["selected-a", "selected-b"],
            "project_id": None,
            "profile_revision_id": "profile-1",
            "model_identity": "qwen-local",
            "model_preset": "qwen-9b",
        },
        on_progress,
    )

    assert result["status"] == expected_status
    if expected_status == "rejected":
        assert result["code"] == "TOOL_SCOPE_VIOLATION"
        assert "artifact" not in result
        return
    assert result["artifact"]["source_scope"] == [
        f"attachment:{attachment['attachment_id']}",
        "dataset:selected-a",
        "dataset:selected-b",
    ]


@pytest.mark.asyncio
async def test_chat_workbook_executor_rejects_foreign_preserved_attachment_before_execution(
    tmp_path, monkeypatch
):
    """A model cannot switch a request to another server-owned attachment."""
    monkeypatch.chdir(tmp_path)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Кабель", "м", 2])
    workbook.save(source)
    workbook.close()
    bound = preserve_read_attachment(
        source,
        attachment_id="read_111111111111",
        original_name="bound.xlsx",
        root=attachment_root,
    )
    foreign = preserve_read_attachment(
        source,
        attachment_id="read_222222222222",
        original_name="foreign.xlsx",
        root=attachment_root,
    )

    result = await chat._execute_chat_workbook_tool(
        {
            "tool": "build_vor_workbook",
            "args": {"attachment_id": foreign["attachment_id"]},
        },
        {
            "session_id": "session-1",
            "question": "Собери ВОР",
            "attachment_id": bound["attachment_id"],
            "dataset_ids": [],
            "project_id": None,
            "profile_revision_id": "profile-1",
            "model_identity": "qwen-local",
            "model_preset": "qwen-9b",
        },
        lambda _event: None,
    )

    assert result["status"] == "rejected"
    assert result["code"] == "TOOL_SCOPE_VIOLATION"
    assert not Path("storage/workbook_checkpoints.db").exists()
    assert not Path("storage/artifacts/meta.db").exists()
from proxy.services.canonical_route_service import CanonicalRouteMode
from proxy.services.context_governor_service import (
    ContextKind,
    ContextObject,
    ContextRequiredSectionOverflow,
)
from proxy.services.model_execution_preset_service import ModelExecutionPreset


def _governor_preset(
    *, input_tokens: int = 6000, preset_id: str = "fixture-restrictive"
) -> ModelExecutionPreset:
    return ModelExecutionPreset(
        preset_id=preset_id,
        model_family="fixture",
        input_token_limit=input_tokens,
        generation_reserve_tokens=20,
        safety_reserve_tokens=20,
        normal_tool_count=3,
        max_tools=5,
        max_batch_items=5,
        parallel_read_limit=1,
        reasoning_enabled=False,
        source_chain=("test",),
    )


def test_governed_inference_trace_exposes_exact_evidence_but_not_private_memory() -> None:
    messages, packet = service.govern_inference_messages(
        preset=_governor_preset(),
        profile_prefix="bound profile",
        request_payload={"question": "current request"},
        shortlist=[{"name": "read_source"}],
        checkpoint=[ContextObject("checkpoint:1", {"status": "continue"})],
        working_memory=[
            ContextObject("memory:1", {"context_role": "advisory_state", "secret": "hidden"})
        ],
        evidence=[{"source": "evidence payload"}],
        source_map=[{"label": "Источник 1"}],
        tool_exchange=[{"status": "ok"}],
        dialogue=["prior turn"],
        terminal_instruction="bound final phase",
    )

    assert [section.kind for section in packet.sections] == [
        kind for kind in ContextKind if kind not in {ContextKind.CURRENT_READ_FRAME, ContextKind.PHASE_INSTRUCTION}
    ]
    assert [message["role"] for message in messages] == ["system", "user", "user"]
    assert messages[-1]["content"] == "bound final phase"
    trace = service.context_packet_trace(packet, purpose="answer")
    assert trace["purpose"] == "answer"
    assert [section["kind"] for section in trace["sections"]] == [
        kind.value for kind in ContextKind if kind not in {ContextKind.CURRENT_READ_FRAME, ContextKind.PHASE_INSTRUCTION}
    ]
    assert "hidden" not in json.dumps(trace)
    evidence = next(section for section in trace["sections"] if section["kind"] == "evidence")
    source_map = next(section for section in trace["sections"] if section["kind"] == "source_map")
    assert evidence["objects"][0]["payload"] == {"source": "evidence payload"}
    assert evidence["objects"][0]["text"] == '{"source":"evidence payload"}'
    assert len(evidence["objects"][0]["sha256"]) == 64
    assert source_map["objects"][0]["payload"] == {"label": "Источник 1"}
    terminal = next(section for section in trace["sections"] if section["kind"] == "terminal_request")
    assert terminal["object_ids"] == ["request:terminal-phase"]
    assert "objects" not in terminal
    assert "bound final phase" not in json.dumps(trace)


def test_context_trace_records_exact_omitted_evidence_ids_and_cursor() -> None:
    _messages, packet = service.govern_inference_messages(
        preset=_governor_preset(input_tokens=90),
        profile_prefix="p",
        request_payload="q",
        evidence=["x" * 200],
        source_map=[{"label": "Источник 1"}],
    )

    trace = service.context_packet_trace(packet, purpose="tool_decision")
    omitted = next(item for item in trace["omissions"] if item["kind"] == "evidence")

    assert omitted["object_ids"] == ["evidence:0"]
    assert omitted["cursor"].startswith("ctx:evidence:")


def test_governed_inference_rejects_required_overflow_before_provider_call() -> None:
    provider_calls = []

    with pytest.raises(ContextRequiredSectionOverflow):
        messages, _packet = service.govern_inference_messages(
            preset=_governor_preset(input_tokens=50),
            profile_prefix="profile is too large for this deliberately tiny fixture",
            request_payload={"question": "also required"},
        )
        provider_calls.append(messages)

    assert provider_calls == []


@pytest.mark.parametrize("purpose,reserve", [("query", 16000), ("answer", 24000)])
def test_profile_output_budget_is_reserved_before_native_tools_and_required_evidence(purpose, reserve):
    from proxy.services.model_execution_preset_service import (
        BackendCapacity, model_rag_answer_execution_preset, resolve_execution_preset,
    )
    preset = resolve_execution_preset(
        BackendCapacity("freetoken", "Qwen3.6-35B", 65536, True, "fixture"),
        operator={"query_output_tokens": 16000, "answer_output_tokens": 24000},
    )
    if purpose == "answer":
        preset = model_rag_answer_execution_preset(preset, model_rag=True)
    tools = [{"type": "function", "function": {"name": "read_source",
              "description": "Return literal source " * 20,
              "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}}]
    messages, packet = service.govern_inference_messages(
        preset=preset, profile_prefix="literal profile", request_payload="literal question",
        native_tools=tools, required_evidence=["literal source row", "complete evidence body"],
    )
    assert packet.generation_reserve_tokens == reserve
    assert packet.provider_payload_tokens > 0
    assert packet.input_budget_tokens == 65536 - reserve - 2048 - packet.provider_payload_tokens
    assert packet.included_tokens + packet.provider_payload_tokens + reserve + 2048 <= 65536
    assert "literal source row" in str(messages) and "complete evidence body" in str(messages)
    if purpose == "query":
        budget = service.governed_query_generation_budget(preset, packet)
        assert budget["effective"] == reserve and budget["reserved_tokens"] == reserve


def test_gui_query_limit_only_narrows_reserved_profile_output(monkeypatch):
    from proxy.services.model_execution_preset_service import BackendCapacity, resolve_execution_preset
    preset = resolve_execution_preset(
        BackendCapacity("freetoken", "Qwen3.6-35B", 65536, True, "fixture"),
        operator={"query_output_tokens": 16000, "answer_output_tokens": 24000},
    )
    _messages, packet = service.govern_inference_messages(
        preset=preset, profile_prefix="profile", request_payload="question",
    )
    monkeypatch.setenv("LES_CHAT_MODEL_RAG_QUERY_MAX_TOKENS", "4096")
    assert service.governed_query_generation_budget(preset, packet)["effective"] == 4096
    monkeypatch.setenv("LES_CHAT_MODEL_RAG_QUERY_MAX_TOKENS", "65536")
    assert service.governed_query_generation_budget(preset, packet)["effective"] == 16000
    assert packet.generation_reserve_tokens == preset.generation_reserve_tokens == 16000
    assert preset.diagnostics()["answer_output_tokens"]["effective"] == 24000


def test_cloud_fallback_re_resolves_and_repacks_before_local_provider() -> None:
    source = inspect.getsource(service._execute_chat_evidence_application)

    resolve_at = source.index("fallback_preset = resolve_transport_execution_profile(")
    repack_at = source.index("fallback_messages, fallback_packet = govern_inference_messages(")
    send_at = source.index("fallback_body = {")
    assert resolve_at < repack_at < send_at
    assert '"messages": fallback_messages' in source
    assert "fallback_answer_preset.generation_reserve_tokens" in source
    assert 'purpose="answer_fallback"' in source


def test_general_evidence_execution_is_outside_http_router():
    router_source = inspect.getsource(chat._run_chat)
    evidence_source = inspect.getsource(service._execute_chat_evidence_application)

    assert "retrieval_trace = retrieval.payload()" not in router_source
    assert "build_retrieval_evidence_packet(" not in router_source
    assert "async with gen_semaphore" not in router_source
    assert "retrieval_trace = retrieval.payload()" in evidence_source
    assert "build_retrieval_evidence_packet(" in evidence_source
    assert "async with acquire_generation_slot" in evidence_source
    assert "generation_slot_timeout_seconds()" in evidence_source
    assert "timeout_seconds=45.0" not in evidence_source


def test_evidence_boundary_is_typed_and_does_not_capture_namespaces():
    router_source = inspect.getsource(chat._run_chat)
    service_source = inspect.getsource(service)

    assert "globals()" not in router_source
    assert "locals()" not in router_source
    assert "global_scope" not in service_source
    assert "local_scope" not in service_source
    assert {field.name for field in fields(service.EvidenceRequestContext)} >= {
        "req", "dataset_ids", "query_route_payload", "target_file_ref", "topic_retrieval_plan"
    }
    assert {field.name for field in fields(service.EvidenceRuntimeDeps)} >= {
        "state", "rag_backend", "cache", "llm_runtime", "table_query_response"
    }
    assert {field.name for field in fields(service.ResponseBoundary)} == {
        "save_chat_history", "token_sink", "version_stamp"
    }


def test_router_builds_explicit_evidence_contracts():
    router_source = inspect.getsource(chat._run_chat)

    assert "EvidenceRequestContext(" in router_source
    assert "EvidenceRuntimeDeps(" in router_source
    assert "ResponseBoundary(" in router_source
    assert "run_chat_evidence_application(" in router_source


@pytest.mark.asyncio
async def test_typed_contract_maps_every_internal_binding(monkeypatch):
    dummy = lambda *_args, **_kwargs: None
    request = service.EvidenceRequestContext(
        req=SimpleNamespace(question="test"),
        dataset_ids=["ds"],
        effective_dataset_filter="DS",
        resolved_dataset_names=["Dataset"],
        dataset_name_by_id={"ds": "Dataset"},
        query_route_payload={"channel": "rag"},
        target_doc_filter=[],
        target_file_ref=None,
        topic_doc_filter=[],
        topic_retrieval_plan=None,
        inventory_requested=False,
        study_requested=False,
        memory_block="",
        session_block="",
        class_suggestions=[],
        use_semantic_cache=False,
        use_validation=False,
        validation_skip_reason="test",
        route=SimpleNamespace(intent="rag"),
        table_result=None,
        request_started_at=1.0,
    )
    runtime = service.EvidenceRuntimeDeps(
        state="state", rag_backend="rag", cache="cache", cache_embedding=None,
        cache_marker="miss", cache_scope="scope",
        assistant_text=dummy, augment_model_tool_args=dummy,
        chat_model_final_answer=dummy, cloud_body_for_model=dummy,
        compact_tool_result_for_prompt=dummy, dataset_ids_from_chunks=dummy,
        dataset_sensitivities=dummy, env_bool=dummy, env_float=dummy, env_int=dummy,
        expand_context_windows=dummy,
        format_tool_results_for_model=dummy, generation_token_budget=dummy,
        llm_runtime=dummy, local_context_budget=dummy, mlx_runtime=dummy,
        names_for_dataset_ids=dummy, notebook_study_validation_status=dummy,
        ollama_native_complete=dummy, parse_model_tool_calls=dummy,
        prepare_notebook_reader_memory=dummy, record_cloud_cost=dummy,
        retrieve_chat_chunks=dummy,
        source_excerpts=dummy, table_query_response=dummy,
        cloud_fallback_models=dummy, cloud_model_timeout=dummy,
    )
    boundary = service.ResponseBoundary(
        save_chat_history=dummy,
        token_sink=None,
        version_stamp=dummy,
    )
    captured = {}

    async def fake_execute(**kwargs):
        captured.update(kwargs)
        return {"answer": "ok"}

    monkeypatch.setattr(service, "_execute_chat_evidence_application", fake_execute)

    result = await service.run_chat_evidence_application(request, runtime, boundary)

    assert result == {"answer": "ok"}
    assert captured["req"] is request.req
    assert captured["_dataset_ids"] == ["ds"]
    assert captured["state"] == "state"
    assert captured["source_excerpts"] is dummy
    assert captured["save_chat_history"] is dummy


@pytest.mark.asyncio
async def test_shadow_candidate_executes_only_one_decision_and_redacts_result() -> None:
    calls = []

    class FakeHarness:
        async def call_async(self, tool, args, **policy):
            calls.append((tool, args, policy))
            return {
                "schema": "les_tool_result_v1",
                "status": "ok",
                "result": {"secret_text": "must not enter shadow trace"},
                "execution": {
                    "schema": "les_tool_execution_v1",
                    "status": "ok",
                    "code": "TOOL_OK",
                },
            }

    trace = await service.execute_canonical_shadow_decision(
        proposed_calls=[
            {"tool": "read_source", "args": {"doc_id": "d1"}},
            {"tool": "read_source", "args": {"doc_id": "d2"}},
        ],
        allowed_tools={"read_source"},
        dataset_ids=["selected"],
        tool_harness=FakeHarness(),
    )

    assert len(calls) == 1
    assert calls[0][2]["shadow"] is True
    assert trace["executed_calls"] == 1
    assert trace["pending_calls"] == 1
    assert trace["user_visible"] is False
    assert "secret_text" not in str(trace)


def test_grounded_application_never_uses_answer_cache_or_code_no_data_final() -> None:
    source = inspect.getsource(service._execute_chat_evidence_application)

    assert "if document_grounding_enabled:" in source
    assert "use_semantic_cache = False" in source
    assert "stamp_empty_retrieval(" in source
    assert "empty_scoped_retrieval_no_data_v1" not in source
    assert "if not chunks and effective_dataset_filter:" not in source
    assert "if not chunks and target_file_ref" not in source
    helpers = inspect.getsource(service.stamp_empty_retrieval) + inspect.getsource(
        service.finalize_actual_retrieval_emptiness
    )
    assert '"empty_retrieval_model_first_v1"' in helpers


def test_plain_ai_scope_removes_only_document_evidence_tools() -> None:
    tools = service.tools_for_document_scope(
        ["search_sources", "read_source", "calculate", "send_mail"],
        enabled=False,
    )

    assert tools == ["calculate", "send_mail"]
    assert service.tools_for_document_scope(
        ["search_sources", "read_source", "calculate"], enabled=True
    ) == ["search_sources", "read_source", "calculate"]


def test_estimator_role_uses_model_authored_initial_rag_query() -> None:
    assert service.profile_uses_model_driven_retrieval(
        {
            "mode": "estimator",
            "rag_policy": {
                "system_datasets": ["smeta"],
                "model_authored_initial_query": True,
            },
        }
    ) is True


def test_native_tool_selector_keeps_attachment_rows_inside_9b_context() -> None:
    attachment = "\n".join(
        f"{row}. Работа {row} | шт. | {row}" for row in range(1, 31)
    )
    evidence = service.selector_evidence_payload(
        attachment_context=attachment,
        rendered_context="[ФРАГМЕНТЫ ИЗ ИСТОЧНИКОВ]\nНет найденных фрагментов.",
    )
    messages, packet = service.govern_inference_messages(
        preset=_governor_preset(input_tokens=6000, preset_id="qwen-9b-restrictive"),
        profile_prefix=("Роль сметчика. " * 380),
        request_payload={"question": "Собери ЛСР", "attachment_id": "read_123456abcdef"},
        shortlist=service.selector_context_shortlist(
            [
                {"name": "search_sources", "input_schema": {"type": "object"}},
                {"name": "build_lsr_workbook", "input_schema": {"type": "object"}},
            ],
            native_tool_schemas=True,
        ),
        evidence=evidence,
    )

    visible = str(messages)
    assert "1. Работа 1 | шт. | 1" in visible
    assert "5. Работа 5 | шт. | 5" in visible
    assert not any(section.kind is ContextKind.TOOL_SHORTLIST for section in packet.sections)


def test_model_authored_first_search_is_not_labelled_as_empty_retrieval() -> None:
    empty_status = "[СТАТУС ИСТОЧНИКОВ: ФРАГМЕНТЫ НЕ НАЙДЕНЫ]"

    assert service.initial_selector_context(
        empty_status,
        model_authored_initial_query=True,
    ) == ""
    assert service.initial_selector_context(
        empty_status,
        model_authored_initial_query=False,
    ) == empty_status


def test_tool_selector_uses_thin_role_contract_and_bound_skill() -> None:
    prompt = service.profile_tool_selector_prompt(
        {
            "mode": "estimator",
            "prompt_text": "LONG ANSWER PROMPT MUST NOT ENTER TOOL DECISION",
            "skill_text": "Сначала изучи ВОР, затем ищи нормы.",
        }
    )

    assert "профиль estimator" in prompt
    assert "Сначала изучи ВОР, затем ищи нормы." in prompt
    assert "LONG ANSWER PROMPT" not in prompt
    assert "предметные решения" in prompt
    assert service.profile_uses_model_driven_retrieval(
        {
            "mode": "estimator",
            "rag_policy": {"system_datasets": ["smeta"]},
        }
    ) is True
    assert service.profile_uses_model_driven_retrieval(
        {
            "mode": "search",
            "rag_policy": {"model_authored_initial_query": True},
        }
    ) is True


def test_application_routes_model_search_sources_through_canonical_research_service() -> None:
    source = inspect.getsource(service._execute_chat_evidence_application)

    assert "ModelResearchToolService(" in source
    assert "model_research_tools.execute(call)" in source
    assert "retrieve=retrieve_chat_chunks" in source


def test_model_research_loop_is_evidence_first_and_model_stopped() -> None:
    source = inspect.getsource(service._execute_chat_evidence_application)

    initial_packet = source.index("initial_evidence_packet,")
    selector_loop = source.index(
        "while time.monotonic() < research_deadline and calls_remaining > 0:"
    )
    assert initial_packet < selector_loop
    assert "evidence=selector_evidence" in source
    assert "source_map=selector_source_map" in source
    assert "research_result.chunks" in source
    assert "seen_call_signatures" not in source
    assert 'stop_reason = "model_stop"' in source


def test_model_research_loop_enforces_call_budget_across_all_rounds() -> None:
    source = inspect.getsource(service._execute_chat_evidence_application)

    assert "calls_remaining = max_calls" in source
    assert "while time.monotonic() < research_deadline and calls_remaining > 0:" in source
    assert "max_calls=calls_remaining" in source
    assert "calls_remaining -= 1" in source
    assert 'stop_reason = "calls_budget"' in source


def test_ordinary_chat_does_not_semantically_validate_or_rewrite_model_answer() -> None:
    source = inspect.getsource(service._execute_chat_evidence_application)

    assert "use_validation = False" in source
    assert "_chat_model_final_answer(answer" not in source
    assert "_notebook_study_validation_status(" not in source
    assert 'final_evidence_packet["evidence_status"] = "partial"' not in source
    assert 'crag_status = "UNVALIDATED"' not in source[source.index("citation_check ="):]


@pytest.mark.asyncio
async def test_shadow_failure_is_redacted_and_cannot_escape_to_legacy_path() -> None:
    class ThrowingHarness:
        async def call_async(self, *_args, **_kwargs):
            raise RuntimeError("secret candidate failure")

    trace = await service.safe_execute_canonical_shadow_decision(
        proposed_calls=[{"tool": "read_source", "args": {"doc_id": "d1"}}],
        allowed_tools={"read_source"},
        dataset_ids=["selected"],
        tool_harness=ThrowingHarness(),
    )

    assert trace["status"] == "error"
    assert trace["error_type"] == "RuntimeError"
    assert trace["attempted_calls"] == 1
    assert "secret candidate failure" not in str(trace)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        "normal",
        "normal_unscoped",
        "selector_overflow",
        "cloud_retry",
        "cloud_retry_output_budgets",
        "active",
        "active_output_budgets",
        "active_web_research",
        "active_workbook",
        "active_workbook_private_arg",
        "active_workbook_rejected",
        "active_model_rag_result",
        "active_model_rag_output_budgets",
        "active_model_rag_recovery",
        "candidate_workbook",
        "shadow_workbook",
        "legacy_workbook",
    ],
)
async def test_actual_chat_shadow_failure_preserves_legacy_answer_history_and_model_count(
    monkeypatch,
    tmp_path,
    scenario,
    application_setup=None,
) -> None:
    selector_overflow = scenario == "selector_overflow"
    cloud_retry = scenario in {"cloud_retry", "cloud_retry_output_budgets"}
    fallback_budgets = scenario == "cloud_retry_output_budgets"
    output_budgets = scenario in {"active_model_rag_output_budgets", "active_output_budgets"}
    workbook_profile = scenario in {
        "active_workbook",
        "active_workbook_private_arg",
        "active_workbook_rejected",
        "active_model_rag_result",
        "active_model_rag_output_budgets",
        "active_model_rag_recovery",
        "candidate_workbook",
        "shadow_workbook",
        "legacy_workbook",
    }
    active_workbook = scenario in {
        "active_workbook",
        "active_workbook_private_arg",
        "active_workbook_rejected",
        "active_model_rag_result",
        "active_model_rag_output_budgets",
        "active_model_rag_recovery",
        "candidate_workbook",
    }
    candidate_acceptance = scenario == "candidate_workbook"
    rejected_workbook = scenario == "active_workbook_rejected"
    model_rag_recovery = scenario == "active_model_rag_recovery"
    model_rag_result = scenario in {
        "active_model_rag_result",
        "active_model_rag_output_budgets",
        "active_model_rag_recovery",
    }
    active_web_research = scenario == "active_web_research"
    active = scenario in {
        "active",
        "active_output_budgets",
        "active_web_research",
        "active_workbook",
        "active_workbook_private_arg",
        "active_workbook_rejected",
        "active_model_rag_result",
        "active_model_rag_output_budgets",
        "active_model_rag_recovery",
        "candidate_workbook",
    }
    inactive_workbook = workbook_profile and not active
    model_calls = []
    model_bodies = []
    shortlist_policies = []
    shadow_calls = []
    executor_codes = []
    legacy_calls = []
    history_rows = []
    progress_events = []
    workbook_executor_calls = []
    captured_web_configs = []
    rag_queries = []
    exact_decisions = [
        {
            "source_row": 1,
            "section": "ЭОМ",
            "title": "монтаж шкафа управления",
            "unit": "шт.",
            "quantity": 2.0,
            "norm_code": "ГЭСНм08-02-401-01",
            "analogue": "Монтаж оборудования по найденной карточке нормы",
            "coverage": "прямое соответствие",
            "evidence_refs": ["Q1.H1"],
        }
    ]
    protected_db = tmp_path / "protected.db"
    with sqlite3.connect(protected_db) as conn:
        conn.execute("CREATE TABLE protected_events (value TEXT NOT NULL)")

    def protected_hash():
        with sqlite3.connect(protected_db) as conn:
            rows = conn.execute(
                "SELECT value FROM protected_events ORDER BY rowid"
            ).fetchall()
        return hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()

    before_protected = protected_hash()

    class FakeResponse:
        status_code = 200

        def __init__(self, content):
            self._content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": self._content}}],
                "usage": {"completion_tokens": 7},
            }

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, _url, *, json, **_kwargs):
            model_bodies.append((_url, json))
            system_text = str(json["messages"][0]["content"])
            if "исследовательским чтением LES" in system_text:
                model_calls.append("selector")
                if model_calls.count("selector") > 1:
                    return FakeResponse('{"calls":[]}')
                return FakeResponse(
                    '{"calls":['
                    '{"tool":"read_source","args":{"doc_id":"d1"}},'
                    '{"tool":"read_source","args":{"doc_id":"d2"}}]}'
                )
            if cloud_retry and "cloud.fixture" in _url:
                model_calls.append("cloud_final")
                raise service.httpx.ConnectError("fixture cloud failure")
            if cloud_retry:
                model_calls.append("local_final")
                if model_calls.count("local_final") == 1:
                    return FakeResponse("")
                return FakeResponse("legacy visible answer")
            model_calls.append("final")
            return FakeResponse("legacy visible answer")

    from proxy.services.tool_contract_service import (
        EffectClass,
        IdempotencyPolicy,
        ResultBudget,
        RetryPolicy,
        ToolContract,
    )
    from proxy.services.tool_registry_service import ToolRegistration, ToolRegistry
    from proxy.services.trusted_executor_service import (
        ExecutionRequest,
        TrustedExecutor,
    )

    def persistence_probe_handler(args):
        with sqlite3.connect(protected_db) as conn:
            conn.execute("INSERT INTO protected_events VALUES (?)", (args["doc_id"],))
        return {
            "schema": "les_tool_result_v1",
            "tool": "read_source",
            "operation": "read",
            "inputs": [dict(args)],
            "status": "ok",
            "result": {},
            "sources": [],
            "missing": [],
            "warnings": [],
            "trace": "persistence probe",
            "decision_required_from_model": True,
        }

    registry = ToolRegistry(
        [
            ToolRegistration(
                contract=ToolContract(
                    name="read_source",
                    version="1.0.0",
                    title="Read source",
                    category="source",
                    summary="Read one source",
                    input_schema={
                        "type": "object",
                        "required": ["doc_id"],
                        "properties": {"doc_id": {"type": "string"}},
                        "additionalProperties": False,
                    },
                    result_schema="les_tool_result_v1",
                    effect=EffectClass.READ,
                    scopes=("dataset",),
                    timeout_seconds=30,
                    retry=RetryPolicy.SAFE,
                    idempotency=IdempotencyPolicy.DERIVED,
                    result_budget=ResultBudget(max_chars=7000, max_items=20),
                    model_owned_fields=(),
                    provenance="source_refs_required",
                    tags=("shadow_validate_only",),
                ),
                handler=persistence_probe_handler,
            )
        ]
    )
    executor = TrustedExecutor(
        registry,
        scope_resolver=lambda _contract, _args: ("selected",),
    )

    class ExecutorBackedHarness:
        def shortlist(self, *_args, **kwargs):
            shortlist_policies.append(dict(kwargs))
            if active_web_research:
                return {
                    "schema": "les_tool_shortlist_v1",
                    "tools": [
                        {
                            "name": "web_search",
                            "summary": "Search public web",
                            "input_schema": {
                                "type": "object",
                                "properties": {"q": {"type": "string"}},
                                "required": ["q"],
                                "additionalProperties": False,
                            },
                        },
                        {
                            "name": "web_read",
                            "summary": "Read selected public page",
                            "input_schema": {
                                "type": "object",
                                "properties": {"url": {"type": "string"}},
                                "required": ["url"],
                                "additionalProperties": False,
                            },
                        },
                    ],
                }
            if model_rag_result:
                return {
                    "schema": "les_tool_shortlist_v1",
                    "tools": [
                        *(
                            [
                                {
                                    "name": "build_vor_workbook",
                                    "summary": "Extract a VOR workbook without estimating it",
                                    "input_schema": {
                                        "type": "object",
                                        "properties": {"attachment_id": {"type": "string"}},
                                        "required": ["attachment_id"],
                                        "additionalProperties": False,
                                    },
                                }
                            ]
                            if model_rag_recovery
                            else []
                        ),
                        {
                            "name": "search_sources",
                            "summary": "Search frozen datasets with native RRF",
                            "input_schema": {
                                "type": "object",
                                "properties": {"q": {"type": "string"}},
                                "required": ["q"],
                                "additionalProperties": False,
                            },
                        },
                        {
                            "name": "build_lsr_workbook",
                            "summary": "Render model decisions as XLSX",
                            "input_schema": {
                                "type": "object",
                                "properties": {
                                    "attachment_id": {"type": "string"},
                                    "decisions": {"type": "array"},
                                },
                                "required": ["attachment_id", "decisions"],
                                "additionalProperties": False,
                            },
                        },
                    ],
                }
            return {
                "schema": "les_tool_shortlist_v1",
                "tools": [{"name": "build_vor_workbook" if workbook_profile else "read_source"}],
            }

        async def call_async(self, tool, args, **policy):
            shadow_calls.append((tool, dict(args)))
            envelope = await executor.execute(
                ExecutionRequest(
                    call_id="shadow-call-1",
                    tool_name=tool,
                    arguments=args,
                    allowed_dataset_ids=tuple(policy["allowed_dataset_ids"]),
                    actor_id=str(policy["actor_id"]),
                    actor_role=str(policy["actor_role"]),
                    approval_receipt_id=None,
                    idempotency_key=None,
                    deadline_monotonic=float(
                        policy.get("deadline_monotonic", time.monotonic() + 120)
                    ),
                    shadow=bool(policy["shadow"]),
                )
            )
            executor_codes.append(envelope.code)
            if not workbook_profile:
                assert envelope.code == (
                    "TOOL_SCOPE_VIOLATION"
                    if scenario == "normal_unscoped"
                    else "TOOL_WOULD_EXECUTE"
                )
            raise RuntimeError("secret shadow failure")

        def call(self, tool, args):
            legacy_calls.append((tool, dict(args)))
            if active_web_research and tool == "web_search":
                return {
                    "schema": "les_tool_result_v1",
                    "tool": "web_search",
                    "operation": "search",
                    "inputs": [dict(args)],
                    "status": "ok",
                    "result": {
                        "query": args["q"],
                        "requested_mode": "extended",
                        "effective_mode": "extended",
                        "provider": "searxng",
                        "degraded": False,
                        "fallback_reason": "",
                        "results": [
                            {
                                "title": "Каталог материалов",
                                "snippet": "Цены на цемент и арматуру",
                                "url": "https://public.example/materials",
                                "domain": "public.example",
                            }
                        ],
                    },
                    "sources": [
                        {
                            "kind": "web",
                            "title": "Каталог материалов",
                            "url": "https://public.example/materials",
                            "domain": "public.example",
                        }
                    ],
                    "missing": [],
                    "warnings": [],
                    "trace": "fixture search",
                    "decision_required_from_model": True,
                }
            if active_web_research and tool == "web_read":
                return {
                    "schema": "les_tool_result_v1",
                    "tool": "web_read",
                    "operation": "read",
                    "inputs": [dict(args)],
                    "status": "ok",
                    "result": {
                        "requested_url": args["url"],
                        "final_url": args["url"],
                        "title": "Каталог материалов",
                        "text": "Цемент — 650 руб.; арматура — 72 000 руб./т.",
                        "text_truncated": False,
                        "retrieved_at": "2026-09-02T10:00:00+00:00",
                    },
                    "sources": [
                        {
                            "kind": "web_page",
                            "title": "Каталог материалов",
                            "url": args["url"],
                        }
                    ],
                    "missing": [],
                    "warnings": [],
                    "trace": "fixture read",
                    "decision_required_from_model": True,
                }
            return {
                "schema": "les_tool_result_v1",
                "tool": tool,
                "operation": "read",
                "inputs": [dict(args)],
                "status": "missing",
                "result": {},
                "sources": [],
                "missing": ["test fixture"],
                "warnings": [],
                "trace": "legacy fixture",
                "decision_required_from_model": True,
            }

    class FakeRetrieval:
        trace = SimpleNamespace(status="ok", error_code="")
        quality = SimpleNamespace(status="weak", top_score=0.0)

        def __init__(self, chunks=()):
            self.chunks = list(chunks)

        def payload(self):
            return {"schema": "retrieval_trace_v1", "status": "ok"}

    class FakeWindows:
        def __init__(self, chunks=()):
            self.chunks = list(chunks)

        def payload(self):
            return {"schema": "context_windows_v1", "count": 0}

    runtime_config = SimpleNamespace(
        provider="openai" if cloud_retry else "mlx",
        model="cloud-fixture-model" if cloud_retry else "fixture-model",
        base_url="http://cloud.fixture" if cloud_retry else "http://fixture.invalid",
        chat_url=(
            "http://cloud.fixture/v1/chat/completions"
            if cloud_retry else "http://fixture.invalid/v1/chat/completions"
        ),
        api_key="",
        supports_validation=not cloud_retry,
    )
    mlx_runtime_config = SimpleNamespace(
        provider="mlx",
        model="local-fixture-model",
        base_url="http://local.fixture",
        chat_url="http://local.fixture/v1/chat/completions",
        api_key="",
        supports_validation=True,
    )
    state = SimpleNamespace(
        reranker_available=False,
        reranker_cls=None,
        llm_semaphore=asyncio.Semaphore(1),
        metrics_cache={},
        crag_stats={"no_data": 0, "hallucination": 0, "verified": 0},
        chat_metrics={
            "latency_search": [],
            "latency_gen": [],
            "tokens": [],
            "crag_fail": 0,
        },
    )

    from proxy.services import tool_harness_service

    def fixture_harness(**kwargs):
        captured_web_configs.append(kwargs.get("web_config"))
        return ExecutorBackedHarness()

    monkeypatch.setattr(tool_harness_service, "harness", fixture_harness)
    if active_web_research:
        monkeypatch.setenv("LES_WEB_SEARCH_MODE", "extended")
        monkeypatch.setenv("LES_SEARXNG_URL", "http://127.0.0.1:8888")
        monkeypatch.setenv("LES_CRAWL4AI_URL", "http://127.0.0.1:11235")
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        service,
        "rules_pre_verdict",
        lambda *_args, **_kwargs: pytest.fail("ordinary chat must not invoke semantic validator"),
    )
    monkeypatch.setattr(service, "maybe_answer_table_query", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "dataset_memory_prompt_excerpt", lambda *_a, **_k: "")
    active_transport = None
    active_connection = None
    if active:
        from proxy.services.canonical_route_service import (
            CanonicalRouteDecision,
            CanonicalRouteMode,
        )
        from proxy.services.model_connection_contracts import ConnectionLocality, ConnectionRole
        from proxy.services.openai_compatible_transport_service import InferenceResponse

        active_connection = SimpleNamespace(
            connection_id="conn:active",
            revision_id="conn:active:r3",
            display_name="Active fixture",
            model_id="active-model",
            locality=ConnectionLocality.LOOPBACK,
            base_url="http://127.0.0.1:1919/v1",
            secret_ref=None,
            effective_preset=_governor_preset(
                # Positive handoff cases need both source rows and whole cards:
                # truthful markers add 392 wire chars; target declarations add
                # shared instruction framing. Keep whole-card handoff assertions.
                # Exact capacity rejection is covered by the marker boundary test.
                input_tokens=(7500 if scenario in {
                    "active_model_rag_result", "active_model_rag_recovery",
                } else 6000),
                preset_id="active-preset",
            ),
        )
        if output_budgets:
            from proxy.services import freetoken_cache_profile_service as cache_profiles

            active_connection.model_id = "Qwen3.6-35B"
            active_connection.extension_type = "freetoken"
            active_connection.requested_context_tokens = 65536
            # The saved preset is deliberately stale. The real chat must resolve
            # the observed KV, then reapply the immutable profile budgets.
            monkeypatch.setattr(
                cache_profiles, "align_freetoken_cache_for_turn",
                lambda *_args, **_kwargs: {"status": "aligned", "effective_kv_tokens": 65536,
                                          "desired_kv_tokens": 65536},
            )
            monkeypatch.delenv("LES_CHAT_MODEL_RAG_QUERY_MAX_TOKENS", raising=False)

        class ActiveResolver:
            def resolve(self, role, **_kwargs):
                assert role is ConnectionRole.ANSWER
                return active_connection

            def resolve_fallback(self, *_args, **_kwargs):
                raise AssertionError("fallback must not be used")

        class ActiveTransport:
            def __init__(self):
                self.revisions = []
                self.requests = []
                if active_web_research:
                    self.responses = [
                        InferenceResponse(
                            text="",
                            tool_calls=(
                                {
                                    "id": "web-search-1",
                                    "type": "function",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": '{"q":"цены цемента и арматуры"}',
                                    },
                                },
                            ),
                            finish_reason="tool_calls",
                            usage={},
                        ),
                        InferenceResponse(
                            text="",
                            tool_calls=(
                                {
                                    "id": "web-read-1",
                                    "type": "function",
                                    "function": {
                                        "name": "web_read",
                                        "arguments": '{"url":"https://public.example/materials"}',
                                    },
                                },
                            ),
                            finish_reason="tool_calls",
                            usage={},
                        ),
                        InferenceResponse(
                            text="Исследование завершено",
                            tool_calls=(),
                            finish_reason="stop",
                            usage={},
                        ),
                        InferenceResponse(
                            text="Цемент — 650 руб.; арматура — 72 000 руб./т.",
                            tool_calls=(),
                            finish_reason="stop",
                            usage={"completion_tokens": 12},
                        ),
                    ]
                elif model_rag_result:
                    self.responses = [
                        InferenceResponse(
                            text=(
                                "монтаж шкафа управления\n"
                                "прокладка контрольного кабеля"
                            ),
                            tool_calls=(),
                            finish_reason="stop",
                            usage={},
                        ),
                        InferenceResponse(
                            text=(
                                "active visible answer\n\n"
                                "| source_row | section | title | unit | quantity | norm_code | analogue | coverage | coefficient | evidence_refs |\n"
                                "|---:|---|---|---|---:|---|---|---|---:|---|\n"
                                "| 1 | ЭОМ | монтаж шкафа управления | шт. | 2 | ГЭСНм08-02-401-01 | "
                                "Монтаж оборудования по найденной карточке нормы | прямое соответствие | | Q1.H1 |\n"
                                "\nartifact_kind: lsr"
                            ),
                            tool_calls=(),
                            finish_reason="stop",
                            usage={"completion_tokens": 5},
                        ),
                    ]
                else:
                    self.responses = [
                        InferenceResponse(
                            text="",
                            tool_calls=(
                                (
                                    {"id": "workbook-call-1", "type": "function", "function": {"name": "build_vor_workbook", "arguments": '{"attachment_id":"read_123456abcdef"}'} },
                                    {"id": "workbook-call-2", "type": "function", "function": {"name": "build_vor_workbook", "arguments": '{"attachment_id":"read_123456abcdef"}'} },
                                )
                                if rejected_workbook
                                    else ({"id": "workbook-call-1", "type": "function", "function": {"name": "build_vor_workbook", "arguments": ('{"attachment_id":"read_123456abcdef","question":"C:/private/les/SECRET_TRACE_TOKEN"}' if scenario == "active_workbook_private_arg" else '{"attachment_id":"read_123456abcdef"}')} },)
                            ) if active_workbook else (
                                {"id": "c1", "type": "function", "function": {"name": "read_source", "arguments": '{"doc_id":"d1"}'}},
                                {"id": "c2", "type": "function", "function": {"name": "read_source", "arguments": '{"doc_id":"d2"}'}},
                            ),
                            finish_reason="tool_calls",
                            usage={},
                        ),
                        InferenceResponse(
                            text=(
                                '{"calls":[]}'
                                if rejected_workbook or not active_workbook
                                else "active visible answer"
                            ),
                            tool_calls=(),
                            finish_reason="stop",
                            usage={"completion_tokens": 5},
                        ),
                        InferenceResponse(
                            text="active visible answer",
                            tool_calls=(),
                            finish_reason="stop",
                            usage={"completion_tokens": 5},
                        ),
                    ]

            async def complete(self, connection, _request):
                self.revisions.append(connection.revision_id)
                self.requests.append(_request)
                return self.responses.pop(0)

        active_transport = ActiveTransport()
        monkeypatch.setattr(
            service,
            "resolve_canonical_route",
            lambda **_kwargs: CanonicalRouteDecision(
                requested=(
                    CanonicalRouteMode.SHADOW
                    if candidate_acceptance
                    else CanonicalRouteMode.ACTIVE
                ),
                effective=(
                    CanonicalRouteMode.SHADOW
                    if candidate_acceptance
                    else CanonicalRouteMode.ACTIVE
                ),
                source="test",
                reason=("receipt_missing" if candidate_acceptance else "exact_test_receipt"),
                restart_required=False,
            ),
        )
    elif scenario == "legacy_workbook":
        from proxy.services.canonical_route_service import (
            CanonicalRouteDecision,
            CanonicalRouteMode,
        )

        monkeypatch.setattr(
            service,
            "resolve_canonical_route",
            lambda **_kwargs: CanonicalRouteDecision(
                requested=CanonicalRouteMode.LEGACY,
                effective=CanonicalRouteMode.LEGACY,
                source="test",
                reason="explicit_legacy",
                restart_required=False,
            ),
        )
    if cloud_retry:
        monkeypatch.setattr(
            service,
            "decide_provider",
            lambda *_a, **_k: SimpleNamespace(
                downgraded=False,
                sensitivity="P0",
                reason="fixture cloud route",
            ),
        )
        if fallback_budgets:
            from dataclasses import replace
            from proxy.services.model_execution_preset_service import apply_output_budget_policy

            def fallback_budget_preset(*, provider, operator=None, **_kwargs):
                preset = replace(
                    _governor_preset(input_tokens=12000 if provider == "openai" else 6000,
                                     preset_id="cloud-large" if provider == "openai" else "local-restrictive"),
                    generation_reserve_tokens=1200, output_capacity_observed=provider == "openai",
                )
                return apply_output_budget_policy(preset, operator)

            monkeypatch.setattr(service, "resolve_transport_execution_profile", fallback_budget_preset)
        else:
            monkeypatch.setattr(
                service,
                "resolve_transport_execution_profile",
                lambda *, provider, **_kwargs: _governor_preset(
                    input_tokens=12_000 if provider == "openai" else 6_000,
                    preset_id="cloud-large" if provider == "openai" else "local-restrictive",
                ),
            )
    if selector_overflow:
        original_govern = service.govern_inference_messages

        def overflow_selector(**kwargs):
            if kwargs.get("shortlist"):
                raise ContextRequiredSectionOverflow(
                    object_ids=("profile:bound", "request:current"),
                    budget=10,
                    required_tokens=11,
                )
            return original_govern(**kwargs)

        monkeypatch.setattr(service, "govern_inference_messages", overflow_selector)

    def save_history(**row):
        history_rows.append(row)
        return "history-1"

    request = service.EvidenceRequestContext(
        req=SimpleNamespace(
            question=(
                "Найди текущие цены цемента и арматуры"
                if active_web_research
                else "Собери ЛСР; ВОР не создавай"
                if model_rag_result
                else "Проверь документы"
            ),
            mode="agent" if active_web_research else "estimator" if model_rag_result else "rag",
            response_length="short",
            output_directive="",
            session_id="session-1",
            dataset_filter=None,
                project_id=0,
                attachment_id="read_123456abcdef" if workbook_profile else None,
                attachment_context=(
                    "Строка 1: монтаж шкафа управления — 2 шт."
                    if model_rag_result
                    else ""
                ),
            candidate_acceptance=candidate_acceptance,
            reranker_enabled=None,
        ),
        dataset_ids=None if scenario == "normal_unscoped" else ["selected"],
        effective_dataset_filter="",
        resolved_dataset_names=[],
        dataset_name_by_id={},
        query_route_payload={"channel": "rag"},
        target_doc_filter=[],
        target_file_ref=None,
        topic_doc_filter=[],
        topic_retrieval_plan=None,
        inventory_requested=False,
        study_requested=False,
        memory_block="",
        session_block="",
        class_suggestions=[],
        use_semantic_cache=False,
        use_validation=False,
        validation_skip_reason="test",
        route=SimpleNamespace(intent="rag"),
        table_result=None,
        request_started_at=1.0,
        profile_snapshot={
            "revision_id": "fixture-profile:1",
            "mode": "agent" if active_web_research else "estimator" if model_rag_result else "rag",
            "tools": (
                ["web_search", "web_read"]
                if active_web_research
                else ["search_sources", "build_lsr_workbook", "build_vor_workbook"]
                if model_rag_result
                else ["build_vor_workbook" if workbook_profile else "read_source"]
            ),
            "rag_policy": (
                {
                    "iterative": True,
                    "system_datasets": ["smeta"],
                    "model_authored_initial_query": True,
                }
                if model_rag_result
                else {"iterative": False}
            ),
            "prompt_text": "Answer only from evidence.",
            "model_policy": ({"query_output_tokens": 16000, "answer_output_tokens": 24000,
                              "reasoning_enabled": True, "temperature": 0.15}
                             if output_budgets else {"query_output_tokens": 700, "answer_output_tokens": 9000}
                             if fallback_budgets else {}),
        },
    )

    def retrieve_fixture(**kwargs):
        if not model_rag_result:
            return _async_value(FakeRetrieval())
        pytest.fail("estimator model-RAG must not call the general les_rag retriever")

    def retrieve_smeta_fixture(query, *, limit):
        assert limit == 6
        rag_queries.append(query)
        return {
            "backend": "typed_sqlite_fts+smeta_norm_qdrant_hybrid",
            "cards": [
                {
                    "norm_code": "ГЭСНм08-02-401-01",
                    "title": f"Карточка нормы для {query}",
                    "measure_unit": "шт.",
                    "work_steps": ["Монтаж оборудования"],
                    "source_ref": f"fsnb#query={len(rag_queries)}",
                }
            ],
            "retrieval_trace": {
                "rag": {
                    "status": "ok",
                    "collection": "les_smeta_norm_cards",
                    "retrieval_channels": ["dense", "bm25_sparse"],
                    "fusion": "rrf",
                }
            },
        }

    monkeypatch.setattr(service, "retrieve_smeta_norm_cards", retrieve_smeta_fixture)

    runtime = service.EvidenceRuntimeDeps(
        state=state,
        rag_backend=SimpleNamespace(collection_name="fixture"),
        cache=SimpleNamespace(),
        cache_embedding=None,
        cache_marker="miss",
        cache_scope="",
        assistant_text=lambda message: str(message.get("content") or ""),
        augment_model_tool_args=lambda call, **_kwargs: call,
        chat_model_final_answer=lambda _answer, status: ("rewritten by code", status, {}),
        cloud_body_for_model=lambda body, *_args: body,
        compact_tool_result_for_prompt=lambda item, **_kwargs: item,
        dataset_ids_from_chunks=lambda _chunks: [],
        dataset_sensitivities=lambda _ids: [],
        env_bool=lambda _key, default=False: default,
        env_float=lambda _key, default=0.0: default,
        env_int=lambda _key, default=0: default,
        expand_context_windows=lambda chunks, *_args, **_kwargs: FakeWindows(chunks),
        format_tool_results_for_model=lambda rows: json.dumps(rows, ensure_ascii=False),
        generation_token_budget=lambda **_kwargs: 128,
        llm_runtime=lambda: runtime_config,
        local_context_budget=lambda **_kwargs: {
            "focus_max_chunks": 0,
            "context_max_chunks": 0,
            "context_chars_limit": 4000,
            "context_window_chars": 1000,
        },
        mlx_runtime=lambda: mlx_runtime_config if cloud_retry else runtime_config,
        names_for_dataset_ids=lambda *_args: [],
        notebook_study_validation_status=lambda status, **_kwargs: status,
        ollama_native_complete=lambda *_args, **_kwargs: None,
        parse_model_tool_calls=(
            lambda raw, *_args, **_kwargs: (
                    [{"tool": "build_vor_workbook", "args": {"attachment_id": "read_123456abcdef"}}]
                        if workbook_profile and not active
                        else json.loads(raw).get("calls", [])
                        if str(raw).lstrip().startswith("{")
                        else []
                )
            ),
        prepare_notebook_reader_memory=lambda *_args, **_kwargs: None,
        record_cloud_cost=lambda *_args, **_kwargs: None,
        retrieve_chat_chunks=retrieve_fixture,
        source_excerpts=lambda *_args, **_kwargs: [],
        table_query_response=lambda **_kwargs: None,
        cloud_fallback_models=lambda runtime: [runtime.model] if cloud_retry else [],
        cloud_model_timeout=lambda: 1.0,
        model_connection_resolver=(
            (lambda: (ActiveResolver(), object())) if active else None
        ),
        model_connection_transport=(
            (lambda _client, _secret_store: active_transport) if active else None
        ),
        workbook_tool_executor=(
            (lambda call, context, progress: _rejected_workbook_execution(call, workbook_executor_calls))
            if rejected_workbook
            else (
                (
                    lambda call, context, progress: (
                        _rejected_workbook_execution(call, workbook_executor_calls)
                        if model_rag_recovery and call.get("tool") == "build_vor_workbook"
                        else _tracked_workbook_execution(
                            call, context, progress, progress_events, workbook_executor_calls
                        )
                    )
                )
                if active_workbook else None
            )
        ),
    )
    boundary = service.ResponseBoundary(
        save_chat_history=save_history,
        token_sink=(lambda event: _async_append(progress_events, event)) if active_workbook else None,
        version_stamp=lambda: {},
    )

    if application_setup is not None:
        return await application_setup(request, runtime, boundary)

    if selector_overflow:
        with pytest.raises(service.HTTPException) as error:
            await service.run_chat_evidence_application(request, runtime, boundary)
        assert error.value.status_code == 422
        assert error.value.detail["code"] == "CONTEXT_REQUIRED_SECTION_OVERFLOW"
        assert model_calls == []
        assert history_rows == []
        assert protected_hash() == before_protected
        return

    result = await service.run_chat_evidence_application(request, runtime, boundary)

    if output_budgets and not model_rag_result:
        assert active_transport.requests[-1].max_output_tokens == 24000
        trace = history_rows[0]["retrieval_trace"]
        assert trace["model_execution_profile"]["answer_output_tokens"]["effective"] == 24000
        packet = next(call for call in trace["context_governor"]["calls"] if call["purpose"] == "answer")
        assert packet["generation_reserve_tokens"] == 24000
        assert packet["input_budget_tokens"] == 65536 - 24000 - 2048

    after_protected = protected_hash()
    if active_web_research:
        expected_answer = "Цемент — 650 руб.; арматура — 72 000 руб./т."
        assert result["answer"].encode("utf-8") == expected_answer.encode("utf-8")
        assert history_rows[0]["answer"].encode("utf-8") == expected_answer.encode("utf-8")
        assert [call[0] for call in legacy_calls] == ["web_search", "web_read"]
        assert legacy_calls[1][1] == {"url": "https://public.example/materials"}
        assert captured_web_configs[0].mode == "extended"
        tool_loop = history_rows[0]["retrieval_trace"]["tool_loop"]
        assert [call["tool"] for call in tool_loop["selected_calls"]] == [
            "web_search",
            "web_read",
        ]
        assert tool_loop["web_research"]["mode"] == "extended"
        assert result["source_map"][0]["locator"]["url"] == (
            "https://public.example/materials"
        )
        assert result["source_map"][0]["snippet"].startswith("Цемент — 650")
        assert len(active_transport.requests) == 4
        assert "Цемент — 650" in str(active_transport.requests[3].messages)
        return
    if model_rag_result:
        assert result["answer"].startswith("active visible answer\n\n| source_row |")
        assert rag_queries == [
            "монтаж шкафа управления",
            "прокладка контрольного кабеля",
        ]
        assert "Собери ЛСР" not in rag_queries
        packaged = workbook_executor_calls[-1]["args"]["decisions"]
        assert len(packaged) == 1
        for field, value in exact_decisions[0].items():
            assert packaged[0].get(field) == value
        assert workbook_executor_calls[-1]["tool"] == "build_lsr_workbook"
        assert active_transport.revisions[:2] == ["conn:active:r3"] * 2
        assert active_transport.requests[0].tools == ()
        assert active_transport.requests[1].tools == ()
        assert "Строка 1: монтаж шкафа управления — 2 шт." in str(
            active_transport.requests[0].messages
        )
        final_messages = str(active_transport.requests[1].messages)
        assert "Строка 1: монтаж шкафа управления — 2 шт." in final_messages
        assert "Карточка нормы для монтаж шкафа управления" in final_messages
        assert "Карточка нормы для прокладка контрольного кабеля" in final_messages
        assert "[Поисковый запрос Q1] монтаж шкафа управления" in final_messages
        assert "Q1.H1" in final_messages
        assert "[Поисковый запрос Q2] прокладка контрольного кабеля" in final_messages
        assert "Q2.H1" in final_messages
        first_messages = str(active_transport.requests[0].messages)
        assert "Строка 1: монтаж шкафа управления — 2 шт." in first_messages
        assert "можешь объявить artifact_kind" in first_messages
        # Both supported query carriers remain explicit; the technical stage
        # must not inherit the final-answer persona/table instructions.
        assert "JSON-конверт" in first_messages
        assert "При выборе дословных строк запросов" in first_messages
        assert "каждый запрос — отдельной строкой" in first_messages
        assert service._MODEL_RAG_QUERY_PHASE_INSTRUCTION in first_messages
        assert "Число запросов определяешь ты по представленным операциям" in first_messages
        assert "по фактически представленным операциям и данным" in first_messages
        assert "сохраняй язык и профессиональную терминологию исходных строк" in first_messages
        assert "не переводи и не транслитерируй" in first_messages
        assert "Код не выбирает норму и не меняет ячейки" in final_messages
        assert history_rows[0]["retrieval_trace"]["status"] == "model_driven"
        assert history_rows[0]["retrieval_trace"]["reason"] == (
            "awaiting_model_authored_query"
        )
        tool_loop = history_rows[0]["retrieval_trace"]["tool_loop"]
        assert tool_loop["schema"] == "les_model_rag_batch_v1"
        assert tool_loop["model_queries"] == rag_queries
        assert tool_loop["evidence_groups"] == ["Q1", "Q2"]
        assert history_rows[0]["sources"] == ["smeta_norm_cards.v1"]
        manifest = history_rows[0]["retrieval_trace"]["evidence_manifest"]
        assert manifest["schema"] == "les.chat-evidence-manifest.v1"
        assert [item["id"] for item in manifest["model_visible"]] == ["Q1.H1", "Q2.H1"]
        assert manifest["cited_ids"] == ["Q1.H1"]
        assert history_rows[0]["retrieval_trace"]["source_map"] == result["source_map"]
        assert "rounds" not in tool_loop
        assert len(active_transport.requests) == 2
        if output_budgets:
            assert [call.max_output_tokens for call in active_transport.requests] == [16000, 24000]
            assert [call.temperature for call in active_transport.requests] == [0.15, 0.15]
            assert all(call.reasoning_enabled is True for call in active_transport.requests)
            assert active_connection.requested_context_tokens == 65536
            assert active_connection.effective_preset.input_token_limit == 6000
            trace = history_rows[0]["retrieval_trace"]
            assert trace["model_execution_profile"]["context_input_tokens"]["effective"] == 65536
            assert trace["model_execution_profile"]["query_output_tokens"]["effective"] == 16000
            assert trace["model_execution_profile"]["answer_output_tokens"]["effective"] == 24000
            calls = trace["context_governor"]["calls"]
            query_packet = next(call for call in calls if call["purpose"] == "model_rag_queries")
            answer_packet = next(call for call in calls if call["purpose"] == "answer")
            assert query_packet["generation_reserve_tokens"] == 16000
            assert answer_packet["generation_reserve_tokens"] == 24000
            assert query_packet["input_budget_tokens"] == 65536 - 16000 - 2048
            assert answer_packet["input_budget_tokens"] == 65536 - 24000 - 2048
        assert history_rows[0]["retrieval_trace"]["norm_quality_gate"] == {
            "schema": "les.lsr-norm-quality-gate.v1",
            "status": "not_run",
            "reason": "terminal_model_result_preserved",
            "norms_status": "model_authored",
        }
        history_wire = json.dumps(history_rows[0], ensure_ascii=False).casefold()
        # This numeric provenance diagnostic is not a confirmation action or
        # gate. Keep rejecting every other confirmation token in the payload.
        diagnostic = '"normative_generation_unconfirmed_rows": 0'
        assert diagnostic in history_wire
        assert "confirm" not in history_wire.replace(diagnostic, "")
        return
    if inactive_workbook:
        assert result["answer"] == "legacy visible answer"
        assert shortlist_policies == []
        assert shadow_calls == []
        assert legacy_calls == []
        assert executor_codes == []
        assert after_protected == before_protected
        return
    if active:
        assert result["answer"] == "active visible answer"
        assert result["model_connection"] == {
            "connection_id": "conn:active",
            "revision_id": "conn:active:r3",
            "display_name": "Active fixture",
            "model_id": "Qwen3.6-35B" if output_budgets else "active-model",
                "locality": "loopback",
                "fallback_used": False,
                "pending_tool_calls": 0,
        }
        assert result["source_scope"] == {
            "requested": ["selected"],
            "resolved": ["selected"],
            "used": [],
            "used_names": [],
        }
        assert active_transport.revisions == ["conn:active:r3", "conn:active:r3"] + (
            ["conn:active:r3"]
            if rejected_workbook or not active_workbook
            else []
        )
        if active_workbook:
            assert len(workbook_executor_calls) == (2 if rejected_workbook else 1)
            if rejected_workbook:
                assert "artifact" not in result
                assert history_rows[0]["retrieval_trace"]["tool_loop"]["stop_reason"] == "model_stop"
                return
            assert result["artifact"]["revision_id"] == "rev-2"
            assert result["attachment_retry"]["attachment_id"] == "read_123456abcdef"
            assert history_rows[0]["artifact"]["revision_id"] == "rev-2"
            if scenario == "active_workbook_private_arg":
                selected_calls = result["retrieval_trace"]["tool_loop"]["selected_calls"]
                assert selected_calls == history_rows[0]["retrieval_trace"]["tool_loop"]["selected_calls"]
                assert selected_calls[0]["tool"] == "build_vor_workbook"
                assert selected_calls[0]["call_id"] == "workbook-call-1"
                assert len(selected_calls[0]["arguments_sha256"]) == 64
                assert "args" not in selected_calls[0]
                assert "SECRET_TRACE_TOKEN" not in json.dumps(result, ensure_ascii=False)
                assert "C:/private/les" not in json.dumps(history_rows[0], ensure_ascii=False)
            assert any(event.get("event") == "tool_progress" for event in progress_events)
            assert legacy_calls == []
            if candidate_acceptance:
                trace = history_rows[0]["retrieval_trace"]
                assert trace["canonical_route"]["effective"] == "shadow"
                assert trace["candidate_acceptance"] == {
                    "enabled": True,
                    "execution_mode": "active",
                    "promotion_receipt": "not_used",
                    "state_root": "process_cwd_isolated",
                }
                assert trace["route_comparison"]["candidate_acceptance"] is True
                assert trace["route_comparison"]["legacy_output_authoritative"] is False
        else:
            assert [call[1]["doc_id"] for call in legacy_calls] == ["d1", "d2"]
        assert history_rows[0]["retrieval_trace"]["context_governor"]["preset_id"] == (
            "qwen-35b-extended" if output_budgets else "active-preset"
        )
        assert after_protected == before_protected
        return
    assert result["answer"] == "legacy visible answer"
    if cloud_retry:
        assert model_calls == [
            "selector",
            "selector",
            "cloud_final",
            "local_final",
            "local_final",
        ]
        if fallback_budgets:
            trace = history_rows[0]["retrieval_trace"]
            fallback_packet = next(call for call in trace["context_governor"]["calls"]
                                   if call["purpose"] == "answer_fallback")
            assert fallback_packet["generation_reserve_tokens"] == 1200
            assert trace["model_execution_profile"]["query_output_tokens"]["effective"] == 700
            assert trace["model_execution_profile"]["answer_output_tokens"]["effective"] == 1200
            assert "unobserved_capacity_default" in trace["model_execution_profile"]["answer_output_tokens"]["source"]
            assert trace["model_execution_profile"]["model_preset"]["requested"] == "local-fixture-model"
            local_bodies = [body for url, body in model_bodies if "local.fixture" in url]
            assert [body["max_tokens"] for body in local_bodies] == [1200, 1200]
        calls = history_rows[0]["retrieval_trace"]["context_governor"]["calls"]
        assert [call["purpose"] for call in calls] == [
            "tool_decision",
            "tool_decision",
            "answer",
            "answer_fallback",
            "answer",
        ]
        assert [call["preset_id"] for call in calls] == [
            "cloud-large",
            "cloud-large",
            "cloud-large",
            "local-restrictive",
            "local-restrictive",
        ]
        assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["persisted_effects"] == 0
        assert after_protected == before_protected
        return
    if scenario == "normal_unscoped":
        assert model_calls == ["final"]
        assert shortlist_policies == []
        assert shadow_calls == []
        assert executor_codes == []
        assert legacy_calls == []
        assert history_rows[0]["retrieval_trace"]["status"] == "skipped"
        assert history_rows[0]["retrieval_trace"]["reason"] == "scope_none"
        assert after_protected == before_protected
        return
    assert model_calls == ["selector", "selector", "final"]
    assert shortlist_policies == [
        {
            "mode": "rag",
            "allowed_tools": ["read_source"],
            "limit": 5,
            "dataset_ids": () if scenario == "normal_unscoped" else ("selected",),
            "workflow_phase": "research",
            "model_preset": "qwen-9b-restrictive",
            "runtime_available": frozenset({"read_source"}),
            "calls_remaining": 5,
            "result_chars_remaining": 35_000,
        }
    ]
    assert [call[1]["doc_id"] for call in shadow_calls] == ["d1"]
    assert executor_codes == [
        "TOOL_SCOPE_VIOLATION" if scenario == "normal_unscoped" else "TOOL_WOULD_EXECUTE"
    ]
    assert [call[1]["doc_id"] for call in legacy_calls] == ["d1", "d2"]
    assert len(history_rows) == 1
    assert history_rows[0]["answer"] == "legacy visible answer"
    assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["status"] == "error"
    assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["attempted_calls"] == 1
    assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["pending_calls"] == 1
    assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["persisted_effects"] == 0
    assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["profile_revision"] == "fixture-profile:1"
    assert history_rows[0]["retrieval_trace"]["route_comparison"] == {
        "schema": "les.canonical-route-comparison.v1",
        "requested": "shadow",
        "effective": "shadow",
        "legacy_output_authoritative": True,
        "same_request": True,
        "profile_revision": "fixture-profile:1",
        "canonical_provider_calls_added": 0,
        "persisted_effects": 0,
    }
    governor_trace = history_rows[0]["retrieval_trace"]["context_governor"]
    assert governor_trace["preset_id"] == "qwen-9b-restrictive"
    assert [call["purpose"] for call in governor_trace["calls"]] == [
        "tool_decision",
        "tool_decision",
        "answer",
    ]
    assert "Проверь документы" not in json.dumps(governor_trace, ensure_ascii=False)
    assert "legacy fixture" not in json.dumps(governor_trace, ensure_ascii=False)
    assert "secret shadow failure" not in str(history_rows[0])
    assert after_protected == before_protected


def test_workbook_projection_keeps_bounded_conflict_diagnostics():
    raw = {
        "schema": "les.workbook_tool_result.v1",
        "tool": "build_lsr_workbook",
        "status": "complete",
        "missing": ["row:2:unit_conflict"],
        "blockers": [],
        "artifact": {"revision_id": "rev-2"},
    }

    safe = service.safe_workbook_history_projection(raw)

    assert safe["status"] == "partial"
    assert safe["missing"] == ["row:2:unit_conflict"]
    assert safe["blockers"] == []


def test_workbook_projection_preserves_every_vor_source_error():
    errors = [f"source_quantity_mismatch:Архитектура!R{index}" for index in range(1, 319)]
    raw = {"schema": "les.workbook_tool_result.v1", "tool": "build_vor_workbook", "status": "complete",
           "missing": [], "blockers": [], "vor_source_errors": errors,
           "artifact": {"revision_id": "rev-vor"}}
    safe = service.safe_workbook_history_projection(raw)
    assert safe["vor_source_errors"] == errors
    assert safe["status"] == "partial"
    assert service.safe_workbook_history_projection(safe) == safe


def _lsr_tool_result_with_basis() -> dict:
    """One realistic ``build_lsr_workbook`` result for the carrying chain."""

    return {
        "schema": "les.workbook_tool_result.v1",
        "tool": "build_lsr_workbook",
        "status": "partial",
        "pricing_status": "priced_partial",
        "norms_status": "norms_selected_unverified",
        "missing": ["price_missing:01.7.07.24-0010"],
        "blockers": [],
        "calculated_positions": 0,
        "confirmed_amount": 0.0,
        "preliminary_amount": 0.0,
        "price_basis": {
            "requested": "",
            "requested_region": "",
            "requested_region_origin": "не указан",
            "contradictions": [],
            "actual_book": "sankt-peterburg_2kv2026",
            "actual_region": "Санкт-Петербург",
            "actual_quarter": "",
            "origin": "",
            "available_books": ["sankt-peterburg_2kv2026", "msk_3kv2026"],
            "match": "unspecified",
            "note": "Ценовая база в запросе и исходнике не указана.",
        },
        "price_gaps": [
            {
                "resource": "Кабель ВВГнг(А)-LS 3х2,5",
                "code": "01.7.07.24-0010",
                "quantity": 92,
                "unit": "м",
                "price_action": "price_missing",
                "required_source": "КАЦ",
                "action": (
                    "Задайте цену для Кабель ВВГнг(А)-LS 3х2,5 (01.7.07.24-0010) "
                    "в позиции 01.7.07.24-0010. Количество 92 м. Источник: КАЦ."
                ),
            }
        ],
        "norm_conflicts": [
            {
                "locator": "АР!R9",
                "code": "ГЭСНм8-02-101-01",
                "row_action": "Демонтаж",
                "norm_action": "Монтаж",
            }
        ],
        "artifact": {
            "artifact_id": "art-1",
            "revision_id": "rev-2",
            "revision_no": 2,
            "download_url": "/api/artifacts/rev-2/download",
            "source_scope": ["attachment:read_123456abcdef"],
            "decision_checkpoint_id": "cp-1",
            "filename": "lsr.xlsx",
            "artifact_kind": "lsr_workbook",
        },
        "checkpoint": {"checkpoint_id": "cp-1", "status": "complete"},
        "source": {"attachment_id": "read_123456abcdef", "sha256": "a" * 64},
    }


def test_projected_basis_and_conflicts_open_the_chat_readiness_block():
    """Task § 7 / § 10: the draft has to ask the questions it is blocked by.

    Build 816 shipped the readiness, the prompt and the projector, yet a live
    run of the big ВОР carried ``dimensions.prices.basis == {}`` because the
    history projection listed only identifiers.  This test walks the exact chain
    the chat route uses — projection → harvest → readiness → visible notice —
    and fails if any link drops the basis, the price holes or the reversed
    operation rows again.
    """

    harvested = service.harvest_workbook_tool_result(_lsr_tool_result_with_basis())
    assert harvested["price_basis"]["match"] == "unspecified"
    assert harvested["price_gaps"][0]["code"] == "01.7.07.24-0010"
    assert harvested["norm_conflicts"][0]["locator"] == "АР!R9"

    readiness = service.build_lsr_result_readiness(
        packaged=True,
        rows=[
            {
                "source_row": "АР!R9",
                "title": "Прокладка кабеля",
                "unit": "м",
                "quantity": 92,
                "norm_code": "ГЭСНм8-02-101-01",
                "norm_status": "EXACT",
            }
        ],
        missing=list(harvested.get("missing") or []),
        pricing_status=str(harvested.get("pricing_status") or ""),
        price_gaps=list(harvested.get("price_gaps") or []),
        norm_conflicts=list(harvested.get("norm_conflicts") or []),
        price_basis=dict(harvested.get("price_basis") or {}),
    )

    prices = readiness["dimensions"]["prices"]
    assert prices["basis"]["match"] == "unspecified"
    assert prices["complete"] is False
    assert prices["gaps"][0]["resource"] == "Кабель ВВГнг(А)-LS 3х2,5"
    norm_kinds = {
        str(item.get("kind") or "")
        for item in readiness["dimensions"]["norms"]["gaps"]
    }
    assert "reversed_action" in norm_kinds

    notice = service.format_lsr_readiness_notice(readiness, filename="lsr.xlsx")
    assert "Ценовая база" in notice

    from sovushka.pages.chat import lsr_price_basis_prompt

    prompt = lsr_price_basis_prompt(prices["basis"], books=("sankt-peterburg_2kv2026",))
    assert prompt["visible"] is True
    assert prompt["match"] == "unspecified"


def test_projected_basis_and_gaps_stay_bounded():
    """The same projection is the tool result the model reads back, so it is capped."""

    raw = _lsr_tool_result_with_basis()
    raw["price_gaps"] = [
        {
            "resource": f"Ресурс {index}",
            "code": f"01.7.07.24-{index:04d}",
            "action": "Длинный вопрос оператору. " * 80,
        }
        for index in range(120)
    ]
    raw["price_basis"]["available_books"] = [f"book-{index}" for index in range(200)]
    raw["norm_conflicts"] = [
        {"locator": f"АР!R{index}", "row_action": "Демонтаж", "norm_action": "Монтаж"}
        for index in range(120)
    ]

    safe = service.safe_workbook_history_projection(raw)

    assert len(safe["price_gaps"]) <= 40
    assert len(safe["norm_conflicts"]) <= 40
    assert len(safe["price_gaps"][0]["action"]) <= 400
    assert len(safe["price_basis"]["available_books"]) <= 40
    assert safe["price_basis"]["match"] == "unspecified"
    payload = json.dumps(safe, ensure_ascii=False)
    assert "private" not in payload
    assert len(payload) < 120_000


from proxy.services.attachment_source_catalog_service import (
    AttachmentSourceCatalog,
    CatalogRow,
)
from proxy.services.chat_evidence_application_service import (
    claim_or_join_sheet_pass,
    release_sheet_pass,
    sheet_pass_progress_counts,
    sheet_pass_progress_label,
    sheet_pass_should_run,
)


def _work_catalog(count: int) -> AttachmentSourceCatalog:
    rows = tuple(
        CatalogRow(
            locator=f"S!R{index}",
            sheet="S",
            excel_row=index,
            values=("работа", "шт", "1"),
            line=f"S!R{index} | работа | шт | 1",
            numbers=(1.0,),
            row_classification="work",
        )
        for index in range(2, 2 + count)
    )
    return AttachmentSourceCatalog(
        original_name="demo.xlsx",
        sheets=(("S", count),),
        rows=rows,
    )


def test_sheet_pass_runs_for_small_and_large_tabular_catalogs() -> None:
    small = _work_catalog(9)
    large = _work_catalog(35)
    assert sheet_pass_should_run(small, tabular_estimator_bound=True, model_driven=True) is True
    assert sheet_pass_should_run(large, tabular_estimator_bound=True, model_driven=True) is True
    assert sheet_pass_should_run(small, tabular_estimator_bound=True, model_driven=False) is False


def test_sheet_pass_progress_counts_rows_and_resume_prefix() -> None:
    assert sheet_pass_progress_label(
        "СКС", sheet_index=1, sheet_count=1, stage="поиск норм"
    ) == 'Лист «СКС» (1/1): поиск норм'
    assert sheet_pass_progress_label(
        "СКС",
        sheet_index=1,
        sheet_count=1,
        stage="поиск норм",
        resumed=True,
    ) == 'Продолжаю: Лист «СКС» (1/1): поиск норм'
    counts = sheet_pass_progress_counts(
        accepted_now=23,
        work_total=75,
        session_accepted_start=23,
        prior_elapsed_seconds=1500,
    )
    assert counts["completed"] == 23
    assert counts["total"] == 75
    assert counts["eta_completed"] == 0
    assert counts["eta_total"] == 52
    assert counts["remaining"] == 52
    assert counts["resumed"] is True
    assert counts["prior_elapsed_seconds"] == 1500.0
    source = inspect.getsource(service._execute_chat_evidence_application)
    loop = source[
        source.index("async def _emit_row_progress") : source.index("sheet_pass_done = True")
    ]
    assert "completed=sheet_index - 1" not in loop
    assert "sheet_pass_progress_counts" in loop
    assert "remaining_locators" in source
    assert "catalog_work_count" in source
    assert "claim_or_join_sheet_pass" in loop
    assert "owns_sheet_pass" in loop


@pytest.mark.asyncio
async def test_claim_or_join_sheet_pass_serializes_duplicate_continue() -> None:
    order: list[str] = []
    job_id = "job-overnight-1"
    service._LIVE_SHEET_PASS_GATES.pop(job_id, None)

    async def first() -> None:
        owns = await claim_or_join_sheet_pass(job_id)
        assert owns is True
        order.append("a-start")
        await asyncio.sleep(0.05)
        order.append("a-end")
        release_sheet_pass(job_id)

    async def second() -> None:
        await asyncio.sleep(0.01)
        owns = await claim_or_join_sheet_pass(job_id)
        order.append("b")
        assert owns is False

    try:
        await asyncio.gather(first(), second())
        assert order == ["a-start", "a-end", "b"]
    finally:
        release_sheet_pass(job_id)


def test_model_rag_result_reads_row_role_and_cited_conversion() -> None:
    answer = (
        "| source_row | row_role | work_row | title | unit | quantity | conversion_factor | conversion_source | open_gap | norm_code |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| СКС!R2 | work | СКС!R2 | Монтаж | упак | 2 | 12 | упаковка 12 шт |  | 10-06-024-01 |\n"
        "| СКС!R3 | resource | СКС!R2 | Кабель | м | 40 |  |  |  |  |\n"
    )
    parsed = service.parse_model_rag_result(answer)
    assert parsed is not None
    _text, rows = parsed
    assert rows[0]["row_role"] == "work"
    assert rows[0]["conversion_factor"] == 12
    assert rows[0]["conversion_source"] == "упаковка 12 шт"
    assert rows[1]["row_role"] == "resource"
    assert rows[1]["work_row"] == "СКС!R2"
    assert "open_gap" not in rows[0] or not rows[0].get("open_gap")


def test_sheet_pass_source_keeps_model_rows_and_does_not_rewrite() -> None:
    source = inspect.getsource(service._execute_chat_evidence_application)
    start = source.index("async def _sheet_pass_llm")
    end = source.index("sheet_pass_done = True")
    loop = source[start:end]
    assert "apply_verifier_table" not in loop
    assert "lsr_verifier_instruction()" not in loop
    assert "mark_research_exhausted" not in loop
    assert "merge_model_rag_rows" in loop
    assert "structurally_complete_source_keys" in loop
    assert "record_search_cache" in loop
    assert "research_job_service.pause" in loop


def test_sheet_pass_empty_search_is_not_packet_failure() -> None:
    assert service.model_search_result_blocks_packet({"status": "ok"}) is False
    assert service.model_search_result_blocks_packet({"status": "missing"}) is False
    assert service.model_search_result_blocks_packet({"status": "MISSING"}) is False
    assert service.model_search_result_blocks_packet({"status": "blocked"}) is True
    assert service.model_search_result_blocks_packet({"status": "error"}) is True
    assert service.model_search_result_blocks_packet({}) is True
    assert service.model_search_result_blocks_packet(None) is True
    source = inspect.getsource(service._execute_chat_evidence_application)
    loop = source[
        source.index("search_blocked = False") : source.index("if search_blocked:")
    ]
    assert "model_search_result_blocks_packet" in loop
    assert '!= "ok"' not in loop
    oneshot = source[
        source.index("blocked_queries = [") : source.index("if blocked_queries:")
    ]
    assert "model_search_result_blocks_packet" in oneshot
    assert '!= "ok"' not in oneshot


def test_restore_empty_search_hits_counts_as_cached() -> None:
    hits = service.restore_query_hits_from_cache(
        ["нет карточек"],
        {"нет карточек": []},
    )
    assert hits == [("нет карточек", ())]


def test_cache_contract_rejects_legacy_and_foreign_hits_including_empty_results():
    cache = {"legacy": [], "foreign": {"contract": "expanded-v0", "hits": []},
             "current": {"contract": "literal-v1", "hits": []}}
    assert service.restore_query_hits_from_cache(list(cache), cache, cache_contract="literal-v1") == [("current", ())]


@pytest.mark.asyncio
async def test_held_page_refreshes_obsolete_cache_without_a_new_model_query():
    from proxy.services.model_research_tool_service import ModelResearchToolResult
    calls = []
    class Tools:
        cache_contract = "literal-v1"
        async def execute(self, call):
            calls.append(call)
            return ModelResearchToolResult(payload={"status": "missing"}, chunks=())
    cache = {"model-declared tail": [{"content": "expanded result", "meta": {}}]}
    trace = {}
    hits, updates, blocked = await service.restore_or_refresh_held_query_hits(
        ["model-declared tail"], cache, model_research_tools=Tools(), retrieval_trace=trace, hits_per_query=6)
    assert calls == [{"tool": "search_sources", "args": {"q": "model-declared tail"}}]
    assert hits == [("model-declared tail", ())] and updates == {"model-declared tail": []} and not blocked
    assert service.restore_query_hits_from_cache(list(cache), cache, cache_contract="literal-v1") == hits
    assert trace["actual_model_calls"]["search_executions"] == 1
    assert trace["actual_model_calls"]["calls"] == []
    again, updates, blocked = await service.restore_or_refresh_held_query_hits(
        ["model-declared tail"], cache, model_research_tools=Tools(), retrieval_trace=trace, hits_per_query=6)
    assert again == hits and updates == {} and len(calls) == 1 and not blocked


@pytest.mark.asyncio
async def test_held_cache_refresh_infrastructure_failure_is_not_missing_evidence():
    from proxy.services.model_research_tool_service import ModelResearchToolResult
    class Tools:
        cache_contract = "literal-v1"
        async def execute(self, call):
            return ModelResearchToolResult(payload={"status": "blocked"})
    cache = {"pending": []}
    hits, updates, blocked = await service.restore_or_refresh_held_query_hits(
        ["pending"], cache, model_research_tools=Tools(), retrieval_trace={}, hits_per_query=6)
    assert hits == [] and updates == {} and blocked == "blocked"
    assert cache == {"pending": []}


def test_unstructured_notice_distinguishes_empty_sheet_pass() -> None:
    parse_miss = service.format_lsr_unstructured_notice()
    assert "наименования" in parse_miss
    empty = service.format_lsr_unstructured_notice(sheet_pass_empty=True)
    assert "таблица строк не получена" in empty
    assert "наименования" not in empty
    source = inspect.getsource(service._execute_chat_evidence_application)
    assert "sheet_pass_empty=bool(sheet_pass_done)" in source


def test_empty_retrieval_is_not_stamped_while_awaiting_model_queries() -> None:
    trace: dict = {}
    service.stamp_empty_retrieval(trace, model_driven=True, chunks=[])
    assert "empty_retrieval" not in trace
    service.stamp_empty_retrieval(trace, model_driven=False, chunks=[])
    assert trace["empty_retrieval"]["schema"] == "empty_retrieval_model_first_v1"
    service.finalize_actual_retrieval_emptiness(
        trace,
        evidence_count=4,
        searches_executed=2,
        search_hits=4,
    )
    assert "empty_retrieval" not in trace


def test_actual_model_and_search_calls_are_recorded() -> None:
    trace: dict = {}
    service.append_actual_model_call(
        trace,
        purpose="model_rag_sheet_queries",
        finish_reason="stop",
        completion_tokens=12,
    )
    service.append_actual_search(trace, cached=False, hit_count=6)
    service.append_actual_search(trace, cached=True, hit_count=6)
    bucket = trace["actual_model_calls"]
    assert bucket["schema"] == service.ACTUAL_MODEL_CALLS_SCHEMA
    assert bucket["calls"][0]["purpose"] == "model_rag_sheet_queries"
    assert bucket["search_executions"] == 1
    assert bucket["search_cache_hits"] == 1
    assert bucket["search_hits"] == 12


def test_packaged_notice_uses_three_readiness_dimensions() -> None:
    notice = service.format_lsr_packaged_notice(
        filename="LSR.xlsx",
        status="partial",
        pricing_status="priced_partial",
        norms_status="model_authored",
        missing=["price_missing:10-01-001-01"],
        readiness=service.build_lsr_result_readiness(
            packaged=True,
            rows=[{"source_row": "СКС!R2", "norm_code": "", "norm_status": "MISSING"}],
            missing=["price_missing:10-01-001-01"],
            pricing_status="priced_partial",
        ),
    )
    assert "независимую проверку" not in notice
    assert "Файл:" in notice
    assert "Нормы:" in notice
    assert "Цены:" in notice


def test_restore_query_hits_from_cache_skips_search_payload() -> None:
    hits = service.restore_query_hits_from_cache(
        ["монтаж шкафа", "нет в кэше"],
        {
            "монтаж шкафа": [
                {
                    "content": "карточка",
                    "doc_id": "c1",
                    "doc_name": "ФСНБ",
                    "score": 0.9,
                    "meta": {"norm_code": "10-01-001-01"},
                }
            ]
        },
    )
    assert len(hits) == 1
    assert hits[0][0] == "монтаж шкафа"
    assert hits[0][1][0].content == "карточка"


async def _async_value(value):
    return value


def test_stage_g_evidence_meta_names_query_and_attempt_scopes_ids():
    query_hits = [
        (
            "\u041b\u043e\u0442\u043e\u043a \u043c\u0435\u0442\u0430\u043b\u043b\u0438\u0447\u0435\u0441\u043a\u0438\u0439 \u0448\u0442\u0430\u043c\u043f\u043e\u0432\u0430\u043d\u043d\u044b\u0439 \u0434\u043e 200 \u043c\u043c",
            [
                SimpleNamespace(
                    content="\u0428\u0438\u0444\u0440: \u0413\u042d\u0421\u041d\u043c08-02-395-01 \u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435: \u041b\u043e\u0442\u043a\u0438",
                    doc_id="doc-tray-1",
                    doc_name="smeta_norm_cards.v1",
                    score=1.0,
                    meta={},
                )
            ],
        )
    ]
    _groups, chunks, omitted = service.build_model_rag_evidence_groups(
        query_hits,
        max_chars=4000,
        hits_per_query=4,
        evidence_namespace="packet_attempt_one:a1",
    )
    assert omitted == []
    meta = chunks[0].meta
    assert meta["model_query_text"] == query_hits[0][0]
    assert meta["evidence_namespace"] == "packet_attempt_one:a1"
    _g2, chunks2, _o2 = service.build_model_rag_evidence_groups(
        query_hits,
        max_chars=4000,
        hits_per_query=4,
        evidence_namespace="packet_attempt_one:a2",
    )
    # The same alias in two attempts of one packet must not collide.
    assert chunks2[0].meta["global_evidence_id"] != meta["global_evidence_id"]


def test_stage_g_provenance_check_flags_mismatch_without_touching_norm():
    query_hits = [
        (
            "\u041c\u043e\u043d\u0442\u0430\u0436 \u043e\u0431\u043e\u0440\u0443\u0434\u043e\u0432\u0430\u043d\u0438\u044f \u0434\u043e\u0441\u0442\u0443\u043f\u0430",
            [
                SimpleNamespace(
                    content="\u0428\u0438\u0444\u0440: \u0413\u042d\u0421\u041d\u043c08-02-384-02 \u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435: \u041a\u0430\u0431\u0435\u043b\u044c",
                    doc_id="doc-wifi-1",
                    doc_name="smeta_norm_cards.v1",
                    score=1.0,
                    meta={},
                )
            ],
        )
    ]
    _groups, chunks, _omitted = service.build_model_rag_evidence_groups(
        query_hits,
        max_chars=4000,
        hits_per_query=4,
        evidence_namespace="packet_probe",
    )
    row = {
        "source_row": "\u0421\u041a\u0421!R45",
        "norm_code": "\u0413\u042d\u0421\u041d\u043c10-10-006-01",
        "evidence_refs": ["Q1.H1", "Q9.H9"],
    }
    bound = service.bind_row_evidence_ids([row], chunks)
    check = bound[0]["_evidence_check"]
    assert bound[0]["norm_code"] == "\u0413\u042d\u0421\u041d\u043c10-10-006-01"
    assert check["code_not_in_refs"] is True
    assert check["cited"][0]["card"] == "\u0413\u042d\u0421\u041d\u043c08-02-384-02"
    assert check["cited"][0]["query"] == query_hits[0][0]
    assert check["unresolved_refs"] == ["Q9.H9"]
    # A matching citation must not be flagged.
    row_ok = {
        "source_row": "\u0421\u041a\u0421!R45",
        "norm_code": "\u0413\u042d\u0421\u041d\u043c08-02-384-02",
        "evidence_refs": ["Q1.H1"],
    }
    check_ok = service.bind_row_evidence_ids([row_ok], chunks)[0]["_evidence_check"]
    assert check_ok["code_not_in_refs"] is False
    # Rows without a norm carry no check at all.
    plain = service.bind_row_evidence_ids(
        [{"source_row": "\u0421\u041a\u0421!R47", "evidence_refs": ["Q1.H1"]}],
        chunks,
    )
    assert "_evidence_check" not in plain[0]


def test_stage_g_budget_omitted_cards_name_query_and_shifr():
    query_hits = [
        (
            "\u0448\u043a\u0430\u0444 42U",
            [
                SimpleNamespace(
                    content="\u0428\u0438\u0444\u0440: \u0413\u042d\u0421\u041d01-01-001-01 " + "\u0441\u043e\u0441\u0442\u0430\u0432 " * 40,
                    doc_id="doc-cab-1",
                    doc_name="smeta_norm_cards.v1",
                    score=0.9,
                    meta={},
                )
                for _ in range(3)
            ],
        )
    ]
    groups, chunks, omitted_refs = service.build_model_rag_evidence_groups(
        query_hits,
        max_chars=0,
        hits_per_query=3,
    )
    assert groups == [] and chunks == []
    assert "Q1.H1" in omitted_refs
    detail = service.model_rag_budget_omitted_cards(query_hits, chunks, omitted_refs)
    assert detail
    first = detail[0]
    assert first["ref"] == "Q1.H1"
    assert first["query"] == "\u0448\u043a\u0430\u0444 42U"
    assert first["card"] == "\u0413\u042d\u0421\u041d01-01-001-01"
    # Nothing omitted -> nothing named.
    assert service.model_rag_budget_omitted_cards(query_hits, chunks, []) == []


def test_model_answer_timeout_follows_registered_runtime_knob(monkeypatch):
    monkeypatch.delenv("LES_MODEL_CONNECTION_TIMEOUT_SEC", raising=False)
    assert service.model_answer_timeout_seconds() == 300.0
    monkeypatch.setenv("LES_MODEL_CONNECTION_TIMEOUT_SEC", "600")
    assert service.model_answer_timeout_seconds() == 600.0
    monkeypatch.setenv("LES_MODEL_CONNECTION_TIMEOUT_SEC", "0")
    assert service.model_answer_timeout_seconds() == 1.0
    monkeypatch.setenv("LES_MODEL_CONNECTION_TIMEOUT_SEC", "not-a-number")
    assert service.model_answer_timeout_seconds() == 300.0


def test_agent_loop_llm_client_uses_registered_timeout(monkeypatch):
    source = inspect.getsource(service)
    assert "async with httpx.AsyncClient(timeout=model_answer_timeout_seconds()) as client:" in source
    assert "httpx.AsyncClient(timeout=300.0)" not in source


def test_workbook_packaging_tool_follows_operator_intent():
    # Both packagers present, as on the sheet-pass / durable-resume routes
    # where prioritize_workbook_tools never runs: intent must still win.
    both = ["build_lsr_workbook", "build_vor_workbook", "search_sources"]
    vor_only = ["build_vor_workbook", "search_sources", "read_source"]
    assert service.workbook_packaging_tool(both, "Собери ВОР из спецификации") == [
        "build_vor_workbook"
    ]
    assert service.workbook_packaging_tool(
        vor_only, "Собери ВОР из прикреплённой спецификации"
    ) == ["build_vor_workbook"]
    # A priced-only request keeps the priced packager with both available.
    assert service.workbook_packaging_tool(both, "Собери ЛСР") == [
        "build_lsr_workbook"
    ]
    # Unspecified/mixed requests require the model's literal target.
    assert service.workbook_packaging_tool(both, "Что видно в документе") == []
    assert service.workbook_packaging_tool(both, "Собери ЛСР из ВОР") == []
    assert service.workbook_packaging_tool(both, "Собери ЛСР из ВОР",
        model_declaration={"status": "declared", "artifact_kind": "lsr"}) == ["build_lsr_workbook"]
    assert service.workbook_packaging_tool(vor_only, "Что видно в документе") == []
    assert service.workbook_packaging_tool(["search_sources"], "Собери ВОР") == []


def test_workbook_packaging_args_match_each_tool_contract():
    # Regression (build 794 live run wrj_5bbbf11b): the ВОР packaging call sent
    # the priced-only confirmed_data overlay and died with TOOL_SCHEMA_INVALID.
    from proxy.services.structured_extract import validate as validate_json_schema
    from proxy.services.workbook_tool_service import (
        BUILD_LSR_WORKBOOK,
        BUILD_VOR_WORKBOOK,
    )

    decisions = [
        {"source_row": "СКС!R2", "row_role": "work", "title": "Монтаж трубы", "unit": "м", "quantity": 10}
    ]
    overrides = {"СКС!R2": {"confirmed_price": 125.5}}
    vor_args = service.workbook_packaging_args(
        packaging_tool="build_vor_workbook",
        attachment_id="att-1",
        question="Собери ВОР из спецификации",
        decisions=decisions,
        operator_overrides=overrides,
    )
    assert validate_json_schema(vor_args, BUILD_VOR_WORKBOOK.input_schema) == []
    assert "confirmed_data" not in vor_args
    lsr_args = service.workbook_packaging_args(
        packaging_tool="build_lsr_workbook",
        attachment_id="att-1",
        question="Собери ЛСР из ВОР",
        decisions=decisions,
        operator_overrides=overrides,
    )
    assert validate_json_schema(lsr_args, BUILD_LSR_WORKBOOK.input_schema) == []
    assert lsr_args["confirmed_data"] == overrides


def test_sheet_pass_visible_tools_for_vor_intent_hide_priced_packager():
    # integration of the two intent gates: narrowing must leave exactly the
    # row-preserving packager visible and selectable for auto-packaging.
    tools = service.prioritize_workbook_tools(
        ["search_sources", "read_source", "build_lsr_workbook", "build_vor_workbook"],
        workbook_phase=True,
        question="Собери ВОР из прикреплённой спецификации",
    )
    assert "build_lsr_workbook" not in tools
    assert service.workbook_packaging_tool(tools, "Собери ВОР из прикреплённой спецификации") == [
        "build_vor_workbook"
    ]


def test_terminal_research_packaging_rows_only_for_complete_jobs():
    rows = [
        {"source_row": "СКС!R26", "title": "Монтаж", "unit": "м", "quantity": 2}
    ]
    assert service.terminal_research_packaging_rows(None) == []
    assert service.terminal_research_packaging_rows(
        {"status": "running", "accepted_rows": rows}
    ) == []
    assert service.terminal_research_packaging_rows(
        {"status": "paused", "accepted_rows": rows}
    ) == []
    durable = service.terminal_research_packaging_rows(
        {"status": "complete", "accepted_rows": rows}
    )
    assert durable == rows
    # Packaged copies never alias the stored job payload.
    assert all(item is not rows[index] for index, item in enumerate(durable))
    # Non-mapping entries can never leak into the decision set.
    assert service.terminal_research_packaging_rows(
        {"status": "complete", "accepted_rows": rows + ["junk", None]}
    ) == rows


def test_workbook_packaging_args_draft_and_parent_are_opt_in():
    # Regression (build 797 live run wrj_ca8feeda): the completing resume must
    # package the full durable set as a fresh non-draft revision, while paused
    # intermediates carry an explicit draft marker.  The identity already covers
    # decisions, so ordinary calls must keep gaining no new keys.
    from proxy.services.structured_extract import validate as validate_json_schema
    from proxy.services.workbook_tool_service import (
        BUILD_LSR_WORKBOOK,
        BUILD_VOR_WORKBOOK,
    )

    decisions = [
        {"source_row": "СКС!R2", "row_role": "work", "title": "Монтаж трубы", "unit": "м", "quantity": 10}
    ]
    base = service.workbook_packaging_args(
        packaging_tool="build_lsr_workbook",
        attachment_id="att-1",
        question="Собери ЛСР из ВОР",
        decisions=decisions,
        operator_overrides={},
    )
    assert "draft" not in base
    assert "parent_revision_id" not in base
    draft_args = service.workbook_packaging_args(
        packaging_tool="build_lsr_workbook",
        attachment_id="att-1",
        question="Собери ЛСР из ВОР",
        decisions=decisions,
        operator_overrides={},
        draft=True,
    )
    assert draft_args["draft"] is True
    assert validate_json_schema(draft_args, BUILD_LSR_WORKBOOK.input_schema) == []
    final_args = service.workbook_packaging_args(
        packaging_tool="build_lsr_workbook",
        attachment_id="att-1",
        question="Собери ЛСР из ВОР",
        decisions=decisions,
        operator_overrides={},
        parent_revision_id="rev_draft",
    )
    assert final_args["parent_revision_id"] == "rev_draft"
    assert "draft" not in final_args
    assert validate_json_schema(final_args, BUILD_LSR_WORKBOOK.input_schema) == []
    vor_draft = service.workbook_packaging_args(
        packaging_tool="build_vor_workbook",
        attachment_id="att-1",
        question="Собери ВОР из спецификации",
        decisions=decisions,
        operator_overrides=None,
        draft=True,
    )
    assert validate_json_schema(vor_draft, BUILD_VOR_WORKBOOK.input_schema) == []
    assert "confirmed_data" not in vor_draft


def test_workbook_packaging_lineage_replays_settled_final_without_duplicate():
    # Live regression (build 798 runtime run wrj_2b0fff82): re-opening a job
    # that is already terminal packaged the identical durable decision set as a
    # second revision. The lineage helper must hand back the parent that the
    # settled final call itself used, so the call identity (which already
    # covers ``decisions``) matches and the tool serves the same revision.
    draft_event = {
        "sequence": 2,
        "event_type": "workbook_packaged",
        "payload": {
            "tool": "build_lsr_workbook",
            "revision_id": "rev_draft",
            "draft": True,
            "parent_revision_id": "",
        },
    }
    final_event = {
        "sequence": 5,
        "event_type": "workbook_packaged",
        "payload": {
            "tool": "build_lsr_workbook",
            "revision_id": "rev_final",
            "draft": False,
            "parent_revision_id": "rev_draft",
        },
    }
    events = [
        {"sequence": 1, "event_type": "packet_checkpoint", "payload": {}},
        draft_event,
        {"sequence": 3, "event_type": "packet_checkpoint", "payload": {}},
        {"sequence": 4, "event_type": "complete", "payload": {}},
        final_event,
    ]

    parents, settled = service.workbook_packaging_lineage(events, durable_decisions=True)
    assert parents == {"build_lsr_workbook": "rev_final"}
    assert settled == {"build_lsr_workbook": "rev_draft"}

    # A paused job has no final revision to replay: it must keep chaining.
    _, settled_paused = service.workbook_packaging_lineage(
        events[:3], durable_decisions=False
    )
    assert settled_paused == {}

    # New durable decisions after the final revision must chain, not replay.
    grown = events + [{"sequence": 6, "event_type": "packet_checkpoint", "payload": {}}]
    grown_parents, grown_settled = service.workbook_packaging_lineage(
        grown, durable_decisions=True
    )
    assert grown_parents == {"build_lsr_workbook": "rev_final"}
    assert grown_settled == {}

    # A sibling packager writing later is not a decision change for this tool.
    sibling = events + [
        {
            "sequence": 6,
            "event_type": "workbook_packaged",
            "payload": {
                "tool": "build_vor_workbook",
                "revision_id": "rev_vor",
                "draft": False,
                "parent_revision_id": "",
            },
        }
    ]
    _, sibling_settled = service.workbook_packaging_lineage(
        sibling, durable_decisions=True
    )
    assert sibling_settled == {
        "build_lsr_workbook": "rev_draft",
        "build_vor_workbook": None,
    }
    parents_all, _ = service.workbook_packaging_lineage(sibling, durable_decisions=True)
    assert parents_all == {
        "build_lsr_workbook": "rev_final",
        "build_vor_workbook": "rev_vor",
    }


def test_workbook_packaging_lineage_ignores_malformed_events():
    events = [
        {"sequence": 1, "event_type": "workbook_packaged", "payload": "not-a-mapping"},
        {"sequence": 2, "event_type": "workbook_packaged", "payload": {"tool": "build_lsr_workbook"}},
        {"sequence": 3, "event_type": "workbook_packaged", "payload": {"revision_id": "rev_x"}},
    ]
    parents, settled = service.workbook_packaging_lineage(events, durable_decisions=True)
    assert parents == {}
    assert settled == {}


def test_workbook_packaging_lineage_derives_parent_for_legacy_events():
    # The runtime job wrj_2b0fff82 was packaged by build 798, which recorded no
    # parent in the workbook_packaged event. Re-opening it after the fix must
    # still replay the existing call, so the parent is read back from the
    # packaging chain itself.
    legacy_events = [
        {"sequence": 1, "event_type": "packet_checkpoint", "payload": {}},
        {
            "sequence": 2,
            "event_type": "workbook_packaged",
            "payload": {"tool": "build_lsr_workbook", "revision_id": "rev_draft", "draft": True},
        },
        {"sequence": 3, "event_type": "complete", "payload": {}},
        {
            "sequence": 4,
            "event_type": "workbook_packaged",
            "payload": {"tool": "build_lsr_workbook", "revision_id": "rev_final", "draft": False},
        },
    ]
    parents, settled = service.workbook_packaging_lineage(
        legacy_events, durable_decisions=True
    )
    assert parents == {"build_lsr_workbook": "rev_final"}
    assert settled == {"build_lsr_workbook": "rev_draft"}

    # A recorded parent wins over the chain when both exist.
    mixed = [legacy_events[0], legacy_events[1]] + [
        {
            "sequence": 4,
            "event_type": "workbook_packaged",
            "payload": {
                "tool": "build_lsr_workbook",
                "revision_id": "rev_final",
                "draft": False,
                "parent_revision_id": "rev_external",
            },
        }
    ]
    _, mixed_settled = service.workbook_packaging_lineage(mixed, durable_decisions=True)
    assert mixed_settled == {"build_lsr_workbook": "rev_external"}

    # A first-ever final has no parent at all, recorded or derived.
    first_only = [legacy_events[0], legacy_events[3]]
    _, first_settled = service.workbook_packaging_lineage(first_only, durable_decisions=True)
    assert first_settled == {"build_lsr_workbook": None}


def test_workbook_packaging_lineage_survives_repeated_terminal_bookkeeping():
    # Live ledger of job wrj_2b0fff82: each re-open of the finished job appended
    # another ``complete`` event before packaging, which made the previous final
    # revision look stale and wrote a duplicate document.  Only events that can
    # change the saved durable decisions may invalidate a settled final.
    events = [
        {"sequence": 35, "event_type": "packet_checkpoint", "payload": {}},
        {"sequence": 36, "event_type": "complete", "payload": {}},
        {
            "sequence": 37,
            "event_type": "workbook_packaged",
            "payload": {"tool": "build_lsr_workbook", "revision_id": "rev_first", "draft": False},
        },
        {"sequence": 38, "event_type": "complete", "payload": {}},
        {
            "sequence": 39,
            "event_type": "workbook_packaged",
            "payload": {
                "tool": "build_lsr_workbook",
                "revision_id": "rev_second",
                "draft": False,
                "parent_revision_id": "rev_first",
            },
        },
        {"sequence": 40, "event_type": "complete", "payload": {}},
    ]
    parents, settled = service.workbook_packaging_lineage(events, durable_decisions=True)
    assert parents == {"build_lsr_workbook": "rev_second"}
    assert settled == {"build_lsr_workbook": "rev_first"}

    # Re-running the query cache or a stall guard is bookkeeping too.  A replay
    # records the same revision with the parent it was built on, so the settled
    # parent stays stable across repeated re-opens.
    noisy = [
        *events,
        {"sequence": 41, "event_type": "workbook_packaged",
         "payload": {"tool": "build_lsr_workbook", "revision_id": "rev_second",
                     "draft": False, "parent_revision_id": "rev_first"}},
        {"sequence": 42, "event_type": "search_cache", "payload": {}},
        {"sequence": 43, "event_type": "stall_guard_triggered", "payload": {}},
    ]
    _, noisy_settled = service.workbook_packaging_lineage(noisy, durable_decisions=True)
    assert noisy_settled == {"build_lsr_workbook": "rev_first"}

    # Reopened locators are a real change: the next package must chain.
    reopened = [
        *events,
        {"sequence": 41, "event_type": "workbook_packaged",
         "payload": {"tool": "build_lsr_workbook", "revision_id": "rev_second",
                     "draft": False, "parent_revision_id": "rev_first"}},
        {"sequence": 42, "event_type": "locators_reopened", "payload": {}},
    ]
    _, reopened_settled = service.workbook_packaging_lineage(
        reopened, durable_decisions=True
    )
    assert reopened_settled == {}


# --------------------------------------------------------------------------- #
# Criterion 2 (build 806): packaging that dies of MemoryError must not end the
# run without a file.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_memory_pressure_packaging_gets_a_relief_and_retry_attempt(monkeypatch) -> None:
    """A retry that repeats the same allocation is useless without relief."""

    calls: list[int] = []
    cleared: list[str] = []

    def fake_relief(reason: str = "") -> dict:
        cleared.append(reason)
        return {"released": ["fgis_pricebook"], "reason": reason}

    monkeypatch.setattr(
        service, "release_memory_for_packaging", fake_relief, raising=False
    )

    async def executor(_call, _ctx, _sink):
        calls.append(len(calls) + 1)
        return {
            "schema": "les.workbook_tool_result.v1",
            "tool": "build_lsr_workbook",
            "status": "failed",
            "code": "WORKBOOK_GENERATION_FAILED",
            "error_type": "MemoryError",
            "memory_pressure": True,
            "message": "injected packaging fault",
            "checkpoint": {"checkpoint_id": "cp-mem", "resumed": len(calls) > 1},
        }

    payload, traces = await service.execute_workbook_with_bounded_retry(
        executor,
        {"tool": "build_lsr_workbook", "args": {}},
        {"session_id": "s1"},
        None,
    )

    assert len(calls) == service._PACKAGING_MEMORY_ATTEMPTS
    assert cleared == ["build_lsr_workbook"] * (len(calls) - 1)
    assert payload["memory_relief"][0]["released"] == ["fgis_pricebook"]
    # The repair hint survives the retry loop, so the client still sees it.
    assert traces[-1]["status"] == "failed"
    # Each retry is logged with the relief that made it worth attempting.
    assert "memory_released" not in traces[-1]
    assert [item.get("memory_released") for item in traces] == [
        ["fgis_pricebook"],
        ["fgis_pricebook"],
        None,
    ]


@pytest.mark.asyncio
async def test_deterministic_packaging_failure_is_not_retried_forever(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        service, "release_memory_for_packaging",
        lambda reason="": calls.append(1) or {"released": []},
        raising=False,
    )

    async def executor(_call, _ctx, _sink):
        calls.append(len(calls) + 1)
        return {
            "schema": "les.workbook_tool_result.v1",
            "tool": "build_lsr_workbook",
            "status": "failed",
            "code": "WORKBOOK_GENERATION_FAILED",
            "error_type": "ValueError",
            "memory_pressure": False,
            "checkpoint": {"checkpoint_id": "cp-det", "resumed": len(calls) > 1},
        }

    payload, traces = await service.execute_workbook_with_bounded_retry(
        executor,
        {"tool": "build_lsr_workbook", "args": {}},
        {"session_id": "s1"},
        None,
    )

    # Bounded: the same deterministic error cannot burn the run.
    assert len(calls) == 2
    assert "memory_relief" not in payload
    assert all("memory_released" not in item for item in traces)


def test_terminal_research_without_packaging_events_reports_pending_document() -> None:
    readiness_state = service._turn_document_state(
        research_job_service=None,
        research_job={"job_id": "wrj_1", "status": "complete"},
        job_status="complete",
        workbook_files=[{"filename": "ЛСР · черновик.xlsx", "draft": True}],
    )

    # A draft-only turn of a finished job is not "the document is ready".
    assert readiness_state == "draft_only"


def test_open_research_claims_no_durable_document_state() -> None:
    assert service._turn_document_state(
        research_job_service=None,
        research_job={"job_id": "wrj_1", "status": "paused"},
        job_status="paused",
        workbook_files=[],
    ) == ""


# ── ADR-16: систематический сбор кандидатов кодом поверх модельных запросов ──


def _adr16_catalog():
    from proxy.services.attachment_source_catalog_service import CatalogRow

    rows = (
        CatalogRow(
            locator="СКС!R5",
            sheet="СКС",
            excel_row=5,
            values=("Прокладка кабеля NYM 3x2.5 в трубе ПНД",),
            line="СКС!R5: Прокладка кабеля NYM 3x2.5 в трубе ПНД",
            numbers=(),
            section_context="Раздел 4. Наружные сети",
        ),
    )
    return SimpleNamespace(rows=rows, source_file_id="f1", original_name="СКС.xlsx")


class _Adr16Tools:
    """Stub of the read-only ``search_sources`` harness used by the sheet-pass."""

    def __init__(self, status: str = "ok") -> None:
        self.calls: list[str] = []
        self.status = status

    async def execute(self, call: dict) -> SimpleNamespace:
        query = str(call["args"]["q"])
        self.calls.append(query)
        if self.status != "ok":
            return SimpleNamespace(payload={"status": self.status, "error": "RAG_DOWN"}, chunks=())
        chunk = SimpleNamespace(
            content=f"Шифр: ГЭСН04-12-001-01 Наименование: {query}",
            doc_id="card-1",
            doc_name="les_smeta_norm_cards.v1",
            score=0.9,
            meta={"norm_code": "ГЭСН04-12-001-01", "dataset_id": "smeta"},
        )
        return SimpleNamespace(
            payload={"schema": "les_tool_result_v1", "tool": "search_sources", "status": "ok",
                     "result": {"count": 1}},
            chunks=(chunk,),
        )


@patch.dict("os.environ", {"LES_LSR_SYSTEM_CANDIDATE_QUERIES": "on"})
def _run_adr16(*, variant="B1_CANDIDATE", mode="estimator", status="ok", tools=None,
               model_queries=("кабель NYM",), cache=None):
    catalog = _adr16_catalog()
    tools = tools or _Adr16Tools(status)
    pass_hits: list[tuple[str, tuple]] = [(query, ()) for query in model_queries]
    trace: dict = {}
    provenance: dict[str, str] = {}
    addresses: dict[str, list[str]] = {}
    cache_updates: dict[str, list] = {}
    added = asyncio.run(
        service._execute_system_candidate_queries(
            catalog=catalog,
            sheet="СКС",
            packet=["СКС!R5"],
            profile_snapshot={"mode": mode},
            comparative_variant=variant,
            model_research_tools=tools,
            model_queries=list(model_queries),
            pass_hits=pass_hits,
            pass_tools=[],
            sheet_query_cache=cache if cache is not None else {},
            cache_updates=cache_updates,
            query_provenance=provenance,
            retrieval_trace=trace,
            hits_per_query=6,
            query_addresses=addresses,
        )
    )
    return {
        "added": added,
        "tools": tools,
        "pass_hits": pass_hits,
        "trace": trace,
        "provenance": provenance,
        "addresses": addresses,
        "cache_updates": cache_updates,
    }


def test_adr16_b0_direct_baseline_runs_no_system_queries() -> None:
    result = _run_adr16(variant="B0_DIRECT")
    assert result["added"] == 0
    assert result["tools"].calls == []
    assert result["provenance"] == {"кабель NYM": "model"}
    assert result["trace"]["system_candidate_queries"]["status"] == "skipped_baseline"


def test_adr16_ordinary_chat_turn_runs_no_system_queries() -> None:
    result = _run_adr16(mode="agent")
    assert result["added"] == 0
    assert result["tools"].calls == []


def test_adr16_estimator_sheet_pass_adds_tagged_candidate_groups() -> None:
    result = _run_adr16()
    assert result["added"] == 2
    original, derived = result["tools"].calls
    assert original == "Прокладка кабеля NYM 3x2.5 в трубе ПНД"
    assert derived.startswith(original) and "Раздел 4. Наружные сети" in derived
    assert result["provenance"] == {
        "кабель NYM": "model",
        original: "original",
        derived: "derived",
    }
    # candidates are appended to the model's own groups, never instead of them
    assert [query for query, _hits in result["pass_hits"]] == ["кабель NYM", original, derived]
    sheet_trace = result["trace"]["system_candidate_queries"]["sheets"]["СКС"]
    assert sheet_trace["queries_authored_by_code"] == 2
    assert {item["query_provenance"] for item in sheet_trace["executed"]} == {"original", "derived"}
    assert all(item["source_row"] == "СКС!R5" for item in sheet_trace["executed"])
    assert all(item["ungrounded_tokens"] == [] for item in sheet_trace["executed"])


def test_a_candidate_query_carries_the_row_it_was_built_from() -> None:
    """Blocker § 2: every query says which source row it stands for.

    A code-authored candidate knows its own locator, so the adapter can show the
    address instead of letting the model guess which operation the query is for.
    The model's own query is left without an invented address.
    """

    result = _run_adr16()
    original, derived = result["tools"].calls
    assert result["addresses"] == {original: ["СКС!R5"], derived: ["СКС!R5"]}
    assert "кабель NYM" not in result["addresses"]


def test_a_packet_deferred_by_the_character_budget_stays_visible(monkeypatch) -> None:
    """"Отложено by a technical bound is recorded, never read as «нет нормы»."""

    monkeypatch.setenv("LES_LSR_SYSTEM_CANDIDATE_MAX_CHARS", "1")
    result = _run_adr16()
    assert result["added"] == 0
    sheet_trace = result["trace"]["system_candidate_queries"]["sheets"]["СКС"]
    assert sheet_trace["deferred"]["deferred_by_char_budget"] == ["СКС!R5"]
    assert sheet_trace["source_text_filter"]["rows_in_packet"] == 1
    assert sheet_trace["source_text_filter"]["packets"] == 1
    assert "СКС!R5" not in sheet_trace["deferred"].get("skipped_without_source_text", [])


def test_adr16_candidate_hits_are_cached_like_model_hits() -> None:
    result = _run_adr16()
    assert set(result["cache_updates"]) == set(result["tools"].calls)
    assert result["cache_updates"][result["tools"].calls[0]][0]["doc_id"] == "card-1"
    # a second pass over the same packet reads the cache instead of re-searching
    tools = _Adr16Tools()
    again = _run_adr16(
        tools=tools,
        cache={query: records for query, records in result["cache_updates"].items()},
    )
    assert again["tools"].calls == []
    assert again["added"] == 2


def test_adr16_search_failure_defers_candidates_without_inventing_a_norm() -> None:
    result = _run_adr16(status="error")
    sheet_trace = result["trace"]["system_candidate_queries"]["sheets"]["СКС"]
    assert sheet_trace["search_blocked"] == "error"
    # the failure is visible; rows are not silently marked as having no norm
    assert sheet_trace["queries_authored_by_code"] == 0


def test_adr16_query_header_states_origin_and_keeps_model_headers_unchanged() -> None:
    assert service._model_rag_query_header(3, "кабель NYM") == "[Поисковый запрос Q3] кабель NYM"
    assert service._model_rag_query_header(3, "кабель NYM", "model") == (
        "[Поисковый запрос Q3] кабель NYM"
    )
    header = service._model_rag_query_header(4, "Прокладка кабеля", "derived")
    assert header == "[Поисковый запрос Q4] Прокладка кабеля (системный подбор по атрибутам этой строки)"
    origin = service._model_rag_query_provenance({"Прокладка кабеля": "derived"}, "прокладка  кабеля")
    assert origin == "derived"
    assert service._model_rag_query_provenance(None, "что угодно") == "model"


def test_adr16_budget_accounts_for_the_provenance_label() -> None:
    hit = SimpleNamespace(content="Шифр: ГЭСН04-12-001-01", doc_id="d", doc_name="c", score=0.5, meta={})
    query_hits = [("Прокладка кабеля", (hit,))]
    plain = service.model_rag_evidence_header_chars(query_hits, hits_per_query=6)
    tagged = service.model_rag_evidence_header_chars(
        query_hits, hits_per_query=6, query_provenance={"Прокладка кабеля": "derived"}
    )
    assert tagged > plain
    complete, _chunks, _ = service.build_model_rag_evidence_groups(
        query_hits, max_chars=10000, hits_per_query=6,
        query_provenance={"Прокладка кабеля": "derived"},
    )
    tagged_budget = len("\n\n".join(complete))
    groups, chunks, _omitted = service.build_model_rag_evidence_groups(
        query_hits, max_chars=tagged_budget, hits_per_query=6,
        query_provenance={"Прокладка кабеля": "derived"},
    )
    assert "(системный подбор по атрибутам этой строки)" in groups[0]
    assert chunks[0].meta["query_provenance"] == "derived"
    assert chunks[0].content == hit.content and chunks[0].meta["body_status"] == "full"
    assert len("\n\n".join(groups)) == tagged_budget
    # an untagged query is reported as the model's own, never as a system query
    untagged, _c, _o = service.build_model_rag_evidence_groups(
        query_hits, max_chars=tagged_budget - (tagged - plain), hits_per_query=6, query_provenance=None
    )
    assert "системный подбор" not in untagged[0]


def _adr16_two_row_catalog():
    from proxy.services.attachment_source_catalog_service import CatalogRow

    rows = tuple(
        CatalogRow(
            locator=f"СКС!R{number}",
            sheet="СКС",
            excel_row=number,
            values=(f"Прокладка кабеля NYM 3x2.5 в трубе ПНД, участок {number}",),
            line=f"СКС!R{number}: Прокладка кабеля NYM 3x2.5 в трубе ПНД, участок {number}",
            numbers=(),
            section_context="Раздел 4. Наружные сети",
        )
        for number in (5, 6)
    )
    return SimpleNamespace(rows=rows, source_file_id="f1", original_name="СКС.xlsx")


@patch.dict("os.environ", {"LES_LSR_SYSTEM_CANDIDATE_QUERIES": "on"})
def _adr16_packet(trace: dict, *, catalog, packet: list[str], tools=None) -> dict:
    """Run one packet of system candidates into an existing retrieval trace."""

    model_queries = ["кабель NYM"]
    tools = tools or _Adr16Tools()
    asyncio.run(
        service._execute_system_candidate_queries(
            catalog=catalog,
            sheet="СКС",
            packet=list(packet),
            profile_snapshot={"mode": "estimator"},
            comparative_variant="B1_CANDIDATE",
            model_research_tools=tools,
            model_queries=list(model_queries),
            pass_hits=[(query, ()) for query in model_queries],
            pass_tools=[],
            sheet_query_cache={},
            cache_updates={},
            query_provenance={},
            retrieval_trace=trace,
            hits_per_query=6,
        )
    )
    return trace["system_candidate_queries"]["sheets"]["СКС"]


def test_adr16_packets_of_one_sheet_accumulate_instead_of_overwriting() -> None:
    """Two packets of the same sheet must both stay readable in the trace."""

    catalog = _adr16_two_row_catalog()
    trace: dict = {}
    first = _adr16_packet(trace, catalog=catalog, packet=["СКС!R5"])
    assert first["queries_authored_by_code"] == 2
    second = _adr16_packet(trace, catalog=catalog, packet=["СКС!R6"])

    assert second["queries_authored_by_code"] == 4
    assert {item["source_row"] for item in second["executed"]} == {"СКС!R5", "СКС!R6"}
    assert len(second["executed"]) == 4


def test_adr16_a_blocked_candidate_search_is_recorded_as_deferred() -> None:
    """§ 6: an interrupted search is «отложено», never «норма отсутствует»."""

    trace: dict = {}
    sheet_trace = _adr16_packet(
        trace,
        catalog=_adr16_two_row_catalog(),
        packet=["СКС!R5"],
        tools=_Adr16Tools("error"),
    )

    assert sheet_trace["search_blocked"] == "error"
    assert sheet_trace["queries_authored_by_code"] == 0
    deferred = sheet_trace["deferred"]["deferred_by_search_block"]
    assert len(deferred) == 2
    assert all("Прокладка кабеля" in item for item in deferred)


def test_adr16_a_locator_the_catalog_lacks_is_named_in_the_trace() -> None:
    trace: dict = {}
    sheet_trace = _adr16_packet(
        trace, catalog=_adr16_two_row_catalog(), packet=["СКС!R5", "СКС!R99"]
    )

    assert sheet_trace["deferred"]["not_in_source_catalog"] == ["СКС!R99"]


def test_structural_source_completion_accepts_verified_file_id_alias_without_mutating_decisions():
    from proxy.services.attachment_source_catalog_service import AttachmentSourceCatalog, CatalogRow
    from proxy.services.chat_evidence_application_service import structurally_complete_source_keys
    from proxy.services.lsr_source_coverage_service import operation_identity

    catalog = AttachmentSourceCatalog(original_name="source.pdf", sheets=(("PDF", 2), ("PDF_TEXT", 1)),
        source_file_id="src_structure_identity", rows=(
            CatalogRow(locator="PDF!R2", sheet="PDF", excel_row=2, values=("Work",),
                       line="PDF!R2: Work", numbers=(), row_classification="ambiguous"),
            CatalogRow(locator="PDF!R3", sheet="PDF", excel_row=3, values=("Material",),
                       line="PDF!R3: Material", numbers=(), row_classification="ambiguous"),
            CatalogRow(locator="PDF_TEXT!R1", sheet="PDF_TEXT", excel_row=1, values=("Literal prose",),
                       line="PDF_TEXT!R1: Literal prose", numbers=(), row_classification="ambiguous"),
        ))
    rows = [{"source_row": "src_structure_identity!R2", "row_role": "work", "evidence_refs": "Q3.H2"},
            {"source_row": "PDF!R3", "row_role": "material", "work_row": "src_structure_identity!R2"}]
    before = json.dumps(rows, sort_keys=True)
    identities = [operation_identity(row) for row in rows]
    complete = structurally_complete_source_keys(rows, catalog)
    assert {"PDF!R2", "PDF!R3"}.issubset(complete)
    assert "PDF_TEXT!R1" not in complete
    assert json.dumps(rows, sort_keys=True) == before
    assert [operation_identity(row) for row in rows] == identities
