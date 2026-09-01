from pathlib import Path
from types import SimpleNamespace
import json
import time

import pytest

from proxy.services import smeta_chat_application_service as service
from proxy.services import smeta_chat_adapter_service as adapter_service

_SMETA_HOST_ENV = (
    "LES_SMETA_DOCUMENT_BATCH_SIZE",
    "LES_SMETA_DOCUMENT_MAX_TOOL_TURNS",
    "LES_SMETA_DOCUMENT_NUM_CTX",
    "LES_SMETA_DOCUMENT_TEMPERATURE",
    "LES_SMETA_DOCUMENT_TOP_P",
    "LES_SMETA_LOCAL_GLOBAL_REVIEW",
)


def test_source_row_count_reads_plain_labelled_and_xlsx_transport_rows():
    labelled = "\n".join(
        f"Строка {index} — Работа {index}; ед. изм.: шт.; количество: {index}"
        for index in range(1, 5)
    )
    xlsx_context = """Файл: test.xlsx
## Лист: ВОР
ВОР!R1: № | Наименование | Ед. изм. | Количество
ВОР!R2: 1 | Монтаж шкафа | шт. | 2
ВОР!R3: 2 | Прокладка кабеля | м | 120
Итого непустых строк на листе «ВОР»: 3"""

    assert adapter_service._smeta_source_row_count(labelled) == 4
    assert adapter_service._smeta_source_row_count(xlsx_context) == 2


def _clear_smeta_host_env(monkeypatch) -> None:
    """Host LES-START / windows-cuda.env must not leak into unit expectations."""
    for name in _SMETA_HOST_ENV:
        monkeypatch.delenv(name, raising=False)


def test_approval_open_items_projects_only_unresolved_rows():
    workflow = {
        "lsr": {
            "sections": [
                {
                    "positions": [
                        {
                            "work_id": "w-bound",
                            "name": "Организатор",
                            "code": "ГЭСНм37-01-014-08",
                            "qty": 8,
                            "unit": "шт.",
                            "summary": {"result_status": "priced"},
                        },
                        {
                            "work_id": "w-open",
                            "name": "Кабель OM4",
                            "code": "",
                            "qty": 400,
                            "unit": "м.п",
                            "summary": {
                                "result_status": "norm_selection_required",
                                "flags": ["нужны условия прокладки"],
                            },
                        },
                    ]
                }
            ]
        }
    }

    assert service._approval_open_items(workflow) == [
        {
            "work_id": "w-open",
            "title": "Кабель OM4",
            "quantity": 400,
            "unit": "м.п",
            "reason": "нужны условия прокладки",
        }
    ]


@pytest.mark.asyncio
async def test_document_application_preserves_stream_artifact_and_trace(tmp_path, monkeypatch):
    _clear_smeta_host_env(monkeypatch)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-test")
    consumed = []
    workflow_call = {}
    events = []
    exchange_attempts = 0

    monkeypatch.setattr(service, "resolve_read_attachment", lambda attachment_id: (
        source,
        {
            "attachment_id": attachment_id,
            "original_name": "ВОР тест.pdf",
            "sha256": "source-sha",
        },
    ))
    monkeypatch.setattr(service, "consume_read_attachment", consumed.append)

    def model_exchange(_messages, _tools):
        nonlocal exchange_attempts
        exchange_attempts += 1
        if exchange_attempts == 1:
            return {}
        return {"tool_calls": [{"id": "model-owned"}]}

    def run_workflow(path, **kwargs):
        workflow_call.update({"path": path, **kwargs})
        assert kwargs["exchange"]([], []) == {"tool_calls": [{"id": "model-owned"}]}
        kwargs["progress"]({"phase": "batch_search", "queries_count": 19})
        kwargs["progress"]({
            "phase": "row_ready",
            "status": "done",
            "row": {"work_id": "w1", "title": "Работа", "norm_code": "ГЭСН01"},
        })
        Path(kwargs["out_xlsx"]).write_bytes(b"xlsx")
        Path(kwargs["out_report"]).write_text("{}", encoding="utf-8")
        return {
            "schema": "smeta_vor_pdf_workflow_v1",
            "agent_trace": {},
            "model_trace": [{"turn": 1}],
            "lsr": {
                "summary": {
                    "result_status": "priced_partial",
                    "input_rows": 19,
                    "bound_rows": 16,
                    "open_rows": 3,
                    "total_without_vat": 100,
                    "total_with_vat": 122,
                },
                "positions": [{"work_id": "w1", "selected_by": "model"}],
            },
        }

    monkeypatch.setattr(service, "run_vor_document_workflow", run_workflow)

    async def sink(event):
        events.append(event)

    result = await service.run_smeta_document_application(
        attachment_id="read_0123456789ab",
        user_request="Сделай ЛСР",
        model_exchange=model_exchange,
        model_provider="openai",
        model_name="gpt-5.4",
        cloud_provider=True,
        token_sink=sink,
        artifact_dir=tmp_path / "artifacts",
    )

    assert result is not None
    assert result.operation == "smeta_document_lsr"
    assert result.crag == "PARTIAL"
    assert "Из 19 позиций рассчитаны 16" in result.answer
    assert result.extra["artifact"]["mode"] == "xlsx"
    assert result.extra["artifact"]["rim_trace"]["positions"][0]["selected_by"] == "model"
    assert result.extra["retrieval_trace"] == {
        "mode": "smeta_document",
        "schema": "smeta_vor_pdf_workflow_v1",
        "zero_state": True,
        "previous_revision_read": False,
        "source_sha256": "source-sha",
        "result_status": "priced_partial",
        "summary": {
            "result_status": "priced_partial",
            "input_rows": 19,
            "bound_rows": 16,
            "open_rows": 3,
            "total_without_vat": 100,
            "total_with_vat": 122,
        },
        "model_provider": "openai",
        "agent_engine": "native",
        "model_requested": "gpt-5.4",
        "model": "gpt-5.4",
        "models_used": ["gpt-5.4"],
        "model_fallbacks": [],
        "model_calls": 1,
        "mapping_fingerprint": {
            "schema": "les.smeta_mapping_fingerprint.v1",
            "digest": "4f53cda18c2b",
            "entries": [],
            "bound_rows": 0,
            "open_rows": 0,
            "repair_collection_demotions": [],
        },
    }
    assert workflow_call["candidate_limit"] == 12
    assert workflow_call["batch_size"] == 0
    saved_trace = json.loads(Path(result.extra["artifact"]["files"]["trace_path"]).read_text())
    assert saved_trace["agent_trace"]["engine"] == "native"
    assert saved_trace["agent_trace"]["provider"] == "openai"
    assert saved_trace["agent_trace"]["model"] == "gpt-5.4"
    assert workflow_call["source_name"] == "ВОР тест.pdf"
    assert workflow_call["user_request"] == "Сделай ЛСР"
    assert exchange_attempts == 2
    assert consumed == []
    assert result.extra["artifact"]["approval"]["attachment"] == {
        "id": "read_0123456789ab",
        "name": "ВОР тест.pdf",
        "mode": "read",
    }
    assert result.extra["artifact"]["approval"]["open_items"][0]["work_id"] == "w1"
    assert [(event["event"], event["data"]["phase"]) for event in events] == [
        ("smeta_step", "document_workflow"),
        ("smeta_step", "batch_search"),
        ("smeta_row", "row_ready"),
    ]


