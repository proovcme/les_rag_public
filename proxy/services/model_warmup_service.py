"""Optional generation warmup of the explicitly assigned local answer model."""

from __future__ import annotations

import time
from typing import Any

import httpx

from backend.http_client_policy import trust_env_for_url
from proxy.config import ENV_PATH
from proxy.services.context_governor_service import (
    ContextCandidate, ContextGovernor, ContextKind, ContextObject,
    ContextRequiredSectionOverflow, ContextRequiredWireOverflow,
)
from proxy.services.model_connection_contracts import (
    CapabilityName, ConnectionLocality, ConnectionRole,
)
from proxy.services.model_connection_registry_service import (
    ModelConnectionRegistry, ModelConnectionRegistryError,
)
from proxy.services.model_connection_resolver_service import (
    ModelConnectionResolutionError, ModelConnectionResolver,
)
from proxy.services.model_secret_service import EnvironmentSecretStore
from proxy.services.openai_compatible_transport_service import (
    InferenceRequest, ModelTransportError, OpenAICompatibleTransport,
)


async def warmup_answer_model(
    *,
    registry: ModelConnectionRegistry | None = None,
    resolver: ModelConnectionResolver | None = None,
    transport: OpenAICompatibleTransport | None = None,
) -> dict[str, Any]:
    """Warm one pinned local ANSWER revision, without probes or model fallback.

    Embeddings and reranking keep their independent production configuration.
    Remote answers are skipped before security resolution or secret access;
    a missing/stale assignment must never load a legacy or fallback model.
    """

    started = time.monotonic()
    identity: dict[str, Any] = {}
    try:
        registry = registry or (resolver.registry if resolver is not None else ModelConnectionRegistry())
        binding = registry.get_role_binding(ConnectionRole.ANSWER)
        if binding is None:
            return {"status": "skipped", "code": "ANSWER_BINDING_MISSING"}
        revision = registry.get_revision(binding.connection_revision_id)
        identity = {"connection_revision_id": revision.revision_id, "model_id": revision.model_id}
        if revision.locality is ConnectionLocality.REMOTE:
            return {"status": "skipped", "code": "REMOTE_ANSWER_NOT_WARMED", **identity}
        if not registry.get_connection(revision.connection_id).enabled:
            return {"status": "skipped", "code": "CONNECTION_DISABLED", **identity}
        if resolver is None:
            resolver = ModelConnectionResolver(
                registry=registry, secret_store=EnvironmentSecretStore(ENV_PATH),
                allow_private_http=True,
            )
        connection = resolver.resolve_revision(
            revision.revision_id,
            required_capabilities=frozenset({CapabilityName.CHAT_COMPLETIONS}),
        )
        packet = ContextGovernor(connection.effective_preset).pack([
            ContextCandidate(
                ContextKind.REQUEST, (ContextObject("startup-warmup", "прогрев"),), required=True,
            ),
        ])
        request = InferenceRequest(
            messages=packet.as_messages(), max_output_tokens=1, reasoning_enabled=False,
        )

        async def complete_once(selected_transport: OpenAICompatibleTransport) -> dict[str, Any]:
            # The immutable revision was resolved above, but the operator may
            # have changed its role while the transport/client was prepared.
            if registry.get_role_binding(ConnectionRole.ANSWER) != binding:
                return {"status": "skipped", "code": "ANSWER_BINDING_CHANGED", **identity}
            if not registry.get_connection(revision.connection_id).enabled:
                return {"status": "skipped", "code": "CONNECTION_DISABLED", **identity}
            await selected_transport.complete(connection, request)
            return {"status": "ok", "elapsed": round(time.monotonic() - started, 1), **identity}

        if transport is not None:
            return await complete_once(transport)
        async with httpx.AsyncClient(
            trust_env=trust_env_for_url(connection.base_url), timeout=180.0,
        ) as client:
            selected_transport = OpenAICompatibleTransport(
                client=client, secret_store=resolver.secret_store, timeout=180.0,
            )
            return await complete_once(selected_transport)
    except (
        ModelConnectionRegistryError, ModelConnectionResolutionError, ModelTransportError,
        ContextRequiredSectionOverflow, ContextRequiredWireOverflow,
    ) as error:
        return {"status": "error", "code": str(error).partition(":")[0], **identity}
    except httpx.HTTPError as error:
        # HTTP exception text may contain URLs; diagnostics need no endpoint or
        # request headers, and an unsuccessful warmup is never reported as OK.
        return {"status": "error", "code": type(error).__name__, **identity}
