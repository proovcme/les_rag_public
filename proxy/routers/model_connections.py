"""Authenticated administrator API for immutable model connections."""

from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from proxy.config import ENV_PATH
from proxy.security import RequestUser, require_admin, require_user
from proxy.services.model_capability_service import CapabilityProbe, CapabilityProbeError
from proxy.services.model_connection_contracts import (
    CapabilityName,
    CapabilitySnapshot,
    ConnectionLocality,
    ConnectionRole,
    ModelConnectionRevision,
    RoleBinding,
)
from proxy.services.model_connection_registry_service import (
    ModelConnectionRegistry,
    ModelConnectionRegistryError,
    RevisionConflictError,
)
from proxy.services.model_connection_resolver_service import (
    ModelConnectionResolutionError,
    ModelConnectionResolver,
)
from proxy.services.model_connection_security_service import (
    ConnectionSecurityError,
    validate_endpoint,
)
from proxy.services.model_secret_service import EnvironmentSecretStore, ModelSecretError
from proxy.services.model_engine_extension_service import EngineExtensionRegistry
from proxy.services.canonical_promotion_service import (
    CanonicalPromotionError,
    accept_promotion_report,
)


router = APIRouter(prefix="/api/model-connections", tags=["model-connections"])


def _registry() -> ModelConnectionRegistry:
    return ModelConnectionRegistry()


def _secret_store() -> EnvironmentSecretStore:
    return EnvironmentSecretStore(ENV_PATH)


def _probe(client: httpx.AsyncClient) -> CapabilityProbe:
    return CapabilityProbe(
        client=client,
        secret_store=_secret_store(),
        allow_private_http=True,
    )


def _extension_registry(client: httpx.AsyncClient) -> EngineExtensionRegistry:
    return EngineExtensionRegistry.with_read_only_defaults(client)


def _actor(user: RequestUser) -> str:
    identity = str(user.holder or user.source or "administrator").strip()
    return f"{user.role}:{identity}"


def _error(status_code: int, code: str, message: str | None = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message or code},
    )


def _code(error: Exception) -> str:
    text = str(error or "").strip()
    return text.split(":", 1)[0].strip() or type(error).__name__


def _registry_error(error: ModelConnectionRegistryError) -> HTTPException:
    code = _code(error)
    if isinstance(error, RevisionConflictError):
        return _error(status.HTTP_409_CONFLICT, code)
    if code in {"CONNECTION_NOT_FOUND", "CONNECTION_REVISION_NOT_FOUND"}:
        return _error(status.HTTP_404_NOT_FOUND, code)
    return _error(status.HTTP_409_CONFLICT, code)


def _secret_ref(connection_id: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9]+", "_", connection_id).strip("_").upper()
    return f"env:LES_MODEL_CONNECTION_{suffix}_API_KEY"


class ConnectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=160)
    base_url: str = Field(min_length=1, max_length=2048)
    model_id: str = Field(min_length=1, max_length=300)
    locality: ConnectionLocality
    requested_context_tokens: int | None = Field(default=None, ge=1)
    extension_type: str | None = Field(default=None, max_length=80)
    secret_value: SecretStr | None = None


class ConnectionRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_id: str = Field(min_length=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    model_id: str | None = Field(default=None, min_length=1, max_length=300)
    locality: ConnectionLocality | None = None
    requested_context_tokens: int | None = Field(default=None, ge=1)
    extension_type: str | None = Field(default=None, max_length=80)


class DisableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_id: str = Field(min_length=1)
    confirm_bound_roles: bool = False


class SecretReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_id: str = Field(min_length=1)
    secret_value: SecretStr


class CapabilityTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: str = Field(min_length=1)
    capabilities: list[CapabilityName] = Field(min_length=1)


class RoleBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_revision_id: str = Field(min_length=1)
    expected_binding_revision: int | None = Field(default=None, ge=1)


class PromotionAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: dict[str, Any]
    operator_confirmed: bool = False


class CapabilityPublic(BaseModel):
    name: str
    state: str
    evidence_source: str
    observed_at: str
    detail: str


class ConnectionAdminPublic(BaseModel):
    connection_id: str
    revision_id: str
    revision_no: int
    display_name: str
    protocol: str
    base_url: str
    model_id: str
    locality: str
    requested_context_tokens: int | None
    extension_type: str | None
    enabled: bool
    created_at: str
    created_by: str
    secret_status: str
    capabilities: list[CapabilityPublic]


class ConnectionSafePublic(BaseModel):
    connection_id: str
    revision_id: str
    display_name: str
    model_id: str
    locality: str
    fallback_used: bool = False
    preset_id: str
    input_token_limit: int


class BindingPublic(BaseModel):
    role: str
    binding_revision: int
    connection_revision_id: str
    bound_at: str
    bound_by: str


def _capabilities(snapshot: CapabilitySnapshot | None) -> list[CapabilityPublic]:
    if snapshot is None:
        return []
    return [
        CapabilityPublic(
            name=item.capability.value,
            state=item.state.value,
            evidence_source=item.evidence_source,
            observed_at=item.observed_at.isoformat(),
            detail=item.detail,
        )
        for item in snapshot.observations
    ]


def _admin_projection(
    revision: ModelConnectionRevision,
    *,
    registry: ModelConnectionRegistry,
    secret_store: EnvironmentSecretStore,
) -> ConnectionAdminPublic:
    try:
        secret_status = secret_store.status(revision.secret_ref)
    except ModelSecretError:
        secret_status = "invalid_reference"
    return ConnectionAdminPublic(
        connection_id=revision.connection_id,
        revision_id=revision.revision_id,
        revision_no=revision.revision_no,
        display_name=revision.display_name,
        protocol=revision.protocol,
        base_url=revision.base_url,
        model_id=revision.model_id,
        locality=revision.locality.value,
        requested_context_tokens=revision.requested_context_tokens,
        extension_type=revision.extension_type,
        enabled=revision.enabled,
        created_at=revision.created_at,
        created_by=revision.created_by,
        secret_status=secret_status,
        capabilities=_capabilities(
            registry.latest_capability_snapshot(revision.revision_id)
        ),
    )


def _binding_projection(binding: RoleBinding) -> BindingPublic:
    return BindingPublic(
        role=binding.role.value,
        binding_revision=binding.binding_revision,
        connection_revision_id=binding.connection_revision_id,
        bound_at=binding.bound_at,
        bound_by=binding.bound_by,
    )


def _bound_roles(registry: ModelConnectionRegistry, revision_id: str) -> list[str]:
    return [
        role.value
        for role in ConnectionRole
        if (binding := registry.get_role_binding(role)) is not None
        and binding.connection_revision_id == revision_id
    ]


_TEMPLATES: tuple[dict[str, Any], ...] = (
    {"template_id": "freetoken", "display_name": "FreeToken", "base_url": "http://127.0.0.1:1919/v1", "locality": "loopback", "extension_type": "freetoken"},
    {"template_id": "ollama", "display_name": "Ollama", "base_url": "http://127.0.0.1:11434/v1", "locality": "loopback", "extension_type": "ollama"},
    {"template_id": "lemonade", "display_name": "Lemonade", "base_url": "http://127.0.0.1:13305/api/v1", "locality": "loopback", "extension_type": "lemonade"},
    {"template_id": "mlx", "display_name": "MLX", "base_url": "http://127.0.0.1:8080/v1", "locality": "loopback", "extension_type": "mlx"},
    {"template_id": "lm_studio", "display_name": "LM Studio", "base_url": "http://127.0.0.1:1234/v1", "locality": "loopback", "extension_type": "lm_studio"},
    {"template_id": "llama_cpp", "display_name": "llama.cpp", "base_url": "http://127.0.0.1:8080/v1", "locality": "loopback", "extension_type": "llama_cpp"},
    {"template_id": "openai_compatible", "display_name": "OpenAI-compatible", "base_url": "https://example.invalid/v1", "locality": "remote", "extension_type": None},
)


@router.get("")
async def list_connections(_admin: RequestUser = Depends(require_admin)):
    registry = _registry()
    secrets = _secret_store()
    return {
        "connections": [
            _admin_projection(item, registry=registry, secret_store=secrets)
            for item in registry.list_connections(include_disabled=True)
        ],
        "bindings": {
            role.value: (
                _binding_projection(binding).model_dump()
                if (binding := registry.get_role_binding(role)) is not None
                else None
            )
            for role in ConnectionRole
        },
    }


@router.get("/templates")
async def connection_templates(_admin: RequestUser = Depends(require_admin)):
    return {"templates": [dict(item) for item in _TEMPLATES]}


@router.post("/promotion/accept")
async def accept_promotion(
    req: PromotionAcceptRequest,
    admin: RequestUser = Depends(require_admin),
):
    try:
        receipt = accept_promotion_report(
            None,
            req.report,
            operator_confirmed=req.operator_confirmed,
            actor=_actor(admin),
        )
    except CanonicalPromotionError as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, _code(error)) from error
    return {
        "status": "accepted",
        "source_commit": receipt.source_commit,
        "build_number": receipt.build_number,
        "preset_id": receipt.preset_id,
        "observed_model_identity": receipt.observed_model_identity,
        "acceptance_sha256": receipt.acceptance_sha256,
        "route_mode_changed": False,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_connection(
    req: ConnectionCreateRequest,
    admin: RequestUser = Depends(require_admin),
):
    registry = _registry()
    secrets = _secret_store()
    actor = _actor(admin)
    try:
        endpoint = validate_endpoint(
            req.base_url,
            req.locality,
            allow_private_http=True,
        )
        revision = registry.create_connection(
            display_name=req.display_name,
            base_url=endpoint.canonical_base_url,
            model_id=req.model_id,
            locality=req.locality,
            requested_context_tokens=req.requested_context_tokens,
            secret_ref=None,
            extension_type=req.extension_type,
            actor=actor,
        )
        if req.secret_value is not None:
            secret_ref = _secret_ref(revision.connection_id)
            secrets.replace(secret_ref, req.secret_value.get_secret_value(), actor=actor)
            revision = registry.revise_connection(
                revision.connection_id,
                expected_revision_id=revision.revision_id,
                secret_ref=secret_ref,
                actor=actor,
            )
        return _admin_projection(revision, registry=registry, secret_store=secrets)
    except ConnectionSecurityError as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, _code(error)) from error
    except ModelSecretError as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, _code(error)) from error
    except ModelConnectionRegistryError as error:
        raise _registry_error(error) from error


