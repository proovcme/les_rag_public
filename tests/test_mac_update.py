from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from proxy.services import update_service
from tools import mac_update, mac_update_apply


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _prepared_update(tmp_path: Path, *, current: bytes, target: bytes) -> tuple[Path, Path, dict]:
    runtime = tmp_path / "runtime"
    update_root = tmp_path / "updates"
    runtime_file = runtime / "proxy" / "example.py"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_bytes(current)
    update_root.mkdir()
    manifest = {
        "schema": "les.mac-update.v1",
        "update_id": "unit-update",
        "branch": "codex/audit-rag",
        "base_commit": "a" * 40,
        "target_commit": "b" * 40,
        "product_version": "0.25.4",
        "build_number": 477,
        "services": [],
        "files": [
            {
                "operation": "replace",
                "path": "proxy/example.py",
                "base_sha256": _sha(current),
                "accepted_missing": False,
                "sha256": _sha(target),
                "bytes": len(target),
            }
        ],
    }
    archive = update_root / "unit-update.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
        bundle.writestr("payload/proxy/example.py", target)
    helper = update_root / "mac_update_apply.py"
    helper.write_bytes(Path(mac_update_apply.__file__).read_bytes())
    feed = {
        "schema": "les.mac-update-feed.v1",
        "update": manifest,
        "archive": str(archive),
        "archive_sha256": update_service.sha256_file(archive),
        "archive_bytes": archive.stat().st_size,
        "helper": str(helper),
        "helper_sha256": update_service.sha256_file(helper),
        "published": False,
    }
    (update_root / "latest.json").write_text(json.dumps(feed), encoding="utf-8")
    return runtime, update_root, feed


def _job(tmp_path: Path, runtime: Path, update_root: Path, feed: dict) -> Path:
    job = tmp_path / "job.json"
    job.write_text(
        json.dumps(
            {
                "runtime_root": str(runtime),
                "archive": feed["archive"],
                "archive_sha256": feed["archive_sha256"],
                "status_path": str(update_root / "status.json"),
                "recovery_root": str(tmp_path / "recovery"),
            }
        ),
        encoding="utf-8",
    )
    return job


def test_mac_feed_validates_archive_helper_allowlist_and_runtime_base(tmp_path, monkeypatch):
    runtime, update_root, feed = _prepared_update(
        tmp_path, current=b"old\n", target=b"new\n"
    )
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    monkeypatch.setattr(update_service, "mac_update_root", lambda: update_root)

    info = update_service._validate_mac_update_feed(feed)

    assert info["available"] is True
    assert info["compatible"] is True
    assert info["files"] == 1
    assert info["published"] is False

    feed["update"]["files"][0]["path"] = "data/private.db"
    with pytest.raises(update_service.UpdateError, match="пользовательские данные"):
        update_service._validate_mac_update_feed(feed)


def test_mac_builder_excludes_repo_docs_desktop_and_user_state():
    assert mac_update.normalize_path("proxy/services/example.py") == "proxy/services/example.py"
    for path in ("docs/README.md", "desktop/app.json", "data/private.db", ".env"):
        with pytest.raises(ValueError):
            mac_update.normalize_path(path)


def test_mac_helper_applies_atomically_and_keeps_recovery_copy(tmp_path, monkeypatch):
    runtime, update_root, feed = _prepared_update(
        tmp_path, current=b"old\n", target=b"new\n"
    )
    monkeypatch.setattr(mac_update_apply, "_restart", lambda _services: None)
    monkeypatch.setattr(mac_update_apply, "_wait_ready", lambda _manifest: None)

    result = mac_update_apply.apply_job(_job(tmp_path, runtime, update_root, feed))
    status = json.loads((update_root / "status.json").read_text(encoding="utf-8"))

    assert result == 0
    assert (runtime / "proxy" / "example.py").read_bytes() == b"new\n"
    assert status["state"] == "ready"
    backup = Path(status["backup_root"])
    assert (backup / "files" / "proxy" / "example.py").read_bytes() == b"old\n"


def test_mac_helper_rolls_back_when_smoke_fails(tmp_path, monkeypatch):
    runtime, update_root, feed = _prepared_update(
        tmp_path, current=b"old\n", target=b"broken\n"
    )
    monkeypatch.setattr(mac_update_apply, "_restart", lambda _services: None)
    monkeypatch.setattr(
        mac_update_apply,
        "_wait_ready",
        lambda _manifest: (_ for _ in ()).throw(RuntimeError("smoke failed")),
    )
    monkeypatch.setattr(
        mac_update_apply.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline test")),
    )

    result = mac_update_apply.apply_job(_job(tmp_path, runtime, update_root, feed))
    status = json.loads((update_root / "status.json").read_text(encoding="utf-8"))

    assert result == 1
    assert (runtime / "proxy" / "example.py").read_bytes() == b"old\n"
    assert status["state"] == "failed"
    assert "smoke failed" in status["error"]
