"""Model requests scoped facts; readers do not make an estimate decision."""

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from proxy.services.fgis_price_service import PriceBook
from proxy.services.model_research_tool_service import ModelResearchToolService
from proxy.services.model_pricebook_evidence_service import PriceBookEvidenceSource, read_pricebook_evidence


NORM_CODE = "ГЭСН99-01-001-01"
RESOURCE_CODE = "20.4.01.01-0001"
BASIS = {"pricebook": "chosen-book", "region": "Selected region", "quarter": "3 квартал 2026 г."}


class DocumentRetrieval:
    def __init__(self, dataset="selected", doc_id="offer-1"):
        self.chunks = (SimpleNamespace(
            content="Commercial offer: 12 m, RUB 100/m, VAT included, dated 2026-09-22.",
            doc_name="Offer.pdf", score=0.8,
            meta={"dataset_id": dataset, "doc_id": doc_id, "chunk_id": "offer-chunk", "page": 2,
                  "retrieval_channels": ["dense", "bm25_sparse"], "rrf_score": 0.031},
        ),)

    def payload(self):
        return {"fusion": "native_rrf", "retrieval_channels": ["dense", "bm25_sparse"]}


def norm_search(_query, *, limit):
    return {"cards": [{"norm_key": "norm-immutable", "norm_code": NORM_CODE,
                       "title": "Selected norm", "source_ref": "typed#norm-immutable",
                       "measure_unit": "m", "work_steps": ["Install"], "resource_count": 40}],
            "retrieval_trace": {"rag": {"status": "ok"}}}


def service(**kwargs):
    return ModelResearchToolService(
        retrieve=kwargs.pop("retrieve", lambda **_: pytest.fail("unexpected shared retrieval")),
        frozen_dataset_ids=("selected",), retrieval_kwargs=kwargs.pop("retrieval_kwargs", {"return_trace": True}),
        fallback=kwargs.pop("fallback", lambda *_: pytest.fail("unexpected fallback")),
        smeta_norm_retrieve=kwargs.pop("smeta_norm_retrieve", norm_search),
        **kwargs,
    )


def book_source(book, content=b"synthetic chosen-book bytes"):
    return PriceBookEvidenceSource(book, hashlib.sha256(content).hexdigest(), "chosen-book.parquet", len(content))


def chosen_book():
    rows = [
        {"code": RESOURCE_CODE, "name": "Cable, selected version", "unit": "m", "price_current": 100,
         "currency": "RUB", "vat": "included", "source_date": "2026-09-22"},
        {"code": "20.4.01.01-0002", "name": "Cable, another version", "unit": "m", "price_current": 200},
    ]
    return book_source(PriceBook(rows, region=BASIS["region"], quarter=BASIS["quarter"]),
                       json.dumps(rows, ensure_ascii=False).encode("utf-8"))


@pytest.mark.asyncio
@pytest.mark.parametrize("tool, args", [
    ("search_pricebook_resources", {"q": RESOURCE_CODE}),
    ("read_resource_price", {"code": RESOURCE_CODE}),
])
async def test_price_inventory_preserves_literal_candidate_name_unit_and_source(tool, args):
    from proxy.services.model_rag_grouped_evidence_service import (
        EvidenceCard, EvidenceGroup, plan_full_group_page,
    )

    row = {"code": RESOURCE_CODE, "name": 'Кабель «Свет» 4×1,5 / "FRHF"',
           "unit": "100 м²", "price_current": 123.45,
           "source_note": "Полный текст источника. " * 1000}
    source = book_source(PriceBook([row], region=BASIS["region"], quarter=BASIS["quarter"]),
                         json.dumps(row, ensure_ascii=False).encode("utf-8"))
    result = await service(price_basis=BASIS, pricebook_provider=lambda _: source).execute(
        {"tool": tool, "args": args})
    hit = result.chunks[0]
    body = json.loads(hit.content)
    assert {key: body["resource"][key] for key in row} == row
    page = plan_full_group_page([EvidenceGroup("Literal model query", [
        EvidenceCard("Q1.H1", hit.doc_name, "", hit.content, hit.meta),
    ])], 1400)
    assert page.inventory_refs == ["Q1.H1"] and page.body_refs == []
    literal_pointer = page.pointer_by_ref["Q1.H1"]
    pointer = json.loads(literal_pointer)
    assert pointer[1] == "deferred_capacity"
    assert pointer[4:6] == [row["name"], row["unit"]]
    assert pointer[-1]["resource_code"] == RESOURCE_CODE
    assert pointer[-1]["pricebook"] == BASIS["pricebook"]
    assert pointer[-1]["pricebook_sha256"] == source.source_sha256
    assert body["source_ref"] in "\n\n".join(page.groups)
    assert row["source_note"] not in literal_pointer and "price_current" not in literal_pointer
    assert len(literal_pointer) < 1000


