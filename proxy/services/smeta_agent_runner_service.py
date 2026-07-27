"""Pluggable agent loops for the model-owned document smeta workflow."""

from __future__ import annotations

import asyncio
import copy
import json
import os
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Protocol

from proxy.services.prompt_registry_service import smeta_native_skill_prompt
from proxy.smeta_core.document_workflow import (
    Progress,
    SmetaNormToolSession,
    _batch_norm_tools,
)


CancelCheck = Callable[[], bool]
SUPPORTED_SMETA_AGENT_ENGINES = ("native", "qwen_agent", "google_adk")


def normalize_smeta_agent_engine(value: str | None) -> str:
    engine = str(value or "native").strip().lower()
    if engine not in SUPPORTED_SMETA_AGENT_ENGINES:
        raise ValueError(f"unsupported smeta agent engine: {engine}")
    return engine


class SmetaAgentRunner(Protocol):
    engine: str
    provider: str
    model: str

    def run_batch(
        self,
        work_rows: list[dict[str, Any]],
        *,
        candidate_limit: int,
        max_turns: int,
        progress: Progress | None,
        user_request: str,
    ) -> dict[str, Any]: ...


def _agent_input(work_rows: list[dict[str, Any]], user_request: str) -> str:
    return json.dumps({
        "user_request": str(user_request or "").strip(),
        "work_items": work_rows,
        "batch_contract": (
            "Use only LES tools supplied to you. Search and open evidence before binding. "
            "Finish by calling submit_lsr_mapping for every work_id. Neighbor rows are context only."
        ),
    }, ensure_ascii=False, default=str)


def _cancelled(cancel_check: CancelCheck) -> None:
    if cancel_check():
        raise RuntimeError("smeta document workflow cancelled by user")


