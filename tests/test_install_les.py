import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tools import install_les


def test_ensure_dirs_creates_required_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(install_les, "ROOT", tmp_path)

    created = install_les.ensure_dirs()

    assert "data" in created
    assert "RAG_Content" in created
    assert "static" in created
    assert (tmp_path / "data" / "mail_imap_checkpoints").exists()
    assert (tmp_path / "static").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_ensure_dirs_creates_nested_directory_through_windows_state_junction(
    monkeypatch,
):
    programs_root = Path(os.environ["LOCALAPPDATA"]) / "Programs"
    test_root = Path(tempfile.mkdtemp(prefix="LES-junction-test-", dir=programs_root))
    runtime_root = test_root / "runtime"
    state_root = test_root / "state"
    junctions = {
        runtime_root / "artifacts": state_root / "artifacts",
        runtime_root / "storage": state_root / "storage",
    }
    try:
        runtime_root.mkdir()
        for junction, target in junctions.items():
            target.mkdir(parents=True)
            subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(junction), str(target)],
                check=True,
                capture_output=True,
                text=True,
            )
        monkeypatch.setattr(install_les, "ROOT", runtime_root)

        created = install_les.ensure_dirs()

        assert "artifacts/backups" in created
        assert (state_root / "artifacts" / "backups").is_dir()
        assert (state_root / "storage" / "artifacts" / "files").is_dir()
    finally:
        for junction in junctions:
            if junction.is_junction():
                junction.rmdir()
        shutil.rmtree(test_root, ignore_errors=True)


def test_init_env_does_not_overwrite_existing_env(tmp_path, monkeypatch):
    monkeypatch.setattr(install_les, "ROOT", tmp_path)
    (tmp_path / "env.example").write_text("ADMIN_PASSWORD=example\n", encoding="utf-8")
    (tmp_path / ".env").write_text("ADMIN_PASSWORD=real\n", encoding="utf-8")

    result = install_les.init_env()

    assert result == ".env exists"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "ADMIN_PASSWORD=real\n"


def test_init_env_can_create_env(tmp_path, monkeypatch):
    monkeypatch.setattr(install_les, "ROOT", tmp_path)
    (tmp_path / "env.example").write_text("ADMIN_PASSWORD=example\n", encoding="utf-8")

    result = install_les.init_env()

    assert result == ".env created from env.example"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "ADMIN_PASSWORD=example\n"


def test_init_env_honors_persistent_env_path(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    state_env = tmp_path / "state" / ".env"
    runtime.mkdir()
    (runtime / "env.example").write_text("LES_LLM_PROVIDER=ollama\n", encoding="utf-8")
    monkeypatch.setattr(install_les, "ROOT", runtime)
    monkeypatch.setenv("LES_ENV_PATH", str(state_env))

    assert install_les.init_env() == ".env created from env.example"
    assert state_env.read_text(encoding="utf-8") == "LES_LLM_PROVIDER=ollama\n"
    assert not (runtime / ".env").exists()


def test_profile_checks_include_profile_result():
    checks = install_les.build_profile_checks("server-remote-model")

    assert any(check.name == "profile" and check.ok for check in checks)
    assert any(check.name == "remote-model" and check.ok for check in checks)
