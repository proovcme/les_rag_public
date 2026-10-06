"""Provider-neutral HTTP transport for resolved model connections."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
import asyncio
from dataclasses import dataclass, field
import json
import os
from types import MappingProxyType
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx

from proxy.services.llm_transport_profile_service import (
    apply_transport_options,
    assistant_delta_text,
    final_assistant_text,
    FinalTextFilter,
    provider_is_local,
)
from proxy.services.model_connection_contracts import CapabilityName, CapabilityState, ConnectionLocality
from proxy.services.model_connection_resolver_service import ResolvedModelConnection
from proxy.services.model_connection_security_service import (
    ValidatedEndpoint,
    join_openai_path,
    validate_connected_peer,
)
from proxy.services.model_secret_service import EnvironmentSecretStore, ModelSecretError
from proxy.services.model_wire_token_count_service import (
    InputTokenCount, UnsupportedTokenCountWire, model_token_count_payload,
    normalize_model_count_wire, supports_model_token_count, wire_sha256,
    TOKEN_COUNT_SOURCE, TOKEN_COUNT_PROVIDER_OWNER,
)


CHAT_RESPONSE_BODY_LIMIT = 512 * 1024
TOKEN_COUNT_TIMEOUT_SECONDS = 15.0


class ModelTransportError(RuntimeError):
    """The exact resolved connection could not complete a safe request."""


class CloudBudgetStop(RuntimeError):
    """A technical spending stop; never a transport failure eligible for fallback."""


PeerVerifier = Callable[[httpx.Response, ValidatedEndpoint], None]


@dataclass(frozen=True)
class InferenceRequest:
    messages: Sequence[Mapping[str, Any]]
    max_output_tokens: int
    temperature: float | None = None
    tools: Sequence[Mapping[str, Any]] = ()
    response_format: Mapping[str, Any] | None = None
    reasoning_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.reasoning_enabled, bool):
            raise ValueError("reasoning_enabled must be a boolean")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        object.__setattr__(self, "messages", tuple(dict(item) for item in self.messages))
        object.__setattr__(self, "tools", tuple(dict(item) for item in self.tools))
        if self.response_format is not None:
            object.__setattr__(self, "response_format", dict(self.response_format))


@dataclass(frozen=True)
class InferenceResponse:
    text: str
    tool_calls: tuple[Mapping[str, Any], ...]
    finish_reason: str
    usage: Mapping[str, int]
    model_id: str = ""
    # Provider protocol state, never visible answer text or a public receipt.
    reasoning_content: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class InferenceEvent:
    kind: str
    text: str = ""
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    finish_reason: str = ""
    model_id: str = ""


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: tuple[tuple[float, ...], ...]
    model_id: str
    usage: Mapping[str, int]


def _usage(value: object) -> Mapping[str, int]:
    if not isinstance(value, Mapping):
        return MappingProxyType({})
    result: dict[str, int] = {}
    for key, raw in value.items():
        if isinstance(raw, bool):
            continue
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            result[str(key)] = parsed
    return MappingProxyType(result)


def _message_text(message: Mapping[str, Any]) -> str:
    return final_assistant_text(message)


class OpenAICompatibleTransport:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        secret_store: EnvironmentSecretStore,
        peer_verifier: PeerVerifier = validate_connected_peer,
        response_body_limit: int = 32_768,
        timeout: float = 120.0,
    ):
        if response_body_limit < 1:
            raise ValueError("response_body_limit must be positive")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.client = client
        self.secret_store = secret_store
        self.peer_verifier = peer_verifier
        self.response_body_limit = response_body_limit
        self.timeout = timeout
        # One transport is shared by all calls in one chat turn, including retries.
        # This is deliberately not an account balance or a resumable-job allowance.
        self._cloud_budget_limit = int(os.getenv("LES_CLOUD_TURN_TOKEN_BUDGET", "0"))
        if self._cloud_budget_limit < 0:
            raise ValueError("LES_CLOUD_TURN_TOKEN_BUDGET must be nonnegative")
        self._cloud_accounted = 0
        self._cloud_requests = 0
        self._cloud_usage_requests = 0
        self._cloud_reported_tokens = 0
        self._cloud_last_attempt: dict[str, Any] = {}
        self._token_count_last_attempt: dict[str, Any] = {}

    def token_count_snapshot(self) -> dict[str, Any]:
        """Count provenance or a visible estimator fallback, never prompt bodies."""
        return dict(self._token_count_last_attempt)

    def cloud_budget_snapshot(self) -> dict[str, Any]:
        return {"limit_tokens": self._cloud_budget_limit, "accounted_tokens": self._cloud_accounted,
                "requests_sent": self._cloud_requests, "requests_with_usage": self._cloud_usage_requests,
                "reported_tokens": self._cloud_reported_tokens,
                "unsettled_reservation_tokens": self._cloud_accounted - self._cloud_reported_tokens,
                "last_attempt": dict(self._cloud_last_attempt),
                "remaining_tokens": max(0, self._cloud_budget_limit - self._cloud_accounted),
                "reservation_method": "utf8_wire_bytes_plus_1024_plus_total_output_cap_plus_10",
                "scope": "one_chat_turn", "provider_balance": "unknown"}

    def _cloud_reservation(self, connection: ResolvedModelConnection, body: Mapping[str, Any]) -> int:
        if not self._cloud_budget_limit or connection.locality is not ConnectionLocality.REMOTE:
            return 0
        limit = body.get("max_completion_tokens")
        if type(limit) is not int or limit <= 0:
            raise CloudBudgetStop("CLOUD_TURN_TOKEN_BUDGET: TOTAL_OUTPUT_CAP_REQUIRED")
        # Byte-based reservation is conservative for text; it is not a tokenizer
        # or a valid estimate for images/audio. Do not silently admit those inputs.
        if any(not isinstance(m.get("content", ""), (str, type(None))) for m in body.get("messages", ())):
            raise CloudBudgetStop("CLOUD_TURN_TOKEN_BUDGET: TEXT_INPUT_REQUIRED")
        reserve = len(json.dumps(body, ensure_ascii=False).encode("utf-8")) + 1024 + limit + 10
        self._cloud_last_attempt = {
            "number": self._cloud_requests + 1,
            "reservation_tokens": reserve,
            "output_cap_tokens": limit,
            "wire_bytes": reserve - 1024 - limit - 10,
            "message_count": len(body.get("messages", ())),
            "tool_count": len(body.get("tools", ())),
            "sent": False,
        }
        self._cloud_last_attempt["message_bytes_by_role"] = {
            role: sum(len(json.dumps(m, ensure_ascii=False).encode("utf-8"))
                      for m in body.get("messages", ()) if m.get("role") == role)
            for role in ("system", "developer", "user", "assistant", "tool")
        }
        return reserve

    def cloud_request_fits(self, connection: ResolvedModelConnection, request: InferenceRequest) -> bool:
        """Exact wire preflight for ContextGovernor; never sends or reserves funds."""
        reserve = self._cloud_reservation(connection, self._chat_body(connection, request, stream=False))
        return not reserve or self._cloud_accounted + reserve <= self._cloud_budget_limit

    def _reserve_cloud(self, connection: ResolvedModelConnection, body: Mapping[str, Any]) -> int:
        reserve = self._cloud_reservation(connection, body)
        if not reserve:
            return 0
        if self._cloud_accounted + reserve > self._cloud_budget_limit:
            raise CloudBudgetStop(
                f"CLOUD_TURN_TOKEN_BUDGET: limit={self._cloud_budget_limit}, "
                f"accounted={self._cloud_accounted}, next_reservation={reserve}"
            )
        self._cloud_accounted += reserve
        self._cloud_requests += 1
        self._cloud_last_attempt["sent"] = True
        return reserve

    def _settle_cloud(self, response: httpx.Response, usage: object) -> None:
        reserved = response.extensions.pop("les_cloud_reservation", 0)
        if not reserved or not isinstance(usage, Mapping):
            return
        prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if type(prompt) is not int or type(completion) is not int or prompt <= 0 or completion < 0:
            return  # Failed/unknown usage remains charged at the full reservation.
        total = usage.get("total_tokens", prompt + completion)
        if type(total) is not int or total < prompt + completion:
            return
        self._cloud_accounted += total - reserved
        self._cloud_usage_requests += 1
        self._cloud_reported_tokens += total

    @staticmethod
    def _require(connection: ResolvedModelConnection, capability: CapabilityName) -> None:
        observation = connection.capability_snapshot.observation(capability)
        if observation.state is not CapabilityState.SUPPORTED:
            raise ModelTransportError(f"CAPABILITY_REQUIRED: {capability.value}")
        if observation.evidence_source in {"template_default", "unavailable"}:
            raise ModelTransportError(
                f"CAPABILITY_EVIDENCE_INSUFFICIENT: {capability.value}"
            )

    def _headers(self, connection: ResolvedModelConnection) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        try:
            secret = self.secret_store.resolve(connection.secret_ref)
        except ModelSecretError as exc:
            raise ModelTransportError("CONNECTION_SECRET_MISSING") from exc
        if secret is not None:
            headers["Authorization"] = f"Bearer {secret.reveal()}"
        return headers

    @staticmethod
    def _output_field(connection: ResolvedModelConnection) -> str:
        return connection.chat_options.output_field(
            connection.capability_snapshot.transport_options.get("max_output_field", "max_tokens")
        )

    def _chat_body(
        self,
        connection: ResolvedModelConnection,
        request: InferenceRequest,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        messages = [dict(item) for item in request.messages]
        system_messages = [item for item in messages if item.get("role") == "system"]
        conversation = [item for item in messages if item.get("role") != "system"]
        if system_messages and all(isinstance(item.get("content"), str) for item in system_messages):
            system_messages = [{
                **system_messages[0],
                "content": "\n\n".join(str(item["content"]) for item in system_messages),
            }]
        body: dict[str, Any] = {
            "model": connection.model_id,
            "messages": system_messages + conversation,
            **connection.chat_options.parameters(
                max_output_tokens=request.max_output_tokens, temperature=request.temperature,
                reasoning_enabled=request.reasoning_enabled, legacy_field=self._output_field(connection),
                include_reasoning=not provider_is_local(connection.extension_type),
            ),
        }
        if request.tools:
            self._require(connection, CapabilityName.TOOLS)
            body["tools"] = [dict(item) for item in request.tools]
        if request.response_format is not None:
            self._require(connection, CapabilityName.STRUCTURED_OUTPUT)
            body["response_format"] = dict(request.response_format)
        if stream:
            body["stream"] = True
        if provider_is_local(connection.extension_type):
            local_body = apply_transport_options(
                body, connection.extension_type, reasoning_enabled=request.reasoning_enabled
            )
            return normalize_model_count_wire(local_body, connection.extension_type)
        return body

    @staticmethod
    def _native_chat_url(connection: ResolvedModelConnection) -> str:
        parsed = urlsplit(connection.endpoint.canonical_base_url)
        path = parsed.path.rstrip("/")
        for suffix in ("/api/v1", "/v1"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
                break
        return urlunsplit((parsed.scheme, parsed.netloc, f"{path}/api/chat", "", ""))

    @staticmethod
    def _native_chat_body(
        connection: ResolvedModelConnection,
        request: InferenceRequest,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "num_predict": min(request.max_output_tokens, connection.chat_options.requested_output_tokens or request.max_output_tokens),
            "num_ctx": int(connection.effective_preset.input_token_limit),
        }
        if request.temperature is not None and connection.chat_options.temperature_mode == "profile":
            options["temperature"] = request.temperature
        body: dict[str, Any] = {
            "model": connection.model_id,
            "messages": [dict(item) for item in request.messages],
            "think": request.reasoning_enabled,
            # Native chat sends one NDJSON event per generated fragment.
            # Consuming it keeps a long local generation alive while complete()
            # still returns the exact concatenated model answer as one value.
            "stream": True,
            "options": options,
        }
        if request.tools:
            body["tools"] = [dict(item) for item in request.tools]
        if request.response_format is not None:
            response_format = dict(request.response_format)
            if response_format.get("type") == "json_schema":
                json_schema = response_format.get("json_schema") or {}
                body["format"] = dict(json_schema.get("schema") or {})
            elif response_format.get("type") == "json_object":
                body["format"] = "json"
        return body

    async def _complete_native_chat(
        self,
        connection: ResolvedModelConnection,
        request: InferenceRequest,
    ) -> InferenceResponse:
        if request.tools:
            self._require(connection, CapabilityName.TOOLS)
        if request.response_format is not None:
            self._require(connection, CapabilityName.STRUCTURED_OUTPUT)
        response = await self._open(
            connection,
            url=self._native_chat_url(connection),
            body=self._native_chat_body(connection, request),
        )
        try:
            if not 200 <= response.status_code < 300:
                await self._read_bounded(response)
                raise ModelTransportError(f"UPSTREAM_HTTP_ERROR: {response.status_code}")

            semantic_size = 0
            event_count = 0
            event_count_limit = max(256, request.max_output_tokens * 8)
            event_wire_limit = max(1024, self.response_body_limit * 8)
            saw_event = False
            text_parts: list[str] = []
            final_filter = FinalTextFilter()
            tool_calls: list[Mapping[str, Any]] = []
            prompt_tokens = 0
            completion_tokens = 0
            finish_reason = ""
            model_id = connection.model_id
            async for line in response.aiter_lines():
                event_count += 1
                if event_count > event_count_limit or len(line.encode("utf-8")) > event_wire_limit:
                    raise ModelTransportError("UPSTREAM_RESPONSE_TOO_LARGE")
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                    message = payload["message"]
                    if not isinstance(message, Mapping):
                        raise TypeError("message must be a mapping")
                    prompt_tokens = int(payload.get("prompt_eval_count") or prompt_tokens)
                    completion_tokens = int(payload.get("eval_count") or completion_tokens)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ModelTransportError("UPSTREAM_RESPONSE_INVALID") from exc
                saw_event = True
                model_id = str(payload.get("model") or model_id)
                content = message.get("content")
                if isinstance(content, str) and content:
                    semantic_size += len(content.encode("utf-8"))
                    if semantic_size > self.response_body_limit:
                        raise ModelTransportError("UPSTREAM_RESPONSE_TOO_LARGE")
                    visible = final_filter.feed(content)
                    if visible:
                        text_parts.append(visible)
                tool_calls_raw = message.get("tool_calls") or ()
                if not isinstance(tool_calls_raw, Sequence) or isinstance(tool_calls_raw, str):
                    raise ModelTransportError("UPSTREAM_TOOL_CALLS_INVALID")
                semantic_size += len(
                    json.dumps(tool_calls_raw, ensure_ascii=False).encode("utf-8")
                ) if tool_calls_raw else 0
                if semantic_size > self.response_body_limit:
                    raise ModelTransportError("UPSTREAM_RESPONSE_TOO_LARGE")
                tool_calls.extend(
                    MappingProxyType(dict(item))
                    for item in tool_calls_raw
                    if isinstance(item, Mapping)
                )
                finish_reason = str(payload.get("done_reason") or finish_reason)
            if not saw_event:
                raise ModelTransportError("UPSTREAM_RESPONSE_INVALID")
            return InferenceResponse(
                text="".join(text_parts),
                tool_calls=tuple(tool_calls),
                finish_reason=finish_reason,
                usage=MappingProxyType(
                    {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    }
                ),
                model_id=model_id,
            )
        finally:
            await response.aclose()

    @staticmethod
    def _fold_system_into_user(body: Mapping[str, Any]) -> dict[str, Any]:
        updated = dict(body)
        messages = [dict(item) for item in body.get("messages", ()) if isinstance(item, Mapping)]
        system_text = "\n\n".join(
            str(item.get("content") or "")
            for item in messages
            if item.get("role") == "system"
        ).strip()
        conversation = [item for item in messages if item.get("role") != "system"]
        if system_text:
            for item in conversation:
                if item.get("role") == "user" and isinstance(item.get("content"), str):
                    item["content"] = f"{system_text}\n\n{item['content']}"
                    break
            else:
                conversation.insert(0, {"role": "user", "content": system_text})
        updated["messages"] = conversation
        return updated

    async def _open(
        self,
        connection: ResolvedModelConnection,
        *,
        url: str,
        body: Mapping[str, Any],
        method: str = "POST",
        timeout: float | None = None,
    ) -> httpx.Response:
        reservation = self._reserve_cloud(connection, body) if url.endswith("/chat/completions") else 0
        request = self.client.build_request(
            method,
            url,
            headers=self._headers(connection),
            **({"json": dict(body)} if method == "POST" else {}),
            timeout=self.timeout if timeout is None else min(self.timeout, timeout),
        )
        try:
            response = await self.client.send(request, stream=True, follow_redirects=False)
        except (httpx.HTTPError, OSError) as exc:
            raise ModelTransportError(f"UPSTREAM_REQUEST_FAILED: {type(exc).__name__}") from exc
        response.extensions["les_cloud_reservation"] = reservation
        if 300 <= response.status_code < 400:
            await response.aclose()
            raise ModelTransportError("UPSTREAM_REDIRECT_REJECTED")
        try:
            self.peer_verifier(response, connection.endpoint)
        except (ValueError, OSError) as exc:
            await response.aclose()
            raise ModelTransportError(str(exc)) from exc
        return response

    async def _token_count_model_identity(self, connection: ResolvedModelConnection) -> str:
        """The count route uses the loaded state, not an arbitrary request model."""
        response = await self._open(
            connection, url=join_openai_path(connection.endpoint, "/models"), body={}, method="GET",
            timeout=TOKEN_COUNT_TIMEOUT_SECONDS,
        )
        try:
            raw = await self._read_bounded(response)
            if response.status_code != 200:
                raise ModelTransportError("TOKEN_COUNT_MODEL_METADATA_UNAVAILABLE")
            try:
                payload = json.loads(raw)
                if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list) or len(payload["data"]) != 1:
                    raise ModelTransportError("TOKEN_COUNT_MODEL_METADATA_INVALID")
                models = payload["data"]
                model = models[0]
                if not isinstance(model, Mapping):
                    raise ModelTransportError("TOKEN_COUNT_MODEL_METADATA_INVALID")
                if (model.get("id") != connection.model_id
                        or model.get("owned_by") != TOKEN_COUNT_PROVIDER_OWNER
                        or not isinstance(model.get("root"), str) or not model["root"]):
                    raise ModelTransportError("TOKEN_COUNT_MODEL_IDENTITY_MISMATCH")
                return wire_sha256({key: model.get(key) for key in ("id", "root", "created", "owned_by")})
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ModelTransportError("TOKEN_COUNT_MODEL_METADATA_INVALID") from exc
        finally:
            await response.aclose()

    async def count_input_tokens(
        self, connection: ResolvedModelConnection, request: InferenceRequest,
    ) -> InputTokenCount | None:
        """Count the exact supported local wire without generation or model fallback.

        A missing/failed/unsupported counter leaves the conservative governor
        intact. It cannot authorize a larger context or change model evidence.
        """
        self._token_count_last_attempt = {
            "status": "fallback", "source": "conservative_estimator",
            "model_id": connection.model_id, "connection_revision_id": connection.revision_id,
            "request_timeout_seconds": min(self.timeout, TOKEN_COUNT_TIMEOUT_SECONDS),
            "operation_deadline_seconds": min(self.timeout, TOKEN_COUNT_TIMEOUT_SECONDS),
        }
        if not supports_model_token_count(connection.extension_type, connection.locality, connection.endpoint.locality):
            self._token_count_last_attempt["reason"] = "local_token_counter_required"
            return None
        if connection.capability_snapshot.transport_options.get("chat_protocol") == "native_chat_v1":
            self._token_count_last_attempt["reason"] = "openai_chat_protocol_required"
            return None
        try:
            body = self._chat_body(connection, request, stream=False)
            payload = model_token_count_payload(body)
            count, identity_before = await asyncio.wait_for(
                self._count_bound_input_payload(connection, payload),
                timeout=min(self.timeout, TOKEN_COUNT_TIMEOUT_SECONDS),
            )
            result = InputTokenCount(count, TOKEN_COUNT_SOURCE, connection.model_id,
                                     connection.revision_id, wire_sha256(body), identity_before)
            self._token_count_last_attempt = {"status": "counted", **vars(result),
                                              "request_timeout_seconds": min(self.timeout, TOKEN_COUNT_TIMEOUT_SECONDS),
                                              "operation_deadline_seconds": min(self.timeout, TOKEN_COUNT_TIMEOUT_SECONDS)}
            return result
        except UnsupportedTokenCountWire as exc:
            self._token_count_last_attempt["reason"] = str(exc)
        except ModelTransportError as exc:
            # Only stable diagnostic codes leave transport, never upstream bodies.
            code = str(exc).partition(":")[0]
            self._token_count_last_attempt["reason"] = (code if code.isascii() and code.isupper()
                                                       and code.replace("_", "").isalnum() and len(code) < 100
                                                       else "token_count_transport_error")
        except (TypeError, ValueError):
            self._token_count_last_attempt["reason"] = "invalid_count_wire"
        except TimeoutError:
            self._token_count_last_attempt["reason"] = "TOKEN_COUNT_DEADLINE"
        return None

    async def _count_bound_input_payload(
        self, connection: ResolvedModelConnection, payload: Mapping[str, Any],
    ) -> tuple[int, str]:
        identity_before = await self._token_count_model_identity(connection)
        response = await self._open(
            connection, url=join_openai_path(connection.endpoint, "/messages/count_tokens"), body=payload,
            timeout=TOKEN_COUNT_TIMEOUT_SECONDS,
        )
        try:
            raw = await self._read_bounded(response)
            if response.status_code != 200:
                raise ModelTransportError("TOKEN_COUNT_ENDPOINT_UNAVAILABLE")
            try:
                count = json.loads(raw).get("input_tokens")
            except (AttributeError, ValueError) as exc:
                raise ModelTransportError("TOKEN_COUNT_RESPONSE_INVALID") from exc
            if type(count) is not int or count <= 0:
                raise ModelTransportError("TOKEN_COUNT_RESPONSE_INVALID")
        finally:
            await response.aclose()
        if await self._token_count_model_identity(connection) != identity_before:
            raise ModelTransportError("TOKEN_COUNT_MODEL_CHANGED")
        return count, identity_before

    async def _read_bounded(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > self.response_body_limit:
                raise ModelTransportError("UPSTREAM_RESPONSE_TOO_LARGE")
            chunks.append(chunk)
        return b"".join(chunks)

    async def complete(
        self,
        connection: ResolvedModelConnection,
        request: InferenceRequest,
    ) -> InferenceResponse:
        self._require(connection, CapabilityName.CHAT_COMPLETIONS)
        if (
            connection.capability_snapshot.transport_options.get("chat_protocol")
            == "native_chat_v1"
        ):
            return await self._complete_native_chat(connection, request)
        body = self._chat_body(connection, request, stream=False)
        response = await self._open(
            connection,
            url=join_openai_path(connection.endpoint, "/chat/completions"),
            body=body,
        )
        try:
            raw = await self._read_bounded(response)
            if (
                response.status_code == 502
                and b"System message must be at the beginning" in raw
                and any(item.get("role") == "system" for item in body.get("messages", ()))
            ):
                await response.aclose()
                response = await self._open(
                    connection,
                    url=join_openai_path(connection.endpoint, "/chat/completions"),
                    body=self._fold_system_into_user(body),
                )
                raw = await self._read_bounded(response)
            if not 200 <= response.status_code < 300:
                raise ModelTransportError(f"UPSTREAM_HTTP_ERROR: {response.status_code}")
            try:
                payload = json.loads(raw)
                choice = payload["choices"][0]
                message = choice["message"]
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise ModelTransportError("UPSTREAM_RESPONSE_INVALID") from exc
            tool_calls_raw = message.get("tool_calls") or ()
            if not isinstance(tool_calls_raw, Sequence) or isinstance(tool_calls_raw, str):
                raise ModelTransportError("UPSTREAM_TOOL_CALLS_INVALID")
            tool_calls = tuple(
                MappingProxyType(dict(item)) for item in tool_calls_raw if isinstance(item, Mapping)
            )
            self._settle_cloud(response, payload.get("usage"))
            reasoning_content = message.get("reasoning_content")
            if reasoning_content is not None and not isinstance(reasoning_content, str):
                raise ModelTransportError("UPSTREAM_REASONING_CONTENT_INVALID")
            return InferenceResponse(
                text=_message_text(message),
                tool_calls=tool_calls,
                finish_reason=str(choice.get("finish_reason") or ""),
                usage=_usage(payload.get("usage")),
                model_id=str(payload.get("model") or ""),
                reasoning_content=reasoning_content,
            )
        finally:
            await response.aclose()

    async def stream(
        self,
        connection: ResolvedModelConnection,
        request: InferenceRequest,
    ) -> AsyncIterator[InferenceEvent]:
        self._require(connection, CapabilityName.CHAT_COMPLETIONS)
        self._require(connection, CapabilityName.STREAMING)
        response = await self._open(
            connection,
            url=join_openai_path(connection.endpoint, "/chat/completions"),
            body=self._chat_body(connection, request, stream=True),
        )
        consumed = 0
        finished = False
        observed_model_id = ""
        final_filter = FinalTextFilter()
        try:
            if not 200 <= response.status_code < 300:
                await self._read_bounded(response)
                raise ModelTransportError(f"UPSTREAM_HTTP_ERROR: {response.status_code}")
            async for line in response.aiter_lines():
                consumed += len(line.encode("utf-8")) + 1
                if consumed > self.response_body_limit:
                    raise ModelTransportError("UPSTREAM_RESPONSE_TOO_LARGE")
                if not line.startswith("data:"):
                    continue
                raw = line.removeprefix("data:").strip()
                if raw == "[DONE]":
                    if not finished:
                        yield InferenceEvent(kind="finish", model_id=observed_model_id)
                    break
                try:
                    payload = json.loads(raw)
                    choice = payload["choices"][0]
                    delta = choice.get("delta") or {}
                except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                    raise ModelTransportError("UPSTREAM_STREAM_EVENT_INVALID") from exc
                observed_model_id = str(payload.get("model") or observed_model_id)
                text = final_filter.feed(assistant_delta_text(delta))
                if text:
                    yield InferenceEvent(
                        kind="text_delta",
                        text=text,
                        model_id=observed_model_id,
                    )
                tool_calls_raw = delta.get("tool_calls") or ()
                if tool_calls_raw:
                    if not isinstance(tool_calls_raw, Sequence) or isinstance(tool_calls_raw, str):
                        raise ModelTransportError("UPSTREAM_TOOL_CALLS_INVALID")
                    yield InferenceEvent(
                        kind="tool_delta",
                        tool_calls=tuple(
                            MappingProxyType(dict(item))
                            for item in tool_calls_raw
                            if isinstance(item, Mapping)
                        ),
                        model_id=observed_model_id,
                    )
                finish_reason = str(choice.get("finish_reason") or "")
                if finish_reason:
                    finished = True
                    yield InferenceEvent(
                        kind="finish",
                        finish_reason=finish_reason,
                        model_id=observed_model_id,
                    )
        finally:
            await response.aclose()

    async def embed(
        self,
        connection: ResolvedModelConnection,
        inputs: Sequence[str],
    ) -> EmbeddingResponse:
        self._require(connection, CapabilityName.EMBEDDINGS)
        normalized_inputs = tuple(str(item) for item in inputs)
        if not normalized_inputs:
            raise ValueError("inputs must not be empty")
        response = await self._open(
            connection,
            url=join_openai_path(connection.endpoint, "/embeddings"),
            body={"model": connection.model_id, "input": list(normalized_inputs)},
        )
        try:
            raw = await self._read_bounded(response)
            if not 200 <= response.status_code < 300:
                raise ModelTransportError(f"UPSTREAM_HTTP_ERROR: {response.status_code}")
            try:
                payload = json.loads(raw)
                rows = sorted(payload["data"], key=lambda item: int(item["index"]))
                vectors = tuple(
                    tuple(float(value) for value in item["embedding"]) for item in rows
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ModelTransportError("UPSTREAM_EMBEDDING_RESPONSE_INVALID") from exc
            if len(vectors) != len(normalized_inputs):
                raise ModelTransportError("UPSTREAM_EMBEDDING_COUNT_MISMATCH")
            return EmbeddingResponse(
                vectors=vectors,
                model_id=str(payload.get("model") or connection.model_id),
                usage=_usage(payload.get("usage")),
            )
        finally:
            await response.aclose()
