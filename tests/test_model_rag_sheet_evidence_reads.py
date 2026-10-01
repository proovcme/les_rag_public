"""Offline sheet-pass integration: model-owned reads reach the real XLSX executor."""

import asyncio
import hashlib
import json
import re
import time
from types import SimpleNamespace

import openpyxl
import pytest

from proxy.routers import chat
from proxy.services import chat_evidence_application_service as service
from proxy.services import fgis_price_service
from proxy.services.canonical_route_service import CanonicalRouteDecision, CanonicalRouteMode
from proxy.services.chat_attachment_service import preserve_read_attachment
from proxy.services.model_connection_contracts import ConnectionLocality, ConnectionRole
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.openai_compatible_transport_service import InferenceResponse


NORM_CODE = "ГЭСН99-01-001-01"
RESOURCE_A = "20.4.01.01-0001"
RESOURCE_B = "20.4.01.01-0002"
BOOK = "sankt-peterburg_3kv2026"


def _native(tool, **arguments):
    return {"id": tool + ":" + str(len(arguments)), "type": "function",
            "function": {"name": tool, "arguments": json.dumps(arguments, ensure_ascii=False)}}


def _answer(*, refs=("Q1.H1", "Q2.H1")):
    first, second = refs
    return (
        "Model-authored final rows\n\n"
        "| source_row | row_role | title | unit | quantity | norm_code | resource_code | evidence_refs |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        f"| S!R2 | material | Cable A | m | 12 | — | {RESOURCE_A} | {first} |\n"
        f"| S!R3 | material | Cable B | m | 3 | — | {RESOURCE_B} | {second} |"
    )


