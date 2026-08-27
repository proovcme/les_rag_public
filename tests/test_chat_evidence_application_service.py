import asyncio
import hashlib
import inspect
import json
import sqlite3
import time
from dataclasses import fields
from types import SimpleNamespace

import pytest

from proxy.routers import chat
from proxy.services import chat_evidence_application_service as service
from proxy.services.canonical_route_service import CanonicalRouteMode


def test_general_evidence_execution_is_outside_http_router():
    router_source = inspect.getsource(chat._run_chat)
    evidence_source = inspect.getsource(service._execute_chat_evidence_application)

    assert "retrieval_trace = retrieval.payload()" not in router_source
    assert "build_retrieval_evidence_packet(" not in router_source
    assert "async with gen_semaphore" not in router_source
    assert "retrieval_trace = retrieval.payload()" in evidence_source
    assert "build_retrieval_evidence_packet(" in evidence_source
    assert "async with gen_semaphore" in evidence_source


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
async def test_actual_chat_shadow_failure_preserves_legacy_answer_history_and_model_count(
    monkeypatch,
    tmp_path,
) -> None:
    model_calls = []
    shortlist_policies = []
    shadow_calls = []
    executor_codes = []
    legacy_calls = []
    history_rows = []
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
            system_text = str(json["messages"][0]["content"])
            if "исследовательским чтением LES" in system_text:
                model_calls.append("selector")
                return FakeResponse(
                    '{"calls":['
                    '{"tool":"read_source","args":{"doc_id":"d1"}},'
                    '{"tool":"read_source","args":{"doc_id":"d2"}}]}'
                )
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
            return {
                "schema": "les_tool_shortlist_v1",
                "tools": [{"name": "read_source"}],
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
            assert envelope.code == "TOOL_WOULD_EXECUTE"
            raise RuntimeError("secret shadow failure")

        def call(self, tool, args):
            legacy_calls.append((tool, dict(args)))
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
        chunks = []
        trace = SimpleNamespace(status="ok", error_code="")
        quality = SimpleNamespace(status="weak", top_score=0.0)

        def payload(self):
            return {"schema": "retrieval_trace_v1", "status": "ok"}

    class FakeWindows:
        chunks = []

        def payload(self):
            return {"schema": "context_windows_v1", "count": 0}

    runtime_config = SimpleNamespace(
        provider="mlx",
        model="fixture-model",
        base_url="http://fixture.invalid",
        chat_url="http://fixture.invalid/v1/chat/completions",
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

    monkeypatch.setattr(tool_harness_service, "harness", lambda: ExecutorBackedHarness())
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(service, "maybe_answer_table_query", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "dataset_memory_prompt_excerpt", lambda *_a, **_k: "")

    def save_history(**row):
        history_rows.append(row)
        return "history-1"

    request = service.EvidenceRequestContext(
        req=SimpleNamespace(
            question="Проверь документы",
            mode="rag",
            response_length="short",
            output_directive="",
            session_id="session-1",
            dataset_filter=None,
            project_id=0,
            reranker_enabled=None,
        ),
        dataset_ids=["selected"],
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
            "tools": ["read_source"],
            "rag_policy": {"iterative": False},
            "prompt_text": "Answer only from evidence.",
        },
    )
    runtime = service.EvidenceRuntimeDeps(
        state=state,
        rag_backend=SimpleNamespace(collection_name="fixture"),
        cache=SimpleNamespace(),
        cache_embedding=None,
        cache_marker="miss",
        cache_scope="",
        assistant_text=lambda message: str(message.get("content") or ""),
        augment_model_tool_args=lambda call, **_kwargs: call,
        chat_model_final_answer=lambda answer, status: (answer, status, {}),
        cloud_body_for_model=lambda body, *_args: body,
        compact_tool_result_for_prompt=lambda item, **_kwargs: item,
        dataset_ids_from_chunks=lambda _chunks: [],
        dataset_sensitivities=lambda _ids: [],
        env_bool=lambda _key, default=False: default,
        env_float=lambda _key, default=0.0: default,
        env_int=lambda key, default=0: 1 if key == "LES_CHAT_RESEARCH_MAX_ROUNDS" else default,
        expand_context_windows=lambda *_args, **_kwargs: FakeWindows(),
        format_tool_results_for_model=lambda rows: json.dumps(rows, ensure_ascii=False),
        generation_token_budget=lambda **_kwargs: 128,
        llm_runtime=lambda: runtime_config,
        local_context_budget=lambda **_kwargs: {
            "focus_max_chunks": 0,
            "context_max_chunks": 0,
            "context_chars_limit": 4000,
            "context_window_chars": 1000,
        },
        mlx_runtime=lambda: runtime_config,
        names_for_dataset_ids=lambda *_args: [],
        notebook_study_validation_status=lambda status, **_kwargs: status,
        ollama_native_complete=lambda *_args, **_kwargs: None,
        parse_model_tool_calls=lambda *_args, **_kwargs: [
            {"tool": "read_source", "args": {"doc_id": "d1"}},
            {"tool": "read_source", "args": {"doc_id": "d2"}},
        ],
        prepare_notebook_reader_memory=lambda *_args, **_kwargs: None,
        record_cloud_cost=lambda *_args, **_kwargs: None,
        retrieve_chat_chunks=lambda **_kwargs: _async_value(FakeRetrieval()),
        source_excerpts=lambda *_args, **_kwargs: [],
        table_query_response=lambda **_kwargs: None,
        cloud_fallback_models=lambda *_args: [],
        cloud_model_timeout=lambda: 1.0,
    )
    boundary = service.ResponseBoundary(
        save_chat_history=save_history,
        token_sink=None,
        version_stamp=lambda: {},
    )

    result = await service.run_chat_evidence_application(request, runtime, boundary)

    after_protected = protected_hash()
    assert result["answer"] == "legacy visible answer"
    assert model_calls == ["selector", "final"]
    assert shortlist_policies == [
        {
            "mode": "rag",
            "allowed_tools": ["read_source"],
            "limit": 64,
            "dataset_ids": ("selected",),
            "workflow_phase": "research",
            "model_preset": "qwen-9b",
            "runtime_available": frozenset({"read_source"}),
            "calls_remaining": 48,
            "result_chars_remaining": 35_000,
        }
    ]
    assert [call[1]["doc_id"] for call in shadow_calls] == ["d1"]
    assert executor_codes == ["TOOL_WOULD_EXECUTE"]
    assert [call[1]["doc_id"] for call in legacy_calls] == ["d1", "d2"]
    assert len(history_rows) == 1
    assert history_rows[0]["answer"] == "legacy visible answer"
    assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["status"] == "error"
    assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["attempted_calls"] == 1
    assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["pending_calls"] == 1
    assert "secret shadow failure" not in str(history_rows[0])
    assert after_protected == before_protected


async def _async_value(value):
    return value
