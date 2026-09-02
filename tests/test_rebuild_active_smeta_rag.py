from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path


def test_active_rebuild_builds_exact_base_then_activates_alias(tmp_path: Path, monkeypatch):
    rebuild = importlib.import_module("tools.rebuild_active_smeta_rag")
    base = tmp_path / "les_smeta_base.sqlite"
    base.write_bytes(b"active-base")
    base_sha = hashlib.sha256(base.read_bytes()).hexdigest()
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        calls["build"] = kwargs
        kwargs["manifest_path"].write_text(
            json.dumps(
                {
                    "schema": "smeta_norm_rag_manifest_v2",
                    "status": "passed",
                    "collection": kwargs["collection"],
                    "expected_points": 3,
                    "base_sha256": base_sha,
                    "point_embedding_fingerprint": "fp",
                }
            ),
            encoding="utf-8",
        )
        return {"status": "passed"}

    monkeypatch.setattr(rebuild, "build_rag_generation", fake_build)
    monkeypatch.setattr(
        rebuild,
        "run_readiness_gate",
        lambda **kwargs: {
            "schema": "les.smeta.rag-readiness.v1",
            "status": "ready",
            "ready": True,
            "live_rrf_ready": True,
            "collection": kwargs["collection"],
            "expected_points": 3,
            "base_sha256": base_sha,
        },
    )
    monkeypatch.setattr(rebuild, "activate", lambda **kwargs: calls.update(activate=kwargs))
    monkeypatch.setattr(rebuild, "qdrant_client", lambda: object())

    result = rebuild.rebuild_active_index(
        base_path=base,
        alias="customer_catalog",
        generations_root=tmp_path / "generations",
        active_manifest_path=tmp_path / "active-rag.json",
    )

    assert result["status"] == "activated"
    assert calls["build"]["base_path"] == base
    assert calls["activate"]["target"] == f"customer_catalog_{base_sha[:20]}"
    assert calls["activate"]["manifest_destinations"] == [tmp_path / "active-rag.json"]
