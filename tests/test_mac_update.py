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


def test_mac_feed_accepts_only_explicit_full_hash_from_previous_deploy_stamp(
    tmp_path, monkeypatch
):
    runtime, update_root, feed = _prepared_update(
        tmp_path, current=b"partial-restored\n", target=b"new\n"
    )
    current_hash = _sha(b"partial-restored\n")
    feed["update"]["files"][0]["base_sha256"] = _sha(b"declared-base\n")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    monkeypatch.setattr(update_service, "mac_update_root", lambda: update_root)

    blocked = update_service._validate_mac_update_feed(feed)
    assert blocked["compatible"] is False

    feed["update"]["files"][0]["accepted_sha256"] = [current_hash]
    accepted = update_service._validate_mac_update_feed(feed)
    assert accepted["compatible"] is True


def test_mac_builder_excludes_repo_docs_desktop_and_user_state():
    assert mac_update.normalize_path("proxy/services/example.py") == "proxy/services/example.py"
    for path in ("docs/README.md", "desktop/app.json", "data/private.db", ".env"):
        with pytest.raises(ValueError):
            mac_update.normalize_path(path)


def test_mac_update_carries_qdrant_visualizer_static_runtime_only():
    visualizer = "qdrant_visualizer/index.html"

    assert mac_update.normalize_path(visualizer) == visualizer
    assert mac_update_apply.safe_relative_path(visualizer).as_posix() == visualizer
    assert "qdrant_visualizer/" in update_service.MAC_UPDATE_ALLOWED_ROOTS
    assert {".html", ".css", ".js"} <= mac_update.ALLOWED_SUFFIXES
    assert {".html", ".css", ".js"} <= mac_update_apply.ALLOWED_SUFFIXES
    assert {".html", ".css", ".js"} <= update_service.MAC_UPDATE_ALLOWED_SUFFIXES


def test_mac_update_branch_is_explicit_and_rejects_git_ref_syntax():
    assert mac_update._configured_branch("codex/sovushka-ui-kit") == (
        "codex/sovushka-ui-kit"
    )
    for branch in ("main", "codex/../main", "codex/ui//next", "codex/ui^"):
        with pytest.raises(RuntimeError, match=r"safe codex/\* branch"):
            mac_update._configured_branch(branch)


def test_stale_one_time_reconciliation_does_not_block_later_file_update(
    tmp_path, monkeypatch
):
    runtime = tmp_path / "runtime"
    runtime_file = runtime / "sovushka" / "styles.py"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_bytes(b"already-reconciled\n")
    accepted_hash = _sha(b"historical-drift\n")
    stale_target_hash = _sha(b"old-target\n")
    payload = {
        "schema": mac_update.RECONCILIATION_SCHEMA,
        "entries": [{
            "path": "sovushka/styles.py",
            "accepted_sha256": accepted_hash,
            "target_sha256": stale_target_hash,
        }],
    }

    def fake_git_bytes(_target: str, path: str):
        if path == mac_update.RECONCILIATION_PATH:
            return json.dumps(payload).encode()
        if path == "sovushka/styles.py":
            return b"new-target\n"
        return None

    monkeypatch.setattr(mac_update, "git_bytes", fake_git_bytes)

    accepted, forced = mac_update._committed_reconciliation(runtime, "target")

    assert accepted == {}
    assert forced == set()


def test_active_reconciliation_still_validates_exact_target(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime_file = runtime / "sovushka" / "styles.py"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_bytes(b"historical-drift\n")
    payload = {
        "schema": mac_update.RECONCILIATION_SCHEMA,
        "entries": [{
            "path": "sovushka/styles.py",
            "accepted_sha256": _sha(b"historical-drift\n"),
            "target_sha256": _sha(b"old-target\n"),
        }],
    }

    def fake_git_bytes(_target: str, path: str):
        if path == mac_update.RECONCILIATION_PATH:
            return json.dumps(payload).encode()
        if path == "sovushka/styles.py":
            return b"new-target\n"
        return None

    monkeypatch.setattr(mac_update, "git_bytes", fake_git_bytes)

    with pytest.raises(RuntimeError, match="invalid committed reconciliation"):
        mac_update._committed_reconciliation(runtime, "target")


def test_mac_stamp_keeps_untouched_owned_hashes_and_updates_changed_file(tmp_path):
    runtime = tmp_path / "runtime"
    changed = runtime / "proxy" / "example.py"
    changed.parent.mkdir(parents=True)
    changed.write_bytes(b"new\n")
    manifest = {
        "update_id": "unit",
        "branch": "codex/audit-rag",
        "target_commit": "b" * 40,
        "product_version": "0.25.4",
        "build_number": 477,
        "files": [{"path": "proxy/example.py", "operation": "replace"}],
    }
    previous = {
        "file_hash_bundle": {
            "sovushka/styles.py": "d8c9c495140ecd28",
            "proxy/example.py": "old",
        }
    }

    stamp = mac_update_apply._stamp(manifest, runtime, previous)

    assert stamp["file_hash_bundle"]["sovushka/styles.py"] == "d8c9c495140ecd28"
    assert stamp["file_hash_bundle"]["proxy/example.py"] == _sha(b"new\n")[:16]


def test_mac_helper_applies_atomically_and_keeps_recovery_copy(tmp_path, monkeypatch):
    runtime, update_root, feed = _prepared_update(
        tmp_path, current=b"old\n", target=b"new\n"
    )
    (runtime / ".les_deploy_stamp.json").write_text(
        json.dumps({"file_hash_bundle": {"sovushka/styles.py": "owned-prefix"}}),
        encoding="utf-8",
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
    assert (backup / "previous_deploy_stamp.json").is_file()
    installed_stamp = json.loads(
        (runtime / ".les_deploy_stamp.json").read_text(encoding="utf-8")
    )
    assert installed_stamp["file_hash_bundle"]["sovushka/styles.py"] == "owned-prefix"


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
