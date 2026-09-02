from __future__ import annotations

from pathlib import Path

from tools import gesn_update_from_fgis as updater


def test_fgis_update_runs_full_machine_base_pipeline(tmp_path: Path, monkeypatch):
    calls: list[str] = []
    progress_events: list[dict] = []

    def fake_download(**kwargs):
        calls.append("download")
        assert kwargs["out_path"] == tmp_path / "raw.parquet"
        kwargs["progress_callback"](
            {"collection": 12, "collection_index": 1, "collection_total": 1, "current_prefix": "12-01"}
        )
        return {"rows": 3, "sborniki": [12]}

    def fake_unify(**kwargs):
        calls.append("unify")
        assert kwargs["legacy"] == tmp_path / "raw.parquet"
        assert kwargs["out"] == tmp_path / "unified.parquet"
        return {"schema": "gesn_unified_audit_v1", "rows": 3, "norm_keys": 2}

    def fake_structured(**kwargs):
        calls.append("structured")
        assert kwargs["source"] == tmp_path / "unified.parquet"
        assert kwargs["active_base"] == tmp_path / "structured.sqlite"
        return {
            "status": "activated",
            "collection": "smeta_new",
            "structured": {
                "schema": "les_smeta_base_v1",
                "output": {"norms": 2, "resources": 3},
            },
        }

    def fake_service_rag(out_dir: Path):
        calls.append("service_rag")
        assert out_dir == tmp_path / "SMETA_SERVICE"
        return {"collection_cards": 1, "price_cards": 1}

    monkeypatch.setattr(updater.gesn_bulk_import, "run", fake_download)
    monkeypatch.setattr(updater, "build_unified", fake_unify)
    monkeypatch.setattr(updater, "publish_smeta_generation", fake_structured)
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
        progress_callback=progress_events.append,
    )

    assert calls == ["download", "unify", "structured", "service_rag"]
    assert result["status"] == "done"
    assert result["structured"]["schema"] == "les_smeta_base_v1"
    assert result["service_rag"]["collection_cards"] == 1
    assert [event["stage"] for event in progress_events] == [
        "download",
        "download",
        "unify",
        "structured",
        "service_rag",
        "done",
    ]
    assert '"stage": "done"' in (tmp_path / "status.json").read_text(encoding="utf-8")


def test_fgis_update_can_skip_generated_layers(tmp_path: Path, monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(updater.gesn_bulk_import, "run", lambda **_: calls.append("download") or {})
    monkeypatch.setattr(updater, "build_unified", lambda **_: calls.append("unify") or {})
    monkeypatch.setattr(
        updater,
        "publish_smeta_generation",
        lambda **_: calls.append("structured") or {},
    )
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


def test_fgis_update_publishes_structured_base_through_generation_coordinator(
    tmp_path: Path, monkeypatch
):
    calls: list[str] = []
    active_base = tmp_path / "active.sqlite"
    active_base.write_bytes(b"old")

    monkeypatch.setattr(updater.gesn_bulk_import, "run", lambda **_: {})
    monkeypatch.setattr(updater, "build_unified", lambda **_: {})
    monkeypatch.setattr(
        updater,
        "publish_smeta_generation",
        lambda **kwargs: calls.append(str(kwargs["active_base"]))
        or {"status": "activated", "collection": "smeta_new"},
        raising=False,
    )
    monkeypatch.setattr(updater.build_smeta_service_rag, "build", lambda *_: {})

    result = updater.run_update(
        raw_out=tmp_path / "raw.parquet",
        overlay=tmp_path / "overlay.parquet",
        unified_out=tmp_path / "unified.parquet",
        audit_out=tmp_path / "audit.json",
        structured_out=active_base,
        structured_manifest_out=tmp_path / "active-manifest.json",
        service_rag_out=tmp_path / "SMETA_SERVICE",
        status_out=tmp_path / "status.json",
    )

    assert calls == [str(active_base)]
    assert result["structured_generation"]["status"] == "activated"
