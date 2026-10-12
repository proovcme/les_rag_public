from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from proxy.services.les_module_contracts import (
    ChatContext,
    ChatRequestContext,
    ChatResponse,
    ModuleManifest,
)


def _manifest(tmp_path: Path, module_id: str, handlers: tuple[str, ...]) -> ModuleManifest:
    skill = tmp_path / module_id / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(f"# {module_id}\n", encoding="utf-8")
    return ModuleManifest(
        api_version="1.0",
        module_id=module_id,
        title=module_id,
        icon="o_extension",
        router_factories=(),
        panel_builder=None,
        chat_handler_factories=handlers,
        skill_path=str(skill),
        capabilities=("chat_context",),
    )


def _request() -> ChatRequestContext:
    return ChatRequestContext(
        request_id="req-1",
        user_id="operator",
        message="Проверь проект",
        mode="engineer",
        dataset_id="dataset-1",
        metadata={},
    )


def _context() -> ChatContext:
    return ChatContext(active_state={}, allowed_tools=("retrieval",), module_id="docs_review")


@pytest.mark.asyncio
async def test_chat_handlers_run_in_manifest_then_factory_order(tmp_path: Path) -> None:
    from proxy.services.les_module_mount_service import module_chat_handlers, run_module_chat_handlers

    calls: list[str] = []

    class Handler:
        def __init__(self, name: str):
            self.name = name

        async def handle(self, request, context):
            calls.append(self.name)
            return ChatResponse(False, None, {"system_instructions": self.name})

    manifests = (
        _manifest(tmp_path, "alpha", ("modules.alpha:first", "modules.alpha:second")),
        _manifest(tmp_path, "beta", ("modules.beta:first",)),
    )
    factories = {
        "modules.alpha:first": lambda: Handler("alpha-1"),
        "modules.alpha:second": lambda: Handler("alpha-2"),
        "modules.beta:first": lambda: Handler("beta-1"),
    }
    handlers = module_chat_handlers(manifests, resolve_entry_point=factories.__getitem__)

    response = await run_module_chat_handlers(_request(), _context(), handlers)

    assert calls == ["alpha-1", "alpha-2", "beta-1"]
    assert response.context_delta["system_instructions"] == (
        "alpha-1\nalpha-2\nbeta-1"
    )


@pytest.mark.asyncio
async def test_none_means_not_handled_and_chain_continues(tmp_path: Path) -> None:
    from proxy.services.les_module_mount_service import module_chat_handlers, run_module_chat_handlers

    class Skip:
        async def handle(self, request, context):
            return None

    class AddContext:
        async def handle(self, request, context):
            return ChatResponse(False, None, {"tool_instructions": "read_source only"})

    manifest = _manifest(
        tmp_path,
        "alpha",
        ("modules.alpha:skip", "modules.alpha:add_context"),
    )
    factories = {
        "modules.alpha:skip": Skip,
        "modules.alpha:add_context": AddContext,
    }
    handlers = module_chat_handlers((manifest,), resolve_entry_point=factories.__getitem__)

    response = await run_module_chat_handlers(_request(), _context(), handlers)

    assert response.context_delta == {"tool_instructions": "read_source only"}
    assert response.diagnostics == ()


@pytest.mark.asyncio
async def test_handler_exception_becomes_bounded_diagnostic_and_chain_continues(tmp_path: Path) -> None:
    from proxy.services.les_module_mount_service import module_chat_handlers, run_module_chat_handlers

    class Broken:
        async def handle(self, request, context):
            raise RuntimeError("database password leaked")

    class Healthy:
        async def handle(self, request, context):
            return ChatResponse(False, None, {"system_instructions": "healthy"})

    manifest = _manifest(
        tmp_path,
        "alpha",
        ("modules.alpha:broken", "modules.alpha:healthy"),
    )
    factories = {
        "modules.alpha:broken": Broken,
        "modules.alpha:healthy": Healthy,
    }
    handlers = module_chat_handlers((manifest,), resolve_entry_point=factories.__getitem__)

    response = await run_module_chat_handlers(_request(), _context(), handlers)

    assert response.context_delta == {"system_instructions": "healthy"}
    assert response.diagnostics == ("MODULE_HANDLER_FAILED:alpha",)
    assert "password" not in repr(response)


