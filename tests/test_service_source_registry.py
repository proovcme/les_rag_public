from pathlib import Path

import yaml

from proxy.services.service_source_registry import process_service_source, service_source, service_sources


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
    assert gesn["folders"][0]["path"] == str(tmp_path)
    processed = process_service_source("gesn_base", cfg_path)
    assert processed["status"] == "missing_blocking"
    assert "Положи нужные файлы" in processed["message"]


def test_canonical_service_sources_include_smeta_and_normcontrol():
    out = service_sources()
    ids = {x["id"] for x in out["sources"]}
    assert {
        "gesn_base",
        "fgis_price_base",
        "smeta_service_dataset",
        "normcontrol_spds_rulepack",
        "normcontrol_spds_rag",
    } <= ids
    assert out["summary"]["total"] >= 5
    gesn = service_source("gesn_base")
    assert gesn["folders"]
    assert gesn["process_label"]
    assert "tools/" not in str(gesn.get("operator_action", ""))
    smeta_service = service_source("smeta_service_dataset")
    required = smeta_service["required_documents"]
    assert required["schema"] == "service_source_required_documents_v1"
    assert {x["id"] for x in required["items"]} >= {"norms", "prices", "methodology", "forms"}
    processed = process_service_source("smeta_service_dataset")
    assert processed["required_documents"]["summary"]["total"] >= 4
    assert "Play проверил состав" in processed["message"]


def test_service_source_play_reports_required_document_manifest(tmp_path):
    service_root = tmp_path / "SMETA_SERVICE"
    service_root.mkdir()
    (service_root / "gesn_norms.parquet").write_bytes(b"not-real-parquet-but-present")
    (service_root / "kp_raw.pdf").write_bytes(b"%PDF")
    cfg = {
        "meta": {"version": 1, "title": "test"},
        "sources": [
            {
                "id": "smeta_service_dataset",
                "domain": "smeta",
                "label": "SMETA_SERVICE",
                "status_if_missing": "degraded",
                "paths": [str(service_root / "**/*.parquet"), str(service_root / "**/*.pdf")],
                "folders": [str(service_root)],
                "required_documents": [
                    {
                        "id": "norms",
                        "label": "Нормы",
                        "requiredness": "blocking",
                        "preferred_files": ["*.parquet"],
                        "accepted_files": ["*.pdf"],
                        "preferred_paths": [str(service_root / "**/*norm*.parquet")],
                        "raw_paths": [str(service_root / "**/*norm*.pdf")],
                    },
                    {
                        "id": "prices",
                        "label": "Цены",
                        "requiredness": "degraded",
                        "preferred_files": ["*.xlsx"],
                        "accepted_files": ["*.pdf"],
                        "preferred_paths": [str(service_root / "**/*price*.xlsx")],
                        "raw_paths": [str(service_root / "**/*kp*.pdf")],
                    },
                    {
                        "id": "forms",
                        "label": "Формы",
                        "requiredness": "degraded",
                        "preferred_files": ["*.xlsx"],
                        "accepted_files": ["*.md"],
                        "preferred_paths": [str(service_root / "**/*lsr*.xlsx")],
                        "raw_paths": [str(service_root / "**/*form*.md")],
                    },
                ],
            }
        ],
    }
    cfg_path = tmp_path / "sources.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    item = service_source("smeta_service_dataset", cfg_path)
    manifest = item["required_documents"]
    by_id = {row["id"]: row for row in manifest["items"]}
    assert by_id["norms"]["status"] == "ready"
    assert by_id["prices"]["status"] == "partial"
    assert by_id["forms"]["status"] == "missing_degraded"
    assert manifest["summary"]["ready"] == 1
    assert manifest["summary"]["partial"] == 1
    assert manifest["summary"]["missing_degraded"] == 1
    assert item["status"] == "missing_degraded"

    processed = process_service_source("smeta_service_dataset", cfg_path)
    assert processed["status"] == "missing_degraded"
    assert "Готово 1, частично 1, не хватает 1" in processed["message"]
    assert processed["required_documents"]["items"][0]["found_preferred_count"] == 1


def test_present_normative_base_is_quarantined_without_integrity_report(tmp_path):
    base = tmp_path / "base.sqlite"
    manifest = tmp_path / "manifest.json"
    base.write_bytes(b"unverified")
    manifest.write_text('{"source":{"sha256":"source"}}', encoding="utf-8")
    cfg = {
        "meta": {"version": 1, "title": "test"},
        "sources": [
            {
                "id": "gesn_base",
                "domain": "smeta",
                "label": "ГЭСН",
                "status_if_missing": "blocking",
                "paths": [str(base), str(manifest)],
                "structured_base_path": str(base),
                "base_manifest_path": str(manifest),
                "integrity_report": str(tmp_path / "integrity.json"),
                "integrity_required": True,
            }
        ],
    }
    cfg_path = tmp_path / "sources.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    item = service_source("gesn_base", cfg_path)

    assert item["status"] == "quarantined_blocking"
    assert item["integrity"]["trusted_for_pricing"] is False
    assert process_service_source("gesn_base", cfg_path)["ok"] is False
