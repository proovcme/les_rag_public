from __future__ import annotations

import hashlib

import pytest

from tools import onboard_reranker


def test_configured_model_defaults_to_multilingual_bge(monkeypatch):
    monkeypatch.delenv("RERANK_MODEL", raising=False)
    assert onboard_reranker.configured_model() == "BAAI/bge-reranker-v2-m3"


def test_configured_model_honours_explicit_override(monkeypatch):
    monkeypatch.setenv("RERANK_MODEL", "org/custom-reranker")
    assert onboard_reranker.configured_model() == "org/custom-reranker"


def test_download_model_retries_configured_mirror(monkeypatch):
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("official unavailable")

    monkeypatch.setenv("HF_MIRROR_ENDPOINT", "https://mirror.example")
    onboard_reranker.download_model(download, "org/model")

    assert calls == [
        {"repo_id": "org/model", "etag_timeout": 20},
        {"repo_id": "org/model", "endpoint": "https://mirror.example", "etag_timeout": 20},
    ]


def test_download_model_force_flag_reaches_official_and_mirror(monkeypatch):
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("official unavailable")
        return "/snapshot"

    monkeypatch.setenv("HF_MIRROR_ENDPOINT", "https://mirror.example")
    assert onboard_reranker.download_model(download, "org/model", force_download=True) == "/snapshot"
    assert all(call["force_download"] is True for call in calls)


def test_verify_snapshot_rejects_corrupt_published_weights(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"correct")
    expected = hashlib.sha256(b"correct").hexdigest()
    monkeypatch.setitem(
        onboard_reranker.EXPECTED_WEIGHTS,
        "org/model",
        {"model.safetensors": expected},
    )

    assert onboard_reranker.verify_snapshot(tmp_path, "org/model") == {
        "model.safetensors": expected
    }
    weights.write_bytes(b"corrupt")
    with pytest.raises(onboard_reranker.ModelIntegrityError, match="checksum mismatch"):
        onboard_reranker.verify_snapshot(tmp_path, "org/model")


def test_quarantine_removes_corrupt_weight_from_published_name(tmp_path, monkeypatch):
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"bad")
    monkeypatch.setitem(
        onboard_reranker.EXPECTED_WEIGHTS,
        "org/model",
        {"model.safetensors": "expected"},
    )

    quarantined = onboard_reranker.quarantine_corrupt_weights(tmp_path, "org/model")

    assert not weights.exists()
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"bad"


def test_verification_marker_skips_rehash_only_while_file_identity_matches(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"verified")
    expected = hashlib.sha256(b"verified").hexdigest()
    monkeypatch.setitem(
        onboard_reranker.EXPECTED_WEIGHTS,
        "org/model",
        {"model.safetensors": expected},
    )
    checked = onboard_reranker.verify_snapshot(tmp_path, "org/model")
    onboard_reranker.write_verification_marker(tmp_path, "org/model", checked)

    assert onboard_reranker.verification_marker_valid(tmp_path, "org/model") is True
    weights.write_bytes(b"modified")
    assert onboard_reranker.verification_marker_valid(tmp_path, "org/model") is False