@pytest.mark.asyncio
async def test_document_application_keeps_attachment_after_workflow_failure(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-test")
    consumed = []
    monkeypatch.setattr(service, "resolve_read_attachment", lambda _attachment_id: (
        source,
        {"original_name": "source.pdf", "sha256": "sha"},
    ))
    monkeypatch.setattr(service, "consume_read_attachment", consumed.append)
    partial = {
        "selections": {"w1": {"norm_code": "", "reason": "решение модели"}},
        "remaining_work_ids": ["w2"],
        "incomplete": True,
    }

    def fail_after_checkpoint(*_args, **kwargs):
        assert kwargs["resume_agent_result"] is None
        kwargs["batch_checkpoint"](partial)
        raise RuntimeError("provider down")

    monkeypatch.setattr(
        service,
        "run_vor_document_workflow",
        fail_after_checkpoint,
    )

    result = await service.run_smeta_document_application(
        attachment_id="read_0123456789ab",
        user_request="Сделай ЛСР",
        model_exchange=lambda _messages, _tools: {},
        model_provider="mlx",
        model_name="local",
        cloud_provider=False,
        artifact_dir=tmp_path / "artifacts",
    )

    assert result is not None
    assert result.operation == "smeta_document_failed"
    assert result.crag == "ERROR"
    assert "Вложение сохранено" in result.answer
    assert result.extra["attachment_retry"] == {
        "preserved": True,
        "id": "read_0123456789ab",
        "name": "source.pdf",
        "mode": "read",
    }
    assert consumed == []
    checkpoint_path = (
        tmp_path / "artifacts" / ".checkpoints" / "read_0123456789ab.json"
    )
    assert checkpoint_path.exists()
    assert service._load_document_checkpoint(
        checkpoint_path,
        source_fingerprint=service._source_fingerprint(source),
    ) == partial


@pytest.mark.asyncio
async def test_document_application_emits_heartbeat_while_model_workflow_is_busy(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-test")
    events = []
    monkeypatch.setattr(service, "SMETA_DOCUMENT_HEARTBEAT_SEC", 0.01)
    monkeypatch.setattr(service, "resolve_read_attachment", lambda _attachment_id: (
        source, {"original_name": "source.pdf", "sha256": "sha"},
    ))

    def slow_failure(*_args, **_kwargs):
        time.sleep(0.04)
        raise RuntimeError("provider down")

    monkeypatch.setattr(service, "run_vor_document_workflow", slow_failure)

    async def sink(event):
        events.append(event)

    result = await service.run_smeta_document_application(
        attachment_id="read_0123456789ab",
        user_request="Сделай ЛСР",
        model_exchange=lambda _messages, _tools: {},
        model_provider="ollama",
        model_name="qwen3.5:9b",
        cloud_provider=False,
        token_sink=sink,
        artifact_dir=tmp_path / "artifacts",
    )

    assert result is not None and result.operation == "smeta_document_failed"
    assert any(
        event["data"].get("status") == "running" and "модель работает" in event["data"].get("label", "")
        for event in events
    )


@pytest.mark.asyncio
async def test_document_application_reports_missing_attachment(monkeypatch):
    monkeypatch.setattr(
        service,
        "resolve_read_attachment",
        lambda _attachment_id: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )

    result = await service.run_smeta_document_application(
        attachment_id="read_0123456789ab",
        user_request="Сделай ЛСР",
        model_exchange=lambda _messages, _tools: {},
        model_provider="mlx",
        model_name="local",
        cloud_provider=False,
    )

    assert result is not None
    assert result.operation == "smeta_document_attachment_missing"
    assert result.crag == "ERROR"


@pytest.mark.asyncio
async def test_document_application_routes_xlsx_through_document_workflow(tmp_path, monkeypatch):
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"xlsx")
    consumed = []
    monkeypatch.setattr(service, "resolve_read_attachment", lambda _attachment_id: (
        source,
        {"original_name": "source.xlsx", "sha256": "sha"},
    ))
    monkeypatch.setattr(service, "consume_read_attachment", consumed.append)
    workflow_calls = []

    def run_workflow(path, **kwargs):
        workflow_calls.append((path, kwargs))
        Path(kwargs["out_xlsx"]).write_bytes(b"xlsx-result")
        Path(kwargs["out_report"]).write_text("{}", encoding="utf-8")
        return {
            "schema": "smeta_document_workflow_v2",
            "agent_trace": {},
            "model_trace": [],
            "lsr": {
                "summary": {
                    "result_status": "priced_complete",
                    "input_rows": 2,
                    "bound_rows": 2,
                    "open_rows": 0,
                    "total_without_vat": 100,
                    "total_with_vat": 122,
                },
                "positions": [],
            },
        }

    monkeypatch.setattr(service, "run_vor_document_workflow", run_workflow)

    result = await service.run_smeta_document_application(
        attachment_id="read_0123456789ab",
        user_request="Сделай ЛСР",
        model_exchange=lambda _messages, _tools: {},
        model_provider="mlx",
        model_name="local",
        cloud_provider=False,
        artifact_dir=tmp_path / "artifacts",
    )

    assert result is not None
    assert result.operation == "smeta_document_lsr"
    assert workflow_calls[0][0] == source
    assert workflow_calls[0][1]["source_name"] == "source.xlsx"
    assert consumed == ["read_0123456789ab"]


def test_document_application_contains_no_professional_selector():
    source = Path(service.__file__).read_text(encoding="utf-8")

    assert "bind_norm" not in source
    assert "selected_norm" not in source
    assert "resource_actions" not in source


@pytest.mark.asyncio
async def test_gemma_document_application_uses_one_model_owned_conversation(tmp_path, monkeypatch):
    _clear_smeta_host_env(monkeypatch)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-test")
    monkeypatch.setattr(service, "resolve_read_attachment", lambda _attachment_id: (
        source,
        {"original_name": "source.pdf", "sha256": "sha"},
    ))
    monkeypatch.setattr(service, "consume_read_attachment", lambda _attachment_id: None)
    seen = {}

    def run_workflow(_path, **kwargs):
        seen.update(kwargs)
        Path(kwargs["out_xlsx"]).write_bytes(b"xlsx")
        Path(kwargs["out_report"]).write_text("{}", encoding="utf-8")
        return {
            "schema": "smeta_document_workflow_v2",
            "agent_trace": {},
            "model_trace": [],
            "lsr": {
                "summary": {
                    "result_status": "priced_complete",
                    "input_rows": 1,
                    "bound_rows": 1,
                    "open_rows": 0,
                },
                "positions": [],
            },
        }

    monkeypatch.setattr(service, "run_vor_document_workflow", run_workflow)
    result = await service.run_smeta_document_application(
        attachment_id="read_0123456789ab",
        user_request="Сделай ЛСР",
        model_exchange=lambda _messages, _tools: {},
        model_provider="ollama",
        model_name="gemma4:12b",
        cloud_provider=False,
        artifact_dir=tmp_path / "artifacts",
    )

    assert result is not None
    assert seen["batch_size"] == 5


@pytest.mark.asyncio
async def test_local_ollama_qwen_document_application_uses_single_row_batches(tmp_path, monkeypatch):
    _clear_smeta_host_env(monkeypatch)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-test")
    monkeypatch.setattr(service, "resolve_read_attachment", lambda _attachment_id: (
        source,
        {"original_name": "source.pdf", "sha256": "sha"},
    ))
    monkeypatch.setattr(service, "consume_read_attachment", lambda _attachment_id: None)
    seen = {}

    def run_workflow(_path, **kwargs):
        seen.update(kwargs)
        Path(kwargs["out_xlsx"]).write_bytes(b"xlsx")
        Path(kwargs["out_report"]).write_text("{}", encoding="utf-8")
        return {
            "schema": "smeta_document_workflow_v2",
            "agent_trace": {},
            "model_trace": [],
            "lsr": {
                "summary": {
                    "result_status": "priced_complete",
                    "input_rows": 1,
                    "bound_rows": 1,
                    "open_rows": 0,
                },
                "positions": [],
            },
        }

    monkeypatch.setattr(service, "run_vor_document_workflow", run_workflow)
    result = await service.run_smeta_document_application(
        attachment_id="read_0123456789ab",
        user_request="Сделай ЛСР",
        model_exchange=lambda _messages, _tools: {},
        model_provider="ollama",
        model_name="qwen3.5:9b",
        cloud_provider=False,
        artifact_dir=tmp_path / "artifacts",
    )

    assert result is not None
    assert seen["batch_size"] == 1
    assert seen["accumulate_task_state"] is False
    # Local Qwen defaults to review-off for demo latency; force via env if needed.
    assert seen["require_global_review"] is False
    assert seen["require_scoped_search"] is True


@pytest.mark.asyncio
async def test_local_freetoken_document_application_uses_single_row_batches(tmp_path, monkeypatch):
    _clear_smeta_host_env(monkeypatch)
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"xlsx")
    monkeypatch.setattr(service, "resolve_read_attachment", lambda _attachment_id: (
        source,
        {"original_name": "source.xlsx", "sha256": "sha"},
    ))
    monkeypatch.setattr(service, "consume_read_attachment", lambda _attachment_id: None)
    seen = {}

    def run_workflow(_path, **kwargs):
        seen.update(kwargs)
        Path(kwargs["out_xlsx"]).write_bytes(b"xlsx")
        Path(kwargs["out_report"]).write_text("{}", encoding="utf-8")
        return {
            "schema": "smeta_document_workflow_v2",
            "agent_trace": {},
            "model_trace": [],
            "lsr": {"summary": {
                "result_status": "priced_complete",
                "input_rows": 1,
                "bound_rows": 1,
                "open_rows": 0,
            }, "positions": []},
        }

    monkeypatch.setattr(service, "run_vor_document_workflow", run_workflow)
    result = await service.run_smeta_document_application(
        attachment_id="read_0123456789ab",
        user_request="Сделай ЛСР",
        model_exchange=lambda _messages, _tools: {},
        model_provider="freetoken",
        model_name="Qwen3.6-35B-A3B-NVFP4",
        cloud_provider=False,
        artifact_dir=tmp_path / "artifacts",
    )

    assert result is not None
    assert seen["batch_size"] == 1
    assert seen["max_agent_turns"] == 8
    assert seen["require_global_review"] is False
    assert seen["require_scoped_search"] is True


