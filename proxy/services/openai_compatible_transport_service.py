"""Provider-neutral HTTP transport for resolved model connections."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Any, Callable

import httpx

from proxy.services.llm_transport_profile_service import assistant_delta_text
from proxy.services.model_connection_contracts import CapabilityName, CapabilityState
from proxy.services.model_connection_resolver_service import ResolvedModelConnection
from proxy.services.model_connection_security_service import (
    ValidatedEndpoint,
    join_openai_path,
    validate_connected_peer,
)
from proxy.services.model_secret_service import EnvironmentSecretStore, ModelSecretError


class ModelTransportError(RuntimeError):
    """The exact resolved connection could not complete a safe request."""


PeerVerifier = Callable[[httpx.Response, ValidatedEndpoint], None]


@dataclass(frozen=True)
class InferenceRequest:
    messages: Sequence[Mapping[str, Any]]
    max_output_tokens: int
    temperature: float | None = None
    tools: Sequence[Mapping[str, Any]] = ()
    response_format: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
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
    content = message.get("content")
    if isinstance(content, str) and content:
        return content
    return assistant_delta_text(message)


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
        return connection.capability_snapshot.transport_options.get(
            "max_output_field", "max_tokens"
        )

    def _chat_body(
        self,
        connection: ResolvedModelConnection,
        request: InferenceRequest,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": connection.model_id,
            "messages": [dict(item) for item in request.messages],
            self._output_field(connection): request.max_output_tokens,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.tools:
            self._require(connection, CapabilityName.TOOLS)
            body["tools"] = [dict(item) for item in request.tools]
        if request.response_format is not None:
            self._require(connection, CapabilityName.STRUCTURED_OUTPUT)
            body["response_format"] = dict(request.response_format)
        if stream:
            body["stream"] = True
        return body

    async def _open(
        self,
        connection: ResolvedModelConnection,
        *,
        url: str,
        body: Mapping[str, Any],
    ) -> httpx.Response:
        request = self.client.build_request(
            "POST",
            url,
            headers=self._headers(connection),
            json=dict(body),
            timeout=self.timeout,
        )
        try:
            response = await self.client.send(request, stream=True, follow_redirects=False)
        except (httpx.HTTPError, OSError) as exc:
            raise ModelTransportError(f"UPSTREAM_REQUEST_FAILED: {type(exc).__name__}") from exc
        if 300 <= response.status_code < 400:
            await response.aclose()
            raise ModelTransportError("UPSTREAM_REDIRECT_REJECTED")
        try:
            self.peer_verifier(response, connection.endpoint)
        except (ValueError, OSError) as exc:
            await response.aclose()
            raise ModelTransportError(str(exc)) from exc
        return response

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
        response = await self._open(
            connection,
            url=join_openai_path(connection.endpoint, "/chat/completions"),
            body=self._chat_body(connection, request, stream=False),
        )
        try:
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
            return InferenceResponse(
                text=_message_text(message),
                tool_calls=tool_calls,
                finish_reason=str(choice.get("finish_reason") or ""),
                usage=_usage(payload.get("usage")),
                model_id=str(payload.get("model") or ""),
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
                text = assistant_delta_text(delta)
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
