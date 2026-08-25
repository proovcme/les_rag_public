from __future__ import annotations

import hashlib

import httpx
import pytest

from proxy.services import update_service


def _release(version: str = "0.24.0.405") -> dict:
    return {
        "schema": "les.update.v1",
        "version": version,
        "name": f"LES {version}",
        "notes": "Изменения",
        "build_number": 405,
        "desktop_version": "5.1.405",
        "commit": "a" * 40,
    }


def test_release_summary_requires_newer_complete_package(monkeypatch):
    monkeypatch.setattr(update_service.sys, "platform", "win32")
    result = update_service.release_summary(_release(), current_version="0.24.0.404")
    assert result["available"] is True
    assert result["package_complete"] is True
    assert result["install_supported"] is True
    assert result["build_number"] == 405
    assert result["target_commit"] == "a" * 40


def test_release_summary_marks_release_without_exact_identity_incomplete():
    payload = _release()
    payload.pop("commit")
    assert update_service.release_summary(
        payload, current_version="0.24.0.404"
    )["package_complete"] is False


def test_release_summary_does_not_downgrade():
    result = update_service.release_summary(_release("0.24.0.403"), current_version="0.24.0.404")
    assert result["available"] is False


def test_release_summary_rejects_unknown_manifest_schema():
    payload = _release()
    payload["schema"] = "unknown"
    with pytest.raises(update_service.UpdateError, match="схема"):
        update_service.release_summary(payload, current_version="0.24.0.404")


def test_parse_checksum_and_file_hash(tmp_path):
    payload = b"verified installer"
    path = tmp_path / "LES-Setup.exe"
    path.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    assert update_service.parse_checksum(f"{expected}  LES-Setup.exe\n") == expected
    assert update_service.sha256_file(path) == expected


def test_untrusted_download_url_is_rejected():
    assert update_service._trusted_release_url("https://github.com/o/r/file") is True
    assert update_service._trusted_release_url("https://example.invalid/file") is False


def test_default_patch_feed_is_exact_public_github_release():
    assert update_service.GITHUB_PATCH_MANIFEST_URL == (
        "https://github.com/proovcme/les_rag_public/"
        "releases/latest/download/les-update.json"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.invalid/releases/latest/download/les-update.json",
        "http://github.com/proovcme/les_rag_public/releases/latest/download/les-update.json",
        "https://github.com/other/les_rag_public/releases/latest/download/les-update.json",
        "https://github.com/proovcme/les_rag_public/releases/download/v0.28.2/les-update.json",
    ],
)
def test_foreign_insecure_or_non_latest_update_feed_is_rejected(url):
    assert update_service._trusted_github_update_url(url) is False


def test_only_tag_specific_patch_asset_is_trusted():
    assert update_service._trusted_github_update_url(
        "https://github.com/proovcme/les_rag_public/releases/download/v0.28.2/les-patch.zip",
        asset=True,
    )
    assert not update_service._trusted_github_update_url(
        "https://github.com/proovcme/les_rag_public/releases/latest/download/les-patch.zip",
        asset=True,
    )


@pytest.mark.asyncio
async def test_check_update_reads_only_latest_release_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json=_release(), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await update_service.check_update(client=client)
    assert result["latest_version"] == "0.24.0.405"