@pytest.mark.asyncio
async def test_ollama_qwen_document_uses_fast_local_defaults(tmp_path, monkeypatch):
    import os

    source = tmp_path / "source.xlsx"
    source.write_bytes(b"xlsx")
    seen = {}
    monkeypatch.delenv("LES_SMETA_AGENT_ENGINE", raising=False)
    monkeypatch.delenv("LES_SMETA_DOCUMENT_BATCH_SIZE", raising=False)
    monkeypatch.delenv("LES_SMETA_DOCUMENT_MAX_TOOL_TURNS", raising=False)
    monkeypatch.delenv("LES_SMETA_SEARCH_BUDGET", raising=False)
    monkeypatch.delenv("LES_SMETA_READ_BUDGET", raising=False)
    monkeypatch.delenv("LES_SMETA_MAPPING_EVIDENCE_REPAIR_TURNS", raising=False)
    monkeypatch.delenv("LES_SMETA_NORM_RERANK", raising=False)
    monkeypatch.delenv("LES_SMETA_LOCAL_GLOBAL_REVIEW", raising=False)
    monkeypatch.setattr(service, "resolve_read_attachment", lambda _attachment_id: (
        source, {"original_name": "source.xlsx", "sha256": "sha"},
    ))
    monkeypatch.setattr(service, "consume_read_attachment", lambda _attachment_id: None)

    def run_workflow(_path, **kwargs):
        seen.update(kwargs)
        Path(kwargs["out_xlsx"]).write_bytes(b"xlsx")
        Path(kwargs["out_report"]).write_text("{}", encoding="utf-8")
        return {
            "schema": "smeta_document_workflow_v2",
            "agent_trace": {},
            "model_trace": [],
            "lsr": {"summary": {
                "result_status": "priced_complete",
                "input_rows": 1,
                "bound_rows": 1,
                "open_rows": 0,
            }, "positions": []},
        }

    monkeypatch.setattr(service, "run_vor_document_workflow", run_workflow)
    result = await service.run_smeta_document_application(
        attachment_id="read_0123456789ab",
        user_request="Сделай ЛСР",
        model_exchange=lambda _messages, _tools: {},
        model_provider="ollama",
        model_name="qwen3.5:9b",
        cloud_provider=False,
        artifact_dir=tmp_path / "artifacts",
    )

    assert result is not None
    assert seen["batch_size"] == 1
    assert seen["max_agent_turns"] == 8
    assert seen["require_scoped_search"] is True
    assert seen["require_global_review"] is False
    assert os.environ["LES_SMETA_SEARCH_BUDGET"] == "3"
    assert os.environ["LES_SMETA_READ_BUDGET"] == "3"
    assert os.environ["LES_SMETA_MAPPING_EVIDENCE_REPAIR_TURNS"] == "1"
    assert "LES_SMETA_NORM_RERANK" not in os.environ


