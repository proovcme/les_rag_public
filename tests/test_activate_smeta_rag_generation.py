import json
from types import SimpleNamespace

import pytest

from tools import activate_smeta_rag_generation as activation
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


def test_release_activation_rolls_back_sqlite_when_alias_postcheck_fails(tmp_path):
    class Client:
        def __init__(self):
            self.aliases = {"les_smeta_norm_cards": "old_generation"}

        def collection_exists(self, target):
            return target == "new_generation"

        def count(self, _target, *, count_filter=None, exact=True):
            return SimpleNamespace(count=1)

        def get_aliases(self):
            return SimpleNamespace(
                aliases=[
                    SimpleNamespace(alias_name=alias, collection_name=target)
                    for alias, target in self.aliases.items()
                ]
            )

        def update_collection_aliases(self, operations):
            for operation in operations:
                if hasattr(operation, "delete_alias"):
                    self.aliases.pop(operation.delete_alias.alias_name, None)
                elif hasattr(operation, "create_alias"):
                    value = operation.create_alias
                    self.aliases[value.alias_name] = value.collection_name
            return True

    staged = tmp_path / "staged"
    active = tmp_path / "active"
    staged.mkdir()
    active.mkdir()
    new_base = staged / "base.sqlite"
    old_base = active / "base.sqlite"
    new_base.write_bytes(b"new")
    old_base.write_bytes(b"old")
    rag_source = staged / "rag.json"
    rag_active = active / "rag.json"
    rag_active.write_text('{"old": true}', encoding="utf-8")
    rag_source.write_text(
        json.dumps(
            {
                "schema": "smeta_norm_rag_manifest_v2",
                "collection": "new_generation",
                "status": "passed",
                "expected_points": 1,
                "point_embedding_fingerprint": "fp",
                "base_sha256": "base-sha",
            }
        ),
        encoding="utf-8",
    )
    client = Client()

    with pytest.raises(RuntimeError, match="post activation failed"):
        activation.activate_release(
            client=client,
            alias="les_smeta_norm_cards",
            target="new_generation",
            report={"expected_points": 1, "base_sha256": "base-sha"},
            rag_manifest_source=rag_source,
            rag_manifest_destinations=[rag_active],
            artifact_pairs=[(new_base, old_base)],
            post_activate=lambda: (_ for _ in ()).throw(
                RuntimeError("post activation failed")
            ),
        )

    assert client.aliases == {"les_smeta_norm_cards": "old_generation"}
    assert old_base.read_bytes() == b"old"
    assert json.loads(rag_active.read_text(encoding="utf-8")) == {"old": True}


def test_release_activation_keeps_active_files_when_sqlite_is_locked(
    tmp_path, monkeypatch
):
    staged = tmp_path / "staged"
    active = tmp_path / "active"
    staged.mkdir()
    active.mkdir()
    new_base = staged / "base.sqlite"
    old_base = active / "base.sqlite"
    new_base.write_bytes(b"new")
    old_base.write_bytes(b"old")
    rag_source = staged / "rag.json"
    rag_source.write_text("{}", encoding="utf-8")
    original_replace = activation.Path.replace

    def locked_replace(path, target):
        if path == old_base:
            raise PermissionError("active SQLite is locked")
        return original_replace(path, target)

    monkeypatch.setattr(activation.Path, "replace", locked_replace)

    with pytest.raises(PermissionError, match="locked"):
        activation.activate_release(
            client=object(),
            alias="renamed_catalog",
            target="new_generation",
            report={},
            rag_manifest_source=rag_source,
            rag_manifest_destinations=[active / "rag.json"],
            artifact_pairs=[(new_base, old_base)],
        )

    assert old_base.read_bytes() == b"old"
    assert not any(active.glob("*.rollback"))
    assert not any(active.glob("*.activate"))


def test_release_activation_rolls_back_files_when_qdrant_is_unavailable(tmp_path):
    class UnavailableClient:
        def collection_exists(self, _target):
            raise ConnectionError("qdrant unavailable")

    staged = tmp_path / "staged"
    active = tmp_path / "active"
    staged.mkdir()
    active.mkdir()
    new_base = staged / "base.sqlite"
    old_base = active / "base.sqlite"
    new_base.write_bytes(b"new")
    old_base.write_bytes(b"old")
    rag_source = staged / "rag.json"
    rag_active = active / "rag.json"
    rag_source.write_text("{}", encoding="utf-8")
    rag_active.write_text('{"old": true}', encoding="utf-8")

    with pytest.raises(ConnectionError, match="unavailable"):
        activation.activate_release(
            client=UnavailableClient(),
            alias="renamed_catalog",
            target="new_generation",
            report={},
            rag_manifest_source=rag_source,
            rag_manifest_destinations=[rag_active],
            artifact_pairs=[(new_base, old_base)],
        )

    assert old_base.read_bytes() == b"old"
    assert json.loads(rag_active.read_text(encoding="utf-8")) == {"old": True}
