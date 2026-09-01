from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tools.windows_runtime_entrypoints import validate_registry
from tools import build_tauri_app


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _fixture(tmp_path: Path, *, source: str, staged_target: bool) -> dict:
    root = tmp_path / "root"
    staged = tmp_path / "staged"
    callsite = Path("proxy/services/worker_service.py")
    for base in (root, staged):
        path = base / callsite
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    target = Path("tools/worker.py")
    (root / target).parent.mkdir(parents=True, exist_ok=True)
    (root / target).write_text("def main(): return 0\n", encoding="utf-8")
    if staged_target:
        (staged / target).parent.mkdir(parents=True, exist_ok=True)
        (staged / target).write_text("def main(): return 0\n", encoding="utf-8")
    manifest = _write_json(
        root / "config/windows_runtime_manifest.json",
        {
            "schema": "les.windows-runtime-manifest.v1",
            "include_prefixes": ["proxy/"],
            "include_files": ["tools/worker.py"],
        },
    )
    return {
        "root": root,
        "staged_root": staged,
        "runtime_manifest": manifest,
    }


def _registry(tmp_path: Path, entries: list[dict]) -> Path:
    return _write_json(
        tmp_path / "runtime-entrypoints.json",
        {"schema": "les.windows-runtime-entrypoints.v1", "entries": entries},
    )


def _worker_entry() -> dict:
    return {
        "id": "worker",
        "kind": "python_module",
        "target": "tools.worker",
        "required_files": ["tools/worker.py"],
        "callsites": ["proxy/services/worker_service.py"],
    }


def test_registry_rejects_missing_dynamic_python_module(tmp_path):
    fixture = _fixture(
        tmp_path,
        source='cmd = [sys.executable, "-m", "tools.worker"]\n',
        staged_target=False,
    )

    with pytest.raises(RuntimeError, match="MISSING_RUNTIME_ENTRYPOINT"):
        validate_registry(
            **fixture,
            registry_path=_registry(tmp_path, [_worker_entry()]),
        )


def test_registry_rejects_unregistered_runtime_module_call(tmp_path):
    fixture = _fixture(
        tmp_path,
        source='cmd = [sys.executable, "-m", "tools.worker"]\n',
        staged_target=True,
    )

    with pytest.raises(RuntimeError, match="UNREGISTERED_RUNTIME_ENTRYPOINT"):
        validate_registry(
            **fixture,
            registry_path=_registry(tmp_path, []),
        )


@pytest.mark.parametrize(
    ("target", "source"),
    [
        ("tools/helper.py", 'python tools/helper.py\n'),
        ("tools/helper.ps1", '& "tools/helper.ps1"\n'),
        ("tools/helper.exe", '& "tools/helper.exe"\n'),
    ],
)
def test_registry_discovers_nonmodule_runtime_targets(tmp_path, target, source):
    fixture = _fixture(tmp_path, source="", staged_target=True)
    relative = Path(target)
    for base in (fixture["root"], fixture["staged_root"]):
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")
    callsite = fixture["staged_root"] / "tools/caller.ps1"
    callsite.write_text(source, encoding="utf-8")

    with pytest.raises(RuntimeError, match="UNREGISTERED_RUNTIME_ENTRYPOINT"):
        validate_registry(
            **fixture,
            registry_path=_registry(tmp_path, []),
        )


def test_registry_accepts_declared_staged_module_and_returns_hash(tmp_path):
    fixture = _fixture(
        tmp_path,
        source='cmd = [sys.executable, "-m", "tools.worker"]\n',
        staged_target=True,
    )

    result = validate_registry(
        **fixture,
        registry_path=_registry(tmp_path, [_worker_entry()]),
    )

    assert result["schema"] == "les.windows-runtime-entrypoint-check.v1"
    assert result["entry_count"] == 1
    assert result["validated_ids"] == ["worker"]
    assert len(result["registry_sha256"]) == 64


def test_registry_rejects_parent_traversal_before_reading_files(tmp_path):
    fixture = _fixture(tmp_path, source="", staged_target=True)
    invalid = _worker_entry()
    invalid["required_files"] = ["../worker.py"]

    with pytest.raises(ValueError, match="unsafe runtime entrypoint path"):
        validate_registry(
            **fixture,
            registry_path=_registry(tmp_path, [invalid]),
        )


def test_checked_in_registry_closes_every_declared_dynamic_callsite(tmp_path):
    root = build_tauri_app.ROOT
    registry_path = root / "installers/windows/runtime-entrypoints.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    staged = tmp_path / "staged"
    for entry in registry["entries"]:
        for relative in [*entry["required_files"], *entry["callsites"]]:
            source = root / relative
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    result = validate_registry(
        root=root,
        staged_root=staged,
        runtime_manifest=root / "config/windows_runtime_manifest.json",
        registry_path=registry_path,
    )

    assert result["entry_count"] == 5
    assert result["validated_ids"] == [
        "fgis-full-update",
        "fgis-update-supervisor",
        "gesn-update-from-fgis",
        "les-shell",
        "uvicorn-runtime",
    ]
