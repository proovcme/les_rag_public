"""Actual governed producers share one opt-in source frame; no model/network."""
import dataclasses
import json
import os
from pathlib import Path

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services import runtime_config_registry_service as registry
from proxy.services.model_source_frame_service import SOURCE_MODEL_RENDER_SCHEMA
from test_model_rag_sheet_evidence_reads import _run_sheet


FACTOR = "LES_CHAT_SOURCE_FRAME_ROWS"


async def _run_frame(tmp_path, monkeypatch, *, cap=2, first_answer_source_read=None, **kwargs):
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv(FACTOR, raising=False)
    original = service.run_chat_evidence_application
    wire_requests = []
    captured_request = []

    async def configured(request, runtime, boundary):
        captured_request.append(request)
        prior = runtime.env_int
        configured_runtime = dataclasses.replace(runtime, env_int=lambda key, default=0:
            (cap() if callable(cap) else cap) if key == FACTOR else prior(key, default))
        if first_answer_source_read:
            original_transport = runtime.model_connection_transport

            class Transport:
                def __init__(self, *args):
                    self.inner = original_transport(*args)

                def __getattr__(self, name):
                    return getattr(self.inner, name)

                async def complete(self, connection, request):
                    wire_requests.append(request)
                    if len(wire_requests) == 2:
                        from test_model_rag_sheet_evidence_reads import _native
                        return service.InferenceResponse(text="", finish_reason="tool_calls", usage={},
                            tool_calls=(_native("read_source", source_row=first_answer_source_read),))
                    return await self.inner.complete(connection, request)

            configured_runtime = dataclasses.replace(configured_runtime, model_connection_transport=Transport)
        return await original(request, configured_runtime, boundary)

    monkeypatch.setattr(service, "run_chat_evidence_application", configured)
    run = await _run_sheet(tmp_path, monkeypatch, **kwargs)
    run.wire_requests = wire_requests
    run.request = captured_request[0]
    return run


def _frames(request):
    found = []
    for message in request.messages:
        for line in str(message.get("content") or "").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("schema") == SOURCE_MODEL_RENDER_SCHEMA:
                found.append(item)
    return found


def _unshown(frame):
    assert frame["available_not_shown_selector"] == "source_manifest.records minus requested_source_rows and reference_source_rows"
    return {row[0] for row in frame["source_manifest"]["records"]} - set(frame["requested_source_rows"]) - set(frame["reference_source_rows"])


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_actual_first_query_and_answer_share_frozen_frame(tmp_path, monkeypatch, variant):
    run = await _run_frame(tmp_path, monkeypatch, reads=True, variant=variant)
    query_frame = _frames(run.requests[0])
    answer_frame = _frames(run.requests[1])
    assert len(query_frame) == len(answer_frame) == 1
    assert query_frame == answer_frame
    assert query_frame[0]["requested_source_rows"] == ["S!R2", "S!R3"]
    assert "Собери ЛСР; ВОР не создавай. Санкт-Петербург, 3 квартал 2026" in str(run.requests[0].messages)
    assert run.requests[0].tools == ()
    assert "read_source" in {tool["function"]["name"] for tool in run.requests[1].tools}
    assert "original_attachment_context" not in str(run.requests[1].messages)
    assert "fixture-resource-21" in str(run.requests[-1].messages)
    trace = run.result["retrieval_trace"]["model_source_frames"]
    assert trace[0]["source_frame_sha256"] == query_frame[0]["source_frame_sha256"]
    assert trace[0]["requested_scope_sha256"] == query_frame[0]["requested_scope_sha256"]
    assert trace[0]["model_render_sha256"] == query_frame[0]["model_render_sha256"]
    assert trace[0]["model_render_bytes"] > 0
    assert set(trace[0]["available_not_shown_locators"]) == _unshown(query_frame[0])
    assert trace[0]["model_delivery_status"] == "delivered"


