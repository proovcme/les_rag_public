from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from tools.build_smeta_structured_base import build_structured_base
from tools.gesn_import import RESOURCE_FIELDS


def test_windows_smeta_data_path_bypasses_install_junction(tmp_path: Path, monkeypatch):
    import json

    from proxy.smeta_core.base_registry import active_base, runtime_data_path

    monkeypatch.delenv("LES_SMETA_STRUCTURED_BASE", raising=False)
    monkeypatch.delenv("LES_SMETA_BASE_MANIFEST", raising=False)
    monkeypatch.delenv("LES_SMETA_BASE_INTEGRITY", raising=False)
    monkeypatch.delenv("LES_SMETA_BASE_SOURCE", raising=False)
    monkeypatch.delenv("LES_SMETA_PUBLIC_FIXTURE", raising=False)
    monkeypatch.setenv("LES_WINDOWS_STATE_ROOT", str(tmp_path))
    config_path = tmp_path / "active.json"
    config_path.write_text(
        json.dumps(
            {
                "base_path": "data/smeta_base/les_smeta_base.sqlite",
                "manifest_path": "data/smeta_base/les_smeta_base_manifest.json",
                "integrity_path": "data/smeta_base/les_smeta_base_integrity.json",
            }
        ),
        encoding="utf-8",
    )

    assert runtime_data_path("data/smeta_base/les_smeta_base.sqlite") == (
        tmp_path / "data" / "smeta_base" / "les_smeta_base.sqlite"
    )
    active = active_base(config_path)
    assert Path(active["base_path"]) == tmp_path / "data" / "smeta_base" / "les_smeta_base.sqlite"
    assert Path(active["manifest_path"]) == tmp_path / "data" / "smeta_base" / "les_smeta_base_manifest.json"
    assert Path(active["integrity_path"]) == tmp_path / "data" / "smeta_base" / "les_smeta_base_integrity.json"


def _row(**overrides):
    row = {field: None for field in RESOURCE_FIELDS}
    row.update(source_doc="synthetic-fixture", source_guid="fixture-guid")
    row.update(overrides)
    return row


def test_structured_base_excludes_norms_without_machine_metadata(tmp_path: Path):
    source = tmp_path / "gesn2022_unified.parquet"
    out = tmp_path / "les_smeta_base.sqlite"
    manifest_out = tmp_path / "les_smeta_base_manifest.json"
    pd.DataFrame(
        [
            _row(
                norm_code="ГЭСН08-01-001-01",
                norm_key="ГЭСН:08-01-001-01",
                base_type="ГЭСН",
                norm_name="Монтаж оборудования",
                norm_unit="шт",
                work_steps='["Разметка", "Установка"]',
                kind="labor",
                resource_name="Средний разряд работы 4,0",
                resource_unit="чел.-ч",
                per_unit=2.5,
            ),
            _row(
                norm_code="ГЭСН08-01-001-01",
                norm_key="ГЭСН:08-01-001-01",
                base_type="ГЭСН",
                norm_name="Монтаж оборудования",
                norm_unit="шт",
                kind="material",
                resource_code="01.1.01.01-0001",
                resource_name="Материал тестовый",
                resource_unit="шт",
                per_unit=1.0,
                price=12.3,
            ),
            _row(
                norm_code="ГЭСН09-01-001-01",
                norm_key="ГЭСН:09-01-001-01",
                base_type="ГЭСН",
                norm_name="",
                norm_unit="",
                kind="machine",
                resource_code="91.01.01-001",
                resource_name="Кран",
                resource_unit="маш.-ч",
                per_unit=3.0,
            ),
        ],
        columns=list(RESOURCE_FIELDS),
    ).to_parquet(source, index=False)

    manifest = build_structured_base(source=source, out=out, manifest_out=manifest_out)

    assert manifest["output"]["norms"] == 1
    assert manifest["output"]["resources"] == 2
    assert manifest["excluded"]["norms_missing_name_or_unit"] == 1
    assert json.loads(manifest_out.read_text(encoding="utf-8"))["schema"] == "les_smeta_base_v2"
    integrity_path = tmp_path / "les_smeta_base_integrity.json"
    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    assert integrity["schema"] == "les_smeta_base_integrity_v1"
    assert integrity["verdict"] == "passed"
    assert all(check["failures"] == 0 for check in integrity["checks"].values())

    conn = sqlite3.connect(out)
    try:
        assert conn.execute("SELECT count(*) FROM norms").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM resources").fetchone()[0] == 2
        row = conn.execute("SELECT norm_key, norm_id, edition, work_steps FROM norms").fetchone()
        parent = conn.execute("SELECT DISTINCT parent_norm_id FROM resources").fetchone()[0]
    finally:
        conn.close()
    assert row[0] == "ГЭСН:08-01-001-01"
    assert row[1] == "FSNB-2022|ГЭСН|08-01-001-01"
    assert row[2] == "FSNB-2022"
    assert json.loads(row[3]) == ["Разметка", "Установка"]
    assert parent == row[1]


