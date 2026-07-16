from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from proxy.services import smeta_chat_application_service as service
from proxy.services.smeta_chat_adapter_service import _smeta_document_turn_tokens


def test_smeta_document_turn_budget_is_large_only_after_norm_cards_are_opened():
    assert _smeta_document_turn_tokens([{"role": "user", "content": "ВОР"}], 8000) == 1600
    assert _smeta_document_turn_tokens(
        [{"role": "tool", "name": "search_norms_batch", "content": "{}"}], 8000
    ) == 1000
    assert _smeta_document_turn_tokens(
        [{"role": "tool", "name": "read_norms_batch", "content": "{}"}], 8000
    ) == 8000


@pytest.mark.asyncio
async def test_document_application_preserves_stream_artifact_and_trace(tmp_path, monkeypatch):
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
        "model_requested": "gpt-5.4",
        "model": "gpt-5.4",
        "models_used": ["gpt-5.4"],
        "model_fallbacks": [],
        "model_calls": 1,
    }
    assert workflow_call["candidate_limit"] == 12
    assert workflow_call["batch_size"] == 0
    assert workflow_call["source_name"] == "ВОР тест.pdf"
    assert workflow_call["user_request"] == "Сделай ЛСР"
    assert exchange_attempts == 2
    assert consumed == ["read_0123456789ab"]
    assert [event["data"]["phase"] for event in events] == [
        "document_workflow",
        "batch_search",
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
    monkeypatch.setattr(
        service,
        "run_vor_document_workflow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider down")),
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
    assert consumed == []


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
    assert seen["batch_size"] == 0


def test_document_exchange_requires_tool_and_falls_back_from_non_tool_ollama(monkeypatch):
    from proxy.services import smeta_chat_adapter_service as adapter

    bodies = []
    urls = []

    class Response:
        status_code = 200

        def __init__(self, message):
            self._message = message

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": self._message}], "message": self._message}

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
            if len(bodies) <= 2:
                return Response({"content": "Я отвечу текстом"})
            return Response({"tool_calls": [{"id": "tool-1", "function": {"name": "search_norms_batch"}}]})

    monkeypatch.setattr(adapter, "_smeta_model_runtime", lambda _name: adapter.LlmRuntime(
        "ollama", "http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1/chat/completions",
        "gemma4:12b", "", True,
    ))
    monkeypatch.setattr(adapter.httpx, "Client", Client)

    result = adapter._smeta_document_exchange(
        [{"role": "user", "content": "Собери ЛСР"}],
        [{"type": "function", "function": {"name": "search_norms_batch"}}],
    )

    assert result["tool_calls"][0]["id"] == "tool-1"
    assert result["_les_model"] == "qwen3.5:9b"
    assert result["_les_fallback_from"] == "gemma4:12b"
    assert bodies[1]["messages"][-1]["content"].startswith("Продолжи только")
    assert bodies[1]["model"] == "gemma4:12b"
    assert bodies[2]["messages"][-1]["content"].startswith("Продолжи только")
    assert bodies[2]["model"] == "qwen3.5:9b"
    assert "options" in bodies[0]
    assert urls == ["http://127.0.0.1:11434/api/chat"] * 3


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
