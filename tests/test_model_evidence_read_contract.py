import json
from types import SimpleNamespace

import pytest

from proxy.services.chat_evidence_application_service import (
    compact_estimator_draft_rows, parse_model_rag_result, model_read_frame_evidence,
    govern_inference_messages,
)
from proxy.services.model_evidence_read_contract import (
    MODEL_EVIDENCE_READ_INSTRUCTION, shown_evidence_registry,
)
from proxy.services.model_result_packet_service import admit_model_result_packet
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.context_governor_service import ContextRequiredSectionOverflow


def test_preview_count_does_not_claim_consumption_or_prove_missing_norm():
    instruction = MODEL_EVIDENCE_READ_INSTRUCTION
    assert "Обзор ресурсов, даже N из N" in instruction
    assert "не подтверждает их расходы" in instruction
    assert "либо явно оставь этот конкретный пробел" in instruction
    assert "Отсутствие цены не означает отсутствие нормы" in instruction
    assert "непрочитанный указатель не доказывает отсутствие подходящей нормы" in instruction


@pytest.mark.parametrize("representation", ["json", "table", "text"])
def test_authored_revision_survives_reader_and_packet_admission(representation):
    row = {"operation_id": "op_a", "expected_revision": 3,
           "source_row": "S!R2", "row_role": "work", "title": "Работа",
           "unit": "м", "quantity": 12, "norm_code": "MISSING", "open_gap": "Нужна карточка"}
    if representation == "json":
        answer = json.dumps({"rows": [row]}, ensure_ascii=False)
    elif representation == "table":
        answer = "\n".join(["|" + "|".join(row) + "|", "|" + "|".join("---" for _ in row) + "|",
                            "|" + "|".join(str(v) for v in row.values()) + "|"])
    else:
        answer = "\n".join(f"{k}: {v}" for k, v in row.items())
    result = parse_model_rag_result(answer)
    assert result is not None
    authored = compact_estimator_draft_rows(result[1])
    assert int(authored[0]["expected_revision"]) == 3
    admission = admit_model_result_packet(authored, packet_locators=["S!R2"],
                                         prior_operations=[{**row, "revision": 3}])
    assert len(admission.accepted_rows) == 1
    assert not admission.unapplied_proposals
    stale = admit_model_result_packet(authored, packet_locators=["S!R2"],
                                     prior_operations=[{**row, "revision": 4}])
    assert not stale.accepted_rows
    assert int(stale.unapplied_proposals[0]["decision"]["expected_revision"]) == 3


def test_requested_full_read_survives_restart_without_marking_rows_done(tmp_path):
    db = tmp_path / "reads.sqlite"
    service = WorkbookResearchJobService(db)
    identity = service.identity(session_id="s", attachment_id="a", source_sha256="f" * 64,
                                dataset_ids=[], profile_revision_id="r", model_identity="m",
                                question="ЛСР СПб 3 квартал 2026")
    job = service.begin_or_resume(identity)
    receipt = {"call": {"tool": "read_norm_card", "args": {"norm_key": "literal_key"}}, "status": "ok"}
    evidence = {"global_evidence_id": "full_card", "content": "exact resources and quantities",
                "meta": {"model_evidence_ref": "Q7.H1", "model_read_packet_id": "packet_a"}}
    before = job["stall_guard"]
    service.record_evidence_read(job["job_id"], packet_id="packet_a", evidence=[evidence], read_receipts=[receipt])
    service.record_evidence_read(job["job_id"], packet_id="packet_a", evidence=[evidence], read_receipts=[receipt])
    recovered = WorkbookResearchJobService(db).get(job["job_id"])
    assert recovered["accepted_rows"] == []
    assert recovered["stall_guard"] == before
    assert recovered["evidence"] == [evidence]
    assert recovered["task_context"]["model_evidence_reads"]["packet_a"] == [receipt]
    assert not any(e["event"] == "packet_checkpoint" for e in service.events_after(job["job_id"]))


def test_previous_searches_remain_addressable_with_literal_body_delivery():
    chunks = [SimpleNamespace(doc_name="catalog", content="body", meta={
        "global_evidence_id": "e1", "model_evidence_ref": "Q2.H1",
        "norm_code": "ГЭСН1", "norm_key": "key1", "source_ref": "source1"})]
    registry = shown_evidence_registry(chunks * 2)
    assert len(registry["previously_shown_evidence_registry"]) == 1
    pointer = registry["previously_shown_evidence_registry"][0]
    assert pointer["evidence_ref"] == "Q2.H1" and pointer["norm_key"] == "key1"
    assert pointer["content"] == "body" and pointer["body_available"] is True


