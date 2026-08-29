from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
import httpx

from proxy.services.model_engine_extension_service import (
    EngineExtensionError,
    EngineExtensionRegistry,
)
from proxy.services.model_connection_contracts import ConnectionLocality
from proxy.services.openai_compatible_transport_service import OpenAICompatibleTransport


class FakeExtension:
    async def status(self, connection):
        return {"status": "ok", "seen": connection.revision_id}

    async def execute(self, connection, operation, arguments, approval_ref):
        return {"operation": operation, "approval_ref": approval_ref}


def _connection(*, extension_type="mlx", display_name="Renamed"):
    return SimpleNamespace(
        revision_id="conn:c1:r2",
        display_name=display_name,
        extension_type=extension_type,
        base_url="http://127.0.0.1:8080/v1",
        locality=ConnectionLocality.LOOPBACK,
    )


def test_inference_transport_cannot_access_engine_extensions():
    assert "extension_registry" not in inspect.signature(
        OpenAICompatibleTransport.__init__
    ).parameters


@pytest.mark.asyncio
async def test_extension_is_selected_by_type_not_display_name():
    registry = EngineExtensionRegistry()
    registry.register("mlx", FakeExtension())

    result = await registry.status(
        _connection(extension_type="mlx", display_name="FreeToken")
    )

    assert result["extension_type"] == "mlx"
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_missing_extension_is_explicit_and_does_not_affect_inference():
    result = await EngineExtensionRegistry().status(
        _connection(extension_type="ollama")
    )
    assert result == {"status": "unsupported", "extension_type": "ollama"}


@pytest.mark.asyncio
async def test_mutating_extension_operation_requires_exact_approval():
    registry = EngineExtensionRegistry()
    registry.register("mlx", FakeExtension())

    with pytest.raises(EngineExtensionError, match="APPROVAL_REQUIRED"):
        await registry.execute(_connection(), "unload", {}, approval_ref=None)

    result = await registry.execute(
        _connection(), "unload", {}, approval_ref="approval:exact"
    )
    assert result["approval_ref"] == "approval:exact"


@pytest.mark.asyncio
async def test_http_extension_revalidates_endpoint_before_status_request():
    requested: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json={"loaded": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registry = EngineExtensionRegistry.with_read_only_defaults(
            client,
            address_resolver=lambda _host, _port: ("203.0.113.8",),
        )
        result = await registry.status(_connection())

    assert result == {
        "status": "blocked",
        "code": "LOCALITY_ADDRESS_MISMATCH",
        "extension_type": "mlx",
    }
    assert requested == []