async def _run_sheet(tmp_path, monkeypatch, *, reads, variant="B1_CANDIDATE", unknown_tool=False,
                     reasoning_enabled=False, empty_final=False):
    # All stores, attachment bytes, norm cards and prices belong to this test.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(tmp_path / "attachments"))
    source = tmp_path / "source.xlsx"
    source_book = openpyxl.Workbook()
    source_book.active.title = "S"
    source_book.active.append(["Наименование", "Ед. изм.", "Количество"])
    source_book.active.append(["Cable A", "m", 12])
    source_book.active.append(["Cable B", "m", 3])
    source_book.save(source)
    source_book.close()
    attachment = preserve_read_attachment(source, attachment_id="read_123456abcdef",
                                         original_name="source.xlsx", root=tmp_path / "attachments")
    lookups = []
    book = fgis_price_service.PriceBook([
        {"code": RESOURCE_A, "name": "Cable A", "unit": "m", "price_current": 100},
        {"code": RESOURCE_B, "name": "Cable B", "unit": "m", "price_current": 200},
    ], region="Санкт-Петербург", quarter="3 квартал 2026 г.")
    real_lookup = book.lookup

    def lookup(code):
        lookups.append(code)
        return real_lookup(code)

    book.lookup = lookup
    monkeypatch.setattr(fgis_price_service, "available_pricebooks", lambda *a, **k: [BOOK + ".json"])

    def resolve_book(selected=None, **kwargs):
        assert kwargs.get("explicit_only") is True
        assert selected == BOOK
        return BOOK + ".json"

    monkeypatch.setattr(fgis_price_service, "resolve_pricebook_path", resolve_book)
    monkeypatch.setattr(fgis_price_service, "get_pricebook", lambda path: book)
    from proxy.services import model_pricebook_evidence_service as price_evidence
    source_bytes = json.dumps([real_lookup(RESOURCE_A), real_lookup(RESOURCE_B)], ensure_ascii=False).encode("utf-8")
    book.source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    book.source_name = BOOK + ".parquet"
    book.source_byte_size = len(source_bytes)
    monkeypatch.setattr(price_evidence, "_provider", lambda name: price_evidence.PriceBookEvidenceSource(
        book, book.source_sha256, book.source_name, book.source_byte_size))
    search_queries = []

    def norm_search(query, *, limit):
        search_queries.append(query)
        assert limit == 6
        return {"cards": [{"norm_key": "immutable-norm", "norm_code": NORM_CODE,
                           "title": "Synthetic exact norm", "measure_unit": "m",
                           "source_ref": "fixture#immutable-norm", "work_steps": ["Install"],
                           "resource_count": 24,
                           "resource_preview": [{"code": RESOURCE_A, "name": "Cable A", "unit": "m"},
                                                {"code": RESOURCE_B, "name": "Cable B", "unit": "m"}]}],
                "retrieval_trace": {"rag": {"status": "ok", "fusion": "native_rrf"}}}

    monkeypatch.setattr(service, "retrieve_smeta_norm_cards", norm_search)
    from proxy.smeta_core import norm_browser
    exact_reads = []
    full_resources = [{"kind": "material", "code": f"fixture-resource-{i}",
                       "name": f"Resource {i}", "unit": "m", "per_unit": i + 0.25}
                      for i in range(24)]
    full_resources[-2] = {"kind": "material", "code": RESOURCE_A, "name": "Cable A", "unit": "m", "per_unit": 12}
    full_resources[-1] = {"kind": "material", "code": RESOURCE_B, "name": "Cable B", "unit": "m", "per_unit": 3}

    def exact_card(**pointer):
        exact_reads.append(pointer)
        assert pointer == {"norm_key": "immutable-norm", "norm_code": NORM_CODE}
        return {"status": "ok", "schema": "smeta_exact_norm_card.v1", "missing": [], "warnings": [],
                "card": {"norm_key": "immutable-norm", "norm_code": NORM_CODE,
                         "title": "Synthetic exact norm", "measure_unit": "m", "work_steps": ["Install"],
                         "source_ref": "fixture#immutable-norm", "resource_count": 24,
                         "resources": full_resources, "resources_returned": 24,
                         "resources_complete": True, "resource_consumption_known": True}}

    monkeypatch.setattr(norm_browser, "read_norm_card_exact", exact_card)
    preset = ModelExecutionPreset(preset_id="fixture-sheet", model_family="fixture",
                                  input_token_limit=100_000, generation_reserve_tokens=5000,
                                  safety_reserve_tokens=100, normal_tool_count=6, max_tools=6,
                                  max_batch_items=6, parallel_read_limit=1, reasoning_enabled=False,
                                  reasoning_supported=True,
                                  source_chain=("test",))
    connection = SimpleNamespace(connection_id="conn:sheet", revision_id="conn:sheet:r1",
                                 display_name="Offline sheet model", model_id="fixture-model",
                                 locality=ConnectionLocality.LOOPBACK, base_url="http://127.0.0.1:1919/v1",
                                 secret_ref=None, effective_preset=preset)

    class Resolver:
        def resolve(self, role, **kwargs):
            assert role is ConnectionRole.ANSWER
            return connection

        def resolve_fallback(self, *args, **kwargs):
            pytest.fail("offline model must not use fallback")

    responses = [InferenceResponse(text="S!R2 — Cable A\nS!R3 — Cable B", tool_calls=(),
                                   finish_reason="stop", usage={})]
    if unknown_tool:
        responses.append(InferenceResponse(text="", tool_calls=(_native("not_a_reader", code=RESOURCE_A),),
                                          finish_reason="tool_calls", usage={}))
    elif reads:
        responses.extend([
            InferenceResponse(text="", tool_calls=(_native("read_norm_card", norm_key="immutable-norm"),),
                              finish_reason="tool_calls", usage={}),
            InferenceResponse(text="", tool_calls=(_native("read_resource_price", code=RESOURCE_A),
                                                    _native("read_resource_price", code=RESOURCE_B)),
                              finish_reason="tool_calls", usage={}),
        ])
    def final_response():
        # The model fixture uses the source addresses actually assigned to the
        # two book reads, including any candidate groups shown before them.
        refs = (f"Q{len(search_queries) + 2}.H1", f"Q{len(search_queries) + 3}.H1") if reads else ("Q1.H1", "Q2.H1")
        return InferenceResponse(text="" if empty_final else _answer(refs=refs), tool_calls=(),
                                 finish_reason="length" if empty_final else "stop",
                                 usage={"completion_tokens": 120})

    if not unknown_tool:
        responses.append(final_response)
    requests = []

    class Transport:
        async def complete(self, selected, request):
            assert selected.revision_id == connection.revision_id
            requests.append(request)
            assert responses, "harness forced another model cycle after final rows"
            response = responses.pop(0)
            return response() if callable(response) else response

    monkeypatch.setattr(service, "resolve_canonical_route", lambda **kw: CanonicalRouteDecision(
        requested=CanonicalRouteMode.ACTIVE, effective=CanonicalRouteMode.ACTIVE,
        source="test", reason="offline fixture", restart_required=False))
    monkeypatch.setattr(service, "maybe_answer_table_query", lambda *a, **k: None)
    monkeypatch.setattr(service, "dataset_memory_prompt_excerpt", lambda *a, **k: "")
    monkeypatch.setattr(service, "rules_pre_verdict", lambda *a, **k: pytest.fail("no semantic validator"))
    state = SimpleNamespace(reranker_available=False, reranker_cls=None, llm_semaphore=asyncio.Semaphore(1),
                            metrics_cache={}, crag_stats={"no_data": 0, "hallucination": 0, "verified": 0},
                            chat_metrics={"latency_search": [], "latency_gen": [], "tokens": [], "crag_fail": 0})
    config = SimpleNamespace(provider="mlx", model="fixture-model", base_url="http://fixture.invalid",
                             chat_url="http://fixture.invalid/v1/chat/completions", api_key="",
                             supports_validation=False)
    executions = []

    async def execute_workbook(call, context, progress):
        result = await chat._execute_chat_workbook_tool(call, context, progress)
        executions.append((call, result))
        return result

    def no_shared_retrieval(**kwargs):
        pytest.fail("norm queries must not use the document retriever")

    runtime = service.EvidenceRuntimeDeps(
        state=state, rag_backend=SimpleNamespace(collection_name="fixture"), cache=SimpleNamespace(),
        cache_embedding=None, cache_marker="miss", cache_scope="",
        assistant_text=lambda message: str(message.get("content") or ""),
        augment_model_tool_args=lambda call, **kw: call,
        chat_model_final_answer=lambda answer, status: (answer, status, {}),
        cloud_body_for_model=lambda body, *a: body,
        compact_tool_result_for_prompt=lambda item, **kw: item,
        dataset_ids_from_chunks=lambda chunks: [], dataset_sensitivities=lambda ids: [],
        env_bool=lambda key, default=False: default, env_float=lambda key, default=0: default,
        env_int=lambda key, default=0: default,
        expand_context_windows=lambda chunks, *a, **kw: SimpleNamespace(chunks=chunks, payload=lambda: {}),
        format_tool_results_for_model=lambda rows: json.dumps(rows, ensure_ascii=False),
        generation_token_budget=lambda **kw: 5000, llm_runtime=lambda: config,
        local_context_budget=lambda **kw: {"focus_max_chunks": 0, "context_max_chunks": 0,
                                          "context_chars_limit": 300_000, "context_window_chars": 1000},
        mlx_runtime=lambda: config, names_for_dataset_ids=lambda *a: [],
        notebook_study_validation_status=lambda status, **kw: status,
        ollama_native_complete=lambda *a, **kw: pytest.fail("unbound model call"),
        parse_model_tool_calls=chat._parse_model_tool_calls,
        prepare_notebook_reader_memory=lambda *a, **kw: None, record_cloud_cost=lambda *a, **kw: None,
        retrieve_chat_chunks=no_shared_retrieval, source_excerpts=lambda *a, **kw: [],
        table_query_response=lambda **kw: None, cloud_fallback_models=lambda runtime: [],
        cloud_model_timeout=lambda: 1, model_connection_resolver=lambda: (Resolver(), object()),
        model_connection_transport=lambda client, secret_store: Transport(),
        workbook_tool_executor=execute_workbook,
    )
    request = service.EvidenceRequestContext(
        req=SimpleNamespace(question="Собери ЛСР; ВОР не создавай. Санкт-Петербург, 3 квартал 2026",
                            mode="estimator", response_length="short", output_directive="", session_id="sheet-session",
                            dataset_filter=None, project_id=0, attachment_id=attachment["attachment_id"],
                            attachment_context="Cable A — 12 m; Cable B — 3 m", candidate_acceptance=False,
                            reranker_enabled=None, comparative_acceptance_variant=variant),
        dataset_ids=["selected"], effective_dataset_filter="", resolved_dataset_names=[], dataset_name_by_id={},
        query_route_payload={"channel": "rag"}, target_doc_filter=[], target_file_ref=None, topic_doc_filter=[],
        topic_retrieval_plan=None, inventory_requested=False, study_requested=False, memory_block="", session_block="",
        class_suggestions=[], use_semantic_cache=False, use_validation=False, validation_skip_reason="test",
        route=SimpleNamespace(intent="rag"), table_result=None, request_started_at=time.time(),
        profile_snapshot={"revision_id": "fixture-profile:1", "mode": "estimator",
                          "model_policy": {"reasoning_enabled": reasoning_enabled},
                          "tools": ["search_sources", "build_lsr_workbook"],
                          "rag_policy": {"iterative": True, "system_datasets": ["smeta"],
                                         "model_authored_initial_query": True},
                          "prompt_text": "Answer only from shown evidence."},
    )
    histories = []
    result = await service.run_chat_evidence_application(request, runtime, service.ResponseBoundary(
        save_chat_history=lambda **row: histories.append(row) or "history-sheet", token_sink=None,
        version_stamp=lambda: {}))
    return SimpleNamespace(result=result, executions=executions, requests=requests, responses=responses,
                           exact_reads=exact_reads, lookups=lookups, queries=search_queries, histories=histories)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_native_sheet_reads_keep_full_resources_distinct_price_arguments_and_real_workbook(tmp_path, monkeypatch, variant):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant)
    assert len(run.requests) == 4 and not run.responses
    for name in ("read_norm_card", "search_pricebook_resources", "read_resource_price", "read_source"):
        assert name in str(run.requests[1].tools)
    assert len(run.exact_reads) == 1
    registries = []
    for message in run.requests[2].messages:
        for line in message["content"].splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and "previously_shown_evidence_registry" in item:
                registries.extend(item["previously_shown_evidence_registry"])
    full_card = next(item["content"] for item in registries if "fixture-resource-21" in item["content"])
    assert '"per_unit": 21.25' in full_card and "resources_complete=True" in full_card
    assert sum("fixture-resource-21" in item["content"] for item in registries) == 1
    assert RESOURCE_A in str(run.requests[3].messages) and RESOURCE_B in str(run.requests[3].messages)
    # Same tool name with different literal codes must execute both reads.
    assert run.lookups.count(RESOURCE_A) == 2
    assert run.lookups.count(RESOURCE_B) == 2
    assert len(run.executions) == 1
    call, receipt = run.executions[0]
    assert call["tool"] == "build_lsr_workbook" and receipt["status"] == "complete"
    rows = call["args"]["decisions"]
    assert [(row["source_row"], row["resource_code"], row["quantity"]) for row in rows] == [
        ("S!R2", RESOURCE_A, 12), ("S!R3", RESOURCE_B, 3)]
    assert all(row["evidence_bindings"] for row in rows)
    assert all("confirmed_price" not in row for row in rows)
    assert receipt["calculated_positions"] == 2
    assert receipt["confirmed_amount"] == 1800 and receipt["preliminary_amount"] == 0
    from proxy.services.artifact_revision_service import ArtifactRevisionStore
    artifacts = ArtifactRevisionStore(tmp_path / "storage/artifacts/meta.db", tmp_path / "storage/artifacts/files")
    output = artifacts.resolve_path(receipt["artifact"]["revision_id"])
    rendered = openpyxl.load_workbook(output, data_only=False)
    try:
        sheet = rendered["ЛСР РИМ"]
        for code, quantity, price in ((RESOURCE_A, 12, 100), (RESOURCE_B, 3, 200)):
            row = next(cells[1].row for cells in sheet.iter_rows() if cells[1].value == code)
            assert sheet.cell(row, 7).value == quantity
            assert sheet.cell(row, 10).value == price
            assert sheet.cell(row, 12).value == f"=ROUND(G{row}*J{row}*K{row},2)"
    finally:
        rendered.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_plain_final_sheet_rows_do_not_force_an_evidence_read_cycle(tmp_path, monkeypatch, variant):
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant)
    assert len(run.requests) == 2 and not run.responses
    assert run.exact_reads == []
    assert len(run.executions) == 1
    assert run.executions[0][1]["status"] == "complete"
    assert [row["resource_code"] for row in run.executions[0][0]["args"]["decisions"]] == [RESOURCE_A, RESOURCE_B]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_unknown_native_reader_never_becomes_a_terminal_workbook(tmp_path, monkeypatch, variant):
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant, unknown_tool=True)
    assert len(run.requests) == 2 and not run.responses
    assert run.executions == []
    trace = run.result["retrieval_trace"]
    assert run.result["model_connection"]["pending_tool_calls"] == 1
    if variant == "B0_DIRECT":
        assert trace["tool_loop"]["evidence_read_stop"] == "evidence_read_unknown_tool"
    else:
        assert "evidence_read_unknown_tool" in str(trace)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("reasoning_enabled", [False, True])
async def test_bound_sheet_profile_reasoning_reaches_every_existing_model_turn(tmp_path, monkeypatch, variant, reasoning_enabled):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant,
                           reasoning_enabled=reasoning_enabled)
    assert len(run.requests) == 4 and not run.responses
    assert all(request.reasoning_enabled is reasoning_enabled for request in run.requests)
    assert len(run.executions) == 1
    final_prompt = str(run.requests[-1].messages)
    assert ("/no_think" in final_prompt) is (not reasoning_enabled)
    reasoning = run.result["retrieval_trace"]["model_execution_profile"]["reasoning"]
    assert reasoning == {"requested": reasoning_enabled, "effective": reasoning_enabled,
                         "source": "profile_model_policy", "restart_required": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_reasoning_without_final_length_stops_without_workbook_or_new_model_turn(tmp_path, monkeypatch, variant):
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
                           reasoning_enabled=True, empty_final=True)
    assert len(run.requests) == 2 and not run.responses
    assert run.executions == []
    assert run.result["retrieval_trace"]["model_generation"] == {
        "status": "technical_pending", "reason": "model_final_output_missing", "finish_reason": "length"}
