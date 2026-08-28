import asyncio
import hashlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from proxy.security import ADMIN_ROLE, USER_ROLE, RequestUser, require_user
from proxy.services.artifact_revision_service import ArtifactRevisionRequest, ArtifactRevisionStore

from tools.live_workbook_acceptance import (
    AcceptanceConfig,
    CONTRACT_TEST,
    LiveAcceptanceError,
    exercise_contract,
    run_acceptance,
    validate_report,
)


def _revision(*, revision_id: str, revision_no: int, sha256: str, parent_revision_id: str | None) -> dict:
    return {
        "artifact_id": "art_123",
        "revision_id": revision_id,
        "revision_no": revision_no,
        "parent_revision_id": parent_revision_id,
        "sha256": sha256,
        "download_sha256": sha256,
        "byte_size": 8,
        "source_scope": ["attachment:read_123456abcdef"],
        "profile_revision_id": "profile:7",
        "model_identity": "qwen3.5:9b",
        "model_preset": "qwen-9b-restrictive",
        "decision_checkpoint_id": f"cp-{revision_no}",
        "missing_count": 0,
        "blocker_count": 0,
        "visible_sheet_count": 1,
        "header_cell_count": 2,
        "data_row_count": 1,
    }


@pytest.fixture
def report() -> dict:
    first_hash = hashlib.sha256(b"revision").hexdigest()
    second_hash = hashlib.sha256(b"revision-2").hexdigest()
    return {
        "schema": "les.live_workbook_acceptance.v1",
        "evidence_kind": "live_runtime",
        "runtime": {
            "source_commit_full": "a" * 40,
            "build_number": 622,
            "runtime_alignment": "aligned",
            "profile_revision_id": "profile:7",
            "model_preset": "qwen-9b",
            "observed_model_preset": "qwen-9b-restrictive",
            "model_identity": "qwen3.5:9b",
        },
        "attachment": {
            "attachment_id": "read_123456abcdef",
            "sha256": hashlib.sha256(b"source").hexdigest(),
        },
        "revision_1": _revision(
            revision_id="rev_1", revision_no=1, sha256=first_hash, parent_revision_id=None,
        ),
        "revision_2": _revision(
            revision_id="rev_2", revision_no=2, sha256=second_hash, parent_revision_id="rev_1",
        ),
        "elapsed_seconds": 1.25,
    }


def test_acceptance_report_requires_live_runtime_identity():
    with pytest.raises(ValueError, match="live_runtime"):
        validate_report({"evidence_kind": "synthetic_fixture"})


def test_acceptance_requires_two_immutable_revisions(report):
    validate_report(report)
    assert report["revision_1"]["sha256"] != report["revision_2"]["sha256"]
    assert report["revision_2"]["parent_revision_id"] == report["revision_1"]["revision_id"]


def test_acceptance_report_rejects_unredacted_runtime_data(report):
    report["runtime"]["authorization"] = "Bearer secret"

    with pytest.raises(ValueError, match="redacted|unknown"):
        validate_report(report)


@pytest.mark.parametrize("field", ["access_token", "raw_prompt", "unexpected"])
def test_acceptance_report_rejects_unknown_structured_fields(report, field):
    report["runtime"][field] = "value"

    with pytest.raises(ValueError, match="unknown"):
        validate_report(report)


def test_acceptance_report_rejects_source_path_embedded_in_blocker(report):
    report["revision_1"]["blockers"] = ["adapter wrote C:\\private\\source.xlsx"]

    with pytest.raises(ValueError, match="redacted|unknown"):
        validate_report(report)


def test_acceptance_report_rejects_traceback_or_prompt_dump_in_blockers(report):
    report["revision_1"]["blockers"] = ["Traceback (most recent call last): prompt dump"]

    with pytest.raises(ValueError, match="redacted"):
        validate_report(report)


def test_acceptance_report_rejects_embedded_auth_or_relative_source_path(report):
    report["revision_1"]["blockers"] = ["token=supersecret", "data/source.xlsx"]

    with pytest.raises(ValueError, match="redacted"):
        validate_report(report)


def test_acceptance_report_rejects_generic_relative_source_paths(report):
    report["revision_1"]["blockers"] = [
        "./source.xlsx",
        "..\\source.xlsx",
        "workspace\\source.xlsx",
        "source.xlsx",
    ]

    with pytest.raises(ValueError, match="redacted"):
        validate_report(report)