def admit_search_inventory(reader, result, call):
    """Model-visible search admission precedes restoring its exact reader handles."""
    from proxy.services import chat_evidence_application_service as application
    from proxy.services.model_execution_preset_service import ModelExecutionPreset
    receipt = {"call": call, "status": result.payload["status"]}
    _, chunks, _ = application.bind_model_requested_read_evidence(
        [result], existing_chunks=[], evidence_namespace="action-fixture", receipts=[receipt])
    preset = ModelExecutionPreset(preset_id="action-admission", model_family="fixture",
        input_token_limit=20_000, generation_reserve_tokens=0, safety_reserve_tokens=0,
        normal_tool_count=5, max_tools=5, max_batch_items=5, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=("test",))
    messages, packet, inventory, bodies = application.govern_model_read_messages(
        preset=preset, profile_prefix="fixture profile", request_payload="literal model question",
        source_context=["literal current source"], chunks=chunks, receipts=[receipt])
    assert packet.included_tokens <= packet.input_budget_tokens
    assert inventory == receipt["evidence_refs"]
    assert all(ref in str(messages) for ref in inventory)
    application.confirm_model_read_delivery(chunks, [receipt], inventory_refs=inventory, body_refs=bodies)
    reader.register_shown_norm_cards(chunks)
    return chunks


@pytest.mark.asyncio
async def test_visible_deferred_norm_pointer_reads_full_resources_without_another_search():
    from proxy.services import chat_evidence_application_service as chat_evidence
    searches, reads = [], []
    card = {"norm_key": "norm-immutable", "norm_code": NORM_CODE, "title": "Selected norm",
            "source_ref": "typed#norm-immutable", "measure_unit": "m",
            "work_steps": ["Literal complete conditions " + "x" * 5000], "resource_count": 1}

    def search(query, *, limit):
        searches.append(query)
        return {"cards": [card], "retrieval_trace": {"rag": {"status": "ok"}}}

    def exact(**pointer):
        reads.append(pointer)
        return {"status": "ok", "card": {**card, "resources": [
            {"kind": "material", "code": RESOURCE_CODE, "name": "Literal resource", "unit": "kg", "per_unit": 7.25}],
            "resources_complete": True, "resources_returned": 1, "resource_consumption_known": True}}

    reader = service(smeta_norm_retrieve=search, norm_card_reader=exact)
    found = await reader.execute({"tool": "search_sources", "args": {"q": "literal model query", "target": "norms"}})
    groups, pointers, deferred = chat_evidence.build_model_rag_evidence_groups(
        [("literal model query", found.chunks)], max_chars=1400, hits_per_query=6)
    assert deferred == ["Q1.H1"] and groups
    pointer = pointers[0]
    assert pointer.meta["body_status"] == "deferred_capacity" and pointer.meta["card_body_shown"] is False
    assert card["work_steps"][0] not in pointer.content
    reader.register_shown_norm_cards(pointers)
    result = await reader.execute({"tool": "read_norm_card", "args": {"norm_key": "norm-immutable", "norm_code": NORM_CODE}})
    assert searches == ["literal model query"] and len(reads) == 1
    assert result.payload["status"] == "ok"
    assert result.chunks[0].meta["body_status"] == "full"
    assert result.chunks[0].meta["normative_card_identity"] == pointer.meta["normative_card_identity"]
    assert card["work_steps"][0] in result.chunks[0].content
    assert '"per_unit": 7.25' in result.chunks[0].content and '"unit": "kg"' in result.chunks[0].content


