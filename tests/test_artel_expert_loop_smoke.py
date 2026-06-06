import subprocess

from tools import smoke_artel_expert_loop as smoke


def test_health_check_requires_all_artel_doc_types(monkeypatch):
    def fake_request(method, url, *, payload=None, timeout=30.0):
        return {
            "status": "ok",
            "rag": {
                "status": "ready",
                "totals": {"files": 67, "pending_files": 0, "error_files": 0},
                "qdrant": {"ok": True, "points_match_sqlite_chunks": True},
                "by_doc_type": {
                    "FAMILY_GUIDE": {},
                    "FOP_PROFILE": {},
                    "REVIT_MODEL_GUIDE": {},
                    "REVIT_API_REFERENCE": {},
                    "REVIT_API_SYMBOL_MAP": {},
                    "REVIT_API_SDK_DOC": {},
                    "LEARNING_CASE": {},
                },
            },
        }

    monkeypatch.setattr(smoke, "request_json", fake_request)

    result = smoke.health_check("http://127.0.0.1:8050", 3)

    assert result["ok"] is True
    assert result["missing_doc_types"] == []


def test_health_check_reports_missing_doc_type(monkeypatch):
    def fake_request(method, url, *, payload=None, timeout=30.0):
        return {
            "status": "ok",
            "rag": {
                "status": "ready",
                "totals": {"files": 1, "pending_files": 0, "error_files": 0},
                "qdrant": {"ok": True, "points_match_sqlite_chunks": True},
                "by_doc_type": {"FOP_PROFILE": {}},
            },
        }

    monkeypatch.setattr(smoke, "request_json", fake_request)

    result = smoke.health_check("http://127.0.0.1:8050", 3)

    assert result["ok"] is False
    assert "REVIT_API_SDK_DOC" in result["missing_doc_types"]


def test_search_case_requires_expected_doc_type(monkeypatch):
    def fake_request(method, url, *, payload=None, timeout=30.0):
        assert method == "POST"
        assert payload["dataset_filter"] == "ARTEL"
        return {
            "count": 1,
            "chunks": [{"doc_type": "REVIT_API_SDK_DOC", "doc_name": "sdk.md", "score": 0.91}],
            "retrieval_trace": {"quality_status": "good"},
        }

    monkeypatch.setattr(smoke, "request_json", fake_request)

    result = smoke.search_case(
        "http://127.0.0.1:8050",
        {"name": "sdk", "query": "FamilyManager", "expected_doc_type": "REVIT_API_SDK_DOC"},
        timeout=3,
        top_k=5,
    )

    assert result["ok"] is True
    assert result["doc_types"] == ["REVIT_API_SDK_DOC"]
    assert result["quality"] == "good"


def test_run_legion_check_accepts_locked_for_readiness(monkeypatch):
    def fake_run(command, *, timeout):
        return subprocess.CompletedProcess(command, 2, stdout='{"status":"locked"}', stderr="")

    monkeypatch.setattr(smoke, "run_command", fake_run)

    args = type("Args", (), {"artel_health_timeout_sec": 20, "legion_timeout_sec": 60})()
    result = smoke.run_legion_check(args, backend_only=False)

    assert result["ok"] is True
    assert result["status"] == "locked"


def test_run_legion_check_requires_zero_for_backend_only(monkeypatch):
    def fake_run(command, *, timeout):
        return subprocess.CompletedProcess(command, 2, stdout='{"status":"locked"}', stderr="")

    monkeypatch.setattr(smoke, "run_command", fake_run)

    args = type("Args", (), {"artel_health_timeout_sec": 20, "legion_timeout_sec": 60})()
    result = smoke.run_legion_check(args, backend_only=True)

    assert result["ok"] is False
