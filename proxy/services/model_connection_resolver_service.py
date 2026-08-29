"""Legacy migration and fail-closed role resolution for model connections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
from typing import Callable, Mapping
from urllib.parse import urlsplit

from proxy.services.llm_transport_profile_service import (
    resolve_connection_execution_profile,
)
from proxy.services.model_capability_service import (
    CapabilityRequirementError,
    require_capabilities,
)
from proxy.services.model_connection_contracts import (
    CapabilityName,
    CapabilitySnapshot,
    ConnectionLocality,
    ConnectionRole,
    ModelConnectionRevision,
)
from proxy.services.model_connection_registry_service import ModelConnectionRegistry
from proxy.services.model_connection_security_service import (
    AddressResolver,
    ConnectionSecurityError,
    ValidatedEndpoint,
    system_resolver,
    validate_endpoint,
)
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.model_secret_service import EnvironmentSecretStore, ModelSecretError


class ModelConnectionResolutionError(RuntimeError):
    """A role cannot safely resolve to an executable model connection."""


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _positive_int(value: str | None) -> int | None:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _locality(
    base_url: str,
    *,
    resolver: AddressResolver = system_resolver,
) -> ConnectionLocality:
    host = (urlsplit(base_url).hostname or "").strip().lower()
    if host == "localhost":
        return ConnectionLocality.LOOPBACK
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            port = urlsplit(base_url).port or (
                443 if urlsplit(base_url).scheme.lower() == "https" else 80
            )
            addresses = tuple(ipaddress.ip_address(item) for item in resolver(host, port))
        except (ConnectionSecurityError, ValueError):
            return ConnectionLocality.REMOTE
        if addresses and all(
            address.is_private and not address.is_loopback for address in addresses
        ):
            return ConnectionLocality.PRIVATE_NETWORK
        if addresses and all(address.is_loopback for address in addresses):
            return ConnectionLocality.LOOPBACK
        return ConnectionLocality.REMOTE
    if address.is_loopback:
        return ConnectionLocality.LOOPBACK
    if address.is_private:
        return ConnectionLocality.PRIVATE_NETWORK
    return ConnectionLocality.REMOTE


@dataclass(frozen=True)
class ResolvedModelConnection:
    connection_id: str
    revision_id: str
    display_name: str
    base_url: str
    model_id: str
    locality: ConnectionLocality
    requested_context_tokens: int | None
    secret_ref: str | None
    extension_type: str | None
    capability_snapshot: CapabilitySnapshot
    endpoint: ValidatedEndpoint
    effective_preset: ModelExecutionPreset


@dataclass(frozen=True)
class _LegacyTemplate:
    provider: str
    base_url: str
    model_id: str
    requested_context_tokens: int | None
    secret_ref: str | None
    extension_type: str | None


class LegacyConnectionImporter:
    """Snapshot the old environment and import its effective runtime once."""

    def __init__(
        self,
        registry: ModelConnectionRegistry,
        environ: Mapping[str, str],
        *,
        address_resolver: AddressResolver = system_resolver,
    ):
        self.registry = registry
        self.environ = dict(environ)
        self.address_resolver = address_resolver

    def _value(self, name: str, default: str = "") -> str:
        return str(self.environ.get(name, default) or "").strip()

    def _mlx(self) -> _LegacyTemplate:
        return _LegacyTemplate(
            provider="mlx",
            base_url=self._value("MLX_URL", "http://127.0.0.1:8080"),
            model_id=(
                self._value("LLM_MODEL")
                or self._value("MLX_MODEL")
                or "Qwen3.5-9B-MLX-4bit"
            ),
            requested_context_tokens=None,
            secret_ref=None,
            extension_type="mlx",
        )

    def _configured(self) -> _LegacyTemplate:
        provider = self._value("LES_LLM_PROVIDER", "mlx").lower() or "mlx"
        if provider in {"mlx", "local"}:
            return self._mlx()
        if provider == "freetoken":
            return _LegacyTemplate(
                provider="freetoken",
                base_url=self._value("FREETOKEN_BASE_URL", "http://127.0.0.1:1919/v1"),
                model_id=self._value("FREETOKEN_MODEL") or self._value("LLM_MODEL"),
                requested_context_tokens=_positive_int(self._value("FREETOKEN_CONTEXT_TOKENS")),
                secret_ref=(
                    "env:FREETOKEN_API_KEY" if self._value("FREETOKEN_API_KEY") else None
                ),
                extension_type="freetoken",
            )
        if provider == "openrouter":
            template = _LegacyTemplate(
                provider="openrouter",
                base_url=self._value("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                model_id=self._value("OPENROUTER_MODEL") or self._value("LLM_MODEL"),
                requested_context_tokens=None,
                secret_ref=(
                    "env:OPENROUTER_API_KEY" if self._value("OPENROUTER_API_KEY") else None
                ),
                extension_type=None,
            )
        elif provider in {"openai", "openai-compatible", "openai_compatible"}:
            template = _LegacyTemplate(
                provider="openai",
                base_url=self._value("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                model_id=(
                    self._value("OPENAI_MODEL")
                    or self._value("LES_DEFAULT_OPENAI_MODEL", "gpt-5.4")
                ),
                requested_context_tokens=None,
                secret_ref="env:OPENAI_API_KEY" if self._value("OPENAI_API_KEY") else None,
                extension_type=None,
            )
        elif provider == "ollama":
            template = _LegacyTemplate(
                provider="ollama",
                base_url=(
                    self._value("OLLAMA_BASE_URL")
                    or self._value("OLLAMA_URL", "http://127.0.0.1:11434")
                ),
                model_id=self._value("OLLAMA_MODEL") or self._value("LLM_MODEL"),
                requested_context_tokens=None,
                secret_ref="env:OLLAMA_API_KEY" if self._value("OLLAMA_API_KEY") else None,
                extension_type="ollama",
            )
        elif provider == "lemonade":
            template = _LegacyTemplate(
                provider="lemonade",
                base_url=self._value("LEMONADE_BASE_URL", "http://127.0.0.1:13305/api/v1"),
                model_id=self._value("LEMONADE_MODEL") or self._value("LLM_MODEL"),
                requested_context_tokens=None,
                secret_ref=(
                    "env:LEMONADE_API_KEY" if self._value("LEMONADE_API_KEY") else None
                ),
                extension_type="lemonade",
            )
        else:
            raise ModelConnectionResolutionError(f"LEGACY_PROVIDER_UNSUPPORTED: {provider}")

        if (
            template.secret_ref is None
            and _locality(template.base_url, resolver=self.address_resolver)
            is ConnectionLocality.REMOTE
        ):
            return self._mlx()
        return template

    def import_effective(self, *, actor: str) -> ModelConnectionRevision:
        template = self._configured()
        if not template.model_id:
            raise ModelConnectionResolutionError("LEGACY_MODEL_MISSING")
        revision = self.registry.import_connection(
            stable_connection_id=f"legacy:{template.provider}",
            display_name=f"Legacy · {template.provider}",
            base_url=template.base_url,
            model_id=template.model_id,
            locality=_locality(template.base_url, resolver=self.address_resolver),
            requested_context_tokens=template.requested_context_tokens,
            secret_ref=template.secret_ref,
            extension_type=template.extension_type,
            actor=actor,
        )
        if self.registry.get_role_binding(ConnectionRole.ANSWER) is None:
            self.registry.bind_role(
                ConnectionRole.ANSWER,
                revision.revision_id,
                expected_binding_revision=None,
                actor=actor,
            )
        return revision


class ModelConnectionResolver:
    def __init__(
        self,
        *,
        registry: ModelConnectionRegistry,
        secret_store: EnvironmentSecretStore,
        address_resolver: AddressResolver = system_resolver,
        clock: Clock = _utc_now,
        allow_private_http: bool = False,
    ):
        self.registry = registry
        self.secret_store = secret_store
        self.address_resolver = address_resolver
        self.clock = clock
        self.allow_private_http = allow_private_http

    def resolve(
        self,
        role: ConnectionRole,
        *,
        required_capabilities: frozenset[CapabilityName] = frozenset(),
    ) -> ResolvedModelConnection:
        canonical_role = ConnectionRole(role)
        binding = self.registry.get_role_binding(canonical_role)
        if binding is None:
            raise ModelConnectionResolutionError(
                f"ROLE_BINDING_MISSING: {canonical_role.value}"
            )
        revision = self.registry.get_revision(binding.connection_revision_id)
        if not self.registry.get_connection(revision.connection_id).enabled:
            raise ModelConnectionResolutionError("CONNECTION_DISABLED")
        try:
            if self.secret_store.status(revision.secret_ref) == "missing":
                raise ModelConnectionResolutionError("CONNECTION_SECRET_MISSING")
        except ModelSecretError as exc:
            raise ModelConnectionResolutionError(str(exc)) from exc
        snapshot = self.registry.latest_capability_snapshot(revision.revision_id)
        if snapshot is None:
            raise ModelConnectionResolutionError("CAPABILITY_SNAPSHOT_MISSING")
        required = set(required_capabilities)
        if canonical_role in {ConnectionRole.ANSWER, ConnectionRole.LOCAL_FALLBACK}:
            required.add(CapabilityName.CHAT_COMPLETIONS)
        elif canonical_role is ConnectionRole.EMBEDDINGS:
            required.add(CapabilityName.EMBEDDINGS)
        try:
            require_capabilities(snapshot, required, now=self.clock())
            endpoint = validate_endpoint(
                revision.base_url,
                revision.locality,
                resolver=self.address_resolver,
                allow_private_http=self.allow_private_http,
            )
        except (CapabilityRequirementError, ConnectionSecurityError) as exc:
            raise ModelConnectionResolutionError(str(exc)) from exc
        observed_context = _positive_int(snapshot.transport_options.get("observed_context_tokens"))
        preset = resolve_connection_execution_profile(
            model_id=revision.model_id,
            requested_context_tokens=revision.requested_context_tokens,
            observed_context_tokens=observed_context,
            observed_source=(
                "capability_snapshot" if observed_context is not None else "unavailable"
            ),
        )
        return ResolvedModelConnection(
            connection_id=revision.connection_id,
            revision_id=revision.revision_id,
            display_name=revision.display_name,
            base_url=endpoint.canonical_base_url,
            model_id=revision.model_id,
            locality=revision.locality,
            requested_context_tokens=revision.requested_context_tokens,
            secret_ref=revision.secret_ref,
            extension_type=revision.extension_type,
            capability_snapshot=snapshot,
            endpoint=endpoint,
            effective_preset=preset,
        )

    def resolve_fallback(
        self,
        failed_revision_id: str,
        *,
        required_capabilities: frozenset[CapabilityName] = frozenset(),
    ) -> ResolvedModelConnection:
        fallback = self.resolve(
            ConnectionRole.LOCAL_FALLBACK,
            required_capabilities=required_capabilities,
        )
        if fallback.revision_id == failed_revision_id:
            raise ModelConnectionResolutionError("FALLBACK_MATCHES_PRIMARY")
        return fallback