@router.post("/{connection_id}/revisions")
async def revise_connection(
    connection_id: str,
    req: ConnectionRevisionRequest,
    admin: RequestUser = Depends(require_admin),
):
    registry = _registry()
    secrets = _secret_store()
    try:
        current = registry.get_connection(connection_id)
        changes = req.model_dump(exclude={"expected_revision_id"}, exclude_unset=True)
        effective_url = str(changes.get("base_url", current.base_url))
        effective_locality = ConnectionLocality(changes.get("locality", current.locality))
        endpoint = validate_endpoint(
            effective_url,
            effective_locality,
            allow_private_http=True,
        )
        if "base_url" in changes:
            changes["base_url"] = endpoint.canonical_base_url
        revision = registry.revise_connection(
            connection_id,
            expected_revision_id=req.expected_revision_id,
            actor=_actor(admin),
            **changes,
        )
        return _admin_projection(revision, registry=registry, secret_store=secrets)
    except ConnectionSecurityError as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, _code(error)) from error
    except ModelConnectionRegistryError as error:
        raise _registry_error(error) from error


@router.post("/{connection_id}/disable")
async def disable_connection(
    connection_id: str,
    req: DisableRequest,
    admin: RequestUser = Depends(require_admin),
):
    registry = _registry()
    secrets = _secret_store()
    try:
        current = registry.get_connection(connection_id)
        roles = _bound_roles(registry, current.revision_id)
        if roles and not req.confirm_bound_roles:
            raise _error(
                status.HTTP_409_CONFLICT,
                "BOUND_CONNECTION_CONFIRMATION_REQUIRED",
                ",".join(roles),
            )
        revision = registry.disable_connection(
            connection_id,
            expected_revision_id=req.expected_revision_id,
            actor=_actor(admin),
        )
        return _admin_projection(revision, registry=registry, secret_store=secrets)
    except HTTPException:
        raise
    except ModelConnectionRegistryError as error:
        raise _registry_error(error) from error


