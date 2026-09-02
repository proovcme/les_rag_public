from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from tools import build_smeta_structured_base, smeta_generation_coordinator
from tools import build_tauri_app


ROOT = Path(__file__).resolve().parents[1]


def test_make_smeta_base_publishes_through_generation_coordinator():
    completed = subprocess.run(
        ["make", "-n", "smeta-base"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "tools.smeta_generation_coordinator" in completed.stdout
    assert "python -m tools.build_smeta_structured_base" not in completed.stdout


def test_low_level_structured_builder_refuses_configured_active_path(
    tmp_path: Path, monkeypatch
):
    active = tmp_path / "renamed bases" / "customer.sqlite"
    monkeypatch.setattr(
        "proxy.smeta_core.base_registry.active_base",
        lambda: {
            "base_path": str(active),
            "minimum_norms": 1,
        },
    )

    with pytest.raises(RuntimeError, match="generation coordinator"):
        build_smeta_structured_base.main(
            [
                "--source",
                str(tmp_path / "source.parquet"),
                "--out",
                str(active),
                "--manifest-out",
                str(active.with_suffix(".manifest.json")),
            ]
        )


def test_coordinator_cli_uses_configured_paths_and_arbitrary_alias(
    tmp_path: Path, monkeypatch
):
    active = tmp_path / "renamed bases" / "customer.sqlite"
    manifest = tmp_path / "metadata" / "customer-manifest.json"
    integrity = tmp_path / "metadata" / "customer-integrity.json"
    source = tmp_path / "input.parquet"
    source.write_bytes(b"source")
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        "proxy.smeta_core.base_registry.active_base",
        lambda: {
            "base_path": str(active),
            "manifest_path": str(manifest),
            "integrity_path": str(integrity),
            "rag_collection": "customer_norm_catalog_2026",
            "minimum_norms": 40000,
        },
    )
    monkeypatch.setattr(
        smeta_generation_coordinator,
        "publish_generation",
        lambda **kwargs: observed.update(kwargs) or {"status": "activated"},
    )
    monkeypatch.setattr(
        smeta_generation_coordinator,
        "mutable_path",
        lambda _path: tmp_path / "generations",
        raising=False,
    )

    assert smeta_generation_coordinator.main(["--source", str(source)]) == 0
    assert observed["active_base"] == active
    assert observed["active_base_manifest"] == manifest
    assert observed["active_integrity"] == integrity
    assert observed["active_rag_manifest"] == active.with_name(
        "les_smeta_norm_rag_manifest.json"
    )
    assert observed["alias"] == "customer_norm_catalog_2026"


def test_windows_runtime_contains_the_complete_smeta_generation_worker():
    required = {
        "tools/activate_qdrant_generation.py",
        "tools/activate_smeta_rag_generation.py",
        "tools/build_smeta_norm_rag.py",
        "tools/rebuild_active_smeta_rag.py",
        "tools/smeta_generation_coordinator.py",
        "tools/smeta_generation_lease.py",
        "tools/smeta_rag_readiness.py",
    }

    missing = {
        relative
        for relative in required
        if not build_tauri_app.windows_runtime_manifest_allows(ROOT / relative)
    }
    assert not missing, f"installed runtime is missing smeta update workers: {sorted(missing)}"


def test_active_smeta_builder_calls_are_confined_to_staging_publishers():
    allowed = {
        "tools/build_smeta_base_v2.py",
        "tools/smeta_generation_coordinator.py",
    }
    callers: set[str] = set()
    for path in (ROOT / "tools").glob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if relative == "tools/build_smeta_structured_base.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "build_structured_base")
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "build_structured_base"
                )
            )
            for node in ast.walk(tree)
        ):
            callers.add(relative)

    assert callers == allowed