def test_acceptance_report_allows_structured_identifiers_with_dots(report):
    report["revision_1"]["artifact_id"] = "artifact.v1"
    report["revision_1"]["revision_id"] = "revision.1"
    report["revision_2"]["parent_revision_id"] = "revision.1"

    validate_report(report)


def test_acceptance_report_rejects_even_safe_looking_raw_status_arrays(report):
    report["revision_1"]["missing"] = ["id.with.dots"]
    report["revision_1"]["blockers"] = ["status.code"]

    with pytest.raises(ValueError, match="redacted|unknown"):
        validate_report(report)


@pytest.mark.parametrize(
    ("field", "value"),
    (("build_number", True), ("revision_no", True), ("source_scope", [1]), ("elapsed_seconds", float("nan"))),
)
def test_acceptance_report_rejects_wrong_allowed_field_types(report, field, value):
    target = report["runtime"] if field == "build_number" else report["revision_1"]
    if field == "elapsed_seconds":
        target = report
    target[field] = value

    with pytest.raises(ValueError, match="invalid|must contain"):
        validate_report(report)


def test_acceptance_rejects_fixture_path_before_any_live_request(tmp_path):
    fixture = tmp_path / "tests" / "fixtures" / "representative.xlsx"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"not live input")
    config = AcceptanceConfig(
        attachment=fixture,
        base_url="http://127.0.0.1:8050",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key=None,
    )

    with pytest.raises(LiveAcceptanceError, match="tests/fixtures"):
        exercise_contract(config, client=object())


class _FakeResponse:
    def __init__(self, *, payload=None, content=b"", lines=()):
        self._payload = payload
        self.content = content
        self._lines = list(lines)

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    def iter_lines(self):
        return iter(self._lines)


def _xlsx_bytes(value: str) -> bytes:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Acceptance"
    worksheet.append(["status", "revision"])
    worksheet.append([value, 1])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _xlsx_with_rows(rows: list[list[object]]) -> bytes:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Acceptance"
    for row in rows:
        worksheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


class _FakeHttpClient:
    def __init__(self):
        self.requests: list[tuple[str, str, dict]] = []
        self._first = _xlsx_bytes("revision")
        self._second = _xlsx_bytes("revision-2")

    def request(self, method: str, url: str, **kwargs):
        self.requests.append((method, url, kwargs))
        if url.endswith("/api/version"):
            return _FakeResponse(payload={
                "git_commit": "6b4952d9",
                "git_commit_full": "a" * 40,
                "build_number": 622,
                "repo_dirty": False,
                "runtime_alignment": {"status": "aligned"},
            })
        if url.endswith("/api/chat/attachments"):
            return _FakeResponse(payload={
                "attachment_id": "read_123456abcdef",
                "sha256": hashlib.sha256(b"source").hexdigest(),
            })
        if url.endswith("/api/chat/stream"):
            body = kwargs["json"]
            second = "rev_1" in body["question"]
            revision_id = "rev_2" if second else "rev_1"
            payload = {
                "artifact": {
                    "artifact_id": "art_123",
                    "revision_id": revision_id,
                    "revision_no": 2 if second else 1,
                    "parent_revision_id": "rev_1" if second else None,
                    "sha256": hashlib.sha256(self._second if second else self._first).hexdigest(),
                    "byte_size": len(self._second if second else self._first),
                    "source_scope": ["attachment:read_123456abcdef"],
                    "profile_revision_id": "profile:7",
                    "model_identity": "qwen3.5:9b",
                    "model_preset": "qwen-9b",
                    "decision_checkpoint_id": "cp-2" if second else "cp-1",
                    "missing": [],
                    "blockers": [],
                },
                "attachment_retry": {"attachment_id": "read_123456abcdef"},
                "checkpoint": {"checkpoint_id": "cp-2" if second else "cp-1", "status": "complete"},
                "source": {
                    "attachment_id": "read_123456abcdef",
                    "sha256": hashlib.sha256(b"source").hexdigest(),
                },
                "model_connection": {"model_id": "qwen3.5:9b"},
            }
            checkpoint_id = "cp-2" if second else "cp-1"
            return _FakeResponse(lines=(
                "event: tool_progress",
                f"data: {json.dumps({'checkpoint_id': checkpoint_id, 'completed': 1, 'total': 1})}",
                "",
                "event: final",
                f"data: {json.dumps(payload)}",
                "",
            ))
        if url.endswith("/api/artifacts/rev_1") or url.endswith("/api/artifacts/rev_2"):
            second = url.endswith("rev_2")
            payload = {
                "artifact_id": "art_123",
                "revision_id": "rev_2" if second else "rev_1",
                "revision_no": 2 if second else 1,
                "parent_revision_id": "rev_1" if second else None,
                "sha256": hashlib.sha256(self._second if second else self._first).hexdigest(),
                "byte_size": len(self._second if second else self._first),
                "source_scope": ["attachment:read_123456abcdef"],
                "profile_revision_id": "profile:7",
                "model_identity": "qwen3.5:9b",
                "model_preset": "qwen-9b-restrictive",
                "decision_checkpoint_id": "cp-2" if second else "cp-1",
                "missing": [],
                "blockers": [],
            }
            return _FakeResponse(payload=payload)
        if url.endswith("/api/artifacts/rev_1/download"):
            return _FakeResponse(content=self._first)
        if url.endswith("/api/artifacts/rev_2/download"):
            return _FakeResponse(content=self._second)
        raise AssertionError(f"unexpected request: {method} {url}")


