import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from backend.runtime_paths import MutablePathError, mutable_path


def test_windows_state_root_owns_registered_mutable_path(tmp_path, monkeypatch):
    monkeypatch.setenv("LES_WINDOWS_STATE_ROOT", str(tmp_path / "state"))

    assert mutable_path("storage/artifacts/files") == (
        tmp_path / "state" / "storage" / "artifacts" / "files"
    )


def test_unknown_mutable_root_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("LES_WINDOWS_STATE_ROOT", str(tmp_path / "state"))

    with pytest.raises(MutablePathError, match="registered mutable root"):
        mutable_path("scratch/result.json")


def test_absolute_input_is_rejected(tmp_path):
    with pytest.raises(MutablePathError, match="relative"):
        mutable_path(Path(tmp_path) / "outside")


def test_repository_runtime_preserves_relative_path(monkeypatch):
    monkeypatch.delenv("LES_WINDOWS_STATE_ROOT", raising=False)

    assert mutable_path("logs/proxy.log") == Path("logs/proxy.log")


def test_proxy_meta_db_uses_direct_windows_state_root(tmp_path):
    state_root = tmp_path / "state"
    env = os.environ.copy()
    env["LES_WINDOWS_STATE_ROOT"] = str(state_root)
    env["LES_EMBED_PROFILE"] = "qwen"
    env.pop("RAG_META_DB_PATH", None)
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; from proxy.config import DATA_DIR, META_DB_PATH; "
                "from backend.rag_config import rag_meta_db_path; "
                "from proxy.services.job_service import JobService; JobService(); "
                "print(json.dumps({'data': str(DATA_DIR), 'meta': str(META_DB_PATH), "
                "'rag_meta': rag_meta_db_path(), 'meta_exists': META_DB_PATH.exists()}))"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(probe.stdout)

    assert Path(payload["data"]) == state_root / "data"
    assert Path(payload["meta"]) == state_root / "data" / "les_meta.db"
    assert Path(payload["rag_meta"]) == state_root / "data" / "les_meta_qwen.db"
    assert payload["meta_exists"] is True
