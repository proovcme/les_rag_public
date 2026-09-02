from __future__ import annotations

import importlib
import hashlib
import json
from pathlib import Path

import pytest


def test_generation_coordinator_activates_only_staged_sqlite_and_matching_rag(
    tmp_path: Path, monkeypatch
):
    coordinator = importlib.import_module("tools.smeta_generation_coordinator")
    source = tmp_path / "unified.parquet"
    source.write_bytes(b"source")
    active = tmp_path / "active"
    active.mkdir()
    active_base = active / "les_smeta_base.sqlite"
    active_base.write_bytes(b"old-base")
    calls: dict[str, object] = {}

    def fake_structured(**kwargs):
        assert kwargs["out"] != active_base
        kwargs["out"].write_bytes(b"new-base")
        kwargs["manifest_out"].write_text('{"base": "new"}', encoding="utf-8")
        kwargs["integrity_out"].write_text('{"verdict": "passed"}', encoding="utf-8")
        return {
            "output": {
                "sha256": hashlib.sha256(b"new-base").hexdigest(),
                "norms": 2,
            }
        }

    def fake_rag(**kwargs):
        calls["rag_base"] = kwargs["base_path"]
        kwargs["manifest_path"].write_text(
            json.dumps(
                {
                    "schema": "smeta_norm_rag_manifest_v2",
                    "status": "passed",
                    "collection": kwargs["collection"],
                    "expected_points": 2,
                    "base_sha256": hashlib.sha256(b"new-base").hexdigest(),
                    "point_embedding_fingerprint": "fp",
                }
            ),
            encoding="utf-8",
        )
        return {"status": "passed", "collection": kwargs["collection"]}

    monkeypatch.setattr(coordinator, "build_structured_base", fake_structured)
    monkeypatch.setattr(coordinator, "build_rag_generation", fake_rag)
    monkeypatch.setattr(
        coordinator,
        "run_readiness_gate",
        lambda **kwargs: {
            "schema": "les.smeta.rag-readiness.v1",
            "status": "ready",
            "ready": True,
            "live_rrf_ready": True,
            "collection": kwargs["collection"],
            "expected_points": 2,
            "base_sha256": hashlib.sha256(b"new-base").hexdigest(),
        },
    )

    def fake_activate(**kwargs):
        calls["activation"] = kwargs

    monkeypatch.setattr(coordinator, "activate_release", fake_activate)
    monkeypatch.setattr(coordinator, "qdrant_client", lambda: object())

    result = coordinator.publish_generation(
        source=source,
        active_base=active_base,
        active_base_manifest=active / "les_smeta_base_manifest.json",
        active_integrity=active / "les_smeta_base_integrity.json",
        active_rag_manifest=active / "les_smeta_norm_rag_manifest.json",
        generations_root=tmp_path / "generations",
        alias="customer_norm_catalog",
        minimum_norms=1,
    )

    activation = calls["activation"]
    staged_base = calls["rag_base"]
    assert result["status"] == "activated"
    assert result["collection"].startswith("customer_norm_catalog_")
    assert staged_base != active_base
    assert (staged_base, active_base) in activation["artifact_pairs"]
    assert activation["target"] == result["collection"]


def test_generation_coordinator_keeps_active_base_when_readiness_is_blocked(
    tmp_path: Path, monkeypatch
):
    coordinator = importlib.import_module("tools.smeta_generation_coordinator")
    source = tmp_path / "unified.parquet"
    source.write_bytes(b"source")
    active_base = tmp_path / "active.sqlite"
    active_base.write_bytes(b"old-base")

    def fake_structured(**kwargs):
        kwargs["out"].write_bytes(b"new-base")
        kwargs["manifest_out"].write_text("{}", encoding="utf-8")
        kwargs["integrity_out"].write_text("{}", encoding="utf-8")
        return {
            "output": {
                "sha256": hashlib.sha256(b"new-base").hexdigest(),
                "norms": 2,
            }
        }

    def fake_rag(**kwargs):
        kwargs["manifest_path"].write_text("{}", encoding="utf-8")
        return {"status": "passed"}

    monkeypatch.setattr(coordinator, "build_structured_base", fake_structured)
    monkeypatch.setattr(coordinator, "build_rag_generation", fake_rag)
    monkeypatch.setattr(
        coordinator,
        "run_readiness_gate",
        lambda **_kwargs: {"status": "blocked", "ready": False},
    )
    monkeypatch.setattr(
        coordinator,
        "activate_release",
        lambda **_kwargs: pytest.fail("blocked generation must not activate"),
    )

    with pytest.raises(RuntimeError, match="readiness"):
        coordinator.publish_generation(
            source=source,
            active_base=active_base,
            active_base_manifest=tmp_path / "active-manifest.json",
            active_integrity=tmp_path / "active-integrity.json",
            active_rag_manifest=tmp_path / "active-rag.json",
            generations_root=tmp_path / "generations",
            alias="les_smeta_norm_cards",
            minimum_norms=1,
        )

    assert active_base.read_bytes() == b"old-base"