@pytest.mark.asyncio
async def test_ollama_qwen_document_keeps_explicit_max_turns_override(tmp_path, monkeypatch):
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"xlsx")
    seen = {}
    monkeypatch.delenv("LES_SMETA_AGENT_ENGINE", raising=False)
    monkeypatch.delenv("LES_SMETA_DOCUMENT_BATCH_SIZE", raising=False)
    monkeypatch.setenv("LES_SMETA_DOCUMENT_MAX_TOOL_TURNS", "12")
    monkeypatch.setattr(service, "resolve_read_attachment", lambda _attachment_id: (
        source, {"original_name": "source.xlsx", "sha256": "sha"},
    ))
    monkeypatch.setattr(service, "consume_read_attachment", lambda _attachment_id: None)

    def run_workflow(_path, **kwargs):
        seen.update(kwargs)
        Path(kwargs["out_xlsx"]).write_bytes(b"xlsx")
        Path(kwargs["out_report"]).write_text("{}", encoding="utf-8")
        return {
            "schema": "smeta_document_workflow_v2",
            "agent_trace": {},
            "model_trace": [],
            "lsr": {"summary": {
                "result_status": "priced_complete",
                "input_rows": 1,
                "bound_rows": 1,
                "open_rows": 0,
            }, "positions": []},
        }

    monkeypatch.setattr(service, "run_vor_document_workflow", run_workflow)
    await service.run_smeta_document_application(
        attachment_id="read_0123456789ab",
        user_request="Сделай ЛСР",
        model_exchange=lambda _messages, _tools: {},
        model_provider="ollama",
        model_name="qwen3.5:9b",
        cloud_provider=False,
        artifact_dir=tmp_path / "artifacts",
    )

    assert seen["max_agent_turns"] == 12


@pytest.mark.asyncio
async def test_qwen_document_application_defaults_to_accumulated_single_rows(tmp_path, monkeypatch):
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"xlsx")
    seen = {}
    monkeypatch.setenv("LES_SMETA_AGENT_ENGINE", "qwen_agent")
    monkeypatch.delenv("LES_SMETA_DOCUMENT_BATCH_SIZE", raising=False)
    monkeypatch.setattr(service, "resolve_read_attachment", lambda _attachment_id: (
        source, {"original_name": "source.xlsx", "sha256": "sha"},
    ))
    monkeypatch.setattr(service, "consume_read_attachment", lambda _attachment_id: None)
    fake_runner = SimpleNamespace(run_batch=lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        "proxy.services.smeta_agent_runner_service.build_smeta_agent_runner",
        lambda *_args, **_kwargs: fake_runner,
    )

    def run_workflow(_path, **kwargs):
        seen.update(kwargs)
        Path(kwargs["out_xlsx"]).write_bytes(b"xlsx")
        Path(kwargs["out_report"]).write_text("{}", encoding="utf-8")
        return {
            "schema": "smeta_document_workflow_v2",
            "agent_trace": {},
            "model_trace": [],
            "lsr": {"summary": {
                "result_status": "priced_complete",
                "input_rows": 1,
                "bound_rows": 1,
                "open_rows": 0,
            }, "positions": []},
        }

    monkeypatch.setattr(service, "run_vor_document_workflow", run_workflow)
    result = await service.run_smeta_document_application(
        attachment_id="read_0123456789ab",
        user_request="Сделай ЛСР",
        artifact_dir=tmp_path / "artifacts",
    )

    assert result is not None and result.operation == "smeta_document_lsr"
    assert seen["batch_size"] == 1
    assert seen["accumulate_task_state"] is True
    assert seen["agent_batch_runner"] == fake_runner.run_batch


def test_document_exchange_makes_one_ollama_request_without_hidden_fallback(monkeypatch):
    from proxy.services import smeta_chat_adapter_service as adapter

    _clear_smeta_host_env(monkeypatch)
    bodies = []
    urls = []

    class Response:
        status_code = 200
        text = ""

        def __init__(self, message):
            self._message = message

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": self._message}],
                "message": self._message,
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "prompt_tokens_details": {"cached_tokens": 75},
                },
            }

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url, **kwargs):
            urls.append(_url)
            bodies.append(kwargs["json"])
            return Response({"content": "Я отвечу текстом"})

    monkeypatch.setattr(adapter, "_smeta_model_runtime", lambda _name: adapter.LlmRuntime(
        "ollama", "http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1/chat/completions",
        "gemma4:12b", "", True,
    ))
    monkeypatch.setattr(adapter.httpx, "Client", Client)

    result = adapter._smeta_document_exchange(
        [
            {"role": "user", "content": "Собери ЛСР"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-1", "function": {"name": "search_norms_batch", "arguments": {}}}],
                "model": "transport-metadata-is-not-native",
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "name": "search_norms_batch",
                "content": '{"ok":true}',
            },
        ],
        [{"type": "function", "function": {"name": "search_norms_batch"}}],
    )

    assert result["content"] == "Я отвечу текстом"
    assert result["_les_model"] == "gemma4:12b"
    assert result["_les_generation_metrics"]["prompt_tokens"] == 100
    assert result["_les_generation_metrics"]["cached_prompt_tokens"] == 75
    assert result["_les_generation_metrics"]["cache_hit_ratio"] == 0.75
    assert "tool_calls" not in result
    assert "_les_fallback_from" not in result
    assert "options" in bodies[0]
    assert bodies[0]["options"]["num_predict"] == 4096
    assert bodies[0]["options"]["num_ctx"] == 32768
    assert bodies[0]["options"]["temperature"] == 0.7
    assert bodies[0]["options"]["top_p"] == 0.8
    assert bodies[0]["options"]["top_k"] == 20
    assert bodies[0]["options"]["min_p"] == 0.0
    assert bodies[0]["options"]["seed"] == 0
    assert result["_les_seed"] == 0
    assert bodies[0]["think"] is False
    assert bodies[0]["messages"][-1] == {
        "role": "tool",
        "content": '{"ok":true}',
        "tool_name": "search_norms_batch",
    }
    assert "model" not in bodies[0]["messages"][1]
    assert bodies[0]["messages"][1]["tool_calls"][0]["id"] == "call-1"
    assert urls == ["http://127.0.0.1:11434/api/chat"]