def _google_function_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove conditionals unsupported by Gemini function declarations.

    The shared session still applies the same terminal reference-integrity
    checks; this changes only provider-side JSON serialization.
    """
    payload = copy.deepcopy(schema)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("allOf", "if", "then", "else", "const"):
                value.pop(key, None)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return payload


@dataclass
class QwenAgentSmetaRunner:
    model: str = "qwen3.5:9b"
    ollama_base_url: str = "http://127.0.0.1:11434"
    cancel_check: CancelCheck = lambda: False
    engine: str = "qwen_agent"
    provider: str = "ollama"

    def run_batch(
        self,
        work_rows: list[dict[str, Any]],
        *,
        candidate_limit: int,
        max_turns: int,
        progress: Progress | None,
        user_request: str,
    ) -> dict[str, Any]:
        from qwen_agent.agents import FnCallAgent
        from qwen_agent.tools.base import BaseTool

        _cancelled(self.cancel_check)
        skill = smeta_native_skill_prompt()
        if not skill:
            raise RuntimeError("canonical smeta skill is unavailable")
        session = SmetaNormToolSession(
            work_rows, candidate_limit=candidate_limit, progress=progress,
        )
        turn_counter = {"tool": 0, "model": 0}
        dispatch_trace: list[dict[str, Any]] = []
        cancel_check = self.cancel_check

        class SessionTool(BaseTool):
            def __init__(self, specification: dict[str, Any]) -> None:
                function = specification["function"]
                self.name = str(function["name"])
                self.description = str(function.get("description") or "")
                self.parameters = dict(function["parameters"])
                super().__init__()

            def call(self, params: str | dict[str, Any], **_: Any) -> str:
                _cancelled(cancel_check)
                if isinstance(params, dict):
                    arguments = params
                else:
                    try:
                        parsed = json.loads(str(params or "{}"))
                    except json.JSONDecodeError:
                        parsed = {}
                    arguments = parsed if isinstance(parsed, dict) else {}
                turn_counter["tool"] += 1
                if progress:
                    progress({
                        "phase": "agent_tool", "status": "started",
                        "label": f"Смета: Qwen-Agent вызывает {self.name}",
                        "turn": turn_counter["tool"], "tool": self.name,
                    })
                result = session.execute(self.name, arguments, turn=turn_counter["tool"])
                _cancelled(cancel_check)
                return json.dumps(result, ensure_ascii=False, default=str)

        class BoundedFnCallAgent(FnCallAgent):
            def _call_tool(self, tool_name: str, tool_args: str | dict[str, Any] = "{}", **kwargs: Any) -> str:
                dispatch_trace.append({"tool": tool_name, "arguments": tool_args})
                if progress:
                    progress({
                        "phase": "agent_dispatch", "status": "started",
                        "label": f"Смета: Qwen-Agent передал вызов {tool_name}",
                        "tool": tool_name,
                    })
                return super()._call_tool(tool_name, tool_args, **kwargs)

            def _call_llm(self, *args: Any, **kwargs: Any):
                if session.complete:
                    raise RuntimeError("qwen agent terminal mapping accepted")
                _cancelled(cancel_check)
                if turn_counter["model"] >= max_turns:
                    raise RuntimeError(
                        f"qwen agent exceeded {max_turns} model turns without terminal mapping; "
                        f"dispatch={json.dumps(dispatch_trace[-3:], ensure_ascii=False, default=str)[:600]}"
                    )
                turn_counter["model"] += 1
                if progress:
                    progress({
                        "phase": "model_wait", "status": "started",
                        "label": f"Смета: Qwen-Agent выполняет ход {turn_counter['model']}",
                        "turn": turn_counter["model"],
                    })
                return super()._call_llm(*args, **kwargs)

        tools = [SessionTool(specification) for specification in _batch_norm_tools()]
        llm = {
            "model": self.model,
            "model_server": self.ollama_base_url.rstrip("/") + "/v1",
            "api_key": "EMPTY",
            "generate_cfg": {
                "fncall_prompt_type": "nous",
                # Qwen-Agent 0.0.34's Nous text wrapper collides with Ollama's
                # always-on native Qwen tool parser (server returns 500 EOF).
                # The framework still owns the loop; raw API delegates only
                # serialization/parsing of declared function calls to Ollama.
                "use_raw_api": True,
                "max_input_tokens": 32768,
                "max_tokens": 4096,
                "temperature": 0.0,
                # Ollama's OpenAI-compatible endpoint controls thinking through
                # the documented OpenAI field, not the native `/api/chat`
                # `think` flag. Without this, Qwen-Agent receives an empty
                # content stream while Ollama emits only a private thinking field.
                "reasoning_effort": "none",
            },
        }
        agent = BoundedFnCallAgent(
            function_list=tools,
            llm=llm,
            system_message=skill,
            name="les_smeta_qwen_agent",
            description="LES document estimating agent",
        )
        started = perf_counter()
        final_messages: list[Any] = []
        try:
            for response in agent.run(
                messages=[{"role": "user", "content": _agent_input(work_rows, user_request)}],
            ):
                _cancelled(cancel_check)
                final_messages = list(response or [])
        except RuntimeError:
            if not session.complete:
                raise
        model_trace = []
        for index, message in enumerate(final_messages, 1):
            payload = message.model_dump(mode="json", exclude_none=True) if hasattr(message, "model_dump") else dict(message)
            model_trace.append({"turn": index, "assistant": payload, "engine": self.engine})
        return session.result(
            model_trace=model_trace,
            agent_trace={
                "mode": "qwen_agent_function_loop",
                "engine": self.engine,
                "provider": self.provider,
                "model": self.model,
                "model_turns": turn_counter["model"],
                "tool_turns": turn_counter["tool"],
                "dispatch_trace": dispatch_trace,
                "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                "token_usage": {},
            },
        )


@dataclass
class GoogleAdkSmetaRunner:
    api_key: str
    model: str = "gemini-3.5-flash"
    cloud_consent: bool = False
    cancel_check: CancelCheck = lambda: False
    engine: str = "google_adk"
    provider: str = "google"

    def __post_init__(self) -> None:
        if not self.cloud_consent:
            raise PermissionError(
                "Google ADK disabled: explicit cloud consent is required for the source document"
            )
        if not str(self.api_key or "").strip():
            raise RuntimeError("Google ADK unavailable: GOOGLE_API_KEY is not configured")

    def run_batch(
        self,
        work_rows: list[dict[str, Any]],
        *,
        candidate_limit: int,
        max_turns: int,
        progress: Progress | None,
        user_request: str,
    ) -> dict[str, Any]:
        return asyncio.run(self._run_batch_async(
            work_rows,
            candidate_limit=candidate_limit,
            max_turns=max_turns,
            progress=progress,
            user_request=user_request,
        ))

    async def _run_batch_async(
        self,
        work_rows: list[dict[str, Any]],
        *,
        candidate_limit: int,
        max_turns: int,
        progress: Progress | None,
        user_request: str,
    ) -> dict[str, Any]:
        from google.adk.agents import LlmAgent
        from google.adk.models.google_llm import Gemini
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.adk.tools import BaseTool
        from google.genai import types

        _cancelled(self.cancel_check)
        skill = smeta_native_skill_prompt()
        if not skill:
            raise RuntimeError("canonical smeta skill is unavailable")
        session = SmetaNormToolSession(
            work_rows, candidate_limit=candidate_limit, progress=progress,
        )
        turn_counter = {"tool": 0, "model": 0}
        cancel_check = self.cancel_check

        class SessionTool(BaseTool):
            def __init__(self, specification: dict[str, Any]) -> None:
                function = specification["function"]
                self._parameters = _google_function_schema(function["parameters"])
                super().__init__(
                    name=str(function["name"]),
                    description=str(function.get("description") or ""),
                )

            def _get_declaration(self):
                return types.FunctionDeclaration(
                    name=self.name,
                    description=self.description,
                    parametersJsonSchema=self._parameters,
                )

            async def run_async(self, *, args: dict[str, Any], tool_context: Any) -> Any:
                del tool_context
                _cancelled(cancel_check)
                turn_counter["tool"] += 1
                if progress:
                    progress({
                        "phase": "agent_tool", "status": "started",
                        "label": f"Смета: Google ADK вызывает {self.name}",
                        "turn": turn_counter["tool"], "tool": self.name,
                    })
                result = session.execute(self.name, args, turn=turn_counter["tool"])
                _cancelled(cancel_check)
                return result

        def before_model_callback(_context: Any, _request: Any) -> None:
            _cancelled(cancel_check)
            if turn_counter["model"] >= max_turns:
                raise RuntimeError(
                    f"Google ADK exceeded {max_turns} model turns without terminal mapping"
                )
            turn_counter["model"] += 1
            if progress:
                progress({
                    "phase": "model_wait", "status": "started",
                    "label": f"Смета: Google ADK выполняет ход {turn_counter['model']}",
                    "turn": turn_counter["model"],
                })

        agent = LlmAgent(
            name="les_smeta_google_adk",
            model=Gemini(model=self.model, client_kwargs={"api_key": self.api_key.strip()}),
            instruction=skill,
            tools=[SessionTool(specification) for specification in _batch_norm_tools()],
            generate_content_config=types.GenerateContentConfig(temperature=0.0),
            before_model_callback=before_model_callback,
        )
        session_service = InMemorySessionService()
        app_name = "les_smeta"
        user_id = "les_smeta_document"
        session_id = "zero_state"
        await session_service.create_session(
            app_name=app_name, user_id=user_id, session_id=session_id,
        )
        runner = Runner(
            app_name=app_name, agent=agent, session_service=session_service,
        )
        started = perf_counter()
        events = []
        usage = {
            "prompt_tokens": 0,
            "candidate_tokens": 0,
            "total_tokens": 0,
        }
        try:
            message = types.Content(
                role="user", parts=[types.Part.from_text(text=_agent_input(work_rows, user_request))],
            )
            try:
                async for event in runner.run_async(
                    user_id=user_id, session_id=session_id, new_message=message,
                ):
                    _cancelled(cancel_check)
                    payload = event.model_dump(mode="json", exclude_none=True)
                    events.append(payload)
                    metadata = event.usage_metadata
                    if metadata:
                        usage["prompt_tokens"] += int(metadata.prompt_token_count or 0)
                        usage["candidate_tokens"] += int(metadata.candidates_token_count or 0)
                        usage["total_tokens"] += int(metadata.total_token_count or 0)
            except RuntimeError:
                if not session.complete:
                    raise
        finally:
            await runner.close()
        return session.result(
            model_trace=[
                {"turn": index, "event": event, "engine": self.engine}
                for index, event in enumerate(events, 1)
            ],
            agent_trace={
                "mode": "google_adk_function_loop",
                "engine": self.engine,
                "provider": self.provider,
                "model": self.model,
                "model_turns": turn_counter["model"],
                "tool_turns": turn_counter["tool"],
                "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                "token_usage": usage,
            },
        )


def build_smeta_agent_runner(
    engine: str,
    *,
    cancel_check: CancelCheck,
) -> SmetaAgentRunner | None:
    normalized = normalize_smeta_agent_engine(engine)
    if normalized == "native":
        return None
    if normalized == "qwen_agent":
        return QwenAgentSmetaRunner(
            model=os.getenv("LES_SMETA_QWEN_MODEL", "qwen3.5:9b").strip() or "qwen3.5:9b",
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            cancel_check=cancel_check,
        )
    return GoogleAdkSmetaRunner(
        api_key=os.getenv("GOOGLE_API_KEY", ""),
        model=os.getenv("LES_SMETA_GOOGLE_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash",
        cloud_consent=os.getenv("LES_CLOUD_CONSENT", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        cancel_check=cancel_check,
    )
