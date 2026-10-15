"""Bounded capability probes for OpenAI-compatible model connections."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit
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
        **connection.chat_options.parameters(
            max_output_tokens=1, temperature=0, reasoning_enabled=False,
            include_reasoning=str(connection.extension_type or "").strip().casefold() != "freetoken",
        ),
    }
    if str(connection.extension_type or "").strip().casefold() == "freetoken":
        chat_body["chat_template_kwargs"] = {"enable_thinking": False}
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


def _positive_context_tokens(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _observed_freetoken_kv(payload: object) -> int | None:
    """Read FreeToken physical KV pages without retaining model text."""

    if not isinstance(payload, Mapping):
        return None
    geometry = payload.get("geometry")
    sources = []
    if isinstance(geometry, Mapping):
        sources.append(geometry.get("num_pages"))
    sources.append(payload.get("num_pages"))
    for candidate in sources:
        parsed = _positive_context_tokens(candidate)
        if parsed is not None:
            return parsed
    return None


def _observed_openai_model_context(payload: object, model_id: str) -> int | None:
    """Read a generic OpenAI-compatible context_length for one model id."""

    if not isinstance(payload, Mapping):
        return None
    rows = payload.get("data")
    if not isinstance(rows, list):
        return None
    wanted = str(model_id or "").strip()
    fallback = None
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        parsed = _positive_context_tokens(
            row.get("context_length", row.get("max_model_len"))
        )
        if parsed is None:
            continue
        if str(row.get("id") or "").strip() == wanted:
            return parsed
        if fallback is None:
            fallback = parsed
    return fallback


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
        for capability in CapabilityName:
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
                        async for chunk in response.aiter_bytes():
                            response_size += len(chunk)
                            if response_size > self.response_body_limit:
                                too_large = True
                                break
                        if too_large:
                            state = CapabilityState.UNKNOWN
                            detail = "response_too_large"
                        else:
                            state = _state_for_status(response.status_code)
                            detail = f"http_{response.status_code}"
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

        transport_options = {"max_output_field": connection.chat_options.output_field()}
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
                "options": {"num_predict": 1, **connection.chat_options.sampling_parameters(), **({"temperature": 0}
                            if connection.chat_options.temperature_mode == "profile" else {})},
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

        if str(connection.extension_type or "").strip().casefold() == "freetoken":
            observed_context = None
            try:
                async with self.client.stream(
                    "GET",
                    join_openai_path(endpoint, "/cache/status"),
                    headers=headers,
                    follow_redirects=False,
                ) as response:
                    self.peer_verifier(response, endpoint)
                    cache_chunks: list[bytes] = []
                    cache_size = 0
                    async for chunk in response.aiter_bytes():
                        cache_size += len(chunk)
                        if cache_size > self.response_body_limit:
                            cache_chunks = []
                            break
                        cache_chunks.append(chunk)
                    cache_payload = (
                        httpx.Response(
                            status_code=response.status_code,
                            content=b"".join(cache_chunks),
                        ).json()
                        if 200 <= response.status_code < 300 and cache_chunks
                        else None
                    )
                    observed_context = _observed_freetoken_kv(cache_payload)
            except (httpx.HTTPError, OSError, TypeError, ValueError):
                observed_context = None
            if observed_context is None:
                try:
                    async with self.client.stream(
                        "GET",
                        join_openai_path(endpoint, "/models"),
                        headers=headers,
                        follow_redirects=False,
                    ) as response:
                        self.peer_verifier(response, endpoint)
                        model_chunks: list[bytes] = []
                        model_size = 0
                        async for chunk in response.aiter_bytes():
                            model_size += len(chunk)
                            if model_size > self.response_body_limit:
                                model_chunks = []
                                break
                            model_chunks.append(chunk)
                        models_payload = (
                            httpx.Response(
                                status_code=response.status_code,
                                content=b"".join(model_chunks),
                            ).json()
                            if 200 <= response.status_code < 300 and model_chunks
                            else None
                        )
                        observed_context = _observed_openai_model_context(
                            models_payload,
                            connection.model_id,
                        )
                except (httpx.HTTPError, OSError, TypeError, ValueError):
                    observed_context = None
            if observed_context is not None:
                transport_options["observed_context_tokens"] = str(observed_context)

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
        requested_set = {CapabilityName(item) for item in requested}
        if not requested_set:
            raise CapabilityProbeError("CAPABILITY_REQUEST_EMPTY")
        previous = registry.latest_capability_snapshot(connection.revision_id)
        if previous is not None:
            # A saved snapshot replaces the latest evidence for this revision.
            # Re-measure its previously probed scope instead of turning omitted
            # capabilities into not_requested or prolonging old support claims.
            # Failed/unsupported probes are included too, so regressions remain
            # visible and only newly measured evidence receives the new TTL.
            requested_set.update(
                item.capability for item in previous.observations
                if item.evidence_source == "probe"
            )
        snapshot = await self.probe(connection, requested=requested_set)
        registry.save_capability_snapshot(snapshot, actor=actor)
        return snapshot


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