def test_document_mapping_exchange_uses_ollama_json_schema(monkeypatch):
    from proxy.services import smeta_chat_adapter_service as adapter

    _clear_smeta_host_env(monkeypatch)
    captured = {}

    class Response:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {"content": '{"rows":[{"work_id":"w1","decision":"unbound","reason":"model"}]}'},
                "done_reason": "stop",
                "eval_count": 42,
            }

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, **kwargs):
            captured["url"] = url
            captured["body"] = kwargs["json"]
            return Response()

    monkeypatch.setattr(adapter, "_smeta_model_runtime", lambda _name: adapter.LlmRuntime(
        "ollama", "http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1/chat/completions",
        "qwen3.5:9b", "", True,
    ))
    monkeypatch.setattr(adapter.httpx, "Client", Client)
    schema = {
        "type": "object",
        "properties": {"rows": {"type": "array", "maxItems": 1}},
        "required": ["rows"],
    }

    result = adapter._smeta_document_mapping_exchange(
        [{"role": "assistant", "content": "", "thinking": "model reasoning"}], schema,
    )

    assert result["rows"][0]["reason"] == "model"
    assert result["_les_model"] == "qwen3.5:9b"
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["body"]["format"] == schema
    assert "tools" not in captured["body"]
    assert captured["body"]["think"] is False
    assert captured["body"]["messages"][0]["thinking"] == "model reasoning"
    assert captured["body"]["options"]["num_ctx"] == 32768
    assert captured["body"]["options"]["temperature"] == 0.7
    assert captured["body"]["options"]["top_p"] == 0.8
    assert captured["body"]["options"]["top_k"] == 20
    assert captured["body"]["options"]["seed"] == 0
    assert captured["body"]["options"]["num_predict"] == 2200
    assert result["_les_seed"] == 0


def test_document_mapping_exchange_strips_inline_thinking(monkeypatch):
    from proxy.services import smeta_chat_adapter_service as adapter

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "content": (
                        '<think>{"unrelated":"reasoning"}</think>'
                        '{"rows":[{"work_id":"w1","decision":"unbound","reason":"model"}]}'
                    ),
                },
                "done_reason": "stop",
                "eval_count": 42,
            }

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url, **_kwargs):
            return Response()

    monkeypatch.setattr(adapter, "_smeta_model_runtime", lambda _name: adapter.LlmRuntime(
        "ollama", "http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1/chat/completions",
        "qwen3.5:9b", "", True,
    ))
    monkeypatch.setattr(adapter.httpx, "Client", Client)

    result = adapter._smeta_document_mapping_exchange(
        [{"role": "user", "content": "mapping"}],
        {"type": "object", "properties": {"rows": {"type": "array"}}, "required": ["rows"]},
    )

    assert result["rows"][0]["reason"] == "model"


def test_mapping_parser_tolerates_trailing_comma_without_changing_values():
    from proxy.services import smeta_chat_adapter_service as adapter

    parsed = adapter._extract_mapping_json(
        'prefix {"note":"not mapping"} '
        '{"rows":[{"work_id":"w1","decision":"bind",'
        '"norm_code":"ГЭСНм:11-04-027-01",}],}'
    )
    assert parsed == {
        "rows": [{
            "work_id": "w1",
            "decision": "bind",
            "norm_code": "ГЭСНм:11-04-027-01",
        }],
    }


def test_mapping_parser_accepts_schema_object_from_thinking_field():
    from proxy.services import smeta_chat_adapter_service as adapter

    parsed = adapter._parse_mapping_message({
        "content": "",
        "thinking": '{"rows":[{"work_id":"w1","decision":"unbound","reason":"model"}]}',
    })
    assert parsed is not None
    assert parsed["rows"][0]["decision"] == "unbound"


def test_document_mapping_exchange_retries_length_without_thinking(monkeypatch):
    from proxy.services import smeta_chat_adapter_service as adapter

    requests = []

    class Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url, **kwargs):
            body = kwargs["json"]
            requests.append(body)
            if len(requests) == 2:
                return Response({
                    "message": {
                        "content": (
                            '{"rows":[{"work_id":"w1","decision":"unbound",'
                            '"reason":"retry"}]}'
                        ),
                    },
                    "done_reason": "stop",
                    "eval_count": 12,
                })
            return Response({
                "message": {"content": "", "thinking": "unfinished reasoning"},
                "done_reason": "length",
                "eval_count": 8000,
            })

    monkeypatch.setattr(adapter, "_smeta_model_runtime", lambda _name: adapter.LlmRuntime(
        "ollama", "http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1/chat/completions",
        "qwen3.5:9b", "", True,
    ))
    monkeypatch.setattr(adapter.httpx, "Client", Client)

    huge_history = "tool-history " * 4000
    final_request = "mapping for w1"
    result = adapter._smeta_document_mapping_exchange(
        [
            {"role": "system", "content": huge_history},
            {"role": "user", "content": "inspect candidates"},
            {"role": "assistant", "content": "I choose unbound for w1"},
            {"role": "tool", "content": huge_history},
            {"role": "user", "content": final_request},
        ],
        {"type": "object", "properties": {"rows": {"type": "array"}}, "required": ["rows"]},
    )

    assert result["rows"][0]["reason"] == "retry"
    assert len(requests) == 2
    assert requests[0]["think"] is False
    assert requests[1]["think"] is False
    assert requests[1]["options"]["num_predict"] == 16000
    assert sum(
        len(str(message.get("content") or ""))
        for message in requests[1]["messages"]
    ) < len(huge_history)
    assert requests[1]["messages"][-1]["content"] == final_request
    assert any(
        "I choose unbound for w1" in str(message.get("content") or "")
        for message in requests[1]["messages"]
    )


