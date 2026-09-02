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


def test_reconciler_repairs_exact_saved_metadata_after_interrupted_file_switch(
    tmp_path: Path, monkeypatch
):
    service = importlib.import_module(
        "proxy.services.smeta_generation_reconciliation_service"
    )
    base = tmp_path / "renamed active" / "customer.sqlite"
    base.parent.mkdir()
    base.write_bytes(b"new-base")
    base_sha = hashlib.sha256(base.read_bytes()).hexdigest()
    active_base_manifest = tmp_path / "custom metadata" / "active-manifest.json"
    active_integrity = tmp_path / "custom metadata" / "active-integrity.json"
    active_base_manifest.parent.mkdir()
    active_base_manifest.write_text('{"output":{"sha256":"old"}}', encoding="utf-8")
    active_integrity.write_text(
        '{"verdict":"passed","base_sha256":"old"}', encoding="utf-8"
    )
    active_rag_manifest = base.with_name("active-rag.json")
    active_rag_manifest.write_text('{"base_sha256":"old"}', encoding="utf-8")
    generation = tmp_path / "generations" / "saved"
    generation.mkdir(parents=True)
    saved_base_manifest = generation / "les_smeta_base_manifest.json"
    saved_integrity = generation / "les_smeta_base_integrity.json"
    saved_base_manifest.write_text(
        json.dumps({"output": {"sha256": base_sha}}), encoding="utf-8"
    )
    saved_integrity.write_text(
        json.dumps(
            {
                "schema": "les_smeta_base_integrity_v1",
                "verdict": "passed",
                "base_sha256": base_sha,
            }
        ),
        encoding="utf-8",
    )
    rag_manifest = generation / "les_smeta_norm_rag_manifest.json"
    rag_manifest.write_text(
        json.dumps(
            {
                "status": "passed",
                "collection": "renamed_catalog_generation",
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
                "collection": "renamed_catalog_generation",
                "base_sha256": base_sha,
            }
        ),
        encoding="utf-8",
    )

    def activate_after_metadata_recovery(**_kwargs):
        assert json.loads(active_base_manifest.read_text(encoding="utf-8"))[
            "output"
        ]["sha256"] == base_sha
        assert json.loads(active_integrity.read_text(encoding="utf-8"))[
            "base_sha256"
        ] == base_sha

    monkeypatch.setattr(service, "activate", activate_after_metadata_recovery)

    result = service.reconcile_matching_generation(
        base_path=base,
        active_base_manifest_path=active_base_manifest,
        active_integrity_path=active_integrity,
        active_manifest_path=active_rag_manifest,
        generations_root=tmp_path / "generations",
        alias="renamed_catalog",
        client=object(),
        apply=True,
    )

    assert result["status"] == "activated"
    assert result["metadata_recovered"] is True


def test_reconciler_blocks_corrupt_saved_metadata_without_overwriting_active_files(
    tmp_path: Path, monkeypatch
):
    service = importlib.import_module(
        "proxy.services.smeta_generation_reconciliation_service"
    )
    base = tmp_path / "base.sqlite"
    base.write_bytes(b"base")
    base_sha = hashlib.sha256(base.read_bytes()).hexdigest()
    active_base_manifest = tmp_path / "active-base.json"
    active_integrity = tmp_path / "active-integrity.json"
    active_rag = tmp_path / "active-rag.json"
    active_base_manifest.write_text('{"old":true}', encoding="utf-8")
    active_integrity.write_text('{"old":true}', encoding="utf-8")
    active_rag.write_text('{"base_sha256":"old"}', encoding="utf-8")
    generation = tmp_path / "generations" / "saved"
    generation.mkdir(parents=True)
    (generation / "les_smeta_base_manifest.json").write_text(
        json.dumps({"output": {"sha256": "wrong"}}), encoding="utf-8"
    )
    (generation / "les_smeta_base_integrity.json").write_text(
        json.dumps({"verdict": "failed", "base_sha256": base_sha}),
        encoding="utf-8",
    )
    (generation / "les_smeta_norm_rag_manifest.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "collection": "candidate",
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
                "collection": "candidate",
                "base_sha256": base_sha,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        service,
        "activate",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("corrupt saved metadata must not activate")
        ),
    )

    result = service.reconcile_matching_generation(
        base_path=base,
        active_base_manifest_path=active_base_manifest,
        active_integrity_path=active_integrity,
        active_manifest_path=active_rag,
        generations_root=tmp_path / "generations",
        alias="catalog",
        client=object(),
        apply=True,
    )

    assert result["status"] == "blocked"
    assert result["warning_code"] == "SMETA_SAVED_BASE_METADATA_INVALID"
    assert json.loads(active_base_manifest.read_text(encoding="utf-8")) == {
        "old": True
    }
    assert json.loads(active_integrity.read_text(encoding="utf-8")) == {"old": True}