def test_contract_exercise_uses_public_boundaries_without_live_receipt(tmp_path):
    source = tmp_path / "user-owned.xlsx"
    source.write_bytes(b"source")
    client = _FakeHttpClient()
    config = AcceptanceConfig(
        attachment=source,
        base_url="http://127.0.0.1:8050/",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key="test-secret",
    )

    report = exercise_contract(config, client=client)

    validate_report(report, expected_evidence_kind=CONTRACT_TEST)
    assert not config.out.exists()
    assert report["evidence_kind"] == CONTRACT_TEST
    methods_urls = [(method, url) for method, url, _ in client.requests]
    assert methods_urls == [
        ("GET", "http://127.0.0.1:8050/api/version"),
        ("POST", "http://127.0.0.1:8050/api/chat/attachments"),
        ("POST", "http://127.0.0.1:8050/api/chat/stream"),
        ("GET", "http://127.0.0.1:8050/api/artifacts/rev_1"),
        ("GET", "http://127.0.0.1:8050/api/artifacts/rev_1/download"),
        ("POST", "http://127.0.0.1:8050/api/chat/stream"),
        ("GET", "http://127.0.0.1:8050/api/artifacts/rev_2"),
        ("GET", "http://127.0.0.1:8050/api/artifacts/rev_2/download"),
    ]
    first_chat = client.requests[2][2]["json"]
    second_chat = client.requests[5][2]["json"]
    assert client.requests[1][2]["data"] == {"candidate_acceptance": "true"}
    assert first_chat["attachment_id"] == second_chat["attachment_id"] == "read_123456abcdef"
    assert first_chat["candidate_acceptance"] is True
    assert second_chat["candidate_acceptance"] is True
    assert "rev_1" in second_chat["question"]
    serialized = json.dumps(report)
    assert str(source) not in serialized
    assert "test-secret" not in serialized
    assert "Authorization" not in serialized


def test_contract_exercise_rejects_hash_valid_non_xlsx_artifact(tmp_path):
    source = tmp_path / "user-owned.xlsx"
    source.write_bytes(b"source")
    client = _FakeHttpClient()
    client._first = b"not-an-xlsx"
    config = AcceptanceConfig(
        attachment=source,
        base_url="http://127.0.0.1:8050",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key=None,
    )

    with pytest.raises(LiveAcceptanceError, match="readable XLSX"):
        exercise_contract(config, client=client)


@pytest.mark.parametrize(
    ("rows", "message"),
    (([["status", "revision"]], "data row"), ([["only"]], "header")),
)
def test_contract_exercise_rejects_template_or_one_cell_xlsx(tmp_path, rows, message):
    source = tmp_path / "user-owned.xlsx"
    source.write_bytes(b"source")
    client = _FakeHttpClient()
    client._first = _xlsx_with_rows(rows)
    config = AcceptanceConfig(
        attachment=source,
        base_url="http://127.0.0.1:8050",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key=None,
    )

    with pytest.raises(LiveAcceptanceError, match=message):
        exercise_contract(config, client=client)


def test_contract_exercise_rejects_incomplete_checkpoint_progress(tmp_path):
    source = tmp_path / "user-owned.xlsx"
    source.write_bytes(b"source")
    client = _FakeHttpClient()
    original_request = client.request

    def incomplete_progress(method, url, **kwargs):
        response = original_request(method, url, **kwargs)
        if url.endswith("/api/chat/stream"):
            response._lines[1] = response._lines[1].replace('"completed": 1', '"completed": 0')
        return response

    client.request = incomplete_progress
    config = AcceptanceConfig(
        attachment=source,
        base_url="http://127.0.0.1:8050",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key=None,
    )

    with pytest.raises(LiveAcceptanceError, match="did not complete"):
        exercise_contract(config, client=client)


