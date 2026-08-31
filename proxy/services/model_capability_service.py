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


def _native_chat_url(endpoint: ValidatedEndpoint) -> str:
    parsed = urlsplit(endpoint.canonical_base_url)
    path = parsed.path.rstrip("/")
    for suffix in ("/api/v1", "/v1"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit((parsed.scheme, parsed.netloc, f"{path}/api/chat", "", ""))


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

        transport_options = {"max_output_field": "max_tokens"}
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
