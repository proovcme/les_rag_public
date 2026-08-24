from __future__ import annotations

import sqlite3

from backend.qdrant_adapter import MetaDB
from proxy.services.system_dataset_service import (
    dataset_identity,
    ensure_system_datasets,
    module_dataset_ids,
    system_dataset_spec,
)


def test_smeta_service_is_module_owned_system_dataset():
    spec = system_dataset_spec("SMETA_SERVICE_Index")
    assert spec is not None
    assert spec.module_id == "smeta"
    assert dataset_identity("SMETA_SERVICE_Index") == ("system", "smeta")
    assert dataset_identity("PRICE_SERVICE_Index") == ("system", "smeta")
    assert dataset_identity("NORMATIVE_SERVICE_Index") == ("system", "normcontrol")


def test_smeta_norms_are_an_explicit_ordinary_rag_dataset():
    spec = system_dataset_spec("SMETA_NORMS_Index")

    assert spec is not None
    assert spec.module_id == "smeta"
    assert spec.source_role == "normative_reference"
    assert spec.display_name == "Сметные нормы"


def test_artel_index_is_owned_by_separate_artel_module():
    spec = system_dataset_spec("ARTEL_Index")
    assert spec is not None
    assert spec.module_id == "artel"
    assert dataset_identity("ARTEL_Index") == ("system", "artel")


def test_les_bootstrap_does_not_provision_external_artel_dataset(tmp_path):
    db = MetaDB(str(tmp_path / "meta.db"))
    db.ensure_system_datasets()
    assert "ARTEL_Index" not in {item.name for item in db.list_datasets()}


def test_gesn_projection_is_system_but_project_table_is_user():
    assert dataset_identity("SMETA_RU_NORM_FSNB2022_Index") == ("system", "smeta")
    assert dataset_identity("GESN_NORMS_2022_PDF") == ("system", "smeta")
    assert dataset_identity("TABLE_SMETA_Index") == ("user", "")


def test_metadb_persists_dataset_identity(tmp_path):
    db = MetaDB(str(tmp_path / "meta.db"))
    system_id = db.create_dataset("SMETA_SERVICE_Index")
    user_id = db.create_dataset("My project")
    by_id = {item.id: item for item in db.list_datasets()}
    assert by_id[system_id].dataset_scope == "system"
    assert by_id[system_id].module_id == "smeta"
    assert by_id[user_id].dataset_scope == "user"
    assert by_id[user_id].module_id == ""
    assert system_id in module_dataset_ids("smeta", db_path=str(tmp_path / "meta.db"))


def test_system_dataset_reclaims_its_stable_id_from_legacy_name(tmp_path):
    db_path = tmp_path / "meta.db"
    db = MetaDB(str(db_path))
    db.ensure_system_datasets()
    dataset_id = db.create_dataset("SMETA_NORMS_Index")
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE datasets SET name=? WHERE id=?", ("legacy-smeta-norms", dataset_id))
        ensure_system_datasets(conn)
        row = conn.execute(
            "SELECT name, dataset_scope, module_id FROM datasets WHERE id=?",
            (dataset_id,),
        ).fetchone()

    assert row == ("SMETA_NORMS_Index", "system", "smeta")
