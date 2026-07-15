from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile

import httpx
import pytest

from proxy.services import update_service
from tools import vps_patch
from tools import vps_patch_apply


def test_patch_allowlist_rejects_runtime_boundaries():
    assert vps_patch.normalize_path("proxy/services/example.py") == "proxy/services/example.py"
    with pytest.raises(ValueError, match="allowlist|denied"):
        vps_patch.normalize_path("pyproject.toml")
    with pytest.raises(ValueError, match="denied"):
        vps_patch.normalize_path("installers/windows/start-light.ps1")
    with pytest.raises(ValueError, match="unsafe"):
        vps_patch.normalize_path("../outside.py")


def test_build_patch_contains_only_manifest_and_declared_payload(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    path = repo / "proxy" / "x.py"
    path.parent.mkdir()
    path.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    path.write_text("VALUE = 2\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "target"], cwd=repo, check=True)
    target = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    original = vps_patch.ROOT
    vps_patch.ROOT = repo
    try:
        result = vps_patch.build_patch(base=base, target=target, files=["proxy/x.py"], output=tmp_path / "out", origin="https://les.ovc.me/updates")
    finally:
        vps_patch.ROOT = original
    with zipfile.ZipFile(result["archive"]) as bundle:
        assert set(bundle.namelist()) == {"manifest.json", "payload/proxy/x.py"}
        manifest = json.loads(bundle.read("manifest.json"))
    assert manifest["base_commit"] == base
    assert manifest["target_commit"] == target
    assert manifest["files"][0]["base_sha256"] == hashlib.sha256(b"VALUE = 1\r\n").hexdigest()
    assert hashlib.sha256(b"VALUE = 1\r\n").hexdigest() in manifest["files"][0]["accepted_sha256"]
    assert hashlib.sha256(b"VALUE = 2\n").hexdigest() in manifest["files"][0]["accepted_sha256"]
    assert result["archive_sha256"] == vps_patch.sha256_file(result["archive"])


def test_patch_feed_requires_matching_base_hashes(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    target = runtime / "proxy" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    before = hashlib.sha256(b"before").hexdigest()
    after = hashlib.sha256(b"after").hexdigest()
    payload = {
        "schema": update_service.VPS_PATCH_FEED_SCHEMA,
        "archive_url": "https://les.ovc.me/updates/p.zip",
        "archive_sha256": "a" * 64,
        "patch": {
            "schema": update_service.VPS_PATCH_SCHEMA,
            "patch_id": "p1",
            "base_commit": "b" * 40,
            "target_commit": "c" * 40,
            "files": [{"path": "proxy/x.py", "base_sha256": before, "sha256": after, "bytes": 5}],
        },
    }
    result = update_service._validate_patch_feed(payload)
    assert result["available"] is True
    assert result["compatible"] is True
    target.write_bytes(b"foreign")
    assert update_service._validate_patch_feed(payload)["compatible"] is False


def test_cumulative_patch_accepts_mixed_base_and_already_updated_files(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    first = runtime / "proxy" / "first.py"
    second = runtime / "proxy" / "second.py"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"after-one")
    second.write_bytes(b"before-two")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    entries = [
        {
            "path": "proxy/first.py",
            "base_sha256": hashlib.sha256(b"before-one").hexdigest(),
            "sha256": hashlib.sha256(b"after-one").hexdigest(),
            "bytes": 9,
        },
        {
            "path": "proxy/second.py",
            "base_sha256": hashlib.sha256(b"before-two").hexdigest(),
            "sha256": hashlib.sha256(b"after-two").hexdigest(),
            "bytes": 9,
        },
    ]
    payload = {
        "schema": update_service.VPS_PATCH_FEED_SCHEMA,
        "archive_url": "https://les.ovc.me/updates/cumulative.zip",
        "archive_sha256": "a" * 64,
        "patch": {
            "schema": update_service.VPS_PATCH_SCHEMA,
            "patch_id": "cumulative",
            "base_commit": "b" * 40,
            "target_commit": "c" * 40,
            "files": entries,
        },
    }
    result = update_service._validate_patch_feed(payload)
    assert result["available"] is True
    assert result["compatible"] is True


def test_cumulative_patch_accepts_an_exact_intermediate_release_state(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    target = runtime / "proxy" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"intermediate")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    hashes = {
        name: hashlib.sha256(value).hexdigest()
        for name, value in {
            "base": b"base",
            "intermediate": b"intermediate",
            "target": b"target",
        }.items()
    }
    entry = {
        "path": "proxy/x.py",
        "base_sha256": hashes["base"],
        "accepted_sha256": list(hashes.values()),
        "sha256": hashes["target"],
        "bytes": 6,
    }
    payload = {
        "schema": update_service.VPS_PATCH_FEED_SCHEMA,
        "archive_url": "https://les.ovc.me/updates/cumulative.zip",
        "archive_sha256": "a" * 64,
        "patch": {
            "schema": update_service.VPS_PATCH_SCHEMA,
            "patch_id": "cumulative-intermediate",
            "base_commit": "b" * 40,
            "target_commit": "c" * 40,
            "files": [entry],
        },
    }
    assert update_service._validate_patch_feed(payload)["compatible"] is True
    assert vps_patch_apply.entry_accepts_current(entry, hashes["intermediate"]) is True
    assert vps_patch_apply.entry_accepts_current(entry, hashlib.sha256(b"foreign").hexdigest()) is False


def test_patch_helper_is_launched_as_independent_interactive_task(tmp_path):
    helper = tmp_path / "vps patch apply.py"
    job = tmp_path / "job file.json"
    task_name, encoded = update_service._patch_task_command(helper, job, "patch:one")
    command = __import__("base64").b64decode(encoded).decode("utf-16le")
    assert task_name == "LES-Patch-patch-one"
    assert "New-ScheduledTaskPrincipal" in command
    assert "-LogonType Interactive" in command
    assert str(helper) in command
    assert str(job) in command


@pytest.mark.asyncio
async def test_patch_check_uses_only_les_https_origin(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    file = runtime / "proxy" / "x.py"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"before")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    payload = {
        "schema": update_service.VPS_PATCH_FEED_SCHEMA,
        "archive_url": "https://les.ovc.me/updates/p.zip",
        "archive_sha256": "a" * 64,
        "patch": {
            "schema": update_service.VPS_PATCH_SCHEMA,
            "patch_id": "p1",
            "base_commit": "b" * 40,
            "target_commit": "c" * 40,
            "files": [{"path": "proxy/x.py", "base_sha256": hashlib.sha256(b"before").hexdigest(), "sha256": hashlib.sha256(b"after").hexdigest(), "bytes": 5}],
        },
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload, request=request))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await update_service.check_vps_patch(client=client)
    assert result["patch_id"] == "p1"
    assert update_service._trusted_patch_url("https://example.invalid/updates/p.zip") is False


@pytest.mark.asyncio
async def test_patch_archive_download_accepts_only_vps_origin(tmp_path):
    target = tmp_path / "patch.zip"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"patch", request=request))
    async with httpx.AsyncClient(transport=transport) as client:
        await update_service._download(
            client,
            "https://les.ovc.me/updates/p.zip",
            target,
            max_bytes=64,
            trusted_url=update_service._trusted_patch_url,
        )
        with pytest.raises(update_service.UpdateError, match="недоверенный"):
            await update_service._download(
                client,
                "https://example.invalid/updates/p.zip",
                target,
                max_bytes=64,
                trusted_url=update_service._trusted_patch_url,
            )
    assert target.read_bytes() == b"patch"
