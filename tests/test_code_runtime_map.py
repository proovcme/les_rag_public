import json
import subprocess
from pathlib import Path

import pytest

from tools.code_runtime_map import _tracked_python_files, build_inventory, render_markdown


ROOT = Path(__file__).resolve().parents[1]


def test_tracked_python_files_ignore_worktree_deletions(tmp_path: Path):
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    keep = tmp_path / "keep.py"
    retired = tmp_path / "retired.py"
    keep.write_text("VALUE = 1\n", encoding="utf-8")
    retired.write_text("VALUE = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "keep.py", "retired.py"], cwd=tmp_path, check=True)
    retired.unlink()

    assert _tracked_python_files(tmp_path) == ["keep.py"]


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


def test_proven_cleanup_leaves_only_the_intentionally_dormant_mail_surface(
    inventory: dict,
):
    modules = _modules_by_path(inventory)
    dormant = sorted(
        item["path"]
        for item in inventory["modules"]
        if item["status"] == "DORMANT_CANDIDATE"
    )

    assert dormant == ["sovushka/pages/mail.py"]
    for retired in (
        "proxy/legacy_app.py",
        "test_auth.py",
        "test_ng.py",
        "tools/pikabu_construction_rd.py",
        "tools/test_chunk_density.py",
    ):
        assert retired not in modules


def test_retired_one_off_operator_scripts_do_not_reenter_tool_inventory(
    inventory: dict,
):
    modules = _modules_by_path(inventory)

    for supported in (
        "proxy/routers/checklist_review.py",
        "sovushka/pages/samovar.py",
        "tools/ezhik_imap_smoke.py",
        "tools/reindex_route_changes_guarded.py",
    ):
        assert supported in modules

    for retired in (
        "tools/checklist_review_smoke.py",
        "tools/ezhik_mail_smoke.py",
        "tools/rag_batch_parse.py",
        "tools/rebucket_ntd_other.py",
        "tools/smart_dataset_plan.py",
        "tools/smart_dataset_rebuild.py",
    ):
        assert retired not in modules


def test_api_surface_keeps_profiles_and_internal_extraction_without_duplicate_public_controls(
    inventory: dict,
):
    modules = _modules_by_path(inventory)
    routes = {(item["method"], item["path"]) for item in inventory["routes"]}

    assert "proxy/services/prompt_registry_service.py" in modules
    assert "proxy/services/extract_service.py" in modules
    assert ("GET", "/api/profiles") in routes

    assert ("GET", "/api/prompts") not in routes
    assert ("PATCH", "/api/prompts/{prompt_key:path}") not in routes
    assert ("DELETE", "/api/prompts/{prompt_key:path}") not in routes
    assert ("POST", "/api/extract/structured") not in routes


def test_unfinished_incoming_control_is_retired_without_removing_active_workflows(
    inventory: dict,
):
    modules = _modules_by_path(inventory)
    paths = {item["path"] for item in inventory["routes"]}

    for active_prefix in (
        "/api/field",
        "/api/tasks",
        "/api/notes",
        "/api/filemap",
        "/api/decisions",
    ):
        assert any(path == active_prefix or path.startswith(f"{active_prefix}/") for path in paths)

    assert "proxy/routers/incoming_control.py" not in modules
    assert "proxy/services/incoming_control_service.py" not in modules
    assert not [path for path in paths if path.startswith("/api/incoming-control")]