@pytest.mark.asyncio
async def test_each_actual_packet_preserves_full_document_denominator_and_manifest(tmp_path, monkeypatch):
    run = await _run_frame(tmp_path, monkeypatch, reads=True, packet_count=2)
    frames = [_frames(request)[0] for request in run.requests if _frames(request)]
    assert {tuple(frame["requested_source_rows"]) for frame in frames} == {
        ("S!R2", "S!R3"), ("S!R4", "S!R5")}
    assert len({frame["source_manifest"]["source_file_sha256"] for frame in frames}) == 1
    assert all({row[0] for row in frame["source_manifest"]["records"]} == {
        "S!R1", "S!R2", "S!R3", "S!R4", "S!R5"} for frame in frames)
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService
    store = WorkbookResearchJobService()
    job = store.get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert job["task_context"]["source_frame"]["rows_per_frame"] == 2
    assert len(job["task_context"]["_source_catalog_locators"]) == 4
    assert {row["source_row"] for row in job["accepted_rows"]} == {"S!R2", "S!R3", "S!R4", "S!R5"}
    before = list(run.requests)
    rows = job["accepted_rows"]
    await run.resume_same_request()
    assert run.requests == before
    assert store.get(job["job_id"])["accepted_rows"] == rows


@pytest.mark.asyncio
async def test_zero_keeps_legacy_source_body_and_checkpoint_identity(tmp_path, monkeypatch):
    run = await _run_frame(tmp_path, monkeypatch, cap=0, reads=True)
    assert not any(_frames(request) for request in run.requests)
    assert "original_attachment_context" in str(run.requests[1].messages)
    assert "model_source_frames" not in run.result["retrieval_trace"]
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService
    job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert "source_frame" not in job["task_context"]
    assert "source_frame_contract_sha256" not in job["identity"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", [-1, 13, True])
async def test_invalid_frame_mode_fails_before_any_generation(tmp_path, monkeypatch, cap):
    with pytest.raises(service.HTTPException, match="SOURCE_FRAME_ROWS_INVALID"):
        await _run_frame(tmp_path, monkeypatch, cap=cap, reads=False)


def test_frame_factor_is_gui_visible_with_effective_default_and_no_restart(monkeypatch):
    monkeypatch.delenv(FACTOR, raising=False)
    registry.declared_env_defaults.cache_clear()
    factor = registry._factor(FACTOR, {})
    assert factor["effective_value"] == factor["declared_default"] == "0"
    assert factor["secret"] is False and factor["mutable"] is True
    assert factor["restart_required"] is False
    assert "1–12" in factor["help_text"] and "токен" in factor["help_text"]


@pytest.mark.asyncio
async def test_actual_branches_receive_same_bytes_same_bound_id_and_first_scope(tmp_path, monkeypatch):
    import test_model_rag_sheet_evidence_reads as fixture
    preserved = fixture.preserve_read_attachment
    exact_bytes = []

    def shared_bytes(source, **kwargs):
        # Only this synthetic workbook: both controls must bind identical bytes.
        if exact_bytes:
            Path(source).write_bytes(exact_bytes[0])
        else:
            exact_bytes.append(Path(source).read_bytes())
        return preserved(source, **kwargs)

    monkeypatch.setattr(fixture, "preserve_read_attachment", shared_bytes)
    with monkeypatch.context() as baseline_patch:
        baseline = await _run_frame(tmp_path / "baseline", baseline_patch, reads=True,
                                    variant="B0_DIRECT", packet_count=2)
    with monkeypatch.context() as candidate_patch:
        candidate = await _run_frame(tmp_path / "candidate", candidate_patch, reads=True,
                                     variant="B1_CANDIDATE", packet_count=2)
    assert _frames(baseline.requests[0]) == _frames(candidate.requests[0])
    assert _frames(baseline.requests[1]) == _frames(candidate.requests[1])
    assert baseline.declared_queries[:2] == candidate.declared_queries[:2]
    assert baseline.requests[0].max_output_tokens == candidate.requests[0].max_output_tokens
    assert baseline.requests[1].max_output_tokens == candidate.requests[1].max_output_tokens


@pytest.mark.asyncio
async def test_actual_frame_bound_reader_reaches_unshown_rows_without_retrieval(tmp_path, monkeypatch):
    created = []
    original_reader = service.ModelResearchToolService

    def capture_reader(*args, **kwargs):
        reader = original_reader(*args, **kwargs)
        created.append(reader)
        return reader

    monkeypatch.setattr(service, "ModelResearchToolService", capture_reader)
    run = await _run_frame(tmp_path, monkeypatch, reads=True, variant="B0_DIRECT", packet_count=2)
    frame = _frames(run.requests[0])[0]
    assert {"S!R4", "S!R5"} <= _unshown(frame)
    assert len(created) == 1
    for record in frame["source_manifest"]["records"]:
        read = await created[0].execute({"tool": "read_source", "args": {"source_row": record[0]}})
        assert read.payload["status"] == "ok"
        assert read.payload["trace"]["body_complete"] is True
        assert read.chunks[0].content == created[0]._attachment_catalog.lookup(record[0]).line
    assert run.queries == run.declared_queries[:2]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_actual_model_read_source_request_reaches_unshown_frame_row(tmp_path, monkeypatch, variant):
    run = await _run_frame(tmp_path, monkeypatch, reads=True, variant=variant, packet_count=2,
                           first_answer_source_read="S!R4")
    frame = _frames(run.wire_requests[1])[0]
    assert "S!R4" in _unshown(frame)
    delivered = run.wire_requests[2].messages
    literal = service.load_catalog_from_attachment_id("read_123456abcdef").lookup("S!R4").line
    registries = []
    for message in delivered:
        for line in str(message.get("content") or "").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                registries.extend(item.get("previously_shown_evidence_registry", []))
    assert any(row["content"] == literal for row in registries)
    calls = [call for message in delivered for call in message.get("tool_calls", ())
             if call["function"]["name"] == "read_source"]
    assert len(calls) == 1
    assert any(message["role"] == "tool" and message.get("tool_call_id") == calls[0]["id"]
               and json.loads(message["content"])["status"] == "ok" for message in delivered)
    assert _frames(run.wire_requests[2]) == [frame]
    reads = run.result["retrieval_trace"]["tool_loop"]["evidence_reads"]
    exact = [read for read in reads if read["call"]["tool"] == "read_source"]
    assert len(exact) == 1 and exact[0]["model_delivery_status"] == "delivered"
    assert exact[0]["call"]["args"] == {"source_row": "S!R4"}
    if variant == "B1_CANDIDATE":
        assert any(_frames(request)[0]["requested_source_rows"] == ["S!R4", "S!R5"]
                   for request in run.wire_requests if _frames(request))


@pytest.mark.asyncio
async def test_same_frame_capacity_resume_retains_literals_without_researching_again(tmp_path, monkeypatch):
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService
    run = await _run_frame(tmp_path, monkeypatch, reads=True, query_count=2, input_token_limit=30_000,
                           candidate_padding=1000, native_read_batch=True, exact_resource_padding=40_000)
    store = WorkbookResearchJobService()
    job_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    paused = store.get(job_id)
    assert paused["accepted_rows"] == []
    assert paused["task_context"]["source_frame"]["rows_per_frame"] == 2
    saved = [row for row in paused["evidence"] if row["meta"].get("model_read_packet_id")]
    assert saved and "x" * 40_000 in str(saved)
    old_queries, old_reads, old_requests = list(run.queries), len(run.exact_reads), len(run.requests)
    run.responses[:] = []
    resumed = await run.resume_same_request()
    assert run.queries == old_queries and len(run.exact_reads) == old_reads and len(run.requests) == old_requests
    assert resumed["retrieval_trace"]["source_frame"] == run.result["retrieval_trace"]["source_frame"]
    assert resumed["retrieval_trace"]["context_governor"]["error"]["overflow_tokens"] > 0
    restored = {row["global_evidence_id"]: row for row in store.get(job_id)["evidence"]}
    assert all(restored[row["global_evidence_id"]]["content"] == row["content"] for row in saved)


@pytest.mark.asyncio
async def test_actual_plain_resume_after_scope_change_stops_before_model_and_keeps_old_job(tmp_path, monkeypatch):
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService
    cap = [2]
    run = await _run_frame(tmp_path, monkeypatch, cap=lambda: cap[0], reads=True)
    store = WorkbookResearchJobService()
    job_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    old = store.get(job_id)
    old_calls, old_queries = len(run.requests), list(run.queries)
    cap[0] = 3
    run.request.req.question = "Продолжи это же задание по тому же прикреплённому документу."
    with pytest.raises(service.HTTPException) as error:
        await run.resume_same_request()
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "SOURCE_FRAME_CONTINUATION_SCOPE_CHANGED"
    assert len(run.requests) == old_calls and run.queries == old_queries
    unchanged = store.get(job_id)
    assert unchanged["accepted_rows"] == old["accepted_rows"]
    assert unchanged["task_context"]["price_basis"] == old["task_context"]["price_basis"]


@pytest.mark.asyncio
async def test_frame_mode_keeps_full_shown_rag_body_and_native_exchange(tmp_path, monkeypatch):
    run = await _run_frame(tmp_path, monkeypatch, reads=True, candidate_padding=12000,
                           exact_resource_padding=12000, native_reasoning="fixture-private-reasoning")
    first_answer = str(run.requests[1].messages)
    assert "x" * 12000 in first_answer
    last = run.requests[-1].messages
    assert "x" * 12000 in str(last)
    assert "fixture-resource-21" in str(last)
    assert {message["role"] for message in last} >= {"assistant", "tool"}
    assert any(message.get("tool_calls") for message in last if message["role"] == "assistant")


@pytest.mark.parametrize("value", ["bad", "-1", "13", "", "١"])
def test_malformed_environment_cannot_silently_become_full_mode(monkeypatch, value):
    monkeypatch.setenv(FACTOR, value)
    with pytest.raises(service.HTTPException, match="SOURCE_FRAME_ROWS_INVALID"):
        service.configured_source_frame_rows(lambda _key, _default: 0)


def test_source_scope_cap_is_independent_of_generation_budget():
    locators = [f"S!R{i}" for i in range(1, 25)]
    for reserve in (500, 5000, 16000):
        assert service.adaptive_row_packet(locators, generation_reserve_tokens=reserve,
                                           source_frame_rows=12) == locators[:12]


def test_bound_source_id_is_part_of_frame_and_catalog_identity():
    from test_model_source_frame_service import _catalog
    from proxy.services.model_source_frame_service import build_model_source_frame
    source = _catalog()
    first = build_model_source_frame(source, ["Раздел А!R3"])
    same = build_model_source_frame(source, ["Раздел А!R3"])
    other = build_model_source_frame(dataclasses.replace(source, source_file_id="other-bound-source"), ["Раздел А!R3"])
    assert first == same
    assert first.catalog_sha256 != other.catalog_sha256
    assert first.source_frame_sha256 != other.source_frame_sha256


@pytest.mark.parametrize("value", ["-1", "13", "", "bad", "1.0", "١"])
def test_gui_rejects_invalid_frame_mode_before_write(tmp_path, monkeypatch, value):
    monkeypatch.setattr(registry, "env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(registry, "declared_env_keys", lambda: frozenset({FACTOR}))
    with pytest.raises(registry.RuntimeConfigRegistryError, match="INVALID_VALUE"):
        registry.update_factors({FACTOR: value})
    assert not (tmp_path / ".env").exists()


@pytest.mark.parametrize("value", ["0", "1", "6", "12"])
def test_gui_saves_supported_source_scope_as_effective_next_request_value(tmp_path, monkeypatch, value):
    path = tmp_path / ".env"
    # Track a process-only value so direct registry env writes are undone too.
    monkeypatch.setenv(FACTOR, "0")
    monkeypatch.setattr(registry, "env_path", lambda: path)
    monkeypatch.setattr(registry, "declared_env_keys", lambda: frozenset({FACTOR}))
    monkeypatch.setattr(registry, "registry_snapshot", lambda: {"factors": [registry._factor(FACTOR, {})]})
    result = registry.update_factors({FACTOR: value})
    assert os.getenv(FACTOR) == value and registry._dotenv_values(path)[FACTOR] == value
    assert result["updated"] == [{"key": FACTOR, "value": value, "restart_required": False}]
    assert result["registry"]["factors"][0]["effective_value"] == value
    from proxy.routers.chat import _env_int
    assert service.configured_source_frame_rows(_env_int) == int(value)