@pytest.mark.asyncio
async def test_model_document_target_uses_selected_native_rrf_without_norm_fallback():
    calls = []

    async def retrieve(**kwargs):
        calls.append(kwargs)
        return DocumentRetrieval()

    reader = service(retrieve=retrieve, smeta_norm_retrieve=lambda *_a, **_k: pytest.fail("norm route must not run"))
    result = await reader.execute({"tool": "search_sources", "args": {"q": "literal commercial offer", "target": "documents"}})
    assert calls == [{"question": "literal commercial offer", "dataset_ids": ["selected"],
                      "result_limit": 6, "candidate_limit": 64, "document_diversity_k": 2, "return_trace": True}]
    assert result.payload["trace"]["fusion"] == "native_rrf"
    assert result.chunks[0].content == DocumentRetrieval().chunks[0].content
    assert result.chunks[0].meta["chunk_id"] == "offer-chunk"
    assert result.chunks[0].meta["rrf_score"] == 0.031


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [
    {"q": "offer", "target": "documents", "dataset_ids": ["foreign"]},
    {"q": "offer", "target": "documents", "dataset_ids": "selected"},
    {"q": "offer", "target": ["documents"]},
    {"q": ["offer"], "target": "documents"},
])
async def test_malformed_or_foreign_search_scope_never_calls_a_reader(args):
    result = await service().execute({"tool": "search_sources", "args": args})
    assert result.payload["status"] in {"missing", "conflict"}
    assert result.chunks == ()


@pytest.mark.asyncio
async def test_document_reader_cannot_return_foreign_dataset_evidence():
    async def retrieve(**_kwargs):
        return DocumentRetrieval(dataset="foreign")

    result = await service(retrieve=retrieve).execute({"tool": "search_sources", "args": {"q": "offer", "target": "documents"}})
    assert result.payload["status"] == "conflict"
    assert result.chunks == ()


@pytest.mark.asyncio
async def test_read_source_uses_a_shown_document_and_preserves_quote_provenance():
    calls = []

    async def retrieve(**_kwargs):
        return DocumentRetrieval()

    def fallback(tool, args):
        calls.append((tool, args))
        return {"status": "ok", "result": {"chunks": [
            {"text": "Exact offer body: RUB 100/m, VAT included, 2026-09-22.", "dataset_id": "selected",
             "doc_id": "offer-1", "doc_name": "Offer.pdf", "chunk_id": "quote-2", "page": 2}
        ]}}

    reader = service(retrieve=retrieve, fallback=fallback)
    search_call = {"tool": "search_sources", "args": {"q": "offer", "target": "documents"}}
    found = await reader.execute(search_call)
    exact_call = {"tool": "read_source", "args": {"doc_id": "offer-1"}}
    unshown = await reader.execute(exact_call)
    assert unshown.payload["status"] in {"missing", "conflict"} and unshown.chunks == ()
    assert calls == []  # Retained raw search data does not authorize a fallback read.
    admitted = admit_search_inventory(reader, found, search_call)
    assert admitted[0].meta["model_inventory_delivery_status"] == "delivered"
    result = await reader.execute(exact_call)
    assert calls == [("read_source", {"doc_id": "offer-1", "dataset_id": "selected", "doc_name": "Offer.pdf"})]
    assert result.chunks[0].meta["dataset_id"] == "selected"
    assert result.chunks[0].meta["chunk_id"] == "quote-2"
    assert result.chunks[0].meta["minimum_evidence_body_chars"] == len(result.chunks[0].content)
    assert "VAT included" in result.chunks[0].content
    assert "confirmed_price" not in result.payload


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [{"doc_id": "unshown"}, {"dataset_id": "foreign", "doc_name": "Offer.pdf"},
                                 {"dataset_id": ["selected"], "doc_name": "Offer.pdf"}])
