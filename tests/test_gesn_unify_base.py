from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tools.gesn_import import RESOURCE_FIELDS
from tools.gesn_unify_base import build_unified


def _row(**overrides):
    row = {field: None for field in RESOURCE_FIELDS}
    row.update(overrides)
    return row


def test_unified_preserves_family_collisions_and_fills_empty_overlay(tmp_path: Path):
    legacy = tmp_path / "gesn2022.parquet"
    overlay = tmp_path / "gesn2022_v2.parquet"
    out = tmp_path / "gesn2022_unified.parquet"
    audit = tmp_path / "gesn2022_unified_audit.json"

    pd.DataFrame([
        {
            "norm_code": "ГЭСН38-01-001-01",
            "norm_name": "Возведение плотин каменно-набросных",
            "norm_unit": "1000 м3",
            "kind": "machine",
            "per_unit": 3.0,
            "resource_code": "91.05.01-017",
            "resource_name": "Краны башенные",
            "resource_unit": "маш.-ч",
            "price": None,
        },
        {
            "norm_code": "38-01-001-01",
            "norm_name": "Листовые конструкции массой свыше 0,5 т",
            "norm_unit": "т",
            "kind": "labor",
            "per_unit": 91.8,
            "resource_code": "",
            "resource_name": "Средний разряд работы 4,0",
            "resource_unit": "чел.-ч",
            "price": None,
        },
    ]).to_parquet(legacy, index=False)
    pd.DataFrame([
        _row(
            norm_code="38-01-001-01",
            norm_name="",
            norm_unit="",
            work_steps='["Наброска камня", "Планировка откосов"]',
            kind="machine",
            per_unit=3.0,
            resource_code="91.05.01-017",
            resource_name="Краны башенные",
            resource_unit="маш.-ч",
            base_type="ГЭСН",
            norm_key="ГЭСН:38-01-001-01",
        ),
        _row(
            norm_code="38-01-001-01",
            norm_name="Листовые конструкции массой свыше 0,5 т",
            norm_unit="т",
            kind="labor",
            per_unit=91.8,
            resource_code="1-100-40",
            resource_name="Средний разряд работы 4,0",
            resource_unit="чел.-ч",
            base_type="ГЭСНм",
            norm_key="ГЭСНм:38-01-001-01",
        ),
    ], columns=list(RESOURCE_FIELDS)).to_parquet(overlay, index=False)

    result = build_unified(legacy=legacy, overlay=overlay, out=out, audit_out=audit)

    assert result["bare_code_collisions"]["count"] == 1
    keys = {variant["norm_key"] for variant in result["bare_code_collisions"]["examples"][0]["variants"]}
    assert keys == {"ГЭСН:38-01-001-01", "ГЭСНм:38-01-001-01"}

    df = pd.read_parquet(out)
    by_key = {row.norm_key: row for row in df.itertuples()}
    assert by_key["ГЭСН:38-01-001-01"].norm_name == "Возведение плотин каменно-набросных"
    assert by_key["ГЭСН:38-01-001-01"].norm_unit == "1000 м3"
    assert "Наброска камня" in by_key["ГЭСН:38-01-001-01"].work_steps
    assert by_key["ГЭСНм:38-01-001-01"].norm_name == "Листовые конструкции массой свыше 0,5 т"
    assert "Средний разряд работы 4,0" not in set(df[df["norm_key"] == "ГЭСН:38-01-001-01"]["resource_name"])
    assert "Средний разряд работы 4,0" in set(df[df["norm_key"] == "ГЭСНм:38-01-001-01"]["resource_name"])


def test_gesn_service_prefers_unified_default(tmp_path: Path, monkeypatch):
    from proxy.services import gesn_service as gs

    monkeypatch.setenv("LES_SMETA_STRUCTURED_BASE", str(tmp_path / "missing.sqlite"))
    legacy = tmp_path / "legacy.parquet"
    overlay = tmp_path / "overlay.parquet"
    unified = tmp_path / "unified.parquet"
    pd.DataFrame([_row(norm_code="ГЭСН01-01-001-01", norm_key="ГЭСН:01-01-001-01", base_type="ГЭСН")]).to_parquet(
        legacy,
        index=False,
    )
    pd.DataFrame([_row(norm_code="ГЭСН02-01-001-01", norm_key="ГЭСН:02-01-001-01", base_type="ГЭСН")]).to_parquet(
        overlay,
        index=False,
    )
    pd.DataFrame([_row(norm_code="ГЭСН03-01-001-01", norm_key="ГЭСН:03-01-001-01", base_type="ГЭСН")]).to_parquet(
        unified,
        index=False,
    )

    monkeypatch.setattr(gs, "DEFAULT_BASE_PATH", legacy)
    monkeypatch.setattr(gs, "DEFAULT_BASE_V2_PATH", overlay)
    monkeypatch.setattr(gs, "DEFAULT_UNIFIED_BASE_PATH", unified)
    gs.load_base_norms.cache_clear()
    gs.load_structured_base_norms.cache_clear()

    norms = gs.load_base_norms()
    assert set(norms) == {"ГЭСН:03-01-001-01"}