@router.post("/{connection_id}/secret")
async def replace_secret(
    connection_id: str,
    req: SecretReplaceRequest,
    admin: RequestUser = Depends(require_admin),
):
    registry = _registry()
    secrets = _secret_store()
    actor = _actor(admin)
    try:
        current = registry.get_connection(connection_id)
        if current.revision_id != req.expected_revision_id:
            raise RevisionConflictError("CONNECTION_REVISION_CONFLICT")
        secret_ref = current.secret_ref or _secret_ref(current.connection_id)
        secrets.replace(secret_ref, req.secret_value.get_secret_value(), actor=actor)
        if current.secret_ref is None:
            current = registry.revise_connection(
                connection_id,
                expected_revision_id=req.expected_revision_id,
                secret_ref=secret_ref,
                actor=actor,
            )
        return _admin_projection(current, registry=registry, secret_store=secrets)
    except ModelSecretError as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, _code(error)) from error
    except ModelConnectionRegistryError as error:
        raise _registry_error(error) from error


@router.post("/{connection_id}/test")
async def test_connection(
    connection_id: str,
    req: CapabilityTestRequest,
    admin: RequestUser = Depends(require_admin),
):
    registry = _registry()
    try:
        revision = registry.get_revision(req.revision_id)
        if revision.connection_id != connection_id:
            raise _error(status.HTTP_404_NOT_FOUND, "CONNECTION_REVISION_NOT_FOUND")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            snapshot = await _probe(client).probe_and_store(
                revision,
                requested=req.capabilities,
                registry=registry,
                actor=_actor(admin),
            )
        return {
            "revision_id": revision.revision_id,
            "snapshot_id": snapshot.snapshot_id,
            "observed_at": snapshot.observed_at.isoformat(),
            "expires_at": snapshot.expires_at.isoformat(),
            "capabilities": [item.model_dump() for item in _capabilities(snapshot)],
        }
    except HTTPException:
        raise
    except (ConnectionSecurityError, ModelSecretError, CapabilityProbeError) as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, _code(error)) from error
    except ModelConnectionRegistryError as error:
        raise _registry_error(error) from error


@router.get("/{connection_id}/extension/status")
async def extension_status(
    connection_id: str,
    _admin: RequestUser = Depends(require_admin),
):
    registry = _registry()
    try:
        revision = registry.get_connection(connection_id)
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            return await _extension_registry(client).status(revision)
    except ModelConnectionRegistryError as error:
        raise _registry_error(error) from error


@router.put("/roles/{role}")
async def bind_role(
    role: ConnectionRole,
    req: RoleBindingRequest,
    admin: RequestUser = Depends(require_admin),
):
    registry = _registry()
    try:
        binding = registry.bind_role(
            role,
            req.connection_revision_id,
            expected_binding_revision=req.expected_binding_revision,
            actor=_actor(admin),
        )
        return _binding_projection(binding)
    except ModelConnectionRegistryError as error:
        raise _registry_error(error) from error


@router.get("/effective")
async def effective_connections(_user: RequestUser = Depends(require_user)):
    registry = _registry()
    resolver = ModelConnectionResolver(
        registry=registry,
        secret_store=_secret_store(),
        allow_private_http=True,
    )
    roles: dict[str, dict[str, Any] | None] = {}
    for role in ConnectionRole:
        binding = registry.get_role_binding(role)
        if binding is None:
            roles[role.value] = None
            continue
        try:
            connection = resolver.resolve(role)
            roles[role.value] = ConnectionSafePublic(
                connection_id=connection.connection_id,
                revision_id=connection.revision_id,
                display_name=connection.display_name,
                model_id=connection.model_id,
                locality=connection.locality.value,
                preset_id=connection.effective_preset.preset_id,
                input_token_limit=connection.effective_preset.input_token_limit,
            ).model_dump()
        except ModelConnectionResolutionError as error:
            revision = registry.get_revision(binding.connection_revision_id)
            roles[role.value] = {
                "connection_id": revision.connection_id,
                "revision_id": revision.revision_id,
                "display_name": revision.display_name,
                "model_id": revision.model_id,
                "locality": revision.locality.value,
                "status": "blocked",
                "code": _code(error),
            }
    return {"roles": roles}
