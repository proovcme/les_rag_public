import json
from pathlib import Path

import pytest

from tools.code_runtime_map import build_inventory, render_markdown


ROOT = Path(__file__).resolve().parents[1]


def _modules_by_path(inventory: dict) -> dict[str, dict]:
    return {item["path"]: item for item in inventory["modules"]}


@pytest.fixture(scope="module")
def inventory() -> dict:
    return build_inventory(ROOT)


def test_runtime_map_distinguishes_product_runtime_and_tool_only_code(inventory: dict):
    modules = _modules_by_path(inventory)

    assert modules["proxy/app.py"]["status"] == "PRODUCT_REACHABLE"
    assert modules["proxy/smeta_core/document_workflow.py"]["status"] == "PRODUCT_REACHABLE"
    assert modules["tools/windows_update_engine.py"]["status"] == "RUNTIME_SUPPORT"
    assert modules["tools/build_tauri_app.py"]["status"] == "TEST_OR_TOOL_ONLY"


def test_runtime_map_exposes_registered_route_and_smeta_symbol_consumers(inventory: dict):
    assert any(
        route["path"] == "/api/rim/sessions" and route["method"] == "POST"
        for route in inventory["routes"]
    )
    smeta = inventory["focus"]["proxy/smeta_core/document_workflow.py"]
    assert "proxy/routers/chat.py" in smeta["symbols"]["finalize_locked_mapping_revision"]
    assert "proxy/services/rim_agent_turn_service.py" in smeta["symbols"]["_run_batch_norm_agent"]
    assert "proxy/services/smeta_chat_application_service.py" in smeta["symbols"]["run_vor_document_workflow"]


def test_runtime_map_is_conservative_and_deterministically_sorted(inventory: dict):
    paths = [item["path"] for item in inventory["modules"]]
    route_keys = [
        (item["path"], item["method"], item["source"], item["handler"])
        for item in inventory["routes"]
    ]

    assert paths == sorted(paths)
    assert route_keys == sorted(route_keys)
    assert inventory["summary"]["tracked_python_files"] > 900
    assert inventory["summary"]["product_reachable"] > 100
    assert inventory["summary"]["dormant_candidates"] > 0
    markdown = render_markdown(inventory)
    assert "не является доказательством мёртвого кода" in markdown
    assert "proxy/smeta_core/document_workflow.py" in markdown
    assert "DORMANT_CANDIDATE" in markdown
    assert (ROOT / "docs" / "CODE_RUNTIME_MAP.md").read_text(encoding="utf-8") == markdown
    assert json.loads(
        (ROOT / "docs" / "generated" / "code_runtime_map.json").read_text(encoding="utf-8")
    ) == inventory