async def test_read_source_refuses_unshown_or_foreign_document(args):
    result = await service().execute({"tool": "read_source", "args": args})
    assert result.chunks == ()
    assert result.payload["status"] in {"conflict", "missing"}


@pytest.mark.asyncio
async def test_read_source_rejects_callback_evidence_outside_selected_document():
    result = await service(fallback=lambda *_: {"status": "ok", "result": {"chunks": [
        {"text": "foreign quote", "dataset_id": "foreign", "doc_id": "other"}
    ]}}).execute({"tool": "read_source", "args": {"dataset_id": "selected", "doc_name": "Offer.pdf"}})
    assert result.payload["status"] == "conflict"
    assert result.chunks == ()


@pytest.mark.asyncio
async def test_read_source_cannot_replace_the_requested_document_inside_a_dataset():
    result = await service(fallback=lambda *_: {"status": "ok", "result": {"chunks": [
        {"text": "another document", "dataset_id": "selected", "doc_name": "Other.pdf"}
    ]}}).execute({"tool": "read_source", "args": {"dataset_id": "selected", "doc_name": "Offer.pdf"}})
    assert result.payload["status"] == "conflict" and result.chunks == ()


@pytest.mark.asyncio
async def test_exact_norm_read_keeps_all_resource_consumption_and_nrsp_choices(monkeypatch):
    from proxy.services import model_research_tool_service as module
    from proxy.services.model_resource_reference_service import resource_slot_records, shown_resource_record

    monkeypatch.setattr(module.nr_sp_service, "model_candidates", lambda **_: [{
        "rule_id": "nrsp-user-choice", "label": "Known condition", "nr_pct": 10, "sp_pct": 5,
        "basis": "Synthetic source", "source_ref": "rules#choice",
    }])
    calls = []
    expected_resources = [{"kind": "material", "code": f"literal-{i}", "name": f"Resource {i}",
                           "unit": "m", "per_unit": i / 10, "source_ref": f"typed#resource-{i}"}
                          for i in range(40)]

    def exact_reader(**kwargs):
        calls.append(kwargs)
        return {"status": "ok", "card": {
            "norm_key": "norm-immutable", "norm_code": NORM_CODE, "title": "Selected norm",
            "source_ref": "typed#norm-immutable", "measure_unit": "m", "work_steps": ["Install"],
            "resource_count": 40, "resources_returned": 40, "resources_complete": True,
            "resource_consumption_known": True,
            "resources": [dict(row) for row in expected_resources],
        }, "missing": [], "warnings": []}

    reader = service(norm_card_reader=exact_reader)
    search_call = {"tool": "search_sources", "args": {"q": "chosen norm"}}
    found = await reader.execute(search_call)
    exact_call = {"tool": "read_norm_card", "args": {"norm_key": "norm-immutable"}}
    unshown = await reader.execute(exact_call)
    assert unshown.payload["status"] in {"missing", "conflict"} and unshown.chunks == ()
    assert calls == []  # The typed reader has not been called before actual admission.
    admitted = admit_search_inventory(reader, found, search_call)
    assert admitted[0].meta["model_inventory_delivery_status"] == "delivered"
    result = await reader.execute(exact_call)
    assert calls == [{"norm_key": "norm-immutable", "norm_code": NORM_CODE}]
    assert result.payload["result"]["card"]["resources"] == expected_resources
    expected_meta = {"exact_card_read": True,
                     "resources": resource_slot_records({"resources": expected_resources})}
    shown_resources = [shown_resource_record(expected_meta, result.chunks[0].content, slot)
                       for slot in range(1, 41)]
    assert json.dumps(shown_resources, ensure_ascii=False, sort_keys=True) == json.dumps(
        expected_resources, ensure_ascii=False, sort_keys=True)
    assert shown_resources[-1] == expected_resources[-1]
    assert "nrsp-user-choice" in result.chunks[0].content
    assert result.chunks[0].meta["resources_complete"] is True
    assert result.chunks[0].meta["minimum_evidence_body_chars"] == len(result.chunks[0].content)


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [{"norm_key": "unknown"}, {"norm_code": NORM_CODE}, {"norm_key": ["invalid"]}])
async def test_unshown_or_malformed_exact_norm_pointer_does_not_call_reader(args):
    result = await service(norm_card_reader=lambda **_: pytest.fail("unshown pointer must not read base")).execute(
        {"tool": "read_norm_card", "args": args})
    assert result.chunks == ()
    assert result.payload["status"] in {"missing", "conflict"}