def test_read_frame_preserves_source_and_decisions_without_duplicate_bodies():
    context = [{"source_rows": ["S!R2"], "prior_model_decisions": [{"operation_id": "op1"}],
                "previously_shown_cited_evidence": [{"content": "literal body"}]},
               {"previous_model_requested_exact_reads": [{"content": "literal body"}]}]
    chunk = SimpleNamespace(doc_name="source", content="literal body", meta={
        "model_evidence_ref": "Q1.H1", "global_evidence_id": "e1"})
    frame = model_read_frame_evidence(context, [chunk], [])
    assert frame[0]["source_rows"] == ["S!R2"]
    assert frame[0]["prior_model_decisions"] == [{"operation_id": "op1"}]
    assert json.dumps(frame).count("literal body") == 1
    assert "previously_shown_cited_evidence" in context[0]


@pytest.mark.parametrize("native", [False, True])
def test_read_frame_receipt_appears_once_in_its_real_protocol(native):
    from dataclasses import replace
    from proxy.services.model_evidence_read_service import native_evidence_read_exchange

    call = {"tool": "read_source", "args": {"source_row": "SOURCE!R2"}}
    if native:
        call["call_id"] = "literal_read_id"
    receipt = {"call": call, "status": "ok", "trace": {"literal_trace_marker": "x" * 2400}}
    exchanges = (native_evidence_read_exchange([call], [receipt]),) if native else ()
    chunk = SimpleNamespace(doc_name="source", content="FULL_LITERAL_BODY", meta={
        "model_evidence_ref": "Q1.H1", "global_evidence_id": "source_identity", "body_status": "full"})
    frame = model_read_frame_evidence(["literal source"], [chunk], [receipt], native_exchanges=exchanges)
    preset = ModelExecutionPreset(preset_id="receipt-once", model_family="fixture",
        input_token_limit=10_000, generation_reserve_tokens=0, safety_reserve_tokens=0,
        normal_tool_count=5, max_tools=5, max_batch_items=5, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=("test",))
    messages, packet = govern_inference_messages(preset=preset, profile_prefix="profile",
        request_payload="request", required_evidence=frame, native_exchanges=exchanges)
    serialized = json.dumps(messages)
    assert serialized.count("literal_trace_marker") == 1
    assert "FULL_LITERAL_BODY" in messages[1]["content"]
    if native:
        assert "model_requested_reads" not in messages[1]["content"]
        assert messages[-1]["role"] == "tool" and messages[-1]["tool_call_id"] == call["call_id"]
        assert json.loads(messages[-1]["content"]) == receipt
    else:
        assert len(messages) == 2 and "model_requested_reads" in messages[1]["content"]
    tight = replace(preset, input_token_limit=packet.included_tokens)
    governed, _ = govern_inference_messages(preset=tight, profile_prefix="profile", request_payload="request",
                                           required_evidence=frame, native_exchanges=exchanges)
    assert governed == messages


def test_mixed_read_frame_keeps_legacy_receipt_without_repeating_native_reply():
    from proxy.services.model_evidence_read_service import native_evidence_read_exchange

    call = {"call_id": "native_read", "tool": "read_source", "args": {"source_row": "SOURCE!R2"}}
    native = {"call": call, "status": "ok", "trace": {"native_receipt_marker": True}}
    legacy = {"call": {"tool": "read_source", "args": {"doc_id": "literal_doc"}},
              "status": "ok", "trace": {"legacy_receipt_marker": True}}
    exchange = native_evidence_read_exchange([call], [native])
    frame = model_read_frame_evidence(["literal source"], [], [native, legacy], native_exchanges=[exchange])
    encoded = json.dumps(frame)
    assert "native_receipt_marker" not in encoded and "legacy_receipt_marker" in encoded
    assert json.loads(exchange.replies[0].content) == native


