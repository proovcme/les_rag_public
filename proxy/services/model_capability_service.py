"""Bounded capability probes for OpenAI-compatible model connections."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json
from typing import Callable, Iterable, Mapping
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import httpx

from proxy.services.model_connection_contracts import (
    CapabilityName,
    CapabilityObservation,
    CapabilitySnapshot,
    CapabilityState,
    ModelConnectionRevision,
)
from proxy.services.model_connection_registry_service import ModelConnectionRegistry
from proxy.services.model_connection_security_service import (
    AddressResolver,
    ValidatedEndpoint,
    join_openai_path,
    system_resolver,
    validate_connected_peer,
    validate_endpoint,
)
from proxy.services.model_secret_service import EnvironmentSecretStore
from extensions.lemonade.transport import lemonade_transport_options


class CapabilityProbeError(RuntimeError):
    """The bounded probe could not be performed safely."""


class CapabilityRequirementError(RuntimeError):
    """A required capability is absent, stale or weakly evidenced."""


PeerVerifier = Callable[[httpx.Response, ValidatedEndpoint], None]
Clock = Callable[[], datetime]
_OLLAMA_SHOW_BODY_LIMIT = 262_144


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _probe_request(
    capability: CapabilityName,
    connection: ModelConnectionRevision,
    endpoint: ValidatedEndpoint,
) -> tuple[str, str, Mapping[str, object] | None]:
    model = connection.model_id
    chat_body: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": "capability probe"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    if capability is CapabilityName.MODELS:
        return "GET", join_openai_path(endpoint, "/models"), None
    if capability is CapabilityName.CHAT_COMPLETIONS:
        return "POST", join_openai_path(endpoint, "/chat/completions"), chat_body
    if capability is CapabilityName.STREAMING:
        return "POST", join_openai_path(endpoint, "/chat/completions"), {
            **chat_body,
            "stream": True,
        }
    if capability is CapabilityName.TOOLS:
        return "POST", join_openai_path(endpoint, "/chat/completions"), {
            **chat_body,
            "messages": [{"role": "user", "content": "Call les_capability_probe once with empty arguments {}."}],
            "max_tokens": 256,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "les_capability_probe",
                        "description": "Return probe status",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    },
                }
            ],
        }
    if capability is CapabilityName.STRUCTURED_OUTPUT:
        return "POST", join_openai_path(endpoint, "/chat/completions"), {
            **chat_body,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "les_capability_probe",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                        "additionalProperties": False,
                    },
                },
            },
        }
    if capability is CapabilityName.RESPONSES:
        return "POST", join_openai_path(endpoint, "/responses"), {
            "model": model,
            "input": "capability probe",
            "max_output_tokens": 1,
        }
    if capability is CapabilityName.EMBEDDINGS:
        return "POST", join_openai_path(endpoint, "/embeddings"), {
            "model": model,
            "input": ["capability probe"],
        }
    if capability is CapabilityName.TOKEN_COUNT:
        return "POST", join_openai_path(endpoint, "/messages/count_tokens"), {
            "model": model,
            "messages": [{"role": "user", "content": "capability probe"}],
        }
    if capability is CapabilityName.RERANK:
        return "POST", join_openai_path(endpoint, "/rerank"), {
            "model": model,
            "query": "capability probe",
            "documents": ["capability probe"],
        }
    raise CapabilityProbeError(f"CAPABILITY_PROBE_UNSUPPORTED: {capability.value}")


def _state_for_status(status_code: int) -> CapabilityState:
    if 200 <= status_code < 300:
        return CapabilityState.SUPPORTED
    if status_code in {404, 405, 501}:
        return CapabilityState.UNSUPPORTED
    return CapabilityState.UNKNOWN


def _native_api_url(endpoint: ValidatedEndpoint, operation: str) -> str:
    parsed = urlsplit(endpoint.canonical_base_url)
    path = parsed.path.rstrip("/")
    for suffix in ("/api/v1", "/v1"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit(
        (parsed.scheme, parsed.netloc, f"{path}/api/{operation.lstrip('/')}", "", "")
    )


def _native_chat_url(endpoint: ValidatedEndpoint) -> str:
    return _native_api_url(endpoint, "chat")


def _observed_context_tokens(payload: object) -> int | None:
    """Read Ollama's generic model context value without model-specific keys."""

    if not isinstance(payload, Mapping):
        return None
    model_info = payload.get("model_info")
    if not isinstance(model_info, Mapping):
        return None
    candidates: list[int] = []
    for key, value in model_info.items():
        if not str(key).casefold().endswith(".context_length"):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            candidates.append(parsed)
    return max(candidates) if candidates else None


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _lemonade_model_transport_options(
    payload: object,
    *,
    model_id: str,
) -> dict[str, str]:
    """Project safe transport facts for the exact model returned by Lemonade."""
    if not isinstance(payload, Mapping):
        return {}
    records = payload.get("data")
    if not isinstance(records, list):
        return {}
    expected = str(model_id or "").strip().casefold().removesuffix(":latest")
    record = next(
        (
            item
            for item in records
            if isinstance(item, Mapping)
            and str(item.get("id") or "").strip().casefold().removesuffix(":latest")
            == expected
        ),
        None,
    )
    if record is None:
        return {}

    result: dict[str, str] = {}
    recipe = str(record.get("recipe") or "").strip().casefold()
    if recipe in {"llamacpp", "llama_cpp"}:
        result["observed_backend"] = "llama_cpp"
    elif recipe == "flm":
        result["observed_backend"] = "flm"

    recipe_options = record.get("recipe_options")
    configured_context = (
        _positive_int(recipe_options.get("ctx_size"))
        if isinstance(recipe_options, Mapping)
        else None
    )
    # The catalogue maximum describes the model architecture, not this process.
    # IQ3 advertised 262144 while Lemonade actually resolved a 4096-token window.
    if configured_context is not None:
        result["observed_context_tokens"] = str(configured_context)
        result["observed_context_source"] = "lemonade_models.recipe_options.ctx_size"
    return result