@pytest.mark.asyncio
async def test_exact_reader_cannot_substitute_a_different_norm():
    reader = service(norm_card_reader=lambda **_: {"status": "ok", "card": {
        "norm_key": "another", "norm_code": "ГЭСН99-01-002-01", "resources": []}})
    reader.register_shown_norm_cards([{"norm_key": "norm-immutable", "norm_code": NORM_CODE, "source_ref": "typed#norm"}])
    result = await reader.execute({"tool": "read_norm_card", "args": {"norm_key": "norm-immutable"}})
    assert result.payload["status"] == "conflict"
    assert result.chunks == ()


@pytest.mark.asyncio
async def test_incomplete_norm_resource_evidence_is_reported_without_default_consumption():
    reader = service(norm_card_reader=lambda **_: {"status": "ok", "card": {
        "norm_key": "norm-immutable", "norm_code": NORM_CODE, "source_ref": "typed#norm",
        "resources_complete": False, "resource_consumption_known": False, "resource_count": 2,
        "resources": [{"kind": "material", "code": RESOURCE_CODE, "unit": "m", "per_unit": None}]},
        "warnings": ["resource consumption column absent"]})
    reader.register_shown_norm_cards([{"norm_key": "norm-immutable", "norm_code": NORM_CODE, "source_ref": "typed#norm"}])
    result = await reader.execute({"tool": "read_norm_card", "args": {"norm_key": "norm-immutable"}})
    assert result.chunks[0].meta["resources_complete"] is False
    assert result.chunks[0].meta["resource_consumption_known"] is False
    assert result.payload["result"]["card"]["resources"][0]["per_unit"] is None
    assert result.payload["warnings"] == ["resource consumption column absent"]


@pytest.mark.asyncio
async def test_pricebook_search_returns_candidates_without_selecting_or_confirming_one():
    calls = []

    def provider(name):
        calls.append(name)
        return chosen_book()

    result = await service(price_basis=BASIS, pricebook_provider=provider).execute(
        {"tool": "search_pricebook_resources", "args": {"q": "Cable"}})
    assert calls == ["chosen-book"]
    assert len(result.chunks) == 2
    records = [json.loads(chunk.content) for chunk in result.chunks]
    assert {record["resource"]["code"] for record in records} == {RESOURCE_CODE, "20.4.01.01-0002"}
    assert records[0]["semantic_applicability"] == "model_decision_required"
    assert "confirmed_price" not in result.payload["result"]
    assert result.chunks[0].meta["global_evidence_id"].startswith("pricebook_")