def test_default_direct_dependencies_live_in_smeta_adapter_not_router():
    dependencies = service.default_smeta_direct_dependencies()

    assert dependencies.rag_context.__module__ == "proxy.services.smeta_chat_adapter_service"
    assert dependencies.norm_lookup.__module__ == "proxy.services.smeta_chat_adapter_service"
    assert dependencies.norm_choice.__module__ == "proxy.services.smeta_chat_adapter_service"
    assert dependencies.model_answer.__module__ == "proxy.services.smeta_chat_adapter_service"
    router_source = Path("proxy/routers/chat.py").read_text(encoding="utf-8")
    assert "def _smeta_direct_rag_context" not in router_source
    assert "def _smeta_direct_norm_lookup_context" not in router_source
    assert "def _smeta_direct_structured_norm_choice" not in router_source
    assert "def _smeta_direct_model_answer" not in router_source


def test_mlx_native_tool_exchange_does_not_append_prose_prefill(monkeypatch):
    from proxy.services import smeta_chat_adapter_service as adapter

    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"tool_calls": [{"id": "tool-1"}]}}]}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url, **kwargs):
            captured.update(kwargs["json"])
            return Response()

    monkeypatch.setattr(adapter, "_smeta_model_runtime", lambda _name: adapter.LlmRuntime(
        "mlx", "http://127.0.0.1:8080", "http://127.0.0.1:8080/v1/chat/completions",
        "local-tool-model", "", True,
    ))
    monkeypatch.setattr(adapter.httpx, "Client", Client)
    messages = [{"role": "user", "content": "Вызови инструмент"}]

    result = adapter._smeta_document_exchange(messages, [{"type": "function"}])

    assert result["tool_calls"] == [{"id": "tool-1"}]
    assert captured["messages"] == messages
    assert captured["messages"][-1]["role"] == "user"


def test_document_exchange_bounds_single_question_generation(monkeypatch):
    from proxy.services import smeta_chat_adapter_service as adapter

    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"tool_calls": [{"id": "question-1"}]}}]}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url, **kwargs):
            captured.update(kwargs["json"])
            return Response()

    monkeypatch.setattr(adapter, "_smeta_model_runtime", lambda _name: adapter.LlmRuntime(
        "mlx", "http://127.0.0.1:8080", "http://127.0.0.1:8080/v1/chat/completions",
        "local-tool-model", "", True,
    ))
    monkeypatch.setattr(adapter.httpx, "Client", Client)

    adapter._smeta_document_exchange(
        [{"role": "user", "content": "Задай один вопрос"}],
        [{"type": "function", "function": {"name": "ask_user"}}],
    )

    assert captured["max_tokens"] == 512


def test_document_exchange_uses_freetoken_transport_profile(monkeypatch):
    from proxy.services import smeta_chat_adapter_service as adapter

    captured = {}

    class Response:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, **kwargs):
            captured["url"] = url
            captured["body"] = kwargs["json"]
            return Response()

    monkeypatch.setattr(adapter, "_smeta_model_runtime", lambda _name: adapter.LlmRuntime(
        "freetoken",
        "http://127.0.0.1:1919/v1",
        "http://127.0.0.1:1919/v1/chat/completions",
        "Qwen3.6-35B-A3B-NVFP4",
        "",
        False,
    ))
    monkeypatch.setattr(adapter.httpx, "Client", Client)

    result = adapter._smeta_document_exchange(
        [{"role": "user", "content": "Подбери норму"}],
        [{"type": "function", "function": {"name": "search_fsnb"}}],
    )

    assert captured["url"] == "http://127.0.0.1:1919/v1/chat/completions"
    assert captured["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["body"]["max_tokens"] == 1024
    assert result["content"] == "ok"


def test_freetoken_transport_keeps_authoritative_working_set_not_audit_history(monkeypatch):
    from proxy.services import smeta_chat_adapter_service as adapter

    captured = {}

    class Response:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url, **kwargs):
            captured["body"] = kwargs["json"]
            return Response()

    monkeypatch.setattr(adapter, "_smeta_model_runtime", lambda _name: adapter.LlmRuntime(
        "freetoken",
        "http://127.0.0.1:1919/v1",
        "http://127.0.0.1:1919/v1/chat/completions",
        "Qwen3.6-35B-A3B-NVFP4",
        "",
        False,
    ))
    monkeypatch.setattr(adapter.httpx, "Client", Client)
    messages = [
        {"role": "system", "content": "skill"},
        {"role": "user", "content": "source row"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "old-call"}]},
        {"role": "tool", "tool_call_id": "old-call", "content": "old audit evidence" * 1000},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "live-call"}]},
        {"role": "tool", "tool_call_id": "live-call", "content": "latest typed evidence"},
        {
            "role": "user",
            "content": '{"working_memory_contract":"smeta_norm_agent_working_memory_v1"}',
        },
        {"role": "user", "content": "Call the next tool now."},
    ]

    adapter._smeta_document_exchange(messages, [{"type": "function"}])

    sent = captured["body"]["messages"]
    assert sent[0:2] == messages[0:2]
    assert all("old-call" not in str(message) for message in sent)
    assert any("live-call" in str(message) for message in sent)
    assert sent[-2:] == messages[-2:]