class CapabilityProbe:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        secret_store: EnvironmentSecretStore | None = None,
        resolver: AddressResolver = system_resolver,
        peer_verifier: PeerVerifier = validate_connected_peer,
        clock: Clock = _utc_now,
        freshness: timedelta = timedelta(hours=24),
        response_body_limit: int = 32_768,
        allow_private_http: bool = False,
    ):
        if freshness.total_seconds() <= 0:
            raise ValueError("freshness must be positive")
        if response_body_limit < 1:
            raise ValueError("response_body_limit must be positive")
        self.client = client
        self.secret_store = secret_store
        self.resolver = resolver
        self.peer_verifier = peer_verifier
        self.clock = clock
        self.freshness = freshness
        self.response_body_limit = response_body_limit
        self.allow_private_http = allow_private_http

    async def probe(
        self,
        connection: ModelConnectionRevision,
        *,
        requested: Iterable[CapabilityName],
    ) -> CapabilitySnapshot:
        requested_set = frozenset(CapabilityName(item) for item in requested)
        if not requested_set:
            raise CapabilityProbeError("CAPABILITY_REQUEST_EMPTY")
        if not connection.enabled:
            raise CapabilityProbeError("CONNECTION_DISABLED")
        endpoint = validate_endpoint(
            connection.base_url,
            connection.locality,
            resolver=self.resolver,
            allow_private_http=self.allow_private_http,
        )
        headers: dict[str, str] = {}
        if connection.secret_ref:
            if self.secret_store is None:
                raise CapabilityProbeError("SECRET_RESOLVER_REQUIRED")
            secret = self.secret_store.resolve(connection.secret_ref)
            if secret is not None:
                headers["Authorization"] = f"Bearer {secret.reveal()}"

        observed_at = self.clock()
        observations: list[CapabilityObservation] = []
        models_payload: object = None
        is_lemonade = str(connection.extension_type or "").strip().casefold() == "lemonade"
        capabilities = list(CapabilityName)
        if is_lemonade:
            # Backend/context evidence is a prerequisite for safe chat probing,
            # not an optional checkbox callers must remember to select.
            requested_set = requested_set | {CapabilityName.MODELS}
            capabilities = [CapabilityName.MODELS, *[item for item in capabilities if item is not CapabilityName.MODELS]]
        for capability in capabilities:
            if capability not in requested_set:
                observations.append(
                    CapabilityObservation(
                        capability=capability,
                        state=CapabilityState.UNKNOWN,
                        evidence_source="unavailable",
                        observed_at=observed_at,
                        detail="not_requested",
                    )
                )
                continue
            method, url, body = _probe_request(capability, connection, endpoint)
            if is_lemonade and body is not None and url.endswith("/chat/completions"):
                observed = _lemonade_model_transport_options(models_payload, model_id=connection.model_id)
                body = lemonade_transport_options(
                    body, provider="lemonade", model_id=connection.model_id,
                    backend=observed.get("observed_backend"),
                )
            try:
                async with self.client.stream(
                    method,
                    url,
                    headers=headers,
                    json=body,
                    follow_redirects=False,
                ) as response:
                    if 300 <= response.status_code < 400:
                        state = CapabilityState.UNKNOWN
                        detail = "redirect_rejected"
                    else:
                        # The connected peer is observable only while the socket is
                        # still open. A completed SSE response may release that
                        # metadata, so validate it before consuming the body.
                        self.peer_verifier(response, endpoint)
                        response_size = 0
                        too_large = False
                        response_chunks: list[bytes] = []
                        async for chunk in response.aiter_bytes():
                            response_size += len(chunk)
                            if response_size > self.response_body_limit:
                                too_large = True
                                break
                            if capability is CapabilityName.TOOLS or (is_lemonade and capability is CapabilityName.MODELS):
                                response_chunks.append(chunk)
                        if too_large:
                            state = CapabilityState.UNKNOWN
                            detail = "response_too_large"
                        else:
                            state = _state_for_status(response.status_code)
                            detail = f"http_{response.status_code}"
                            if capability is CapabilityName.TOOLS:
                                state, detail = _tools_probe_outcome(response.status_code, b"".join(response_chunks))
                            if (
                                is_lemonade
                                and capability is CapabilityName.MODELS
                                and state is CapabilityState.SUPPORTED
                                and response_chunks
                            ):
                                try:
                                    models_payload = json.loads(b"".join(response_chunks))
                                except (TypeError, ValueError, json.JSONDecodeError):
                                    models_payload = None
            except (httpx.HTTPError, OSError, ValueError) as exc:
                state = CapabilityState.UNKNOWN
                detail = f"request_error:{type(exc).__name__}"
            observations.append(
                CapabilityObservation(
                    capability=capability,
                    state=state,
                    evidence_source="probe",
                    observed_at=observed_at,
                    detail=detail,
                )
            )

        transport_options = {"max_output_field": "max_tokens"}
        if is_lemonade:
            transport_options.update(
                _lemonade_model_transport_options(
                    models_payload,
                    model_id=connection.model_id,
                )
            )
            # Same configured origin and peer checks; never follow a backend URL
            # supplied by the catalogue. Options resolve defaults such as ctx=-1.
            url = join_openai_path(endpoint, f"/models/{quote(connection.model_id, safe='')}/options")
            try:
                async with self.client.stream("GET", url, headers=headers, follow_redirects=False) as response:
                    self.peer_verifier(response, endpoint)
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.response_body_limit:
                            chunks = []
                            break
                        chunks.append(chunk)
                    if response.status_code == 200 and chunks:
                        options = json.loads(b"".join(chunks))
                        if isinstance(options, Mapping) and options.get("model_name") == connection.model_id:
                            resolved_context = _positive_int(options.get("resolved_ctx_size"))
                            if resolved_context is not None:
                                transport_options["observed_context_tokens"] = str(resolved_context)
                                transport_options["observed_context_source"] = "lemonade_model_options.resolved_ctx_size"
            except (httpx.HTTPError, OSError, ValueError):
                # Older providers may lack options. Retain explicit configured
                # capacity if supplied; never substitute the catalogue maximum.
                pass
        chat_observation = next(
            (
                item
                for item in observations
                if item.capability is CapabilityName.CHAT_COMPLETIONS
            ),
            None,
        )
        if (
            str(connection.extension_type or "").strip().casefold() == "ollama"
            and CapabilityName.CHAT_COMPLETIONS in requested_set
            and chat_observation is not None
            and chat_observation.state is CapabilityState.SUPPORTED
        ):
            native_body = {
                "model": connection.model_id,
                "messages": [{"role": "user", "content": "capability probe"}],
                "think": False,
                "stream": False,
                "options": {"num_predict": 1, "temperature": 0},
            }
            try:
                async with self.client.stream(
                    "POST",
                    _native_chat_url(endpoint),
                    headers=headers,
                    json=native_body,
                    follow_redirects=False,
                ) as response:
                    self.peer_verifier(response, endpoint)
                    response_size = 0
                    async for chunk in response.aiter_bytes():
                        response_size += len(chunk)
                        if response_size > self.response_body_limit:
                            break
                    if 200 <= response.status_code < 300 and response_size <= self.response_body_limit:
                        transport_options["chat_protocol"] = "native_chat_v1"
            except (httpx.HTTPError, OSError, ValueError):
                pass

            if transport_options.get("chat_protocol") == "native_chat_v1":
                try:
                    async with self.client.stream(
                        "POST",
                        _native_api_url(endpoint, "show"),
                        headers=headers,
                        json={"model": connection.model_id},
                        follow_redirects=False,
                    ) as response:
                        self.peer_verifier(response, endpoint)
                        show_chunks: list[bytes] = []
                        show_size = 0
                        async for chunk in response.aiter_bytes():
                            show_size += len(chunk)
                            if show_size > _OLLAMA_SHOW_BODY_LIMIT:
                                show_chunks = []
                                break
                            show_chunks.append(chunk)
                        show_payload = (
                            httpx.Response(
                                status_code=response.status_code,
                                content=b"".join(show_chunks),
                            ).json()
                            if 200 <= response.status_code < 300 and show_chunks
                            else None
                        )
                        observed_context = _observed_context_tokens(show_payload)
                        if observed_context is not None:
                            transport_options["observed_context_tokens"] = str(
                                observed_context
                            )
                except (httpx.HTTPError, OSError, TypeError, ValueError):
                    pass

        return CapabilitySnapshot(
            snapshot_id=f"cap:{uuid4().hex}",
            connection_revision_id=connection.revision_id,
            observations=tuple(observations),
            observed_at=observed_at,
            expires_at=observed_at + self.freshness,
            transport_options=transport_options,
        )

    async def probe_and_store(
        self,
        connection: ModelConnectionRevision,
        *,
        requested: Iterable[CapabilityName],
        registry: ModelConnectionRegistry,
        actor: str,
    ) -> CapabilitySnapshot:
        snapshot = await self.probe(connection, requested=requested)
        registry.save_capability_snapshot(snapshot, actor=actor)
        return snapshot