@pytest.mark.asyncio
async def test_exact_resource_price_keeps_book_scope_and_literal_source_fields():
    reader = service(price_basis=BASIS, pricebook_provider=lambda _: chosen_book())
    result = await reader.execute({"tool": "read_resource_price", "args": {"code": RESOURCE_CODE}})
    body = json.loads(result.chunks[0].content)
    assert body["pricebook"] == "chosen-book"
    assert body["resource"]["price_current"] == 100
    assert body["resource"]["currency"] == "RUB" and body["resource"]["vat"] == "included"
    assert body["resource"]["source_date"] == "2026-09-22"
    assert result.chunks[0].meta["source_ref"] == (
        f"fgis_pricebook:chosen-book@sha256:{chosen_book().source_sha256}#resource={RESOURCE_CODE}")
    assert body["source_sha256"] == chosen_book().source_sha256
    assert result.chunks[0].meta["pricebook_sha256"] == body["source_sha256"]
    assert result.chunks[0].meta["minimum_evidence_body_chars"] == len(result.chunks[0].content)
    assert result.payload["decision_required_from_model"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("basis,args", [
    ({}, {"q": "Cable", "pricebook": "guessed-book"}),
    (BASIS, {"q": "Cable", "pricebook": "other-book"}),
    (BASIS, {"q": "Cable", "quarter": "2 квартал 2026 г."}),
    (BASIS, {"q": "Cable", "region": ["Selected region"]}),
])
async def test_missing_or_mismatched_task_price_scope_never_loads_a_book(basis, args):
    result = await service(price_basis=basis, pricebook_provider=lambda _: pytest.fail("wrong book must not load")).execute(
        {"tool": "search_pricebook_resources", "args": args})
    assert result.payload["status"] in {"missing", "conflict"}
    assert result.chunks == ()


@pytest.mark.asyncio
async def test_missing_resource_does_not_search_a_similar_resource_or_another_book():
    result = await service(price_basis=BASIS, pricebook_provider=lambda _: chosen_book()).execute(
        {"tool": "read_resource_price", "args": {"code": "unselected-code"}})
    assert result.payload["status"] == "missing"
    assert result.chunks == ()


@pytest.mark.asyncio
async def test_unavailable_or_mislabelled_chosen_book_stays_unpriced():
    reader = service(price_basis=BASIS, pricebook_provider=lambda _: None)
    result = await reader.execute({"tool": "read_resource_price", "args": {"code": RESOURCE_CODE}})
    assert result.payload["status"] == "missing"
    reader = service(price_basis=BASIS, pricebook_provider=lambda _: book_source(PriceBook(
        [{"code": RESOURCE_CODE, "unit": "m", "price_current": 100}], region="Other region", quarter=BASIS["quarter"])))
    result = await reader.execute({"tool": "read_resource_price", "args": {"code": RESOURCE_CODE}})
    assert result.payload["status"] == "conflict" and result.chunks == ()


@pytest.mark.asyncio
async def test_durable_price_basis_can_be_bound_after_service_construction():
    reader = service(pricebook_provider=lambda _: chosen_book())
    reader.set_price_basis(BASIS)
    result = await reader.execute({"tool": "read_resource_price", "args": {"code": RESOURCE_CODE}})
    assert result.payload["status"] == "ok"


@pytest.mark.asyncio
async def test_malformed_action_args_do_not_reach_fallback():
    result = await service().execute({"tool": "read_source", "args": []})
    assert result.payload["status"] == "missing" and result.chunks == ()


@pytest.mark.asyncio
async def test_document_search_preserves_explicit_filter_and_rejects_outside_documents():
    calls = []

    async def retrieve(**kwargs):
        calls.append(kwargs)
        return DocumentRetrieval()

    reader = service(retrieve=retrieve, retrieval_kwargs={"doc_filter": ["Selected.pdf"]})
    result = await reader.execute({"tool": "search_sources", "args": {"q": "offer", "target": "documents"}})
    assert calls[0]["doc_filter"] == ["Selected.pdf"]
    assert result.payload["status"] == "conflict" and result.chunks == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [{"dataset_id": "selected", "doc_name": "Other.pdf"}, {"doc_id": "offer-1"}])
async def test_read_source_cannot_expand_explicit_document_filter_via_name_or_shown_pointer(args):
    reader = service(retrieval_kwargs={"doc_filter": ["Selected.pdf"]})
    reader.register_shown_norm_cards(DocumentRetrieval().chunks)
    result = await reader.execute({"tool": "read_source", "args": args})
    assert result.payload["status"] == "conflict" and result.chunks == ()


@pytest.mark.asyncio
async def test_literal_document_scope_accepts_case_and_unicode_equivalence_without_basename_choice():
    calls = []

    def fallback(tool, args):
        calls.append(args)
        return {"status": "ok", "result": {"chunks": [{"text": "selected quote", "doc_name": "Café.pdf"}]}}

    reader = service(retrieval_kwargs={"doc_filter": ["Cafe\u0301.pdf"]}, fallback=fallback)
    result = await reader.execute({"tool": "read_source", "args": {"dataset_id": "selected", "doc_name": "CAFÉ.pdf"}})
    assert result.payload["status"] == "ok" and result.chunks[0].content == "selected quote"
    assert calls[0]["doc_name"] == "CAFÉ.pdf"
    outside = await reader.execute({"tool": "read_source", "args": {"dataset_id": "selected", "doc_name": "folder/Café.pdf"}})
    assert outside.payload["status"] == "conflict" and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("doc_filter", ["Offer.pdf", [None], [""]])
