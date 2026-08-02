"""Pluggable agent loops for the model-owned document smeta workflow."""

from __future__ import annotations

import asyncio
import copy
import json
import os
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Protocol

import httpx

from proxy.services.prompt_registry_service import smeta_native_skill_prompt
from proxy.smeta_core.document_workflow import (
    Progress,
    SmetaNormToolSession,
    _batch_norm_tools,
    _mapping_output_schema,
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


def _terminal_recovery_input(remaining_work_ids: list[str]) -> str:
    return (
        "You ended the estimating turn without a terminal tool call. Keep your own professional "
        "decision; LES code will not choose or improve it. Do not restart research. Now call "
        "submit_lsr_mapping exactly once for every remaining work_id: "
        + ", ".join(remaining_work_ids)
        + ". If your decision is unbound, include reason and complete unbound_evidence with at "
        "least two distinct queries_used copied verbatim from allowed_evidence returned by the tool, "
        "opened_norm_codes containing only cards you actually opened, at least one "
        "rejection_reasons item, and non-empty coverage_checked. Return no ordinary prose."
        " If your decision is bind, include norm_code, selection_kind, applicability, "
        "analog_limitations, candidate_evaluations for the selected norm and at least one opened "
        "alternative when search showed two or more candidates, and the complete technology_check "
        "required by the schema."
    )


def _requires_evidence_continuation(feedback: dict[str, Any] | None) -> bool:
    """Return true only when terminal repair cannot succeed without another tool read/search."""
    evidence_markers = (
        "was not opened through read_norms_batch",
        "not present in the opened structured cards",
        "requires opening at least one shown alternative",
        "cards not opened through tools",
        "opened_norm_codes must include a read_norms_batch card",
        "at least two distinct searches",
        "searches absent from the tool trace",
    )
    return any(
        marker in str(detail)
        for error in ((feedback or {}).get("errors") or [])
        for detail in (error.get("details") or [])
        for marker in evidence_markers
    )


def _qwen_terminal_schema(
    session: SmetaNormToolSession,
    validation_feedback: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Constrain recovery to executed facts and, on retry, the model's prior decision type."""
    remaining = session.remaining_work_ids
    allowed_by_work = {
        work_id: session._allowed_unbound_evidence(work_id)
        for work_id in remaining
    }
    allowed_bind_codes = {
        work_id: [
            str(code)
            for code in (evidence.get("opened_norm_codes") or [])
            if str(code)
        ]
        for work_id, evidence in allowed_by_work.items()
    }
    schema = _mapping_output_schema(
        remaining,
        # Before the first recovery Qwen must still be able to express a bind
        # decision so the strict session can tell it which evidence is missing.
        # Once at least one typed card is open, provider-side JSON is narrowed
        # to those factual codes as well.
        allowed_bind_codes=(
            allowed_bind_codes
            if any(allowed_bind_codes.values())
            else None
        ),
        allowed_coverage_targets={
            work_id: [
                target_work_id
                for target_work_id in session.by_id
                if target_work_id != work_id
            ]
            for work_id in remaining
        },
    )
    row_union = schema["properties"]["rows"]["items"]
    variants = list(row_union.get("oneOf") or [])

    feedback_errors = list((validation_feedback or {}).get("errors") or [])
    invalid_unbound_ids = {
        str(error.get("work_id") or "")
        for error in feedback_errors
        if str(error.get("error") or "") == "invalid unbound_evidence"
    }
    incomplete_bind_ids = {
        str(error.get("work_id") or "")
        for error in feedback_errors
        if str(error.get("error") or "") == "incomplete bind evidence"
    }
    if len(remaining) == 1 and remaining[0] in invalid_unbound_ids:
        # The first structured response already made the professional unbound
        # decision. The retry preserves it while asking for compact evidence;
        # executed queries and codes remain in the immutable tool trace.
        row_union["oneOf"] = [
            variant for variant in variants
            if (variant.get("properties") or {}).get("decision", {}).get("enum") == ["unbound"]
        ]
    elif len(remaining) == 1 and remaining[0] in incomplete_bind_ids:
        # The professional bind already exists. This retry only requires the
        # complete bind variant, constrained to cards the same model opened.
        row_union["oneOf"] = [
            variant for variant in variants
            if (variant.get("properties") or {}).get("decision", {}).get("enum") == ["bind"]
        ]
    return schema, allowed_by_work


def _qwen_agent_function_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Adapt a canonical tool schema to Qwen-Agent 0.0.34's root-key limit.

    The shared session still executes and validates the original LES contract;
    this facade changes only provider-side serialization and keeps all nested
    constraints intact.
    """
    payload = copy.deepcopy(schema)
    return {
        "type": "object",
        "properties": dict(payload.get("properties") or {}),
        "required": list(payload.get("required") or []),
    }


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

    def _structured_terminal_mapping(
        self,
        *,
        work_rows: list[dict[str, Any]],
        user_request: str,
        session: SmetaNormToolSession,
        final_messages: list[Any],
        validation_feedback: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Ask the same Qwen model to serialize its decision under a factual schema."""
        remaining = session.remaining_work_ids
        schema, allowed_by_work = _qwen_terminal_schema(session, validation_feedback)

        history = []
        for message in final_messages:
            if hasattr(message, "model_dump"):
                history.append(message.model_dump(mode="json", exclude_none=True))
            elif isinstance(message, dict):
                history.append(message)
            else:
                history.append({"content": str(message)})
        recovery_request = {
            "instruction": _terminal_recovery_input(remaining),
            "allowed_evidence_by_work_id": allowed_by_work,
            "validation_feedback": validation_feedback or {},
            "assistant_and_tool_history": history,
            "constraint": (
                "Return your own current decisions only. JSON Schema constrains factual provenance; "
                "it does not choose the professional decision."
            ),
        }
        ollama_root = self.ollama_base_url.rstrip("/")
        if ollama_root.casefold().endswith("/v1"):
            ollama_root = ollama_root[:-3]
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": smeta_native_skill_prompt()},
                {"role": "user", "content": _agent_input(work_rows, user_request)},
                {"role": "user", "content": json.dumps(recovery_request, ensure_ascii=False, default=str)},
            ],
            "format": schema,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.8,
                "top_k": 20,
                "min_p": 0.0,
                "num_predict": 4096,
                "num_ctx": 32768,
            },
        }
        try:
            with httpx.Client(timeout=300.0) as client:
                response = client.post(f"{ollama_root}/api/chat", json=body)
                if response.status_code >= 400:
                    body_fallback = dict(body)
                    body_fallback["format"] = "json"
                    response = client.post(f"{ollama_root}/api/chat", json=body_fallback)
                response.raise_for_status()
                payload = response.json()
        except Exception as error:
            raise RuntimeError(
                f"qwen structured terminal recovery failed: {type(error).__name__}: {error}"
            ) from error
        content = str(((payload.get("message") or {}).get("content") or ""))
        try:
            mapping = json.loads(content)
        except json.JSONDecodeError as error:
            raise RuntimeError("qwen structured terminal recovery returned invalid JSON") from error
        if not isinstance(mapping, dict) or not isinstance(mapping.get("rows"), list):
            raise RuntimeError("qwen structured terminal recovery returned no mapping rows")
        mapping["_les_model"] = str(payload.get("model") or self.model)
        return mapping

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
        recovery_state = {"attempted": False, "model_turns": 0}
        evidence_continuation_used = False
        dispatch_trace: list[dict[str, Any]] = []
        cancel_check = self.cancel_check

        class SessionTool(BaseTool):
            def __init__(self, specification: dict[str, Any]) -> None:
                function = specification["function"]
                self.name = str(function["name"])
                self.description = str(function.get("description") or "")
                self.parameters = _qwen_agent_function_schema(function["parameters"])
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
                if max(session.invalid_submission_attempts.values(), default=0) >= 3:
                    raise RuntimeError(
                        "qwen agent repeated invalid terminal mapping; switch the same model "
                        "to provider-enforced JSON Schema recovery"
                    )
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
                "temperature": 0.7,
                "top_p": 0.8,
                "top_k": 20,
                "min_p": 0.0,
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
        initial_message = {"role": "user", "content": _agent_input(work_rows, user_request)}
        final_messages: list[Any] = []
        first_run_error = ""
        recovery_trace: list[dict[str, Any]] = []
        try:
            for response in agent.run(
                messages=[initial_message],
            ):
                _cancelled(cancel_check)
                final_messages = list(response or [])
        except RuntimeError as exc:
            if not session.complete:
                first_run_error = str(exc)
        if not session.complete:
            _cancelled(cancel_check)
            recovery_state["attempted"] = True
            validation_feedback: dict[str, Any] | None = None
            for recovery_attempt in range(1, 3):
                _cancelled(cancel_check)
                recovery_state["model_turns"] += 1
                turn_counter["model"] += 1
                if progress:
                    progress({
                        "phase": "model_wait", "status": "started",
                        "label": f"Смета: Qwen фиксирует terminal mapping, попытка {recovery_attempt}",
                        "turn": turn_counter["model"],
                    })
                mapping = self._structured_terminal_mapping(
                    work_rows=work_rows,
                    user_request=user_request,
                    session=session,
                    final_messages=final_messages,
                    validation_feedback=validation_feedback,
                )
                rows = list(mapping.get("rows") or [])
                turn_counter["tool"] += 1
                arguments = {"rows": rows}
                dispatch_trace.append({
                    "tool": "submit_lsr_mapping",
                    "arguments": arguments,
                    "transport": "same_model_json_schema_recovery",
                })
                result = session.execute(
                    "submit_lsr_mapping",
                    arguments,
                    turn=turn_counter["tool"],
                )
                recovery_trace.append({
                    "turn": turn_counter["model"],
                    "assistant": {"role": "assistant", "content": json.dumps({"rows": rows}, ensure_ascii=False)},
                    "engine": self.engine,
                    "transport": "same_model_json_schema_recovery",
                    "tool_result": result,
                })
                if session.complete:
                    break
                validation_feedback = result
                if (
                    recovery_attempt == 1
                    and not evidence_continuation_used
                    and _requires_evidence_continuation(validation_feedback)
                ):
                    evidence_continuation_used = True
                    continuation = {
                        "role": "user",
                        "content": json.dumps({
                            "instruction": (
                                "Your own terminal mapping needs additional factual evidence. Resume the "
                                "same LES tool loop once: choose which shown alternatives matter, call "
                                "search_norms_batch/read_norms_batch only as needed, then call "
                                "submit_lsr_mapping. Do not let code choose a norm and do not answer in prose."
                            ),
                            "validation_feedback": validation_feedback,
                        }, ensure_ascii=False, default=str),
                    }
                    continuation_messages = [*final_messages, continuation]
                    try:
                        for response in agent.run(messages=continuation_messages):
                            _cancelled(self.cancel_check)
                            final_messages = list(response or [])
                    except RuntimeError as exc:
                        if not session.complete:
                            first_run_error = f"{first_run_error}; evidence_continuation={exc}".strip("; ")
                    if session.complete:
                        break
        if not session.complete:
            raise RuntimeError(
                "qwen agent ended without terminal mapping after same-model recovery for: "
                + ",".join(session.remaining_work_ids)
                + (f"; first_run_error={first_run_error}" if first_run_error else "")
                + "; validation_feedback="
                + json.dumps(validation_feedback or {}, ensure_ascii=False, default=str)[:1200]
                + "; dispatch="
                + json.dumps(dispatch_trace[-5:], ensure_ascii=False, default=str)[:1000]
            )
        model_trace = []
        for index, message in enumerate(final_messages, 1):
            payload = message.model_dump(mode="json", exclude_none=True) if hasattr(message, "model_dump") else dict(message)
            model_trace.append({"turn": index, "assistant": payload, "engine": self.engine})
        model_trace.extend(recovery_trace)
        return session.result(
            model_trace=model_trace,
            agent_trace={
                "mode": "qwen_agent_function_loop",
                "engine": self.engine,
                "provider": self.provider,
                "model": self.model,
                "model_turns": turn_counter["model"],
                "terminal_recovery_attempted": recovery_state["attempted"],
                "terminal_recovery_model_turns": recovery_state["model_turns"],
                "evidence_continuation_used": evidence_continuation_used,
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