def test_legacy_saved_exact_price_receipt_keeps_raw_body_required_on_tight_resume(monkeypatch):
    from proxy.services import chat_evidence_application_service as service
    price = SimpleNamespace(doc_name="quote.pdf", doc_id="doc", score=1.0, content="LITERAL_PRICE 25 m" + "x" * 3000,
                            meta={"global_evidence_id": "old-price", "model_evidence_ref": "Q8.H1",
                                  "model_read_packet_id": "packet", "resource_code": "literal-code",
                                  "pricebook": "literal-book", "model_delivery_status": "prepared", "body_status": "full"})
    discovery = SimpleNamespace(doc_name="catalog", doc_id="doc", score=1.0, content="OPTIONAL_DISCOVERY" + "y" * 8000,
                                meta={"global_evidence_id": "other", "model_evidence_ref": "Q9.H1", "body_status": "full"})
    receipt = {"call": {"tool": "read_resource_price", "args": {"code": "literal-code"}},
               "status": "ok", "evidence_refs": ["Q8.H1"], "evidence_bindings": {"Q8.H1": "old-price"}}
    preset = ModelExecutionPreset(preset_id="legacy-resume", model_family="fixture",
        input_token_limit=3000, generation_reserve_tokens=0, safety_reserve_tokens=0,
        normal_tool_count=5, max_tools=5, max_batch_items=5, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=("test",))
    original = dict(price.meta)
    real_govern = service.govern_inference_messages
    governed_inputs = []
    def record_govern(**kwargs):
        governed_inputs.append(kwargs)
        return real_govern(**kwargs)
    monkeypatch.setattr(service, "govern_inference_messages", record_govern)
    messages, packet, inventory, bodies = service.govern_model_read_messages(
        preset=preset, profile_prefix="profile", request_payload="original question",
        source_context=["original source"], chunks=[price, discovery], receipts=[receipt])
    assert packet.included_tokens <= packet.input_budget_tokens
    assert "Q8.H1" in bodies and "Q9.H1" not in bodies
    assert inventory == ["Q8.H1", "Q9.H1"]
    assert "LITERAL_PRICE" in messages[1]["content"] and "OPTIONAL_DISCOVERY" not in messages[1]["content"]
    # The saved literal tool receipt is authoritative even without the new
    # model_read_tool stamp. This body must survive optional-view omission.
    assert "LITERAL_PRICE" in json.dumps(governed_inputs[0]["required_evidence"])
    assert "LITERAL_PRICE" not in json.dumps(governed_inputs[0]["evidence"])
    assert price.meta == original and price.meta["global_evidence_id"] == "old-price"
    service.confirm_model_read_delivery([price, discovery], inventory_refs=inventory, body_refs=bodies)
    assert price.meta["model_delivery_status"] == "delivered"


@pytest.mark.asyncio
async def test_native_search_pointer_is_readable_only_after_actual_inventory_admission(monkeypatch):
    from proxy.services import chat_evidence_application_service as application
    from proxy.services import model_research_tool_service as research
    monkeypatch.setattr(research.nr_sp_service, "model_candidates", lambda **_kw: [])
    reads = []
    card = {"norm_key": "literal-key", "norm_code": "CODE-1", "source_ref": "literal-source",
            "title": "Literal title", "measure_unit": "m", "work_steps": ["Literal exact work"],
            "resources": [], "resource_count": 0, "resources_complete": True}
    def exact_reader(**kwargs):
        reads.append(kwargs)
        return {"status": "ok", "card": card}
    async def no_general_search(**_kwargs):
        pytest.fail("norm search must use the configured canonical route")
    tools = research.ModelResearchToolService(
        retrieve=no_general_search, frozen_dataset_ids=(), retrieval_kwargs={},
        fallback=lambda *_args: pytest.fail("fallback must not run"), norm_card_reader=exact_reader,
        smeta_norm_retrieve=lambda _q, **_kw: {"cards": [{**card, "resource_preview": [{
            "resource_code": "literal-preview", "name": "UNSHOWN_RAW_BODY" + "x" * 8000}]}],
            "retrieval_trace": {"rag": {"status": "ok"}}})
    search_call = {"tool": "search_sources", "args": {"q": "literal model query"}}
    search = await tools.execute(search_call)
    exact_call = {"tool": "read_norm_card", "args": {"norm_key": "literal-key", "norm_code": "CODE-1"}}
    # Both calls can belong to one native assistant batch. Search execution
    # alone has not put its result in any answer frame.
    premature = await tools.execute(exact_call)
    assert premature.payload["status"] == "conflict" and reads == []
    receipt = {"call": search_call, "status": "ok"}
    _, chunks, _ = application.bind_model_requested_read_evidence(
        [search], existing_chunks=[], evidence_namespace="literal-scope", receipts=[receipt])
    tools.register_shown_norm_cards(chunks)
    assert (await tools.execute(exact_call)).payload["status"] == "conflict" and reads == []
    preset = ModelExecutionPreset(preset_id="inventory-before-reader", model_family="fixture",
        input_token_limit=2000, generation_reserve_tokens=0, safety_reserve_tokens=0,
        normal_tool_count=5, max_tools=5, max_batch_items=5, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=("test",))
    messages, _, inventory, bodies = application.govern_model_read_messages(
        preset=preset, profile_prefix="profile", request_payload="original question",
        source_context=["original source"], chunks=chunks, receipts=[receipt])
    assert inventory and bodies == [] and "UNSHOWN_RAW_BODY" not in str(messages)
    application.confirm_model_read_delivery(chunks, [receipt], inventory_refs=inventory, body_refs=bodies)
    tools.register_shown_norm_cards(chunks)
    exact = await tools.execute(exact_call)
    assert exact.payload["status"] == "ok" and reads == [{"norm_key": "literal-key", "norm_code": "CODE-1"}]
    assert chunks[0].meta["model_delivery_status"] == "prepared"
    assert chunks[0].meta["model_inventory_delivery_status"] == "delivered"
    assert "Literal exact work" in exact.chunks[0].content


