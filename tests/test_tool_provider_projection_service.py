import pytest

from proxy.services.tool_provider_projection_service import project_tool_contract
from proxy.services.tool_registry_service import canonical_tool_registry


@pytest.mark.parametrize("provider", ["openai", "openai_compatible", "ollama", "mcp"])
def test_provider_projection_preserves_canonical_identity_and_schema(provider):
    contract = canonical_tool_registry().require("build_vor_workbook").contract
    projected = project_tool_contract(contract, provider)

    assert projected["name"] == "build_vor_workbook"
    assert projected["version"] == "1.0.0"
    assert projected["effect"] == "draft"
    assert projected["input_schema"]["required"] == ["attachment_id"]
    assert "handler" not in projected


def test_unknown_provider_is_rejected():
    contract = canonical_tool_registry().require("build_vor_workbook").contract
    with pytest.raises(ValueError, match="provider"):
        project_tool_contract(contract, "custom")
