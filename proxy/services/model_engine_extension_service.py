"""Optional engine management kept outside the inference transport."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from proxy.services.model_connection_security_service import (
    AddressResolver,
    ConnectionSecurityError,
    ValidatedEndpoint,
    system_resolver,
    validate_connected_peer,
    validate_endpoint,
)


class EngineExtensionError(RuntimeError):
    pass


class EngineExtension(Protocol):
    async def status(self, connection: Any) -> Mapping[str, Any]: ...

    async def execute(
        self,
        connection: Any,
        operation: str,
        arguments: Mapping[str, Any],
        approval_ref: str,
    ) -> Mapping[str, Any]: ...


def _engine_root(base_url: str) -> str:
    parsed = urlsplit(str(base_url or ""))
    path = parsed.path.rstrip("/")
    for suffix in ("/api/v1", "/v1"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


class ReadOnlyHttpStatusExtension:
    def __init__(
        self,
        extension_type: str,
        path: str,
        *,
        client: httpx.AsyncClient,
        address_resolver: AddressResolver = system_resolver,
        peer_verifier: Callable[[httpx.Response, ValidatedEndpoint], None] = validate_connected_peer,
    ):
        self.extension_type = extension_type
        self.path = "/" + path.lstrip("/")
        self.client = client
        self.address_resolver = address_resolver
        self.peer_verifier = peer_verifier

    async def status(self, connection: Any) -> Mapping[str, Any]:
        try:
            endpoint = validate_endpoint(
                connection.base_url,
                connection.locality,
                resolver=self.address_resolver,
                allow_private_http=True,
            )
            response = await self.client.get(
                f"{_engine_root(endpoint.canonical_base_url)}{self.path}",
                follow_redirects=False,
            )
            self.peer_verifier(response, endpoint)
            payload = response.json() if response.status_code == 200 else {}
        except ConnectionSecurityError as error:
            return {"status": "blocked", "code": str(error)}
        except (httpx.HTTPError, TypeError, ValueError):
            return {"status": "unavailable"}
        safe: dict[str, Any] = {"status": "ok" if response.status_code == 200 else "unavailable"}
        if isinstance(payload, Mapping):
            for key in (
                "model",
                "loaded",
                "memory_state",
                "num_pages",
                "moe_cache_size",
                "num_mamba_slots",
            ):
                if key in payload and isinstance(payload[key], (str, int, float, bool, type(None))):
                    safe[key] = payload[key]
            geometry = payload.get("geometry")
            if isinstance(geometry, Mapping):
                for key in ("num_pages", "moe_cache_size", "num_mamba_slots"):
                    if key in geometry and isinstance(geometry[key], (int, float)):
                        safe[key] = geometry[key]
        return safe

    async def execute(
        self,
        connection: Any,
        operation: str,
        arguments: Mapping[str, Any],
        approval_ref: str,
    ) -> Mapping[str, Any]:
        raise EngineExtensionError("EXTENSION_READ_ONLY")


class EngineExtensionRegistry:
    def __init__(self) -> None:
        self._extensions: dict[str, EngineExtension] = {}

    @classmethod
    def with_read_only_defaults(
        cls,
        client: httpx.AsyncClient,
        *,
        address_resolver: AddressResolver = system_resolver,
        peer_verifier: Callable[[httpx.Response, ValidatedEndpoint], None] = validate_connected_peer,
    ) -> "EngineExtensionRegistry":
        registry = cls()
        registry.register(
            "freetoken",
            ReadOnlyHttpStatusExtension(
                "freetoken",
                "/v1/cache/status",
                client=client,
                address_resolver=address_resolver,
                peer_verifier=peer_verifier,
            ),
        )
        registry.register(
            "mlx",
            ReadOnlyHttpStatusExtension(
                "mlx",
                "/api/health",
                client=client,
                address_resolver=address_resolver,
                peer_verifier=peer_verifier,
            ),
        )
        return registry

    def register(self, extension_type: str, extension: EngineExtension) -> None:
        key = str(extension_type or "").strip().casefold()
        if not key:
            raise EngineExtensionError("EXTENSION_TYPE_REQUIRED")
        if key in self._extensions:
            raise EngineExtensionError("EXTENSION_ALREADY_REGISTERED")
        self._extensions[key] = extension

    def _resolve(self, connection: Any) -> tuple[str, EngineExtension | None]:
        key = str(getattr(connection, "extension_type", "") or "").strip().casefold()
        return key, self._extensions.get(key)

    async def status(self, connection: Any) -> Mapping[str, Any]:
        extension_type, extension = self._resolve(connection)
        if extension is None:
            return {"status": "unsupported", "extension_type": extension_type or "none"}
        payload = dict(await extension.status(connection))
        payload["extension_type"] = extension_type
        return payload

    async def execute(
        self,
        connection: Any,
        operation: str,
        arguments: Mapping[str, Any],
        approval_ref: str | None,
    ) -> Mapping[str, Any]:
        extension_type, extension = self._resolve(connection)
        if extension is None:
            raise EngineExtensionError("EXTENSION_UNSUPPORTED")
        exact_approval = str(approval_ref or "").strip()
        if not exact_approval:
            raise EngineExtensionError("APPROVAL_REQUIRED")
        return await extension.execute(
            connection,
            str(operation or "").strip(),
            dict(arguments),
            exact_approval,
        )