def test_contract_exercise_rejects_elapsed_deadline(monkeypatch, tmp_path):
    from tools import live_workbook_acceptance as acceptance

    source = tmp_path / "user-owned.xlsx"
    source.write_bytes(b"source")
    ticks = iter((100.0, 102.0))
    monkeypatch.setattr(acceptance.time, "monotonic", lambda: next(ticks))
    config = AcceptanceConfig(
        attachment=source,
        base_url="http://127.0.0.1:8050",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key=None,
        max_elapsed_seconds=1,
    )

    with pytest.raises(LiveAcceptanceError, match="configured deadline"):
        exercise_contract(config, client=_FakeHttpClient())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("git_commit_full", "a" * 12, "full source commit"),
        ("git_commit_full", "unknown", "full source commit"),
        ("repo_dirty", True, "dirty"),
        ("runtime_alignment", {"status": "divergent"}, "alignment"),
    ),
)
def test_contract_exercise_rejects_unverified_runtime_identity(tmp_path, field, value, message):
    source = tmp_path / "user-owned.xlsx"
    source.write_bytes(b"source")
    client = _FakeHttpClient()
    original_request = client.request

    def invalid_version(method, url, **kwargs):
        response = original_request(method, url, **kwargs)
        if url.endswith("/api/version"):
            response._payload[field] = value
        return response

    client.request = invalid_version
    config = AcceptanceConfig(
        attachment=source,
        base_url="http://127.0.0.1:8050",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key=None,
    )

    with pytest.raises(LiveAcceptanceError, match=message):
        exercise_contract(config, client=client)