async def test_malformed_selected_document_filter_never_calls_shared_retrieval_or_reader(doc_filter):
    reader = service(retrieval_kwargs={"doc_filter": doc_filter})
    for call in ({"tool": "search_sources", "args": {"q": "offer", "target": "documents"}},
                 {"tool": "read_source", "args": {"dataset_id": "selected", "doc_name": "Offer.pdf"}}):
        result = await reader.execute(call)
        assert result.payload["status"] == "conflict" and result.chunks == ()


@pytest.mark.asyncio
async def test_price_reader_honors_actual_explicit_estimate_basis_aliases_and_period_token():
    from proxy.services.lsr_workbook_adapter_service import explicit_estimate_pricebook
    basis = explicit_estimate_pricebook(question_text="Санкт-Петербург, 3 квартал 2026",
                                       pricebooks=["sankt-peterburg_3kv2026"])
    book = PriceBook([{"code": RESOURCE_CODE, "unit": "m", "price_current": 100}],
                     region="Санкт-Петербург", quarter="3 квартал 2026 г.")
    reader = service(price_basis=basis, pricebook_provider=lambda name: book_source(book))
    result = await reader.execute({"tool": "read_resource_price", "args": {
        "code": RESOURCE_CODE, "region": "Санкт-Петербург", "quarter": "3 квартал 2026"}})
    assert result.payload["status"] == "ok"
    assert result.chunks[0].meta["region"] == basis["requested_region"]
    assert basis["requested_quarter"] == "3:2026"


@pytest.mark.parametrize("basis,args", [
    ({"pricebook": "chosen-book", "requested_region": "Selected region"}, {"code": RESOURCE_CODE, "region": "Other region"}),
    ({"pricebook": "chosen-book", "requested_quarter": "3:2026"}, {"code": RESOURCE_CODE, "quarter": "2 квартал 2026"}),
    ({**BASIS, "requested_region": "Other region"}, {"code": RESOURCE_CODE}),
    ({**BASIS, "requested_quarter": "2:2026"}, {"code": RESOURCE_CODE}),
    ({**BASIS, "actual_book": "other-book"}, {"code": RESOURCE_CODE}),
    ({**BASIS, "requested_region": ["malformed"]}, {"code": RESOURCE_CODE}),
    (BASIS, {"code": RESOURCE_CODE, "pricebook": "chosen_book"}),
])
def test_requested_price_aliases_and_literal_book_ids_cannot_silently_change_scope(basis, args):
    result = read_pricebook_evidence("read_resource_price", args, price_basis=basis,
                                   pricebook_provider=lambda name: pytest.fail("conflicting scope cannot load book"))
    assert result["status"] in {"missing", "conflict"} and not result["result"]["hits"]


def test_book_metadata_must_match_requested_basis_aliases_even_when_model_omits_scope():
    basis = {"pricebook": "chosen-book", "requested_region": "Selected region", "requested_quarter": "3:2026"}
    book = PriceBook([{"code": RESOURCE_CODE, "unit": "m", "price_current": 100}],
                     region="Other region", quarter="3 квартал 2026")
    result = read_pricebook_evidence("read_resource_price", {"code": RESOURCE_CODE}, price_basis=basis,
                                   pricebook_provider=lambda name: book_source(book))
    assert result["status"] == "conflict" and result["result"]["hits"] == []


def test_price_book_without_source_hash_is_visible_missing_not_false_cited_proof():
    result = read_pricebook_evidence("read_resource_price", {"code": RESOURCE_CODE}, price_basis=BASIS,
                                   pricebook_provider=lambda name: chosen_book().book)
    assert result["status"] == "missing" and result["result"]["hits"] == []
    assert result["missing"] == ["chosen pricebook source identity is unavailable"]