def test_large_shown_inventory_replays_without_verbose_registry_inflation():
    from proxy.services import chat_evidence_application_service as service
    from test_model_rag_grouped_evidence_service import _body, _rules

    rules = _rules()
    hits = []
    for index in range(150):
        meta = {"norm_key": f"immutable-{index}", "norm_code": f"CODE-{index}",
                "title": f"Literal candidate {index}", "measure_unit": "m",
                "source_ref": f"literal-source-{index}-" + "s" * 150,
                "edition": "exact-edition", "base_type": "fixture",
                "nr_sp_candidates": rules}
        hits.append((f"literal model query {index}", [SimpleNamespace(
            content=_body(rules, token=f"body-{index}", padding=1500),
            doc_name="catalog", doc_id="", score=1.0, meta=meta)]))
    groups, chunks, deferred = service.build_model_rag_evidence_groups(
        hits, max_chars=45_000, hits_per_query=1)
    assert deferred and any(c.meta["body_status"] == "full" for c in chunks)
    preset = ModelExecutionPreset(preset_id="inventory-replay", model_family="fixture",
        input_token_limit=100_000, generation_reserve_tokens=5000, safety_reserve_tokens=100,
        normal_tool_count=5, max_tools=5, max_batch_items=5, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=("test",))
    source = {"original_attachment_context": "literal original attachment",
              "source_rows": ["S!R2", "S!R3"], "prior_model_decisions": [{"operation_id": "op1"}]}
    _, initial = govern_inference_messages(preset=preset, profile_prefix="profile",
        request_payload="literal original question", required_evidence=[source, *groups])
    frame = model_read_frame_evidence([source], chunks, [])
    messages, replay = govern_inference_messages(preset=preset, profile_prefix="profile",
        request_payload="literal original question", required_evidence=frame)
    assert replay.included_tokens <= initial.included_tokens * 1.1
    text = "\n".join(message["content"] for message in messages)
    assert "literal original attachment" in text and "literal original question" in text
    registry = next(item for item in frame if isinstance(item, dict)
                    and "previously_shown_evidence_registry" in item)
    full_refs = {c.meta["model_evidence_ref"] for c in chunks if c.meta["body_status"] == "full"}
    assert {row["evidence_ref"] for row in registry["previously_shown_evidence_registry"]} == full_refs
    for chunk in chunks:
        if chunk.meta["body_status"] == "deferred_capacity":
            assert chunk.content in text
        else:
            assert chunk.content.splitlines()[-1] in text


