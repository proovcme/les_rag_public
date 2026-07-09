from __future__ import annotations

from pathlib import Path

from tools import gesn_update_from_fgis as updater


def test_fgis_update_runs_full_machine_base_pipeline(tmp_path: Path, monkeypatch):
    calls: list[str] = []

    def fake_download(**kwargs):
        calls.append("download")
        assert kwargs["out_path"] == tmp_path / "raw.parquet"
        return {"rows": 3, "sborniki": [12]}

    def fake_unify(**kwargs):
        calls.append("unify")
        assert kwargs["legacy"] == tmp_path / "raw.parquet"
        assert kwargs["out"] == tmp_path / "unified.parquet"
        return {"schema": "gesn_unified_audit_v1", "rows": 3, "norm_keys": 2}

    def fake_structured(**kwargs):
        calls.append("structured")
        assert kwargs["source"] == tmp_path / "unified.parquet"
        assert kwargs["out"] == tmp_path / "structured.sqlite"
        return {"schema": "les_smeta_base_v1", "output": {"norms": 2, "resources": 3}}

    def fake_service_rag(out_dir: Path):
        calls.append("service_rag")
        assert out_dir == tmp_path / "SMETA_SERVICE"
        return {"collection_cards": 1, "price_cards": 1}

    monkeypatch.setattr(updater.gesn_bulk_import, "run", fake_download)
    monkeypatch.setattr(updater, "build_unified", fake_unify)
    monkeypatch.setattr(updater, "build_structured_base", fake_structured)
    monkeypatch.setattr(updater.build_smeta_service_rag, "build", fake_service_rag)

    result = updater.run_update(
        all_sborniki=False,
        sbornik=12,
        raw_out=tmp_path / "raw.parquet",
        overlay=tmp_path / "overlay.parquet",
        unified_out=tmp_path / "unified.parquet",
        audit_out=tmp_path / "audit.json",
        structured_out=tmp_path / "structured.sqlite",
        structured_manifest_out=tmp_path / "structured_manifest.json",
        service_rag_out=tmp_path / "SMETA_SERVICE",
        status_out=tmp_path / "status.json",
        rate=0.1,
    )

    assert calls == ["download", "unify", "structured", "service_rag"]
    assert result["status"] == "done"
    assert result["structured"]["schema"] == "les_smeta_base_v1"
    assert result["service_rag"]["collection_cards"] == 1
    assert '"stage": "done"' in (tmp_path / "status.json").read_text(encoding="utf-8")


def test_fgis_update_can_skip_generated_layers(tmp_path: Path, monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(updater.gesn_bulk_import, "run", lambda **_: calls.append("download") or {})
    monkeypatch.setattr(updater, "build_unified", lambda **_: calls.append("unify") or {})
    monkeypatch.setattr(updater, "build_structured_base", lambda **_: calls.append("structured") or {})
    monkeypatch.setattr(updater.build_smeta_service_rag, "build", lambda *_: calls.append("service_rag") or {})

    updater.run_update(
        raw_out=tmp_path / "raw.parquet",
        overlay=tmp_path / "overlay.parquet",
        unified_out=tmp_path / "unified.parquet",
        audit_out=tmp_path / "audit.json",
        status_out=tmp_path / "status.json",
        skip_structured=True,
        skip_service_rag=True,
    )

    assert calls == ["download", "unify"]
