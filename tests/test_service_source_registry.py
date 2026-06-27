from pathlib import Path

import yaml

from proxy.services.service_source_registry import service_source, service_sources


def test_service_sources_report_required_files(tmp_path):
    cfg = {
        "meta": {"version": 1, "title": "test"},
        "sources": [
            {
                "id": "gesn_base",
                "domain": "smeta",
                "label": "ГЭСН",
                "status_if_missing": "blocking",
                "paths": [str(tmp_path / "missing.parquet")],
                "needed_for": ["ЛСР"],
                "accepted_files": ["*.parquet"],
                "operator_hint": "import",
            },
            {
                "id": "smeta_coefficients",
                "domain": "smeta",
                "label": "coeff",
                "status_if_missing": "blocking",
                "paths": [str(tmp_path / "nr_sp.yaml")],
            },
        ],
    }
    (tmp_path / "nr_sp.yaml").write_text("x: 1\n", encoding="utf-8")
    cfg_path = tmp_path / "sources.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    out = service_sources(cfg_path)
    assert out["schema"] == "service_sources_v1"
    assert out["summary"]["missing_blocking"] == 1
    assert out["summary"]["ok"] == 1
    assert service_source("smeta_coefficients", cfg_path)["status"] == "ok"
    gesn = service_source("gesn_base", cfg_path)
    assert gesn["status"] == "missing_blocking"
    assert gesn["accepted_files"] == ["*.parquet"]


def test_canonical_service_sources_include_smeta_and_normcontrol():
    out = service_sources()
    ids = {x["id"] for x in out["sources"]}
    assert {"gesn_base", "fgis_price_base", "normcontrol_spds_rulepack", "normcontrol_spds_rag"} <= ids
    assert out["summary"]["total"] >= 5