def test_deferred_capacity_never_replays_an_unshown_raw_body():
    chunk = SimpleNamespace(doc_name="catalog", content="UNSHOWN FULL RESOURCE BODY", meta={
        "model_evidence_ref": "Q1.H1", "global_evidence_id": "immutable-deferred",
        "body_status": "deferred_capacity", "norm_key": "literal-key", "norm_code": "CODE-1",
        "title": "Literal identity", "source_ref": "literal-source", "measure_unit": "m"})
    frame = model_read_frame_evidence(["literal source row"], [chunk], [])
    text = json.dumps(frame, ensure_ascii=False)
    assert "UNSHOWN FULL RESOURCE BODY" not in text
    assert "Q1.H1" in text and "CODE-1" in text and "deferred_capacity" in text


def test_native_tool_schema_payload_reserves_capacity_without_text_duplication():
    preset = ModelExecutionPreset(preset_id="native-budget", model_family="fixture",
        input_token_limit=4000, generation_reserve_tokens=200, safety_reserve_tokens=100,
        normal_tool_count=5, max_tools=5, max_batch_items=5, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=("test",))
    schema = {"type": "function", "function": {"name": "read_source",
        "description": "UNIQUE_NATIVE_SCHEMA_MARKER " + "description " * 180,
        "parameters": {"type": "object"}}}
    messages, packet = govern_inference_messages(preset=preset, profile_prefix="profile",
        request_payload="request", native_tools=[schema], required_evidence=["complete body"])
    assert packet.provider_payload_tokens > 0
    assert packet.input_budget_tokens + packet.provider_payload_tokens == 3700
    assert "UNIQUE_NATIVE_SCHEMA_MARKER" not in json.dumps(messages)
    oversized = {"type": "function", "function": {"name": "read_source",
        "description": "x" * 20000, "parameters": {"type": "object"}}}
    with pytest.raises(ContextRequiredSectionOverflow):
        govern_inference_messages(preset=preset, profile_prefix="profile",
            request_payload="request", native_tools=[oversized], required_evidence=["complete body"])


def test_read_source_schema_exposes_current_attachment_row_without_file_selector():
    from proxy.services.model_evidence_read_contract import (
        MODEL_EVIDENCE_READ_INSTRUCTION, model_evidence_read_tool_schemas,
    )

    tool = next(item["function"] for item in model_evidence_read_tool_schemas()
                if item["function"]["name"] == "read_source")
    properties = tool["parameters"]["properties"]
    assert properties["source_row"] == {"type": "string"}
    assert {"doc_id", "dataset_id", "doc_name", "q"}.issubset(properties)
    assert not {"path", "attachment_id", "source_sha256"}.intersection(properties)
    assert tool["parameters"]["additionalProperties"] is False
    assert "source_row" in MODEL_EVIDENCE_READ_INSTRUCTION and "текущего вложения" in MODEL_EVIDENCE_READ_INSTRUCTION


