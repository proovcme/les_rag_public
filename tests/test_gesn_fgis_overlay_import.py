from __future__ import annotations

from pathlib import Path

from tools import gesn_fgis_overlay_import as overlay


def test_gesn_fgis_overlay_import_deduplicates_codes_and_appends(monkeypatch, tmp_path):
    calls: list[str] = []

    def fake_fetch(code: str, *, timeout: int):
        calls.append(code)
        return [{"code": code}]

    def fake_parse(records):
        code = records[0]["code"]
        return [
            {
                "norm_code": code,
                "norm_name": "Сварка волокон оптического кабеля",
                "norm_unit": "1 стык",
                "kind": "labor",
                "per_unit": 1.0,
                "resource_code": "1-100-73",
                "resource_name": "Средний разряд работы 7,3",
                "resource_unit": "чел.-ч",
                "price": None,
                "base_type": "ГЭСНм",
                "norm_key": f"ГЭСНм:{code}",
                "source_doc": "fixture",
                "source_guid": "fixture",
            }
        ]

    def fake_build(rows, out_path: str | Path, *, append: bool):
        assert append is True
        assert len(rows) == 2
        return {"parquet": str(out_path), "norms": 2, "resources": 2}

    monkeypatch.setattr(overlay, "_fetch_raw", fake_fetch)
    monkeypatch.setattr(overlay, "parse_fgis_json", fake_parse)
    monkeypatch.setattr(overlay, "build_parquet", fake_build)

    stats = overlay.import_overlay(
        ["10-06-058-01", "10-06-058-01", "10-06-060-15"],
        out_path=tmp_path / "gesn2022_v2.parquet",
        rate=0,
    )

    assert calls == ["10-06-058-01", "10-06-060-15"]
    assert stats["codes"] == 2
    assert stats["rows"] == 2
    assert stats["norms"] == 2