def test_structured_base_refuses_to_replace_canonical_output_below_floor(tmp_path: Path):
    source = tmp_path / "source.parquet"
    out = tmp_path / "base.sqlite"
    out.write_bytes(b"existing-canonical-base")
    pd.DataFrame([
        _row(
            norm_code="ГЭСН08-01-001-01",
            norm_key="ГЭСН:08-01-001-01",
            base_type="ГЭСН",
            norm_name="Монтаж оборудования",
            norm_unit="шт",
            kind="labor",
            resource_name="Рабочий",
            per_unit=1,
        )
    ], columns=list(RESOURCE_FIELDS)).to_parquet(source, index=False)

    with pytest.raises(RuntimeError, match="1 < 40000 norms"):
        build_structured_base(
            source=source,
            out=out,
            manifest_out=tmp_path / "manifest.json",
            minimum_norms=40_000,
        )

    assert out.read_bytes() == b"existing-canonical-base"


def test_gesn_service_prefers_structured_base(tmp_path: Path, monkeypatch):
    from proxy.services import gesn_service as gs

    source = tmp_path / "gesn2022_unified.parquet"
    sqlite_path = tmp_path / "les_smeta_base.sqlite"
    manifest = tmp_path / "manifest.json"
    pd.DataFrame(
        [
            _row(
                norm_code="ГЭСН08-01-001-01",
                norm_key="ГЭСН:08-01-001-01",
                base_type="ГЭСН",
                norm_name="Монтаж оборудования",
                norm_unit="шт",
                kind="labor",
                resource_name="Средний разряд работы 4,0",
                resource_unit="чел.-ч",
                per_unit=2.5,
            ),
            _row(
                norm_code="ГЭСН09-01-001-01",
                norm_key="ГЭСН:09-01-001-01",
                base_type="ГЭСН",
                norm_name="",
                norm_unit="",
                kind="machine",
                resource_name="Кран",
                resource_unit="маш.-ч",
                per_unit=3.0,
            ),
        ],
        columns=list(RESOURCE_FIELDS),
    ).to_parquet(source, index=False)
    build_structured_base(source=source, out=sqlite_path, manifest_out=manifest)

    monkeypatch.setenv("LES_SMETA_STRUCTURED_BASE", str(sqlite_path))
    gs.load_base_norms.cache_clear()
    gs.load_structured_base_norms.cache_clear()
    try:
        norms = gs.load_base_norms()
    finally:
        gs.load_base_norms.cache_clear()
        gs.load_structured_base_norms.cache_clear()

    assert set(norms) == {"ГЭСН:08-01-001-01"}
    norm = norms["ГЭСН:08-01-001-01"]
    assert norm["_source_kind"] == "structured_sqlite"
    assert norm["unit"] == "шт"
    assert norm["resources"][0]["code"] == "1-100-40"