@pytest.mark.asyncio
async def test_native_attachment_read_reaches_governed_frame_and_durable_immutable_receipt(tmp_path):
    from proxy.services import chat_evidence_application_service as service
    from proxy.services.model_evidence_read_contract import model_evidence_read_tool_schemas
    from proxy.services.model_evidence_read_service import run_model_evidence_read_turn
    from proxy.services.smeta_chat_adapter_service import _parse_model_tool_calls
    from test_model_research_tool_service import _attachment_catalog, _attachment_reader

    catalog = _attachment_catalog()
    tools = _attachment_reader(catalog, catalog.source_file_sha256)
    db = tmp_path / "attachment_native.sqlite"
    jobs = WorkbookResearchJobService(db)
    identity = jobs.identity(session_id="s", attachment_id="a", source_sha256=catalog.source_file_sha256,
                             dataset_ids=[], profile_revision_id="r", model_identity="m", question="literal request")
    job = jobs.begin_or_resume(identity)
    reads = []
    all_chunks = []
    frames = []
    preset = ModelExecutionPreset(preset_id="attachment-native", model_family="fixture",
        input_token_limit=20_000, generation_reserve_tokens=500, safety_reserve_tokens=100,
        normal_tool_count=5, max_tools=5, max_batch_items=5, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=("test",))

    async def on_read(receipts, results):
        groups, chunks, omitted = service.bind_model_requested_read_evidence(
            results, existing_chunks=all_chunks, evidence_namespace="table-packet:read",
            packet_id="table-packet", receipts=receipts)
        assert groups and not omitted
        reads.extend(receipts)
        all_chunks.extend(chunks)
        jobs.record_evidence_read(job["job_id"], packet_id="table-packet",
                                 evidence=[service.durable_evidence_record(c) for c in all_chunks],
                                 read_receipts=reads)

    async def continuation(receipts, _results, exchanges):
        messages, _packet = govern_inference_messages(
            preset=preset, profile_prefix="profile", request_payload="literal request",
            native_tools=model_evidence_read_tool_schemas(), native_exchanges=exchanges,
            required_evidence=model_read_frame_evidence([{"source_rows": ["PDF!R4"]}], all_chunks, receipts))
        frames.append(messages)
        return '{"rows": []}', {}

    call = {"call_id": "source_c1", "tool": "read_source", "args": {"source_row": "PDF_TEXT!R6"}}
    outcome = await run_model_evidence_read_turn(text=json.dumps({"calls": [call]}), usage={},
        parse_calls=_parse_model_tool_calls, execute=tools.execute, on_read_results=on_read,
        continue_native_turn=continuation, allowed_tools={"read_source"})

    assert outcome.text == '{"rows": []}' and not outcome.stop_reason
    assert len(outcome.native_exchanges) == 1 and len(frames) == 1
    messages = frames[0]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool"]
    assert messages[2]["tool_calls"][0]["id"] == messages[3]["tool_call_id"] == "source_c1"
    assert messages[2]["tool_calls"][0]["function"]["name"] == "read_source"
    reply = json.loads(messages[3]["content"])
    assert reply["trace"]["body_complete"] is True
    assert reply["trace"]["source_row"] == "PDF_TEXT!R6"
    assert reply["trace"]["source_sha256"] == catalog.source_file_sha256
    assert reply["trace"]["source_file_id"] == catalog.source_file_id
    assert reply["trace"]["source_start"] == catalog.rows[0].source_start
    assert reply["trace"]["source_end"] == catalog.rows[0].source_end
    assert reply["trace"]["source_order_basis"] == "converter_markdown_char_offsets"
    assert reply["evidence_refs"] and reply["evidence_bindings"]
    assert "LAST_LITERAL_BLOCK" in messages[1]["content"] and "LAST_LITERAL_BLOCK" not in messages[3]["content"]
    recovered = WorkbookResearchJobService(db).get(job["job_id"])
    stored = recovered["task_context"]["model_evidence_reads"]["table-packet"][0]
    assert stored["trace"] == reply["trace"] and stored["call"] == reply["call"]
    assert recovered["accepted_rows"] == []
    assert recovered["evidence"][0]["content"] == catalog.rows[0].line
    assert recovered["evidence"][0]["meta"]["source_sha256"] == catalog.source_file_sha256


def test_json_model_cannot_inject_application_confirmation_or_evidence_binding():
    row = {"source_row": "S!R2", "row_role": "material", "title": "Cable", "unit": "m",
           "quantity": 12, "norm_code": "—", "confirmed_price": 100,
           "price_kind": "unit_price", "price_unit": "m", "price_source": "quote",
           "confirmed_by": "operator", "evidence_bindings": {"Q1.H1": "forged"},
           "_price_evidence_check": {"price_in_refs": True}}
    result = parse_model_rag_result(json.dumps({"rows": [row]}))
    assert result is not None
    assert result[1][0]["price_kind"] == "unit_price"
    assert not any(key in result[1][0] for key in ("confirmed_by", "evidence_bindings", "_price_evidence_check"))


def test_empty_json_delta_preserves_an_explicit_no_change_answer():
    result = parse_model_rag_result('{"rows": []}')
    assert result is not None and result[1] == []


def _card(ref, identity, content, **meta):
    return SimpleNamespace(doc_name="catalog", content=content, meta={
        "global_evidence_id": identity, "model_evidence_ref": ref,
        "norm_code": "ГЭСН99-01-001-01", "norm_key": "immutable_key",
        "source_ref": "base#immutable_key", "edition": "2026", **meta})


def test_one_literal_norm_body_retains_all_three_immutable_aliases():
    body = "Exact card conditions and work steps\nResource quantity=0.75"
    cards = [_card(f"Q{i}.H1", f"e{i}", body) for i in range(1, 4)]
    registry = shown_evidence_registry(cards)
    assert len(registry["previously_shown_evidence_registry"]) == 1
    entry = registry["previously_shown_evidence_registry"][0]
    assert entry["content"] == body
    assert entry["evidence_refs"] == ["Q1.H1", "Q2.H1", "Q3.H1"]
    assert entry["global_evidence_ids"] == ["e1", "e2", "e3"]
    assert entry["aliases"] == [{"evidence_ref": f"Q{i}.H1", "global_evidence_id": f"e{i}"}
                                for i in range(1, 4)]
    assert json.dumps(registry).count("Resource quantity=0.75") == 1