def capability_diagnostic_observation(observation: CapabilityObservation) -> CapabilityObservation:
    """Project legacy HTTP acceptance honestly without rewriting stored evidence."""
    if observation.capability is CapabilityName.TOOLS and observation.state is CapabilityState.SUPPORTED:
        if (observation.evidence_source == "probe" and len(observation.detail) == 8
                and observation.detail.startswith("http_2") and observation.detail[5:].isdigit()):
            return replace(observation, state=CapabilityState.UNKNOWN, detail="legacy_http_accepted_no_native_proof")
        if observation.evidence_source in {"template_default", "operator_declaration"}:
            return replace(observation, state=CapabilityState.UNKNOWN, detail="advertised_tools_unverified")
    return observation


def _tools_probe_outcome(status: int, body: bytes) -> tuple[CapabilityState, str]:
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return CapabilityState.UNKNOWN, "invalid_json"
    if not 200 <= status < 300:
        error = payload.get("error") if isinstance(payload, Mapping) else None
        if (status in {400, 422} and isinstance(error, Mapping) and error.get("param") == "tools"
                and error.get("code") in {"tools_not_supported", "unsupported_tools"}):
            return CapabilityState.UNSUPPORTED, "explicit_tools_refusal"
        return CapabilityState.UNKNOWN, f"http_{status}_tools_unverified"
    choices = payload.get("choices") if isinstance(payload, Mapping) else None
    if not isinstance(choices, list) or not choices:
        return CapabilityState.UNKNOWN, "invalid_tool_response"
    calls = []
    for choice in choices:
        if not isinstance(choice, Mapping):
            return CapabilityState.UNKNOWN, "invalid_tool_response"
        if choice.get("finish_reason") == "length":
            return CapabilityState.UNKNOWN, "response_truncated"
        message = choice.get("message")
        if not isinstance(message, Mapping):
            return CapabilityState.UNKNOWN, "invalid_tool_response"
        native = message.get("tool_calls") or []
        if not isinstance(native, list):
            return CapabilityState.UNKNOWN, "invalid_tool_call"
        calls.extend(native)
    if not calls:
        return CapabilityState.UNKNOWN, "http_accepted_no_tool_call"
    for call in calls:
        if (not isinstance(call, Mapping) or call.get("type") != "function"
                or not isinstance(call.get("id"), str) or not call["id"].strip()):
            return CapabilityState.UNKNOWN, "invalid_tool_call"
        function = call.get("function")
        if not isinstance(function, Mapping) or function.get("name") != "les_capability_probe":
            return CapabilityState.UNKNOWN, "invalid_tool_call"
        try:
            arguments = json.loads(function.get("arguments"))
        except (ValueError, TypeError):
            return CapabilityState.UNKNOWN, "invalid_tool_call"
        if arguments != {}:
            return CapabilityState.UNKNOWN, "invalid_tool_call"
    return CapabilityState.SUPPORTED, "native_tool_call_observed"


def require_capabilities(
    snapshot: CapabilitySnapshot,
    required: Iterable[CapabilityName],
    *,
    now: datetime | None = None,
) -> None:
    checked_at = now or _utc_now()
    if checked_at >= snapshot.expires_at:
        raise CapabilityRequirementError("CAPABILITY_SNAPSHOT_STALE")
    for capability in frozenset(CapabilityName(item) for item in required):
        observation = snapshot.observation(capability)
        if observation.state is not CapabilityState.SUPPORTED:
            raise CapabilityRequirementError(f"CAPABILITY_REQUIRED: {capability.value}")
        if observation.evidence_source in {"template_default", "unavailable"}:
            raise CapabilityRequirementError(
                f"CAPABILITY_EVIDENCE_INSUFFICIENT: {capability.value}"
            )
        if capability_diagnostic_observation(observation).state is not CapabilityState.SUPPORTED:
            raise CapabilityRequirementError(f"CAPABILITY_REQUIRED: {capability.value}")