def test_asgi_contract_exercises_guarded_multipart_sse_and_artifact_boundaries(monkeypatch, tmp_path):
    """Hermetic HTTP boundary evidence, not a model-quality acceptance.

    The real chat router/application/harvest composes the final SSE payload.
    The fixture supplies an isolated profile snapshot plus empty retrieval/history
    ports, and controls the model transport, tool shortlist, and workbook executor.
    """
    from proxy.routers import artifacts, chat, datasets, runtime
    from proxy.services import chat_profile_service, request_idempotency_service
    from proxy.services import tool_harness_service
    from proxy.services.model_connection_contracts import ConnectionLocality, ConnectionRole
    from proxy.services.model_execution_preset_service import ModelExecutionPreset
    from proxy.services.openai_compatible_transport_service import InferenceResponse

    monkeypatch.chdir(tmp_path)
    for key, path in {
        "LES_CANONICAL_ACCEPTANCE_STATE_ROOT": tmp_path,
        "LES_CHAT_ATTACHMENT_ROOT": tmp_path / "storage" / "chat_attachments",
        "RAG_META_DB_PATH": tmp_path / "data" / "les_meta.db",
        "LES_IDEMPOTENCY_DB": tmp_path / "storage" / "request_idempotency.db",
    }.items():
        monkeypatch.setenv(key, str(path))
    monkeypatch.setattr(
        request_idempotency_service,
        "DEFAULT_DB_PATH",
        tmp_path / "storage" / "request_idempotency.db",
    )
    attachment_id = "read_123456abcdef"
    source = tmp_path / "real-source.xlsx"
    source.write_bytes(_xlsx_bytes("source"))
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    store = ArtifactRevisionStore(tmp_path / "storage" / "artifacts" / "meta.db", tmp_path / "storage" / "artifacts" / "files")
    first_file = tmp_path / "first.xlsx"
    second_file = tmp_path / "second.xlsx"
    first_file.write_bytes(_xlsx_bytes("first"))
    second_file.write_bytes(_xlsx_bytes("second"))
    request_base = {
        "artifact_kind": "vor_workbook",
        "source_scope": (f"attachment:{attachment_id}",),
        "profile_revision_id": "profile:7",
        "model_identity": "qwen3.5:9b",
        "model_preset": "qwen-9b-restrictive",
        "tool_calls": (),
        "missing": (),
        "blockers": (),
    }
    first = store.create_revision(ArtifactRevisionRequest(
        file_path=first_file, decision_checkpoint_id="cp-1", parent_revision_id=None, **request_base,
    ))
    second = store.create_revision(ArtifactRevisionRequest(
        file_path=second_file, decision_checkpoint_id="cp-2", parent_revision_id=first.revision_id, **request_base,
    ))
    monkeypatch.setattr(artifacts, "artifact_revision_store", store)
    monkeypatch.setattr(runtime, "version_info", lambda: {
        "git_commit": "a" * 12,
        "git_commit_full": "a" * 40,
        "build_number": 623,
        "repo_dirty": False,
        "runtime_alignment": {"status": "aligned"},
    })
    saved_upload_names: list[str] = []

    async def save_upload_in_isolated_root(file, **_kwargs):
        saved_upload_names.append(file.filename)
        target = tmp_path / "storage" / "uploads" / str(file.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(await file.read())
        return target

    async def prepared_attachment(_temp_path, _original_name, **_kwargs):
        return {"attachment_id": attachment_id, "mode": "read", "name": "real-source.xlsx", "chars": 1, "text": "x", "truncated": False}

    revision_queue = {"values": iter((first, second))}

    class ToolHarness:
        def shortlist(self, *_args, **_kwargs):
            return {"tools": [{"name": "build_vor_workbook"}]}

    class ActiveResolver:
        def resolve(self, role, **_kwargs):
            assert role is ConnectionRole.ANSWER
            return SimpleNamespace(
                connection_id="conn:asgi",
                revision_id="conn:asgi:r1",
                display_name="ASGI fixture",
                model_id="qwen3.5:9b",
                locality=ConnectionLocality.LOOPBACK,
                base_url="http://127.0.0.1:1919/v1",
                secret_ref=None,
                effective_preset=ModelExecutionPreset(
                    preset_id="qwen-9b-restrictive",
                    model_family="fixture",
                    input_token_limit=6000,
                    generation_reserve_tokens=20,
                    safety_reserve_tokens=20,
                    normal_tool_count=3,
                    max_tools=5,
                    max_batch_items=5,
                    parallel_read_limit=1,
                    reasoning_enabled=False,
                    source_chain=("test",),
                ),
            )

        def resolve_fallback(self, *_args, **_kwargs):
            raise AssertionError("fallback must not be used")

    class ActiveTransport:
        def __init__(self, *_args, **_kwargs):
            self.responses = iter((
                InferenceResponse(
                    text="",
                    tool_calls=({
                        "id": "workbook-call-1",
                        "type": "function",
                        "function": {
                            "name": "build_vor_workbook",
                            "arguments": '{"attachment_id":"read_123456abcdef"}',
                        },
                    },),
                    finish_reason="tool_calls",
                    usage={},
                ),
                InferenceResponse(
                    text="Workbook draft complete.",
                    tool_calls=(),
                    finish_reason="stop",
                    usage={"completion_tokens": 5},
                ),
            ))

        async def complete(self, _connection, _request):
            return next(self.responses)

    async def execute_workbook(call, context, progress):
        assert call["tool"] == "build_vor_workbook"
        assert context["attachment_id"] == attachment_id
        revision = next(revision_queue["values"])
        await progress({
            "call_id": call.get("call_id") or "workbook-call-1",
            "checkpoint_id": revision.decision_checkpoint_id,
            "phase": "rows",
            "completed": 1,
            "total": 1,
        })
        return {
            "schema": "les.workbook_tool_result.v1",
            "tool": "build_vor_workbook",
            "status": "complete",
            "artifact": revision.to_dict(),
            "source": {"attachment_id": attachment_id, "sha256": source_sha256},
            "checkpoint": {"checkpoint_id": revision.decision_checkpoint_id, "status": "complete"},
            "missing": [],
            "blockers": [],
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

    async def fake_retrieval(**_kwargs):
        return FakeRetrieval()

    async def no_dataset_ids(*_args, **_kwargs):
        return []

    async def no_dataset_names(*_args, **_kwargs):
        return {}

    def profile_snapshot(**_kwargs):
        return {
            "revision_id": "profile:7",
            "mode": "rag",
            "name": "ASGI acceptance profile",
            "revision_no": 7,
            "tools": ["build_vor_workbook"],
            "prompt_text": "Use the workbook tool.",
            "rag_policy": {"iterative": False},
        }

    monkeypatch.setattr(datasets, "save_upload_tmp", save_upload_in_isolated_root)
    monkeypatch.setattr(datasets, "_prepare_read_attachment", prepared_attachment)
    monkeypatch.setattr(chat_profile_service, "resolve_chat_profile", profile_snapshot)
    monkeypatch.setattr(tool_harness_service, "harness", lambda: ToolHarness())
    monkeypatch.setattr(chat, "_model_connection_resolver", lambda: (ActiveResolver(), object()))
    monkeypatch.setattr(chat, "OpenAICompatibleTransport", ActiveTransport)
    monkeypatch.setattr(chat, "_execute_chat_workbook_tool", execute_workbook)
    monkeypatch.setattr(chat, "resolve_dataset_ids", no_dataset_ids)
    monkeypatch.setattr(chat, "_dataset_name_map", no_dataset_names)
    monkeypatch.setattr(chat, "build_context_memory_block", lambda **_kwargs: "")
    monkeypatch.setattr(chat, "retrieve_chat_chunks", fake_retrieval)
    monkeypatch.setattr(chat, "expand_context_windows", lambda *_args, **_kwargs: FakeWindows())
    monkeypatch.setattr(chat, "source_excerpts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat, "maybe_answer_table_query", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chat, "save_chat_history", lambda **_kwargs: "history-asgi")
    monkeypatch.setattr(chat, "semantic_cache_enabled", lambda: False)
    monkeypatch.setattr(chat, "chat_validation_enabled", lambda: False)
    monkeypatch.setattr(
        chat,
        "_state",
        chat.ChatRouterState(
            rag_backend=SimpleNamespace(collection_name="fixture"),
            llm_semaphore=asyncio.Semaphore(1),
            crag_stats={"verified": 0, "no_data": 0},
            chat_metrics={"latency_search": [], "latency_gen": [], "tokens": [], "crag_pass": 0, "crag_fail": 0},
            reranker_available=False,
            reranker_cls=None,
        ),
    )
    app = FastAPI()
    app.include_router(runtime.router)
    app.include_router(artifacts.router)
    app.include_router(datasets.search_router)
    app.include_router(chat.router)
    current_user = {"value": RequestUser(role=USER_ROLE, source="api_key")}
    app.dependency_overrides[require_user] = lambda: current_user["value"]
    test_client = TestClient(app)

    rejected = test_client.request(
        "POST",
        "/api/chat/attachments",
        files={"file": ("real-source.xlsx", source.read_bytes(), "application/octet-stream")},
        data={"candidate_acceptance": "true"},
    )
    assert rejected.status_code == 403
    assert saved_upload_names == []

    current_user["value"] = RequestUser(role=ADMIN_ROLE, source="trusted_network")

    class TrackingClient:
        def __init__(self):
            self.calls: list[tuple[str, str, object]] = []

        def request(self, method, url, **kwargs):
            response = test_client.request(method, url, **kwargs)
            self.calls.append((method, url, response))
            return response

    tracking = TrackingClient()
    config = AcceptanceConfig(
        attachment=source,
        base_url="http://testserver",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key=None,
    )
    report = exercise_contract(config, client=tracking)

    assert report["runtime"] == {
        "source_commit_full": "a" * 40,
        "build_number": 623,
        "runtime_alignment": "aligned",
        "profile_revision_id": "profile:7",
        "model_preset": "qwen-9b",
        "observed_model_preset": "qwen-9b-restrictive",
        "model_identity": "qwen3.5:9b",
    }
    assert saved_upload_names == ["real-source.xlsx"]
    stream_responses = [response for method, url, response in tracking.calls if method == "POST" and url.endswith("/api/chat/stream")]
    assert len(stream_responses) == 2
    assert all("event: tool_progress" in response.text and "event: final" in response.text for response in stream_responses)
    assert [item[0] for item in tracking.calls] == ["GET", "POST", "POST", "GET", "GET", "POST", "GET", "GET"]

    # A production-harvest mutation must make the runner refuse the SSE final.
    from proxy.services import chat_evidence_application_service

    original_harvest = chat_evidence_application_service.harvest_workbook_tool_result

    def without_source(payload):
        harvested = original_harvest(payload)
        harvested.pop("source", None)
        return harvested

    monkeypatch.setattr(
        chat_evidence_application_service,
        "harvest_workbook_tool_result",
        without_source,
    )
    revision_queue["values"] = iter((first, second))
    with pytest.raises(LiveAcceptanceError, match="source attachment lineage"):
        exercise_contract(config, client=tracking)


def test_public_live_entrypoint_rejects_injected_transport(tmp_path):
    config = AcceptanceConfig(
        attachment=tmp_path / "source.xlsx",
        base_url="http://127.0.0.1:8050",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key=None,
    )

    with pytest.raises(TypeError):
        run_acceptance(config, client=_FakeHttpClient())
