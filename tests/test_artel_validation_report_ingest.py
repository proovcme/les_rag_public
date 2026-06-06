import os

from tools import ingest_artel_validation_report as ingest


def test_normalize_addin_validation_report_payload():
    payload = ingest.normalize_validation_report(
        {
            "schema": "artel.revit_family_validation_report.v1",
            "status": "fail",
            "summary": "Missing shared parameter.",
            "family": {"family_name": "Шкаф управления"},
            "issues": [
                {
                    "severity": "error",
                    "code": "ARF-FOP-001",
                    "title": "Missing required shared parameter",
                    "description": "ADSK_Наименование is absent.",
                    "revitElementId": "123",
                    "suggestedFix": "Load approved FOP parameter.",
                }
            ],
            "actions": [
                {
                    "type": "flex",
                    "target": "Шкаф управления",
                    "status": "completed",
                    "message": "Types regenerated.",
                }
            ],
        }
    )

    assert payload["status"] == "fail"
    assert payload["summary"] == "Missing shared parameter."
    assert payload["issues"] == [
        {
            "severity": "error",
            "code": "ARF-FOP-001",
            "title": "Missing required shared parameter",
            "description": "ADSK_Наименование is absent.",
            "revitElementId": "123",
            "suggestedFix": "Load approved FOP parameter.",
        }
    ]
    assert payload["actions"][0]["type"] == "flex"


def test_normalize_report_derives_warning_status_and_accepts_snake_case():
    payload = ingest.normalize_validation_report(
        {
            "validation_report": {
                "issues": [
                    {
                        "level": "warn",
                        "id": "ARF-LOAD-000",
                        "name": "Load test not executed",
                        "message": "Scratch load test disabled.",
                        "revit_element_id": 456,
                        "suggested_fix": "Set ARTEL_RUN_LOAD_TEST=true.",
                    }
                ],
                "validation_actions": {"kind": "load", "name": "Door", "state": "skipped"},
            }
        }
    )

    assert payload["status"] == "warning"
    assert payload["issues"][0]["severity"] == "warning"
    assert payload["issues"][0]["revitElementId"] == "456"
    assert payload["issues"][0]["suggestedFix"] == "Set ARTEL_RUN_LOAD_TEST=true."
    assert payload["actions"][0]["type"] == "load"
    assert payload["actions"][0]["target"] == "Door"


def test_normalize_empty_report_defaults_to_pass_payload():
    payload = ingest.normalize_validation_report({"family": {"name": "Generic family"}})

    assert payload["status"] == "pass"
    assert payload["summary"] == "Generic family: validation pass; issues=0; actions=0."
    assert payload["issues"] == []
    assert payload["actions"] == []


def test_resolve_report_path_picks_newest_glob_match(tmp_path):
    old_report = tmp_path / "validation_old.json"
    new_report = tmp_path / "validation_new.json"
    old_report.write_text("{}", encoding="utf-8")
    new_report.write_text("{}", encoding="utf-8")
    os.utime(old_report, (1, 1))
    os.utime(new_report, (2, 2))

    assert ingest.resolve_report_path(str(tmp_path / "validation_*.json")) == new_report


def test_attach_projection_metadata_marks_revit_addin_report(tmp_path):
    report = tmp_path / "validation_001.json"
    case = {"case_id": "case_001", "projection_metadata": {"existing": "kept"}}

    enriched = ingest.attach_projection_metadata(
        case,
        report_path=report,
        raw_report={"schema": "artel.revit_family_validation_report.v1"},
    )

    assert enriched["projection_metadata"] == {
        "existing": "kept",
        "projection_source": "revit_addin_validation_report",
        "validation_report_path": str(report),
        "validation_report_schema": "artel.revit_family_validation_report.v1",
    }
    assert "projection_metadata" not in case or case["projection_metadata"] == {"existing": "kept"}