def test_mapping_exchange_uses_terminal_tool_when_freetoken_has_no_json_schema(monkeypatch):
    from proxy.services import smeta_chat_adapter_service as adapter

    captured = {}
    schema = {
        "type": "object",
        "properties": {"rows": {"type": "array", "maxItems": 1}},
        "required": ["rows"],
    }

    class Response:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{
                    "message": {
                        "tool_calls": [{
                            "id": "mapping-1",
                            "type": "function",
                            "function": {
                                "name": "submit_estimate_mapping",
                                "arguments": '{"rows":[{"work_id":"vor-0001","decision":"unbound"}]}',
                            },
                        }]
                    }
                }]
            }

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, **kwargs):
            captured["url"] = url
            captured["body"] = kwargs["json"]
            return Response()

    monkeypatch.setattr(adapter, "_smeta_model_runtime", lambda _name: adapter.LlmRuntime(
        "freetoken",
        "http://127.0.0.1:1919/v1",
        "http://127.0.0.1:1919/v1/chat/completions",
        "Qwen3.6-35B-A3B-NVFP4",
        "",
        False,
    ))
    monkeypatch.setattr(adapter.httpx, "Client", Client)

    result = adapter._smeta_document_mapping_exchange(
        [{"role": "user", "content": "Зафиксируй решение"}], schema
    )

    assert "response_format" not in captured["body"]
    assert captured["body"]["tools"][0]["function"] == {
        "name": "submit_estimate_mapping",
        "description": "Зафиксировать выбранное моделью решение без его изменения.",
        "parameters": schema,
    }
    assert captured["body"]["tool_choice"] == {
        "type": "function",
        "function": {"name": "submit_estimate_mapping"},
    }
    assert result["rows"][0]["work_id"] == "vor-0001"


def test_document_exchange_retries_ollama_tool_xml_syntax_error(monkeypatch):
    from proxy.services import smeta_chat_adapter_service as adapter

    posts: list[int] = []

    class Response:
        def __init__(self, status_code: int, text: str = "", message=None):
            self.status_code = status_code
            self.text = text
            self._message = message or {"content": "ok"}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise adapter.httpx.HTTPStatusError(
                    "boom",
                    request=adapter.httpx.Request("POST", "http://x"),
                    response=self,
                )

        def json(self):
            return {"message": self._message, "done_reason": "stop"}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url, **_kwargs):
            posts.append(1)
            if len(posts) == 1:
                return Response(
                    500,
                    text='{"error":"XML syntax error on line 4: '
                    'element <parameter> closed by </function>"}',
                )
            return Response(200, message={"content": "retry-ok"})

    monkeypatch.setattr(adapter, "_smeta_model_runtime", lambda _name: adapter.LlmRuntime(
        "ollama", "http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1/chat/completions",
        "qwen3.5:9b", "", True,
    ))
    monkeypatch.setattr(adapter.httpx, "Client", Client)

    result = adapter._smeta_document_exchange(
        [{"role": "user", "content": "Собери ЛСР"}],
        [{"type": "function", "function": {"name": "continue_norm_catalog"}}],
    )

    assert len(posts) == 2
    assert result["content"] == "retry-ok"


def test_document_exchange_soft_degrades_after_repeated_xml_tool_error(monkeypatch):
    from proxy.services import smeta_chat_adapter_service as adapter

    posts: list[dict] = []

    class Response:
        def __init__(self, status_code: int, text: str = ""):
            self.status_code = status_code
            self.text = text

        def raise_for_status(self):
            if self.status_code >= 400:
                raise adapter.httpx.HTTPStatusError(
                    "boom",
                    request=adapter.httpx.Request("POST", "http://x"),
                    response=self,
                )

        def json(self):
            return {"message": {"content": "unreachable"}}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url, **kwargs):
            posts.append(kwargs.get("json") or {})
            return Response(
                500,
                text='{"error":"XML syntax error on line 4: '
                'element <parameter> closed by </function>"}',
            )

    monkeypatch.setattr(adapter, "_smeta_model_runtime", lambda _name: adapter.LlmRuntime(
        "ollama", "http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1/chat/completions",
        "qwen3.5:9b", "", True,
    ))
    monkeypatch.setattr(adapter.httpx, "Client", Client)

    result = adapter._smeta_document_exchange(
        [{"role": "user", "content": "Собери ЛСР"}],
        [{"type": "function", "function": {"name": "continue_norm_catalog"}}],
    )

    assert len(posts) == 2
    assert posts[1]["options"]["seed"] == 1
    assert result["tool_calls"] == []
    assert "xml" in str(result.get("_les_xml_tool_error") or "").casefold()


@pytest.mark.asyncio
async def test_direct_application_preserves_model_owned_priced_flow(tmp_path, monkeypatch):
    request = SimpleNamespace(
        question="Сделай ЛСР",
        project_id=None,
        dataset_ids=["project-ds"],
        dataset_filter="PROJECT",
    )
    calls = {}
    events = []

    monkeypatch.setattr(
        "proxy.services.system_dataset_service.module_dataset_ids",
        lambda module_id: ["system-ds"] if module_id == "smeta" else [],
    )

    async def rag_context(req, *, rag_backend, dataset_ids, state):
        calls["rag"] = (req.dataset_filter, rag_backend, dataset_ids, state)
        return {
            "text": "evidence text",
            "trace": {"schema": "rag"},
            "sources": ["source.pdf"],
            "source_map": [{"file": "source.pdf"}],
        }

    def norm_lookup(question):
        calls["lookup_question"] = question
        return {"text": "norm cards", "trace": {"status": "ok", "results": [1, 2]}}

    def norm_choice(question, trace, progress):
        calls["choice"] = (question, trace)
        assert progress is not None
        progress({"event": "smeta_step", "data": {"phase": "model_choice"}})
        return {"rows": [{"work_id": "w1", "norm_code": "ГЭСН01"}], "trace": {"status": "ok"}}

    def model_answer(question, context):
        calls["answer"] = (question, context)
        return "Модельная смета"

    rim_form = {"schema": "rim", "rows": [{"work_id": "w1"}], "trace": {"summary": {"rows": 1}}}
    def build_form(rows, **_kwargs):
        calls["rim_rows"] = rows
        return rim_form

    monkeypatch.setattr(service, "build_checked_rim_form_from_visible_rows", build_form)
    monkeypatch.setattr(service, "build_smeta_artifact", lambda *_args, **_kwargs: {"mode": "model"})
    monkeypatch.setattr(service, "build_smeta_artifact_from_rim_form", lambda *_args, **_kwargs: {"mode": "rim"})
    monkeypatch.setattr(service, "persist_smeta_artifact_exports", lambda artifact, **_kwargs: artifact)
    monkeypatch.setattr(service, "compact_smeta_answer", lambda answer, artifact: f"{answer} [{artifact['mode']}]")

    async def sink(event):
        events.append(event)

    state = object()
    result = await service.run_smeta_direct_application(
        request=request,
        harness_question="SOURCE VOR",
        rag_backend="rag-backend",
        router_state=state,
        dataset_ids=["project-ds"],
        dataset_filter="PROJECT",
        pricing_requested=True,
        auto_estimate_work=False,
        dependencies=service.SmetaDirectDependencies(
            rag_context=rag_context,
            norm_lookup=norm_lookup,
            norm_choice=norm_choice,
            model_answer=model_answer,
            active_state=lambda question, answer: {"question": question, "answer": answer},
            model_runtime=lambda: SimpleNamespace(provider="openai", model="gpt-5.4"),
        ),
        token_sink=sink,
        artifact_dir=tmp_path,
    )

    assert result.operation == "smeta"
    assert result.answer == "Модельная смета [rim]"
    assert calls["rag"] == ("PROJECT", "rag-backend", ["project-ds", "system-ds"], state)
    assert request.dataset_filter == "PROJECT"
    assert "evidence text" in calls["lookup_question"]
    assert calls["choice"][1] == {"status": "ok", "results": [1, 2]}
    assert calls["rim_rows"] == [{"work_id": "w1", "norm_code": "ГЭСН01"}]
    assert "norm cards" in calls["answer"][1]
    assert "CHECKED RIM CALCULATION" in calls["answer"][1]
    assert result.extra["artifact"] == {"mode": "rim"}
    assert result.extra["sources"] == ["source.pdf"]
    assert result.extra["retrieval_trace"]["smeta_execution_mode"] == "priced_lsr"
    assert any(event.get("data", {}).get("phase") == "model_choice" for event in events)
    assert [event["data"]["phase"] for event in events if event.get("data", {}).get("status")] == [
        "rag_context", "rag_context", "norm_lookup", "norm_lookup",
        "norm_choice", "norm_choice", "final_answer", "final_answer",
    ]


