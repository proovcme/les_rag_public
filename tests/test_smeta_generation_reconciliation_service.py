from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path


def test_reconciler_activates_exact_saved_generation_without_rebuilding(
    tmp_path: Path, monkeypatch
):
    service = importlib.import_module(
        "proxy.services.smeta_generation_reconciliation_service"
    )
    base = tmp_path / "data" / "smeta_base" / "les_smeta_base.sqlite"
    base.parent.mkdir(parents=True)
    base.write_bytes(b"current-base")
    base_sha = hashlib.sha256(base.read_bytes()).hexdigest()
    active_manifest = base.with_name("les_smeta_norm_rag_manifest.json")
    active_manifest.write_text(
        json.dumps({"base_sha256": "0" * 64, "physical_generation": "old"}),
        encoding="utf-8",
    )
    generation = tmp_path / "storage" / "smeta_generations" / "matching"
    generation.mkdir(parents=True)
    manifest = generation / "les_smeta_norm_rag_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "smeta_norm_rag_manifest_v2",
                "status": "passed",
                "collection": "les_smeta_norm_cards_matching",
                "expected_points": 2,
                "base_sha256": base_sha,
                "point_embedding_fingerprint": "fp",
            }
        ),
        encoding="utf-8",
    )
    (generation / "les_smeta_norm_rag_readiness.json").write_text(
        json.dumps(
            {
                "schema": "les.smeta.rag-readiness.v1",
                "status": "ready",
                "ready": True,
                "live_rrf_ready": True,
                "collection": "les_smeta_norm_cards_matching",
                "expected_points": 2,
                "base_sha256": base_sha,
            }
        ),
        encoding="utf-8",
    )
    activated: dict[str, object] = {}
    monkeypatch.setattr(service, "activate", lambda **kwargs: activated.update(kwargs))

    result = service.reconcile_matching_generation(
        base_path=base,
        active_manifest_path=active_manifest,
        generations_root=tmp_path / "storage" / "smeta_generations",
        alias="les_smeta_norm_cards",
        client=object(),
        apply=True,
    )

    assert result["status"] == "activated"
    assert result["physical_generation"] == "les_smeta_norm_cards_matching"
    assert activated["target"] == "les_smeta_norm_cards_matching"
    assert activated["manifest_source"] == manifest


def test_reconciler_reports_build_required_without_matching_generation(
    tmp_path: Path, monkeypatch
):
    service = importlib.import_module(
        "proxy.services.smeta_generation_reconciliation_service"
    )
    base = tmp_path / "base.sqlite"
    base.write_bytes(b"current-base")
    active_manifest = tmp_path / "active-rag.json"
    active_manifest.write_text(
        json.dumps({"base_sha256": "0" * 64, "physical_generation": "old"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        service,
        "activate",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not activate")),
    )

    result = service.reconcile_matching_generation(
        base_path=base,
        active_manifest_path=active_manifest,
        generations_root=tmp_path / "generations",
        alias="les_smeta_norm_cards",
        client=object(),
        apply=True,
    )

    assert result["status"] == "build_required"
    assert result["warning_code"] == "SMETA_MATCHING_RAG_GENERATION_NOT_FOUND"


def test_runtime_reconciler_starts_background_build_when_no_saved_match(monkeypatch):
    service = importlib.import_module(
        "proxy.services.smeta_generation_reconciliation_service"
    )
    monkeypatch.setattr(
        service,
        "_runtime_reconciliation_inputs",
        lambda: {
            "base_path": Path("active.sqlite"),
            "active_manifest_path": Path("active-rag.json"),
            "generations_root": Path("generations"),
            "alias": "customer_catalog",
        },
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "reconcile_matching_generation",
        lambda **_kwargs: {"status": "build_required"},
    )
    monkeypatch.setattr(
        service,
        "start_background_rebuild",
        lambda **kwargs: {"status": "building", "alias": kwargs["alias"]},
        raising=False,
    )
    monkeypatch.setattr(service, "QdrantClient", lambda **_kwargs: object())

    result = service.reconcile_runtime_generation(apply=True)

    assert result == {"status": "building", "alias": "customer_catalog"}


def test_reconciler_does_not_trust_matching_manifest_when_alias_is_stale(
    tmp_path: Path, monkeypatch
):
    service = importlib.import_module(
        "proxy.services.smeta_generation_reconciliation_service"
    )
    base = tmp_path / "base.sqlite"
    base.write_bytes(b"base")
    base_sha = hashlib.sha256(base.read_bytes()).hexdigest()
    active_manifest = tmp_path / "active-rag.json"
    active_manifest.write_text(
        json.dumps(
            {
                "base_sha256": base_sha,
                "physical_generation": "matching_generation",
            }
        ),
        encoding="utf-8",
    )
    generation = tmp_path / "generations" / "saved"
    generation.mkdir(parents=True)
    manifest = generation / "les_smeta_norm_rag_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "passed",
                "collection": "matching_generation",
                "base_sha256": base_sha,
            }
        ),
        encoding="utf-8",
    )
    (generation / "les_smeta_norm_rag_readiness.json").write_text(
        json.dumps(
            {
                "schema": "les.smeta.rag-readiness.v1",
                "status": "ready",
                "ready": True,
                "live_rrf_ready": True,
                "collection": "matching_generation",
                "base_sha256": base_sha,
            }
        ),
        encoding="utf-8",
    )
    activated: dict[str, object] = {}
    monkeypatch.setattr(service, "activate", lambda **kwargs: activated.update(kwargs))

    class Client:
        def get_aliases(self):
            class Result:
                aliases = [
                    type(
                        "Alias",
                        (),
                        {"alias_name": "les_smeta_norm_cards", "collection_name": "old"},
                    )()
                ]

            return Result()

    result = service.reconcile_matching_generation(
        base_path=base,
        active_manifest_path=active_manifest,
        generations_root=tmp_path / "generations",
        alias="les_smeta_norm_cards",
        client=Client(),
        apply=True,
    )

    assert result["status"] == "activated"
    assert activated["target"] == "matching_generation"