def test_structured_base_defensively_collapses_duplicate_resource_identity(tmp_path: Path):
    source = tmp_path / "source.parquet"
    out = tmp_path / "base.sqlite"
    manifest_out = tmp_path / "manifest.json"
    rows = [
        _row(
            norm_code="ГЭСН08-01-001-01", norm_key="ГЭСН:08-01-001-01", base_type="ГЭСН",
            norm_name="Монтаж оборудования", norm_unit="шт", kind="machine",
            resource_code="91.01.01-001", resource_name="Кран монтажный", resource_unit="маш.-ч",
            per_unit=3.0,
        ),
        _row(
            norm_code="ГЭСН08-01-001-01", norm_key="ГЭСН:08-01-001-01", base_type="ГЭСН",
            norm_name="Монтаж оборудования", norm_unit="шт", kind="machine",
            resource_code="91.01.01-001", resource_name="КРАН  МОНТАЖНЫЙ", resource_unit="маш.-ч",
            per_unit=3.0,
        ),
        _row(
            norm_code="ГЭСН08-01-001-01", norm_key="ГЭСН:08-01-001-01", base_type="ГЭСН",
            norm_name="Монтаж оборудования", norm_unit="шт", kind="material",
            resource_code="01.1.01.01-0001", resource_name="Материал", resource_unit="шт",
            per_unit=1.0,
        ),
    ]
    pd.DataFrame(rows, columns=list(RESOURCE_FIELDS)).to_parquet(source, index=False)

    manifest = build_structured_base(source=source, out=out, manifest_out=manifest_out)

    assert manifest["excluded"]["resource_identity_duplicates_dropped"] == 1
    assert manifest["output"]["resources"] == 2
    conn = sqlite3.connect(out)
    try:
        assert conn.execute("SELECT count(*) FROM resources").fetchone()[0] == 2
    finally:
        conn.close()


def test_structured_base_quarantines_family_mismatch_and_metadata_conflict(tmp_path: Path):
    source = tmp_path / "source.parquet"
    out = tmp_path / "base.sqlite"
    manifest_out = tmp_path / "manifest.json"
    rows = [
        _row(
            norm_code="ГЭСНм08-01-001-01",
            norm_key="ГЭСН:08-01-001-01",
            base_type="ГЭСНм",
            norm_name="Wrong family",
            norm_unit="шт",
            kind="labor",
            resource_name="Рабочий",
            per_unit=1,
        ),
        _row(
            norm_code="ГЭСН08-02-001-01",
            norm_key="ГЭСН:08-02-001-01",
            base_type="ГЭСН",
            norm_name="Название А",
            norm_unit="шт",
            kind="labor",
            resource_name="Рабочий",
            per_unit=1,
        ),
        _row(
            norm_code="ГЭСН08-02-001-01",
            norm_key="ГЭСН:08-02-001-01",
            base_type="ГЭСН",
            norm_name="Название Б",
            norm_unit="шт",
            kind="material",
            resource_name="Материал",
            per_unit=1,
        ),
    ]
    pd.DataFrame(rows, columns=list(RESOURCE_FIELDS)).to_parquet(source, index=False)

    manifest = build_structured_base(source=source, out=out, manifest_out=manifest_out)

    assert manifest["output"]["norms"] == 0
    assert manifest["excluded"]["family_mismatch_rows_quarantined"] == 1
    assert manifest["excluded"]["metadata_conflict_norms"] == 1
    integrity = json.loads((tmp_path / "base_integrity.json").read_text(encoding="utf-8"))
    assert integrity["verdict"] == "failed"
    assert integrity["checks"]["empty_machine_base"]["failures"] == 1
    assert integrity["quarantine"]["family_mismatch_rows"] == 1
    assert integrity["quarantine"]["metadata_conflict_norms"] == 1