def test_unified_collapses_same_resource_code_despite_display_name_variants(tmp_path: Path):
    legacy = tmp_path / "legacy.parquet"
    overlay = tmp_path / "overlay.parquet"
    out = tmp_path / "unified.parquet"
    audit = tmp_path / "audit.json"
    rows = [
        _row(
            norm_code="ГЭСН01-01-001-01", norm_key="ГЭСН:01-01-001-01", base_type="ГЭСН",
            norm_name="Разработка грунта", norm_unit="100 м3", kind="machine",
            resource_code="91.05.01-017", resource_name="Кран башенный", resource_unit="маш.-ч",
            per_unit=3.0,
        ),
        _row(
            norm_code="ГЭСН01-01-001-01", norm_key="ГЭСН:01-01-001-01", base_type="ГЭСН",
            norm_name="Разработка грунта", norm_unit="100 м3", kind="machine",
            resource_code="91.05.01-017", resource_name="КРАН  БАШЕННЫЙ", resource_unit="маш.-ч",
            per_unit=3.0,
        ),
    ]
    pd.DataFrame([rows[0]], columns=list(RESOURCE_FIELDS)).to_parquet(legacy, index=False)
    pd.DataFrame([rows[1]], columns=list(RESOURCE_FIELDS)).to_parquet(overlay, index=False)

    result = build_unified(legacy=legacy, overlay=overlay, out=out, audit_out=audit)

    assert result["resource_identity_duplicates_dropped"] == 1
    df = pd.read_parquet(out)
    assert len(df) == 1
    assert df.iloc[0]["resource_name"] == "КРАН  БАШЕННЫЙ"


def test_untyped_bare_resource_without_metadata_is_quarantined_not_defaulted_to_gesn(tmp_path: Path):
    legacy = tmp_path / "legacy.parquet"
    overlay = tmp_path / "overlay.parquet"
    out = tmp_path / "unified.parquet"
    audit = tmp_path / "audit.json"
    pd.DataFrame(
        [
            {
                "norm_code": "01-01-001-02",
                "norm_name": "",
                "norm_unit": "",
                "kind": "machine",
                "resource_code": "91.01.01-001",
                "resource_name": "Экскаватор",
                "resource_unit": "маш.-ч",
                "per_unit": 3.0,
            }
        ]
    ).to_parquet(legacy, index=False)
    pd.DataFrame(
        [
            _row(
                norm_code="01-01-001-02",
                norm_key="ГЭСНм:01-01-001-02",
                base_type="ГЭСНм",
                norm_name="Монтаж оборудования",
                norm_unit="шт",
                kind="labor",
                resource_name="Рабочий",
                resource_unit="чел.-ч",
                per_unit=1.0,
            )
        ],
        columns=list(RESOURCE_FIELDS),
    ).to_parquet(overlay, index=False)

    result = build_unified(legacy=legacy, overlay=overlay, out=out, audit_out=audit)

    df = pd.read_parquet(out)
    assert set(df["norm_key"]) == {"ГЭСНм:01-01-001-02"}
    assert "Экскаватор" not in set(df["resource_name"])
    assert result["untyped_rows_quarantined"]["count"] == 1
    assert result["identity_source_counts"] == {"provided": 1}


def test_unify_refuses_to_replace_canonical_source_below_floor(tmp_path: Path):
    legacy = tmp_path / "legacy.parquet"
    out = tmp_path / "unified.parquet"
    out.write_bytes(b"existing-canonical-source")
    pd.DataFrame([
        _row(
            norm_code="ГЭСН01-01-001-01",
            norm_key="ГЭСН:01-01-001-01",
            base_type="ГЭСН",
            norm_name="Работа",
            norm_unit="шт",
            kind="labor",
            resource_name="Рабочий",
            per_unit=1,
        )
    ], columns=list(RESOURCE_FIELDS)).to_parquet(legacy, index=False)

    with pytest.raises(RuntimeError, match="1 < 40000 norms"):
        build_unified(
            legacy=legacy,
            overlay=tmp_path / "missing.parquet",
            out=out,
            audit_out=tmp_path / "audit.json",
            minimum_norms=40_000,
        )

    assert out.read_bytes() == b"existing-canonical-source"
