import json
from types import SimpleNamespace

import pytest

from tools.activate_smeta_rag_generation import (
    activate,
    read_smeta_ready_report,
    verify_smeta_target,
)


def test_smeta_ready_report_requires_native_live_rrf(tmp_path):
    path = tmp_path / "readiness.json"
    path.write_text(
        json.dumps(
            {
                "schema": "les.smeta.rag-readiness.v1",
                "status": "ready",
                "ready": True,
                "collection": "smeta_v4",
                "live_rrf_ready": False,
                "base_sha256": "base",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="live RRF"):
        read_smeta_ready_report(path, "smeta_v4")


def test_smeta_ready_report_rejects_wrong_generation(tmp_path):
    path = tmp_path / "readiness.json"
    path.write_text(
        json.dumps(
            {
                "schema": "les.smeta.rag-readiness.v1",
                "status": "ready",
                "ready": True,
                "collection": "smeta_v3",
                "live_rrf_ready": True,
                "base_sha256": "base",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="another collection"):
        read_smeta_ready_report(path, "smeta_v4")


def test_smeta_target_rechecks_all_channels_and_fingerprint():
    class Client:
        def collection_exists(self, target):
            return target == "smeta_v4"

        def count(self, _target, *, count_filter=None, exact=True):
            assert exact is True
            return SimpleNamespace(count=12 if count_filter is None else 11)

    report = {"expected_points": 12}
    manifest = {
        "collection": "smeta_v4",
        "status": "passed",
        "expected_points": 12,
        "point_embedding_fingerprint": "fp",
    }

    with pytest.raises(ValueError, match="dense coverage changed"):
        verify_smeta_target(
            Client(),
            target="smeta_v4",
            report=report,
            manifest=manifest,
        )


def test_smeta_activation_publishes_alias_and_active_manifest_together(tmp_path):
    class Client:
        def __init__(self):
            self.aliases = {}

        def collection_exists(self, target):
            return target == "smeta_v4"

        def count(self, _target, *, count_filter=None, exact=True):
            assert exact is True
            return SimpleNamespace(count=12)

        def get_aliases(self):
            return SimpleNamespace(
                aliases=[
                    SimpleNamespace(alias_name=alias, collection_name=target)
                    for alias, target in self.aliases.items()
                ]
            )

        def update_collection_aliases(self, _operations):
            self.aliases["les_smeta_norm_cards"] = "smeta_v4"
            return True

    source = tmp_path / "smeta_v4.manifest.json"
    active = tmp_path / "les_smeta_norm_rag_manifest.json"
    runtime_active = tmp_path / "runtime" / "les_smeta_norm_rag_manifest.json"
    source.write_text(
        json.dumps(
            {
                "schema": "smeta_norm_rag_manifest_v2",
                "collection": "smeta_v4",
                "status": "passed",
                "expected_points": 12,
                "point_embedding_fingerprint": "fp",
            }
        ),
        encoding="utf-8",
    )
    client = Client()

    activate(
        client=client,
        alias="les_smeta_norm_cards",
        target="smeta_v4",
        report={"expected_points": 12},
        manifest_source=source,
        manifest_destinations=[active, runtime_active],
    )

    payload = json.loads(active.read_text(encoding="utf-8"))
    runtime_payload = json.loads(runtime_active.read_text(encoding="utf-8"))
    assert client.aliases == {"les_smeta_norm_cards": "smeta_v4"}
    assert payload["collection"] == "les_smeta_norm_cards"
    assert payload["physical_generation"] == "smeta_v4"
    assert runtime_payload == payload
