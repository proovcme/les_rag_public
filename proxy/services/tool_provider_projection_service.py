"""Schema-only projections of canonical tool contracts for supported transports."""
from __future__ import annotations

from typing import Any

from proxy.services.tool_contract_service import ToolContract

SUPPORTED_PROVIDERS = frozenset({"openai", "openai_compatible", "ollama", "mcp"})


def project_tool_contract(contract: ToolContract, provider: str) -> dict[str, Any]:
    normalized = str(provider or "").strip().casefold()
    if normalized not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported tool provider: {provider}")
    payload = contract.public_payload()
    return {
        "provider": normalized,
        "name": payload["name"],
        "version": payload["version"],
        "description": payload["summary"],
        "effect": payload["effect"],
        "input_schema": payload["input_schema"],
    }