def test_stored_pricebook_hash_refuses_a_different_book_snapshot():
    result = read_pricebook_evidence("read_resource_price", {"code": RESOURCE_CODE},
                                   price_basis={**BASIS, "pricebook_sha256": "0" * 64},
                                   pricebook_provider=lambda name: chosen_book())
    assert result["status"] == "conflict" and not result["result"]["hits"]


def _file_book_fixture(tmp_path, monkeypatch):
    from proxy.services import fgis_price_service as prices
    source = tmp_path / "chosen-book.parquet"
    rows = [{"code": RESOURCE_CODE, "unit": "m", "price_current": 100}]

    def write_rows(items):
        source.write_text(json.dumps(items), encoding="utf-8")

    write_rows(rows)
    loads = []

    def load(cls, path):
        loads.append(path)
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), region=BASIS["region"], quarter=BASIS["quarter"])

    monkeypatch.setattr(prices.PriceBook, "from_parquet", classmethod(load))
    monkeypatch.setattr(prices, "resolve_pricebook_path", lambda book, **kw: str(source))
    prices.get_pricebook.cache_clear()
    return source, rows, write_rows, loads


def test_default_provider_binds_whole_file_hash_to_body_metadata_and_citation(tmp_path, monkeypatch):
    source, rows, write_rows, loads = _file_book_fixture(tmp_path, monkeypatch)
    result = read_pricebook_evidence("read_resource_price", {"code": RESOURCE_CODE}, price_basis=BASIS)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    hit = result["result"]["hits"][0]
    assert json.loads(hit["content"])["source_sha256"] == sha
    assert hit["meta"]["pricebook_sha256"] == sha
    assert hit["meta"]["source_hash_kind"] == "file_sha256"
    assert hit["meta"]["source_byte_size"] == source.stat().st_size
    assert f"@sha256:{sha}#resource={RESOURCE_CODE}" in hit["meta"]["source_ref"]
    assert result["sources"][0]["source_sha256"] == sha and len(loads) == 1


def test_same_book_name_with_changed_bytes_uses_new_official_snapshot_not_stale_rows(tmp_path, monkeypatch):
    source, rows, write_rows, loads = _file_book_fixture(tmp_path, monkeypatch)
    first = read_pricebook_evidence("read_resource_price", {"code": RESOURCE_CODE}, price_basis=BASIS)
    # Changing an uncited row still changes the identity of the entire book.
    write_rows([*rows, {"code": "other-resource", "unit": "m", "price_current": 250}])
    second = read_pricebook_evidence("read_resource_price", {"code": RESOURCE_CODE}, price_basis=BASIS)
    first_meta, second_meta = first["result"]["hits"][0]["meta"], second["result"]["hits"][0]["meta"]
    assert first_meta["pricebook_sha256"] != second_meta["pricebook_sha256"]
    assert first_meta["global_evidence_id"] != second_meta["global_evidence_id"]
    assert len(loads) == 2
    again = read_pricebook_evidence("read_resource_price", {"code": RESOURCE_CODE}, price_basis=BASIS)
    assert again["result"]["hits"][0]["meta"] == second_meta and len(loads) == 2


def test_file_change_during_official_pricebook_load_is_conflict_without_false_provenance(tmp_path, monkeypatch):
    from proxy.services import fgis_price_service as prices
    source, rows, write_rows, loads = _file_book_fixture(tmp_path, monkeypatch)

    def mutating_load(cls, path):
        book = cls(rows, region=BASIS["region"], quarter=BASIS["quarter"])
        write_rows([{**rows[0], "price_current": 200}])
        return book

    monkeypatch.setattr(prices.PriceBook, "from_parquet", classmethod(mutating_load))
    result = read_pricebook_evidence("read_resource_price", {"code": RESOURCE_CODE}, price_basis=BASIS)
    assert result["status"] == "conflict" and result["result"]["hits"] == []
    assert result["missing"] == ["selected pricebook changed during read"]
