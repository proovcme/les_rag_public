from tools import seed_artel_backend_reports as bulk


def test_select_report_ids_filters_empty_and_applies_limit():
    reports = [
        {"id": "report_003"},
        {"id": ""},
        {"id": "report_002"},
        {"missing": "ignored"},
        {"id": "report_001"},
    ]

    assert bulk.select_report_ids(reports, limit=2) == ["report_003", "report_002"]
    assert bulk.select_report_ids(reports, limit=0) == ["report_003", "report_002", "report_001"]


def test_list_validation_reports_uses_task_filter(monkeypatch):
    calls = []

    def fake_request_json(method, url, *, api_key="", **_kwargs):
        calls.append((method, url, api_key))
        return [{"id": "report_001"}]

    monkeypatch.setattr(bulk.ingest, "request_json", fake_request_json)

    reports = bulk.list_validation_reports("http://artel.local/", task_id="task 0241", api_key="key")

    assert reports == [{"id": "report_001"}]
    assert calls == [("GET", "http://artel.local/api/validation-reports?taskId=task+0241", "key")]


def test_seed_backend_reports_writes_cases_and_syncs(monkeypatch, tmp_path):
    case = {
        "schema_version": "artel.family_learning_case.v1",
        "case_id": "validation_report_001",
        "product": "ARTEL",
        "task": {
            "title": "Шкаф",
            "family_category": "Furniture",
            "family_name": "Шкаф",
            "goal": "Validate family",
        },
        "specification": {
            "types": ["A"],
            "geometry": "See report.",
            "materials": [],
            "parameters": [{"name": "ADSK_Наименование", "value_or_rule": "required", "group": "Identity Data"}],
        },
        "parameter_profile": {"fop_profile": "fop", "required_shared_parameters": ["ADSK_Наименование"]},
        "validation_report": {"status": "warning", "checks": ["warning: ARF"], "known_failures": [], "fixes": []},
        "catalog_card": {
            "display_name": "Шкаф",
            "category": "Furniture",
            "tags": ["revit-family"],
            "search_terms": ["Шкаф", "ARTEL"],
        },
        "acceptance": {"outcome": "warning", "accepted_by_role": "ARTEL validation workflow", "notes": "Smoke"},
    }

    monkeypatch.setattr(bulk, "list_validation_reports", lambda *_args, **_kwargs: [{"id": "report_001"}])
    monkeypatch.setattr(bulk.ingest, "load_learning_case_for_report", lambda **_kwargs: case)
    monkeypatch.setattr(bulk.learning_cases, "sync_artel", lambda *_args, **_kwargs: {"status": "ok"})

    result = bulk.seed_backend_reports(
        artel_url="http://artel.local",
        task_id="task_0241",
        artel_api_key="",
        runtime_root=tmp_path,
        proxy_url="http://les.local",
        les_api_key="",
        limit=0,
        no_sync=False,
        verify_search=False,
        timeout_sec=1,
        poll_sec=1,
        top_k=3,
    )

    target = tmp_path / "RAG_Content" / "ARTEL" / "family_learning_cases" / "validation_report_001.md"
    assert target.exists()
    assert result["reports_seen"] == 1
    assert result["reports_selected"] == 1
    assert result["written"] == [str(target)]
    assert result["skipped"] == []
    assert result["sync"] == {"status": "ok"}