@pytest.mark.parametrize("changed", [
    {"source_ref": "different-base#immutable_key"}, {"edition": "2027"},
    {"norm_key": "different_variant"}, {"norm_code": "ГЭСН99-01-001-02"},
    {"base_type": "other-base"},
])
def test_norm_source_edition_or_pointer_variants_never_collapse(changed):
    entries = shown_evidence_registry([
        _card("Q1.H1", "e1", "same literal body"),
        _card("Q2.H1", "e2", "same literal body", **changed),
    ])["previously_shown_evidence_registry"]
    assert len(entries) == 2
    assert [item["global_evidence_ids"] for item in entries] == [["e1"], ["e2"]]


def test_different_bodies_of_the_same_norm_pointer_remain_distinct():
    entries = shown_evidence_registry([
        _card("Q1.H1", "e1", "Variant A conditions"),
        _card("Q2.H1", "e2", "Variant B conditions"),
    ])["previously_shown_evidence_registry"]
    assert [item["content"] for item in entries] == ["Variant A conditions", "Variant B conditions"]


def test_verified_prefix_view_uses_only_longest_already_shown_literal_body():
    full = "Conditions: shared scope\nAll shown resources: 1, 2, 3"
    entries = shown_evidence_registry([
        _card("Q1.H1", "e1", "Conditions: shared scope…"),
        _card("Q2.H1", "e2", full),
    ])["previously_shown_evidence_registry"]
    assert len(entries) == 1 and entries[0]["content"] == full
    assert entries[0]["evidence_refs"] == ["Q1.H1", "Q2.H1"]


@pytest.mark.parametrize("target", ["Q1.H1", "global_evidence_id=e1"])
def test_shared_body_marker_resolves_the_actual_already_shown_original(target):
    original = _card("Q1.H1", "e1", "Original full conditions and resources")
    shared = _card("Q2.H1", "e2", f"То же содержимое и источник, что у {target}; см. показанный там текст.")
    entries = shown_evidence_registry([shared, original])["previously_shown_evidence_registry"]
    assert len(entries) == 1
    assert entries[0]["content"] == original.content
    assert entries[0]["body_available"] is True
    assert entries[0]["evidence_refs"] == ["Q2.H1", "Q1.H1"]


def test_shared_reference_does_not_fetch_a_body_from_a_different_source():
    original = _card("Q1.H1", "e1", "Actual conditions", source_ref="other-source")
    shared = _card("Q2.H1", "e2", "", shared_body_ref="Q1.H1")
    entries = shown_evidence_registry([original, shared])["previously_shown_evidence_registry"]
    assert entries[1]["content"] == ""
    assert entries[1]["body_available"] is False
    assert entries[1]["body_missing"] == "shared_body_unavailable"


def test_missing_and_cyclic_shared_bodies_are_explicitly_unavailable():
    cards = [_card("Q1.H1", "e1", "", shared_body_ref="Q2.H1"),
             _card("Q2.H1", "e2", "", shared_body_ref="Q1.H1"),
             _card("Q3.H1", "e3", "")]
    entries = shown_evidence_registry(cards)["previously_shown_evidence_registry"]
    assert len(entries) == 3
    assert all(item["content"] == "" and item["body_available"] is False for item in entries)
    assert [item["body_missing"] for item in entries] == [
        "shared_body_unavailable", "shared_body_unavailable", "shown_body_unavailable"]


@pytest.mark.parametrize("meta", [{"dataset_id": "selected", "doc_id": "doc-1"},
                                   {"resource_code": "literal-code", "pricebook": "bound-book"}])
def test_document_and_price_hits_keep_distinct_immutable_bodies_even_when_equal(meta):
    entries = shown_evidence_registry([SimpleNamespace(doc_name="source", content="same body", meta={
        "global_evidence_id": f"e{i}", "model_evidence_ref": f"Q{i}.H1", **meta}) for i in (1, 2)
    ])["previously_shown_evidence_registry"]
    assert len(entries) == 2
    assert [item["content"] for item in entries] == ["same body", "same body"]