@pytest.mark.asyncio
async def test_direct_application_answer_mode_does_not_calculate_or_choose(monkeypatch, tmp_path):
    request = SimpleNamespace(
        question="Объясни состав работ",
        project_id=None,
        dataset_ids=None,
        dataset_filter=None,
    )
    monkeypatch.setattr(
        "proxy.services.system_dataset_service.module_dataset_ids", lambda _module_id: []
    )
    choice_called = False

    def norm_choice(*_args):
        nonlocal choice_called
        choice_called = True
        return {}

    monkeypatch.setattr(service, "build_smeta_artifact", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "persist_smeta_artifact_exports", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "compact_smeta_answer", lambda answer, _artifact: answer)

    result = await service.run_smeta_direct_application(
        request=request,
        harness_question="Объясни состав работ",
        rag_backend=None,
        router_state=None,
        dataset_ids=None,
        dataset_filter=None,
        pricing_requested=False,
        auto_estimate_work=True,
        dependencies=service.SmetaDirectDependencies(
            rag_context=lambda *_args, **_kwargs: None,
            norm_lookup=lambda _question: {"text": "cards", "trace": {"status": "ok"}},
            norm_choice=norm_choice,
            model_answer=lambda _question, context: f"Ответ: {context}",
            active_state=lambda *_args: {},
            model_runtime=lambda: SimpleNamespace(provider="mlx", model="local"),
        ),
        artifact_dir=tmp_path,
    )

    assert choice_called is False
    assert result.operation == "smeta_auto_work"
    assert result.extra["retrieval_trace"]["smeta_execution_mode"] == "answer"
    assert result.extra["retrieval_trace"]["smeta_norm_choice"]["status"] == "not_requested"


@pytest.mark.asyncio
async def test_direct_priced_lsr_fails_closed_without_verified_rows(monkeypatch, tmp_path):
    request = SimpleNamespace(
        question="Сделай ЛСР",
        project_id=None,
        dataset_ids=None,
        dataset_filter=None,
    )
    monkeypatch.setattr(
        "proxy.services.system_dataset_service.module_dataset_ids", lambda _module_id: []
    )
    model_called = False

    def model_answer(*_args):
        nonlocal model_called
        model_called = True
        return "| Работа | Цена |\n|---|---:|\n| Выдуманная | 913700 |"

    result = await service.run_smeta_direct_application(
        request=request,
        harness_question="Файл распознан без строк",
        rag_backend=None,
        router_state=None,
        dataset_ids=None,
        dataset_filter=None,
        pricing_requested=True,
        auto_estimate_work=False,
        dependencies=service.SmetaDirectDependencies(
            rag_context=lambda *_args, **_kwargs: None,
            norm_lookup=lambda _question: {
                "text": "",
                "trace": {"source_rows_expected": 0, "results": []},
            },
            norm_choice=lambda *_args: {
                "rows": [],
                "trace": {"status": "no_lookup_results"},
            },
            model_answer=model_answer,
            active_state=lambda *_args: {},
            model_runtime=lambda: SimpleNamespace(provider="ollama", model="qwen3.5:9b"),
        ),
        artifact_dir=tmp_path,
    )

    assert result.operation == "smeta_verified_calculation_missing"
    assert result.crag == "ERROR"
    assert "913700" not in result.answer
    assert result.extra["retrieval_trace"]["smeta_failure"] == "verified_calculation_missing"
    assert model_called is False


@pytest.mark.asyncio
async def test_direct_application_model_failure_never_uses_code_fallback(monkeypatch, tmp_path):
    request = SimpleNamespace(
        question="Сделай ЛСР",
        project_id=None,
        dataset_ids=None,
        dataset_filter=None,
    )
    monkeypatch.setattr(
        "proxy.services.system_dataset_service.module_dataset_ids", lambda _module_id: []
    )
    monkeypatch.setenv("LES_SMETA_DIRECT_MODEL_PROVIDER", "openai")

    result = await service.run_smeta_direct_application(
        request=request,
        harness_question="Сделай ЛСР",
        rag_backend=None,
        router_state=None,
        dataset_ids=None,
        dataset_filter=None,
        pricing_requested=False,
        auto_estimate_work=False,
        dependencies=service.SmetaDirectDependencies(
            rag_context=lambda *_args, **_kwargs: None,
            norm_lookup=lambda _question: {"text": "", "trace": {}},
            norm_choice=lambda *_args: {},
            model_answer=lambda *_args: "",
            active_state=lambda *_args: {},
            model_runtime=lambda: SimpleNamespace(provider="mlx", model="local"),
        ),
        artifact_dir=tmp_path,
    )

    assert result.operation == "smeta_model_failed"
    assert result.crag == "ERROR"
    assert result.extra["retrieval_trace"]["code_fallback_disabled"] is True
    assert result.extra["retrieval_trace"]["cloud_config_warning"]