@pytest.mark.asyncio
async def test_malformed_handler_response_is_bounded_and_chain_continues(tmp_path: Path) -> None:
    from proxy.services.les_module_mount_service import module_chat_handlers, run_module_chat_handlers

    class MalformedContext:
        async def handle(self, request, context):
            return ChatResponse(False, None, None)

    class MalformedDiagnostics:
        async def handle(self, request, context):
            return ChatResponse(False, None, {}, "not-a-tuple")

    class Healthy:
        async def handle(self, request, context):
            return ChatResponse(False, None, {"system_instructions": "healthy"})

    manifests = (
        _manifest(tmp_path, "bad_context", ("modules.bad_context:handler",)),
        _manifest(tmp_path, "bad_diagnostics", ("modules.bad_diagnostics:handler",)),
        _manifest(tmp_path, "healthy", ("modules.healthy:handler",)),
    )
    handlers = module_chat_handlers(
        manifests,
        resolve_entry_point={
            "modules.bad_context:handler": MalformedContext,
            "modules.bad_diagnostics:handler": MalformedDiagnostics,
            "modules.healthy:handler": Healthy,
        }.__getitem__,
    )

    response = await run_module_chat_handlers(_request(), _context(), handlers)

    assert response.context_delta == {"system_instructions": "healthy"}
    assert response.diagnostics == (
        "MODULE_HANDLER_INVALID:bad_context",
        "MODULE_HANDLER_INVALID:bad_diagnostics",
    )


@pytest.mark.asyncio
async def test_code_owned_terminal_answer_is_rejected(tmp_path: Path) -> None:
    from proxy.services.les_module_mount_service import module_chat_handlers, run_module_chat_handlers

    class Terminal:
        async def handle(self, request, context):
            return ChatResponse(True, "Готовое профессиональное заключение", {})

    manifest = _manifest(tmp_path, "alpha", ("modules.alpha:terminal",))
    handlers = module_chat_handlers(
        (manifest,),
        resolve_entry_point=lambda _entry: Terminal,
    )

    response = await run_module_chat_handlers(_request(), _context(), handlers)

    assert response.terminal is False
    assert response.message is None
    assert response.context_delta == {}
    assert response.diagnostics == ("MODULE_CODE_OWNED_ANSWER_REJECTED:alpha",)
    assert "заключение" not in repr(response)


@pytest.mark.asyncio
async def test_chat_request_receives_module_context_only_for_model_generation(monkeypatch) -> None:
    from proxy.routers import chat

    async def fake_run(request, context, handlers=None):
        assert request.message == "Проверь проект"
        assert request.user_id == "operator"
        assert context.module_id == "docs_review"
        return ChatResponse(
            False,
            None,
            {
                "system_instructions": "Сверь состав источников.",
                "tool_instructions": "Используй только retrieval.",
            },
        )

    monkeypatch.setattr(chat, "run_module_chat_handlers", fake_run)
    original = chat.ChatRequest(
        question="Проверь проект",
        mode="review",
        output_directive="Ответь кратко.",
        dataset_ids=["dataset-1"],
    )

    prepared = await chat._apply_module_chat_context(
        original,
        SimpleNamespace(holder="operator", role="user"),
    )

    assert original.output_directive == "Ответь кратко."
    assert prepared.output_directive == (
        "Ответь кратко.\n"
        "Контекст подключенного модуля: Сверь состав источников.\n"
        "Инструкции подключенного модуля по инструментам: Используй только retrieval."
    )


@pytest.mark.asyncio
async def test_idempotent_module_prepare_failure_releases_reservation(monkeypatch) -> None:
    from proxy.routers import chat
    from proxy.services import request_idempotency_service

    released: list[dict[str, object]] = []

    monkeypatch.setattr(chat, "_require_candidate_acceptance", lambda *_args: None)

    async def fail_prepare(*_args, **_kwargs):
        raise RuntimeError("module response malformed")

    monkeypatch.setattr(chat, "_apply_module_chat_context", fail_prepare)
    monkeypatch.setattr(request_idempotency_service, "caller_scope", lambda _user: "operator")
    monkeypatch.setattr(request_idempotency_service, "request_fingerprint", lambda _payload: "hash")
    monkeypatch.setattr(request_idempotency_service, "begin", lambda **_kwargs: ("started", None))
    monkeypatch.setattr(
        request_idempotency_service,
        "release",
        lambda **kwargs: released.append(kwargs),
    )

    with pytest.raises(RuntimeError, match="module response malformed"):
        await chat.chat(
            chat.ChatRequest(question="Проверь проект"),
            SimpleNamespace(holder="operator", role="user"),
            "request-key",
        )

    assert released == [
        {
            "operation": "chat",
            "caller": "operator",
            "idempotency_key": "request-key",
            "request_hash": "hash",
        }
    ]
